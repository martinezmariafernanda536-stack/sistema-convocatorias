"""Piezas compartidas por todas las páginas: base de datos, usuario y estilos."""
import streamlit as st

from bandeja.almacen import abrir

NAVY = "#0B2545"
ESTILOS = f"""<style>
 .block-container {{padding-top:1.4rem; max-width:1450px}}
 h1,h2,h3 {{color:{NAVY}}}
 .kpi {{background:#F3F6FA; border-radius:10px; padding:14px 16px;}}
 .kpi .v {{font-size:30px; font-weight:700; color:{NAVY}; line-height:1.1}}
 .kpi .l {{font-size:13px; color:#52514e}}
 .texto {{background:#F3F6FA; border-radius:8px; padding:12px 16px; color:#1B2A3A; font-size:15px; margin-bottom:8px}}
 .err {{background:#FBE4E1; border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .ale {{background:#FFF4CC; border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .ok  {{background:#DDF1EC; border-radius:6px; padding:6px 10px; margin-bottom:4px; font-size:14px}}
 .meta {{background:#F3F6FA; border-radius:6px; padding:8px 12px; font-size:13.5px; margin-bottom:8px}}
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
