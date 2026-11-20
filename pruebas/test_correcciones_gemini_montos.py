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
    yield
    externo._REEMPLAZO.clear()
    externo.reiniciar_corrida()


def test_reintenta_con_el_modelo_nuevo(monkeypatch):
    usados = []

    def post(url, **kw):
        usados.append(url.split("/models/")[1].split(":")[0])
        if "2.5" in url:
            return Resp(404, {"error": {"message": MSG}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    monkeypatch.setattr(externo.requests, "post", post)
    externo.llamar("hola", "clave", "gemini-2.5-flash", buscar_en_google=False)
    externo.llamar("hola", "clave", "gemini-2.5-flash", buscar_en_google=False)
    assert usados == ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.8-flash"]  # el segundo ya va directo


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
