"""Descubrir convocatorias fuera de las fuentes configuradas.

Dos caminos, los dos gratis:
  1. Agregadores como radar (Opportunity Desk, Scholars4Dev…): se lee su listado, se entra a cada publicación y se sigue
     el enlace a la PÁGINA OFICIAL del oferente. Se registra solo esa página oficial, nunca la del agregador; si la
     publicación no trae un enlace oficial, no se usa.
  2. Portal de financiación de la Unión Europea (Funding & Tenders): su búsqueda pública (la misma que usa el portal)
     devuelve las convocatorias abiertas o por abrir. Se consultan las que mencionan Colombia, América Latina, terceros
     países o cooperación internacional.

Lo que se encuentra pasa después por los mismos filtros que la búsqueda normal (Gemini, elegibilidad, duplicados y
control de entrada). Los sitios oficiales nuevos quedan como «fuentes sugeridas» para que un administrador decida.
"""
import html as _html
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from calidad import dominios as D
from motor import extraer
from motor.config import Fuente

log = logging.getLogger("mapeo")

TIPO_AGREGADOR = "Agregador"
TIPO_UE = "Portal de la Unión Europea"
TIPO_DESCUBIERTA = "Descubierta por el radar"

REDES = {"facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com", "youtube.com", "youtu.be", "t.me",
         "telegram.me", "whatsapp.com", "wa.me", "pinterest.com", "reddit.com", "tiktok.com", "google.com", "apple.com",
         "play.google.com", "amazon.com", "wikipedia.org", "feedburner.com", "wordpress.com", "wordpress.org",
         "gravatar.com", "disqus.com", "addtoany.com", "sharethis.com", "mailchimp.com", "list-manage.com", "paypal.com",
         "patreon.com", "medium.com", "bsky.app", "threads.net", "flipboard.com", "tumblr.com", "vk.com", "quora.com",
         "doubleclick.net", "googlesyndication.com", "adservice.google.com", "amzn.to", "unicaf.org", "udemy.com",
         "coursera.org", "forms.gle", "booking.com", "jetpack.com", "w.org", "schema.org", "cloudflare.com", "creativecommons.org"}
_NO_PUBLICACION = re.compile(r"/(category|categoria|tag|tags|page|author|autor|about|about-us|contact|contact-us|privacy|"
                             r"privacy-policy|terms|disclaimer|feed|wp-[a-z]+|login|register|subscribe|search|cart|shop|"
                             r"advertise|sitemap|faq|donate|newsletter)(/|$)|[?&](s|page|replytocom|share)=", re.I)
_PALABRAS = re.compile(r"scholarship|fellowship|grant|award|prize|funding|fund\b|call for|competition|programme|program\b|"
                       r"beca|subvenci|convocatoria|premio|bourse|stipend|residenc|exchange|training|internship|"
                       r"opportunit|contest|challenge|masters?\b|ph\.?d|research", re.I)
_PISTA = re.compile(r"\b(apply|application|official|website|web ?site|more info|more information|learn more|visit|"
                    r"click here|details|read more|aplica|aplicar|postula|sitio oficial|p[aá]gina oficial|"
                    r"m[aá]s informaci[oó]n|link|enlace|here)\b", re.I)
# «Apply» que lleva a una plataforma de postulación o a un inicio de sesión: no describe la convocatoria
_PLATAFORMA = re.compile(r"(^|\.)(interfolio\.com|smapply\.[a-z]+|fluxx\.io|submittable\.com|embark\.com|slideroom\.com|"
                         r"myblueprint|awardspring\.com|academicworks\.com|applyweb\.com|liaisoncas\.com|"
                         r"commonapp\.org|grantinterface\.com|surveymonkey\.com|typeform\.com|jotform\.com|"
                         r"qualtrics\.com|formstack\.com|wufoo\.com|zohopublic\.com|cognitoforms\.com|"
                         r"forms\.office\.com|docs\.google\.com|drive\.google\.com|dropbox\.com|audible\.[a-z.]+|"
                         r"semantik\.[a-z]+|studentaid\.gov)$", re.I)
_RUTA_ACCESO = re.compile(r"/(login|log-in|signin|sign-in|sign_in|signup|sign-up|register|registration|account|"
                          r"apply/?$|applicant|application-portal|portal/?$|auth|sso|cas/login|user/login)(/|\?|$)|"
                          r"\.(pdf|docx?|xlsx?|pptx?|zip)(\?|$)", re.I)
_PISTA_INFO = re.compile(r"\b(official|website|web ?site|more info|more information|learn more|details|visit|"
                         r"sitio oficial|p[aá]gina oficial|m[aá]s informaci[oó]n)\b", re.I)
_SITIO_OFICIAL = re.compile(r"(\.gov(\.[a-z]{2})?|\.gob(\.[a-z]{2})?|\.go\.[a-z]{2}|\.gouv\.fr|\.govt\.nz|\.gc\.ca|"
                            r"\.admin\.ch|\.gv\.at|\.gov\.br|\.int|europa\.eu|\.un\.org|undp\.org|unesco\.org|unicef\.org|"
                            r"fao\.org|oas\.org|iadb\.org|worldbank\.org|caf\.com)$")


def _host(url):
    return D.host(url)


def descartable(url):
    """Enlaces que no son la página oficial de un oferente: redes, otros agregadores, boletines, formularios, ICETEX."""
    h = _host(url)
    if not h or "." not in h:
        return True
    if any(h == d or h.endswith("." + d) for d in REDES):
        return True
    if _PLATAFORMA.search(h) or _RUTA_ACCESO.search(urlparse(url).path + ("?" if urlparse(url).query else "")):
        return True
    if re.match(r"^(apply|login|signin|portal|auth|sso|admissions?-portal|my)\.", h):
        return True
    if len(urlparse(url).path.strip("/")) < 3:  # la portada de un sitio no es una convocatoria
        return True
    categoria, _ = D.clasificar(url)
    return categoria in ("ICETEX", "Agregador / intermediario", "Boletín de otra entidad", "Plataforma de postulación")


def _zona(sopa, articulo=False):
    for t in sopa(["script", "style", "noscript", "form"] + (["header", "footer", "nav", "aside"] if articulo else [])):
        t.decompose()
    if articulo:
        z = (sopa.find("article") or sopa.find(class_=re.compile(r"entry-content|post-content|article-content|"
                                                                 r"single-content|td-post-content", re.I)))
        if z:
            return z
    return sopa.find("main") or sopa.find(id=re.compile(r"^(content|main|primary)$", re.I)) or sopa.body or sopa


def publicaciones(html, url_pagina, maximo=40):
    """Enlaces del listado de un agregador a sus publicaciones (una convocatoria o un resumen de varias)."""
    base = _host(url_pagina)
    zona = _zona(BeautifulSoup(html or "", "html.parser"))
    vistos, salida = set(), []
    for a in zona.find_all("a", href=True):
        url = urljoin(url_pagina, a["href"]).split("#")[0]
        if not url.startswith("http") or _host(url) != base or url.rstrip("/") == url_pagina.rstrip("/"):
            continue
        ruta = urlparse(url).path
        if _NO_PUBLICACION.search(url) or len(ruta.strip("/")) < 10 or url in vistos:
            continue
        texto = " ".join(a.get_text(" ", strip=True).split())
        if not (_PALABRAS.search(texto) or _PALABRAS.search(ruta.replace("-", " "))):
            continue
        if len(texto.split()) < 3 and ruta.count("-") < 2:
            continue
        vistos.add(url)
        salida.append((url, texto))
        if len(salida) >= maximo:
            break
    return salida


def enlaces_oficiales(html, url_pagina, maximo=30):
    """Lee una publicación del agregador y devuelve (externos, internos).

    externos: enlaces a la página del oferente («Apply», «Official website», «Click here»…). Si no hay ninguno con esa
              pista, solo se aceptan enlaces a sitios institucionales (gobiernos, organismos, universidades).
    internos: enlaces «apply / more info» a otras publicaciones del mismo agregador (los resúmenes con muchas)."""
    base = _host(url_pagina)
    zona = _zona(BeautifulSoup(html or "", "html.parser"), articulo=True)
    con_pista, sin_pista, internos, vistos = [], [], [], set()
    for a in zona.find_all("a", href=True):
        url = D.quitar_rastreo(urljoin(url_pagina, a["href"]).strip()).split("#")[0]
        if not url.startswith("http") or url in vistos:
            continue
        vistos.add(url)
        texto = " ".join(a.get_text(" ", strip=True).split())
        pista = bool(_PISTA.search(texto) or _PISTA.search(a.get("title", "") or ""))
        if _host(url) == base:
            if pista and not _NO_PUBLICACION.search(url) and len(urlparse(url).path.strip("/")) >= 10:
                internos.append((url, texto))
            continue
        if descartable(url):
            continue
        (con_pista if pista else sin_pista).append((url, texto))
    # primero «Official website / More information» (describen la convocatoria) y después «Apply»
    con_pista.sort(key=lambda e: not _PISTA_INFO.search(e[1]))
    externos = con_pista or [e for e in sin_pista if D.institucional(e[0])][:2]
    if len(externos) > 1 and len({_host(u) for u, _ in externos}) == 1:
        externos = externos[:1]  # varios enlaces al mismo sitio: basta con el que describe la convocatoria
    return externos[:maximo], internos[:maximo]


def nombre_del_sitio(html):
    sopa = BeautifulSoup((html or "")[:60000], "html.parser")
    for attrs in ({"property": "og:site_name"}, {"name": "application-name"}):
        m = sopa.find("meta", attrs=attrs)
        if m and m.get("content", "").strip():
            return m["content"].strip()[:120]
    t = sopa.title.get_text(" ", strip=True) if sopa.title else ""
    partes = [p.strip() for p in re.split(r"\s[|–—-]\s", t) if p.strip()]
    return partes[-1][:120] if len(partes) > 1 else ""


def fuente_para(url, fuentes):
    """La fuente configurada a la que pertenece el enlace, o una provisional para el sitio descubierto."""
    f = next((f for f in fuentes if f.dominio and extraer.es_del_dominio(url, f.dominio)), None)
    if f:
        return f
    h = _host(url)
    return Fuente(id="RAD-" + h, activa=True, tipo=TIPO_DESCUBIERTA, nombre=h, pais="", dominio="https://" + h, url_becas=url,
                  oficial="Oficial" if _SITIO_OFICIAL.search(h) else "No Oficial", idioma="", requiere_navegador=False,
                  fila=0)


# --- portal de la Unión Europea -------------------------------------------------------
UE_API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA"
UE_TEMA = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
UE_TEXTOS = ("Colombia", '"Latin America"', '"third countries"', '"international cooperation"', '"developing countries"')
UE_CONSULTA = {"bool": {"must": [{"terms": {"type": ["1", "2", "8"]}},              # subvenciones y convocatorias
                                 {"terms": {"status": ["31094501", "31094502"]}}]}}  # por abrir y abiertas
_ESTADOS_UE = {"31094501": "Por abrir (forthcoming)", "31094502": "Abierta (open for submission)"}


def _primero(v):
    return v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else "")


def _fecha_iso(v):
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except ValueError:
        return None


def _consultar_ue(texto, por_pagina, prueba=None):
    if prueba:
        ruta = Path(prueba) / "ue_api.json"
        return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {"results": []}
    import requests
    blob = lambda v: ("blob", json.dumps(v), "application/json")  # noqa: E731
    r = requests.post(f"{UE_API}&text={quote(texto)}&pageSize={por_pagina}&pageNumber=1",
                      files={"query": blob(UE_CONSULTA), "languages": blob(["en"]),
                             "sort": blob({"order": "ASC", "field": "deadlineDate"})},
                      headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    return r.json()


def portal_ue(maximo=30, hoy=None, prueba=None, textos=UE_TEXTOS):
    """Convocatorias abiertas o por abrir del portal de la UE que mencionan a Colombia o a terceros países.

    Devuelve ([(url, título, html armado con lo que trae el portal)], nota). Las páginas del portal se arman con
    JavaScript y no se pueden leer como las demás: por eso se usa el texto que entrega su búsqueda."""
    vistos, salida, notas = set(), [], []
    for texto in textos:
        try:
            datos = _consultar_ue(texto, 50, prueba)
        except Exception as e:  # noqa: BLE001 - si el portal no responde, se sigue con lo demás
            notas.append(f"el portal de la UE no respondió ({str(e)[:80]})")
            break
        for res in datos.get("results", []):
            m = res.get("metadata") or {}
            ident = _primero(m.get("identifier")) or _primero(m.get("callIdentifier"))
            titulo = _primero(m.get("title")) or res.get("summary") or ident
            if not ident or ident in vistos:
                continue
            cierre = _fecha_iso(_primero(m.get("deadlineDate")))
            if hoy and cierre and cierre < hoy:
                continue
            vistos.add(ident)
            url = _primero(m.get("url")) or res.get("url") or UE_TEMA + ident
            if not str(url).startswith("http"):
                url = UE_TEMA + ident
            salida.append((url, titulo, _html_ue(m, titulo, ident, cierre)))
            if len(salida) >= maximo:
                return salida, "; ".join(notas)
    return salida, "; ".join(notas)


def _html_ue(m, titulo, ident, cierre):
    e = _html.escape
    apertura = _fecha_iso(_primero(m.get("startDate")))
    estado = _ESTADOS_UE.get(str(_primero(m.get("status"))), "")
    partes = [f"<h1>{e(titulo)}</h1>",
              f"<p>Funding and tenders opportunity of the European Commission (European Union). Topic: {e(ident)}.</p>"]
    if _primero(m.get("callTitle")) or _primero(m.get("callIdentifier")):
        partes.append(f"<p>Call: {e(_primero(m.get('callTitle')))} ({e(_primero(m.get('callIdentifier')))}).</p>")
    if _primero(m.get("typesOfAction")):
        partes.append(f"<p>Type of action: {e(_primero(m.get('typesOfAction')))}.</p>")
    if estado:
        partes.append(f"<p>Status: {e(estado)}.</p>")
    if apertura:
        partes.append(f"<p>Opening date: {apertura.isoformat()}.</p>")
    if cierre:
        partes.append(f"<p>Deadline: {cierre.isoformat()}.</p>")
    desc = _primero(m.get("descriptionByte")) or _primero(m.get("destinationDescription"))
    if desc:
        partes.append(f"<div>{desc[:20000]}</div>")
    partes.append("<p>Eligibility of non-EU countries: see the call conditions and the General Annexes of the work "
                  "programme on the Funding &amp; Tenders Portal.</p>")
    return f"<html lang=\"en\"><head><title>{e(titulo)}</title></head><body>{''.join(partes)}</body></html>"
