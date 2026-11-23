"""Manifiesto del paquete: la huella de cada archivo de código, para detectar si en el servidor quedaron archivos
de paquetes distintos (pasa al subirlos por partes a GitHub).

    python herramientas/manifiesto.py        # se ejecuta al armar el paquete
"""
import hashlib
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA = RAIZ / "manifiesto.json"
CARPETAS = ["", "motor", "calidad", "bandeja", "analitica", "paginas"]


def _huella(ruta):
    # se ignoran los finales de línea, que GitHub o Windows pueden cambiar
    return hashlib.sha1(ruta.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def archivos():
    for c in CARPETAS:
        for r in sorted((RAIZ / c).glob("*.py")):
            yield r.relative_to(RAIZ).as_posix(), r


def generar(version):
    datos = {"version": version, "archivos": {n: _huella(r) for n, r in archivos()}}
    RUTA.write_text(json.dumps(datos, indent=1, ensure_ascii=False), encoding="utf-8")
    return datos


def revisar():
    """(versión del paquete, [archivos distintos o que faltan]). Sin manifiesto: (None, [])."""
    try:
        datos = json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    distintos = []
    for nombre, huella in datos.get("archivos", {}).items():
        r = RAIZ / nombre
        if not r.exists():
            distintos.append(nombre + " (falta)")
        elif _huella(r) != huella:
            distintos.append(nombre)
    return datos.get("version"), distintos


if __name__ == "__main__":
    import re
    v = re.search(r'^VERSION = "([^"]+)"', (RAIZ / "mapeo.py").read_text(encoding="utf-8"), re.M).group(1)
    d = generar(v)
    print(f"manifiesto.json: versión {v}, {len(d['archivos'])} archivos")
