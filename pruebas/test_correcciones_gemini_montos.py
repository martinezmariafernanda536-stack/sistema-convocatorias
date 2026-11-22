"""Regresión: montos con la moneda al final ('no such group') y modelo de Gemini retirado (404)."""
import json
import pytest
from motor import externo, texto


def test_monto_con_moneda_al_final_no_falla():
    m = texto.montos("apoyo de 5.000 euros, hasta 12,000 usd y 800 chf al mes")
    assert (5000, "EUR") in [(v, c) for v, c, _ in m]
    assert (12000, "USD") in [(v, c) for v, c, _ in m]


MSG = ("This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use "
       "models/gemini-3.8-flash for the latest features and improvements. We recommend you to use the Interactions API "
       "(https://aistudio.google.com/docs/get-started).")


def test_lee_el_modelo_sugerido_por_google():
    assert externo._modelo_sugerido(MSG, "x") == "gemini-3.8-flash"


class Resp:
    def __init__(self, code, data):
        self.status_code, self._d, self.text = code, data, json.dumps(data)

    def json(self):
        return self._d


@pytest.fixture(autouse=True)
def limpio(monkeypatch):
    monkeypatch.delenv("MAPEO_GEMINI_PRUEBA", raising=False)
    monkeypatch.delenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", raising=False)
    externo._REEMPLAZO.clear()
    externo.reiniciar_corrida()
    monkeypatch.setitem(externo._RITMO, "pausa", 0)
    monkeypatch.setattr(externo.time if hasattr(externo, "time") else __import__("time"), "sleep", lambda s: None)
    yield
    externo._REEMPLAZO.clear()
    externo.reiniciar_corrida()


def test_reintenta_con_el_modelo_nuevo(monkeypatch):
    usados = []
    msg = MSG.replace("gemini-2.5-flash", "gemini-9-viejo").replace("gemini-3.8-flash", "gemini-9-nuevo")

    def post(url, **kw):
        usados.append(url.split("/models/")[1].split(":")[0])
        if "viejo" in url:
            return Resp(404, {"error": {"message": msg}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    monkeypatch.setattr(externo.requests, "post", post)
    externo.llamar("hola", "clave", "gemini-9-viejo", buscar_en_google=False)
    externo.llamar("hola", "clave", "gemini-9-viejo", buscar_en_google=False)
    assert usados == ["gemini-9-viejo", "gemini-9-nuevo", "gemini-9-nuevo"]  # el segundo ya va directo


def test_modelos_de_cupo_bajo_van_al_final():
    assert externo.cadena("gemini-2.5-flash")[0] == "gemini-3.5-flash-lite"
    assert externo.cadena("gemini-3.8-flash")[-1] == "gemini-3.8-flash"
    assert externo.cadena("gemini-3.1-flash-lite")[0] == "gemini-3.1-flash-lite"


def test_saturado_reintenta_y_cambia_de_modelo(monkeypatch):
    usados = []

    def post(url, **kw):
        m = url.split("/models/")[1].split(":")[0]
        usados.append(m)
        if m == "gemini-3.5-flash-lite":
            return Resp(503, {"error": {"message": "This model is currently experiencing high demand."}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    monkeypatch.setattr(externo.requests, "post", post)
    externo.llamar("hola", "clave", "gemini-3.5-flash-lite", buscar_en_google=False)
    assert usados == ["gemini-3.5-flash-lite"] * 3 + ["gemini-3.1-flash-lite"]


def test_cupo_diario_agotado_sigue_con_otro_y_al_final_suspende(monkeypatch):
    usados = []
    diario = {"error": {"message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20. "
                                   "Generate content requests per day limit exceeded on Free Tier."}}

    def post(url, **kw):
        usados.append(url.split("/models/")[1].split(":")[0])
        return Resp(429, diario)
    monkeypatch.setattr(externo.requests, "post", post)
    with pytest.raises(externo.ErrorGemini):
        externo.llamar("hola", "clave", "gemini-3.5-flash-lite", buscar_en_google=False)
    assert usados == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]  # una vez cada uno
    assert "cupo gratuito de hoy" in externo.SUSPENDIDO["motivo"]


def test_lo_mismo_en_otro_idioma_y_listados():
    from motor import extraer
    assert extraer.nucleo("Le programme de bourses France Excellence Eiffel") == extraer.nucleo("France Excellence Eiffel scholarship program") \
        == extraer.nucleo("El programa de becas France Excellence Eiffel")
    assert extraer.nucleo("Call for Proposals") == frozenset() and extraer.nucleo("Grants Calls 2027") == frozenset()
    assert extraer.es_enlace_de_idioma("Français") and extraer.es_enlace_de_idioma("EN | ES") and not extraer.es_enlace_de_idioma("Eiffel")
    html = '<html><head><link rel="alternate" hreflang="es" href="/es/becas/eiffel"></head></html>'
    assert extraer.version_en_espanol(html, "https://www.campusfrance.org/en/eiffel") == "https://www.campusfrance.org/es/becas/eiffel"


def test_clave_invalida_no_se_repite_en_cada_convocatoria(monkeypatch):
    llamadas = []

    def post(url, **kw):
        llamadas.append(url)
        return Resp(403, {"error": {"message": "API key not valid"}})
    monkeypatch.setattr(externo.requests, "post", post)
    for _ in range(5):
        with pytest.raises(externo.ErrorGemini):
            externo.llamar("hola", "clave", "gemini-3.8-flash", buscar_en_google=False)
    assert len(llamadas) == 1


def test_alineacion_y_fechas_coherentes():
    """Gemini elige la alineación en los catálogos oficiales; una permanente no conserva una fecha vencida."""
    from datetime import date
    from motor import config as C
    from calidad.reglas import CATALOGOS
    cfg = C.cargar()
    fila = {"Nombre de la Convocatoria": "Democracia y Gobernanza", "Modalidad": "Subvención", "Descripción": "",
            "Objetivos General y Específicos": "", "¿La convocatoria es permanente?": "Si",
            "Fecha Límite de Aplicación": "1/3/2024", "Observaciones a la fecha límite de aplicación": "Applications are reviewed monthly.",
            "Áreas temáticas de interés": "Democracia y Gobernanza", "[Sistema] Evidencia de Gemini en la página": ""}
    c = {"linea_enci": CATALOGOS["Linea Prioritaria ENCI"][0], "metas_pnd": CATALOGOS["Metas PND"][1],
         "cad": "No es un valor del catálogo", "ods": CATALOGOS["ODS"][15]}
    externo.completar(fila, c, CATALOGOS, cfg, "texto", "Subvención", date(2026, 11, 21))
    assert fila["Linea Prioritaria ENCI"] == CATALOGOS["Linea Prioritaria ENCI"][0]
    assert fila["Metas PND"] == CATALOGOS["Metas PND"][1]
    assert not fila.get("Comite de Ayuda al Desarrollo")            # un valor fuera del catálogo no entra
    assert fila["Fecha Límite de Aplicación"] == ""                  # permanente: no conserva la fecha vencida
    assert fila["Observaciones a la fecha límite de aplicación"].startswith("Ver las condiciones")
