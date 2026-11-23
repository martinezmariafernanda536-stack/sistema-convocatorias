"""Ejecuciones largas (validar fuentes, mapeo, búsqueda con Gemini) en segundo plano, en el servidor.

Siguen aunque la persona cierre la pestaña, se le apague el computador o se le cierre la sesión.
Hay una sola ejecución a la vez para todo el sistema. El avance se guarda en la base mientras corre.
"""
import json
import logging
import os
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CFG = "configuracion_mapeo_becas.xlsx"
REGISTRO = "tarea_actual.json"
# El estado vive fuera del módulo: si Streamlit vuelve a cargar los archivos (por ejemplo, tras traer cambios de GitHub),
# el módulo se recarga pero la búsqueda que ya corre en su hilo sigue siendo la misma y no se lanza otra encima.
import builtins as _b  # noqa: E402
_ESTADO = _b.__dict__.setdefault("_tareas_convocatorias", {"actual": None, "candado": threading.Lock()})
_candado = _ESTADO["candado"]


class Tarea:
    def __init__(self, comando, etiqueta, usuario, extra=(), reanudada=False):
        self.comando, self.etiqueta, self.usuario = comando, etiqueta, usuario
        self.extra, self.reanudada = list(extra), reanudada
        self.inicio, self.fin = time.time(), None
        self.estado = "En curso"
        self.lineas = []
        self.hilo = None

    def resumen(self):
        return {"comando": self.comando, "etiqueta": self.etiqueta, "usuario": self.usuario, "estado": self.estado,
                "inicio": datetime.fromtimestamp(self.inicio).strftime("%Y-%m-%d %H:%M"),
                "fin": datetime.fromtimestamp(self.fin).strftime("%Y-%m-%d %H:%M") if self.fin else "",
                "extra": self.extra, "reanudada": self.reanudada, "log": self.lineas[-80:]}

    def minutos(self):
        return int(((self.fin or time.time()) - self.inicio) // 60)


class _AlRegistro(logging.Handler):
    def __init__(self, tarea):
        super().__init__()
        self.tarea = tarea

    def emit(self, record):
        self.tarea.lineas.append(f"{datetime.now():%H:%M} {record.getMessage()}")
        del self.tarea.lineas[:-400]


def actual():
    return _ESTADO["actual"]


def en_curso():
    t = _ESTADO["actual"]
    if t is not None and t.estado == "En curso" and t.hilo is not None and t.hilo.is_alive():
        return True
    # red de seguridad: cualquier hilo de búsqueda vivo en el servidor cuenta como «en curso»
    return any(h.name.startswith("tarea-") and h.is_alive() for h in threading.enumerate())


def interrumpida(almacen):
    """Si el servidor se reinició a mitad de una ejecución, la última quedó registrada como 'En curso'."""
    if en_curso():
        return None
    try:
        reg = json.loads(almacen.leer_archivo(REGISTRO) or b"{}")
    except ValueError:
        return None
    return reg if reg.get("estado") == "En curso" else None


REANUDABLES = ("mapear", "descubrir", "completar-pendientes")


def reanudar_si_se_corto(almacen, config=None):
    """Si el servidor se reinició a mitad de una búsqueda (por ejemplo, al subir archivos a GitHub), la vuelve a lanzar sola
    una vez, con las mismas opciones. No repite trabajo: lo que ya llegó a la bandeja o ya se leyó queda registrado.
    Devuelve el registro de la búsqueda cortada si la reanudó."""
    reg = interrumpida(almacen)
    if not reg or reg.get("reanudada") or reg.get("comando") not in REANUDABLES:
        return None
    try:
        hace = (datetime.now() - datetime.strptime(reg.get("inicio", ""), "%Y-%m-%d %H:%M")).total_seconds() / 3600
    except ValueError:
        return None
    if hace > 6:  # muy antigua: mejor que la persona decida
        return None
    if config is None:
        config = almacen.leer_archivo(CFG) or (RAIZ / "config" / CFG).read_bytes()
        try:
            from motor.config import completar_con_paquete
            config = completar_con_paquete(config, RAIZ / "config" / CFG)
        except Exception:  # noqa: BLE001
            pass
    etiqueta = str(reg.get("etiqueta", "Búsqueda")).replace(" (reanudada)", "") + " (reanudada)"
    if iniciar(almacen, reg["comando"], etiqueta, reg.get("extra", []), reg.get("usuario", ""), config, reanudada=True):
        return reg
    return None


def _guardar_registro(almacen, tarea):
    try:
        almacen.guardar_archivo(REGISTRO, json.dumps(tarea.resumen(), ensure_ascii=False).encode("utf-8"))
    except Exception:  # noqa: BLE001
        pass


def iniciar(almacen, comando, etiqueta, extra, usuario, config, reanudada=False):
    """Arranca la ejecución en segundo plano. Devuelve False si ya hay una en curso."""
    with _candado:
        if en_curso():
            return False
        tarea = Tarea(comando, etiqueta, usuario, extra, reanudada)
        _ESTADO["actual"] = tarea
        tarea.hilo = threading.Thread(target=_correr, args=(almacen, tarea, list(extra), config), daemon=True,
                                      name=f"tarea-{comando}")
        tarea.hilo.start()
        return True


MODULOS = ["mapeo", "motor.extraer", "motor.externo", "motor.reglas", "motor.salidas", "motor.radar", "calidad.reglas", "calidad.entrada",
           "bandeja.flujo", "tareas"]


def modulos_desactualizados():
    """Módulos que el servidor tiene cargados en una versión anterior a la de los archivos (pasa cuando se suben archivos
    nuevos sin reiniciar la app): el archivo define funciones que el módulo en memoria no tiene."""
    import importlib
    import re as _re
    import sys
    viejos = []
    for nombre in MODULOS:
        m = sys.modules.get(nombre)
        if m is None:
            try:
                m = importlib.import_module(nombre)
            except Exception:  # noqa: BLE001
                continue
        try:
            fuente = Path(m.__file__).read_text(encoding="utf-8")
        except (OSError, TypeError):
            continue
        definidas = set(_re.findall(r"^(?:def|class) (\w+)", fuente, _re.M)) | set(_re.findall(r"^([A-Z_]{3,}) = ", fuente, _re.M))
        if any(not hasattr(m, n) for n in definidas):
            viejos.append(nombre)
    return viejos


def detener():
    import mapeo as programa
    if en_curso():
        programa.DETENER.set()
        if _ESTADO["actual"] is not None:
            _ESTADO["actual"].lineas.append(f"{datetime.now():%H:%M} Deteniendo… se termina lo que está en curso y se guarda lo avanzado.")


def _correr(almacen, tarea, extra, config):
    import mapeo as programa
    tmp = Path(tempfile.mkdtemp())
    (tmp / CFG).write_bytes(config)
    hist = almacen.leer_archivo("historial_mapeo.json")
    if hist:
        (tmp / "historial.json").write_bytes(hist)
    os.environ["MAPEO_HISTORIAL"] = str(tmp / "historial.json")

    ultimo = {"historial": 0.0}

    def al_guardar(tipo, ruta):
        if tipo == "config":
            almacen.guardar_archivo(CFG, Path(ruta).read_bytes())
        elif tipo == "historial" and Path(ruta).exists():
            # el historial se guarda en el servidor después de cada fuente y de cada consulta, pero subirlo a GitHub
            # cada vez (varios cientos por búsqueda) hace lenta la búsqueda y puede chocar con los límites de GitHub:
            # se sube como mucho cada 2 minutos, y siempre al terminar
            if time.time() - ultimo["historial"] >= 120:
                almacen.guardar_archivo("historial_mapeo.json", Path(ruta).read_bytes())
                ultimo["historial"] = time.time()

    programa.ALMACEN, programa.AL_GUARDAR = almacen, al_guardar
    programa.DETENER.clear()
    log = logging.getLogger("mapeo")
    manejador = _AlRegistro(tarea)
    log.addHandler(manejador)
    log.setLevel(logging.INFO)
    _guardar_registro(almacen, tarea)
    resultado = None
    try:
        try:
            import sys as _sys
            _sys.path.insert(0, str(RAIZ / "herramientas"))
            import manifiesto
            version, distintos = manifiesto.revisar()
        except Exception:  # noqa: BLE001
            version, distintos = None, []
        if distintos:
            raise RuntimeError(f"En GitHub quedaron archivos de paquetes distintos (paquete {version}); no coinciden: "
                               + ", ".join(distintos[:12]) + ". Sube de nuevo el contenido completo del último paquete y "
                               "reinicia la app. La búsqueda no se lanzó para no dejarla a medias.")
        viejos = modulos_desactualizados()
        if viejos:
            raise RuntimeError("El servidor sigue usando una versión anterior del programa (" + ", ".join(viejos) + "). "
                               "Reinicia la aplicación: en share.streamlit.io, «Manage app» → menú ⋮ → «Reboot app».")
        resultado = programa.main([tarea.comando, "--config", str(tmp / CFG), *extra])
        tarea.estado = "Detenida" if programa.DETENER.is_set() else "Terminada"
    except SystemExit as e:
        tarea.estado = "Detenida" if programa.DETENER.is_set() else "Error"
        tarea.lineas.append(f"{'Detenida' if programa.DETENER.is_set() else 'Error'}: {e}")
    except Exception as e:  # noqa: BLE001 - se muestra el error en la página
        tarea.estado = "Error"
        tarea.lineas.append(f"Error: {e}")
        tarea.lineas.extend(traceback.format_exc().splitlines()[-6:])
    finally:
        log.removeHandler(manejador)
        programa.ALMACEN = programa.AL_GUARDAR = None
        programa.DETENER.clear()
        tarea.fin = time.time()
        try:
            if (tmp / "historial.json").exists():
                almacen.guardar_archivo("historial_mapeo.json", (tmp / "historial.json").read_bytes())
            if tarea.comando == "validar-fuentes":
                almacen.guardar_archivo(CFG, (tmp / CFG).read_bytes())
            if resultado and Path(str(resultado)).exists():
                destino = {"mapear": "ultimo_mapeo.xlsx", "descubrir": "ultimo_descubrimiento.xlsx",
                           "buscar-externo": "ultima_busqueda_externa.xlsx"}.get(tarea.comando)
                if destino:
                    almacen.guardar_archivo(destino, Path(resultado).read_bytes())
            almacen.guardar_archivo(f"ultimo_{tarea.comando}.json",
                                    json.dumps(tarea.resumen() | {"fecha": tarea.resumen()["inicio"]}, ensure_ascii=False).encode("utf-8"))
        finally:
            _guardar_registro(almacen, tarea)
