"""Lee el Excel de configuración y lo deja en estructuras simples."""
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parents[1]
RUTA_CONFIG = RAIZ / "config" / "configuracion_mapeo_becas.xlsx"
RUTA_COLUMNAS = RAIZ / "config" / "columnas_airtable.txt"

# Valores exactos de la lista "Modalidad" del formulario
BECA, COOPERACION, PREMIO, SUBVENCION = ("Beca", "Cooperación Técnica (Asistencia especializada, voluntariados tecnicos, dotacion de equipos)",
                                         "Premio", "Subvención")
MODALIDADES = [BECA, SUBVENCION, COOPERACION, PREMIO]
_CORTAS = {"beca": BECA, "becas": BECA, "subvencion": SUBVENCION, "subvención": SUBVENCION, "subvenciones": SUBVENCION,
           "cooperacion tecnica": COOPERACION, "cooperación técnica": COOPERACION, "premio": PREMIO, "premios": PREMIO}


def modalidad_de(texto):
    """'Cooperación técnica' o el valor largo del formulario -> valor exacto de la lista."""
    t = str(texto or "").strip()
    if t in MODALIDADES:
        return t
    t = t.lower().split("(")[0].strip()
    return _CORTAS.get(t, "")


def modalidades_de(texto):
    """'Todas' o 'Beca; Premio' -> lista de valores exactos (vacío = todas)."""
    t = str(texto or "").strip()
    if not t or t.lower() == "todas":
        return list(MODALIDADES)
    salida = [m for m in (modalidad_de(x) for x in t.split(";")) if m]
    return [m for m in MODALIDADES if m in salida] or list(MODALIDADES)


def _terminos(texto):
    return [t.strip().lower() for t in str(texto or "").split(";") if t.strip()]


def _filas(ws):
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return []
    cab = [str(c).strip() if c is not None else "" for c in filas[0]]
    salida = []
    for f in filas[1:]:
        if all(v in (None, "") for v in f):
            continue
        salida.append({cab[i]: (f[i] if i < len(f) else None) for i in range(len(cab))})
    return salida


@dataclass
class Fuente:
    id: str
    activa: bool
    tipo: str
    nombre: str
    pais: str
    dominio: str
    url_becas: str
    oficial: str
    idioma: str
    requiere_navegador: bool
    fila: int  # fila en el Excel, para escribir la validación
    modalidades: list = field(default_factory=lambda: list(MODALIDADES))
    grupo: str = ""
    actor: str = ""  # nombre exacto en el catálogo de actores (CICLOPE), si se conoce


@dataclass
class Config:
    fuentes: list
    palabras_beca: list        # todas las palabras de convocatoria (de todas las modalidades)
    palabras_exclusion: list
    reglas_elegibilidad: list  # (regla, [terminos], puntos)
    icetex_nombres: list       # [(nombre, url)]
    icetex_paginas: list       # [url]
    icetex_palabras: list
    tematicas: list            # (tema, [terminos])
    alineacion: dict           # tema -> {campo: valor}; "(Por defecto)"
    parametros: dict
    columnas_airtable: list = field(default_factory=list)
    ruta: Path = RUTA_CONFIG
    palabras_modalidad: dict = field(default_factory=dict)  # modalidad -> [términos]

    def palabras_de(self, modalidades):
        if not self.palabras_modalidad:
            return self.palabras_beca
        return [t for m in modalidades for t in self.palabras_modalidad.get(m, [])] or self.palabras_beca

    def p(self, nombre, defecto=None):
        return self.parametros.get(nombre, defecto)


def _si(v):
    return str(v or "").strip().lower() in ("sí", "si", "yes", "true", "1")


def cargar(ruta=RUTA_CONFIG):
    wb = load_workbook(ruta, data_only=True)

    fuentes = []
    for i, f in enumerate(_filas(wb["Fuentes"]), start=2):
        fuentes.append(Fuente(
            id=str(f.get("ID") or "").strip(),
            activa=_si(f.get("Activa")),
            tipo=str(f.get("Tipo de fuente") or "").strip(),
            nombre=str(f.get("Nombre") or "").strip(),
            pais=str(f.get("País") or "").strip(),
            dominio=str(f.get("Dominio oficial") or "").strip().rstrip("/"),
            url_becas=str(f.get("URL de convocatorias") or f.get("URL de becas") or "").strip(),
            oficial=str(f.get("Oficial / No Oficial") or "No Oficial").strip(),
            idioma=str(f.get("Idioma principal") or "").strip(),
            requiere_navegador=_si(f.get("Requiere navegador")),
            fila=i,
            modalidades=modalidades_de(f.get("Modalidades a buscar")),
            grupo=str(f.get("Grupo") or f.get("Tipo de fuente") or "").strip(),
            actor=str(f.get("Actor en el catálogo") or "").strip(),
        ))

    palabras_modalidad = {}
    if "Palabras_modalidad" in wb.sheetnames:
        for f in _filas(wb["Palabras_modalidad"]):
            m = modalidad_de(f.get("Modalidad"))
            if m:
                palabras_modalidad.setdefault(m, []).extend(_terminos(f.get("Términos (separados por ;)")))
    else:
        for f in _filas(wb["Palabras_beca"]):
            palabras_modalidad.setdefault(BECA, []).extend(_terminos(f.get("Términos (separados por ;)")))
    palabras_beca = list(dict.fromkeys(t for ts in palabras_modalidad.values() for t in ts))
    exclusion = []
    for f in _filas(wb["Palabras_exclusion"]):
        exclusion += _terminos(list(f.values())[0])

    reglas = [(str(f["Regla"]), _terminos(f["Términos (separados por ;)"]), int(f["Puntos"] or 0))
              for f in _filas(wb["Elegibilidad"])]

    icetex_nombres = [(str(f.get("Nombre de la beca en ICETEX") or "").strip(), str(f.get("URL en ICETEX") or "").strip())
                      for f in _filas(wb["ICETEX_exclusiones"])]
    icetex_paginas, icetex_palabras = [], []
    for f in _filas(wb["ICETEX_paginas"]):
        url = str(f.get("URL de listado de ICETEX") or "").strip()
        if url.lower().startswith("palabras que indican"):
            icetex_palabras = _terminos(f.get("Notas"))
        elif url.startswith("http") and _si(f.get("Activa")):
            icetex_paginas.append(url)

    tematicas = [(str(f["Área temática (catálogo Airtable)"]), _terminos(f["Términos (separados por ;)"]))
                 for f in _filas(wb["Tematicas"])]

    alineacion = {}
    for f in _filas(wb["Alineacion_sugerida"]):
        tema = str(f.pop("Temática"))
        alineacion[tema] = {k: v for k, v in f.items() if v}

    parametros = {str(f["Parámetro"]): f["Valor"] for f in _filas(wb["Parametros"])}

    columnas = RUTA_COLUMNAS.read_text(encoding="utf-8").splitlines() if RUTA_COLUMNAS.exists() else []

    return Config(fuentes, palabras_beca, exclusion, reglas, icetex_nombres, icetex_paginas,
                  icetex_palabras, tematicas, alineacion, parametros, columnas, Path(ruta), palabras_modalidad)
