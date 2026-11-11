"""Funciones para leer texto: palabras clave, fechas, montos, correos e idiomas."""
import re
import unicodedata
from datetime import date

MESES = {
    # español
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # inglés
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # francés
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "octobre": 10, "novembre": 11, "decembre": 12,
    # alemán
    "januar": 1, "februar": 2, "marz": 3, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # italiano
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "settembre": 9,
    "ottobre": 10, "dicembre": 12,
    # portugués
    "janeiro": 1, "fevereiro": 2, "marco": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    # neerlandés
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "augustus": 8,
}

PALABRAS_CIERRE = [
    "deadline", "closing date", "closes on", "apply by", "applications close", "application period", "submission",
    "fecha límite", "fecha limite", "plazo", "cierre", "hasta el", "date limite", "date de clôture", "clôture",
    "bewerbungsschluss", "bewerbungsfrist", "frist", "scadenza", "prazo", "sluitingsdatum", "deadline for applications",
]
PALABRAS_PERMANENTE = [
    "rolling basis", "rolling admissions", "open all year", "open year-round", "no deadline", "ongoing",
    "abierta todo el año", "convocatoria permanente", "en cualquier momento", "sin fecha límite",
]


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def normalizar(t):
    return re.sub(r"\s+", " ", sin_tildes(str(t or "")).lower()).strip()


def contiene(texto_norm, termino):
    """Busca el término como palabra o frase completa (no dentro de otra palabra)."""
    t = normalizar(termino)
    if not t:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", texto_norm) is not None


def alguno(texto_norm, terminos):
    return [t for t in terminos if contiene(texto_norm, t)]


# --- fechas ----------------------------------------------------------------
_MES = "|".join(sorted(MESES, key=len, reverse=True))
_PATRONES_FECHA = [
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:de\s+)?({_MES})\.?,?\s+(?:de\s+)?(\d{{4}})\b"), "dmy"),
    (re.compile(rf"\b({_MES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b"), "num"),
]


def fechas(texto):
    """Devuelve [(fecha, posición)] encontradas en el texto (ya normalizado)."""
    salida = []
    for patron, tipo in _PATRONES_FECHA:
        for m in patron.finditer(texto):
            try:
                if tipo == "dmy":
                    d, mes, a = int(m.group(1)), MESES[m.group(2)], int(m.group(3))
                elif tipo == "mdy":
                    mes, d, a = MESES[m.group(1)], int(m.group(2)), int(m.group(3))
                elif tipo == "iso":
                    a, mes, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if mes > 12 and d <= 12:  # formato de EE. UU.
                        d, mes = mes, d
                salida.append((date(a, mes, d), m.start()))
            except (ValueError, KeyError):
                continue
    return salida


def fecha_cierre(texto_norm, hoy=None):
    """Busca la fecha límite cerca de palabras como 'deadline' o 'fecha límite'.

    Devuelve (fecha futura más próxima o None, (inicio, fin) de la evidencia, vencida).
    'vencida' es True cuando solo se encontraron fechas límite ya pasadas."""
    hoy = hoy or date.today()
    futuras, pasadas = [], []
    todas = fechas(texto_norm)
    for palabra in PALABRAS_CIERRE:
        p = normalizar(palabra)
        for m in re.finditer(r"(?<![a-z])" + re.escape(p), texto_norm):
            for f, pos in todas:
                if m.start() - 40 <= pos <= m.end() + 160:
                    (futuras if f >= hoy else pasadas).append((f, (min(m.start(), pos), max(m.end(), pos + 12))))
    if futuras:
        f, evid = min(futuras, key=lambda x: x[0])
        return f, evid, False
    if pasadas:
        f, evid = max(pasadas, key=lambda x: x[0])
        return None, evid, True
    return None, None, False


def frase(texto, ini, fin, margen=160):
    """Recorta la oración completa que contiene el tramo [ini, fin)."""
    if ini is None:
        return ""
    a = max(0, ini - margen)
    corte = max(texto.rfind(". ", a, ini), texto.rfind(": ", a, max(a, ini - 25)))
    a = corte + 2 if corte >= 0 else (texto.find(" ", a) + 1 if a else 0)
    b = texto.find(". ", fin, fin + margen)
    b = b + 1 if b >= 0 else min(len(texto), fin + margen)
    if b < len(texto) and b == fin + margen:
        b = texto.rfind(" ", fin, b) if texto.rfind(" ", fin, b) > 0 else b
    return texto[a:b].strip()


def es_permanente(texto_norm):
    return bool(alguno(texto_norm, PALABRAS_PERMANENTE))


# --- montos ----------------------------------------------------------------
_MONEDA = r"(€|eur|euros?|£|gbp|us\$|usd|\$|chf|cad|aud|sek|nok|dkk|jpy|¥|krw|₩)"
_NUMERO = r"(\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d{1,2})?"
_PAT_MONTO = [
    re.compile(_MONEDA + r"\s?" + _NUMERO),
    re.compile(_NUMERO + r"\s?" + _MONEDA),
]
_CODIGOS = {"€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "£": "GBP", "gbp": "GBP", "us$": "USD",
            "usd": "USD", "$": "USD", "chf": "CHF", "cad": "CAD", "aud": "AUD", "sek": "SEK", "nok": "NOK",
            "dkk": "DKK", "jpy": "JPY", "¥": "JPY", "krw": "KRW", "₩": "KRW"}
PALABRAS_COBERTURA = [
    "full tuition", "tuition fee waiver", "tuition waiver", "living allowance", "monthly stipend", "stipend",
    "travel costs", "health insurance", "fully funded", "matrícula", "manutención", "seguro médico", "pasajes",
    "frais de scolarité", "allocation mensuelle", "studiengebühren", "monatlich", "100%",
]


def montos(texto):
    """Devuelve [(valor, moneda, (inicio, fin))]; texto en minúsculas (sin quitar símbolos)."""
    salida = []
    for i, patron in enumerate(_PAT_MONTO):
        for m in patron.finditer(texto):
            moneda = m.group(1) if i == 0 else m.group(3)
            numero = m.group(2) if i == 0 else m.group(1)
            limpio = re.sub(r"[.,\s]", "", numero)
            try:
                valor = int(limpio)
            except ValueError:
                continue
            if valor < 100 or valor > 10_000_000:
                continue
            salida.append((valor, _CODIGOS.get(moneda.strip(), moneda.upper()), (m.start(), m.end())))
    return salida


# --- correos, idiomas, niveles ---------------------------------------------
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def correos(texto):
    vistos = []
    for c in _CORREO.findall(texto):
        c = c.strip(".").lower()
        if c not in vistos and not c.endswith((".png", ".jpg", ".gif")):
            vistos.append(c)
    return vistos


IDIOMAS_HTML = {"en": "Inglés", "es": "Español", "fr": "Francés", "de": "Alemán", "it": "Italiano", "pt": "Portugués"}
IDIOMAS_MENCION = {
    "Inglés": ["taught in english", "english-taught", "in english", "english language"],
    "Español": ["en español", "taught in spanish"],
    "Francés": ["en français", "taught in french"],
    "Alemán": ["auf deutsch", "taught in german", "german language"],
    "Italiano": ["in italiano", "taught in italian"],
    "Portugués": ["em português", "taught in portuguese"],
}

NIVELES = {
    "Pregrado": ["bachelor", "undergraduate", "pregrado", "licence", "licenciatura", "grado"],
    "Maestría": ["master", "masters", "master's", "msc", "mba", "maestria", "magister", "laurea magistrale"],
    "Doctorado": ["phd", "doctoral", "doctorate", "doctorado", "doctorat"],
    "Posdoctorado": ["postdoc", "postdoctoral", "posdoctoral"],
    "Curso corto": ["summer school", "short course", "escuela de verano", "curso corto", "école d'été"],
}

PUBLICO = {
    "Academia/Universidades": ["researchers", "researcher", "faculty", "professors", "investigadores", "docentes", "academics",
                               "universities", "research institutions", "universidades", "centros de investigacion"],
    "Funcionarios Públicos": ["public servants", "civil servants", "government officials", "funcionarios publicos", "servidores publicos"],
    "Entidades sin animo de lucro (ESAL)": ["ngo", "ngos", "non-profit", "nonprofit", "not-for-profit", "civil society organisations",
                                            "civil society organizations", "csos", "ong", "ongs", "organizaciones de la sociedad civil",
                                            "sin animo de lucro", "sin fines de lucro", "charities", "associations"],
    "Empresas Privadas Pequeñas (MiPyme, MicroPYME, Startups, Emprendimientos)": ["startup", "startups", "start-ups", "smes", "sme",
                                            "small and medium", "pymes", "mipymes", "emprendimientos", "emprendedores", "entrepreneurs",
                                            "social enterprises", "early-stage companies"],
    "Empresas Privadas Grandes": ["large companies", "corporations", "grandes empresas"],
    "Entidades Públicas Territoriales": ["local governments", "municipalities", "subnational governments", "gobiernos locales",
                                         "municipios", "alcaldias", "gobernaciones"],
    "Entidades Públicas Nacionales": ["government agencies", "public institutions", "public entities", "entidades publicas",
                                      "ministries", "ministerios", "national governments"],
    "Organizaciones etnicas y/o comunitarias": ["community-based organisations", "community-based organizations", "community organizations",
                                                "grassroots organizations", "indigenous organizations", "organizaciones comunitarias",
                                                "organizaciones de base", "consejos comunitarios"],
}
POBLACIONES = {
    "Mujeres": ["women", "female", "mujeres", "femmes", "frauen"],
    "Jovenes": ["young", "youth", "jovenes", "under 30", "under 35"],
    "Indigenas": ["indigenous", "indigenas", "pueblos originarios"],
    "Negros, Afrodescendeintes, Raizales y Palenqueros": ["afro-descendant", "afrodescendiente", "afrodescendientes", "black students"],
    "Discapacidad": ["disability", "disabilities", "discapacidad", "handicap"],
}
