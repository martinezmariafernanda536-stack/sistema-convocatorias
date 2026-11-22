"""Pruebas del dashboard e informes: python -m pytest pruebas -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from analitica import datos as D  # noqa: E402
from analitica import indicadores as I  # noqa: E402
from analitica import informe as INF  # noqa: E402

CSV = RAIZ / "datos" / "airtable_actual.csv"


@pytest.fixture(scope="module")
def df():
    return D.preparar(pd.read_csv(CSV), ruta_tipos="/no-existe.xlsx")


def test_conteos_coinciden_con_la_base(df):
    crudo = pd.read_csv(CSV)
    crudo = crudo[crudo["Nombre de la Convocatoria"].notna()]
    ind = I.calcular(df)
    assert ind.total == len(crudo)
    assert ind.n["oficial"] == (crudo["Oficial / No Oficial"] == "Oficial").sum()
    assert ind.n["no_oficial"] == (crudo["Oficial / No Oficial"] == "No Oficial").sum()
    assert ind.conteo("Modalidad").sum() == len(crudo)


def test_reglas_de_tipo_de_actor():
    casos = {
        "AECID - Agencia Española de Cooperación Internacional para el Desarrollo": "Gobierno / agencia bilateral",
        "UNICEF - Fondo de las Naciones Unidas para la Infancia": "Organismo multilateral",
        "Fundación La Caixa": "Fundación / filantropía",
        "Mercy Corps": "ONG / sociedad civil",
        "Universidad de Leiden/Leiden University": "Academia / investigación",
        "HoneyComb Credit": "Empresa privada",
        "Banco de Desarrollo de América Latina- CAF": "Organismo multilateral",
    }
    for actor, esperado in casos.items():
        assert D.tipo_por_reglas(actor)[0] == esperado, actor


def test_actor_nuevo_toma_nombre_de_ciclope():
    fila = {"Nombre de la Fuente": "*NUEVO", "Nombre de actor en CICLOPE": "Universidad de Twente/University Twente (Creado)"}
    assert D.limpiar_actor(fila) == "Universidad de Twente/University Twente"


def test_textos_sin_datos_no_fallan(df):
    vacio = df.iloc[0:0]
    if len(vacio) == 0:
        ind = I.Indicadores(df=vacio, corte=pd.Timestamp("2026-11-07"))
        assert "No hay convocatorias" in I.redactar(ind)["resumen"]


def test_filtro_solo_no_oficial(df):
    ind = I.calcular(df[df["Carácter"] == "No Oficial"])
    assert ind.n["oficial"] == 0
    assert "No hay convocatorias oficiales" in ind.textos["oficial"]


def test_informe_word(df, tmp_path):
    """Informe corto: tres páginas, lenguaje sencillo, cifras clave y las abiertas que cierran primero."""
    ruta, _ = INF.generar(df, tmp_path / "informe.docx", pdf=False)
    from docx import Document
    doc = Document(ruta)
    textos = [p.text for p in doc.paragraphs]
    for esperado in ("Principales resultados", "¿Quién ofrece y en qué temas?", "¿A quién se dirigen?",
                     "Convocatorias abiertas: las que cierran primero", "Notas metodológicas"):
        assert esperado in textos
    assert len(doc.inline_shapes) <= 6                      # pocas gráficas, compactas
    saltos = sum(1 for p in doc.paragraphs for r in p.runs if 'w:br' in r._r.xml and 'type="page"' in r._r.xml)
    assert saltos == 2                                       # tres páginas
    ind = I.calcular(df)
    assert 3 <= len(ind.textos["mensajes"]) <= 5


def test_el_informe_analiza_y_no_da_instrucciones(df, tmp_path):
    ruta, _ = INF.generar(df, tmp_path / "informe.docx", pdf=False)
    from docx import Document
    doc = Document(ruta)
    todo = " ".join(p.text for p in doc.paragraphs) + " ".join(c.text for t in doc.tables for f in t.rows for c in f.cells)
    for palabra in ("Lectura estratégica", "Acciones sugeridas", "conviene", "se recomienda", "debe hacerse"):
        assert palabra.lower() not in todo.lower(), palabra


def test_pdf_sin_libreoffice(df, tmp_path, monkeypatch):
    """El PDF se genera directamente en Python: no depende de LibreOffice ni de Word."""
    import re
    monkeypatch.setattr(INF, "convertir_pdf", lambda ruta: None)  # como si no hubiera LibreOffice
    _, pdf = INF.generar(df, tmp_path / "informe.docx", pdf=True)
    assert pdf is not None and pdf.exists()
    datos = pdf.read_bytes()
    assert datos.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b", datos)) == 3
