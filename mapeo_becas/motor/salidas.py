"""Construye las filas con las columnas de Airtable y escribe los Excel de revisión y carga."""
import csv
import io
from datetime import date, datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import reglas

COLUMNAS_SISTEMA = [
    "Decisión", "[Sistema] Estado", "[Sistema] Elegibilidad Colombia", "[Sistema] Motivo elegibilidad",
    "[Sistema] ¿Está en ICETEX?", "[Sistema] Motivo ICETEX", "[Sistema] Duplicado en Airtable", "[Sistema] Nivel",
    "[Sistema] Alerta de cierre", "[Sistema] Motivo modalidad", "[Sistema] Fuente ID", "[Sistema] Tipo de fuente", "[Sistema] País de la fuente",
    "[Sistema] Página donde se encontró",
]
MULTISELECCION = ["Dirigida a (tipo de publico)", "Esta convocatoria prioriza alguna de las siguientes poblaciones?",
                  "Áreas temáticas de interés", "Idioma/s", "Alineación al SNCIC Intersectorial"]
CASILLAS = ["¿Se puede publicar en la web?", "Tiempo de vencimiento es mayor a un mes y una semana",
            "Se sugiere para priorización", "Convocatoria Priorizada",
            "VERIFICACIÓN: Colombia hace parte de los países beneficiarios",
            "VERIFICACIÓN: Página web correcta y activa",
            "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria", "VERIFICACIÓN: Publicada"]
FECHAS = ["Fecha de Registro", "Fecha Límite de Aplicación", "Fecha Facebook Live"]

AZUL, VERDE, AMARILLO, ROJO, GRIS = "0B2545", "DDF1EC", "FFF4CC", "FBE4E1", "EDF1F6"


def _f(d):
    return f"{d.day}/{d.month}/{d.year}" if d else ""


def _multi(valores):
    """Formato de Airtable: valores separados por coma; entre comillas si llevan coma."""
    buf = io.StringIO()
    csv.writer(buf).writerow(list(dict.fromkeys(valores)))
    return buf.getvalue().strip()


def fila_airtable(datos, url, fuente, pagina, cfg, elig, icetex, duplicado, hoy):
    resultado, _, motivo = elig
    en_icetex, motivo_icetex = icetex
    dias = (datos["cierre"] - hoy).days if datos["cierre"] else None
    minimo = int(cfg.p("Días mínimos antes del cierre", 15))
    alin = reglas.alineacion(datos["temas"], cfg, datos.get("modalidad", "Beca"))
    obs_monto = " | ".join(datos["frases_monto"])
    if datos["cobertura"]:
        obs_monto = (obs_monto + " | " if obs_monto else "") + "Cubre: " + ", ".join(datos["cobertura"])
    if datos["frases_monto"] and not datos["monto_usd"]:
        obs_monto += " (monto en otra moneda: convertir a USD al revisar)"
    completa = bool(datos["titulo"] and datos["descripcion"] and (datos["cierre"] or datos["permanente"]))

    fila = {c: "" for c in COLUMNAS_SISTEMA + cfg.columnas_airtable}
    fila.update({
        "[Sistema] Elegibilidad Colombia": resultado,
        "[Sistema] Motivo elegibilidad": motivo,
        "[Sistema] ¿Está en ICETEX?": "Sí" if en_icetex else "No",
        "[Sistema] Motivo ICETEX": motivo_icetex,
        "[Sistema] Duplicado en Airtable": duplicado,
        "[Sistema] Nivel": ", ".join(datos["niveles"]),
        "[Sistema] Alerta de cierre": ("Cierre muy próximo" if dias is not None and dias < minimo else
                                       "Sin fecha detectada" if dias is None and not datos["permanente"] else ""),
        "[Sistema] Motivo modalidad": datos.get("motivo_modalidad", ""),
        "[Sistema] Fuente ID": fuente.id,
        "[Sistema] Tipo de fuente": fuente.tipo,
        "[Sistema] País de la fuente": fuente.pais,
        "[Sistema] Página donde se encontró": pagina,
        "Nombre de la Convocatoria": datos["titulo"],
        "Modalidad": datos.get("modalidad", "Beca"),
        "Fecha de Registro": _f(hoy),
        "Reportado por": cfg.p("Reportado por", "Mapeo automático"),
        "Oficial / No Oficial": fuente.oficial,
        "¿La convocatoria es permanente?": "Si" if datos["permanente"] else "No",
        "Fecha Límite de Aplicación": _f(datos["cierre"]),
        "Nombre de la Fuente": fuente.actor or fuente.nombre,
        "Nombre de actor en CICLOPE": fuente.actor or fuente.nombre,
        "Descripción": datos["descripcion"],
        "Dirigida a (tipo de publico)": _multi(datos["publico"]),
        "Esta convocatoria prioriza alguna de las siguientes poblaciones?": _multi(datos["poblaciones"]) if datos["poblaciones"] else "",
        "Áreas temáticas de interés": _multi(datos["temas"]),
        "Financiación": f"${datos['monto_usd']:.2f}" if datos["monto_usd"] else "",
        "Observaciones sobre el financiamiento": obs_monto,
        "Ámbito Geográfico": reglas.ambito(datos["texto_norm"]),
        "Cómo aplicar": url,
        "Idioma/s": _multi(datos["idiomas"]),
        "Observaciones a la fecha límite de aplicación": ("Convocatoria permanente" if datos["permanente"] else datos["evidencia_cierre"]),
        "Tiempo de vencimiento es mayor a un mes y una semana": "checked" if dias is not None and dias > 37 else "",
        "Email para mayor información": datos["correo"],
        "Link de la Fuente Oferente": fuente.dominio,
        "VERIFICACIÓN: Colombia hace parte de los países beneficiarios": "checked" if resultado == "Elegible" else "",
        "VERIFICACIÓN: Página web correcta y activa": "checked",
        "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria": "checked" if completa else "",
    })
    for campo, valor in alin.items():
        if campo in fila:
            fila[campo] = valor
    return fila


def fila_pdf(url, texto_enlace, fuente, pagina, cfg, hoy):
    modalidad, motivo = reglas.detectar_modalidad(texto_enlace, url, "", cfg, fuente.modalidades)
    fila = {c: "" for c in COLUMNAS_SISTEMA + cfg.columnas_airtable}
    fila.update({
        "[Sistema] Elegibilidad Colombia": "Revisar", "[Sistema] Motivo elegibilidad": "Documento PDF: revisar a mano",
        "[Sistema] ¿Está en ICETEX?": "Revisar", "[Sistema] Fuente ID": fuente.id, "[Sistema] Tipo de fuente": fuente.tipo,
        "[Sistema] País de la fuente": fuente.pais, "[Sistema] Página donde se encontró": pagina,
        "[Sistema] Motivo modalidad": motivo,
        "Nombre de la Convocatoria": texto_enlace, "Modalidad": modalidad, "Fecha de Registro": _f(hoy),
        "Reportado por": cfg.p("Reportado por", "Mapeo automático"), "Oficial / No Oficial": fuente.oficial,
        "Nombre de la Fuente": fuente.actor or fuente.nombre, "Nombre de actor en CICLOPE": fuente.actor or fuente.nombre,
        "Cómo aplicar": url,
        "Link de la Fuente Oferente": fuente.dominio,
    })
    return fila


# --- Excel de revisión -------------------------------------------------------
def _hoja(ws, df, anchos=None, colorear=True):
    ws.append(list(df.columns))
    for fila in df.itertuples(index=False):
        ws.append(list(fila))
    for i, c in enumerate(df.columns, 1):
        cel = ws.cell(row=1, column=i)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor=AZUL if not str(c).startswith(("[Sistema]", "Decisión")) else "2A4F87")
        cel.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = (anchos or {}).get(c, 18 if len(str(c)) < 25 else 28)
    ws.row_dimensions[1].height = 45
    ws.freeze_panes = "C2"
    if colorear and "[Sistema] Elegibilidad Colombia" in df.columns:
        col = list(df.columns).index("[Sistema] Elegibilidad Colombia") + 1
        for r in range(2, ws.max_row + 1):
            v = ws.cell(row=r, column=col).value
            color = {"Elegible": VERDE, "Probable": AMARILLO, "Revisar": GRIS, "No elegible": ROJO}.get(v)
            if color:
                ws.cell(row=r, column=col).fill = PatternFill("solid", fgColor=color)
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.alignment = Alignment(vertical="top", wrap_text=False)


def escribir_revision(ruta, filas, descartadas, resumen_fuentes, retiradas):
    orden = {"Elegible": 0, "Probable": 1, "Revisar": 2, "No elegible": 3}
    df = pd.DataFrame(filas)
    if not df.empty:
        df["_orden"] = df["[Sistema] Elegibilidad Colombia"].map(orden).fillna(5)
        df = df.sort_values(["_orden", "[Sistema] Fuente ID"]).drop(columns="_orden")
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Revisión"
    anchos = {"Decisión": 12, "Nombre de la Convocatoria": 45, "Descripción": 50, "[Sistema] Motivo elegibilidad": 40,
              "[Sistema] Motivo ICETEX": 30, "Cómo aplicar": 45}
    columnas = list(pd.DataFrame(filas).columns) if filas else COLUMNAS_SISTEMA
    _hoja(ws, df if not df.empty else pd.DataFrame(columns=columnas), anchos)
    dv = DataValidation(type="list", formula1='"Aprobar,Descartar,Revisar"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"A2:A{max(ws.max_row, 2) + 500}")

    ws2 = wb.create_sheet("Descartadas automáticamente")
    dfd = pd.DataFrame(descartadas, columns=["Motivo", "Nombre", "URL", "Fuente ID"])
    _hoja(ws2, dfd, {"Motivo": 45, "Nombre": 50, "URL": 60}, colorear=False)

    ws3 = wb.create_sheet("Resultado por fuente")
    dff = pd.DataFrame(resumen_fuentes, columns=["Fuente ID", "Fuente", "Tipo", "Páginas revisadas", "Becas analizadas",
                                                 "Para revisión", "Descartadas", "Nota"])
    _hoja(ws3, dff, {"Fuente": 45, "Nota": 70}, colorear=False)

    ws4 = wb.create_sheet("Ya no aparecen")
    dfr = pd.DataFrame(retiradas, columns=["URL", "Fuente ID", "Nombre", "Vista por última vez"])
    _hoja(ws4, dfr, {"URL": 60, "Nombre": 50}, colorear=False)
    wb.save(ruta)


# --- Exportar aprobadas -------------------------------------------------------
def leer_aprobadas(ruta_revision, columnas_airtable):
    df = pd.read_excel(ruta_revision, sheet_name="Revisión", dtype=str).fillna("")
    aprobadas = df[df["Decisión"].str.strip().str.lower() == "aprobar"]
    return aprobadas[[c for c in columnas_airtable if c in aprobadas.columns]]


def a_registro_airtable(fila):
    """Convierte una fila del Excel en campos para la API de Airtable."""
    campos = {}
    for col, valor in fila.items():
        valor = str(valor).strip()
        if not valor:
            continue
        if col in CASILLAS:
            campos[col] = valor.lower() in ("checked", "sí", "si", "true", "1")
        elif col in MULTISELECCION:
            campos[col] = [v.strip() for v in next(csv.reader(io.StringIO(valor), skipinitialspace=True)) if v.strip()]
        elif col in FECHAS:
            try:
                campos[col] = datetime.strptime(valor, "%d/%m/%Y").date().isoformat()
            except ValueError:
                campos[col] = valor
        elif col == "Financiación":
            try:
                campos[col] = float(valor.replace("$", "").replace(",", ""))
            except ValueError:
                pass
        else:
            campos[col] = valor
    return campos
