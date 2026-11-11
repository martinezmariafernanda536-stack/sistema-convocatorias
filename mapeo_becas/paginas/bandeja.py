"""Página: bandeja de revisión. Ninguna convocatoria entra a la base sin pasar por aquí."""
from datetime import date, datetime

import pandas as pd
import streamlit as st

from analitica.datos import TIPOS
from bandeja import flujo as F
from calidad import reglas as R

import ui  # noqa: E402

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = st.session_state["usuario"]
PUEDE_REVISAR = YO["rol"] in ("admin", "revisor")


A = ui.almacen()
recargar = ui.recargar


@st.cache_data(ttl=60, show_spinner=False)
def leer_items():
    return A.items()


@st.cache_data(ttl=60, show_spinner=False)
def leer_catalogo_filas():
    return A.catalogo().filas()


@st.cache_data(ttl=300, show_spinner=False)
def leer_base():
    return A.base()


items = leer_items()
catalogo_filas = leer_catalogo_filas()
from calidad.actores import Catalogo  # noqa: E402

CAT = Catalogo.desde_filas(catalogo_filas)
BASE = leer_base()
nombres_actores = sorted(f["nombre"] for f in catalogo_filas)
actor_por_nombre = {f["nombre"]: f for f in catalogo_filas}
por_estado = {e: [i for i in items if i["estado"] == e] for e in ("Por revisar", "Actor pendiente de crear", "Aprobada", "Descartada")}

with st.sidebar:
    st.divider()
    for e, lst in por_estado.items():
        st.markdown(f"{e}: **{len(lst)}**")
    st.divider()
    if st.button("Actualizar bandeja"):
        recargar()


from componentes import Contexto, formulario, info_mapeo, panel_validacion  # noqa: E402

CTX = Contexto(A, YO, catalogo_filas, BASE)


# ---------------------------------------------------------------------------
st.title("Bandeja de revisión")
st.caption("Toda convocatoria, mapeada o registrada a mano, se revisa aquí antes de entrar a la base. "
           "Si el actor no está creado en CICLOPE, la convocatoria espera hasta que se cree.")

n_actores_pend = sum(1 for f in catalogo_filas if f["estado_ciclope"] != "Creado en CICLOPE")
t_rev, t_act, t_reg, t_pub, t_desc, t_cat = st.tabs([
    f"Por revisar ({len(por_estado['Por revisar'])})",
    f"Actores pendientes ({n_actores_pend} · {len(por_estado['Actor pendiente de crear'])} en espera)",
    "Registrar convocatoria", f"En la base ({len(por_estado['Aprobada'])})", f"Descartadas ({len(por_estado['Descartada'])})",
    "Catálogo de actores"])

with t_rev:
    lista = sorted(por_estado["Por revisar"], key=lambda i: i["ingreso"])
    if not lista:
        st.success("No hay convocatorias por revisar.")
    else:
        etiquetas = {i["id"]: f"{i['datos'].get('Nombre de la Convocatoria', '(sin nombre)')[:90]}  ·  {i['origen']}" for i in lista}
        sel = st.selectbox("Convocatoria", list(etiquetas), format_func=etiquetas.get, key="sel_rev")
        item = next(i for i in lista if i["id"] == sel)
        izq, der = st.columns([1.9, 1])
        with izq:
            datos = formulario(CTX, item["datos"], f"r_{item['id']}_")
        with der:
            info_mapeo(item)
            enlace = datos.get("Cómo aplicar", "")
            if enlace.startswith("http"):
                st.link_button("Abrir la página oficial", enlace, width="stretch")
            if st.button("Comprobar que los enlaces funcionan", key="ce_" + item["id"], width="stretch"):
                with st.spinner("Abriendo los enlaces…"):
                    st.session_state["enl_" + item["id"]] = F.comprobar_enlaces(datos)
            for campo, url, estado, ok in st.session_state.get("enl_" + item["id"], []):
                (st.success if ok else st.error)(f"{'✓' if ok else '✗'} {campo}: {estado}\n\n{url[:90]}")
            st.markdown("#### Calidad del dato")
            norm, hallazgos = panel_validacion(CTX, datos)
            st.markdown("#### Lista de chequeo")
            chequeo = {c: st.checkbox(c, key=f"chk_{item['id']}_{n}") for n, c in enumerate(F.LISTA_CHEQUEO)}
            with st.container(border=True):
                st.markdown("**Socialización** · aparte de la validación")
                st.caption("No afecta la aprobación: toda convocatoria válida entra a la base. "
                           "Esto solo sugiere si, además, conviene difundirla por los canales institucionales.")
                if norm.get(R.CAMPO_MOTIVO_PRIORIZACION):
                    sug = bool(norm.get("Se sugiere para priorización"))
                    st.markdown(("⭐ **Se sugiere para socializar.** " if sug else "**No se sugiere para socializar.** ")
                                + norm[R.CAMPO_MOTIVO_PRIORIZACION])
            if st.button("Guardar cambios", key="g_" + item["id"], width="stretch"):
                F.guardar_cambios(A, item, datos, YO["nombre"])
                st.toast("Cambios guardados")
                recargar()
            if PUEDE_REVISAR:
                if st.button("Aprobar y enviar a la base", type="primary", key="a_" + item["id"], width="stretch"):
                    try:
                        estado, _ = F.aprobar(A, item, datos, YO["nombre"], chequeo)
                        st.session_state["aviso"] = ("Aprobada y enviada a la base." if estado == "Aprobada" else
                                                     "Revisión aprobada. Queda en espera hasta que el actor esté creado en CICLOPE.")
                        recargar()
                    except F.ErrorFlujo as e:
                        st.error(str(e))
                with st.expander("Descartar"):
                    motivo = st.text_area("Motivo del descarte", key="m_" + item["id"])
                    if st.button("Descartar convocatoria", key="d_" + item["id"]):
                        try:
                            F.descartar(A, item, YO["nombre"], motivo)
                            recargar()
                        except F.ErrorFlujo as e:
                            st.error(str(e))
            else:
                st.info("Tu rol permite registrar y editar. La aprobación la hace un revisor.")
    if st.session_state.get("aviso"):
        st.success(st.session_state.pop("aviso"))

with t_act:
    pendientes = por_estado["Actor pendiente de crear"]
    actores_pend = [f for f in catalogo_filas if f["estado_ciclope"] != "Creado en CICLOPE"]
    st.write("Estos actores deben crearse en CICLOPE con el sistema de creación de actores. "
             "Cuando se registren como creados, las convocatorias que esperaban entran solas a la base si su revisión ya estaba aprobada.")
    if not actores_pend:
        st.success("No hay actores pendientes.")
    else:
        espera = {}
        for i in pendientes:
            espera.setdefault(R.limpiar_nombre(i["datos"].get("Nombre de la Fuente", "")).lower(), []).append(i)
        tabla = pd.DataFrame([{"Actor": f["nombre"], "Tipo de actor": f["tipo"], "Estado en CICLOPE": f["estado_ciclope"],
                               "País": f["pais"], "Sitio web": f["web"],
                               "Convocatorias en espera": len(espera.get(f["nombre"].lower(), []))} for f in actores_pend])
        tabla = tabla.sort_values("Convocatorias en espera", ascending=False)
        st.dataframe(tabla, hide_index=True, width="stretch")
        st.download_button("Descargar datos para la solicitud de creación", tabla.to_csv(index=False).encode("utf-8-sig"),
                           f"actores_por_crear_{date.today():%Y-%m-%d}.csv")
        if PUEDE_REVISAR:
            st.markdown("#### Registrar actor creado en CICLOPE")
            c1, c2, c3 = st.columns([1.4, 1.4, 1])
            elegido = c1.selectbox("Actor", tabla["Actor"].tolist(), key="ac_sel")
            nombre_ciclope = c2.text_input("Nombre exacto en CICLOPE", value=elegido or "", key=f"ac_nom_{elegido}")
            tipo_actual = actor_por_nombre.get(elegido, {}).get("tipo", "Por clasificar")
            tipo = c3.selectbox("Tipo de actor", TIPOS, index=TIPOS.index(tipo_actual) if tipo_actual in TIPOS else len(TIPOS) - 1,
                                key=f"ac_tipo_{elegido}")
            if st.button("Marcar como creado en CICLOPE", type="primary"):
                try:
                    if tipo == "Por clasificar":
                        raise F.ErrorFlujo("Asigna el tipo de actor: de él depende si es Oficial o No Oficial")
                    _, res = F.registrar_actor_creado(A, elegido, nombre_ciclope, YO["nombre"], tipo)
                    enviadas = sum(1 for _, e in res if e == "Aprobada")
                    st.session_state["aviso_act"] = f"Actor registrado. {enviadas} convocatoria(s) enviadas a la base, {len(res) - enviadas} vuelven a revisión."
                    recargar()
                except F.ErrorFlujo as e:
                    st.error(str(e))
    if st.session_state.get("aviso_act"):
        st.success(st.session_state.pop("aviso_act"))
    if pendientes:
        st.markdown("#### Convocatorias en espera")
        st.dataframe(pd.DataFrame([{"Convocatoria": i["datos"].get("Nombre de la Convocatoria"), "Actor": i["datos"].get("Nombre de la Fuente"),
                                    "Revisada por": i.get("revisado_por", ""), "Ingreso": i["ingreso"]} for i in pendientes]),
                     hide_index=True, width="stretch")

with t_reg:
    st.write("La convocatoria queda en la bandeja para su revisión antes de entrar a la base.")
    n = st.session_state.get("n_registro", 0)
    datos = formulario(CTX, {}, f"nuevo{n}_")
    st.markdown("#### Calidad del dato")
    panel_validacion(CTX, datos)
    if st.button("Enviar a revisión", type="primary"):
        if not datos.get("Nombre de la Convocatoria"):
            st.error("Escribe al menos el nombre de la convocatoria.")
        else:
            F.ingresar(A, datos, "Registro manual", YO["nombre"])
            st.session_state["n_registro"] = n + 1
            st.session_state["aviso_reg"] = "Convocatoria enviada a revisión."
            recargar()
    if st.session_state.get("aviso_reg"):
        st.success(st.session_state.pop("aviso_reg"))

with t_pub:
    aprobadas = sorted(por_estado["Aprobada"], key=lambda i: i["ingreso"], reverse=True)
    st.caption("Convocatorias que ya están en la base. Se consultan y corrigen en la página 'Base y calidad'.")
    if aprobadas:
        st.dataframe(pd.DataFrame([{"Convocatoria": i["datos"].get("Nombre de la Convocatoria"), "Actor": i["datos"].get("Nombre de la Fuente"),
                                    "Carácter": i["datos"].get("Oficial / No Oficial"), "Revisada por": i.get("revisado_por", ""),
                                    "Origen": i["origen"]} for i in aprobadas]), hide_index=True, width="stretch")

with t_desc:
    desc = por_estado["Descartada"]
    if desc:
        st.dataframe(pd.DataFrame([{"Convocatoria": i["datos"].get("Nombre de la Convocatoria"), "Motivo": i.get("observacion", ""),
                                    "Origen": i["origen"], "Ingreso": i["ingreso"]} for i in desc]), hide_index=True, width="stretch")
    else:
        st.info("No hay convocatorias descartadas.")

with t_cat:
    st.write("Catálogo único de actores. El **tipo** define si las convocatorias del actor son Oficiales "
             "(gobiernos, agencias, ONU, banca multilateral) o No Oficiales (fundaciones, ONG, academia, empresas).")
    df_cat = pd.DataFrame(catalogo_filas)[["nombre", "tipo", "caracter", "estado_ciclope", "alias", "pais", "web"]] if catalogo_filas else pd.DataFrame()
    if YO["rol"] == "admin" and len(df_cat):
        editado = st.data_editor(df_cat, hide_index=True, width="stretch", disabled=["caracter"], key="cat_ed",
                                 column_config={"tipo": st.column_config.SelectboxColumn("Tipo de actor", options=TIPOS),
                                                "estado_ciclope": st.column_config.SelectboxColumn("Estado en CICLOPE",
                                                    options=["Creado en CICLOPE", "Pendiente de crear", "Por confirmar"]),
                                                "nombre": "Nombre (como en CICLOPE)", "caracter": "Carácter", "alias": "Alias", "pais": "País",
                                                "web": "Sitio web"})
        if st.button("Guardar catálogo"):
            from calidad.actores import Actor
            cambios = 0
            for (_, viejo), (_, nuevo) in zip(df_cat.iterrows(), editado.iterrows()):
                if not viejo.equals(nuevo):
                    A.guardar_actor(Actor(nombre=nuevo["nombre"], tipo=nuevo["tipo"], estado_ciclope=nuevo["estado_ciclope"],
                                          alias=[x.strip() for x in str(nuevo["alias"]).split(";") if x.strip()],
                                          pais=nuevo["pais"], web=nuevo["web"]), nombre_anterior=viejo["nombre"])
                    cambios += 1
            st.success(f"{cambios} actor(es) actualizado(s).")
            recargar()
    else:
        st.dataframe(df_cat, hide_index=True, width="stretch")
        if YO["rol"] != "admin":
            st.caption("Solo el rol admin edita el catálogo.")
