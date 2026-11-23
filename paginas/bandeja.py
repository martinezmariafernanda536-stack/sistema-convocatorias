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
por_estado = {e: [i for i in items if i["estado"] == e]
              for e in ("Por revisar", "Por completar", "Actor pendiente de crear", "Aprobada", "Descartada")}

with st.sidebar:
    st.divider()
    if st.button("Actualizar la lista", icon=":material/refresh:", help="Trae lo último que llegó de la búsqueda."):
        recargar()


from componentes import Contexto, formulario, info_mapeo, panel_validacion  # noqa: E402

CTX = Contexto(A, YO, catalogo_filas, BASE)


# ---------------------------------------------------------------------------
st.title("Revisar convocatorias")
st.caption("Aquí llega todo lo que encuentra la búsqueda y lo que se registra a mano. Nada entra a la base sin que una persona "
           "lo revise y lo apruebe.")

n_actores_pend = sum(1 for f in catalogo_filas if f["estado_ciclope"] != "Creado en CICLOPE")
t_rev, t_comp, t_act, t_reg, t_pub, t_desc, t_cat = st.tabs([
    f"Por revisar ({len(por_estado['Por revisar'])})", f"Por completar ({len(por_estado['Por completar'])})",
    f"Actores pendientes ({n_actores_pend} · {len(por_estado['Actor pendiente de crear'])} en espera)",
    "Registrar convocatoria", f"En la base ({len(por_estado['Aprobada'])})", f"Descartadas ({len(por_estado['Descartada'])})",
    "Catálogo de actores"])

def _origen(i):
    o = i["origen"]
    if o.startswith("Descubrimiento") or "· RAD-" in o:
        return "Descubierta fuera de las fuentes"
    if o.startswith("Mapeo automático · nueva edición") or "· SEG-" in o:
        return "Seguimiento de ediciones"
    return ("Mapeo automático" if o.startswith("Mapeo") or o.startswith("Búsqueda externa")
            else "Airtable" if ("Airtable" in o or "Migración" in o) else "Registro manual")


def _fila_triaje(i, hoy):
    d, m = i["datos"], i.get("meta", {})
    cierre = R.fecha(d.get("Fecha Límite de Aplicación"))
    dias = (cierre - hoy).days if cierre else None
    perm = d.get("¿La convocatoria es permanente?") == "Si"
    pend = F.pendientes(i)
    err = sum(1 for h in pend if h["nivel"] == "Error")
    semaforo = ("⚪ Permanente" if perm else "⚫ Sin fecha" if dias is None else "🔴 Cerrada" if dias < 0 else
                "🔴" if dias < 15 else "🟠" if dias <= 37 else "🟢")
    elig = str(m.get("elegibilidad", "")).split(" · ")[0]
    dup = str(m.get("duplicado", ""))
    return {"id": i["id"], "Listo": "✅" if not err else "", "Cierre": semaforo, "Días": dias if not perm else None,
            "Convocatoria": d.get("Nombre de la Convocatoria", "(sin nombre)"), "Oferente": d.get("Nombre de la Fuente", ""),
            "Modalidad": R.modalidad_corta(d.get("Modalidad")), "Elegibilidad": elig or "—",
            "Errores": err, "Alertas": len(pend) - err, "Origen": _origen(i),
            "Edición": "Nueva edición" if dup.startswith("Nueva edición") else "",
            "Llegó": i["ingreso"][:10], "Página": d.get("Cómo aplicar", "") if str(d.get("Cómo aplicar", "")).startswith("http") else None}


ORIGENES = ["Mapeo automático", "Seguimiento de ediciones", "Descubierta fuera de las fuentes", "Registro manual", "Airtable"]


def kpis(zona, v, tabla, hoy, completar):
    """Cifras de la parte de arriba: se calculan sobre lo filtrado y dicen de cuántas en total."""
    dias = lambda df, si_vacio: df["Días"].fillna(si_vacio)  # noqa: E731
    hace7 = (hoy - pd.Timedelta(days=7)).isoformat()
    filtrado = len(v) != len(tabla)
    with zona:
        k = st.columns(5)
        for col, (n, lab) in zip(k, [
                (len(v), ("por completar" if completar else "por revisar") + (f" (de {len(tabla)})" if filtrado else "")),
                (int(((v["Origen"] != "Airtable") & (v["Llegó"] >= hace7)).sum()), "llegaron en los últimos 7 días"),
                (int(((dias(v, -1) >= 0) & (dias(v, -1) <= 30)).sum()), "cierran en 30 días o menos"),
                (int((v["Errores"] == 0).sum()), "sin nada en rojo" if completar else "completas, listas para aprobar"),
                (int((v["Origen"] == "Descubierta fuera de las fuentes").sum()), "descubiertas fuera de las fuentes")]):
            col.markdown(f"<div class='kpi'><div class='v'>{n}</div><div class='l'>{lab}</div></div>", unsafe_allow_html=True)
        if filtrado:
            st.caption("Las cifras corresponden a los filtros que elegiste.")
        st.write("")


def lista_de_trabajo(todas, pref, completar=False):
    if not todas:
        if completar:
            st.success("No hay convocatorias por completar.")
        else:
            st.success("No hay convocatorias por revisar. 🎉")
            st.page_link("paginas/mapeo.py", label="Buscar convocatorias nuevas", icon=":material/search:")
    else:
        if completar:
            st.info("Estas convocatorias las leyó Gemini, pero a su página le faltaba algún dato obligatorio o parte del texto "
                    "quedó en otro idioma (la columna **Qué falta** lo dice). Puedes **completarlas aquí a mano**: abre la página "
                    "oficial, llena lo que falta en el formulario y pulsa **Pasar a Por revisar**, o apruébala directamente. "
                    "Si no vale la pena, descártala. La búsqueda también vuelve a intentarlas sola con Gemini.")
        with st.expander("Cómo revisar, en 4 pasos", icon=":material/help:"):
            st.markdown("1. **Marca una fila** de la tabla: abajo se abre su ficha.  \n"
                        "2. **Abre la página oficial** y compara nombre, fechas, monto, requisitos y si Colombia puede postularse.  \n"
                        "3. **Corrige lo que está en rojo** en el formulario (lo amarillo es solo un aviso).  \n"
                        "4. **Marca la lista de chequeo y aprueba.** Si falta algo, el sistema te dice qué.  \n\n"
                        "Para descartar varias a la vez (por ejemplo, las que ya cerraron), marca varias filas.")
        hoy = date.today()
        tabla = pd.DataFrame([_fila_triaje(i, hoy) | ({"Qué falta": "; ".join(i.get("meta", {}).get("faltantes", []))[:160]}
                                                      if completar else {}) for i in todas])
        tabla["Días"] = pd.to_numeric(tabla["Días"], errors="coerce").astype("Int64")
        dias = lambda df, si_vacio: df["Días"].fillna(si_vacio)  # noqa: E731
        zona_kpi = st.container()  # se llena después de aplicar los filtros: las cifras responden a lo que se filtra
        f1, f2, f3, f4 = st.columns([1.3, 1.3, 1.1, 1.1])
        origenes = f1.multiselect("Origen", ORIGENES, placeholder="Todos", key=pref + "origen")
        modalidades = f2.multiselect("Modalidad", sorted(tabla["Modalidad"].unique()), placeholder="Todas", key=pref + "mod")
        OPC_CIERRE = ["Todas", "Abiertas", "Cierra en 30 días o menos", "Con más de un mes y una semana",
                      "Sin fecha o permanente", "Ya cerró"]
        n_cerradas = int((dias(tabla, 0) < 0).sum())
        if n_cerradas and st.session_state.get(pref + "cierre", "Todas") == "Todas":
            a1, a2 = st.columns([4, 1.2])
            a1.warning(f"**{n_cerradas} convocatorias ya cerraron.** Puedes verlas juntas y descartarlas de una vez.")
            if a2.button("Mostrar las cerradas", width="stretch", key=pref + "ver_cerradas"):
                st.session_state[pref + "cierre"] = "Ya cerró"
                st.rerun()
        cierre = f3.selectbox("Cierre", OPC_CIERRE, key=pref + "cierre")
        orden = f4.selectbox("Ordenar por", ["Cierre más próximo", "Más recientes", "Menos errores", "Oferente"],
                             key=pref + "orden")
        g1, g2, g3 = st.columns([2.2, 1.2, 1.1])
        buscar = g1.text_input("Buscar por nombre u oferente", placeholder="Ej.: DAAD, clima, maestría", key=pref + "buscar")
        elegs = g2.multiselect("Elegibilidad automática", ["Elegible", "Probable", "Revisar"], placeholder="Todas",
                               key=pref + "eleg")
        solo_listas = g3.toggle("Solo las completas", help="Las que no tienen nada en rojo por corregir.", key=pref + "listas")
        v = tabla.copy()
        if origenes:
            v = v[v["Origen"].isin(origenes)]
        if modalidades:
            v = v[v["Modalidad"].isin(modalidades)]
        if elegs:
            v = v[v["Elegibilidad"].isin(elegs)]
        if solo_listas:
            v = v[v["Errores"] == 0]
        if buscar:
            b = buscar.lower()
            v = v[v["Convocatoria"].str.lower().str.contains(b, regex=False) | v["Oferente"].str.lower().str.contains(b, regex=False)]
        if cierre == "Abiertas":
            v = v[dias(v, 0) >= 0]
        elif cierre == "Cierra en 30 días o menos":
            v = v[(dias(v, -1) >= 0) & (dias(v, -1) <= 30)]
        elif cierre == "Con más de un mes y una semana":
            v = v[dias(v, -1) > 37]
        elif cierre == "Sin fecha o permanente":
            v = v[v["Días"].isna()]
        elif cierre == "Ya cerró":
            v = v[dias(v, 0) < 0]
        # abiertas primero (la más próxima arriba), luego sin fecha, y al final las que ya cerraron
        orden_cierre = dias(v, 10_000).where(dias(v, 10_000) >= 0, 20_000 - dias(v, 0))
        v = {"Cierre más próximo": v.assign(_o=orden_cierre).sort_values(["_o", "Convocatoria"]).drop(columns="_o"),
             "Más recientes": v.sort_values("Llegó", ascending=False), "Menos errores": v.sort_values(["Errores", "Alertas"]),
             "Oferente": v.sort_values("Oferente")}[orden]
        kpis(zona_kpi, v, tabla, hoy, completar)
        st.caption(f"{len(v)} de {len(tabla)} convocatorias · marca una fila para revisarla; marca varias para descartarlas juntas. "
                   "🔴 cierra en menos de 15 días · 🟠 en un mes y una semana o menos · 🟢 con más plazo.")
        vista = v.drop(columns="id").assign(Días=[str(int(d)) if pd.notna(d) and d >= 0 else "" for d in v["Días"]])  # en las cerradas basta con «🔴 Cerrada»
        evento = st.dataframe(
            vista, hide_index=True, width="stretch", height=min(560, 38 + 35 * max(len(v), 1)),
            on_select="rerun", selection_mode="multi-row", key=pref + "tabla",
            column_config={"Página": st.column_config.LinkColumn("Página", display_text="Abrir ↗"),
                           "Cierre": st.column_config.TextColumn("Cierre", width=110),
                           "Días": st.column_config.TextColumn("Días para cierre", width=110),
                           "Convocatoria": st.column_config.TextColumn(width="large"),
                           "Listo": st.column_config.TextColumn("Completa", help="✅ = no tiene nada en rojo por corregir"),
                           "Elegibilidad": st.column_config.TextColumn("¿Colombia elegible?",
                                                                     help="Lo que leyó el sistema: Elegible, Probable o Revisar"),
                           "Qué falta": st.column_config.TextColumn("Qué falta", width="large"),
                           "Errores": st.column_config.NumberColumn("Por corregir", format="%d", help="Datos en rojo: obligatorios"),
                           "Alertas": st.column_config.NumberColumn("Avisos", format="%d", help="Datos en amarillo: conviene mirarlos")})
        filas_sel = evento.selection.rows if evento and evento.selection else []
        ids_sel = [v.iloc[n]["id"] for n in filas_sel if n < len(v)]
        if len(ids_sel) > 1 and PUEDE_REVISAR:
            with st.container(border=True):
                st.markdown(f"**{len(ids_sel)} convocatorias seleccionadas**")
                d1, d2, d3 = st.columns([1.6, 1.6, 0.8])
                motivo = d1.selectbox("Motivo del descarte", F.MOTIVOS_DESCARTE, key=pref + "mot_lote")
                detalle = d2.text_input("Detalle (opcional)", key=pref + "det_lote")
                if d3.button("Descartar seleccionadas", type="primary", width="stretch", key=pref + "desc_lote"):
                    elegidos = [i for i in todas if i["id"] in ids_sel]
                    n = F.descartar_varias(A, elegidos, YO["nombre"], motivo + (f": {detalle}" if detalle else ""))
                    st.session_state["aviso"] = f"{n} convocatorias descartadas."
                    recargar()
                st.caption("Para revisar una por una, deja marcada solo una fila.")
        elif not len(v):
            st.info("Ninguna convocatoria cumple los filtros.")
        else:
            sel = ids_sel[0] if ids_sel else v.iloc[0]["id"]
            if not ids_sel:
                st.caption("Mostrando la primera de la lista. Marca otra fila en la tabla para cambiarla.")
            item = next(i for i in todas if i["id"] == sel)
            st.markdown(f"### {item['datos'].get('Nombre de la Convocatoria', '(sin nombre)')}")
            izq, der = st.columns([1.9, 1])
            with izq:
                datos = formulario(CTX, item["datos"], f"r_{item['id']}_")
            with der:
                info_mapeo(item)
                st.markdown("<div class='paso'>① Comparar con la página oficial</div>", unsafe_allow_html=True)
                enlace = datos.get("Cómo aplicar", "")
                if enlace.startswith("http"):
                    st.link_button("Abrir la página oficial", enlace, width="stretch", icon=":material/open_in_new:")
                if st.button("Comprobar que los enlaces funcionan", key="ce_" + item["id"], width="stretch"):
                    with st.spinner("Abriendo los enlaces…"):
                        st.session_state["enl_" + item["id"]] = F.comprobar_enlaces(datos)
                for campo, url, estado, ok in st.session_state.get("enl_" + item["id"], []):
                    (st.success if ok else st.error)(f"{'✓' if ok else '✗'} {campo}: {estado}\n\n{url[:90]}")
                st.markdown("<div class='paso'>② Qué falta corregir</div>", unsafe_allow_html=True)
                st.caption("Rojo: obligatorio antes de aprobar. Amarillo: conviene mirarlo. Se corrige en el formulario de la izquierda.")
                norm, hallazgos = panel_validacion(CTX, datos)
                st.markdown("<div class='paso'>③ Lista de chequeo</div>", unsafe_allow_html=True)
                chequeo = {c: st.checkbox(c, key=f"chk_{item['id']}_{n}") for n, c in enumerate(F.LISTA_CHEQUEO)}
                with st.container(border=True):
                    st.markdown("**Socialización** · aparte de la validación")
                    st.caption("No afecta la aprobación: toda convocatoria válida entra a la base. "
                               "Esto solo sugiere si, además, conviene difundirla por los canales institucionales.")
                    if norm.get(R.CAMPO_MOTIVO_PRIORIZACION):
                        sug = bool(norm.get("Se sugiere para priorización"))
                        st.markdown(("⭐ **Se sugiere para socializar.** " if sug else "**No se sugiere para socializar.** ")
                                    + norm[R.CAMPO_MOTIVO_PRIORIZACION])
                if st.button("Guardar cambios sin aprobar", key="g_" + item["id"], width="stretch",
                             help="Guarda lo corregido y deja la convocatoria en revisión para terminarla después."):
                    F.guardar_cambios(A, item, datos, YO["nombre"])
                    st.toast("Cambios guardados")
                    recargar()
                if completar:
                    if st.button("Pasar a Por revisar", type="primary", key="pr_" + item["id"], width="stretch",
                                 icon=":material/arrow_forward:",
                                 help="Guarda lo que completaste y la deja en la pestaña Por revisar para aprobarla."):
                        F.pasar_a_revision(A, item, datos, YO["nombre"])
                        st.session_state["aviso"] = "Guardada y enviada a Por revisar."
                        recargar()
                st.markdown("<div class='paso'>④ Aprobar o descartar</div>", unsafe_allow_html=True)
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


with t_rev:
    lista_de_trabajo(por_estado["Por revisar"], "rev_")
    if st.session_state.get("aviso"):
        st.success(st.session_state.pop("aviso"))


with t_comp:
    lista_de_trabajo(por_estado["Por completar"], "comp_", completar=True)
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
        tabla = tabla.sort_values("Convocatorias en espera", ascending=False).reset_index(drop=True)
        st.caption("Marca un actor en la tabla para registrarlo como creado en CICLOPE.")
        ev_a = st.dataframe(tabla, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="sel_actor",
                            column_config={"Sitio web": st.column_config.LinkColumn()})
        actor_marcado = tabla.iloc[ev_a.selection.rows[0]]["Actor"] if ev_a and ev_a.selection.rows else None
        st.download_button("Descargar datos para la solicitud de creación", tabla.to_csv(index=False).encode("utf-8-sig"),
                           f"actores_por_crear_{date.today():%Y-%m-%d}.csv")
        if PUEDE_REVISAR:
            st.markdown("#### Registrar actor creado en CICLOPE")
            c1, c2, c3 = st.columns([1.4, 1.4, 1])
            opciones = tabla["Actor"].tolist()
            elegido = c1.selectbox("Actor", opciones, index=opciones.index(actor_marcado) if actor_marcado in opciones else 0,
                                   key=f"ac_sel_{actor_marcado}")
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
    st.caption("Convocatorias que ya están en la base. Se consultan y corrigen en la página «Base de convocatorias».")
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
