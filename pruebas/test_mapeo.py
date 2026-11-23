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


def test_seguimiento_de_ediciones_elige_las_cerradas_y_rota(tmp_path):
    """Año tras año: las convocatorias de la base (también las de Airtable) que ya cerraron se vuelven a abrir para
    buscar su nueva edición; primero las que se acercan al aniversario de su cierre, y cada una como mucho cada 30 días."""
    from motor import config as C
    from motor.historial import Historial
    hoy = date(2026, 11, 20)
    tec = C.Fuente(id="TEC", activa=True, tipo="Universidad", nombre="Tec", pais="México", dominio="https://tec.mx",
                   url_becas="https://tec.mx/es/profesional/becas", oficial="No Oficial", idioma="es",
                   requiere_navegador=False, fila=0)
    base = [
        {"Nombre de la Convocatoria": "Beca A", "Cómo aplicar": "https://tec.mx/es/profesional/becas#beca-liderazgo",
         "Fecha Límite de Aplicación": "15/12/2025"},                             # aniversario en 25 días: primero
        {"Nombre de la Convocatoria": "Beca B", "Cómo aplicar": "https://otra.org/beca-b",
         "Fecha Límite de Aplicación": "30/6/2026", "Nombre de la Fuente": "Fundación Otra"},  # sitio fuera de las fuentes
        {"Nombre de la Convocatoria": "Abierta", "Cómo aplicar": "https://tec.mx/abierta",
         "Fecha Límite de Aplicación": "1/3/2027"},                               # sigue abierta: no
        {"Nombre de la Convocatoria": "Permanente", "Cómo aplicar": "https://tec.mx/perm",
         "¿La convocatoria es permanente?": "Si"},                                # permanente: no
        {"Nombre de la Convocatoria": "Sin fecha vieja", "Cómo aplicar": "https://tec.mx/vieja",
         "Fecha de Registro": "10/2/2025"},                                       # sin fecha y registrada otro año: sí
        {"Nombre de la Convocatoria": "Sin enlace", "Fecha Límite de Aplicación": "1/1/2025"},
    ]
    h = Historial(tmp_path / "h.json")
    sel = programa.ediciones_a_seguir(base, [tec], h, hoy, limite=10)
    urls = {u for _, lista in sel.values() for u, _ in lista}
    assert urls == {"https://tec.mx/es/profesional/becas#beca-liderazgo", "https://otra.org/beca-b", "https://tec.mx/vieja"}
    assert sel["SEG-otra.org"][0].tipo == "Seguimiento de ediciones" and sel["SEG-otra.org"][0].nombre == "Fundación Otra"
    # con límite 1 va la más cercana al aniversario de su cierre
    uno = programa.ediciones_a_seguir(base, [tec], h, hoy, limite=1)
    assert [u for _, l in uno.values() for u, _ in l] == ["https://tec.mx/es/profesional/becas#beca-liderazgo"]
    # revisada hace poco: no se repite hasta pasados 30 días
    h.marcar_seguida("https://tec.mx/es/profesional/becas#beca-liderazgo", "2026-11-10")
    h.guardar()
    h = Historial(tmp_path / "h.json")
    urls = {u for _, l in programa.ediciones_a_seguir(base, [tec], h, hoy, 10).values() for u, _ in l}
    assert "https://tec.mx/es/profesional/becas#beca-liderazgo" not in urls
    urls = {u for _, l in programa.ediciones_a_seguir(base, [tec], h, date(2026, 12, 15), 10).values() for u, _ in l}
    assert "https://tec.mx/es/profesional/becas#beca-liderazgo" in urls


def test_seguimiento_reabre_la_pagina_aunque_sea_conocida():
    """Aunque el modo rápido salte las convocatorias ya conocidas, la que está en seguimiento se vuelve a leer, y si su
    página trae una fecha nueva llega como nueva edición (no como duplicado de la del año pasado)."""
    import argparse
    from motor import config as C
    from motor import reglas as RG
    cfg = C.cargar()
    fuente = C.Fuente(id="TEC", activa=True, tipo="Universidad", nombre="Tecnológico de Monterrey", pais="México",
                      dominio="https://tec.mx", url_becas="https://tec.mx/es/profesional/becas", oficial="No Oficial",
                      idioma="es", requiere_navegador=False, fila=0, modalidades=["Beca"])
    args = argparse.Namespace(hoy=date(2026, 11, 20), prueba=str(PAGINAS), pausa=0, todas=False)
    url = "https://tec.mx/es/profesional/becas#beca-liderazgo"
    base = pd.DataFrame([{"Nombre de la Convocatoria": "Beca de Liderazgo", "Cómo aplicar": url,
                          "Fecha Límite de Aplicación": "30/4/2026", "Fecha de Registro": "1/2/2026"}])

    class SinIcetex:
        def revisar(self, *a):
            return False, ""
    conocidas = frozenset({url, "https://tec.mx/es/profesional/becas#beca-al-talento-academico"})
    res = programa.revisar_fuente(fuente, cfg, args, SinIcetex(), RG.IndiceAirtable(base, 90), conocidas,
                                  completa=False, seguir=[(url, "Beca de Liderazgo")])
    por_url = {u: (t, f, m) for t, u, f, m in res["hallazgos"]}
    assert "https://tec.mx/es/profesional/becas#beca-al-talento-academico" in res["sin_cambios"]  # la otra se salta
    tipo, fila, motivo = por_url[url]
    assert tipo == "revision" and fila["Fecha Límite de Aplicación"] == "30/4/2027"
    assert "Nueva edición" in fila["[Sistema] Duplicado en Airtable"]
    assert res["seguidas"] == [url]


def test_seguimiento_sitio_fuera_de_las_fuentes():
    """Si la página de la convocatoria no está entre las fuentes, se abre igual con una fuente provisional."""
    import argparse
    from motor import config as C
    from motor import reglas as RG
    cfg = C.cargar()
    base = [{"Nombre de la Convocatoria": "Beca Líderes del Mañana",
             "Cómo aplicar": "https://tec.mx/es/profesional/becas/beca-lideres-del-manana",
             "Fecha Límite de Aplicación": "1/12/2025", "Nombre de la Fuente": "Tec"}]
    from motor.historial import Historial
    import tempfile
    sel = programa.ediciones_a_seguir(base, [], Historial(Path(tempfile.mkdtemp()) / "h.json"), date(2026, 11, 20))
    (fuente, lista), = sel.values()
    args = argparse.Namespace(hoy=date(2026, 11, 20), prueba=str(PAGINAS), pausa=0, todas=False)

    class SinIcetex:
        def revisar(self, *a):
            return False, ""
    res = programa.revisar_fuente(fuente, cfg, args, SinIcetex(), RG.IndiceAirtable(None, 90), seguir=lista)
    assert res["paginas"] == [] and res["seguidas"] == [lista[0][0]]
    assert [u for _, u, _, _ in res["hallazgos"]] == [lista[0][0]]


def test_mapeo_hace_seguimiento_de_ediciones_de_la_base(entorno, tmp_path, monkeypatch):
    monkeypatch.setenv("MAPEO_HISTORIAL", str(tmp_path / "datos" / "historial.json"))
    air = pd.read_csv(RAIZ / "datos" / "airtable_actual.csv")
    i = len(air)
    air.loc[i, "Nombre de la Convocatoria"] = "Beca Líderes del Mañana"
    air.loc[i, "Cómo aplicar"] = "https://tec.mx/es/profesional/becas/beca-lideres-del-manana"
    air.loc[i, "Fecha Límite de Aplicación"] = "1/12/2025"
    ruta_csv = tmp_path / "air.csv"
    air.to_csv(ruta_csv, index=False)
    ruta = correr("mapear", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--csv", str(ruta_csv))
    desc = pd.read_excel(ruta, sheet_name="Descartadas automáticamente", dtype=str).fillna("")
    rev = pd.read_excel(ruta, sheet_name="Revisión", dtype=str).fillna("")
    urls = set(desc.astype(str).stack()) | set(rev.astype(str).stack())
    assert any("beca-lideres-del-manana" in u for u in urls)  # se volvió a abrir aunque ninguna fuente activa la enlaza
    import json
    h = json.loads((tmp_path / "datos" / "historial.json").read_text(encoding="utf-8"))
    assert "https://tec.mx/es/profesional/becas/beca-lideres-del-manana" in h["_seguimiento_ediciones"]


class _SinIcetex:
    def revisar(self, *a):
        return False, ""


def test_radar_lee_el_agregador_y_registra_solo_la_pagina_oficial():
    """Descubrir: el agregador solo sirve de radar. Se sigue el enlace «Apply / Official website» y se registra la
    página del oferente (sin parámetros de rastreo); redes sociales, otros agregadores y formularios se ignoran."""
    import argparse
    from motor import config as C
    from motor import reglas as RG
    cfg = C.cargar()
    od = next(r for r in cfg.radar if r.id == "RAD-OD")
    args = argparse.Namespace(hoy=date(2026, 11, 9), prueba=str(PAGINAS), pausa=0, todas=False)
    res = programa.revisar_radar(od, cfg, args, _SinIcetex(), RG.IndiceAirtable(None, 90))
    por_url = {u: f for _, u, f, _ in res["hallazgos"]}
    assert set(por_url) == {"https://www.fundacionejemplo.org/becas/liderazgo-2027",
                            "https://www.unesco.org/en/prizes/example-peace-education-2027",
                            "https://www.uu.nl/en/scholarships/utrecht-excellence-scholarships"}
    assert not any("opportunitydesk" in u for u in por_url)
    nueva = por_url["https://www.fundacionejemplo.org/becas/liderazgo-2027"]
    assert nueva["[Sistema] Fuente ID"] == "RAD-fundacionejemplo.org"        # sitio que no está entre las fuentes
    assert nueva["Nombre de la Fuente"] == "Fundación Ejemplo"                 # nombre tomado del sitio oficial
    assert nueva["Fecha Límite de Aplicación"] == "15/3/2027"
    assert "Opportunity Desk" in nueva["[Sistema] Página donde se encontró"]
    assert nueva["Link de la Fuente Oferente"].startswith("https://")      # enlace válido del oferente nuevo
    assert not any("interfolio" in u or u.endswith("/login") for u in por_url)  # postulación e inicio de sesión: no
    # si el sitio oficial ya es una fuente, se usa esa fuente (con su actor y su carácter oficial)
    assert por_url["https://www.uu.nl/en/scholarships/utrecht-excellence-scholarships"]["[Sistema] Fuente ID"] == "UNI-NL-01"
    # las publicaciones quedan anotadas para no volver a abrirlas
    assert len(res["sin_cambios"]) == 3
    # en la siguiente búsqueda, lo ya visto no se vuelve a abrir
    res2 = programa.revisar_radar(od, cfg, args, _SinIcetex(), RG.IndiceAirtable(None, 90),
                                  frozenset(res["sin_cambios"]))
    assert res2["hallazgos"] == []


def test_radar_portal_de_la_union_europea():
    import argparse
    from motor import config as C
    from motor import reglas as RG
    from motor import radar as R
    items, nota = R.portal_ue(10, date(2026, 11, 9), str(PAGINAS))
    assert [t for _, t, _ in items] == ["Research cooperation with Latin America on climate adaptation"]  # la cerrada no
    assert "Deadline: 2027-02-17" in items[0][2]
    cfg = C.cargar()
    ue = next(r for r in cfg.radar if r.id == "RAD-UE")
    args = argparse.Namespace(hoy=date(2026, 11, 9), prueba=str(PAGINAS), pausa=0, todas=False)
    res = programa.revisar_radar(ue, cfg, args, _SinIcetex(), RG.IndiceAirtable(None, 90))
    (tipo, url, fila, _), = res["hallazgos"]
    assert tipo == "revision" and url.endswith("topic-details/HORIZON-CL5-2027-01-12")
    assert fila["Fecha Límite de Aplicación"] == "17/2/2027" and fila["Oficial / No Oficial"] == "Oficial"


def test_descubrir_es_una_busqueda_aparte_con_fuentes_sugeridas(entorno, tmp_path, monkeypatch):
    monkeypatch.setenv("MAPEO_HISTORIAL", str(tmp_path / "datos" / "historial.json"))
    ruta = correr("descubrir", "--config", str(entorno), "--prueba", str(PAGINAS), "--hoy", HOY, "--sin-gemini")
    assert Path(ruta).name.startswith("descubrimiento_")
    hojas = pd.read_excel(ruta, sheet_name=None, dtype=str)
    rev = hojas["Revisión"].fillna("")
    assert "https://www.fundacionejemplo.org/becas/liderazgo-2027" in set(rev.astype(str).stack())
    assert not any("ahk.de" in v for v in rev.astype(str).stack())   # no recorre las fuentes normales
    sug = hojas["Fuentes sugeridas"].fillna("")
    assert list(sug["Dominio oficial"]) == ["https://fundacionejemplo.org"]  # UNESCO, Utrecht y la UE ya son fuentes
    assert sug.iloc[0]["Oferente"] == "Fundación Ejemplo"


def test_agregar_fuente_sugerida_por_el_radar(tmp_path):
    from openpyxl import load_workbook
    cfg = tmp_path / "c.xlsx"
    shutil.copy(RAIZ / "config" / "configuracion_mapeo_becas.xlsx", cfg)
    programa.agregar_fuentes(cfg, [{"Oferente": "Fundación Ejemplo", "Dominio oficial": "https://fundacionejemplo.org",
                                    "Tipo de actor": "Por clasificar", "Oficial / No Oficial": "No Oficial",
                                    "Convocatorias encontradas": "Beca X"}], origen="Descubrimiento (radar)")
    ws = load_workbook(cfg)["Fuentes"]
    cab = [c.value for c in ws[1]]
    ultima = {cab[i]: c.value for i, c in enumerate(ws[ws.max_row])}
    assert ultima["Nombre"] == "Fundación Ejemplo" and ultima["Origen"] == "Descubrimiento (radar)"


def test_configuracion_guardada_recibe_hojas_y_parametros_nuevos(tmp_path):
    """Al actualizar el programa, la configuración editada en la app conserva sus cambios y recibe lo nuevo (hoja Radar)."""
    import io
    from openpyxl import load_workbook
    from motor import config as C
    wb = load_workbook(RAIZ / "config" / "configuracion_mapeo_becas.xlsx")
    del wb["Radar"]
    ws = wb["Parametros"]
    for fila in list(ws.iter_rows(min_row=2)):
        if fila[0].value == "Publicaciones a revisar por agregador":
            ws.delete_rows(fila[0].row)
    wb["Fuentes"]["D2"] = "Fuente editada por el administrador"
    b = io.BytesIO()
    wb.save(b)
    nuevo = C.completar_con_paquete(b.getvalue())
    wb2 = load_workbook(io.BytesIO(nuevo))
    assert "Radar" in wb2.sheetnames and wb2["Radar"]["D2"].value == "Opportunity Desk"
    assert wb2["Fuentes"]["D2"].value == "Fuente editada por el administrador"
    assert "Publicaciones a revisar por agregador" in {r[0].value for r in wb2["Parametros"].iter_rows(min_row=2)}
    assert C.completar_con_paquete(nuevo) == nuevo   # si ya está completa, no se toca


def test_completar_a_mano_pasa_a_por_revisar(tmp_path, monkeypatch):
    from bandeja import flujo
    from bandeja.almacen import AlmacenSQLite
    A = AlmacenSQLite(tmp_path / "b.db")
    datos = {"Nombre de la Convocatoria": "Beca de prueba", "Modalidad": "Beca"}
    item = flujo.ingresar(A, datos, "Descubrimiento fuera de las fuentes · RAD-x.org", "Sistema",
                          {"faltantes": ["Fecha Límite de Aplicación: vacía"]}, estado="Por completar")
    item = A.items("Por completar")[0]
    flujo.pasar_a_revision(A, item, datos | {"Fecha Límite de Aplicación": "1/3/2027"}, "Natalia")
    (r,) = A.items("Por revisar")
    assert r["datos"]["Fecha Límite de Aplicación"] == "1/3/2027" and "faltantes" not in r["meta"]
    assert flujo.tocada_por_persona(r)          # la limpieza automática ya no la devuelve
    assert A.items("Por completar") == []


def test_seguimiento_por_temporada_y_tablero(tmp_path):
    """Las que se repiten: en su temporada se revisan cada 14 días; el tablero dice qué pasó con cada una."""
    from motor.historial import Historial
    hoy = date(2026, 11, 22)
    base = [
        {"Nombre de la Convocatoria": "Becas de Doctorado Fundación Carolina", "Nombre de la Fuente": "Fundación Carolina",
         "Cómo aplicar": "https://www.fundacioncarolina.es/becas/doctorado", "Fecha Límite de Aplicación": "10/2/2026"},
        {"Nombre de la Convocatoria": "Premio de verano", "Cómo aplicar": "https://x.org/premio",
         "Fecha Límite de Aplicación": "15/7/2026"},                                    # fuera de temporada
        {"Nombre de la Convocatoria": "Beca sin enlace", "Fecha Límite de Aplicación": "1/3/2026"},
        {"Nombre de la Convocatoria": "Beca Chevening", "Cómo aplicar": "https://chevening.org/scholarships",
         "Fecha Límite de Aplicación": "5/11/2026"},
    ]
    h = Historial(tmp_path / "h.json")
    sel = programa.ediciones_a_seguir(base, [], h, hoy, limite=1)
    assert [u for _, l in sel.values() for u, _ in l] in (["https://www.fundacioncarolina.es/becas/doctorado"],
                                                       ["https://chevening.org/scholarships"])
    h.marcar_seguida("https://www.fundacioncarolina.es/becas/doctorado", "2026-11-01")   # hace 21 días: toca de nuevo
    h.marcar_seguida("https://x.org/premio", "2026-11-01")                               # fuera de temporada: aún no
    urls = {u for _, l in programa.ediciones_a_seguir(base, [], h, hoy, 10).values() for u, _ in l}
    assert "https://www.fundacioncarolina.es/becas/doctorado" in urls and "https://x.org/premio" not in urls
    # la edición nueva de Chevening ya llegó (otro enlace, mismo nombre)
    items = [{"estado": "Por revisar", "ingreso": "2026-11-20", "origen": "Mapeo automático",
              "datos": {"Nombre de la Convocatoria": "Beca Chevening 2027-2028", "Fecha Límite de Aplicación": "4/11/2027",
                        "Cómo aplicar": "https://chevening.org/scholarship-2027"}}]
    tab = {f["Convocatoria"]: f["Estado"] for f in programa.estado_seguimiento(base, items, h.seguidas, hoy)}
    assert tab["Beca Chevening"] == "Edición nueva ya en el sistema"
    assert tab["Becas de Doctorado Fundación Carolina"] == "Revisada: aún sin edición nueva"
    assert tab["Beca sin enlace"] == "Sin página oficial para seguirla"
    assert tab["Premio de verano"] == "Revisada: aún sin edición nueva"


def test_prioridad_de_nueva_edicion():
    hoy = date(2026, 11, 22)
    comun = {"Nombre de la Convocatoria": "Becas Fundación Carolina de doctorado", "Fecha Límite de Aplicación": "1/3/2027",
             "[Sistema] Elegibilidad Colombia": "Elegible", "_texto": "x" * 2000}
    nueva = comun | {"[Sistema] Duplicado en Airtable": "Nueva edición: ya se registró la de 2026"}
    assert programa.prioridad(nueva, hoy) > programa.prioridad(comun, hoy) + 5


def test_seguimiento_lee_el_enlace_dentro_del_texto_y_prueba_el_ano_siguiente(tmp_path):
    from motor.historial import Historial
    base = [{"Nombre de la Convocatoria": "Becas de la Fundación Carolina 2026 - 2027", "Nombre de la Fuente": "Fundación Carolina",
             "Cómo aplicar": "Debe ingresar a la página oficial en el link "
                             "https://www.fundacioncarolina.es/convocatoria-de-becas-2026-2027/",
             "Fecha Límite de Aplicación": "2/3/2026"}]
    sel = programa.ediciones_a_seguir(base, [], Historial(tmp_path / "h.json"), date(2026, 11, 22))
    urls = [u for _, l in sel.values() for u, _ in l]
    assert urls == ["https://www.fundacioncarolina.es/convocatoria-de-becas-2026-2027/",
                    "https://www.fundacioncarolina.es/convocatoria-de-becas-2027-2028/"]


def test_descarta_noticias_y_ganadores_sin_gemini():
    hoy = date(2026, 11, 22)
    no = [{"Nombre de la Convocatoria": "Premio Earthshot 2022: Kheyti (2022 Earthshot Prize Winner)", "_url": "https://x.org/a"},
          {"Nombre de la Convocatoria": "Becca Heller Recibe Beca MacArthur", "_url": "https://x.org/b"},
          {"Nombre de la Convocatoria": "Programa de becas", "_url": "https://x.org/news/2026/programa"},
          {"Nombre de la Convocatoria": "Becas IILA-MAECI 2025", "_url": "https://x.org/becas"}]
    si = [{"Nombre de la Convocatoria": "Becas Chevening 2027-2028", "_url": "https://chevening.org/scholarships"},
          {"Nombre de la Convocatoria": "Premio a ganadores de ideas 2025", "_url": "https://x.org/p",
           "Fecha Límite de Aplicación": "1/3/2027"},                       # con fecha futura nunca se descarta
          {"Nombre de la Convocatoria": "British Council Scholarships for Women in STEM", "_url": "https://x.org/s"}]
    assert all(programa.parece_no_convocatoria(f, hoy) for f in no)
    assert not any(programa.parece_no_convocatoria(f, hoy) for f in si)
