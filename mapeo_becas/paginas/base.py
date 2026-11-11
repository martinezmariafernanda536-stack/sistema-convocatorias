"""Página: base de convocatorias y calidad del dato. Aquí se corrigen los registros que quedaron con pendientes."""
import io
from datetime import date

import pandas as pd
import streamlit as st

import ui
from bandeja.almacen import ahora
from calidad import reglas as R
from calidad.exportacion import excel_completo
from componentes import Contexto, formulario, panel_validacion

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()
A = ui.almacen()
PUEDE_EDITAR = True  # administrador y revisor corrigen la base


@st.cache_data(ttl=60, show_spinner=False)
def leer():
    return A.items("Aprobada"), A.catalogo().filas()


aprobadas, catalogo_filas = leer()
CTX = Contexto(A, YO, catalogo_filas, [i["datos"] | {"_id": i["id"]} for i in aprobadas])

st.title("Base de convocatorias")
st.caption("Convocatorias revisadas y aprobadas: es la base que alimenta el dashboard y los informes.")


def n_pend(item, nivel=None):
    return sum(1 for p in item["meta"].get("pendientes", []) if nivel is None or p["nivel"] == nivel)


con_err = [i for i in aprobadas if n_pend(i, "Error")]
con_ale = [i for i in aprobadas if n_pend(i, "Alerta") and not n_pend(i, "Error")]
k = st.columns(4)
for col, (v, lab) in zip(k, [(len(aprobadas), "convocatorias en la base"), (len(con_err), "con errores por corregir"),
                             (len(con_ale), "solo con alertas"), (len(aprobadas) - len(con_err) - len(con_ale), "sin pendientes")]):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{lab}</div></div>", unsafe_allow_html=True)
st.write("")

c1, c2, c3 = st.columns([1.2, 1, 1.6])
vista = c1.radio("Mostrar", ["Con errores", "Con alertas", "Todas"], horizontal=True)
reglas_presentes = sorted({p["regla"] for i in aprobadas for p in i["meta"].get("pendientes", [])})
regla = c2.selectbox("Regla", ["Todas"] + reglas_presentes, format_func=lambda r: r if r == "Todas" else f"{r} · {R.REGLAS.get(r, '')}")
buscar = c3.text_input("Buscar por nombre o actor")

lista = {"Con errores": con_err, "Con alertas": con_ale, "Todas": aprobadas}[vista]
if regla != "Todas":
    lista = [i for i in lista if any(p["regla"] == regla for p in i["meta"].get("pendientes", []))]
if buscar:
    b = buscar.lower()
    lista = [i for i in lista if b in i["datos"].get("Nombre de la Convocatoria", "").lower()
             or b in i["datos"].get("Nombre de la Fuente", "").lower()]

tabla = pd.DataFrame([{
    "Convocatoria": i["datos"].get("Nombre de la Convocatoria", ""), "Actor": i["datos"].get("Nombre de la Fuente", ""),
    "Carácter": i["datos"].get("Oficial / No Oficial", ""), "Modalidad": i["datos"].get("Modalidad", ""),
    "Registro": i["datos"].get("Fecha de Registro", ""), "Errores": n_pend(i, "Error"), "Alertas": n_pend(i, "Alerta"),
    "Origen": i["origen"]} for i in lista])
st.dataframe(tabla, hide_index=True, width="stretch", height=280)

if lista:
    etiquetas = {i["id"]: f"{i['datos'].get('Nombre de la Convocatoria', '')[:95]}  ·  {n_pend(i, 'Error')} errores" for i in lista}
    sel = st.selectbox("Abrir convocatoria", list(etiquetas), format_func=etiquetas.get)
    item = next(i for i in lista if i["id"] == sel)
    izq, der = st.columns([1.9, 1])
    with izq:
        datos = formulario(CTX, item["datos"], f"b_{item['id']}_")
    with der:
        enlace = datos.get("Cómo aplicar", "")
        if str(enlace).startswith("http"):
            st.link_button("Abrir la página oficial", enlace, width="stretch")
        st.markdown("#### Calidad del dato")
        norm, hallazgos = panel_validacion(CTX, datos, nuevo=False, excluir_id=item["id"])
        if PUEDE_EDITAR:
            if st.button("Guardar corrección", type="primary", width="stretch"):
                item["datos"] = norm
                item["meta"]["pendientes"] = [h.__dict__ for h in hallazgos if h.nivel in ("Error", "Alerta") and h.regla != "R07"]
                item["historial"].append({"fecha": ahora(), "usuario": YO["nombre"], "accion": "Corrección en la base",
                                          "detalle": f"Quedan {n_pend(item, 'Error')} errores y {n_pend(item, 'Alerta')} alertas"})
                A.guardar_item(item)
                st.session_state["aviso_base"] = "Corrección guardada."
                ui.recargar()
            with st.expander("Retirar de la base (duplicada o no válida)"):
                motivo = st.text_area("Motivo", key="ret_" + item["id"])
                if st.button("Retirar", key="retb_" + item["id"]):
                    if not motivo.strip():
                        st.error("Escribe el motivo.")
                    else:
                        item["estado"] = "Descartada"
                        item["observacion"] = motivo
                        item["historial"].append({"fecha": ahora(), "usuario": YO["nombre"], "accion": "Retirada de la base", "detalle": motivo})
                        A.guardar_item(item)
                        ui.recargar()
        else:
            st.info("Tu rol permite consultar. Las correcciones las hace un revisor.")
        with st.expander("Historial y correcciones automáticas"):
            for h in item["historial"]:
                st.markdown(f"- {h['fecha']} · {h['usuario']}: {h['accion']} {('· ' + h['detalle']) if h.get('detalle') else ''}")
            cambios = item["meta"].get("cambios", [])
            if cambios:
                st.markdown("**Corregido automáticamente al migrar:**")
                st.dataframe(pd.DataFrame(cambios), hide_index=True, width="stretch")
if st.session_state.get("aviso_base"):
    st.success(st.session_state.pop("aviso_base"))

st.divider()
st.markdown("#### Descargar")
c1, c2 = st.columns(2)
c1.download_button("Todo lo registrado en Excel", excel_completo(A), f"convocatorias_sistema_{date.today():%Y-%m-%d}.xlsx",
                   width="stretch", help="Base, por revisar, actor pendiente, descartadas y catálogo de actores, con todos los campos.")
if YO["rol"] == "admin":
    c2.download_button("Copia de seguridad de la base (.db)", A.respaldo(), f"convocatorias_{date.today():%Y-%m-%d}.db", width="stretch")

if YO["rol"] == "admin":
    st.divider()
    st.markdown("#### Importación masiva desde Airtable")
    st.write("Carga un export CSV de Airtable. Solo se agregan las convocatorias que aún no están en el sistema "
             "(se comparan por enlace y por nombre); se corrigen igual que en la migración.")
    archivo = st.file_uploader("Export CSV de Airtable", type="csv")
    todo_rev = st.checkbox("Enviar todas a la bandeja de revisión", value=True,
                           help="Si se desmarca, las que tenían las tres verificaciones en Airtable entran directo a la base.")
    if archivo and st.button("Importar", type="primary"):
        from calidad.migracion import importar
        with st.spinner("Importando…"):
            tabla, nuevos = importar(pd.read_csv(archivo), A, todo_a_revision=todo_rev)
        st.success(f"{(tabla['Resultado'] != 'Ya estaba en el sistema').sum()} convocatorias nuevas · "
                   f"{(tabla['Resultado'] == 'Ya estaba en el sistema').sum()} ya estaban · {len(nuevos)} actores nuevos en el catálogo.")
        st.dataframe(tabla, hide_index=True, width="stretch")
        st.cache_data.clear()
