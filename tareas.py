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
_candado = threading.Lock()
_actual = None


class Tarea:
    def __init__(self, comando, etiqueta, usuario):
        self.comando, self.etiqueta, self.usuario = comando, etiqueta, usuario
        self.inicio, self.fin = time.time(), None
        self.estado = "En curso"
        self.lineas = []
        self.hilo = None

    def resumen(self):
        return {"comando": self.comando, "etiqueta": self.etiqueta, "usuario": self.usuario, "estado": self.estado,
                "inicio": datetime.fromtimestamp(self.inicio).strftime("%Y-%m-%d %H:%M"),
                "fin": datetime.fromtimestamp(self.fin).strftime("%Y-%m-%d %H:%M") if self.fin else "",
                "log": self.lineas[-80:]}

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
    return _actual


def en_curso():
    return _actual is not None and _actual.estado == "En curso" and _actual.hilo is not None and _actual.hilo.is_alive()


def interrumpida(almacen):
    """Si el servidor se reinició a mitad de una ejecución, la última quedó registrada como 'En curso'."""
    if en_curso():
        return None
    try:
        reg = json.loads(almacen.leer_archivo(REGISTRO) or b"{}")
    except ValueError:
        return None
    return reg if reg.get("estado") == "En curso" else None


def _guardar_registro(almacen, tarea):
    try:
        almacen.guardar_archivo(REGISTRO, json.dumps(tarea.resumen(), ensure_ascii=False).encode("utf-8"))
    except Exception:  # noqa: BLE001
        pass


def iniciar(almacen, comando, etiqueta, extra, usuario, config):
    """Arranca la ejecución en segundo plano. Devuelve False si ya hay una en curso."""
    global _actual
    with _candado:
        if en_curso():
            return False
        tarea = Tarea(comando, etiqueta, usuario)
        _actual = tarea
        tarea.hilo = threading.Thread(target=_correr, args=(almacen, tarea, list(extra), config), daemon=True,
                                      name=f"tarea-{comando}")
        tarea.hilo.start()
        return True


def detener():
    import mapeo as programa
    if en_curso():
        programa.DETENER.set()
        _actual.lineas.append(f"{datetime.now():%H:%M} Deteniendo… se termina lo que está en curso y se guarda lo avanzado.")


def _correr(almacen, tarea, extra, config):
    import mapeo as programa
    tmp = Path(tempfile.mkdtemp())
    (tmp / CFG).write_bytes(config)
    hist = almacen.leer_archivo("historial_mapeo.json")
    if hist:
        (tmp / "historial.json").write_bytes(hist)
    os.environ["MAPEO_HISTORIAL"] = str(tmp / "historial.json")

    def al_guardar(tipo, ruta):
        if tipo == "config":
            almacen.guardar_archivo(CFG, Path(ruta).read_bytes())
        elif tipo == "historial" and Path(ruta).exists():
            almacen.guardar_archivo("historial_mapeo.json", Path(ruta).read_bytes())

    programa.ALMACEN, programa.AL_GUARDAR = almacen, al_guardar
    programa.DETENER.clear()
    log = logging.getLogger("mapeo")
    manejador = _AlRegistro(tarea)
    log.addHandler(manejador)
    log.setLevel(logging.INFO)
    _guardar_registro(almacen, tarea)
    resultado = None
    try:
        resultado = programa.main([tarea.comando, "--config", str(tmp / CFG), *extra])
        tarea.estado = "Detenida" if programa.DETENER.is_set() else "Terminada"
    except SystemExit as e:
        tarea.estado = "Detenida"
        tarea.lineas.append(f"Detenida: {e}")
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
                destino = {"mapear": "ultimo_mapeo.xlsx", "buscar-externo": "ultima_busqueda_externa.xlsx"}.get(tarea.comando)
                if destino:
                    almacen.guardar_archivo(destino, Path(resultado).read_bytes())
            almacen.guardar_archivo(f"ultimo_{tarea.comando}.json",
                                    json.dumps(tarea.resumen() | {"fecha": tarea.resumen()["inicio"]}, ensure_ascii=False).encode("utf-8"))
        finally:
            _guardar_registro(almacen, tarea)
