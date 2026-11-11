"""Página: usuarios (solo administradores)."""
import pandas as pd
import streamlit as st

import ui
from bandeja import usuarios as U

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
A = ui.almacen()
st.title("Usuarios")
st.caption("Acceso con usuario y contraseña. Las contraseñas se guardan cifradas y las cuentas también, "
           "cuando el repositorio de datos es público. " + U.POLITICA)

filas = A.todos_los_usuarios()
if filas:
    df = pd.DataFrame(filas)
    df["activo"] = df["activo"].map({1: "Sí", 0: "No"})
    df["debe_cambiar"] = df["debe_cambiar"].map({True: "Temporal (debe cambiarla)", False: "Propia"})
    df["bloqueado"] = df["bloqueado"].map({True: "Bloqueada 15 min", False: ""})
    df["permisos"] = df["rol"].map(U.ROLES)
    st.dataframe(df.rename(columns={"usuario": "Usuario", "nombre": "Nombre", "rol": "Rol", "activo": "Activo",
                                    "debe_cambiar": "Contraseña", "bloqueado": "Estado", "codigos": "Códigos de recuperación",
                                    "permisos": "Permisos"}), hide_index=True, width="stretch")

c1, c2 = st.columns(2)
with c1:
    st.markdown("#### Crear usuario")
    with st.form("nuevo_usuario", clear_on_submit=True):
        usuario = st.text_input("Usuario", help="Letras sin tildes, números, punto o guion. Ejemplo: maria.perez")
        nombre = st.text_input("Nombre completo")
        rol = st.selectbox("Rol", list(U.ROLES), format_func=lambda r: f"{r} · {U.ROLES[r]}")
        crear = st.form_submit_button("Crear", type="primary")
    if crear:
        try:
            if usuario.strip().lower() in A.cuentas():
                raise ValueError("Ese usuario ya existe. Para darle una contraseña nueva usa «Restablecer contraseña».")
            clave = U.crear(A, usuario, nombre, rol)
            st.success(f"Usuario **{usuario.strip().lower()}** creado. Contraseña temporal: `{clave}`. "
                       "Entrégasela a la persona: no se vuelve a mostrar y el sistema le pedirá cambiarla al entrar.")
        except ValueError as e:
            st.error(str(e))
    st.markdown("#### Restablecer contraseña")
    st.caption("Para quien olvidó su contraseña y no tiene códigos de recuperación, o tiene la cuenta bloqueada.")
    if filas:
        ur = st.selectbox("Usuario", [f["usuario"] for f in filas], key="u_rest")
        if st.button("Restablecer"):
            clave = U.restablecer(A, ur)
            st.success(f"Contraseña temporal de **{ur}**: `{clave}`. Se cambia al entrar. Desbloquea la cuenta si estaba bloqueada.")
with c2:
    st.markdown("#### Activar o desactivar")
    if filas:
        u = st.selectbox("Usuario", [f["usuario"] for f in filas])
        actual = next(f for f in filas if f["usuario"] == u)["activo"]
        if st.button("Desactivar" if actual else "Activar"):
            if u == ui.usuario()["usuario"]:
                st.error("No puedes desactivarte a ti mismo.")
            else:
                A.activar_usuario(u, not actual)
                st.rerun()
