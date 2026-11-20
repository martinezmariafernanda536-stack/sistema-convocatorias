"""Página de inicio: lo que requiere atención hoy, con acceso directo a cada tarea."""
import json
from datetime import date

import pandas as pd
import streamlit as st

import tareas
import ui
from bandeja import flujo as F
from calidad import reglas as R

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()
A = ui.almacen()
HOY = date.today()


@st.cache_data(ttl=60, show_spinner=False)
def leer():
    return A.items(), A.catalogo().filas()


items, catalogo = leer()
por_estado = {e: [i for i in items if i["estado"] == e] for e in ("Por revisar", "Actor pendiente de crear", "Aprobada", "Por completar")}


def dias_para_cierre(d):
    f = R.fecha(d.get("Fecha Límite de Aplicación"))
    return (f - HOY).days if f else None


def n_errores(i):
    return sum(1 for h in F.pendientes(i) if h["nivel"] == "Error")


revisar = por_estado["Por revisar"]
nuevas_7 = [i for i in revisar if not i["origen"].startswith("Migración") and i["ingreso"][:10] >= (HOY - pd.Timedelta(days=7)).isoformat()]
cierran = [i for i in revisar if (d := dias_para_cierre(i["datos"])) is not None and 0 <= d <= 30]
cerradas = [i for i in revisar if (d := dias_para_cierre(i["datos"])) is not None and d < 0]
actores_pend = [f for f in catalogo if f["estado_ciclope"] != "Creado en CICLOPE"]
base_err = [i for i in por_estado["Aprobada"] if sum(1 for p in i["meta"].get("pendientes", []) if p["nivel"] == "Error")]
abiertas = [i for i in por_estado["Aprobada"] if (d := dias_para_cierre(i["datos"])) is not None and d >= 0]

nombre = YO["nombre"].split()[0]
st.title(f"Hola, {nombre}")
st.caption(f"Lo que requiere atención hoy, {HOY.day}/{HOY.month}/{HOY.year}.")

reg_mapeo = json.loads(A.leer_archivo("ultimo_mapear.json") or b"{}")
if not tareas.en_curso():
    if not reg_mapeo:
        paso = ("**Tu primer paso:** ejecuta la primera búsqueda de convocatorias. Tarda un rato, pero puedes cerrar la pestaña.",
                "paginas/mapeo.py", "Buscar convocatorias")
    elif cierran:
        paso = (f"**Tu siguiente paso:** revisa las **{len(cierran)}** convocatorias que cierran en los próximos 30 días.",
                "paginas/bandeja.py", "Revisarlas ahora")
    elif revisar:
        paso = (f"**Tu siguiente paso:** hay **{len(revisar)}** convocatorias esperando revisión.",
                "paginas/bandeja.py", "Revisarlas ahora")
    else:
        paso = ("**Todo al día.** Puedes ejecutar una nueva búsqueda o consultar el dashboard.", "paginas/mapeo.py",
                "Buscar convocatorias")
    with st.container(border=True):
        a, b, c_ = st.columns([3.2, 1.1, 1])
        a.markdown(paso[0])
        b.page_link(paso[1], label=paso[2], icon=":material/arrow_forward:")
        c_.page_link("paginas/guia.py", label="Cómo se usa", icon=":material/help:")

if tareas.en_curso():
    t = tareas.actual()
    st.info(f"⏳ **{t.etiqueta}** en curso desde hace {t.minutos()} min (la inició {t.usuario}). "
            "Lo encontrado va llegando a la bandeja.")


def tarjeta(col, valor, texto, detalle, pagina, etiqueta, alerta=False):
    with col.container(border=True):
        color = "#B42318" if alerta and valor else "#0B2545"
        st.markdown(f"<div style='font-size:2.1rem;font-weight:700;color:{color};line-height:1.1'>{valor}</div>"
                    f"<div style='font-weight:600;margin-top:2px'>{texto}</div>"
                    f"<div style='color:#5b6472;font-size:.85rem;min-height:2.4em'>{detalle}</div>", unsafe_allow_html=True)
        st.page_link(pagina, label=etiqueta, icon=":material/arrow_forward:")


c = st.columns(4)
tarjeta(c[0], len(revisar), "por revisar", f"{len(nuevas_7)} llegaron esta semana · {len(cierran)} cierran en 30 días",
        "paginas/bandeja.py", "Revisarlas", alerta=bool(cierran))
tarjeta(c[1], len(actores_pend), "actores por crear en CICLOPE",
        f"{len(por_estado['Actor pendiente de crear'])} convocatorias esperan a que se creen",
        "paginas/bandeja.py", "Ver actores pendientes")
tarjeta(c[2], len(base_err), "convocatorias de la base con errores", "Datos por corregir en la base revisada",
        "paginas/base.py", "Corregir en la base", alerta=bool(base_err))
tarjeta(c[3], len(abiertas), "convocatorias abiertas en la base", f"de {len(por_estado['Aprobada'])} en total",
        "paginas/tablero.py", "Ver dashboard e informes")

if por_estado["Por completar"]:
    q1, q2 = st.columns([4, 1.1])
    q1.info(f"**{len(por_estado['Por completar'])} convocatorias encontradas esperan completarse** (no están en español o les "
            "faltan datos). No llegan a la bandeja hasta quedar completas; el sistema las reintenta en cada búsqueda.")
    q2.page_link("paginas/mapeo.py", label="Ver cuáles", icon=":material/arrow_forward:")

if cerradas:
    w1, w2 = st.columns([4, 1.1])
    w1.warning(f"**{len(cerradas)} convocatorias por revisar ya cerraron.** En Revisar convocatorias pulsa «Mostrar las cerradas», "
               "márcalas y descártalas de una vez con el motivo «Ya cerró».")
    w2.page_link("paginas/bandeja.py", label="Ir a descartarlas", icon=":material/arrow_forward:")

izq, der = st.columns([1.35, 1])
with izq:
    st.markdown("#### Cierran pronto")
    st.caption("Convocatorias abiertas, en la base o por revisar, ordenadas por fecha de cierre.")
    proximas = []
    for i in por_estado["Aprobada"] + revisar:
        d = dias_para_cierre(i["datos"])
        if d is not None and 0 <= d <= 45:
            proximas.append({"Cierra en": f"{'🔴' if d < 15 else '🟠' if d <= 37 else '🟢'} {d} días",
                             "Convocatoria": i["datos"].get("Nombre de la Convocatoria", ""),
                             "Modalidad": R.modalidad_corta(i["datos"].get("Modalidad")),
                             "Estado": "En la base" if i["estado"] == "Aprobada" else "Por revisar", "_d": d,
                             "Página": i["datos"].get("Cómo aplicar") if str(i["datos"].get("Cómo aplicar", "")).startswith("http") else None})
    if proximas:
        tabla = pd.DataFrame(proximas).sort_values("_d").drop(columns="_d").head(12)
        st.dataframe(tabla, hide_index=True, width="stretch",
                     column_config={"Página": st.column_config.LinkColumn(display_text="Abrir ↗"),
                                    "Convocatoria": st.column_config.TextColumn(width="large")})
    else:
        st.write("No hay convocatorias que cierren en los próximos 45 días.")

with der:
    st.markdown("#### Lo último que llegó a la bandeja")
    recientes = sorted([i for i in revisar if not i["origen"].startswith("Migración")], key=lambda i: i["ingreso"], reverse=True)[:8]
    if recientes:
        for i in recientes:
            d = i["datos"]
            origen = i["origen"].split(" · ")[0]
            marca = "✅" if not n_errores(i) else "✏️"
            st.markdown(f"{marca} **{d.get('Nombre de la Convocatoria', '')[:80]}**  \n"
                        f"<span style='color:#5b6472;font-size:.85rem'>{d.get('Nombre de la Fuente', '')[:50]} · "
                        f"{R.modalidad_corta(d.get('Modalidad'))} · {origen} · {i['ingreso'][:10]}</span>", unsafe_allow_html=True)
        st.page_link("paginas/bandeja.py", label="Revisarlas", icon=":material/fact_check:")
    else:
        st.write("Todavía no ha llegado nada del mapeo. Ejecuta una búsqueda desde Buscar convocatorias.")

    st.markdown("#### Última búsqueda automática")
    reg = reg_mapeo
    if reg:
        st.write(f"{reg.get('fecha', '')} · {reg.get('usuario', '')} · {reg.get('estado', 'Terminada').lower()}")
        resumen = [l for l in reg.get("log", []) if "Listo:" in l or "enviadas a la bandeja" in l]
        for l in resumen[-2:]:
            st.caption(l[6:] if l[:2].isdigit() else l)
    else:
        st.write("Aún no se ha ejecutado.")
    st.page_link("paginas/mapeo.py", label="Ir a Buscar convocatorias", icon=":material/travel_explore:")
