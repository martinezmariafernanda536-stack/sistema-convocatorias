"""Formulario de convocatoria y panel de calidad, compartidos por la bandeja y la página de base."""
from dataclasses import dataclass, field
from datetime import date

import streamlit as st

import ui
from analitica.datos import TIPOS
from bandeja import flujo as F
from calidad import reglas as R
from calidad.actores import Catalogo


@dataclass
class Contexto:
    almacen: object
    yo: dict
    catalogo_filas: list
    base: list
    cat: Catalogo = None
    nombres_actores: list = field(default_factory=list)
    actor_por_nombre: dict = field(default_factory=dict)

    def __post_init__(self):
        self.cat = Catalogo.desde_filas(self.catalogo_filas)
        self.nombres_actores = sorted(f["nombre"] for f in self.catalogo_filas)
        self.actor_por_nombre = {f["nombre"]: f for f in self.catalogo_filas}


# ---------------------------------------------------------------------------
# Formulario (mismo para revisar y para registrar)
# ---------------------------------------------------------------------------
NUEVO = "➕ El actor no está en la lista"


def _sel(etiqueta, campo, valor, clave, ayuda=None):
    opciones = R.CATALOGOS[campo]
    idx = opciones.index(valor) if valor in opciones else None
    if valor and idx is None:
        st.caption(f"⚠ Valor anterior fuera de la lista: «{valor}»")
    return st.selectbox(etiqueta, opciones, index=idx, key=clave, placeholder="Elegir…", help=ayuda) or ""


def _multi(etiqueta, campo, valor, clave, maximo=None):
    actuales = R.dividir(valor)
    validos = [v for v in actuales if v in R.CATALOGOS[campo]]
    if len(validos) < len(actuales):
        st.caption("⚠ Valores fuera de la lista: " + ", ".join(v for v in actuales if v not in validos))
    if maximo:
        validos = validos[:maximo]
    return R.unir(st.multiselect(etiqueta, R.CATALOGOS[campo], default=validos, key=clave, max_selections=maximo,
                                  placeholder="Elegir…"))


def _fecha(etiqueta, valor, clave):
    d = R.fecha(valor)
    v = st.date_input(etiqueta, value=d, key=clave, format="DD/MM/YYYY")
    return R.f_dmy(v) if v else ""


def formulario(ctx, d, k):
    """Devuelve un dict con las columnas de Airtable."""
    out = dict(d)
    c1, c2 = st.columns(2)
    out["VERIFICACIÓN: Colombia hace parte de los países beneficiarios"] = "checked" if c1.checkbox(
        "Verifiqué que Colombia es elegible", value=R.marcado(d.get("VERIFICACIÓN: Colombia hace parte de los países beneficiarios")), key=k + "v1") else ""
    out["VERIFICACIÓN: Página web correcta y activa"] = "checked" if c2.checkbox(
        "Verifiqué que los enlaces están disponibles", value=R.marcado(d.get("VERIFICACIÓN: Página web correcta y activa")), key=k + "v2") else ""

    out["Nombre de la Convocatoria"] = st.text_input("Nombre de la convocatoria *", d.get("Nombre de la Convocatoria", ""), key=k + "nom",
                                                     help="En español; si el original está en otro idioma, va entre paréntesis.")
    c1, c2, c3 = st.columns(3)
    with c1:
        out["Modalidad"] = _sel("Modalidad *", "Modalidad", d.get("Modalidad", ""), k + "mod")
    with c2:
        out["Fecha de Registro"] = _fecha("Fecha de registro *", d.get("Fecha de Registro") or R.f_dmy(date.today()), k + "freg")
    with c3:
        out["Reportado por"] = st.text_input("Reportado por *", d.get("Reportado por") or ctx.yo["nombre"], key=k + "rep")

    st.markdown("**Actor (oferente)**")
    actual = R.limpiar_nombre(d.get("Nombre de la Fuente", ""))
    match = ctx.cat.buscar(actual) if actual else None
    if st.session_state.get("_fijar_" + k):
        st.session_state[k + "act"] = st.session_state.pop("_fijar_" + k)
    opciones = [NUEVO] + ctx.nombres_actores
    idx = opciones.index(match.nombre) if match and match.nombre in opciones else (0 if actual else None)
    eleccion = st.selectbox("Actor del catálogo *", opciones, index=idx, key=k + "act", placeholder="Buscar actor…",
                            help="El carácter Oficial / No Oficial sale del tipo de actor.")
    if eleccion == NUEVO:
        with st.container(border=True):
            st.caption("Se agregará al catálogo como 'Pendiente de crear'. La convocatoria no entra a la base hasta que el actor esté creado en CICLOPE.")
            n1, n2 = st.columns([2, 1])
            nombre_nuevo = n1.text_input("Nombre del actor (español / idioma original)", actual if actual and not match else "", key=k + "an")
            tipo_nuevo = n2.selectbox("Tipo de actor", [t for t in TIPOS if t != "Por clasificar"], index=None, key=k + "at", placeholder="Elegir…")
            n3, n4 = st.columns(2)
            pais_nuevo = n3.text_input("País", key=k + "ap")
            web_nuevo = n4.text_input("Sitio web oficial", d.get("Link de la Fuente Oferente", ""), key=k + "aw")
            if st.button("Agregar actor al catálogo", key=k + "ab"):
                try:
                    if not tipo_nuevo:
                        raise F.ErrorFlujo("Elige el tipo de actor")
                    F.agregar_actor(ctx.almacen, nombre_nuevo, tipo_nuevo, ctx.yo["nombre"], pais_nuevo, web_nuevo)
                    st.session_state["_fijar_" + k] = nombre_nuevo.strip()
                    ui.recargar()
                except F.ErrorFlujo as e:
                    st.error(str(e))
        out["Nombre de la Fuente"] = nombre_nuevo.strip() if nombre_nuevo else actual
    elif eleccion:
        out["Nombre de la Fuente"] = eleccion
        a = ctx.actor_por_nombre.get(eleccion, {})
        estado = a.get("estado_ciclope", "")
        icono = "✅" if estado == "Creado en CICLOPE" else "⏳"
        st.caption(f"{a.get('tipo', '')} · **{a.get('caracter', '') or 'sin carácter'}** · {icono} {estado}")
    out["Nombre de actor en CICLOPE"] = out.get("Nombre de la Fuente", "")

    c1, c2, c3 = st.columns(3)
    with c1:
        perm = st.radio("¿Es permanente? *", ["No", "Si"], horizontal=True,
                        index=1 if d.get("¿La convocatoria es permanente?") == "Si" else 0, key=k + "perm")
        out["¿La convocatoria es permanente?"] = perm
    with c2:
        out[R.CAMPO_APERTURA] = _fecha("Fecha de apertura", d.get(R.CAMPO_APERTURA), k + "fap")
    with c3:
        if perm == "No":
            out["Fecha Límite de Aplicación"] = _fecha("Fecha límite de aplicación *", d.get("Fecha Límite de Aplicación"), k + "flim")
        else:
            out["Fecha Límite de Aplicación"] = ""
            st.caption("Permanente: sin fecha límite. Explícalo en las observaciones.")
    out["Observaciones a la fecha límite de aplicación"] = st.text_input(
        "Observaciones a la fecha límite *", d.get("Observaciones a la fecha límite de aplicación", ""), key=k + "ofl",
        help="Ejemplo: Cierre estricto el 21 de octubre a las 23:59 (hora de España).")

    out["Descripción"] = st.text_area("Descripción *", d.get("Descripción", ""), key=k + "desc", height=110)
    out["Objetivos General y Específicos"] = st.text_area("Objetivos general y específicos *", d.get("Objetivos General y Específicos", ""), key=k + "obj", height=90)
    req = d.get(R.CAMPO_REQUISITOS, "") or R.plantilla(out.get("Modalidad") or d.get("Modalidad"))
    out[R.CAMPO_REQUISITOS] = st.text_area(
        "Requisitos y condiciones de participación *", req, key=k + "req", height=150,
        help="Un renglón por criterio de la modalidad. Si la convocatoria no lo dice, escribir «No se indica».")
    c1, c2 = st.columns(2)
    with c1:
        out["Dirigida a (tipo de publico)"] = _multi("Dirigida a *", "Dirigida a (tipo de publico)", d.get("Dirigida a (tipo de publico)"), k + "pub")
        out["Áreas temáticas de interés"] = _multi("Áreas temáticas * (máximo 3)", "Áreas temáticas de interés", d.get("Áreas temáticas de interés"), k + "tem", 3)
        out["Idioma/s"] = _multi("Idioma/s *", "Idioma/s", d.get("Idioma/s"), k + "idi")
    with c2:
        out["Esta convocatoria prioriza alguna de las siguientes poblaciones?"] = _multi(
            "Poblaciones priorizadas", "Esta convocatoria prioriza alguna de las siguientes poblaciones?",
            d.get("Esta convocatoria prioriza alguna de las siguientes poblaciones?"), k + "pob")
        out["Ámbito Geográfico"] = _sel("Ámbito geográfico *", "Ámbito Geográfico", d.get("Ámbito Geográfico", ""), k + "amb")

    c1, c2 = st.columns(2)
    m = R.monto(d.get("Financiación"))
    with c1:
        valor = st.number_input("Financiación en USD (si se conoce)", min_value=0, value=int(m) if m is not None else None, step=1000,
                                key=k + "fin", placeholder="Monto en dólares, sin puntos")
        out["Financiación"] = "" if valor is None else str(int(valor))
    with c2:
        tm = d.get(R.CAMPO_TIPO_MONTO, "")
        out[R.CAMPO_TIPO_MONTO] = st.selectbox("Tipo de monto *", R.TIPOS_MONTO, index=R.TIPOS_MONTO.index(tm) if tm in R.TIPOS_MONTO else None,
                                               key=k + "tm", placeholder="Elegir…") or ""
    out["Observaciones sobre el financiamiento"] = st.text_area("Observaciones sobre el financiamiento / beneficios ofrecidos *",
                                                                d.get("Observaciones sobre el financiamiento", ""), key=k + "ofi", height=70)
    c1, c2 = st.columns(2)
    out["Cómo aplicar"] = c1.text_input("Cómo aplicar (enlace oficial) *", d.get("Cómo aplicar", ""), key=k + "como")
    out["Link de la Fuente Oferente"] = c2.text_input("Enlace de la fuente oferente *", d.get("Link de la Fuente Oferente", ""), key=k + "link")
    c1, c2 = st.columns(2)
    out["Email para mayor información"] = c1.text_input("Correo de contacto *", d.get("Email para mayor información", ""), key=k + "mail",
                                                        help="Correo del oferente o 'Sin Email'.")
    out["¿Se puede publicar en la web?"] = "checked" if c2.checkbox(
        "Se puede publicar en la web", value=R.marcado(d.get("¿Se puede publicar en la web?")), key=k + "web") else ""

    st.markdown("**Alineación**")
    c1, c2, c3 = st.columns(3)
    with c1:
        out["Linea Prioritaria ENCI"] = _sel("Línea ENCI *", "Linea Prioritaria ENCI", d.get("Linea Prioritaria ENCI", ""), k + "enci")
        out["Sector Gobierno"] = _sel("Sector Gobierno *", "Sector Gobierno", d.get("Sector Gobierno", ""), k + "sec")
    with c2:
        out["Plan Marco de Implementación"] = _sel("Plan Marco de Implementación *", "Plan Marco de Implementación",
                                                   d.get("Plan Marco de Implementación", ""), k + "pmi",
                                                   "Si no aporta específicamente al proceso de paz, marcar No Aplica.")
        out["ODS"] = _sel("ODS *", "ODS", d.get("ODS", ""), k + "ods")
    with c3:
        out["Metas PND"] = _sel("Meta PND *", "Metas PND", d.get("Metas PND", ""), k + "pnd")
        out["Comite de Ayuda al Desarrollo"] = _sel("Sector CAD *", "Comite de Ayuda al Desarrollo", d.get("Comite de Ayuda al Desarrollo", ""), k + "cad")
    st.markdown("**Socialización** (aparte de la validación: no afecta el registro)")
    out[R.CAMPO_SOLICITUD] = "checked" if st.checkbox(
        "Solicitud expresa del cooperante para socializarla", value=R.marcado(d.get(R.CAMPO_SOLICITUD)), key=k + "sol",
        help="Caso especial: permite sugerirla aunque no cumpla los demás criterios.") else ""
    out["Se sugiere para priorización"] = d.get("Se sugiere para priorización", "")
    st.caption("Toda convocatoria válida se registra, cumpla o no estos criterios. «Se sugiere para priorización» solo indica "
               "cuáles difundir además por los canales institucionales: plazo mayor a un mes y una semana, monto superior a "
               "USD 50.000, preferencia por subvenciones (también becas) o solicitud expresa del cooperante.")
    return out


def panel_validacion(ctx, datos, nuevo=True, excluir_id=None):
    base = [b for b in ctx.base if b.get("_id") != excluir_id]
    norm, hallazgos = R.validar(datos, ctx.cat, base, nuevo=nuevo)
    errores = [h for h in hallazgos if h.nivel == "Error"]
    alertas = [h for h in hallazgos if h.nivel == "Alerta"]
    corregidos = [h for h in hallazgos if h.nivel == "Corregido"]
    if not errores:
        st.markdown("<div class='ok'>Sin errores de calidad.</div>", unsafe_allow_html=True)
    for h in errores:
        extra = f" → <i>{h.sugerencia}</i>" if h.sugerencia else ""
        st.markdown(f"<div class='err'><b>{h.campo}</b>: {h.problema}{extra}</div>", unsafe_allow_html=True)
    for h in alertas:
        extra = f" → <i>{h.sugerencia}</i>" if h.sugerencia else ""
        st.markdown(f"<div class='ale'><b>{h.campo}</b>: {h.problema}{extra}</div>", unsafe_allow_html=True)
    for h in corregidos:
        st.markdown(f"<div class='ok'><b>{h.campo}</b>: {h.problema} → {h.sugerencia}</div>", unsafe_allow_html=True)
    return norm, hallazgos


def info_mapeo(item):
    m = item.get("meta", {})
    partes = [f"<b>Origen:</b> {item['origen']} · <b>Ingreso:</b> {item['ingreso']}"]
    for clave, etiqueta in (("elegibilidad", "Elegibilidad Colombia (automática)"), ("icetex", "ICETEX"),
                            ("pagina", "Página donde se encontró"), ("nivel", "Nivel"),
                            ("gemini", "Lo que propuso Gemini (confirmar en la página)")):
        if m.get(clave):
            partes.append(f"<b>{etiqueta}:</b> {m[clave]}")
    st.markdown("<div class='meta'>" + "<br>".join(partes) + "</div>", unsafe_allow_html=True)


