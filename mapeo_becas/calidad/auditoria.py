"""Auditoría de la base actual: qué está mal, en qué registro y cómo corregirlo."""
from collections import Counter
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from calidad import reglas as R
from calidad.actores import TIPOS_OFICIALES, construir_desde_base

NAVY = "0B2545"
COLOR_NIVEL = {"Error": "FBE4E1", "Alerta": "FFF4CC", "Corregido": "DDF1EC"}
QUE_HACER = {
    "R01": "Marcar la verificación solo después de revisar la página oficial.",
    "R02": "Completar el campo en Airtable.",
    "R03": "Reemplazar por el valor sugerido de la lista.",
    "R04": "Dejar solo las 3 temáticas principales.",
    "R05": "Asignar el actor; si no existe, crearlo en CICLOPE.",
    "R06": "Agregar el actor al catálogo o corregir el nombre.",
    "R07": "Solicitar la creación del actor en CICLOPE.",
    "R08": "Usar el carácter que corresponde al tipo de actor.",
    "R09": "Corregir la fecha o el campo 'permanente'.",
    "R10": "Se corrige solo con las fechas.",
    "R11": "Reemplazar por el enlace oficial del oferente.",
    "R12": "Escribir el correo o 'Sin Email'.",
    "R13": "Indicar si el monto es por beneficiario/proyecto o el presupuesto total.",
    "R14": "Escribir el nombre en español y el original entre paréntesis.",
    "R15": "Ampliar la descripción.",
    "R16": "Revisar si es la misma convocatoria y eliminar el duplicado.",
}


def _hoja(ws, df, anchos=None, color_col=None):
    ws.append(list(df.columns))
    for fila in df.itertuples(index=False):
        ws.append(["" if (isinstance(v, float) and v != v) else v for v in fila])
    for i, c in enumerate(df.columns, 1):
        cel = ws.cell(row=1, column=i)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor=NAVY)
        cel.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = (anchos or {}).get(c, 18)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 34
    if color_col and color_col in df.columns:
        j = list(df.columns).index(color_col) + 1
        for r in range(2, ws.max_row + 1):
            v = ws.cell(row=r, column=j).value
            if v in COLOR_NIVEL:
                ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=COLOR_NIVEL[v])
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def auditar(df_crudo, tipos_corregidos=None, hoy=None):
    df = df_crudo[df_crudo["Nombre de la Convocatoria"].notna()].reset_index(drop=True)
    catalogo = construir_desde_base(df, tipos_corregidos)
    registros = df.to_dict("records")
    hallazgos, cambios = [], []
    for i, reg in enumerate(registros):
        norm, hs = R.validar(reg, catalogo, registros, hoy=hoy, nuevo=False)
        for h in hs:
            # El estado del actor se revisa en el catálogo, no convocatoria por convocatoria
            if h.regla == "R07":
                continue
            hallazgos.append({"Fila en el export": i + 2, "Convocatoria": reg["Nombre de la Convocatoria"],
                              "Campo": h.campo, "Nivel": h.nivel, "Regla": h.regla, "Problema": h.problema,
                              "Valor actual": h.valor, "Valor sugerido": h.sugerencia, "Decisión": ""})
        actual = str(reg.get("Oficial / No Oficial") or "").strip()
        if norm.get("Oficial / No Oficial") and actual != norm["Oficial / No Oficial"]:
            actor = catalogo.buscar(norm["Nombre de la Fuente"])
            cambios.append({"Fila en el export": i + 2, "Convocatoria": reg["Nombre de la Convocatoria"],
                            "Actor": norm["Nombre de la Fuente"], "Tipo de actor": actor.tipo if actor else "",
                            "Carácter actual": actual, "Carácter según el actor": norm["Oficial / No Oficial"]})
    return catalogo, pd.DataFrame(hallazgos), pd.DataFrame(cambios), df


def escribir(ruta, catalogo, hallazgos, cambios, df):
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    n = len(df)
    ws.append(["Auditoría de calidad de la base de convocatorias"])
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws.append([f"{n} convocatorias revisadas · {hallazgos['Fila en el export'].nunique() if len(hallazgos) else 0} con al menos un hallazgo"])
    ws.append([])
    filas = []
    for regla, desc in R.REGLAS.items():
        sub = hallazgos[hallazgos["Regla"] == regla] if len(hallazgos) else hallazgos
        if regla == "R07":
            pend = sum(1 for a in catalogo.actores.values() if a.estado_ciclope != "Creado en CICLOPE")
            filas.append([regla, desc, "Ver hoja Actores", pend, "actores sin confirmar en CICLOPE", QUE_HACER[regla]])
            continue
        if len(sub):
            niveles = Counter(sub["Nivel"])
            filas.append([regla, desc, ", ".join(f"{k}: {v}" for k, v in niveles.items()), sub["Fila en el export"].nunique(),
                          f"{100 * sub['Fila en el export'].nunique() / n:.0f} % de la base", QUE_HACER[regla]])
    res = pd.DataFrame(filas, columns=["Regla", "Qué se revisa", "Hallazgos por nivel", "Convocatorias afectadas", "Proporción", "Qué hacer"])
    inicio = ws.max_row + 1
    for i, c in enumerate(res.columns, 1):
        cel = ws.cell(row=inicio, column=i, value=c)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor=NAVY)
    for fila in res.itertuples(index=False):
        ws.append(list(fila))
    for col, ancho in zip("ABCDEF", (8, 46, 30, 14, 26, 60)):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=inicio + 1):
        for c in fila:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.append([])
    ws.append(["Niveles: Error = debe corregirse; Alerta = revisar; Corregido = el sistema ya lo arregla solo con la regla nueva."])

    ws = wb.create_sheet("Hallazgos")
    _hoja(ws, hallazgos, {"Convocatoria": 45, "Campo": 26, "Problema": 45, "Valor actual": 40, "Valor sugerido": 40,
                          "Fila en el export": 10, "Nivel": 11, "Regla": 7, "Decisión": 12}, color_col="Nivel")
    dv = DataValidation(type="list", formula1='"Aplicar sugerencia,Corregir a mano,Dejar igual"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"I2:I{len(hallazgos) + 2}")

    ws = wb.create_sheet("Cambios de carácter")
    _hoja(ws, cambios if len(cambios) else pd.DataFrame(columns=["Sin cambios"]),
          {"Convocatoria": 45, "Actor": 40, "Tipo de actor": 26})

    ws = wb.create_sheet("Actores")
    act = pd.DataFrame(catalogo.filas())
    conteo = Counter(R.limpiar_nombre(x) for x in df["Nombre de la Fuente"].fillna(""))
    act = act.rename(columns={"nombre": "Nombre (como en CICLOPE)", "tipo": "Tipo de actor", "caracter": "Carácter",
                              "estado_ciclope": "Estado en CICLOPE", "pais": "País", "web": "Sitio web",
                              "alias": "Otras formas en la base", "observaciones": "Observaciones"})
    act = act[["Nombre (como en CICLOPE)", "Tipo de actor", "Carácter", "Estado en CICLOPE", "Otras formas en la base",
               "País", "Sitio web", "Observaciones"]]
    _hoja(ws, act, {"Nombre (como en CICLOPE)": 55, "Tipo de actor": 26, "Estado en CICLOPE": 20,
                    "Otras formas en la base": 45, "Sitio web": 35, "Observaciones": 30})
    from analitica.datos import TIPOS
    dv1 = DataValidation(type="list", formula1='"' + ",".join(TIPOS) + '"', allow_blank=True)
    dv2 = DataValidation(type="list", formula1='"Creado en CICLOPE,Pendiente de crear,Por confirmar"', allow_blank=True)
    ws.add_data_validation(dv1)
    ws.add_data_validation(dv2)
    dv1.add(f"B2:B{len(act) + 300}")
    dv2.add(f"D2:D{len(act) + 300}")
    del conteo

    ws = wb.create_sheet("Reglas")
    _hoja(ws, pd.DataFrame([(k, v, QUE_HACER[k]) for k, v in R.REGLAS.items()], columns=["Regla", "Qué se revisa", "Qué hacer"]),
          {"Qué se revisa": 50, "Qué hacer": 70})
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta


def exportar_actores_csv(catalogo, ruta):
    """CSV para crear la tabla 'Actores' en Airtable."""
    filas = [{"Nombre": a.nombre, "Tipo de actor": a.tipo, "Carácter": a.caracter, "Estado en CICLOPE": a.estado_ciclope,
              "Alias": "; ".join(a.alias), "País": a.pais, "Sitio web": a.web} for a in catalogo.actores.values()]
    pd.DataFrame(filas).sort_values("Nombre").to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


__all__ = ["auditar", "escribir", "exportar_actores_csv", "TIPOS_OFICIALES"]
