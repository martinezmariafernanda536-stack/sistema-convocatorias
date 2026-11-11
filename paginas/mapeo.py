"""Página: mapeo automático de convocatorias internacionales (becas, subvenciones, cooperación técnica y premios)."""
import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import ui

RAIZ = Path(__file__).resolve().parents[1]
CFG = "configuracion_mapeo_becas.xlsx"
st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()
A = ui.almacen()

st.title("Mapeo automático")
st.caption("Busca becas, subvenciones, cooperación técnica y premios abiertos a Colombia en los sitios oficiales de los oferentes: "
           "los actores de la base, gobiernos y agencias, organismos multilaterales, fundaciones, universidades y cámaras binacionales. "
           "Lo que encuentra va a la bandeja de revisión; nunca entra directo a la base.")


def config_bytes():
    return A.leer_archivo(CFG) or (RAIZ / "config" / CFG).read_bytes()


def preparar():
    tmp = Path(tempfile.mkdtemp())
    (tmp / CFG).write_bytes(config_bytes())
    hist = A.leer_archivo("historial_mapeo.json")
    if hist:
        (tmp / "historial.json").write_bytes(hist)
    os.environ["MAPEO_HISTORIAL"] = str(tmp / "historial.json")
    return tmp


class AlEstado(logging.Handler):
    def __init__(self, caja, lineas):
        super().__init__()
        self.caja, self.lineas = caja, lineas

    def emit(self, record):
        msg = record.getMessage()
        self.lineas.append(msg)
        self.caja.write(msg)


def ejecutar(comando, etiqueta, extra=()):
    import mapeo as programa
    tmp = preparar()
    lineas = []
    with st.status(etiqueta, expanded=True) as caja:
        manejador = AlEstado(caja, lineas)
        log = logging.getLogger("mapeo")
        log.addHandler(manejador)
        log.setLevel(logging.INFO)
        try:
            resultado = programa.main([comando, "--config", str(tmp / CFG), *extra])
            caja.update(label=f"{etiqueta}: terminado", state="complete")
        except SystemExit as e:
            caja.update(label=f"{etiqueta}: detenido ({e})", state="error")
            resultado = None
        except Exception as e:  # noqa: BLE001 - se muestra el error a quien ejecuta
            caja.update(label=f"{etiqueta}: error", state="error")
            st.exception(e)
            resultado = None
        finally:
            log.removeHandler(manejador)
    if (tmp / "historial.json").exists():
        A.guardar_archivo("historial_mapeo.json", (tmp / "historial.json").read_bytes())
    if comando == "validar-fuentes":
        A.guardar_archivo(CFG, (tmp / CFG).read_bytes())
    registro = {"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "usuario": YO["nombre"], "comando": comando,
                "log": lineas[-60:]}
    A.guardar_archivo(f"ultimo_{comando}.json", json.dumps(registro, ensure_ascii=False).encode("utf-8"))
    if resultado and Path(resultado).exists() and str(resultado).endswith(".xlsx") and comando == "mapear":
        A.guardar_archivo("ultimo_mapeo.xlsx", Path(resultado).read_bytes())
    if resultado and Path(resultado).exists() and comando == "buscar-externo":
        A.guardar_archivo("ultima_busqueda_externa.xlsx", Path(resultado).read_bytes())
    st.cache_data.clear()


# --- fuentes -------------------------------------------------------------------
tmp_cfg = Path(tempfile.mkdtemp()) / CFG
tmp_cfg.write_bytes(config_bytes())
fuentes = pd.read_excel(tmp_cfg, sheet_name="Fuentes", dtype=str).fillna("")
for c in ("Grupo", "Verificación del dominio", "Origen", "Modalidades a buscar"):
    if c not in fuentes:
        fuentes[c] = fuentes.get("Tipo de fuente", "") if c == "Grupo" else ""
activas = fuentes[fuentes["Activa"].str.lower().isin(["sí", "si"])]
por_confirmar = fuentes[fuentes["Verificación del dominio"].str.startswith("Por confirmar") | (fuentes["Dominio oficial"] == "")]
k = st.columns(4)
for col, (v, lab) in zip(k, [(len(fuentes), "fuentes configuradas"), (len(activas), "fuentes activas"),
                             (activas["Grupo"].nunique(), "grupos de fuentes"),
                             (len(por_confirmar), "sin dominio confirmado (inactivas)")]):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{lab}</div></div>", unsafe_allow_html=True)
st.write("")
resumen = activas.groupby("Grupo").size().rename("Fuentes activas").reset_index()
st.dataframe(resumen, hide_index=True, width="content")

grupos = sorted(g for g in activas["Grupo"].unique() if g)
elegidos = st.multiselect("Qué fuentes revisar", grupos, default=grupos,
                          help="Con más de 200 fuentes, una corrida completa puede tardar más de una hora. "
                               "Se puede ejecutar por grupos: por ejemplo, un grupo cada día.")
n_sel = activas["Grupo"].isin(elegidos).sum()
minutos = max(1, round(n_sel * 1.5 / 6))
st.caption(f"{n_sel} fuentes seleccionadas · tiempo estimado: unos {minutos} minutos (6 fuentes a la vez, 3 segundos entre páginas del mismo sitio).")
extra = [] if set(elegidos) == set(grupos) else [x for g in elegidos for x in ("--grupo", g)]

c1, c2 = st.columns(2)
with c1:
    st.markdown("#### 1. Validar fuentes")
    st.write("Comprueba que cada sitio responda, que no redirija a otro dominio, que se identifique con el nombre del oferente "
             "y encuentra su página de convocatorias. Hazlo la primera vez y una vez al mes.")
    if st.button("Validar fuentes", width="stretch", disabled=not elegidos):
        ejecutar("validar-fuentes", "Validando fuentes", extra)
        st.rerun()
with c2:
    st.markdown("#### 2. Ejecutar el mapeo")
    st.write("Revisa las fuentes seleccionadas buscando becas, subvenciones, cooperación técnica y premios, "
             "y deja en la bandeja lo nuevo o actualizado.")
    if st.button("Ejecutar mapeo ahora", type="primary", width="stretch", disabled=not elegidos):
        ejecutar("mapear", "Buscando convocatorias", extra)

# --- búsqueda externa con Gemini ---------------------------------------------------
st.divider()
st.markdown("#### 3. Búsqueda externa con Gemini (cuando se requiera)")
st.write("Busca en Google, con Gemini, convocatorias en **sitios oficiales que no están entre las fuentes**. "
         "La instrucción le exige sitios oficiales, que Colombia sea elegible, convocatorias abiertas, becas que no estén en ICETEX "
         "y los valores de las listas del formulario. Gemini solo propone: el sistema abre cada página y le aplica las mismas reglas "
         "del mapeo; descarta agregadores, ICETEX y los enlaces que no existen. Lo que pasa llega a la bandeja.")
clave = os.environ.get("GEMINI_API_KEY") or ui.secretos().get("GEMINI_API_KEY", "")
if clave:
    os.environ["GEMINI_API_KEY"] = clave
    g1, g2, g3 = st.columns([1.3, 1.3, 0.8])
    mods = g1.multiselect("Modalidades", ["Beca", "Subvención", "Cooperación técnica", "Premio"],
                          default=["Beca", "Subvención", "Cooperación técnica", "Premio"])
    tema = g2.text_input("Tema (opcional)", placeholder="Ej.: cambio climático, paz, salud")
    region = g2.text_input("País o región del oferente (opcional)", placeholder="Ej.: Unión Europea, Japón")
    maximo = g3.number_input("Convocatorias a pedir", 3, 20, 10)
    if st.button("Buscar con Gemini", disabled=not mods):
        extra_g = [x for m in mods for x in ("--modalidad", m)] + ["--maximo", str(maximo)]
        if tema:
            extra_g += ["--tema", tema]
        if region:
            extra_g += ["--region", region]
        ejecutar("buscar-externo", "Búsqueda externa con Gemini", extra_g)
else:
    st.info("Para activarla, el administrador debe agregar el secreto **GEMINI_API_KEY** (clave de Google AI Studio) "
            "en la configuración del servidor (Hugging Face: Settings → Variables and secrets; Streamlit: Secrets).")

ext = A.leer_archivo("ultima_busqueda_externa.xlsx")
if ext:
    import io
    reg = json.loads(A.leer_archivo("ultimo_buscar-externo.json") or b"{}")
    st.markdown(f"**Última búsqueda externa:** {reg.get('fecha', '')} · {reg.get('usuario', '')}")
    hojas = pd.read_excel(io.BytesIO(ext), sheet_name=None, dtype=str)
    with st.expander("Ver resultado de la última búsqueda externa"):
        st.markdown("**Descartadas**")
        st.dataframe(hojas.get("Descartadas", pd.DataFrame()).fillna(""), hide_index=True, width="stretch")
        st.code("\n".join(reg.get("log", [])) or "(sin mensajes)")
    st.download_button("Descargar resultado de la búsqueda externa (Excel)", ext, "busqueda_externa.xlsx")
    sug = hojas.get("Fuentes sugeridas", pd.DataFrame()).fillna("")
    if len(sug):
        st.markdown("**Sitios oficiales nuevos encontrados** (se pueden agregar como fuentes del mapeo)")
        if YO["rol"] == "admin":
            sug.insert(0, "Agregar", False)
            editado = st.data_editor(sug, hide_index=True, width="stretch", disabled=[c for c in sug.columns if c != "Agregar"])
            elegidas = editado[editado["Agregar"]].drop(columns="Agregar").to_dict("records")
            if st.button("Agregar las marcadas como fuentes", disabled=not elegidas):
                import mapeo as programa
                tmp = Path(tempfile.mkdtemp()) / CFG
                tmp.write_bytes(config_bytes())
                programa.agregar_fuentes(tmp, elegidas)
                A.guardar_archivo(CFG, tmp.read_bytes())
                st.success(f"{len(elegidas)} fuentes agregadas. Ejecuta «Validar fuentes» para confirmarlas.")
                st.rerun()
        else:
            st.dataframe(sug, hide_index=True, width="stretch")
            st.caption("El administrador decide si se agregan como fuentes.")

st.divider()
ult = A.leer_archivo("ultimo_mapear.json")
if ult:
    r = json.loads(ult)
    st.markdown(f"**Última ejecución del mapeo:** {r['fecha']} · {r['usuario']}")
    with st.expander("Ver registro de la última ejecución"):
        st.code("\n".join(r["log"]) or "(sin mensajes)")
    rep = A.leer_archivo("ultimo_mapeo.xlsx")
    if rep:
        st.download_button("Descargar reporte de la última ejecución (Excel)", rep, f"reporte_mapeo_{r['fecha'][:10]}.xlsx")

st.markdown("#### Fuentes")
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
    st.divider()
    st.markdown("#### Configuración (administrador)")
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
