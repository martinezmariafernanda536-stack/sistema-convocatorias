"""Reglas de decisión: modalidad, elegibilidad de colombianos, ICETEX, duplicados y alineación."""
import re

from bs4 import BeautifulSoup

from . import texto as tx

try:
    from rapidfuzz import fuzz

    def similitud(a, b):
        a, b = tx.normalizar(a), tx.normalizar(b)
        # token_set da 100 si un nombre está contenido en otro; solo se usa si
        # ambos nombres son largos, para no confundir títulos genéricos.
        if min(len(a.split()), len(b.split())) >= 4:
            return fuzz.token_set_ratio(a, b)
        return fuzz.token_sort_ratio(a, b)
except ImportError:  # sin rapidfuzz se usa la librería estándar
    from difflib import SequenceMatcher

    def similitud(a, b):
        return 100 * SequenceMatcher(None, tx.normalizar(a), tx.normalizar(b)).ratio()


# --- ¿Beca, subvención, cooperación técnica o premio? ------------------------
def detectar_modalidad(titulo, url, texto_norm, cfg, permitidas):
    """Elige la modalidad con más evidencia entre las que se buscan en la fuente.

    Cuenta las palabras de cada modalidad: en el título valen 3, en la dirección 2 y en el texto 1 (máximo 3).
    Devuelve (modalidad, motivo)."""
    from urllib.parse import urlparse
    t = tx.normalizar(titulo)
    ruta = tx.normalizar(urlparse(url).path.replace("-", " ").replace("_", " ").replace("/", " "))
    puntos, evidencia = {}, {}
    for m in permitidas:
        terminos = cfg.palabras_modalidad.get(m, [])
        en_t, en_r, en_x = tx.alguno(t, terminos), tx.alguno(ruta, terminos), tx.alguno(texto_norm, terminos)
        puntos[m] = 3 * bool(en_t) + 2 * bool(en_r) + min(len(en_x), 3)
        evidencia[m] = (en_t or en_r or en_x or [""])[0]
    if not puntos or max(puntos.values()) == 0:
        return permitidas[0] if permitidas else "Beca", "Sin palabras de modalidad: se asume la primera de la fuente"
    mejor = max(permitidas, key=lambda m: (puntos[m], -permitidas.index(m)))
    return mejor, f"«{evidencia[mejor]}» ({puntos[mejor]} puntos)"


# --- ¿Pueden postularse colombianos? ----------------------------------------
def elegibilidad(texto_norm, cfg):
    """Devuelve (resultado, puntaje, motivo).

    Puntos de cada regla (hoja Elegibilidad):
      3 o más   inclusión fuerte: nombra a Colombia o a América Latina
      1 o 2     apertura general: extranjeros, estudiantes internacionales, todos los países, países en desarrollo (CAD)
      -1 a -9   restricción a otros (solo ciudadanos de la UE, solo africanos…): descarta SOLO si la página no
                nombra a Colombia ni a América Latina
      -10 o menos  exclusión explícita de Colombia o de la región: descarta siempre
    No hace falta que la página nombre a Colombia: basta con que esté abierta a extranjeros sin excluirla.
    """
    positivos, fuertes, restriccion, exclusion, motivos = 0, False, False, False, []
    for regla, terminos, puntos in cfg.reglas_elegibilidad:
        hallados = tx.alguno(texto_norm, terminos)
        if not hallados:
            continue
        motivos.append(f"{regla}: «{hallados[0]}»")
        if puntos <= -10:
            exclusion = True
        elif puntos < 0:
            restriccion = True
        else:
            positivos += puntos
            fuertes = fuertes or puntos >= 3
    if exclusion:
        return "No elegible", positivos, "; ".join(motivos)
    if restriccion and not fuertes:
        return "No elegible", positivos, "; ".join(motivos)
    resultado = "Elegible" if positivos >= 2 else "Probable" if positivos == 1 else "Revisar"
    if restriccion:
        motivos.append("la restricción no aplica porque la página incluye a Colombia o a la región")
    return resultado, positivos, "; ".join(motivos) or "La página no dice quién puede postularse (no excluye a Colombia)"


def ambito(texto_norm):
    regional = tx.alguno(texto_norm, ["latin america", "america latina", "latinoamerica", "lateinamerika", "amerique latine"])
    global_ = tx.alguno(texto_norm, ["all nationalities", "all countries", "international students", "todas las nacionalidades",
                                     "foreign students", "extranjeros", "worldwide", "any country", "todo el mundo"])
    return "Regional" if regional and not global_ else "Global"


# --- ICETEX -----------------------------------------------------------------
class IndiceIcetex:
    """Lista de becas que ya ofrece ICETEX, para excluirlas."""

    def __init__(self, cfg, lector):
        self.umbral = float(cfg.p("Umbral de similitud ICETEX (0-100)", 85))
        self.palabras = cfg.icetex_palabras or ["icetex"]
        self.nombres = [(n, u) for n, u in cfg.icetex_nombres if n or u]
        self.notas = []
        for url in cfg.icetex_paginas:
            r = lector.leer(url)
            if not r.ok:
                self.notas.append(f"No se pudo leer la página de ICETEX {url} ({r.estado})")
                continue
            sopa = BeautifulSoup(r.html, "html.parser")
            for a in sopa.find_all("a", href=True):
                t = re.sub(r"\s+", " ", a.get_text(" ")).strip()
                if len(t) > 12:
                    self.nombres.append((t, a["href"]))
        self.urls = {u.rstrip("/").lower() for _, u in self.nombres if u}

    def revisar(self, titulo, url, datos):
        """Devuelve (está_en_icetex: bool, motivo)."""
        if url.rstrip("/").lower() in self.urls:
            return True, "La URL está en la lista de ICETEX"
        mejor, nombre_mejor = 0, ""
        for nombre, _ in self.nombres:
            if nombre:
                s = similitud(titulo, nombre)
                if s > mejor:
                    mejor, nombre_mejor = s, nombre
        if mejor >= self.umbral:
            return True, f"Nombre parecido a «{nombre_mejor}» de ICETEX ({mejor:.0f}%)"
        if datos.get("enlaces_icetex"):
            return True, "La página enlaza a icetex.gov.co"
        hallados = tx.alguno(datos["texto_norm"], self.palabras)
        if hallados:
            return True, f"La página menciona «{hallados[0]}»"
        return False, ""


# --- duplicados en Airtable --------------------------------------------------
class IndiceAirtable:
    def __init__(self, df, umbral=90):
        self.umbral = float(umbral)
        self.nombres = df["Nombre de la Convocatoria"].dropna().astype(str).tolist() if df is not None else []
        self.urls = set()
        if df is not None:
            for c in ("Cómo aplicar", "Link de la Fuente Oferente"):
                if c in df:
                    self.urls |= {str(u).rstrip("/").lower() for u in df[c].dropna()}

    def revisar(self, titulo, url):
        if url.rstrip("/").lower() in self.urls:
            return "Ya está en la base (misma URL)"
        mejor, nombre = 0, ""
        for n in self.nombres:
            s = similitud(titulo, n)
            if s > mejor:
                mejor, nombre = s, n
        if mejor >= self.umbral:
            return f"Posible duplicado de «{nombre}» ({mejor:.0f}%)"
        return ""


# --- alineación sugerida -----------------------------------------------------
def alineacion(temas, cfg, modalidad="Beca"):
    # El valor por defecto (Educación) solo aplica a becas
    valores = dict(cfg.alineacion.get("(Por defecto)", {})) if modalidad == "Beca" else {}
    for tema in temas:
        if tema in cfg.alineacion:
            valores.update(cfg.alineacion[tema])
            break  # la primera temática específica manda
    return valores
