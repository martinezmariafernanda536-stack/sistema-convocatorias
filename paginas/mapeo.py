"""Página: mapeo automático de convocatorias internacionales (becas, subvenciones, cooperación técnica y premios)."""
import json
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import tareas
import ui

RAIZ = Path(__file__).resolve().parents[1]
CFG = "configuracion_mapeo_becas.xlsx"
st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()
A = ui.almacen()

st.title("Buscar convocatorias")
st.caption("El sistema revisa los sitios oficiales de los oferentes y trae becas, subvenciones, cooperación técnica y premios "
           "abiertos a Colombia. Lo que encuentra llega a **Revisar convocatorias**; nunca entra directo a la base.")


def config_bytes():
    """La configuración guardada en la app, con las hojas y parámetros nuevos del paquete (se guardan una sola vez)."""
    guardada = A.leer_archivo(CFG)
    if not guardada:
        return (RAIZ / "config" / CFG).read_bytes()
    if st.session_state.get("_cfg_revisada") != len(guardada):
        from motor import config as _cfgmod
        try:
            completa = _cfgmod.completar_con_paquete(guardada, RAIZ / "config" / CFG)
        except Exception:  # noqa: BLE001 - si algo falla se usa la guardada tal cual
            completa = guardada
        if completa != guardada:
            A.guardar_archivo(CFG, completa)
            guardada = completa
        st.session_state["_cfg_revisada"] = len(guardada)
    return guardada


def ejecutar(comando, etiqueta, extra=()):
    """Arranca la ejecución en el servidor, en segundo plano: sigue aunque se cierre la pestaña."""
    if tareas.iniciar(A, comando, etiqueta, extra, YO["nombre"], config_bytes()):
        st.toast(f"{etiqueta}: empezó en segundo plano.")
    else:
        st.warning("Ya hay una búsqueda en curso. Espera a que termine o detenla.")
    st.rerun()


_AVANCE = re.compile(r"\[(\d+) de (\d+)\]")
_ENVIADAS = re.compile(r"a la bandeja (\d+)")
_POR_COMPLETAR = re.compile(r"por completar (\d+)")


_COMPLETANDO = re.compile(r"\{(\d+) de (\d+)\}")


def progreso(lineas):
    """(hechas, total, enviadas a la bandeja, por completar, completadas, por completar en esta búsqueda)."""
    hechas = total = enviadas = pendientes = k = n = 0
    for l in lineas:
        if m := _AVANCE.search(l):
            hechas, total = int(m.group(1)), int(m.group(2))
        if m := _COMPLETANDO.search(l):
            k, n = int(m.group(1)), int(m.group(2))
        if "resultado:" in l:
            if m := _ENVIADAS.search(l):
                enviadas = int(m.group(1))
            if m := _POR_COMPLETAR.search(l):
                pendientes = int(m.group(1))
    return hechas, total, enviadas, pendientes, k, n


@st.fragment(run_every=5)
def panel_ejecucion():
    t = tareas.actual()
    if st.session_state.get("_seguia_en_curso") and not tareas.en_curso():
        st.session_state["_seguia_en_curso"] = False
        st.rerun(scope="app")  # terminó: se refresca toda la página (botones y listas), no solo este panel
    st.session_state["_seguia_en_curso"] = tareas.en_curso()
    if tareas.en_curso():
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**⏳ {t.etiqueta}** · lleva {t.minutos()} min · la inició {t.usuario}")
            if getattr(t, "reanudada", False):
                c1.caption("Se cortó porque el servidor se reinició y **se reanudó sola**; no repite lo que ya está en el sistema.")
            c1.caption("Mientras corre, no subas archivos a GitHub ni reinicies la app: eso reinicia el servidor y corta la "
                       "búsqueda (se reanuda sola una vez).")
            if c2.button("Detener", key="detener", width="stretch", icon=":material/stop:"):
                tareas.detener()
            hechas, total, enviadas, pend, k, n = progreso(t.lineas)
            if n:
                st.progress(min(1.0, k / n), text=f"Paso 2 de 2 · Traduciendo y completando con Gemini · "
                                                  f"{k} de {n} convocatorias completas en la bandeja")
            elif total:
                st.progress(hechas / total, text=f"Paso 1 de 2 · {hechas} de {total} fuentes revisadas")
            else:  # sin avance medible: se muestra lo último que está haciendo, para que no parezca detenida
                ultima = next((l for l in reversed(t.lineas) if l.strip()), "")
                st.progress(0.0, text=(ultima[:140] if ultima else "Preparando…"))
            st.caption("Puedes cerrar esta pestaña o seguir trabajando: la búsqueda sigue en el servidor y lo encontrado "
                       "va llegando a Revisar convocatorias.")
            with st.expander("Ver detalle técnico"):
                st.code("\n".join(t.lineas[-25:]) or "Empezando…", language=None)
    elif t is not None and t.fin and time.time() - t.fin < 1800:
        icono = {"Terminada": "✅", "Detenida": "⏹️", "Error": "⚠️"}.get(t.estado, "")
        hechas, total, enviadas, pend, k, n = progreso(t.lineas)
        with st.container(border=True):
            st.markdown(f"**{icono} {t.etiqueta}: {t.estado.lower()}** en {t.minutos()} min"
                        + (f" · {hechas} de {total} fuentes revisadas" if total else "")
                        + (f" · **{enviadas} completas y en español** enviadas a revisión" if t.comando in ("mapear", "descubrir") else "")
                        + (f" · {pend} quedaron por completar" if pend else "") + ".")
            corto = [l for l in t.lineas if "Llegaron " in l and " de las " in l]
            if corto:
                st.warning(corto[-1].split(" ", 1)[1] if corto[-1][:2].isdigit() else corto[-1])
            if t.comando in ("mapear", "descubrir") and t.estado == "Terminada" and not enviadas:
                st.caption("No llegó nada nuevo a la bandeja. Puede ser que no haya convocatorias nuevas, que todo lo encontrado "
                           "ya estuviera registrado, o que Gemini no haya respondido (usa **Probar Gemini**). El detalle "
                           "técnico lo dice.")
            if t.estado == "Error":
                st.error("La búsqueda se detuvo por un error. Esto es lo que pasó:")
                st.code("\n".join(t.lineas[-8:]) or "(sin mensajes)", language=None)
            elif t.estado == "Detenida":
                st.caption("Alguien pulsó «Detener». Lo encontrado hasta ese momento ya está guardado.")
            with st.expander("Ver detalle técnico"):
                st.code("\n".join(t.lineas[-40:]) or "(sin mensajes)", language=None)
            if t.comando in ("mapear", "descubrir", "completar-pendientes"):
                st.page_link("paginas/bandeja.py", label="Revisar lo que encontró", icon=":material/fact_check:")


def tabla_sugeridas(sug, clave, origen):
    """Sitios oficiales nuevos: el administrador marca cuáles se agregan a la lista de fuentes."""
    if YO["rol"] != "admin":
        st.dataframe(sug, hide_index=True, width="stretch")
        st.caption("El administrador decide si se agregan como fuentes.")
        return
    sug = sug.copy()
    sug.insert(0, "Agregar", False)
    editado = st.data_editor(sug, hide_index=True, width="stretch", key=clave,
                             disabled=[c for c in sug.columns if c != "Agregar"])
    elegidas = editado[editado["Agregar"]].drop(columns="Agregar").to_dict("records")
    if st.button("Agregar los marcados como fuentes", disabled=not elegidas, key=clave + "_btn"):
        import mapeo as programa
        tmp = Path(tempfile.mkdtemp()) / CFG
        tmp.write_bytes(config_bytes())
        programa.agregar_fuentes(tmp, elegidas, origen=origen)
        A.guardar_archivo(CFG, tmp.read_bytes())
        st.success(f"{len(elegidas)} fuentes agregadas. Valídalas en Mantenimiento de fuentes.")
        st.rerun()


def revisar_version():
    """Avisa si en el servidor quedaron archivos de versiones distintas (pasa al subirlos por partes)."""
    import importlib.util
    try:
        import sys as _sys
        _sys.path.insert(0, str(RAIZ / "herramientas"))
        import manifiesto
        version, distintos = manifiesto.revisar()
    except Exception:  # noqa: BLE001
        version, distintos = None, []
    if distintos:
        st.error(f"**En GitHub quedaron archivos de paquetes distintos** (el paquete es la versión {version}). No coinciden: "
                 + ", ".join(distintos[:12]) + ("…" if len(distintos) > 12 else "") + ". Las búsquedas no se lanzan "
                 "hasta corregirlo. **Sube de nuevo el contenido completo del último paquete** (todos los archivos a la "
                 "vez) y reinicia la app.")
        return
    faltan = []
    try:
        import mapeo as programa
        if getattr(programa, "VERSION", "") < "2026-11-23m":
            faltan.append("mapeo.py")
        if importlib.util.find_spec("motor.radar") is None:
            faltan.append("motor/radar.py")
        from motor import extraer, externo
        if not hasattr(extraer, "secciones"):
            faltan.append("motor/extraer.py")
        if not getattr(externo, "MODELO_POR_DEFECTO", "").startswith("gemini-3"):
            faltan.append("motor/externo.py")
        if importlib.util.find_spec("calidad.entrada") is None:
            faltan.append("calidad/entrada.py")
    except Exception as e:  # noqa: BLE001
        faltan.append(f"(no se pudo revisar: {e})")
    viejos = tareas.modulos_desactualizados()
    if viejos:
        st.error("**El servidor sigue usando una versión anterior del programa**, aunque los archivos nuevos ya están en "
                 "GitHub. Por eso las búsquedas y la validación se detienen sin hacer nada. **Reinicia la aplicación:** en "
                 "share.streamlit.io, abre «Manage app» (abajo a la derecha de la app) → menú ⋮ → **Reboot app**. "
                 f"(Módulos desactualizados: {', '.join(viejos)}.)")
        return
    if faltan:
        st.error("**Faltan archivos por actualizar en GitHub:** " + ", ".join(faltan) + ". Mientras tanto la búsqueda "
                 "puede detenerse sin encontrar nada. Súbelos del último paquete y vuelve a abrir la aplicación.")


revisar_version()
interrumpida = tareas.interrumpida(A)
if interrumpida:
    st.warning(f"La búsqueda «{interrumpida.get('etiqueta', '')}» del {interrumpida.get('inicio', '')} se interrumpió porque el "
               "servidor se reinició. Lo que alcanzó a encontrar ya está en Revisar convocatorias. Puedes volver a ejecutarla: "
               "no repite lo que ya está en el sistema.")
panel_ejecucion()
OCUPADO = tareas.en_curso()

# --- fuentes -------------------------------------------------------------------
tmp_cfg = Path(tempfile.mkdtemp()) / CFG
tmp_cfg.write_bytes(config_bytes())
fuentes = pd.read_excel(tmp_cfg, sheet_name="Fuentes", dtype=str).fillna("")
for c in ("Grupo", "Verificación del dominio", "Origen", "Modalidades a buscar"):
    if c not in fuentes:
        fuentes[c] = fuentes.get("Tipo de fuente", "") if c == "Grupo" else ""
activas = fuentes[fuentes["Activa"].str.lower().isin(["sí", "si"])]
por_confirmar = fuentes[fuentes["Verificación del dominio"].str.startswith("Por confirmar") | (fuentes["Dominio oficial"] == "")]
grupos = sorted(g for g in activas["Grupo"].unique() if g)
try:
    _par = pd.read_excel(tmp_cfg, sheet_name="Parametros", header=None, dtype=str).fillna("")
    PARAM_GEMINI = next((r[1] for r in _par.values if r[0] == "Completar campos con Gemini en el mapeo"), "Sí") or "Sí"
except Exception:  # noqa: BLE001
    PARAM_GEMINI = "Sí"
clave = os.environ.get("GEMINI_API_KEY") or ui.secretos().get("GEMINI_API_KEY", "")
if clave:
    os.environ["GEMINI_API_KEY"] = clave

tarjeta = st.container(border=True)  # se dibuja primero, pero usa las opciones de abajo
opciones = st.expander("Opciones de la búsqueda (no hace falta cambiarlas)", icon=":material/tune:")
with opciones:
    elegidos = st.multiselect("Grupos de fuentes a revisar", grupos, default=grupos,
                              help="Por defecto se revisan todas. Si tienes poco tiempo, elige uno o dos grupos.")
    o1, o2 = st.columns(2)
    con_gemini = o1.toggle("Completar campos con Gemini", value=bool(clave), disabled=not clave,
                           help="Gemini lee la página de cada convocatoria NUEVA y llena objetivos, poblaciones, requisitos, nombre "
                                "y descripción en español. Una consulta por convocatoria nueva (máximo 80 por búsqueda). En el plan "
                                "gratuito no cuesta, pero cuenta para el límite diario. Apagado, lo que esté en otro idioma o "
                                "incompleto queda «Por completar» y no pasa a la bandeja." if clave else
                                "No está disponible: falta la clave de Gemini en los secretos.")
    completo = o2.toggle("Revisión completa", help="Vuelve a abrir también las convocatorias ya conocidas, para detectar cambios. "
                         "Tarda bastante más. Igual se hace sola en cada fuente cada 30 días.")
    o3, o4 = st.columns(2)
    cupo = st.slider("Convocatorias completas por búsqueda", 10, 60, 20, 5,
                     help="La búsqueda sigue completando candidatas (de la más prometedora a la menos) hasta que esta "
                          "cantidad llegue completa y en español a la bandeja. Tope de seguridad: 120 consultas a Gemini por "
                          "búsqueda, para no agotar el cupo diario gratuito (unas 500 consultas al día).")
    paralelo = o3.slider("Sitios a la vez", 3, 12, 10, help="Más sitios a la vez = más rápido. Si la app se pone lenta, bájalo.")
    pausa = o4.slider("Segundos entre páginas del mismo sitio", 1.0, 5.0, 2.0, 0.5,
                      help="Pausa de cortesía para no saturar cada sitio. No se recomienda menos de 2.")

sel = activas[activas["Grupo"].isin(elegidos)]
fallidas = sel["Estado de validación"].str.startswith(("Sitio no responde", "Bloqueado por robots", "Redirige a otro dominio",
                                                       "No oficial", "Falta dominio"))
n_sel = int((~fallidas).sum())
primera_vez = not A.leer_archivo("historial_mapeo.json")
completa_efectiva = completo or primera_vez
minutos = max(1, round(n_sel * (1.6 if completa_efectiva else 0.35) * pausa / 2 / paralelo + (cupo * 2.5 * 9 / 60 if con_gemini else 0)))
extra = [] if set(elegidos) == set(grupos) else [x for g in elegidos for x in ("--grupo", g)]
extra += ["--paralelo", str(paralelo), "--pausa", str(pausa)]
extra_mapeo = (extra + ["--maximo-nuevas", str(cupo)] + (["--completo"] if completo else [])
               + ([] if con_gemini else ["--sin-gemini"]))

with tarjeta:
    st.markdown("#### Buscar convocatorias nuevas")
    tiempo = f"unos {minutos} minutos" if minutos < 90 else f"cerca de {round(minutos / 60, 1)} horas"
    st.write(f"Se revisarán **{n_sel} sitios oficiales** y la búsqueda seguirá hasta traer **{cupo} convocatorias nuevas, "
             f"traducidas y completas** · tiempo estimado: **{tiempo}**"
             + (" (la primera vez tarda más; las siguientes solo abren lo nuevo)" if primera_vez else "") + ".")
    if not con_gemini:
        st.warning("Sin Gemini solo pasan las convocatorias que ya están en español y completas en su página. "
                   + ("Enciéndelo en *Opciones de la búsqueda*." if clave else "Falta la clave GEMINI_API_KEY en los secretos."))
    elif not str(PARAM_GEMINI).lower().startswith("s"):
        st.warning("En la configuración, el parámetro «Completar campos con Gemini en el mapeo» está en «No»: Gemini no se "
                   "usará. Cámbialo a «Sí» en la configuración (Mantenimiento de fuentes → Configuración).")
    if st.button("Buscar convocatorias nuevas", type="primary", disabled=not elegidos or OCUPADO, icon=":material/search:"):
        ejecutar("mapear", "Búsqueda de convocatorias" + (" (revisión completa)" if completo else ""), extra_mapeo)
    if clave and st.button("Probar Gemini", icon=":material/network_check:",
                           help="Hace una consulta mínima para comprobar que la clave y el modelo funcionan."):
        from motor import externo as _ext
        from motor import config as _cfgmod
        ok, modelo_usado, mensaje = _ext.probar(clave, cfg=_cfgmod.cargar(tmp_cfg))
        (st.success if ok else st.error)(f"{mensaje} Modelo: {modelo_usado or '—'}.")
    if OCUPADO:
        st.caption("Hay una búsqueda en curso; espera a que termine.")
    elif fallidas.any():
        st.caption(f"Se saltan {int(fallidas.sum())} sitios que no respondieron en la última validación "
                   "(ver *Mantenimiento de fuentes*, más abajo).")

# --- por completar: lo que encontró pero no está en español o le faltan datos -----------------
from bandeja import flujo as F  # noqa: E402
from calidad import entrada as E  # noqa: E402

por_completar = A.items(E.ESTADO)
if st.session_state.get("aviso_pc"):
    with st.container(border=True):
        st.success(st.session_state.pop("aviso_pc"))
        st.page_link("paginas/bandeja.py", label="Ir a completarlas en Revisar convocatorias", icon=":material/arrow_forward:")
if por_completar:
    with st.container(border=True):
        st.markdown(f"#### {len(por_completar)} convocatorias por completar")
        st.caption("Gemini ya leyó su página, pero les faltan datos obligatorios, así que **no pasan a la bandeja**. El "
                   f"sistema reintenta unas pocas en cada búsqueda (hasta {E.INTENTOS_MAXIMOS} veces cada una). También "
                   "puedes **completarlas a mano** en Revisar convocatorias → pestaña **Por completar**.")
        st.page_link("paginas/bandeja.py", label="Completarlas a mano", icon=":material/edit_note:")
        if len(por_completar) > 100 and YO["rol"] == "admin":
            st.warning(f"Hay **{len(por_completar)}** acumuladas de búsquedas anteriores, cuando todo lo encontrado se guardaba "
                       "aunque no se pudiera completar. Conviene **vaciar la lista**: el sistema las olvida y las vuelve a "
                       "encontrar en las próximas búsquedas, ahora eligiendo solo las mejores y completándolas antes de "
                       "guardarlas.")
            if st.button(f"Vaciar la lista ({len(por_completar)})", type="primary", icon=":material/delete_sweep:",
                         disabled=OCUPADO):
                tocadas = [i for i in por_completar if F.tocada_por_persona(i)]
                borrar = [i for i in por_completar if not F.tocada_por_persona(i)]
                F.anular(A, borrar, YO["nombre"], "Se vació la lista de por completar")
                hist = A.leer_archivo("historial_mapeo.json")
                if hist:
                    h = json.loads(hist)
                    for i in borrar:
                        h.pop(i["datos"].get("Cómo aplicar", ""), None)
                    A.guardar_archivo("historial_mapeo.json", json.dumps(h, ensure_ascii=False).encode("utf-8"))
                st.success(f"Se vaciaron {len(borrar)}." + (f" Quedan {len(tocadas)} que alguien ya editó." if tocadas else ""))
                st.rerun()
        tabla_pc = pd.DataFrame([{"id": i["id"], "Convocatoria": i["datos"].get("Nombre de la Convocatoria", ""),
                                  "Oferente": i["datos"].get("Nombre de la Fuente", ""),
                                  "Qué le falta": "; ".join(f.split(":")[0] for f in i["meta"].get("faltantes", [])) or "—",
                                  "Intentos": int(i["meta"].get("intentos", 0)),
                                  "Página": i["datos"].get("Cómo aplicar") if str(i["datos"].get("Cómo aplicar", "")).startswith("http") else None}
                                 for i in por_completar[:200]])
        if len(por_completar) > 200:
            st.caption(f"Se muestran 200 de {len(por_completar)}.")
        ev = st.dataframe(tabla_pc.drop(columns="id"), hide_index=True, width="stretch", on_select="rerun",
                          selection_mode="multi-row", key="tabla_pc", height=min(380, 38 + 35 * len(tabla_pc)),
                          column_config={"Página": st.column_config.LinkColumn(display_text="Abrir ↗"),
                                         "Convocatoria": st.column_config.TextColumn(width="large"),
                                         "Qué le falta": st.column_config.TextColumn(width="large")})
        marcadas = [tabla_pc.iloc[n]["id"] for n in (ev.selection.rows if ev and ev.selection else [])]
        elegidas_pc = [i for i in por_completar if i["id"] in marcadas]
        if st.button(f"Completar a mano las marcadas ({len(marcadas)})", type="primary", disabled=not marcadas,
                     icon=":material/edit_note:",
                     help="Para las que sí sirven: pasan a Revisar convocatorias con todo lo que ya mapeó el sistema, y "
                          "allí se completa en el formulario lo que falte."):
            n = F.enviar_a_completar_a_mano(A, elegidas_pc, YO["nombre"])
            st.session_state["rev_origen"] = ["Para completar a mano"]
            st.session_state["aviso_pc"] = (f"{n} enviadas a Revisar convocatorias → pestaña Por revisar, con el origen "
                                            "«Para completar a mano» (el filtro ya queda puesto). Allí está todo lo que "
                                            "mapeó el sistema, listo para completar en el formulario.")
            st.rerun()
        p1, p2, p3 = st.columns([1.2, 1.3, 2])
        if p1.button("Reintentar ahora", disabled=OCUPADO or not clave, icon=":material/refresh:",
                     help="Gemini vuelve a leer la página de cada una. Las que queden completas pasan a la bandeja."):
            ejecutar("completar-pendientes", "Completar convocatorias pendientes", ["--reintentar-todas"])
        if p2.button(f"Descartar marcadas ({len(marcadas)})", disabled=not marcadas,
                     help="Para las que no sirven (por ejemplo, un folleto o una página que no es una convocatoria)."):
            F.descartar_varias(A, [i for i in por_completar if i["id"] in marcadas], YO["nombre"],
                               "No se pudo completar con la información de la página")
            st.rerun()
        p3.caption("Marca las filas: **Completar a mano** si sirven (llegan a Revisar convocatorias con lo que ya se mapeó), "
                   "o **Descartar** si no. Lo descartado se puede restaurar en Revisar convocatorias → Descartadas y anuladas.")

# --- resultado de la última búsqueda ------------------------------------------------
ult = A.leer_archivo("ultimo_mapear.json")
if ult and not OCUPADO:
    r = json.loads(ult)
    with st.container(border=True):
        listo = [l for l in r.get("log", []) if "Listo:" in l]
        st.markdown(f"**Última búsqueda:** {r['fecha']} · {r['usuario']}"
                    + (f"  \n{listo[-1].split('Listo:', 1)[1].strip()}" if listo else ""))
        b1, b2 = st.columns([1, 2])
        rep = A.leer_archivo("ultimo_mapeo.xlsx")
        if rep:
            b1.download_button("Descargar reporte (Excel)", rep, f"reporte_busqueda_{r['fecha'][:10]}.xlsx", icon=":material/download:")
        with b2.expander("Ver detalle técnico"):
            st.code("\n".join(r["log"]) or "(sin mensajes)")

# --- descubrir convocatorias fuera de las fuentes ----------------------------------------
from calidad import entrada as E  # noqa: E402
try:
    radar = pd.read_excel(tmp_cfg, sheet_name="Radar", dtype=str).fillna("")
except Exception:  # noqa: BLE001 - configuración anterior, sin la hoja Radar
    radar = pd.DataFrame(columns=["ID", "Activa", "Tipo", "Nombre"])
radar_activo = radar[radar["Activa"].str.lower().isin(["sí", "si"])]
with st.container(border=True):
    st.markdown("#### Descubrir convocatorias fuera de las fuentes")
    st.write("Búsqueda aparte para encontrar oferentes que **no están en la lista de fuentes**. Usa sitios que publican a "
             "diario convocatorias de muchos oferentes **solo como radar**: el sistema sigue cada enlace hasta la **página "
             "oficial** del oferente y registra únicamente esa; si no hay enlace oficial, la descarta. También consulta el "
             "portal de financiación de la Unión Europea. Lo encontrado pasa por los mismos filtros (Gemini, Colombia "
             "elegible, sin duplicados) y llega a la bandeja. Los sitios nuevos que aporten convocatorias quedan abajo como "
             "**fuentes sugeridas**.")
    if len(radar_activo):
        st.caption("Sitios de radar activos: " + " · ".join(radar_activo["Nombre"]) +
                   ". Se cambian en la hoja «Radar» de la configuración. Cada búsqueda abre solo publicaciones nuevas.")
        if st.button("Descubrir convocatorias", disabled=OCUPADO, icon=":material/radar:",
                     help="Usa la misma meta de convocatorias completas y el mismo cupo de Gemini que la búsqueda normal."):
            ejecutar("descubrir", "Descubrimiento fuera de las fuentes",
                     ["--paralelo", str(paralelo), "--pausa", str(pausa), "--maximo-nuevas", str(cupo)]
                     + ([] if con_gemini else ["--sin-gemini"]))
    else:
        st.info("No hay sitios de radar activos. Actívalos en la hoja «Radar» de la configuración (solo administrador).")
    rep_d = A.leer_archivo("ultimo_descubrimiento.xlsx")
    reg_d = json.loads(A.leer_archivo("ultimo_descubrir.json") or b"{}")
    if rep_d and not OCUPADO:
        import io
        hojas_d = pd.read_excel(io.BytesIO(rep_d), sheet_name=None, dtype=str)
        listo = [l for l in reg_d.get("log", []) if "Listo:" in l]
        st.markdown(f"**Último descubrimiento:** {reg_d.get('fecha', '')} · {reg_d.get('usuario', '')}")
        es_desc = lambda i: i["origen"].startswith("Descubrimiento") or "· RAD-" in i["origen"]  # noqa: E731
        en_rev = [i for i in A.items("Por revisar") if es_desc(i)]
        en_comp = [i for i in A.items(E.ESTADO) if es_desc(i)]
        with st.container(border=True):
            st.markdown("**¿Dónde quedan las que encuentra?** En **Revisar convocatorias**, con el origen "
                        "«Descubierta fuera de las fuentes»:")
            k1, k2 = st.columns(2)
            k1.metric("En la pestaña Por revisar", len(en_rev), help="Llegaron completas y en español: listas para revisar.")
            k2.metric("En la pestaña Por completar", len(en_comp),
                      help="Les falta algún dato obligatorio: se completan a mano o se reintentan con Gemini.")
            b1, b2 = st.columns(2)
            if b1.button("Ver las que llegaron", icon=":material/inbox:", disabled=not en_rev, width="stretch"):
                st.session_state["rev_origen"] = ["Descubierta fuera de las fuentes"]
                st.switch_page("paginas/bandeja.py")
            if b2.button("Ver las por completar", icon=":material/edit_note:", disabled=not en_comp, width="stretch",
                         help="Se abre Revisar convocatorias: elige la pestaña «Por completar»."):
                st.session_state["comp_origen"] = ["Descubierta fuera de las fuentes"]
                st.switch_page("paginas/bandeja.py")
            if listo:
                st.caption("Detalle de la última corrida: " + listo[-1].split("Listo:", 1)[1].strip()
                           + " Las descartadas (páginas de inicio de sesión, noticias, no elegibles) están en el reporte.")
        d1, d2 = st.columns([1, 2])
        d1.download_button("Descargar reporte (Excel)", rep_d, f"descubrimiento_{reg_d.get('fecha', '')[:10]}.xlsx",
                           icon=":material/download:", key="desc_rep")
        with d2.expander("Ver detalle técnico"):
            st.code("\n".join(reg_d.get("log", [])) or "(sin mensajes)")
        sug_d = hojas_d.get("Fuentes sugeridas", pd.DataFrame()).fillna("")
        if len(sug_d):
            st.markdown(f"**Fuentes sugeridas ({len(sug_d)})**: sitios oficiales que no están en la lista y aportaron "
                        "convocatorias. Al agregarlos, la búsqueda normal los revisa siempre.")
            tabla_sugeridas(sug_d, "sug_radar", "Descubrimiento (radar)")

# --- seguimiento año tras año ---------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _tablero_seguimiento(_almacen, n_items, dia):
    import mapeo as programa
    hist = json.loads(_almacen.leer_archivo("historial_mapeo.json") or b"{}")
    return programa.estado_seguimiento(_almacen.base(), _almacen.items(), hist.get("_seguimiento_ediciones", {}),
                                       date.fromisoformat(dia))


with st.container(border=True):
    st.markdown("#### Convocatorias que se repiten cada año")
    st.write("Las convocatorias de la base que ya cerraron (también las que vinieron de Airtable) se siguen solas: en cada "
             "búsqueda se vuelve a abrir su página oficial, con más frecuencia en su **temporada** (desde 4 meses antes "
             "hasta 2 meses después de la fecha en que cerró la edición anterior). Cuando publican la edición nueva, se "
             "completa **antes que cualquier otra** y llega a Revisar convocatorias. Aquí se ve qué pasó con cada una.")
    try:
        _todos = A.items()
        seg = pd.DataFrame(_tablero_seguimiento(A, len(_todos), date.today().isoformat()))
    except Exception as e:  # noqa: BLE001
        seg = pd.DataFrame()
        st.caption(f"No se pudo calcular el seguimiento: {e}")
    if len(seg):
        cuenta = seg["Estado"].value_counts()
        m = st.columns(4)
        for col, (estado, lab) in zip(m, [
                ("Edición nueva ya en el sistema", "con la edición nueva ya encontrada"),
                ("Revisada: aún sin edición nueva", "revisadas, todavía sin edición nueva"),
                ("En temporada: se revisa en la próxima búsqueda", "en temporada, por revisar"),
                ("Sin página oficial para seguirla", "sin página oficial: no se pueden seguir")]):
            col.markdown(f"<div class='kpi'><div class='v'>{int(cuenta.get(estado, 0))}</div><div class='l'>{lab}</div></div>",
                         unsafe_allow_html=True)
        st.write("")
        st.caption(f"{len(seg)} convocatorias de la base ya cerraron. "
                   f"{int(cuenta.get('Fuera de temporada: se revisará al acercarse', 0))} están fuera de temporada y se "
                   "revisarán cuando se acerque su fecha.")
        with st.expander("Ver el detalle por convocatoria"):
            ver = st.multiselect("Estado", sorted(seg["Estado"].unique()), placeholder="Todos", key="seg_estado")
            buscar_s = st.text_input("Buscar por nombre u oferente", key="seg_buscar", placeholder="Ej.: Carolina, Chevening")
            vs = seg[seg["Estado"].isin(ver)] if ver else seg
            if buscar_s:
                b = buscar_s.lower()
                vs = vs[vs["Convocatoria"].str.lower().str.contains(b, regex=False) |
                        vs["Oferente"].str.lower().str.contains(b, regex=False)]
            st.dataframe(vs, hide_index=True, width="stretch", height=min(420, 38 + 35 * max(len(vs), 1)),
                         column_config={"Página oficial": st.column_config.LinkColumn(display_text="Abrir ↗")})
            import io
            buf = io.BytesIO()
            seg.to_excel(buf, index=False, sheet_name="Seguimiento")
            st.download_button("Descargar (Excel)", buf.getvalue(), "seguimiento_ediciones.xlsx",
                               icon=":material/download:", key="seg_dl")
        if int(cuenta.get("Sin página oficial para seguirla", 0)):
            st.caption("«Sin página oficial» son las que en «Cómo aplicar» tienen un formulario (Google, Qualtrics, "
                       "Airtable), un PDF, un texto sin enlace o la portada del sitio, y tampoco tienen una página útil en "
                       "«Link de la Fuente Oferente». Para que entren al seguimiento, ponles en la base el enlace de la "
                       "página de la convocatoria.")
    else:
        st.caption("Todavía no hay convocatorias cerradas en la base para seguir.")

# --- mantenimiento de fuentes -------------------------------------------------------
st.divider()
st.markdown("#### Mantenimiento de fuentes")
st.caption("Una vez al mes: comprobar que los sitios oficiales siguen funcionando. También aquí se consulta la lista de fuentes.")
k = st.columns(4)
for col, (v, lab) in zip(k, [(len(fuentes), "fuentes en la lista"), (len(activas), "activas"),
                             (activas["Grupo"].nunique(), "grupos"),
                             (len(por_confirmar), "sin dominio confirmado (inactivas)")]):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{lab}</div></div>", unsafe_allow_html=True)
st.write("")
m1, m2 = st.columns([1, 2])
if m1.button("Validar fuentes", disabled=not elegidos or OCUPADO, icon=":material/verified:", width="stretch"):
    ejecutar("validar-fuentes", "Validación de fuentes", extra)
m2.caption("Comprueba que cada sitio responda, que no redirija a otro dominio, que sea del oferente y encuentra su página de "
           "convocatorias. Los sitios que fallan se saltan en la búsqueda hasta la siguiente validación.")

with st.expander("Ver la lista de fuentes", icon=":material/list:"):
    f1, f2 = st.columns([1, 1.4])
    filtro_grupo = f1.selectbox("Grupo", ["Todos"] + sorted(g for g in fuentes["Grupo"].unique() if g))
    buscar = f2.text_input("Buscar fuente")
    vista = fuentes if filtro_grupo == "Todos" else fuentes[fuentes["Grupo"] == filtro_grupo]
    if buscar:
        vista = vista[vista["Nombre"].str.contains(buscar, case=False) | vista["Dominio oficial"].str.contains(buscar, case=False)]
    cols = ["ID", "Activa", "Grupo", "Nombre", "País", "Dominio oficial", "Verificación del dominio", "Modalidades a buscar",
            "URL de convocatorias", "URL de becas", "Estado de validación", "Última validación", "Origen", "Notas"]
    st.dataframe(vista[[c for c in cols if c in vista.columns]], hide_index=True, width="stretch", height=420,
                 column_config={"Dominio oficial": st.column_config.LinkColumn(), "URL de convocatorias": st.column_config.LinkColumn()})

if YO["rol"] == "admin":
    with st.expander("Configuración (solo administrador)", icon=":material/settings:"):
        st.write("Las fuentes, palabras de cada modalidad, reglas de elegibilidad y exclusiones de ICETEX están en un Excel. "
                 "Descárgalo, edítalo y vuelve a cargarlo.")
        c1, c2 = st.columns(2)
        c1.download_button("Descargar configuración", config_bytes(), CFG, width="stretch")
        nuevo = c2.file_uploader("Cargar configuración editada", type="xlsx")
        if nuevo and c2.button("Guardar configuración"):
            from openpyxl import load_workbook
            try:
                wb = load_workbook(nuevo)
                faltan = {"Fuentes", "Elegibilidad", "Parametros"} - set(wb.sheetnames)
                if not {"Palabras_modalidad", "Palabras_beca"} & set(wb.sheetnames):
                    faltan.add("Palabras_modalidad")
                if faltan:
                    raise ValueError("Faltan las hojas: " + ", ".join(sorted(faltan)))
                A.guardar_archivo(CFG, nuevo.getvalue())
                st.success("Configuración guardada.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"El archivo no es una configuración válida: {e}")
