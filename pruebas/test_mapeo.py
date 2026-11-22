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

    # un PDF no se puede completar solo: queda en el reporte para revisarlo a mano, no en la bandeja
    assert any(n.startswith("Scholarship brochure") for n in desc["Nombre"])
    assert not any("aggregator" in n.lower() for n in por_nombre)          # agregadores no entran
    assert not any("news" in n.lower() for n in por_nombre)

    # Becas que deben quedar descartadas, cada una por su motivo
    motivos = dict(zip(desc["Nombre"], desc["Motivo"]))
    assert motivos["Holland grant for EU students"].startswith("No elegible")
    assert motivos["ICETEX Utrecht scholarship for Colombians"].startswith("Está en ICETEX")
    assert motivos["Summer school scholarship 2026"].startswith("Convocatoria vencida")

    # Sin Gemini, lo que está en inglés no se guarda: en la segunda corrida vuelve a quedar como candidata (para
    # completarla cuando haya Gemini), sin duplicarse y sin darse por retirada
    assert set(rev["[Sistema] Resultado"]) == {"Incompleta o en otro idioma: se completa en una búsqueda con Gemini"}
    ruta2 = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    rev2 = pd.read_excel(ruta2, sheet_name="Revisión", dtype=str)
    assert set(rev2["Nombre de la Convocatoria"]) == set(rev["Nombre de la Convocatoria"])
    assert len(pd.read_excel(ruta2, sheet_name="Ya no aparecen", dtype=str)) == 0
    # Revisión completa: vuelve a abrir todo; lo que no se pudo guardar sigue disponible como nuevo
    ruta3 = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--completo")
    rev3 = pd.read_excel(ruta3, sheet_name="Revisión", dtype=str)
    assert set(rev3["[Sistema] Estado"]) == {"Nueva"}


def test_revision_completa_automatica_cada_30_dias(entorno, monkeypatch):
    """El modo rápido se salta lo conocido, pero cada fuente tiene revisión completa cada 30 días."""
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", str(RAIZ / "pruebas" / "gemini_completar.json"))
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    rapida = pd.read_excel(correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", "2026-11-20"),
                           sheet_name="Revisión", dtype=str)
    assert len(rapida) == 0
    completa = pd.read_excel(correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", "2026-12-20"),
                             sheet_name="Revisión", dtype=str)
    assert len(completa) > 0  # pasaron 30 días: se vuelven a abrir todas


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
    # sin Gemini, lo que está en inglés no pasa a la bandeja ni se acumula: espera a una búsqueda con Gemini
    assert not [i for i in a.items("Por revisar") if "Scholarships" in i["datos"]["Nombre de la Convocatoria"]]
    assert a.items("Por completar") == []
    assert a.base() == []                                              # nada entra a la base sin revisión
    # una segunda corrida no duplica nada
    total = len(a.items())
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    assert len(a.items()) == total


def test_con_gemini_llegan_traducidas_y_completas(entorno, tmp_path, monkeypatch):
    """Con Gemini, la convocatoria en inglés se traduce y se completa antes de guardarla, y pasa a la bandeja."""
    from bandeja.almacen import AlmacenSQLite
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", str(RAIZ / "pruebas" / "gemini_completar.json"))
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--grupo", "Universidades y centros de investigación")
    a = AlmacenSQLite(tmp_path / "base.db")
    item = next(i for i in a.items("Por revisar") if i["datos"]["Cómo aplicar"].endswith("utrecht-excellence-scholarships"))
    assert item["datos"]["Nombre de la Convocatoria"] == "Becas de Excelencia de Utrecht (Utrecht Excellence Scholarships)"
    assert item["datos"]["Observaciones a la fecha límite de aplicación"].startswith("La fecha límite corresponde")
    assert "Perfil de los aspirantes: Estudiantes" in item["datos"]["Requisitos y condiciones de participación"]


def test_cupo_de_nuevas_por_busqueda(entorno, tmp_path, monkeypatch):
    """La búsqueda se detiene al llegar a la meta de convocatorias completas; las demás quedan para la próxima."""
    from bandeja.almacen import AlmacenSQLite
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", str(RAIZ / "pruebas" / "gemini_completar.json"))
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--maximo-nuevas", "1")
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    resultados = list(rev["[Sistema] Resultado"])
    assert resultados.count("Enviada a la bandeja") == 1
    assert sum(r.startswith("Para la próxima búsqueda") for r in resultados) == len(resultados) - 1
    a = AlmacenSQLite(tmp_path / "base.db")
    assert len(a.items()) == 1
    # en la siguiente búsqueda vuelven a estar disponibles
    rev2 = pd.read_excel(correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--maximo-nuevas", "1"),
                         sheet_name="Revisión", dtype=str).fillna("")
    pendientes = {u for u in rev[rev["[Sistema] Resultado"].str.startswith("Para la próxima")]["Cómo aplicar"]
                  if not u.endswith(".pdf")}  # un PDF sin texto se descarta al leerlo
    assert pendientes and pendientes <= set(rev2["Cómo aplicar"])  # las que no alcanzaron vuelven


def test_gemini_descarta_lo_que_no_es_convocatoria(entorno, tmp_path, monkeypatch):
    import json as _json
    from bandeja.almacen import AlmacenSQLite
    d = _json.load(open(RAIZ / "pruebas" / "gemini_completar.json"))
    t = _json.loads(d["candidates"][0]["content"]["parts"][0]["text"])
    t |= {"es_convocatoria": False, "motivo_descarte": "Es una noticia sobre becas pasadas"}
    d["candidates"][0]["content"]["parts"][0]["text"] = _json.dumps(t, ensure_ascii=False)
    falso = tmp_path / "g.json"
    falso.write_text(_json.dumps(d, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", str(falso))
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY)
    desc = pd.read_excel(ruta, sheet_name="Descartadas automáticamente", dtype=str).fillna("")
    assert any(m.startswith("No es una convocatoria: Es una noticia") for m in desc["Motivo"])
    assert AlmacenSQLite(tmp_path / "base.db").items() == []


def test_limpieza_de_la_bandeja(entorno, tmp_path):
    """Lo automático que nadie ha tocado: los duplicados del mismo año se descartan y lo que está en otro idioma sale
    de la bandeja. Lo que una persona ya editó no se mueve."""
    from bandeja import flujo as F
    from bandeja.almacen import AlmacenSQLite
    a = AlmacenSQLite(tmp_path / "base.db")
    base = {"Nombre de la Convocatoria": "Becas EPOS (EPOS Scholarships)", "Cómo aplicar": "https://www.daad.de/es/epos/",
            "Fecha Límite de Aplicación": "1/3/2027", "¿La convocatoria es permanente?": "No", "Descripción": "x"}
    original, _ = F.ingresar(a, base, "Mapeo automático · X", "Mapeo automático")
    copia, _ = F.ingresar(a, base | {"Cómo aplicar": "http://daad.de/en/epos?utm_source=x"}, "Mapeo automático · X", "Mapeo automático")
    ingles, _ = F.ingresar(a, base | {"Nombre de la Convocatoria": "Research Fellowship for young leaders",
                                       "Cómo aplicar": "https://otra.org/f", "Descripción": "This programme supports researchers from developing countries who want to apply."},
                           "Mapeo automático · Y", "Mapeo automático")
    editada, _ = F.ingresar(a, base | {"Nombre de la Convocatoria": "Training Week for the public sector", "Cómo aplicar": "https://t.org/w"},
                            "Mapeo automático · Z", "Mapeo automático")
    F.guardar_cambios(a, editada, editada["datos"], "Ana")
    duplicadas, devueltas = programa.limpiar_bandeja(a)
    assert a.item(copia["id"])["estado"] == "Descartada" and "Duplicado" in a.item(copia["id"])["observacion"]
    assert a.item(ingles["id"])["estado"] == "Por completar"
    assert a.item(editada["id"])["estado"] == "Por revisar"   # la tocó una persona
    assert duplicadas == 1


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


def test_ejecucion_en_segundo_plano(entorno, tmp_path):
    """El mapeo corre en un hilo del servidor y guarda el avance en la base aunque nadie esté mirando."""
    import json
    import tareas
    from bandeja.almacen import AlmacenSQLite
    A = AlmacenSQLite(tmp_path / "servidor.db")
    assert tareas.iniciar(A, "mapear", "Buscando convocatorias", ["--prueba", str(PAGINAS), "--hoy", HOY],
                          "Natalia", Path(entorno).read_bytes())
    tareas.actual().hilo.join(120)
    t = tareas.actual()
    assert t.estado == "Terminada", t.lineas[-5:]
    assert any("candidatas" in l for l in t.lineas)  # recorrió las fuentes
    assert A.leer_archivo("ultimo_mapeo.xlsx") and A.leer_archivo("historial_mapeo.json")
    assert json.loads(A.leer_archivo("tarea_actual.json"))["estado"] == "Terminada"
    assert tareas.interrumpida(A) is None
    # si el servidor se reinicia a mitad de camino, la página lo avisa
    A.guardar_archivo("tarea_actual.json", json.dumps({"estado": "En curso", "etiqueta": "Validando fuentes"}).encode())
    assert tareas.interrumpida(A)["etiqueta"] == "Validando fuentes"


def test_mapeo_admite_nueva_edicion_de_otro_anio():
    """Una convocatoria con el mismo enlace pero de otro año no se descarta: es una nueva edición."""
    from motor.reglas import IndiceAirtable
    base = pd.DataFrame([{"Nombre de la Convocatoria": "Utrecht Excellence Scholarships",
                          "Cómo aplicar": "https://www.uu.nl/en/masters/scholarships/utrecht-excellence-scholarships",
                          "Fecha Límite de Aplicación": "1/2/2026", "¿La convocatoria es permanente?": "No"}])
    idx = IndiceAirtable(base)
    url = "https://www.uu.nl/en/masters/scholarships/utrecht-excellence-scholarships"
    assert idx.revisar("Utrecht Excellence Scholarships", url, {"Fecha Límite de Aplicación": "1/2/2027"}).startswith("Nueva edición")
    assert idx.revisar("Utrecht Excellence Scholarships", url, {"Fecha Límite de Aplicación": "15/1/2026"}).startswith("Ya está en la base")


def test_se_saltan_fuentes_que_fallaron_en_la_validacion():
    import argparse
    from motor import config as C
    cfg = C.cargar()
    activas = [f for f in cfg.fuentes if f.activa]
    activas[0].estado_validacion = "Sitio no responde (403)"
    activas[1].estado_validacion = "Bloqueado por robots.txt"
    ids = {f.id for f in programa.fuentes_a_revisar(cfg, argparse.Namespace())}
    assert activas[0].id not in ids and activas[1].id not in ids and activas[2].id in ids
    assert activas[0].id in {f.id for f in programa.fuentes_a_revisar(cfg, argparse.Namespace(todas=True))}


def test_pagina_con_varias_becas_se_separa_una_por_una():
    """Páginas como tec.mx/es/profesional/becas: cada beca está en un desplegable de la misma página. Se analiza cada
    una por separado (con su enlace #ancla, sus fechas y su elegibilidad), no la página general."""
    import argparse
    from motor import config as C
    from motor import reglas as RG
    cfg = C.cargar()
    fuente = C.Fuente(id="TEC", activa=True, tipo="Universidad", nombre="Tecnológico de Monterrey", pais="México",
                      dominio="https://tec.mx", url_becas="https://tec.mx/es/profesional/becas", oficial="No Oficial",
                      idioma="es", requiere_navegador=False, fila=0, modalidades=["Beca"])
    args = argparse.Namespace(hoy=date(2026, 11, 20), prueba=str(PAGINAS), pausa=0, todas=False)

    class SinIcetex:
        def revisar(self, *a):
            return False, ""
    res = programa.revisar_fuente(fuente, cfg, args, SinIcetex(), RG.IndiceAirtable(None, 90))
    por_url = {url: (tipo, fila, motivo) for tipo, url, fila, motivo in res["hallazgos"]}
    assert set(por_url) == {"https://tec.mx/es/profesional/becas#beca-al-talento-academico",
                            "https://tec.mx/es/profesional/becas#beca-socioeconomica",
                            "https://tec.mx/es/profesional/becas#beca-liderazgo",
                            "https://tec.mx/es/profesional/becas#beca-internacional",
                            "https://tec.mx/es/profesional/becas/beca-lideres-del-manana"}  # ni la página general ni las preguntas
    tipo, fila, _ = por_url["https://tec.mx/es/profesional/becas#beca-al-talento-academico"]
    assert tipo == "revision" and fila["Nombre de la Convocatoria"] == "Beca al Talento Académico"
    assert fila["Fecha Límite de Aplicación"] == "15/3/2027"                            # la fecha de esa beca
    tipo, fila, motivo = por_url["https://tec.mx/es/profesional/becas#beca-socioeconomica"]
    assert tipo == "descartada" and "nacionalidad mexicana" in motivo.lower()          # solo para mexicanos: no sirve
    tipo, fila, _ = por_url["https://tec.mx/es/profesional/becas#beca-liderazgo"]
    assert tipo == "revision" and fila["Fecha Límite de Aplicación"] == "30/4/2027"
    assert fila["[Sistema] Elegibilidad Colombia"] == "Elegible"
    # la beca para alumnos internacionales sí sirve: está abierta a extranjeros y no exige una nacionalidad
    tipo, fila, _ = por_url["https://tec.mx/es/profesional/becas#beca-internacional"]
    assert tipo == "revision" and fila["[Sistema] Elegibilidad Colombia"] == "Elegible"
    assert fila["Nombre de la Convocatoria"] == "Beca internacional (para alumnos internacionales)"
    assert fila["Fecha Límite de Aplicación"] == "31/5/2027"
    # el enlace a otra página de beca también se sigue; esa exige nacionalidad mexicana
    tipo, _, motivo = por_url["https://tec.mx/es/profesional/becas/beca-lideres-del-manana"]
    assert tipo == "descartada" and "mexicana" in motivo.lower()


def test_meta_de_completas_sigue_hasta_cumplirla(entorno, tmp_path, monkeypatch):
    """Si algunas candidatas no sirven, la búsqueda sigue con las siguientes hasta llegar a la meta."""
    import json as _json
    from motor import externo as EX
    from bandeja.almacen import AlmacenSQLite
    base = _json.load(open(RAIZ / "pruebas" / "gemini_completar.json"))
    contador = {"n": 0}
    original = EX.llamar

    def llamar(prompt, clave, modelo, espera=None, buscar_en_google=True):
        contador["n"] += 1
        t = _json.loads(base["candidates"][0]["content"]["parts"][0]["text"])
        n = contador["n"]
        if n % 2:  # una de cada dos «no es convocatoria»
            t |= {"es_convocatoria": False, "motivo_descarte": "Es un listado general"}
        t["nombre"] = f"Beca de prueba número {n} (Test scholarship {n})"
        return _json.dumps(t, ensure_ascii=False), []
    monkeypatch.setenv("MAPEO_GEMINI_PRUEBA_COMPLETAR", "si")
    monkeypatch.setattr(EX, "llamar", llamar)
    correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--maximo-nuevas", "2")
    a = AlmacenSQLite(tmp_path / "base.db")
    # siguió después de la primera completa y de las que no servían, hasta agotar las candidatas o llegar a la meta
    assert len(a.items("Por revisar")) >= 1 and contador["n"] >= 4
