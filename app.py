"""Sistema de convocatorias internacionales · DGDCI · APC-Colombia

Ejecutar:  streamlit run app.py
Reúne el dashboard, los informes automáticos, la bandeja de revisión y la base de convocatorias.
"""
import streamlit as st

import ui
from bandeja import usuarios as U

st.set_page_config(page_title="Convocatorias · DGDCI", page_icon="📊", layout="wide")
st.markdown(ui.ESTILOS, unsafe_allow_html=True)


def _valor_aleatorio(nombre):
    import secrets as _s
    clave = "gen_" + nombre
    if clave not in st.session_state:
        st.session_state[clave] = _s.token_urlsafe(48)
    return st.session_state[clave]


def pantalla_configuracion(error=None):
    """Se muestra cuando faltan secretos: dice cuáles y genera los valores aleatorios."""
    import os
    _, c, _ = st.columns([1, 2, 1])
    with c:
        st.markdown("### Configuración inicial del sistema")
        if error:
            st.error(str(error))
        st.write("Faltan datos en los **Secrets** de la aplicación. En Streamlit: *Manage app → Settings → Secrets*. "
                 "Pega este texto, completa las dos primeras líneas y pulsa *Save*. La aplicación se reinicia sola.")
        repo = os.environ.get("GITHUB_DATA_REPO") or "tu_usuario_de_github/convocatorias-datos"
        token = "(ya configurado)" if os.environ.get("GITHUB_TOKEN") else "github_pat_..."
        usuarios = "(ya configurado)" if os.environ.get("USUARIOS_CLAVE") else _valor_aleatorio("USUARIOS_CLAVE")
        instal = "(ya configurado)" if os.environ.get("CLAVE_INSTALACION") else _valor_aleatorio("CLAVE_INSTALACION")
        lineas = [f'GITHUB_DATA_REPO = "{repo}"']
        if not os.environ.get("GITHUB_TOKEN"):
            lineas.append(f'GITHUB_TOKEN = "{token}"')
        if not os.environ.get("USUARIOS_CLAVE"):
            lineas.append(f'USUARIOS_CLAVE = "{usuarios}"')
        if not os.environ.get("CLAVE_INSTALACION"):
            lineas.append(f'CLAVE_INSTALACION = "{instal}"')
        if not os.environ.get("GEMINI_API_KEY"):
            lineas.append('GEMINI_API_KEY = "pega-aquí-tu-clave-de-gemini"')
        st.code("\n".join(lineas), language="toml")
        st.markdown("- **GITHUB_DATA_REPO:** tu usuario de GitHub / el repositorio de datos.\n"
                    "- **GITHUB_TOKEN:** token de GitHub con permiso *Contents: Read and write* solo sobre ese repositorio.\n"
                    "- **GEMINI_API_KEY:** clave gratuita de aistudio.google.com (*Get API key → Create API key*). Activa la "
                    "el completado automático de campos con Gemini. Si aún no la tienes, borra esa línea.\n"
                    "- **USUARIOS_CLAVE** y **CLAVE_INSTALACION:** ya vienen generadas. **Guárdalas también en un lugar seguro**: "
                    "la clave de instalación sirve para crear el primer administrador y para recuperar el acceso de un administrador.")


def pantalla_primer_administrador():
    import os
    _, c, _ = st.columns([1, 1.4, 1])
    with c:
        st.markdown("### Crear el primer administrador")
        st.write("El sistema todavía no tiene usuarios. Escribe la **clave de instalación** (el valor de CLAVE_INSTALACION "
                 "en los Secrets) y los datos de la cuenta.")
        st.info(U.POLITICA)
        with st.form("primer_admin"):
            ci = st.text_input("Clave de instalación", type="password")
            usuario = st.text_input("Usuario", help="Letras sin tildes, números, punto o guion. Ejemplo: nata")
            nombre = st.text_input("Nombre completo")
            c1 = st.text_input("Contraseña", type="password")
            c2 = st.text_input("Repite la contraseña", type="password")
            ok = st.form_submit_button("Crear administrador", type="primary", width="stretch")
        if ok:
            try:
                U.crear_primer_administrador(ui.almacen(), ci, os.environ.get("CLAVE_INSTALACION", ""), usuario, nombre, c1, c2)
                st.success("Administrador creado. Ya puedes ingresar.")
                st.rerun()
            except (U.ErrorClave, ValueError) as e:
                st.error(str(e))


def pantalla_ingreso():
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        st.markdown("### Sistema de convocatorias internacionales")
        st.caption("Dirección de Gestión de Demanda de Cooperación Internacional · APC-Colombia")
        with st.form("ingreso"):
            usuario = st.text_input("Usuario")
            clave = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if entrar:
            u, mensaje = U.verificar(ui.almacen(), usuario, clave)
            if u:
                st.session_state["usuario"] = u
                st.session_state["ficha"] = U.emitir_sesion(ui.almacen(), u["usuario"])
                st.query_params["s"] = st.session_state["ficha"]
                st.rerun()
            st.error(mensaje)
        with st.expander("¿Olvidaste tu contraseña?"):
            st.write("Usa uno de tus **códigos de recuperación** (los recibiste al activar tu cuenta). "
                     "Cada código sirve una sola vez. Si no los tienes, pide al administrador que restablezca tu contraseña.")
            with st.form("recuperar", clear_on_submit=False):
                ru = st.text_input("Usuario", key="rec_u")
                rc = st.text_input("Código de recuperación", placeholder="XXXXX-XXXXX", key="rec_c")
                rn = st.text_input("Contraseña nueva", type="password", key="rec_n", help=U.POLITICA)
                rn2 = st.text_input("Repite la contraseña nueva", type="password", key="rec_n2")
                ok = st.form_submit_button("Recuperar el acceso")
            if ok:
                try:
                    quedan = U.recuperar(ui.almacen(), ru, rc, rn, rn2)
                    st.success(f"Listo: ya puedes ingresar con tu nueva contraseña. Te quedan {quedan} códigos de recuperación.")
                except U.ErrorClave as e:
                    st.error(str(e))
            st.caption(U.POLITICA)
        with st.expander("Soy administrador y perdí el acceso"):
            st.write("Solo para administradores sin códigos de recuperación. Se necesita la **clave de instalación**.")
            with st.form("rec_admin"):
                au = st.text_input("Usuario administrador", key="ra_u")
                ac = st.text_input("Clave de instalación", type="password", key="ra_c")
                an = st.text_input("Contraseña nueva", type="password", key="ra_n", help=U.POLITICA)
                an2 = st.text_input("Repite la contraseña nueva", type="password", key="ra_n2")
                ok2 = st.form_submit_button("Recuperar acceso de administrador")
            if ok2:
                import os
                intentos = st.session_state.get("intentos_inst", 0)
                if intentos >= 5:
                    st.error("Demasiados intentos. Cierra y vuelve a abrir la página más tarde.")
                else:
                    try:
                        U.recuperar_administrador(ui.almacen(), ac, os.environ.get("CLAVE_INSTALACION", ""), au, an, an2)
                        st.success("Listo: ya puedes ingresar con tu nueva contraseña.")
                    except U.ErrorClave as e:
                        st.session_state["intentos_inst"] = intentos + 1
                        st.error(str(e))


def pantalla_cambio_obligatorio(yo):
    _, c, _ = st.columns([1, 1.4, 1])
    with c:
        st.markdown("### Cambia tu contraseña")
        st.write("Entraste con una contraseña temporal. Antes de continuar, elige una contraseña propia.")
        st.info(U.POLITICA)
        with st.form("cambio"):
            actual = st.text_input("Contraseña temporal", type="password")
            nueva = st.text_input("Contraseña nueva", type="password")
            nueva2 = st.text_input("Repite la contraseña nueva", type="password")
            ok = st.form_submit_button("Guardar contraseña", type="primary", width="stretch")
        if ok:
            try:
                U.cambiar_clave(ui.almacen(), yo["usuario"], actual, nueva, nueva2)
                yo["debe_cambiar"] = False
                st.session_state["usuario"] = yo
                st.session_state["ficha"] = U.emitir_sesion(ui.almacen(), yo["usuario"])
                st.rerun()
            except (U.ErrorClave, ValueError) as e:
                st.error(str(e))
        if st.button("Salir"):
            st.session_state.clear()
            st.rerun()


def pantalla_codigos(yo):
    _, c, _ = st.columns([1, 1.4, 1])
    with c:
        st.markdown("### Tus códigos de recuperación")
        if "codigos_nuevos" not in st.session_state:
            st.session_state["codigos_nuevos"] = U.generar_codigos(ui.almacen(), yo["usuario"])
        codigos = st.session_state["codigos_nuevos"]
        st.warning("Guárdalos en un lugar seguro, por ejemplo impresos o en tu gestor de contraseñas. "
                   "Sirven para recuperar el acceso si olvidas la contraseña. **Cada uno sirve una sola vez y no se vuelven a mostrar.**")
        st.code("\n".join(codigos))
        st.download_button("Descargar los códigos (.txt)", "\n".join(
            [f"Códigos de recuperación · usuario {yo['usuario']} · Sistema de convocatorias DGDCI", ""] + codigos),
            f"codigos_recuperacion_{yo['usuario']}.txt")
        if st.checkbox("Ya guardé mis códigos"):
            if st.button("Continuar", type="primary"):
                yo["sin_codigos"] = False
                st.session_state["usuario"] = yo
                st.session_state.pop("codigos_nuevos", None)
                st.rerun()


import os  # noqa: E402

from bandeja.almacen import ErrorCuentas, exportar_secretos, sincronizador_configurado  # noqa: E402

exportar_secretos(ui.secretos())
_en_la_nube = bool(os.environ.get("SPACE_ID") or os.path.isdir("/mount/src"))  # Hugging Face o Streamlit Community Cloud
if _en_la_nube and (not sincronizador_configurado() or not os.environ.get("USUARIOS_CLAVE")
                    or not os.environ.get("CLAVE_INSTALACION")):
    pantalla_configuracion()
    st.stop()
try:
    _A = ui.almacen()
    _hay_cuentas = bool(_A.cuentas())
except ErrorCuentas as e:
    pantalla_configuracion(e)
    st.stop()
except Exception as e:  # noqa: BLE001 - repositorio o token mal configurados
    pantalla_configuracion(f"No se pudo abrir la base: {e}")
    st.stop()
if not _hay_cuentas:
    pantalla_primer_administrador()
    st.stop()

if not ui.usuario() and st.query_params.get("s"):
    _u = U.leer_sesion(ui.almacen(), st.query_params.get("s"))  # se cortó la conexión o la app se reinició
    if _u:
        st.session_state["usuario"], st.session_state["ficha"] = _u, st.query_params.get("s")
    else:
        del st.query_params["s"]
if not ui.usuario():
    pantalla_ingreso()
    st.stop()
if st.session_state.get("ficha") and st.query_params.get("s") != st.session_state["ficha"]:
    st.query_params["s"] = st.session_state["ficha"]  # se conserva al cambiar de página
if ui.usuario().get("debe_cambiar"):
    pantalla_cambio_obligatorio(ui.usuario())
    st.stop()
if ui.usuario().get("sin_codigos"):
    pantalla_codigos(ui.usuario())
    st.stop()

yo = ui.usuario()
ROL_LEGIBLE = {"admin": "Administrador", "revisor": "Revisor"}
paginas = {
    "Trabajo diario": [
        st.Page("paginas/inicio.py", title="Inicio", icon=":material/home:", default=True),
        st.Page("paginas/bandeja.py", title="Revisar convocatorias", icon=":material/fact_check:"),
        st.Page("paginas/mapeo.py", title="Buscar convocatorias", icon=":material/travel_explore:"),
    ],
    "Consultar": [
        st.Page("paginas/base.py", title="Base de convocatorias", icon=":material/database:"),
        st.Page("paginas/tablero.py", title="Dashboard e informes", icon=":material/bar_chart:"),
    ],
    "Ayuda": [st.Page("paginas/guia.py", title="Cómo se usa", icon=":material/help:")],
    "Mi cuenta": [st.Page("paginas/cuenta.py", title="Contraseña y códigos", icon=":material/lock:")],
}
if yo["rol"] == "admin":
    paginas["Mi cuenta"].append(st.Page("paginas/usuarios.py", title="Usuarios", icon=":material/group:"))

if yo["rol"] == "admin":
    from bandeja.almacen import datos_en_repo_de_codigo
    if datos_en_repo_de_codigo():
        st.error("**Los datos se están guardando en la rama principal del repositorio del código.** Cada guardado hace que "
                 "Streamlit recargue la aplicación. Borra el secreto `GITHUB_DATA_BRANCH` (o ponle `datos`): el sistema "
                 "guardará los datos en la rama «datos» del mismo repositorio, sin perder nada.")

with st.sidebar:
    st.markdown(f"**{yo['nombre']}**  \n<span style='color:#5b6472'>{ROL_LEGIBLE.get(yo['rol'], yo['rol'])}</span>",
                unsafe_allow_html=True)
    if st.button("Cerrar sesión", icon=":material/logout:"):
        U.cerrar_sesion(ui.almacen(), yo["usuario"])
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()
    st.caption("¿Primera vez? Abre **Cómo se usa** en el menú.")

# si el servidor se reinició a mitad de una búsqueda (al subir archivos a GitHub, por ejemplo), se reanuda sola una vez
try:
    import tareas
    tareas.reanudar_si_se_corto(ui.almacen())
except Exception:  # noqa: BLE001 - nunca impide abrir la app
    pass

st.navigation(paginas).run()
