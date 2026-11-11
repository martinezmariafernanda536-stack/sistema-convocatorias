"""¿El enlace es del sitio oficial del oferente?

Clasifica un enlace en una de estas categorías:
  Oficial del oferente         el dominio es el del actor (o un subdominio)
  Institucional                dominio de gobierno, organismo internacional o universidad, pero no el registrado del actor
  Plataforma de postulación    formularios y gestores de solicitudes (válido para "Cómo aplicar", no como fuente)
  Acortador                    bit.ly, lnkd.in, forms.gle…: esconden el destino; hay que poner el enlace final
  Agregador / intermediario    portales que republican convocatorias de otros (fundsforngos, onglink…)
  Boletín de otra entidad      boletines y páginas de difusión de otras entidades (Boletín de Oferta Internacional de la
                               Alcaldía de Bogotá, Cancillería, secretarías…): hay que poner el enlace del cooperante
  ICETEX                       la beca se ofrece vía ICETEX (se excluye del mapeo)
  Otro sitio                   no coincide con el actor registrado
  Sin dominio del actor        el actor no tiene dominio oficial en el catálogo; no se puede comparar
"""
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ACORTADORES = {"bit.ly", "cutt.ly", "lnkd.in", "forms.gle", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "rb.gy",
               "shorturl.at", "is.gd", "buff.ly", "linktr.ee", "tiny.cc", "s.id", "rebrand.ly", "ffngos.org"}
PLATAFORMAS = {"jotform.com", "docs.google.com", "drive.google.com", "forms.office.com", "forms.microsoft.com",
               "airtable.com", "fluxx.io", "tfaforms.net", "submittable.com", "b2clogin.com", "notion.so", "notion.site",
               "typeform.com", "smapply.io", "smapply.org", "surveymonkey.com", "vform.com.co", "sessionboard.com",
               "wiin.io", "innpactia.com", "zoom.us", "eventbrite.com", "formstack.com", "qualtrics.com",
               "fillout.com", "grantinterface.com", "good-grants.com", "evalato.com", "awardsplatform.com",
               "zengine.com", "ifundwomen.com"}
AGREGADORES = {"fundsforngos.org", "onglink.org", "opportunitiesforyouth.org", "opportunitydesk.org",
               "scholarshipsforafricans.com", "startupgrantsindia.com", "terravivagrants.org", "devex.com",
               "developmentaid.org", "scholars4dev.com", "aicogestion.org", "hotcoursesabroad.com", "leverageedu.com",
               "opportunitiescorners.com", "youthop.com", "grantedai.com", "opengrants.io", "instrumentl.com",
               "becas.com", "becasinternacionales.net", "estudiarfuera.com", "comunidaddelintercambio.com",
               "innovationbridge.info", "news.fundsforngos.org", "www2.fundsforngos.org"}
# Entidades que difunden convocatorias de terceros (boletines). Cualquier dominio público colombiano (.gov.co) que no sea
# el del actor se trata igual: en Colombia las entidades públicas difunden, no ofrecen, la cooperación internacional.
BOLETINES = {"bogota.gov.co", "educacionbogota.edu.co", "redacademica.edu.co", "cancilleria.gov.co", "apccolombia.gov.co",
             "minciencias.gov.co", "mineducacion.gov.co", "colombiacompra.gov.co"}
_PUBLICO_COLOMBIA = re.compile(r"\.gov\.co$|\.mil\.co$")

# Terminaciones de dominios institucionales (gobierno, organismos, academia)
_INSTITUCIONAL = re.compile(
    r"(\.gov(\.[a-z]{2})?|\.gob(\.[a-z]{2})?|\.go\.[a-z]{2}|\.gouv\.fr|\.govt\.nz|\.gc\.ca|\.admin\.ch|\.gv\.at|"
    r"\.gov\.br|\.edu(\.[a-z]{2})?|\.ac\.[a-z]{2}|\.int|europa\.eu|\.un\.org|undp\.org|unesco\.org|unicef\.org|"
    r"fao\.org|oas\.org|iadb\.org|worldbank\.org|caf\.com)$")
PARAMETROS_RASTREO = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|_hsenc|_hsmi|igshid)$", re.I)


def host(url):
    """Dominio sin 'www.' ni punto final. Acepta 'https//' mal escrito."""
    u = str(url or "").strip()
    u = re.sub(r"^(https?)//", r"\1://", u, flags=re.I)
    if not re.match(r"^[a-z]+://", u, re.I):
        u = "https://" + u
    h = urlparse(u).netloc.lower().split(":")[0].strip(".")
    return h[4:] if h.startswith("www.") else h


def _en(h, conjunto):
    return any(h == d or h.endswith("." + d) for d in conjunto)


def dominios_de(dominio_actor):
    """El sitio de un actor puede tener varios dominios separados por ';' (el primero es el principal)."""
    return [host(d) for d in str(dominio_actor or "").split(";") if host(d)]


def coincide(url, dominio_actor):
    h = host(url)
    return bool(h) and any(h == a or h.endswith("." + a) or a.endswith("." + h) for a in dominios_de(dominio_actor))


_ENLACE = re.compile(r"(?:https?:?/{1,2}|www\.)[^\s<>\"')\]]+", re.I)


def enlaces(texto):
    """Enlaces que hay dentro de un texto (por ejemplo, instrucciones de 'Cómo aplicar')."""
    salida = []
    for m in _ENLACE.findall(str(texto or "")):
        m = m.rstrip(".,;:")
        if "." in m and m not in salida:
            salida.append(m)
    return salida


def institucional(url):
    return bool(_INSTITUCIONAL.search(host(url)))


def quitar_rastreo(url):
    """Quita utm_source y otros parámetros de rastreo (por ejemplo ?utm_source=chatgpt.com)."""
    u = str(url or "").strip()
    if "?" not in u:
        return u
    p = urlparse(u)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not PARAMETROS_RASTREO.match(k)]
    return urlunparse(p._replace(query=urlencode(q)))


def clasificar(url, dominio_actor=""):
    """Devuelve (categoría, explicación)."""
    h = host(url)
    if not h or "." not in h:
        return "Sin enlace", ""
    if "icetex.gov.co" in h:
        return "ICETEX", "El enlace es de ICETEX: la convocatoria se ofrece vía ICETEX"
    if _en(h, ACORTADORES):
        return "Acortador", f"{h} es un acortador o redireccionador: poner el enlace final del oferente"
    if _en(h, AGREGADORES):
        return "Agregador / intermediario", f"{h} republica convocatorias de otros: buscar la página del oferente"
    if dominio_actor and coincide(url, dominio_actor):
        return "Oficial del oferente", f"Coincide con el sitio del actor ({h})"
    if _en(h, BOLETINES) or _PUBLICO_COLOMBIA.search(h):
        return "Boletín de otra entidad", (f"{h} es de una entidad que difunde convocatorias de terceros: "
                                           "registrar el enlace oficial del cooperante")
    if _en(h, PLATAFORMAS):
        return "Plataforma de postulación", f"{h} es una plataforma de formularios o solicitudes"
    if not dominio_actor:
        return ("Institucional" if institucional(url) else "Sin dominio del actor"), \
            "El actor no tiene dominio oficial registrado en el catálogo"
    if institucional(url):
        return "Otro sitio institucional", (f"Dominio institucional ({h}) distinto del registrado para el actor "
                                            f"({dominios_de(dominio_actor)[0]}): confirmar que es del cooperante")
    return "Otro sitio", f"{h} no coincide con el sitio del actor ({', '.join(dominios_de(dominio_actor))})"


# Qué categorías se aceptan en cada campo
# ("Institucional" solo sale cuando el actor no tiene dominio registrado; si lo tiene y no coincide es "Otro sitio institucional")
ACEPTADAS = {
    "Link de la Fuente Oferente": {"Oficial del oferente", "Institucional"},
    "Cómo aplicar": {"Oficial del oferente", "Institucional", "Plataforma de postulación"},
}
GRAVES = {"Acortador", "Agregador / intermediario", "Boletín de otra entidad"}
