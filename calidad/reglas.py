"""Reglas de calidad para toda convocatoria, mapeada o registrada a mano.

validar(registro, catalogo, base) -> (registro_normalizado, hallazgos)

- Nivel 'Error': bloquea la aprobación.
- Nivel 'Alerta': quien revisa debe confirmarla, pero no bloquea.
- Lo que se puede corregir sin duda se corrige solo (espacios, formato de fecha,
  carácter según el actor, casilla de 'más de un mes y una semana').
"""
import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from calidad.actores import limpiar_nombre

RAIZ = Path(__file__).resolve().parents[1]
CATALOGOS = json.loads((RAIZ / "config" / "catalogos.json").read_text(encoding="utf-8"))

try:
    from rapidfuzz import fuzz

    def similitud(a, b):
        from analitica.datos import norm
        a, b = norm(a).strip(), norm(b).strip()
        if min(len(a.split()), len(b.split())) >= 4:
            return fuzz.token_set_ratio(a, b)
        return fuzz.token_sort_ratio(a, b)
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def similitud(a, b):
        return 100 * SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()

OBLIGATORIOS = [
    "Nombre de la Convocatoria", "Modalidad", "Fecha de Registro", "Reportado por", "¿La convocatoria es permanente?",
    "Nombre de la Fuente", "Descripción", "Objetivos General y Específicos", "Dirigida a (tipo de publico)",
    "Áreas temáticas de interés", "Ámbito Geográfico",
    "Cómo aplicar", "Idioma/s", "Observaciones a la fecha límite de aplicación", "Email para mayor información",
    "Link de la Fuente Oferente", "Linea Prioritaria ENCI", "Plan Marco de Implementación", "Sector Gobierno", "ODS",
    "Metas PND", "Comite de Ayuda al Desarrollo",
]
# Campos que el formulario de Airtable no tenía y que exige el procedimiento de validación de la DGDCI
CAMPO_APERTURA = "Fecha de apertura"
CAMPO_REQUISITOS = "Requisitos y condiciones de participación"
CAMPO_SOLICITUD = "Solicitud expresa del cooperante"
CAMPO_MOTIVO_PRIORIZACION = "Motivo de la sugerencia de priorización"
CAMPOS_NUEVOS = [CAMPO_APERTURA, CAMPO_REQUISITOS, CAMPO_SOLICITUD, CAMPO_MOTIVO_PRIORIZACION]

# Criterios según la modalidad (procedimiento de validación, numeral 3) + procedimiento de postulación (numeral 2)
PLANTILLAS = {
    "Subvención": ["Organizaciones elegibles", "Requisitos de experiencia", "Contrapartida", "Gastos financiables",
                   "Procedimiento de postulación"],
    "Beca": ["Perfil de los aspirantes", "Nivel de formación", "Requisitos académicos", "Cobertura",
             "Condiciones de participación", "Procedimiento de postulación"],
    "Premio": ["Público objetivo", "Criterios de participación", "Reconocimiento ofrecido", "Condiciones de selección",
               "Procedimiento de postulación"],
    "Cooperación Técnica": ["Tipo de asistencia", "Entidades beneficiarias", "Áreas de intervención", "Requisitos de participación",
                            "Procedimiento de postulación"],
}
NO_SE_INDICA = "No se indica"


def modalidad_corta(m):
    return str(m or "").split(" (")[0].strip()


def plantilla(modalidad):
    """Texto guía del campo de requisitos para una modalidad: un renglón por criterio."""
    criterios = PLANTILLAS.get(modalidad_corta(modalidad), ["Requisitos de participación", "Procedimiento de postulación"])
    return "\n".join(f"{t}: " for t in criterios)


def leer_requisitos(texto_req, modalidad):
    """{criterio: contenido} según los títulos de la modalidad; el contenido va hasta el siguiente título."""
    t = str(texto_req or "")
    criterios = PLANTILLAS.get(modalidad_corta(modalidad), [])
    todos = sorted({c for cs in PLANTILLAS.values() for c in cs}, key=len, reverse=True)
    marcas = sorted((m.start(), m.end(), m.group(1)) for m in
                    re.finditer(r"(" + "|".join(re.escape(c) for c in todos) + r")\s*:", t, re.I))
    salida = {}
    for i, (ini, fin, nombre) in enumerate(marcas):
        hasta = marcas[i + 1][0] if i + 1 < len(marcas) else len(t)
        clave = next((c for c in todos if c.lower() == nombre.lower()), nombre)
        salida[clave] = t[fin:hasta].strip(" \n;|-")
    if not marcas and t.strip():
        salida["_libre"] = t.strip()
    return {c: salida.get(c, "") for c in criterios} | ({"_libre": salida["_libre"]} if "_libre" in salida else {})


def criterios_vacios(texto_req, modalidad):
    """Criterios de la modalidad que no aparecen o están vacíos en el campo de requisitos."""
    leidos = leer_requisitos(texto_req, modalidad)
    return [c for c in PLANTILLAS.get(modalidad_corta(modalidad), []) if not leidos.get(c)]


def priorizacion(r, hoy=None):
    """Criterios de socialización (numeral 5). Van APARTE de la validación: no deciden qué se busca, qué se aprueba
    ni qué entra a la base. Solo sugieren cuáles de las convocatorias ya válidas se difunden además por los canales
    institucionales.

    - Plazo de postulación mayor a un mes y una semana (o convocatoria permanente).
    - Se priorizan montos superiores a USD 50.000.
    - Preferencia por subvenciones; también se socializan becas.
    - Caso especial: solicitud expresa del cooperante.
    Devuelve (sugerida: bool, motivo)."""
    if marcado(r.get(CAMPO_SOLICITUD, "")):
        return True, "Caso especial: solicitud expresa del cooperante"
    plazo = marcado(r.get("Tiempo de vencimiento es mayor a un mes y una semana", "")) or r.get("¿La convocatoria es permanente?") == "Si"
    if not plazo:
        return False, "No cumple el plazo: cierra en menos de un mes y una semana"
    mod = modalidad_corta(r.get("Modalidad"))
    m = monto(r.get("Financiación"))
    if mod == "Subvención":
        if m is not None and m > 50_000:
            return True, f"Subvención de más de USD 50.000 (USD {m:,.0f}) con plazo suficiente"
        return False, ("Subvención de USD 50.000 o menos" if m is not None else "Subvención sin monto en USD: no se puede confirmar si supera USD 50.000")
    if mod == "Beca":
        return True, "Beca con plazo suficiente (las becas también se socializan)"
    if m is not None and m > 50_000:
        return True, f"{mod} de más de USD 50.000 con plazo suficiente (se prefieren subvenciones: confirmar)"
    return False, f"{mod or 'Modalidad'} sin monto superior a USD 50.000"


UNICOS = ["Modalidad", "Ámbito Geográfico", "Linea Prioritaria ENCI", "Plan Marco de Implementación", "Sector Gobierno",
          "ODS", "Metas PND", "Comite de Ayuda al Desarrollo", "¿La convocatoria es permanente?"]
MULTIPLES = ["Dirigida a (tipo de publico)", "Esta convocatoria prioriza alguna de las siguientes poblaciones?",
             "Áreas temáticas de interés", "Idioma/s"]
VERIFICACIONES = ["VERIFICACIÓN: Colombia hace parte de los países beneficiarios", "VERIFICACIÓN: Página web correcta y activa"]
TIPOS_MONTO = ["Por beneficiario o proyecto", "Presupuesto total de la convocatoria", "No especificado"]
CAMPO_TIPO_MONTO = "Tipo de monto"

_URL = re.compile(r"^https?://[\w.-]+\.[a-z]{2,}(/\S*)?$", re.I)
_CORREO = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_INGLES = {"the", "of", "for", "and", "grant", "grants", "program", "programme", "scholarship", "scholarships", "fund",
           "award", "call", "fellowship", "prize", "research", "innovation"}
_ESPANOL = {"de", "la", "el", "para", "y", "del", "convocatoria", "beca", "becas", "programa", "premio", "subvención",
            "subvenciones", "fondo", "los", "las"}


@dataclass
class Hallazgo:
    campo: str
    nivel: str          # Error | Alerta | Corregido
    problema: str
    valor: str = ""
    sugerencia: str = ""
    regla: str = ""


def dividir(v):
    if v is None or (isinstance(v, float) and v != v) or not str(v).strip():
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in next(csv.reader(io.StringIO(str(v)), skipinitialspace=True)) if x.strip()]


def unir(valores):
    buf = io.StringIO()
    csv.writer(buf).writerow(list(dict.fromkeys(valores)))
    return buf.getvalue().strip()


def vacio(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip().lower() in ("", "nan", "none")


def texto(v):
    return "" if vacio(v) else re.sub(r"\s+", " ", str(v).replace("​", "")).strip()


def texto_con_renglones(v):
    if vacio(v):
        return ""
    lineas = [re.sub(r"[ \t\u200b]+", " ", x).strip() for x in str(v).splitlines()]
    return "\n".join(x for x in lineas if x)


def fecha(v):
    if vacio(v):
        return None
    if isinstance(v, (date, datetime)):
        return v.date() if isinstance(v, datetime) else v
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(v).strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def monto(v):
    if vacio(v):
        return None
    t = re.sub(r"[^\d.,]", "", str(v))
    if re.search(r"[.,]\d{2}$", t):
        t = t[:-3]
    t = re.sub(r"[.,]", "", t)
    return float(t) if t else None


def f_dmy(d):
    return f"{d.day}/{d.month}/{d.year}" if d else ""


def marcado(v):
    return str(v).strip().lower() in ("checked", "true", "1", "sí", "si", "x")


def validar(registro, catalogo=None, base=None, hoy=None, nuevo=True):
    """Normaliza y valida una convocatoria.

    registro: dict con columnas de Airtable (más 'Tipo de monto').
    catalogo: calidad.actores.Catalogo (si es None no se revisa el actor).
    base: lista de dicts de convocatorias ya en la base (para duplicados).
    nuevo: True al registrar o revisar; False al auditar la base histórica (fechas vencidas = alerta).
    """
    hoy = hoy or date.today()
    r = {k: (texto(v) if not isinstance(v, (list, tuple)) else v) for k, v in registro.items()}
    if CAMPO_REQUISITOS in registro:  # este campo conserva un renglón por criterio
        r[CAMPO_REQUISITOS] = texto_con_renglones(registro[CAMPO_REQUISITOS])
    h = []

    def add(campo, nivel, problema, valor="", sugerencia="", regla=""):
        h.append(Hallazgo(campo, nivel, problema, str(valor)[:300], str(sugerencia)[:300], regla))

    # 1. Verificaciones del formulario
    for campo in VERIFICACIONES:
        if not marcado(r.get(campo, "")):
            add(campo, "Error", "Falta confirmar esta verificación en la página oficial", r.get(campo, ""), "checked", "R01")

    # 2. Obligatorios
    for campo in OBLIGATORIOS:
        if vacio(r.get(campo)):
            add(campo, "Error", "Campo obligatorio vacío", regla="R02")

    # 3. Listas controladas
    for campo in UNICOS:
        v = r.get(campo, "")
        if v and v not in CATALOGOS.get(campo, [v]):
            sug = max(CATALOGOS[campo], key=lambda o: similitud(v, o))
            add(campo, "Error", "Valor fuera de la lista", v, sug, "R03")
    for campo in MULTIPLES:
        vals = dividir(r.get(campo, ""))
        malos = [x for x in vals if x not in CATALOGOS.get(campo, vals)]
        for x in malos:
            sug = max(CATALOGOS[campo], key=lambda o: similitud(x, o))
            add(campo, "Error", "Valor fuera de la lista", x, sug, "R03")
        if vals:
            r[campo] = unir(vals)
    temas = dividir(r.get("Áreas temáticas de interés", ""))
    if len(temas) > 3:
        add("Áreas temáticas de interés", "Error", f"Tiene {len(temas)} temáticas; el máximo es 3", r["Áreas temáticas de interés"],
            unir(temas[:3]), "R04")

    # 4. Actor y carácter
    fuente = limpiar_nombre(r.get("Nombre de la Fuente", ""))
    if fuente.upper().startswith("*NUEVO") or not fuente:
        alterno = limpiar_nombre(r.get("Nombre de actor en CICLOPE", ""))
        if alterno and alterno.lower() not in ("nan",):
            add("Nombre de la Fuente", "Corregido", "La fuente decía *NUEVO; se usa el nombre de CICLOPE", r.get("Nombre de la Fuente", ""), alterno, "R05")
            fuente = alterno
        else:
            add("Nombre de la Fuente", "Error", "Sin actor: la fuente no puede ser *NUEVO ni estar vacía", r.get("Nombre de la Fuente", ""), regla="R05")
            fuente = ""
    r["Nombre de la Fuente"] = fuente
    actor = catalogo.buscar(fuente) if (catalogo is not None and fuente) else None
    if catalogo is not None and fuente:
        if actor is None:
            sug = "; ".join(catalogo.sugerencias(fuente)) or "Registrar el actor en el catálogo"
            add("Nombre de la Fuente", "Error", "El actor no está en el catálogo de actores", fuente, sug, "R06")
        else:
            r["Nombre de la Fuente"] = actor.nombre
            r["Nombre de actor en CICLOPE"] = actor.nombre
            if actor.estado_ciclope != "Creado en CICLOPE":
                add("Nombre de actor en CICLOPE", "Error",
                    f"El actor está '{actor.estado_ciclope}': hay que crearlo en CICLOPE antes de que la convocatoria entre a la base", actor.nombre,
                    "Solicitar la creación en el sistema de creación de actores", "R07")
            if actor.caracter:
                if r.get("Oficial / No Oficial") and r["Oficial / No Oficial"] != actor.caracter:
                    add("Oficial / No Oficial", "Corregido", f"El actor es '{actor.tipo}'", r["Oficial / No Oficial"], actor.caracter, "R08")
                r["Oficial / No Oficial"] = actor.caracter
            else:
                add("Oficial / No Oficial", "Error", "El actor no tiene tipo asignado en el catálogo", actor.nombre,
                    "Asignar tipo de actor", "R08")

    # 5. Fechas
    f_reg = fecha(r.get("Fecha de Registro")) or hoy
    r["Fecha de Registro"] = f_dmy(f_reg)
    permanente = r.get("¿La convocatoria es permanente?", "")
    f_lim = fecha(r.get("Fecha Límite de Aplicación"))
    if r.get("Fecha Límite de Aplicación") and f_lim is None:
        add("Fecha Límite de Aplicación", "Error", "Fecha con formato no válido (usar dd/mm/aaaa)", r["Fecha Límite de Aplicación"], regla="R09")
    if permanente == "Si" and f_lim:
        add("Fecha Límite de Aplicación", "Error", "Es permanente pero tiene fecha límite", f_dmy(f_lim),
            "Dejar vacía y explicar en 'Observaciones a la fecha límite'", "R09")
    f_ap = fecha(r.get(CAMPO_APERTURA))
    if r.get(CAMPO_APERTURA) and f_ap is None:
        add(CAMPO_APERTURA, "Error", "Fecha con formato no válido (usar dd/mm/aaaa)", r[CAMPO_APERTURA], regla="R09")
    if f_ap:
        r[CAMPO_APERTURA] = f_dmy(f_ap)
        if f_lim and f_ap > f_lim:
            add(CAMPO_APERTURA, "Error", "La fecha de apertura es posterior a la fecha límite", f_dmy(f_ap), regla="R09")
    if permanente == "No" and not f_lim:
        if f_ap and f_ap > hoy:
            add("Fecha Límite de Aplicación", "Alerta", f"Apertura anunciada para el {f_dmy(f_ap)} sin fecha de cierre publicada",
                "", "Registrar la fecha de cierre cuando el cooperante la publique", "R09")
        else:
            add("Fecha Límite de Aplicación", "Error", "No es permanente y no tiene fecha límite",
                sugerencia="Si la convocatoria aún no abre, registrar la fecha de apertura anunciada", regla="R09")
    if f_lim:
        r["Fecha Límite de Aplicación"] = f_dmy(f_lim)
        if f_lim < f_reg:
            add("Fecha Límite de Aplicación", "Error", "La fecha límite es anterior a la fecha de registro", f_dmy(f_lim), regla="R09")
        elif f_lim < hoy and nuevo:
            add("Fecha Límite de Aplicación", "Error", "La convocatoria ya cerró", f_dmy(f_lim), regla="R09")
        mayor = (f_lim - f_reg).days > 37
        actual = marcado(r.get("Tiempo de vencimiento es mayor a un mes y una semana", ""))
        if mayor != actual:
            add("Tiempo de vencimiento es mayor a un mes y una semana", "Corregido", "Se calcula con las fechas",
                "checked" if actual else "", "checked" if mayor else "", "R10")
        r["Tiempo de vencimiento es mayor a un mes y una semana"] = "checked" if mayor else ""

    # 6. Enlaces y correo
    for campo, nivel in (("Link de la Fuente Oferente", "Error"), ("Cómo aplicar", "Alerta")):
        v = r.get(campo, "")
        if v:
            primero = v.split(";")[0].strip()
            if not _URL.match(primero):
                arreglo = ""
                if not re.search(r"\s", primero) and "@" not in primero:
                    arreglo = re.sub(r"^https?//", "https://", primero)
                    if not arreglo.startswith("http"):
                        arreglo = "https://" + arreglo if "." in arreglo else ""
                add(campo, nivel, "No es un enlace válido (debe empezar por https:// y tener dominio)", v, arreglo, "R11")
            if "icetex.gov.co" in v and campo == "Link de la Fuente Oferente":
                add(campo, "Error", "El enlace de la fuente debe ser del oferente, no de ICETEX", v, regla="R11")
    correo = r.get("Email para mayor información", "")
    if correo:
        correo_l = correo.lower().replace("mailto:", "").strip()
        if correo_l in ("sin email", "sin correo", "no aplica", "n/a", "na", "no tiene", "no especifica", "ninguno", "no"):
            r["Email para mayor información"] = "Sin Email"
        else:
            partes = [x.strip() for x in re.split(r"[;,\s]+", correo_l) if x.strip()]
            if partes and all(_CORREO.match(x) for x in partes):
                r["Email para mayor información"] = "; ".join(partes)
            elif correo_l.startswith("http"):
                add("Email para mayor información", "Error" if nuevo else "Alerta",
                    "Es un enlace, no un correo: escribir el correo de contacto o 'Sin Email'", correo, "Sin Email", "R12")
            else:
                add("Email para mayor información", "Error", "Correo no válido (escribir el correo o 'Sin Email')", correo, regla="R12")

    # 6b. ¿Los enlaces son del sitio oficial del oferente?
    from calidad import dominios as DOM
    web_actor = actor.web if actor is not None else ""
    es_beca = r.get("Modalidad", "") == "Beca"
    for campo, aceptadas in DOM.ACEPTADAS.items():
        v = r.get(campo, "")
        urls = DOM.enlaces(v)
        if not urls:
            continue  # sin enlace (o texto de instrucciones): lo revisan R02 y R11
        limpio = v
        for u in urls:
            limpio = limpio.replace(u, DOM.quitar_rastreo(u))
        if limpio != v:
            add(campo, "Corregido", "Se quitaron parámetros de rastreo del enlace (utm_source…)", v, limpio, "R17")
            r[campo] = v = limpio
            urls = DOM.enlaces(v)
        for u in urls[:3]:
            cat, explicacion = DOM.clasificar(u, web_actor)
            if cat == "ICETEX":
                if campo == "Cómo aplicar" and es_beca:
                    add(campo, "Error" if nuevo else "Alerta", "Beca que se ofrece vía ICETEX: el sistema registra becas que no están en ICETEX",
                        u, "Descartar, o poner el enlace del oferente si también se puede aplicar directamente", "R17")
                continue  # el enlace de la fuente en ICETEX ya lo revisa R11
            if cat in aceptadas or cat in ("Sin enlace", "Sin dominio del actor"):
                continue
            grave = cat in DOM.GRAVES and nuevo
            add(campo, "Error" if grave else "Alerta", f"{cat}: {explicacion}", u,
                DOM.dominios_de(web_actor)[0] if campo == "Link de la Fuente Oferente" and web_actor else "Enlace en el sitio oficial del oferente", "R17")
            break

    # 7. Financiación: el monto cuando esté disponible, o la descripción de los beneficios
    if vacio(r.get("Financiación")) and vacio(r.get("Observaciones sobre el financiamiento")):
        add("Observaciones sobre el financiamiento", "Error",
            "Sin monto ni descripción de los beneficios: registrar el monto en USD o describir qué ofrece la convocatoria",
            regla="R13")
    m = monto(r.get("Financiación"))
    if r.get("Financiación") and m is None:
        add("Financiación", "Error", "El monto debe ser un número en USD", r["Financiación"], regla="R13")
    elif m is not None:
        r["Financiación"] = f"{m:.0f}"
        tipo_monto = r.get(CAMPO_TIPO_MONTO, "")
        if tipo_monto not in TIPOS_MONTO and (nuevo or m >= 1_000_000):
            add(CAMPO_TIPO_MONTO, "Alerta" if not nuevo else "Error",
                "Indicar si el monto es por beneficiario/proyecto o el presupuesto total de la convocatoria"
                + ("" if nuevo else f" (monto alto: USD {m:,.0f})"), tipo_monto,
                "Presupuesto total de la convocatoria" if m >= 5_000_000 else "Por beneficiario o proyecto", "R13")
        if m == 0:
            add("Financiación", "Alerta", "Monto en cero: confirmar si no se conoce", "0", regla="R13")

    # 8. Textos
    nombre = r.get("Nombre de la Convocatoria", "")
    palabras = set(re.findall(r"[a-záéíóúñ]+", nombre.lower()))
    if nombre and len(palabras & _INGLES) >= 2 and not palabras & _ESPANOL:
        add("Nombre de la Convocatoria", "Alerta", "Parece estar solo en otro idioma",
            nombre, "Traducción al español (Nombre original)", "R14")
    if r.get("Descripción") and len(r["Descripción"]) < 80:
        add("Descripción", "Alerta", "Descripción muy corta (menos de 80 caracteres)", r["Descripción"], regla="R15")

    # 8b. Requisitos y criterios según la modalidad (solo convocatorias nuevas: la base histórica no tenía el campo)
    if nuevo:
        req = r.get(CAMPO_REQUISITOS, "")
        mod = modalidad_corta(r.get("Modalidad"))
        leidos = leer_requisitos(req, mod)
        if vacio(req) or not any(v for v in leidos.values()):
            add(CAMPO_REQUISITOS, "Error", "Faltan los requisitos y condiciones de participación", "",
                plantilla(mod).replace("\n", " | "), "R18")
        else:
            faltan = criterios_vacios(req, mod)
            if faltan:
                add(CAMPO_REQUISITOS, "Alerta", f"Faltan criterios de la modalidad {mod}: " + ", ".join(faltan),
                    "", f"Completar cada uno; si la convocatoria no lo dice, escribir «{NO_SE_INDICA}»", "R18")

    # Socialización: NO es una regla de validación. Toda convocatoria válida entra a la base; esto solo sugiere
    # cuáles difundir además por los canales institucionales (numeral 5 del procedimiento). No genera hallazgos.
    if nuevo:
        sugerida, motivo = priorizacion(r, hoy)
        r["Se sugiere para priorización"] = "checked" if sugerida else ""
        r[CAMPO_MOTIVO_PRIORIZACION] = motivo

    # 9. Duplicados
    if base:
        url = r.get("Cómo aplicar", "").rstrip("/").lower()
        for otro in base:
            if otro is registro:
                continue
            otro_url = texto(otro.get("Cómo aplicar", "")).rstrip("/").lower()
            if url and url.startswith("http") and url == otro_url:
                add("Cómo aplicar", "Error", "Ya existe una convocatoria con el mismo enlace", otro.get("Nombre de la Convocatoria", ""), regla="R16")
                break
            if nombre and similitud(nombre, otro.get("Nombre de la Convocatoria", "")) >= 92:
                add("Nombre de la Convocatoria", "Alerta", "Nombre muy parecido a otra convocatoria",
                    otro.get("Nombre de la Convocatoria", ""), regla="R16")
                break

    return r, h


def bloquea(hallazgos):
    return any(x.nivel == "Error" for x in hallazgos)


REGLAS = {
    "R01": "Verificaciones de elegibilidad de Colombia y enlace activo",
    "R02": "Campos obligatorios",
    "R03": "Valores de listas controladas",
    "R04": "Máximo 3 temáticas",
    "R05": "Actor definido (no *NUEVO)",
    "R06": "Actor en el catálogo de actores",
    "R07": "Actor creado en CICLOPE antes de entrar a la base",
    "R08": "Carácter Oficial / No Oficial según el tipo de actor",
    "R09": "Vigencia: fechas de apertura y cierre, convocatoria abierta o con apertura anunciada",
    "R10": "Plazo mayor a un mes y una semana (calculado)",
    "R11": "Enlaces válidos y del oferente",
    "R12": "Correo válido o 'Sin Email'",
    "R13": "Monto en USD (cuando esté disponible) o descripción de los beneficios, y tipo de monto",
    "R14": "Nombre en español con el original entre paréntesis",
    "R15": "Descripción suficiente",
    "R16": "Duplicados",
    "R17": "Enlaces del sitio oficial del oferente (sin acortadores, agregadores, boletines de otras entidades ni ICETEX)",
    "R18": "Requisitos y condiciones de participación según la modalidad",
}
