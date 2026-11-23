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


_IDIOMAS = {"english", "espanol", "español", "francais", "français", "portugues", "português", "deutsch", "italiano",
            "nederlands", "русский", "中文", "日本語", "한국어", "العربية", "en", "es", "fr", "pt", "de", "it", "eng", "esp", "fra",
            "en espanol", "en español", "version en espanol", "versión en español", "english version", "version francaise",
            "version française", "em portugues", "em português", "auf deutsch", "in english"}


def es_enlace_de_idioma(texto_a):
    """«Français», «English», «Español»: el selector de idioma de la página, no una convocatoria."""
    t = re.sub(r"\s+", " ", (texto_a or "").strip().lower())
    return t in _IDIOMAS or bool(re.fullmatch(r"(?:[a-z]{2}\s*\|\s*)+[a-z]{2}", t))


def version_en_espanol(html, url):
    """Si la página declara su versión en español (<link rel="alternate" hreflang="es">), devuelve ese enlace."""
    from urllib.parse import urljoin
    for m in re.finditer(r"<link[^>]+>", html[:60000], re.I):
        etiqueta = m.group(0)
        if re.search(r"rel=[\"']?alternate", etiqueta, re.I) and re.search(r"hreflang=[\"']?es(?:[-_][a-z]{2})?[\"'\s>]", etiqueta, re.I):
            h = re.search(r"href=[\"']([^\"']+)", etiqueta, re.I)
            if h:
                destino = urljoin(url, h.group(1))
                return "" if destino.split("#")[0].rstrip("/") == url.split("#")[0].rstrip("/") else destino
    return ""


_GENERICAS = set("""call calls proposal proposals grant grants funding fund funds opportunity opportunities open now apply
application applications scholarship scholarships fellowship fellowships program programs programme programmes award awards
prize prizes convocatoria convocatorias beca becas programa programas premio premios subvencion subvenciones ayuda ayudas
financiacion financiamiento bourse bourses appel appels projets projet edital editais bolsa bolsas chamada chamadas foerderung
stipendium stipendien the for and of de la el los las le les des du en para por y et a an to in on with new nueva nuevo
nouveau novo year years ronda round espanol francais portugues english deutsch national nacional international internacional
information informacion more mas sobre about our nuestras nuestros nos home inicio page pagina news noticias""".split())


def nucleo(titulo):
    """Palabras propias del nombre (sin las genéricas ni las de idioma): «Le programme de bourses France Excellence
    Eiffel» y «France Excellence Eiffel scholarship program» tienen el mismo núcleo."""
    t = unicodedata.normalize("NFKD", (titulo or "").lower()).encode("ascii", "ignore").decode()
    return frozenset(w for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 3 and w not in _GENERICAS and not w.isdigit())


def candidatas(html, url_pagina, fuente, cfg):
    """Enlaces a convocatorias individuales dentro de una página de listado."""
    maximo = int(cfg.p("Máximo de convocatorias por página", 25))
    terminos = cfg.palabras_de(fuente.modalidades)
    salida = []
    for url, texto_a in _enlaces(html, url_pagina):
        if url.rstrip("/") == url_pagina.rstrip("/") or not es_del_dominio(url, fuente.dominio or url_pagina):
            continue
        if len(texto_a) < 6 or es_enlace_de_idioma(texto_a):
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


# --- páginas que reúnen varias convocatorias -----------------------------------
# Muchas páginas («Becas», «Convocatorias abiertas») presentan cada convocatoria en un desplegable, una pestaña o una
# sección con su propio título, sin una página aparte. Si se leen enteras salen como una sola convocatoria «general»,
# sin fechas ni requisitos de cada una. Aquí se separan para analizarlas una por una.
_GENERICOS = [
    "requisito", "requirement", "beneficio", "benefit", "como aplicar", "como postular", "how to apply", "documento", "document",
    "pregunta", "faq", "preguntas frecuentes", "fecha", "calendario", "deadline", "important dates", "contacto", "contact",
    "proceso", "process", "criterio", "criteria", "eligib", "about", "acerca", "sobre ", "descripcion", "objetivo", "cobertura",
    "coverage", "seleccion", "selection", "terminos", "terms", "reglamento", "politica", "aviso", "noticias", "news",
    "tambien te puede", "te puede interesar", "related", "conoce mas", "mas informacion", "more information",
]
_CONTEXTO = ["fecha", "fechas", "calendario", "plazo", "plazos", "periodo", "periodos", "convocatoria", "deadline", "deadlines",
             "important dates", "timeline", "proceso", "how to apply", "como aplicar", "como solicitar"]


def _limpiar_seccion(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.sub(r"^(?:ir a|ver|conoce|conocer|mas sobre|más sobre|leer mas|leer más|go to|see|read more about)\s+", "", t, flags=re.I)
    return re.sub(r"^\d{1,2}[.)-]\s*", "", t)  # «4. Beca de apoyo» → «Beca de apoyo»


def _slug(t):
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]


def _es_generico(titulo_norm):
    return any(titulo_norm.startswith(g) or f" {g}" in titulo_norm[:25] for g in _GENERICOS)


def _hermanos_hasta(encabezado):
    """HTML de lo que sigue a un encabezado hasta el próximo encabezado del mismo nivel o superior."""
    nivel = int(encabezado.name[1]) if re.fullmatch(r"h\d", encabezado.name or "") else 6
    partes = []
    for h in encabezado.find_next_siblings():
        if re.fullmatch(r"h\d", h.name or "") and int(h.name[1]) <= nivel:
            break
        if h.find(re.compile(rf"^h[1-{nivel}]$")):
            break
        partes.append(str(h))
    return "".join(partes)


def _bloque_propio(h, encabezados, terminos):
    """El elemento más grande que contiene el encabezado `h` y ningún otro encabezado de otra convocatoria."""
    def nombre(e):
        return tx.normalizar(_limpiar_seccion(e.get_text(" ")))
    propio = nombre(h)
    otros = [e for e in encabezados if e is not h and nombre(e) != propio and tx.alguno(nombre(e), terminos)
             and not _es_generico(nombre(e))]
    ancestros = {id(e): {id(a) for a in e.parents} for e in otros}
    bloque, actual = None, h
    while actual.parent is not None and actual.parent.name not in ("body", "html", "[document]"):
        padre = actual.parent
        if any(id(padre) in a for a in ancestros.values()):
            break
        bloque = actual = padre
    return bloque


def secciones(html, url, terminos, minimo=2):
    """Devuelve [(título, ancla, html_de_la_sección)] si la página reúne varias convocatorias; [] si es una sola."""
    sopa = _sopa(html)
    for t in sopa(["script", "style", "noscript", "svg", "nav", "header", "footer"]):
        t.decompose()
    vistas, anclas, salida = set(), set(), []

    def agregar(titulo, ancla, contenido_html):
        titulo = _limpiar_seccion(titulo)
        tn = tx.normalizar(titulo)
        texto = re.sub(r"\s+", " ", _sopa(contenido_html).get_text(" ")).strip()
        if ancla and ancla in anclas:  # el mismo panel enlazado desde un índice y desde su botón
            return
        if not (6 <= len(titulo) <= 160) or len(texto) < 120 or tn in vistas or _es_generico(tn):
            return
        if not tx.alguno(tn, terminos):  # el título debe nombrar una convocatoria (beca, grant, premio…)
            return
        vistas.add(tn)
        if ancla:
            anclas.add(ancla)
        salida.append((titulo, ancla or _slug(titulo), contenido_html))

    # 1. desplegables y pestañas: un botón o enlace que abre un panel con id
    for disparador in sopa.find_all(lambda e: e.has_attr("aria-controls") or e.has_attr("data-bs-target")
                                    or e.has_attr("data-target") or (e.name == "a" and str(e.get("href", "")).startswith("#")
                                                                     and len(e.get("href", "")) > 1)):
        destino = (disparador.get("aria-controls") or disparador.get("data-bs-target") or disparador.get("data-target")
                   or disparador.get("href") or "")
        objetivo = destino.strip().lstrip("#").split()[0] if destino.strip().lstrip("#") else ""
        panel = sopa.find(id=objetivo) if objetivo else None
        if panel is not None and panel is not disparador and disparador not in panel.descendants:
            agregar(disparador.get_text(" "), objetivo, str(panel))
    # 2. <details><summary>
    for d in sopa.find_all("details"):
        s = d.find("summary")
        if s:
            titulo = s.get_text(" ")
            s.extract()
            agregar(titulo, d.get("id"), str(d))
    # 3. secciones con encabezado (h2–h4) seguidas de su contenido
    if len(salida) < minimo:
        encabezados = sopa.find_all(["h2", "h3", "h4"])
        mejores, orden = {}, []  # el mismo título puede repetirse (menú de pestañas, versión móvil): se usa el más completo
        for h in encabezados:
            ancla = h.get("id") or (h.parent.get("id") if h.parent is not None and h.parent.name in ("section", "div", "article") else None)
            propio = _hermanos_hasta(h)
            bloque = _bloque_propio(h, encabezados, terminos)
            # en páginas con pestañas internas («Requisitos», «Procesos y fechas»…) lo que sigue al título es solo la
            # presentación: el bloque que lo contiene trae todas las pestañas, también las ocultas
            if bloque is not None and len(bloque.get_text(" ")) > len(_sopa(propio).get_text(" ")) + 80:
                propio = str(bloque)
            clave = tx.normalizar(_limpiar_seccion(h.get_text(" ")))
            largo = len(_sopa(propio).get_text(" "))
            if clave not in mejores:
                orden.append(clave)
                mejores[clave] = [h.get_text(" "), ancla, propio, largo]
            else:
                m = mejores[clave]
                m[1] = m[1] or ancla
                if largo > m[3]:
                    m[2], m[3] = propio, largo
        for clave in orden:
            titulo, ancla, propio, _ = mejores[clave]
            agregar(titulo, ancla, propio)
    if len(salida) < minimo:
        return []
    return salida


def contexto_general(html, terminos):
    """Texto de las secciones generales de la página (fechas, calendario, cómo aplicar) que vale para todas."""
    sopa = _sopa(html)
    for t in sopa(["script", "style", "noscript", "svg", "nav", "header", "footer"]):
        t.decompose()
    partes = []
    for h in sopa.find_all(["h2", "h3", "h4", "summary", "button"]):
        tn = tx.normalizar(h.get_text(" "))
        if tx.alguno(tn, _CONTEXTO) and not tx.alguno(tn, terminos):
            cuerpo = _hermanos_hasta(h) if re.fullmatch(r"h\d", h.name) else str(h.parent)
            partes.append(_limpiar_seccion(h.get_text(" ")) + ": " + re.sub(r"\s+", " ", _sopa(cuerpo).get_text(" ")).strip())
    return " ".join(partes)[:2500]


def html_de_seccion(titulo, contenido_html, contexto="", lang=""):
    """Página sintética con una sola convocatoria, para analizarla igual que una página propia."""
    from html import escape
    extra = f"<div><h2>Información general de la página</h2><p>{escape(contexto)}</p></div>" if contexto else ""
    return (f"<html lang='{escape(lang)}'><head><title>{escape(titulo)}</title></head>"
            f"<body><h1>{escape(titulo)}</h1>{contenido_html}{extra}</body></html>")
