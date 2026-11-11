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
    ruta, _ = INF.generar(df, tmp_path / "informe.docx", pdf=False)
    from docx import Document
    doc = Document(ruta)
    titulos = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    for esperado in ("Ficha técnica", "Resumen ejecutivo", "2. Cooperación oficial", "6. Alineación con el CAD y los ODS"):
        assert esperado in titulos
    assert len(doc.inline_shapes) >= 12  # gráficos
