"""Descarga completa del sistema en Excel: todo lo registrado, en todos los estados."""
import io
from pathlib import Path

import pandas as pd

from calidad import reglas as R

RAIZ = Path(__file__).resolve().parents[1]
HOJAS = [("Base", "Aprobada"), ("Por revisar", "Por revisar"), ("Actor pendiente", "Actor pendiente de crear"),
         ("Descartadas", "Descartada")]


def _columnas():
    cols = (RAIZ / "config" / "columnas_airtable.txt").read_text(encoding="utf-8").splitlines()
    i = cols.index("Financiación") + 1 if "Financiación" in cols else len(cols)
    cols = cols[:i] + [R.CAMPO_TIPO_MONTO] + cols[i:]
    j = cols.index("Fecha Límite de Aplicación") if "Fecha Límite de Aplicación" in cols else len(cols)
    cols = cols[:j] + [R.CAMPO_APERTURA] + cols[j:]
    k = cols.index("Objetivos General y Específicos") + 1 if "Objetivos General y Específicos" in cols else len(cols)
    cols = cols[:k] + [R.CAMPO_REQUISITOS] + cols[k:]
    m = cols.index("Se sugiere para priorización") + 1 if "Se sugiere para priorización" in cols else len(cols)
    return cols[:m] + [R.CAMPO_MOTIVO_PRIORIZACION, R.CAMPO_SOLICITUD] + cols[m:]


def excel_completo(almacen):
    items = almacen.items()
    catalogo = almacen.catalogo()
    columnas = _columnas()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for hoja, estado in HOJAS:
            filas = []
            for i in (x for x in items if x["estado"] == estado):
                actor = catalogo.buscar(i["datos"].get("Nombre de la Fuente", ""))
                pend = i["meta"].get("pendientes", [])
                fila = {"ID": i["id"], "Estado": i["estado"], "Origen": i["origen"], "Fecha de ingreso": i["ingreso"],
                        "Revisado por": i.get("revisado_por", ""), "Observación": i.get("observacion", ""),
                        "Tipo de actor": actor.tipo if actor else "", "Estado del actor en CICLOPE": actor.estado_ciclope if actor else "",
                        "Errores de calidad pendientes": sum(1 for p in pend if p["nivel"] == "Error"),
                        "Alertas de calidad pendientes": sum(1 for p in pend if p["nivel"] == "Alerta")}
                fila.update({c: i["datos"].get(c, "") for c in columnas})
                filas.append(fila)
            df = pd.DataFrame(filas) if filas else pd.DataFrame(columns=["ID", "Estado"] + columnas)
            df.to_excel(w, sheet_name=hoja, index=False)
            ws = w.sheets[hoja]
            ws.freeze_panes = "C2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 22
        act = pd.DataFrame(catalogo.filas())
        if len(act):
            act = act[["nombre", "tipo", "caracter", "estado_ciclope", "alias", "pais", "web", "observaciones"]]
            act.columns = ["Actor", "Tipo de actor", "Carácter", "Estado en CICLOPE", "Alias", "País", "Sitio web", "Observaciones"]
        act.to_excel(w, sheet_name="Actores", index=False)
    return buf.getvalue()
