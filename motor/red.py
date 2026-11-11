"""Lectura de páginas web: igual que un navegador, pero sin pantalla.

- Respeta robots.txt (si el parámetro está en Sí).
- Hace una pausa entre solicitudes al mismo sitio.
- Si la página llega casi vacía y está activado, la abre con Playwright.
- En modo prueba lee páginas guardadas en pruebas/paginas (sin internet).
"""
import json
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests


@dataclass
class Respuesta:
    url: str
    estado: int          # código HTTP; 0 = no respondió; -1 = bloqueado por robots.txt
    html: str = ""
    error: str = ""

    @property
    def ok(self):
        return self.estado == 200 and bool(self.html)


class Lector:
    def __init__(self, agente, pausa=3, espera=20, respetar_robots=True, usar_navegador=False, carpeta_prueba=None):
        self.agente = agente
        self.pausa = float(pausa)
        self.espera = float(espera)
        self.respetar_robots = respetar_robots
        self.usar_navegador = usar_navegador
        self.sesion = requests.Session()
        self.sesion.headers.update({"User-Agent": agente, "Accept-Language": "es,en;q=0.8"})
        self._ultimo = {}
        self._robots = {}
        self.mapa_prueba = None
        if carpeta_prueba:
            carpeta = Path(carpeta_prueba)
            self.carpeta_prueba = carpeta
            self.mapa_prueba = json.loads((carpeta / "mapa.json").read_text(encoding="utf-8"))

    # -- robots.txt -------------------------------------------------------
    def _permitido(self, url):
        if not self.respetar_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            r = self._descargar(base + "/robots.txt", revisar_robots=False)
            if r.estado == 200:
                rp.parse(r.html.splitlines())
            else:
                rp.parse([])  # sin robots.txt = permitido
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.agente, url)

    # -- descarga ---------------------------------------------------------
    def _esperar_turno(self, url):
        dominio = urlparse(url).netloc
        transcurrido = time.time() - self._ultimo.get(dominio, 0)
        if self.mapa_prueba is None and transcurrido < self.pausa:
            time.sleep(self.pausa - transcurrido)
        self._ultimo[dominio] = time.time()

    def _descargar(self, url, revisar_robots=True):
        if self.mapa_prueba is not None:
            archivo = self.mapa_prueba.get(url) or self.mapa_prueba.get(url.rstrip("/"))
            if not archivo:
                return Respuesta(url, 404, error="No existe en las páginas de prueba")
            return Respuesta(url, 200, (self.carpeta_prueba / archivo).read_text(encoding="utf-8"))
        if revisar_robots and not self._permitido(url):
            return Respuesta(url, -1, error="robots.txt no permite leer esta página")
        self._esperar_turno(url)
        try:
            r = self.sesion.get(url, timeout=self.espera, allow_redirects=True)
            tipo = r.headers.get("Content-Type", "")
            if "html" not in tipo and "xml" not in tipo and "text" not in tipo:
                return Respuesta(r.url, r.status_code, error=f"No es una página web ({tipo})")
            r.encoding = r.encoding or r.apparent_encoding
            return Respuesta(r.url, r.status_code, r.text)
        except requests.RequestException as e:
            return Respuesta(url, 0, error=str(e)[:200])

    def leer(self, url, forzar_navegador=False):
        r = self._descargar(url)
        poco_texto = r.ok and len(r.html) < 3000
        if (forzar_navegador or (self.usar_navegador and poco_texto)) and r.estado != -1 and self.mapa_prueba is None:
            return self._leer_con_navegador(url) or r
        return r

    def _leer_con_navegador(self, url):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        try:
            with sync_playwright() as pw:
                nav = pw.chromium.launch()
                pagina = nav.new_page(user_agent=self.agente)
                resp = pagina.goto(url, timeout=self.espera * 1000, wait_until="networkidle")
                html = pagina.content()
                estado = resp.status if resp else 200
                final = pagina.url
                nav.close()
                return Respuesta(final, estado, html)
        except Exception as e:  # noqa: BLE001 - cualquier fallo del navegador se reporta
            return Respuesta(url, 0, error=f"Navegador: {str(e)[:150]}")
