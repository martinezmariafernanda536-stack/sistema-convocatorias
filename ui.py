"""Piezas compartidas por todas las páginas: base de datos, usuario y estilos."""
import streamlit as st

from bandeja.almacen import abrir

NAVY = "#0B2545"
AZUL, VERDE, NARANJA, MORADO, OCRE = "#2a78d6", "#1a9e77", "#eb6834", "#8a63d2", "#c98a00"  # los de los gráficos

# Un solo bloque de CSS (unos 5 KB, sin imágenes ni librerías): fondo claro, color en los acentos.
ESTILOS = f"""<style>
 :root {{--navy:{NAVY}; --azul:{AZUL}; --verde:{VERDE}; --naranja:{NARANJA}; --morado:{MORADO}; --ocre:{OCRE};
         --borde:#e3e9f2; --suave:#f5f8fc; --sombra:0 1px 2px rgba(11,37,69,.06), 0 2px 8px rgba(11,37,69,.05)}}
 .block-container {{padding-top:3.2rem; max-width:1450px}}
 h1,h2,h3,h4 {{color:var(--navy); letter-spacing:-.01em}}
 h1 {{font-weight:800}}
 h1::after {{content:""; display:block; width:72px; height:4px; margin-top:.45rem; border-radius:4px;
            background:linear-gradient(90deg,var(--azul),var(--verde),var(--ocre))}}
 /* franja de color bajo la barra superior */
 [data-testid="stHeader"] {{background:rgba(255,255,255,.92); border-bottom:3px solid transparent;
     border-image:linear-gradient(90deg,var(--navy),var(--azul),var(--verde),var(--ocre)) 1}}
 /* menú lateral */
 [data-testid="stSidebar"] {{background:linear-gradient(180deg,#edf3fb 0%,#f7f9fc 100%); border-right:1px solid var(--borde)}}
 [data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"]
     {{background:var(--navy)!important; border-radius:8px}}
 [data-testid="stSidebarNavLink"][aria-current="page"] span, [data-testid="stSidebarNavLink"][aria-current="page"] *
     {{color:#fff!important}}
 [data-testid="stSidebarNavLink"]:hover {{background:#dde8f7}}
 [data-testid="stNavSectionHeader"], [data-testid="stSidebarNavSeparator"] + div {{color:var(--azul)!important;
     font-weight:700; text-transform:uppercase; font-size:.72rem; letter-spacing:.06em}}
 /* tarjetas de cifras: blancas, con una barra de color que cambia según la posición */
 .kpi {{background:#fff; border:1px solid var(--borde); border-left:5px solid var(--azul); border-radius:12px;
        padding:14px 16px; box-shadow:var(--sombra)}}
 .kpi .v {{font-size:30px; font-weight:800; color:var(--navy); line-height:1.1}}
 .kpi .l {{font-size:13px; color:#52514e}}
 [data-testid="stColumn"]:nth-child(5n+2) .kpi {{border-left-color:var(--verde)}}
 [data-testid="stColumn"]:nth-child(5n+3) .kpi {{border-left-color:var(--naranja)}}
 [data-testid="stColumn"]:nth-child(5n+4) .kpi {{border-left-color:var(--morado)}}
 [data-testid="stColumn"]:nth-child(5n+5) .kpi {{border-left-color:var(--ocre)}}
 [data-testid="stMetric"] {{background:#fff; border:1px solid var(--borde); border-left:5px solid var(--azul);
        border-radius:12px; padding:10px 14px; box-shadow:var(--sombra)}}
 [data-testid="stColumn"]:nth-child(4n+2) [data-testid="stMetric"] {{border-left-color:var(--verde)}}
 [data-testid="stColumn"]:nth-child(4n+3) [data-testid="stMetric"] {{border-left-color:var(--naranja)}}
 [data-testid="stColumn"]:nth-child(4n+4) [data-testid="stMetric"] {{border-left-color:var(--morado)}}
 [data-testid="stMetricValue"] {{color:var(--navy); font-weight:800}}
 /* tarjetas de Inicio: franja de color arriba */
 [class*="st-key-tarjeta_"] {{border-top:5px solid var(--azul)!important; background:#fff}}
 [data-testid="stColumn"]:nth-child(4n+2) [class*="st-key-tarjeta_"] {{border-top-color:var(--verde)!important}}
 [data-testid="stColumn"]:nth-child(4n+3) [class*="st-key-tarjeta_"] {{border-top-color:var(--naranja)!important}}
 [data-testid="stColumn"]:nth-child(4n+4) [class*="st-key-tarjeta_"] {{border-top-color:var(--morado)!important}}
 /* recuadros, desplegables y tablas */
 [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stLayoutWrapper"] > div[class*="border"]
     {{border-radius:12px}}
 div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {{box-shadow:var(--sombra)}}
 [data-testid="stExpander"] details {{border-radius:10px; border-color:var(--borde)}}
 [data-testid="stExpander"] summary {{background:var(--suave); border-radius:10px}}
 [data-testid="stExpander"] summary:hover {{color:var(--azul)}}
 [data-testid="stDataFrame"] {{border-radius:10px; overflow:hidden; border:1px solid var(--borde)}}
 /* pestañas */
 .stTabs [data-baseweb="tab-list"] {{gap:4px; border-bottom:1px solid var(--borde)}}
 .stTabs [data-baseweb="tab"] {{padding:6px 12px; border-radius:8px 8px 0 0}}
 .stTabs [data-baseweb="tab"]:hover {{background:var(--suave); color:var(--azul)}}
 .stTabs [aria-selected="true"] {{color:var(--azul)!important; font-weight:700; background:#eef4fd}}
 .stTabs [data-baseweb="tab-highlight"] {{background:var(--azul); height:3px}}
 /* botones: el principal en azul institucional, aunque falte el archivo de tema */
 button[kind^="primary"], [data-testid^="stBaseButton-primary"] {{background:linear-gradient(90deg,var(--navy),#1b4f8f)!important;
     border:0!important; color:#fff!important; box-shadow:0 2px 6px rgba(11,37,69,.18)}}
 button[kind^="primary"]:hover, [data-testid^="stBaseButton-primary"]:hover {{filter:brightness(1.12)}}
 /* etiquetas de los filtros (las «píldoras» de las listas de selección) */
 [data-baseweb="tag"] {{background:var(--navy)!important}}
 button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {{border-color:var(--azul)!important;
     color:var(--azul)!important}}
 [data-testid="stPageLink"] a {{border-radius:8px}}
 [data-testid="stPageLink"] a:hover {{background:#eef4fd}}
 [data-testid="stPageLink"] a span {{color:var(--azul); font-weight:600}}
 /* textos de apoyo de las páginas */
 .texto {{background:var(--suave); border-left:4px solid var(--azul); border-radius:8px; padding:12px 16px; color:#1B2A3A;
          font-size:15px; margin-bottom:8px}}
 .err {{background:#FBE4E1; border-left:4px solid #c0392b; border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .ale {{background:#FFF4CC; border-left:4px solid var(--ocre); border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .ok  {{background:#DDF1EC; border-left:4px solid var(--verde); border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .meta {{background:var(--suave); border-radius:6px; padding:8px 12px; font-size:13.5px; margin-bottom:8px}}
 .paso {{font-weight:700; font-size:1.05rem; color:var(--navy); margin:14px 0 6px; padding:4px 0 4px 10px;
         border-left:4px solid var(--azul); background:linear-gradient(90deg,#eef4fd,transparent)}}
</style>"""


def secretos():
    try:
        return dict(st.secrets)
    except Exception:  # noqa: BLE001 - sin secrets.toml
        return {}


@st.cache_resource
def almacen():
    return abrir(secretos())


def usuario():
    return st.session_state.get("usuario")


def recargar():
    st.cache_data.clear()
    st.rerun()
