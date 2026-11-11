"""Encuentra páginas de convocatorias (becas, subvenciones, cooperación técnica y premios) en un sitio oficial y saca sus datos."""
import re
import unicodedata
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from . import texto as tx


def dominio_base(url):
    netloc = urlparse(url).netloc.lower().split(":")[0]
    return netloc[4:] if netloc.startswith("www.") else netloc


def es_del_dominio(url, dominio_oficial):
    """True si la URL pertenece al dominio oficial o a uno de sus subdominios."""
    base = dominio_base(dominio_oficial)
    host = dominio_base(url)
    return bool(base) and (host == base or host.endswith("." + base))


def _sopa(html):
    return BeautifulSoup(html, "html.parser")


def _texto_visible(sopa):
    for t in sopa(["script", "style", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", sopa.get_text(" ")).strip()


def _enlaces(html, url_base):
    sopa = _sopa(html)
    vistos = set()
    for a in sopa.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urldefrag(urljoin(url_base, href))[0]
        if url in vistos:
            continue
        vistos.add(url)
        texto_a = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        yield url, texto_a


def _puntaje_enlace(url, texto_a, cfg, terminos=None):
    terminos = terminos or cfg.palabras_beca
    ruta = tx.normalizar(urlparse(url).path.replace("-", " ").replace("_", " ").replace("/", " "))
    t = tx.normalizar(texto_a)
    if tx.alguno(t + " " + ruta, cfg.palabras_exclusion):
        return 0
    puntos = 0
    if tx.alguno(ruta, terminos):
        puntos += 2
    if tx.alguno(t, terminos):
        puntos += 1
    if puntos and tx.alguno(t + " " + ruta, ["international", "internacional", "internationaux", "international students", "latin america"]):
        puntos += 1
    return puntos


def descubrir_paginas(fuente, lector, cfg):
    """Devuelve (lista de URLs de páginas de convocatorias, nota)."""
    if fuente.url_becas:
        urls = [u.strip() for u in fuente.url_becas.split(";") if u.strip()]
        return urls, "URL de convocatorias configurada"
    terminos = cfg.palabras_de(fuente.modalidades)
    if not fuente.dominio:
        return [], "La fuente no tiene dominio oficial"
    inicio = lector.leer(fuente.dominio, forzar_navegador=fuente.requiere_navegador)
    if not inicio.ok:
        return [], f"El sitio no respondió ({inicio.estado}) {inicio.error}".strip()
    puntajes = {}
    for url, texto_a in _enlaces(inicio.html, inicio.url):
        if not es_del_dominio(url, fuente.dominio):
            continue
        p = _puntaje_enlace(url, texto_a, cfg, terminos)
        if p:
            puntajes[url] = max(p, puntajes.get(url, 0))
    # sitemap: segunda vía para encontrar la página de becas
    sitemap = lector.leer(fuente.dominio + "/sitemap.xml")
    if sitemap.ok:
        for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sitemap.html)[:3000]:
            if es_del_dominio(loc, fuente.dominio) and not loc.endswith(".xml"):
                p = _puntaje_enlace(loc, "", cfg, terminos)
                if p:
                    puntajes[loc] = max(p, puntajes.get(loc, 0))
    maximo = int(cfg.p("Máximo de páginas de convocatorias por fuente", cfg.p("Máximo de páginas de becas por fuente", 4)))
    mejores = sorted(puntajes, key=lambda u: (-puntajes[u], len(u)))[:maximo]
    nota = "Encontradas desde la página de inicio" if mejores else "No se encontró página de convocatorias en el inicio ni en el sitemap"
    return mejores, nota


def candidatas(html, url_pagina, fuente, cfg):
    """Enlaces a convocatorias individuales dentro de una página de listado."""
    maximo = int(cfg.p("Máximo de convocatorias por página", 25))
    terminos = cfg.palabras_de(fuente.modalidades)
    salida = []
    for url, texto_a in _enlaces(html, url_pagina):
        if url.rstrip("/") == url_pagina.rstrip("/") or not es_del_dominio(url, fuente.dominio or url_pagina):
            continue
        if len(texto_a) < 6:
            continue
        if _puntaje_enlace(url, texto_a, cfg, terminos) >= 2:
            salida.append((url, texto_a))
    return salida[:maximo]


def _titulo(sopa):
    for sel in [("meta", {"property": "og:title"}), ("meta", {"name": "twitter:title"})]:
        m = sopa.find(*sel)
        if m and m.get("content"):
            return m["content"].strip()
    h1 = sopa.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    return sopa.title.get_text(strip=True) if sopa.title else ""


def _limpiar_titulo(t):
    return re.split(r"\s[|·–—]\s", t)[0].strip() if t else t


def _descripcion(sopa):
    for sel in [("meta", {"name": "description"}), ("meta", {"property": "og:description"})]:
        m = sopa.find(*sel)
        if m and m.get("content") and len(m["content"]) > 60:
            return m["content"].strip()
    parrafos = [p.get_text(" ", strip=True) for p in sopa.find_all("p")]
    largos = [p for p in parrafos if len(p) > 80][:2] or [p for p in parrafos if len(p) > 30][:3]
    return " ".join(largos)[:900]


def nombre_del_sitio(html):
    """Nombre con el que se identifica un sitio (og:site_name o <title>), para confirmar que es del oferente."""
    sopa = _sopa(html)
    m = sopa.find("meta", {"property": "og:site_name"})
    partes = [m["content"]] if m and m.get("content") else []
    if sopa.title and sopa.title.get_text(strip=True):
        partes.append(sopa.title.get_text(" ", strip=True))
    return " | ".join(partes)[:200]


def analizar_beca(resp, fuente, cfg, hoy, texto_enlace=""):
    """Saca los campos de la página de una convocatoria. Devuelve un dict."""
    from .reglas import detectar_modalidad
    sopa = _sopa(resp.html)
    lang = (sopa.html.get("lang") if sopa.html else "") or ""
    titulo = _limpiar_titulo(_titulo(sopa))
    descripcion = _descripcion(sopa)
    plano = unicodedata.normalize("NFC", _texto_visible(sopa))
    norm = tx.normalizar(plano)
    minus = plano.lower()
    # las evidencias se toman del texto original si las posiciones coinciden
    original = plano if len(plano) == len(norm) == len(minus) else norm

    cierre, tramo, vencida = tx.fecha_cierre(norm, hoy)
    evid_cierre = tx.frase(original, *tramo) if tramo else ""
    permanente = tx.es_permanente(norm) and not cierre and not vencida

    lista_montos = tx.montos(minus)
    monto_usd = max((v for v, m, _ in lista_montos if m == "USD"), default=None)
    frases_monto = list(dict.fromkeys(tx.frase(original, *t) for _, _, t in sorted(lista_montos, key=lambda x: -x[0])[:2]))
    cobertura = tx.alguno(norm, tx.PALABRAS_COBERTURA)

    idiomas = []
    codigo = lang.split("-")[0].lower()
    if codigo in tx.IDIOMAS_HTML:
        idiomas.append(tx.IDIOMAS_HTML[codigo])
    for idioma, frases in tx.IDIOMAS_MENCION.items():
        if tx.alguno(norm, frases) and idioma not in idiomas:
            idiomas.append(idioma)

    modalidad, motivo_modalidad = detectar_modalidad(titulo or texto_enlace, resp.url, norm, cfg, fuente.modalidades)
    es_beca = modalidad == "Beca"
    niveles = [n for n, frases in tx.NIVELES.items() if tx.alguno(norm, frases)] if es_beca else []
    publico = [p for p, frases in tx.PUBLICO.items() if tx.alguno(norm, frases)]
    if es_beca:
        publico = ["Ciudadanos"] + [p for p in publico if p != "Ciudadanos"]
    publico = publico or ["No se especifica el público"]
    poblaciones = [p for p, frases in tx.POBLACIONES.items() if tx.alguno(norm, frases)]
    temas = (["Educación"] if es_beca else []) + [t for t, frases in cfg.tematicas if tx.alguno(norm, frases)]

    contacto = [c for c in tx.correos(plano)]
    mailtos = [a["href"][7:].split("?")[0].lower() for a in sopa.find_all("a", href=True) if a["href"].lower().startswith("mailto:")]
    correo = (mailtos + contacto + ["Sin Email"])[0]

    return {
        "modalidad": modalidad,
        "motivo_modalidad": motivo_modalidad,
        "titulo": titulo,
        "descripcion": descripcion,
        "texto_norm": norm,
        "texto_pagina": plano[:15000],
        "cierre": cierre,
        "evidencia_cierre": evid_cierre,
        "vencida": vencida,
        "permanente": permanente,
        "monto_usd": monto_usd,
        "frases_monto": frases_monto,
        "cobertura": cobertura,
        "idiomas": idiomas or ["No especifica"],
        "niveles": niveles,
        "publico": publico,
        "poblaciones": poblaciones,
        "temas": temas,
        "correo": correo,
        "enlaces_icetex": [u for u, _ in _enlaces(resp.html, resp.url) if "icetex.gov.co" in u],
    }
