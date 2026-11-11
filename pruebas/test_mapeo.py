"""Pruebas sin internet: python -m pytest pruebas -q"""
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import mapeo as programa  # noqa: E402
from motor import texto as tx  # noqa: E402
from motor.salidas import a_registro_airtable  # noqa: E402

HOY = "2026-11-09"
PAGINAS = RAIZ / "pruebas" / "paginas"


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    """Copia la configuración, activa solo dos fuentes y aísla historial y salidas."""
    cfg = tmp_path / "config.xlsx"
    shutil.copy(RAIZ / "config" / "configuracion_mapeo_becas.xlsx", cfg)
    wb = load_workbook(cfg)
    ws = wb["Fuentes"]
    for fila in ws.iter_rows(min_row=2):
        fila[1].value = "Sí" if fila[0].value in ("UNI-NL-01", "CAM-DE") else "No"
    ws = wb["ICETEX_paginas"]
    ws["A2"], ws["B2"] = "https://web.icetex.gov.co/es/becas-exterior", "Sí"
    wb.save(cfg)
    monkeypatch.setattr(programa, "RAIZ", tmp_path)
    monkeypatch.setenv("BASE_DATOS", str(tmp_path / "base.db"))
    monkeypatch.setenv("SIN_BASE_INICIAL", "1")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    return cfg


def correr(*args):
    return programa.main(list(args))


def test_mapeo_completo(entorno, tmp_path):
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY,
                  "--csv", str(RAIZ / "datos" / "airtable_actual.csv"))
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    desc = pd.read_excel(ruta, sheet_name="Descartadas automáticamente", dtype=str).fillna("")
    por_nombre = {r["Nombre de la Convocatoria"]: r for _, r in rev.iterrows()}

    # Becas que deben quedar para revisión
    exc = por_nombre["Utrecht Excellence Scholarships"]
    assert exc["[Sistema] Elegibilidad Colombia"] == "Elegible"
    assert exc["Fecha Límite de Aplicación"] == "1/2/2027"
    assert exc["Financiación"] == ""                      # está en euros: no se pone como USD
    assert "15,000" in exc["Observaciones sobre el financiamiento"]
    assert exc["Email para mayor información"] == "scholarships@uu.nl"
    assert "Cambio Climático" in exc["Áreas temáticas de interés"]
    assert exc["Oficial / No Oficial"] == "No Oficial"
    assert exc["Tiempo de vencimiento es mayor a un mes y una semana"] == "checked"
    assert exc["ODS"] == "13. Acción por el Clima"

    dual = por_nombre["Beca de formación dual en Alemania para jóvenes colombianos"]
    assert dual["[Sistema] Elegibilidad Colombia"] == "Elegible"
    assert dual["Financiación"] == "$1200.00"
    assert dual["Fecha Límite de Aplicación"] == "30/1/2027"
    assert "Jovenes" in dual["Esta convocatoria prioriza alguna de las siguientes poblaciones?"]
    assert dual["Oficial / No Oficial"] == "No Oficial"

    assert exc["Modalidad"] == "Beca"

    # Las mismas fuentes se revisan también para subvenciones y premios
    sub = por_nombre["Global Challenges small grants: call for proposals 2027"]
    assert sub["Modalidad"] == "Subvención"
    assert sub["[Sistema] Elegibilidad Colombia"] == "Elegible"
    assert sub["[Sistema] Motivo ICETEX"] == "No aplica (no es beca)"
    assert "Entidades sin animo de lucro (ESAL)" in sub["Dirigida a (tipo de publico)"]
    assert "Ciudadanos" not in sub["Dirigida a (tipo de publico)"]
    assert not sub["Áreas temáticas de interés"].startswith("Educación")
    assert sub["Fecha Límite de Aplicación"] == "15/3/2027"
    pre = por_nombre["Utrecht Sustainability Prize 2027"]
    assert pre["Modalidad"] == "Premio"
    assert pre["Financiación"] == "$50000.00"

    lid = por_nombre["Beca de liderazgo empresarial (ejemplo)"]
    assert lid["¿La convocatoria es permanente?"] == "Si"

    assert any(n.startswith("Scholarship brochure") for n in por_nombre)   # PDF para revisar a mano
    assert not any("aggregator" in n.lower() for n in por_nombre)          # agregadores no entran
    assert not any("news" in n.lower() for n in por_nombre)

    # Becas que deben quedar descartadas, cada una por su motivo
    motivos = dict(zip(desc["Nombre"], desc["Motivo"]))
    assert motivos["Holland grant for EU students"].startswith("No elegible")
    assert motivos["ICETEX Utrecht scholarship for Colombians"].startswith("Está en ICETEX")
    assert motivos["Summer school scholarship 2026"].startswith("Convocatoria vencida")

    # Segunda corrida: nada es nuevo
    ruta2 = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    rev2 = pd.read_excel(ruta2, sheet_name="Revisión", dtype=str)
    assert set(rev2["[Sistema] Estado"]) == {"Sin cambios"}


def test_duplicado_con_airtable(entorno, tmp_path):
    air = pd.read_csv(RAIZ / "datos" / "airtable_actual.csv")
    air.loc[len(air), "Nombre de la Convocatoria"] = "Utrecht Excellence Scholarships"
    ruta_csv = tmp_path / "air.csv"
    air.to_csv(ruta_csv, index=False)
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--csv", str(ruta_csv))
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    fila = rev[rev["Nombre de la Convocatoria"] == "Utrecht Excellence Scholarships"].iloc[0]
    assert fila["[Sistema] Duplicado en Airtable"].startswith("Posible duplicado")


@pytest.mark.parametrize("frase,esperada", [
    ("application deadline: 15 march 2027", date(2027, 3, 15)),
    ("fecha limite: 15 de marzo de 2027", date(2027, 3, 15)),
    ("deadline march 15, 2027", date(2027, 3, 15)),
    ("date limite : 1er fevrier 2027", date(2027, 2, 1)),
    ("bewerbungsschluss: 15.03.2027", date(2027, 3, 15)),
    ("deadline 2027-03-15", date(2027, 3, 15)),
])
def test_fechas(frase, esperada):
    assert tx.fecha_cierre(frase, date(2026, 11, 9))[0] == esperada


def test_registro_para_api():
    r = a_registro_airtable({"Fecha Límite de Aplicación": "1/2/2027", "Financiación": "$1200.00",
                             "Áreas temáticas de interés": 'Educación,"Ciencia, Tecnología , Innovación, Investigación (STEM)"',
                             "VERIFICACIÓN: Página web correcta y activa": "checked", "Descripción": ""})
    assert r == {"Fecha Límite de Aplicación": "2027-02-01", "Financiación": 1200.0,
                 "Áreas temáticas de interés": ["Educación", "Ciencia, Tecnología , Innovación, Investigación (STEM)"],
                 "VERIFICACIÓN: Página web correcta y activa": True}


def test_mapeo_envia_a_la_bandeja_sin_tocar_la_base(entorno, tmp_path):
    from bandeja.almacen import AlmacenSQLite
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    a = AlmacenSQLite(tmp_path / "base.db")
    items = a.items("Por revisar")
    nombres = {i["datos"]["Nombre de la Convocatoria"] for i in items}
    assert "Utrecht Excellence Scholarships" in nombres
    assert "Holland grant for EU students" not in nombres          # descartada automáticamente
    assert all(i["datos"]["VERIFICACIÓN: Colombia hace parte de los países beneficiarios"] == "" for i in items)
    assert a.base() == []                                              # nada entra a la base sin revisión
    # una segunda corrida no duplica la bandeja
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    assert len(a.items()) == len(items)


# --- configuración y fuentes oficiales ---------------------------------------
def test_configuracion_de_fuentes():
    from calidad import dominios as DOM
    from motor import config as C
    cfg = C.cargar()
    assert set(cfg.palabras_modalidad) == set(C.MODALIDADES)
    activas = [f for f in cfg.fuentes if f.activa]
    assert len(activas) >= 200
    assert len({f.id for f in cfg.fuentes}) == len(cfg.fuentes)
    for f in activas:
        assert f.dominio, f.id
        cat, _ = DOM.clasificar(f.dominio, f.dominio)
        assert cat == "Oficial del oferente", (f.id, f.dominio)
        assert f.modalidades == C.MODALIDADES
    assert cfg.icetex_paginas  # lista de becas vigentes de ICETEX
    grupos = {f.grupo for f in cfg.fuentes}
    assert {"Universidades y centros de investigación", "Gobiernos y agencias", "Organismos multilaterales",
            "Fundaciones, ONG y empresas", "Cámaras binacionales"} <= grupos


@pytest.mark.parametrize("titulo,url,texto,esperada", [
    ("Call for proposals: small grants 2027", "https://x.org/funding/call", "grants for ngos", "Subvención"),
    ("Women in Agriculture Award", "https://x.org/awards/women", "the award recognises", "Premio"),
    ("Volunteers for the Amazon", "https://x.org/volunteer", "technical assistance and volunteering", "Cooperación Técnica (Asistencia especializada, voluntariados tecnicos, dotacion de equipos)"),
    ("Master scholarships for Latin America", "https://x.edu/scholarships", "full scholarship", "Beca"),
    ("Programa sin palabras clave", "https://x.org/programa", "", "Beca"),
])
def test_modalidad(titulo, url, texto, esperada):
    from motor import config as C
    from motor.reglas import detectar_modalidad
    cfg = C.cargar()
    assert detectar_modalidad(titulo, url, tx.normalizar(texto), cfg, C.MODALIDADES)[0] == esperada


def test_grupo_de_fuentes(entorno, tmp_path):
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--grupo", "Cámaras binacionales")
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    assert set(rev["[Sistema] Fuente ID"]) == {"CAM-DE"}


# --- búsqueda externa con Gemini ---------------------------------------------
def test_busqueda_externa_gemini(entorno, tmp_path, monkeypatch):
    """Gemini solo propone: el sistema abre cada página y descarta agregadores, ICETEX y enlaces inventados."""
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA", str(RAIZ / "pruebas" / "gemini_respuesta.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ruta = correr("buscar-externo", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY,
                  "--modalidad", "Subvención", "--modalidad", "Beca")
    rev = pd.read_excel(ruta, sheet_name="Para revisión", dtype=str).fillna("")
    desc = pd.read_excel(ruta, sheet_name="Descartadas", dtype=str).fillna("")
    sug = pd.read_excel(ruta, sheet_name="Fuentes sugeridas", dtype=str).fillna("")
    assert list(rev["Nombre de la Convocatoria"]) == [
        "Pequeñas subvenciones para resiliencia climática 2027 (Climate Resilience Small Grants 2027)"]
    f = rev.iloc[0]
    assert f["[Sistema] Título en la página"] == "Climate Resilience Small Grants 2027 - Call for proposals"
    assert f["Descripción"].startswith("Subvenciones de hasta USD 30.000")
    assert f["Objetivos General y Específicos"].startswith("General:")
    assert f["Esta convocatoria prioriza alguna de las siguientes poblaciones?"] == "Indigenas,Mujeres"
    assert f["Ámbito Geográfico"] == "Regional"
    assert f["Plan Marco de Implementación"] == "No Aplica"
    assert f["Tipo de monto"] == "Por beneficiario o proyecto"
    assert f["Financiación"] == "$30000.00"  # leído en la página, no de Gemini
    assert f["[Sistema] Evidencia de Gemini en la página"].startswith("Sí")
    assert "Objetivos General y Específicos" in f["[Sistema] Campos completados por Gemini"]
    assert "Financiación" not in f["[Sistema] Campos completados por Gemini"]
    assert f["Modalidad"] == "Subvención"
    assert f["[Sistema] Elegibilidad Colombia"] == "Elegible"
    assert f["Fecha Límite de Aplicación"] == "20/2/2027"
    assert f["[Sistema] Encontrado en Google"] == "Sí"
    assert "Evidencia Colombia" in f["[Sistema] Propuesta de Gemini"]
    motivos = dict(zip(desc["Convocatoria"], desc["Motivo"]))
    assert motivos["Beca agregada"].startswith("No es un sitio oficial (Agregador")
    assert motivos["Beca por ICETEX"].startswith("No es un sitio oficial (ICETEX")
    assert "posible enlace inventado" in motivos["Beca inventada"]
    assert list(sug["Dominio oficial"]) == ["https://fondo-ejemplo.org"]
    # quedó en la bandeja, sin verificaciones marcadas
    from bandeja.almacen import abrir
    items = abrir().items("Por revisar")
    assert len(items) == 1 and items[0]["origen"].startswith("Búsqueda externa (Gemini)")
    assert items[0]["datos"]["VERIFICACIÓN: Colombia hace parte de los países beneficiarios"] == ""
    # la fuente sugerida se puede agregar a la configuración
    n = programa.agregar_fuentes(entorno, sug.to_dict("records"))
    from motor import config as C
    nueva = [x for x in C.cargar(entorno).fuentes if x.id.startswith("EXT-")]
    assert n == 1 and nueva[0].dominio == "https://fondo-ejemplo.org" and nueva[0].activa


def test_prompt_gemini_tiene_las_condiciones_del_formulario():
    from calidad.reglas import CATALOGOS
    from motor import externo
    p = externo.construir_prompt(CATALOGOS, ["Beca", "Premio"], date(2026, 11, 8), excluir={"uu.nl"})
    for texto in ("sitio web oficial", "FundsforNGOs", "Boletín de Oferta Internacional", "apertura", "requisitos", "ICETEX", "No inventes enlaces", "Colombia", "uu.nl",
                  "Entidades sin animo de lucro (ESAL)", "hasta 3", "08/11/2026"):
        assert texto in p, texto
    for t in CATALOGOS["Áreas temáticas de interés"][:5]:
        assert t in p


@pytest.mark.parametrize("texto,esperado", [
    ("Open to international students from all countries.", "Elegible"),
    ("Scholarships for foreign nationals who want to study in Japan.", "Elegible"),
    ("Becas para extranjeros que deseen cursar un máster en España.", "Elegible"),
    ("Grants for NGOs in developing countries (ODA-eligible, DAC list).", "Elegible"),
    ("Applicants from Africa, Asia and Latin America. Only for citizens of eligible countries listed below.", "Elegible"),
    ("Open to Latin American researchers.", "Elegible"),
    ("This programme is for EU students only.", "No elegible"),
    ("Only for citizens of African countries.", "No elegible"),
    ("Open to all countries except Colombia.", "No elegible"),
    ("Beca para estudios de maestría en ingeniería.", "Revisar"),
])
def test_elegibilidad(texto, esperado):
    from motor import config as C
    cfg = C.cargar()
    from motor import reglas as RG
    from motor import texto as T
    assert RG.elegibilidad(T.normalizar(texto), cfg)[0] == esperado


def test_mapeo_completa_campos_con_gemini(entorno, tmp_path, monkeypatch):
    """Con clave de Gemini, el mapeo normal también completa los campos leyendo la página (sin buscar en Google)."""
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", str(RAIZ / "pruebas" / "gemini_completar.json"))
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--grupo", "Universidades y centros de investigación")
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    assert "_texto" not in rev.columns
    exc = rev[rev["Cómo aplicar"].str.endswith("utrecht-excellence-scholarships")].iloc[0]
    assert exc["Nombre de la Convocatoria"] == "Becas de Excelencia de Utrecht (Utrecht Excellence Scholarships)"
    assert exc["Descripción"].startswith("Becas para estudiantes de fuera de la UE")
    assert exc["Objetivos General y Específicos"].startswith("General:")
    assert exc["Tipo de monto"] == "Por beneficiario o proyecto"
    assert "EUR" in exc["Observaciones sobre el financiamiento"]
    assert exc["Fecha Límite de Aplicación"] == "1/2/2027"  # la de la página
    assert exc["[Sistema] Evidencia de Gemini en la página"].startswith("Sí")
    from bandeja.almacen import abrir
    item = next(i for i in abrir().items() if i["datos"]["Cómo aplicar"].endswith("utrecht-excellence-scholarships"))
    assert item["datos"]["Tipo de monto"] == "Por beneficiario o proyecto"
    assert "completados por Gemini" in item["meta"]["gemini"]



def test_la_busqueda_no_usa_criterios_de_socializacion():
    """El mapeo y Gemini buscan todas las convocatorias válidas, no solo las que se priorizan."""
    from calidad.reglas import CATALOGOS
    from motor import externo
    for p in (externo.construir_prompt(CATALOGOS, ["Subvención"], date(2026, 11, 10)),
              externo.prompt_completar("texto", "t", "u", CATALOGOS, "Subvención")):
        assert "50.000" not in p and "50000" not in p and "prioriz" not in p.lower()
