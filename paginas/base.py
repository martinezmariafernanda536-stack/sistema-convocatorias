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

# --- resumen por tipo de pendiente: al marcar uno se filtra la tabla -------------------
conteo = {}
for i in aprobadas:
    for p in i["meta"].get("pendientes", []):
        c = conteo.setdefault(p["regla"], {"Error": set(), "Alerta": set()})
        c[p["nivel"]].add(i["id"])
resumen = pd.DataFrame([{"Regla": r, "Qué revisa": R.REGLAS.get(r, ""), "Con error": len(c["Error"]), "Con alerta": len(c["Alerta"] - c["Error"])}
                        for r, c in sorted(conteo.items(), key=lambda x: -(len(x[1]["Error"]) * 100 + len(x[1]["Alerta"])))])
regla = None
if len(resumen):
    st.markdown("#### Qué falta por corregir")
    st.caption("Marca un tipo de pendiente para ver solo las convocatorias que lo tienen.")
    ev_r = st.dataframe(resumen, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                        key="sel_regla", height=min(320, 38 + 35 * len(resumen)),
                        column_config={"Qué revisa": st.column_config.TextColumn(width="large")})
    if ev_r and ev_r.selection.rows:
        regla = resumen.iloc[ev_r.selection.rows[0]]["Regla"]

# --- filtros y tabla --------------------------------------------------------------------
def _anio(d):
    p = R.periodo(d)
    return "Permanente" if p[0] == "permanente" else str(p[1] or "Sin fecha")


filas = [{"id": i["id"], "Convocatoria": i["datos"].get("Nombre de la Convocatoria", ""), "Actor": i["datos"].get("Nombre de la Fuente", ""),
          "Año": _anio(i["datos"]), "Modalidad": R.modalidad_corta(i["datos"].get("Modalidad")),
          "Carácter": i["datos"].get("Oficial / No Oficial", ""), "Errores": n_pend(i, "Error"), "Alertas": n_pend(i, "Alerta"),
          "Reglas": ", ".join(sorted({p["regla"] for p in i["meta"].get("pendientes", [])})),
          "Página": i["datos"].get("Cómo aplicar") if str(i["datos"].get("Cómo aplicar", "")).startswith("http") else None}
         for i in aprobadas]
tabla = pd.DataFrame(filas)
c1, c2, c3, c4 = st.columns([1.3, 1, 1.1, 1.6])
vista = c1.radio("Mostrar", ["Con errores", "Con alertas", "Todas"], horizontal=True, index=2 if regla else 0)
anios = c2.multiselect("Año", sorted(tabla["Año"].unique(), reverse=True), placeholder="Todos")
mods = c3.multiselect("Modalidad", sorted(tabla["Modalidad"].unique()), placeholder="Todas")
buscar = c4.text_input("Buscar por nombre o actor")
v = tabla
if vista == "Con errores":
    v = v[v["Errores"] > 0]
elif vista == "Con alertas":
    v = v[(v["Alertas"] > 0) & (v["Errores"] == 0)]
if regla:
    v = v[v["Reglas"].str.contains(regla, regex=False)]
    st.info(f"Filtrando por **{regla}** · {R.REGLAS.get(regla, '')}. Desmarca la fila del resumen para quitar el filtro.")
if anios:
    v = v[v["Año"].isin(anios)]
if mods:
    v = v[v["Modalidad"].isin(mods)]
if buscar:
    b = buscar.lower()
    v = v[v["Convocatoria"].str.lower().str.contains(b, regex=False) | v["Actor"].str.lower().str.contains(b, regex=False)]
v = v.sort_values(["Errores", "Alertas"], ascending=False)
st.caption(f"{len(v)} de {len(tabla)} convocatorias · marca una fila para corregirla; marca varias para retirarlas juntas.")
ev = st.dataframe(v.drop(columns="id"), hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                  key="sel_base", height=min(420, 38 + 35 * max(len(v), 1)),
                  column_config={"Página": st.column_config.LinkColumn(display_text="Abrir ↗"),
                                 "Convocatoria": st.column_config.TextColumn(width="large")})
ids = [v.iloc[n]["id"] for n in (ev.selection.rows if ev else []) if n < len(v)]

if len(ids) > 1:
    with st.container(border=True):
        st.markdown(f"**{len(ids)} convocatorias seleccionadas**")
        d1, d2 = st.columns([3, 1])
        motivo = d1.text_input("Motivo para retirarlas de la base", placeholder="Ej.: duplicadas en el mismo año")
        if d2.button("Retirar seleccionadas", type="primary", width="stretch"):
            if not motivo.strip():
                st.error("Escribe el motivo.")
            else:
                with A.lote(f"Retiradas {len(ids)} convocatorias de la base"):
                    for item in [i for i in aprobadas if i["id"] in ids]:
                        item["estado"], item["observacion"] = "Descartada", motivo
                        item["historial"].append({"fecha": ahora(), "usuario": YO["nombre"], "accion": "Retirada de la base", "detalle": motivo})
                        A.guardar_item(item)
                st.session_state["aviso_base"] = f"{len(ids)} convocatorias retiradas de la base."
                ui.recargar()
elif len(v):
    sel = ids[0] if ids else v.iloc[0]["id"]
    if not ids:
        st.caption("Mostrando la primera de la lista. Marca otra fila para cambiarla.")
    item = next(i for i in aprobadas if i["id"] == sel)
    st.markdown(f"### {item['datos'].get('Nombre de la Convocatoria', '')}")
    izq, der = st.columns([1.9, 1])
    with izq:
        datos = formulario(CTX, item["datos"], f"b_{item['id']}_")
    with der:
        enlace = datos.get("Cómo aplicar", "")
        if str(enlace).startswith("http"):
            st.link_button("Abrir la página oficial", enlace, width="stretch")
        st.markdown("#### Calidad del dato")
        norm, hallazgos = panel_validacion(CTX, datos, nuevo=False, excluir_id=item["id"])
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
        with st.expander("Historial y correcciones automáticas"):
            for h in item["historial"]:
                st.markdown(f"- {h['fecha']} · {h['usuario']}: {h['accion']} {('· ' + h['detalle']) if h.get('detalle') else ''}")
            cambios = item["meta"].get("cambios", [])
            if cambios:
                st.markdown("**Corregido automáticamente al migrar:**")
                st.dataframe(pd.DataFrame(cambios), hide_index=True, width="stretch")
else:
    st.info("Ninguna convocatoria cumple los filtros.")
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
    st.markdown("#### Actualizar desde Airtable")
    st.write("Para traer lo último que se registró en Airtable: descarga de nuevo el export (CSV) y cárgalo aquí. "
             "**No se borra nada del sistema.**")
    st.markdown("- Las convocatorias que **no están** se agregan, con las mismas correcciones de la migración.\n"
                "- Las que **ya están y nadie ha tocado aquí** se actualizan con lo que cambió en Airtable.\n"
                "- Las que **ya se editaron, revisaron, aprobaron o descartaron aquí** no se tocan: manda lo del sistema.\n"
                "- Si una fila es la misma convocatoria del mismo año que otra ya registrada, no se duplica.\n"
                "- Los actores nuevos se agregan al catálogo.")
    archivo = st.file_uploader("Export de Airtable (CSV o Excel)", type=["csv", "xlsx"], key="air_csv")
    todo_rev = st.checkbox("Enviar las nuevas a Revisar convocatorias", value=True,
                           help="Si se desmarca, las nuevas que tenían las tres verificaciones en Airtable entran directo a la base.")
    if archivo:
        from calidad import migracion as MG
        try:
            df_air = (pd.read_excel(archivo, dtype=str) if archivo.name.lower().endswith(".xlsx")
                      else pd.read_csv(archivo, dtype=str, encoding="utf-8-sig"))
            if "Nombre de la Convocatoria" not in df_air.columns:
                raise ValueError("no tiene la columna «Nombre de la Convocatoria»; ¿es el export de la tabla de convocatorias?")
            prev = MG.revisar_actualizacion(df_air, A)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo leer el archivo: {e}")
            prev = None
        if prev:
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Filas en el export", prev["filas"])
            p2.metric("Nuevas (se agregan)", prev["nuevas"])
            p3.metric("Ya están (se actualizan si cambiaron)", prev["se_pueden_actualizar"])
            p4.metric("Editadas aquí (no se tocan)", prev["editadas_aqui"] + prev["iguales_a_otra"])
            if st.button("Aplicar la actualización", type="primary", icon=":material/sync:"):
                from analitica.datos import cargar_tabla_tipos
                tipos = {k: v[0] for k, v in cargar_tabla_tipos().items() if v[1] == "Tabla"}
                with st.spinner("Actualizando…"):
                    res, det = MG.actualizar(df_air, A, tipos_corregidos=tipos, todo_a_revision=todo_rev)
                st.success(f"Listo: {res['nuevas']} nuevas ({res['a_la_base']} a la base, {res['a_revisar']} a Revisar "
                           f"convocatorias) · {res['actualizadas']} actualizadas · {res['sin_cambios']} sin cambios · "
                           f"{res['editadas_aqui'] + res['iguales_a_otra']} no se tocaron · "
                           f"{res['actores_nuevos']} actores nuevos.")
                if len(det):
                    st.dataframe(det, hide_index=True, width="stretch")
                st.cache_data.clear()
