"""Página: mi cuenta (cambiar contraseña y códigos de recuperación)."""
import streamlit as st

import ui
from bandeja import usuarios as U

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()
A = ui.almacen()
st.title("Mi cuenta")
st.caption(f"{YO['nombre']} · usuario **{YO['usuario']}** · {YO['rol']}")

c1, c2 = st.columns(2)
with c1:
    st.markdown("#### Cambiar contraseña")
    st.caption(U.POLITICA)
    with st.form("cambiar", clear_on_submit=True):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        nueva2 = st.text_input("Repite la contraseña nueva", type="password")
        ok = st.form_submit_button("Cambiar contraseña", type="primary")
    if ok:
        try:
            U.cambiar_clave(A, YO["usuario"], actual, nueva, nueva2)
            st.success("Contraseña cambiada.")
        except (U.ErrorClave, ValueError) as e:
            st.error(str(e))
with c2:
    st.markdown("#### Códigos de recuperación")
    n = U.codigos_disponibles(A, YO["usuario"])
    st.write(f"Te quedan **{n}** códigos sin usar. Sirven para recuperar el acceso desde la pantalla de ingreso, "
             "en «¿Olvidaste tu contraseña?».")
    st.caption("Al generar códigos nuevos, los anteriores dejan de servir.")
    clave = st.text_input("Confirma con tu contraseña", type="password", key="conf_cod")
    if st.button("Generar códigos nuevos"):
        u, mensaje = U.verificar(A, YO["usuario"], clave)
        if not u:
            st.error(mensaje)
        else:
            codigos = U.generar_codigos(A, YO["usuario"])
            st.warning("Guárdalos ahora: no se vuelven a mostrar.")
            st.code("\n".join(codigos))
            st.download_button("Descargar (.txt)", "\n".join(codigos), f"codigos_recuperacion_{YO['usuario']}.txt")
