"""Página: dashboard e informe automático, con las convocatorias aprobadas de la base propia."""
import io
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analitica import datos as D
from analitica import indicadores as I
from analitica import informe as INF

RAIZ = Path(__file__).resolve().parent
AZUL, NARANJA = "#2a78d6", "#eb6834"
COLOR = {"Oficial": AZUL, "No Oficial": NARANJA}
NAVY, GRIS, REJILLA = "#0B2545", "#52514e", "#e4e3df"
AZULES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

import ui  # noqa: E402

st.markdown(ui.ESTILOS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
@st.cache_data(ttl=120, show_spinner=False)
def cargar(incluir_revision):
    return D.desde_almacen(ui.almacen(), incluir_revision)


def estilo(fig, alto):
    fig.update_layout(
        template="plotly_white", height=alto, margin=dict(l=10, r=30, t=40, b=10),
        font=dict(family="Arial, sans-serif", size=13, color="#1B2A3A"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title=None),
        hoverlabel=dict(bgcolor="white", font_size=13), bargap=0.25, bargroupgap=0.08,
    )
    fig.update_xaxes(gridcolor=REJILLA, zeroline=False)
    fig.update_yaxes(gridcolor=REJILLA, zeroline=False)
    return fig


def envolver(t, ancho=32):
    import textwrap
    t = I.etiqueta(t).split(" (Asistencia")[0]
    return "<br>".join(textwrap.wrap(t, ancho)) or t


def barras_caracter(tabla, alto=None):
    t = tabla.iloc[::-1]
    fig = go.Figure()
    for serie in reversed(I.CARACTER):  # en barras horizontales la primera serie queda abajo
        fig.add_bar(y=[envolver(i) for i in t.index], x=t[serie], name=serie, orientation="h", marker_color=COLOR[serie],
                    text=t[serie].where(t[serie] > 0, ""), textposition="outside", cliponaxis=False,
                    customdata=[I.etiqueta(i) for i in t.index],
                    hovertemplate="%{customdata}<br>" + serie + ": %{x}<extra></extra>")
    fig.update_layout(barmode="group", legend=dict(traceorder="reversed"))
    fig.update_xaxes(range=[0, max(1, t[I.CARACTER].values.max()) * 1.15])
    return estilo(fig, alto or 100 + 50 * len(t))


def barras_simples(serie, color=AZUL, extra=None, total=None, alto=None, actores=False):
    s = serie.iloc[::-1]
    textos = []
    for k, v in s.items():
        t = f"{int(v)}" + (f" ({100 * v / total:.0f} %)" if total else "") + (f" · {extra[k]}" if extra and k in extra else "")
        textos.append(t)
    nombres = [envolver(I.corto(k) if actores else k, 36) for k in s.index]
    fig = go.Figure(go.Bar(y=nombres, x=s.values, orientation="h", marker_color=color,
                           text=textos, textposition="outside", cliponaxis=False,
                           customdata=[I.etiqueta(k) for k in s.index], hovertemplate="%{customdata}: %{x}<extra></extra>"))
    fig.update_xaxes(range=[0, max(1, s.max()) * (1.9 if extra else 1.3)])
    return estilo(fig, alto or 90 + 34 * len(s))


def texto(t):
    st.markdown(f"<div class='texto'>{t}</div>", unsafe_allow_html=True)


def lectura(t):
    """Análisis debajo de las gráficas: qué muestran las cifras y qué significan."""
    if t:
        texto(t)


# ---------------------------------------------------------------------------
st.title("Convocatorias internacionales")
st.caption("Dirección de Gestión de Demanda de Cooperación Internacional · APC-Colombia")

with st.sidebar:
    incluir = st.toggle("Incluir las que están en revisión", value=False,
                        help="Por defecto el dashboard y el informe usan solo la base revisada.")
    if st.button("Actualizar datos"):
        ui.recargar()
df_todo = cargar(incluir)
if df_todo.empty:
    st.info("La base aún no tiene convocatorias aprobadas.")
    st.stop()

# Filtros en una fila
minimo, maximo = df_todo["Registro"].min().date(), df_todo["Registro"].max().date()
c1, c2, c3, c4 = st.columns([1.3, 1, 1.4, 1.6])
rango = c1.date_input("Fecha de registro", (minimo, maximo), min_value=minimo, max_value=maximo, format="DD/MM/YYYY")
caracter = c2.multiselect("Carácter", I.CARACTER, default=I.CARACTER)
modalidades = sorted(df_todo["Modalidad"].dropna().unique())
modalidad = c3.multiselect("Modalidad", modalidades, default=modalidades)
tipos_presentes = [t for t in D.TIPOS if t in set(df_todo["Tipo de actor"])]
tipos = c4.multiselect("Tipo de actor", tipos_presentes, default=tipos_presentes)

desde, hasta = (rango if isinstance(rango, tuple) and len(rango) == 2 else (minimo, maximo))
df = df_todo[(df_todo["Registro"].dt.date >= desde) & (df_todo["Registro"].dt.date <= hasta)
             & df_todo["Carácter"].isin(caracter) & df_todo["Modalidad"].isin(modalidad) & df_todo["Tipo de actor"].isin(tipos)]

filtros = []
if (desde, hasta) != (minimo, maximo):
    filtros.append(f"registro del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
if set(caracter) != set(I.CARACTER):
    filtros.append("carácter: " + ", ".join(caracter))
if set(modalidad) != set(modalidades):
    filtros.append("modalidad: " + ", ".join(modalidad))
if set(tipos) != set(tipos_presentes):
    filtros.append("tipo de actor: " + ", ".join(tipos))
if incluir:
    filtros.append("incluye convocatorias en revisión")
texto_filtros = "; ".join(filtros) or "Sin filtros (todas las convocatorias de la base revisada)"

if df.empty:
    st.warning("No hay convocatorias con estos filtros.")
    st.stop()

ind = I.calcular(df, corte=df_todo["Registro"].max())
n = ind.n
MOD_COLOR = {"Beca": "#2a78d6", "Subvención": "#eb6834", "Premio": "#1a9e77", "Cooperación técnica": "#8a63d2"}


def color_mod(k):
    return MOD_COLOR.get(str(k).split(" (")[0], "#9aa4b1")


# En pocas palabras: lo que cualquier persona debe saber, sin leer las gráficas
st.markdown("<div style='background:#EEF3F9;border-left:5px solid #0B2545;border-radius:8px;padding:14px 18px;margin:4px 0 14px'>"
            "<div style='font-weight:700;color:#0B2545;margin-bottom:6px'>Principales resultados</div>"
            + "".join(f"<div style='margin:3px 0'>• {m}</div>" for m in ind.textos["mensajes"]) + "</div>",
            unsafe_allow_html=True)
k = st.columns(5)
for col, (v, lab) in zip(k, [
    (I.fmt_n(ind.total), "convocatorias"),
    (I.fmt_n(n["abiertas"]), "abiertas hoy"),
    (I.fmt_n(n["cierran_30"]), "cierran en 30 días"),
    (I.fmt_pct(I.pct(n["oficial"], ind.total)), "son oferta oficial"),
    (I.fmt_n(n["actores"]), "entidades oferentes"),
]):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{lab}</div></div>", unsafe_allow_html=True)
st.write("")

tabs = st.tabs(["Resumen", "Abiertas y cierres", "Quién ofrece", "Temas y público", "Calidad del dato", "Datos", "Informe"])

with tabs[0]:
    a, b = st.columns([1, 1.25])
    with a:
        st.subheader("¿Oficial o no oficial?")
        fig = go.Figure(go.Pie(labels=["Oficial", "No oficial"], values=[n["oficial"], n["no_oficial"]], hole=0.62, sort=False,
                               marker=dict(colors=[AZUL, NARANJA], line=dict(color="white", width=2)),
                               texttemplate="%{percent:.0%}", textfont=dict(size=15, color="white"),
                               hovertemplate="%{label}: %{value} convocatorias (%{percent})<extra></extra>"))
        fig.add_annotation(text=f"<b>{I.fmt_n(ind.total)}</b><br>convocatorias", showarrow=False, font=dict(size=15, color=NAVY))
        st.plotly_chart(estilo(fig, 300), width="stretch")
        st.caption("Oficial: gobiernos, agencias de cooperación y organismos internacionales. "
                   "No oficial: fundaciones, ONG, universidades y empresas.")
    with b:
        st.subheader("¿Qué tipo de convocatorias?")
        mod = ind.conteo("Modalidad")
        fig = go.Figure(go.Bar(y=[str(i).split(" (")[0] for i in mod.index][::-1], x=mod.values[::-1], orientation="h",
                               marker_color=[color_mod(i) for i in mod.index][::-1],
                               text=[f"{v} ({100 * v / ind.total:.0f} %)" for v in mod.values[::-1]], textposition="outside",
                               cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>"))
        fig.update_xaxes(range=[0, max(1, mod.max()) * 1.3])
        st.plotly_chart(estilo(fig, 300), width="stretch")
    st.subheader("¿Cuántas se registran cada mes?")
    pm = ind.por_mes()
    fig = go.Figure()
    for serie in I.CARACTER:
        fig.add_bar(x=[I.mes_corto(p) for p in pm.index], y=pm[serie], name=serie.replace("No Oficial", "No oficial"),
                    marker_color=COLOR[serie], hovertemplate="%{x}<br>" + serie + ": %{y}<extra></extra>")
    if ind.corte < pm.index[-1].end_time.normalize():
        fig.add_vrect(x0=len(pm) - 1.5, x1=len(pm) - 0.5, fillcolor="#f0efec", line_width=0, layer="below",
                      annotation_text="mes en curso", annotation_position="top")
    fig.update_layout(barmode="stack", hovermode="x unified")
    st.plotly_chart(estilo(fig, 340), width="stretch")
    lectura(ind.textos["lecturas"]["resumen"])

with tabs[1]:
    st.subheader("¿Cuándo cierran las convocatorias abiertas?")
    cm = ind.cierres_por_mes(6)
    if cm.empty or not cm.values.sum():
        st.info("No hay convocatorias abiertas con fecha límite en los filtros seleccionados.")
    else:
        fig = go.Figure()
        for col in cm.columns:
            fig.add_bar(x=[I.mes_corto(p) for p in cm.index], y=cm[col], name=str(col).split(" (")[0], marker_color=color_mod(col),
                        hovertemplate="%{x}<br>" + str(col).split(" (")[0] + ": %{y}<extra></extra>")
        fig.update_layout(barmode="stack", hovermode="x unified", showlegend=True)
        st.plotly_chart(estilo(fig, 270), width="stretch")
        st.caption(f"Convocatorias abiertas hoy ({ind.hoy:%d/%m/%Y}) según el mes de su fecha límite. "
                   "Las permanentes no aparecen porque no tienen fecha límite.")
    prox = ind.proximas(None)
    if len(prox):
        st.subheader(f"Las {len(prox)} convocatorias abiertas, de la que cierra primero a la última")
        dias = (prox["Cierre"] - ind.hoy).dt.days
        tabla = pd.DataFrame({
            "": ["🔴" if d < 15 else "🟠" if d <= 37 else "🟢" for d in dias],
            "Convocatoria": prox["Nombre de la Convocatoria"].str.split(" \\(").str[0],
            "Quién la ofrece": prox["Actor"].map(I.corto), "Tipo": prox["Modalidad"].astype(str).str.split(" \\(").str[0],
            "Cierra": prox["Cierre"].dt.strftime("%d/%m/%Y"), "Días": dias.astype(int), "Página": prox["Cómo aplicar"]})
        st.dataframe(tabla, hide_index=True, width="stretch",
                     column_config={"Página": st.column_config.LinkColumn(display_text="Abrir ↗"),
                                    "": st.column_config.TextColumn(width=30),
                                    "Convocatoria": st.column_config.TextColumn(width="large")})
        st.caption("🔴 menos de 15 días · 🟠 hasta 37 días · 🟢 más plazo")
    lectura(ind.textos["lecturas"]["abiertas"])

with tabs[2]:
    vista = st.radio("Ver", ["Todas", "Oficial", "No oficial"], horizontal=True, label_visibility="collapsed")
    sub = df if vista == "Todas" else df[df["Carácter"] == ("Oficial" if vista == "Oficial" else "No Oficial")]
    color = {"Todas": "#256abf", "Oficial": AZUL, "No oficial": NARANJA}[vista]
    texto(ind.textos["oficial"] if vista == "Oficial" else ind.textos["no_oficial"] if vista == "No oficial" else
          ind.textos["oficial"] + " " + ind.textos["no_oficial"])
    if len(sub):
        a, b = st.columns([1, 1.3])
        with a:
            st.subheader("Por tipo de entidad")
            st.plotly_chart(barras_simples(sub["Tipo de actor"].value_counts(), color, total=len(sub)), width="stretch")
        with b:
            st.subheader("Quién ofrece más")
            g = sub.groupby(["Actor", "Tipo de actor"]).size().reset_index(name="Convocatorias")
            top = g.sort_values(["Convocatorias", "Actor"], ascending=[False, True]).head(12)
            st.plotly_chart(barras_simples(top.set_index("Actor")["Convocatorias"], color,
                                           dict(zip(top["Actor"], top["Tipo de actor"].str.split(" /").str[0])), actores=True),
                            width="stretch")
        lectura(ind.textos["lecturas"]["quien"])
        if vista != "Oficial":
            with st.expander("Actores privados y de la sociedad civil (detalle)"):
                no = df[df["Carácter"] == "No Oficial"]
                priv = no[no["Tipo de actor"].isin(D.PRIVADOS)]
                st.dataframe(priv.groupby(["Tipo de actor", "Actor"]).size().reset_index(name="Convocatorias")
                             .sort_values(["Tipo de actor", "Convocatorias"], ascending=[True, False]), hide_index=True, width="stretch")

with tabs[3]:
    texto(ind.textos["tematicas"])
    st.subheader("Temas más frecuentes")
    st.plotly_chart(barras_caracter(ind.por_caracter("Áreas temáticas de interés", multi=True, top=10)), width="stretch")
    conteos, partes = ind.temas_por_trimestre(10)
    if partes.shape[1] >= 1:
        with st.expander("¿Cómo cambian los temas en el tiempo?"):
            cols = [f"T{q.quarter} {q.year}" + (" (en curso)" if ind.corte < q.end_time.normalize() else "") for q in partes.columns]
            fig = go.Figure(go.Heatmap(
                z=partes.values, x=cols, y=[I.etiqueta(i) for i in partes.index], colorscale=[[i / 6, c] for i, c in enumerate(AZULES)],
                text=[[f"{v:.0f} % ({int(c)})" for v, c in zip(fila_p, fila_c)] for fila_p, fila_c in zip(partes.values, conteos.values)],
                texttemplate="%{text}", hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>", xgap=3, ygap=3,
                colorbar=dict(title="%", thickness=12)))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(estilo(fig, 90 + 44 * len(partes)), width="stretch")
            st.caption("Porcentaje de las convocatorias de cada trimestre que incluyen el tema; entre paréntesis, el número.")
    texto(ind.textos["publico"])
    a, b = st.columns(2)
    with a:
        st.subheader("¿A quién se dirigen?")
        st.plotly_chart(barras_simples(ind.conteo("Dirigida a (tipo de publico)", multi=True).drop(index=["Sin dato"], errors="ignore")
                                       .head(8), "#1a9e77", total=ind.total), width="stretch")
    with b:
        st.subheader("Poblaciones que se priorizan")
        pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
        pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore").head(8)
        st.plotly_chart(barras_simples(pobl, "#1a9e77", total=ind.total), width="stretch")
    lectura(ind.textos["lecturas"]["publico"])
    with st.expander("Alineación con los sectores CAD y los ODS"):
        texto(ind.textos["alineacion"])
        a, b = st.columns(2)
        with a:
            st.subheader("Sectores CAD")
            st.plotly_chart(barras_caracter(ind.por_caracter("Comite de Ayuda al Desarrollo", top=10)), width="stretch")
        with b:
            st.subheader("ODS")
            st.plotly_chart(barras_caracter(ind.por_caracter("ODS", top=10)), width="stretch")

with tabs[4]:
    inc = ind.inconsistencias()
    st.subheader("Puntos para revisar en la base")
    st.markdown(f"- **{len(inc['actores_en_ambos'])} actores** aparecen como oficiales y como no oficiales.")
    if inc["actores_en_ambos"]:
        st.dataframe(pd.DataFrame({"Actor": inc["actores_en_ambos"]}), hide_index=True, width="stretch")
    st.markdown(f"- **{len(inc['no_oficial_con_actor_publico'])} convocatorias no oficiales** tienen como actor un gobierno o un organismo multilateral.")
    if len(inc["no_oficial_con_actor_publico"]):
        st.dataframe(inc["no_oficial_con_actor_publico"], hide_index=True, width="stretch")
    st.markdown(f"- **{inc['sin_actor']}** convocatorias sin nombre de actor · **{inc['por_clasificar']}** con actor sin tipo · "
                f"**{inc['tipo_sugerido']}** con tipo de actor sugerido por reglas (no revisado).")

with tabs[5]:
    columnas = ["Nombre de la Convocatoria", "Carácter", "Actor", "Tipo de actor", "Modalidad", "Fecha de Registro",
                "Fecha Límite de Aplicación", "Áreas temáticas de interés", "Dirigida a (tipo de publico)", "ODS",
                "Comite de Ayuda al Desarrollo", "Cómo aplicar"]
    st.dataframe(df[columnas], hide_index=True, width="stretch",
                 column_config={"Cómo aplicar": st.column_config.LinkColumn("Cómo aplicar")})
    buf = io.BytesIO()
    df[columnas].to_excel(buf, index=False)
    st.download_button("Descargar en Excel", buf.getvalue(), f"convocatorias_filtradas_{date.today():%Y-%m-%d}.xlsx")

with tabs[6]:
    st.subheader("Informe automático")
    st.write("Genera un informe de **3 páginas**, en lenguaje sencillo, con los filtros actuales: lo más importante y las "
             "cifras clave; quién ofrece, en qué temas y para quién; y las convocatorias abiertas que cierran primero, con "
             "enlace a su página oficial.")
    st.caption(f"Filtros: {texto_filtros}")
    pdf = st.checkbox("Generar también PDF", value=True, help="El PDF se genera directamente en el servidor, sin LibreOffice ni Word.")
    if st.button("Generar informe", type="primary"):
        with st.spinner("Generando informe…"):
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / f"Informe_convocatorias_{date.today():%Y-%m-%d}.docx"
                ruta_docx, ruta_pdf = INF.generar(df, ruta, texto_filtros, pdf=pdf, corte=df_todo["Registro"].max())
                st.session_state["informe_docx"] = (ruta_docx.name, ruta_docx.read_bytes())
                st.session_state["informe_pdf"] = (ruta_pdf.name, ruta_pdf.read_bytes()) if ruta_pdf else None
        if pdf and not st.session_state.get("informe_pdf"):
            st.info("No se pudo crear el PDF. Descarga el Word y guárdalo como PDF.")
    if st.session_state.get("informe_docx"):
        nombre, datos = st.session_state["informe_docx"]
        st.download_button("Descargar Word", datos, nombre,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if st.session_state.get("informe_pdf"):
        nombre, datos = st.session_state["informe_pdf"]
        st.download_button("Descargar PDF", datos, nombre, mime="application/pdf")
