"""Control de entrada a la bandeja para lo que llega solo (mapeo automático y búsqueda con Gemini).

Una convocatoria automática solo pasa a «Por revisar» si llega en español y con los campos obligatorios completos.
Si no, queda «Por completar»: no aparece en la bandeja y el sistema la vuelve a intentar en la siguiente búsqueda.
Lo que siempre confirma una persona (las verificaciones, el actor en CICLOPE) no cuenta aquí.
"""
import re
import unicodedata

from calidad import reglas as R

ESTADO = "Por completar"
INTENTOS_MAXIMOS = 4  # después de esto deja de reintentar sola; queda en la lista para descartarla o reintentarla a mano

# Reglas que resuelve quien revisa, no el programa
_DE_LA_PERSONA = {"R01", "R05", "R06", "R07", "R08", "R16"}

CAMPOS_TEXTO = ["Nombre de la Convocatoria", "Descripción", "Objetivos General y Específicos", R.CAMPO_REQUISITOS,
                "Observaciones a la fecha límite de aplicación", "Observaciones sobre el financiamiento"]

_PALABRAS = {
    "es": "de la el los las que en por para con una del al se su sus como más este esta son ser pueden debe deben "
          "también hasta sobre entre cada año años convocatoria beca becas apoyo financiación proyectos solicitud "
          "requisitos postulación fecha límite país países".split(),
    "en": "the and of to for with is are this that be will from by on at an or which their your our can must should "
          "applications apply applicants deadline grant grants funding scholarship award who have has more".split(),
    "pt": "não são uma com dos das pelo pela também para os às ao bolsa bolsas edital inscrições prazo projeto "
          "projetos você seu sua".split(),
    "fr": "le les des et est pour une dans sur par avec qui sont aux du vous nous leur bourse bourses candidature "
          "appel date limite projets".split(),
    "de": "der die das und ist für mit von den dem ein eine sind auf werden bei sich auch nicht oder stipendium "
          "bewerbung frist förderung".split(),
}
_CONJUNTOS = {k: set(v) for k, v in _PALABRAS.items()}
_TITULOS_EN = set("program programme programs fellowship fellowships grant grants award awards prize call calls proposals "
                  "scholarship scholarships fund funds training week research challenge initiative opportunity opportunities "
                  "open applications summer school support young leaders course workshop competition innovation".split())
_TITULOS_ES = set("programa beca becas premio premios convocatoria fondo curso concurso iniciativa subvención subvenciones "
                  "ayudas apoyo formación investigación semana taller".split())


def _palabras(texto):
    t = unicodedata.normalize("NFC", str(texto or "").lower())
    return re.findall(r"[a-záéíóúñüàâçèêëîïôûœãõäöß]+", t)


def idioma(texto):
    """Idioma probable ('es', 'en', 'pt', 'fr', 'de') o '' si el texto es muy corto o no se puede saber."""
    p = _palabras(texto)
    if not p:
        return ""
    puntos = {k: sum(1 for w in p if w in c) for k, c in _CONJUNTOS.items()}
    mejor = max(puntos, key=puntos.get)
    if puntos[mejor] == 0 or (len(p) < 4 and puntos[mejor] < 2):
        return ""
    return mejor if puntos[mejor] > puntos["es"] or mejor == "es" else "es"


def en_espanol(texto, campo=""):
    """True si el texto está en español (o es tan corto que no se sabe, como un nombre propio)."""
    t = str(texto or "").strip()
    if not t or t == R.NO_SE_INDICA:
        return True
    if campo == "Nombre de la Convocatoria":
        t = t.split(" (")[0]  # el original va entre paréntesis
        p = set(_palabras(t))
        if p & _TITULOS_EN and not p & _CONJUNTOS["es"] and not p & _TITULOS_ES:
            return False  # «Training Week», «Research Fellowship»: título en inglés sin traducir
    if campo == R.CAMPO_REQUISITOS:  # se mira el contenido, no los títulos de los criterios
        t = " ".join(l.split(":", 1)[1] if ":" in l else l for l in t.splitlines())
    return idioma(t) in ("es", "")


def criterios_con_contenido(texto):
    n = 0
    for linea in str(texto or "").splitlines():
        if ":" in linea:
            valor = linea.split(":", 1)[1].strip()
            if valor and valor.rstrip(".").lower() != R.NO_SE_INDICA.lower():
                n += 1
    return n


def faltantes(datos, hallazgos):
    """Lista, en palabras claras, de lo que impide que la convocatoria pase a la bandeja. Vacía = puede pasar."""
    salida = []
    for h in hallazgos:
        h = h if isinstance(h, dict) else h.__dict__
        if h.get("regla") in _DE_LA_PERSONA:
            continue
        if h.get("nivel") == "Error" or h.get("regla") in ("R14", "R15"):
            salida.append(f"{h.get('campo')}: {h.get('problema')}")
    for campo in CAMPOS_TEXTO:
        if not en_espanol(datos.get(campo, ""), campo):
            salida.append(f"{campo}: no está en español")
    req = datos.get(R.CAMPO_REQUISITOS, "")
    if str(req).strip() and criterios_con_contenido(req) < 2:
        salida.append(f"{R.CAMPO_REQUISITOS}: la página casi no trae información de requisitos")
    vistos, unicos = set(), []
    for s in salida:
        if s not in vistos:
            vistos.add(s)
            unicos.append(s)
    return unicos
