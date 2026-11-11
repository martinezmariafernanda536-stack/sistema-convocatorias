"""Migración desde el export de Airtable a la base propia, con las correcciones automáticas.

Se corrige solo lo que no admite duda; lo demás queda como 'pendiente de calidad' en cada
convocatoria, visible en la página 'Base y calidad' para corregirlo en la aplicación.
"""
from datetime import date

import pandas as pd

from bandeja.almacen import nuevo_item
from calidad import reglas as R
from calidad.actores import construir_desde_base

ORIGEN = "Migración desde Airtable"
VERIFICACIONES_AIRTABLE = ["VERIFICACIÓN: Colombia hace parte de los países beneficiarios",
                           "VERIFICACIÓN: Página web correcta y activa",
                           "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria"]


def revisada_en_airtable(reg):
    """Se considera revisada si tenía marcadas las tres verificaciones del formulario anterior."""
    return all(R.marcado(reg.get(c, "")) for c in VERIFICACIONES_AIRTABLE)


def _pendientes(hallazgos):
    return [h.__dict__ for h in hallazgos if h.nivel in ("Error", "Alerta") and h.regla != "R07"]


def corregir(reg, catalogo, base, hoy):
    """Devuelve (datos corregidos, cambios aplicados, pendientes)."""
    base = [b for b in base if b is not reg]
    norm, hs = R.validar(reg, catalogo, base, hoy=hoy, nuevo=False)
    cambios = [{"campo": h.campo, "antes": h.valor, "despues": h.sugerencia, "regla": h.regla, "motivo": h.problema}
               for h in hs if h.nivel == "Corregido"]

    def cambiar(campo, nuevo, regla, motivo):
        antes = norm.get(campo, "")
        if str(antes) != str(nuevo):
            cambios.append({"campo": campo, "antes": antes, "despues": nuevo, "regla": regla, "motivo": motivo})
            norm[campo] = nuevo

    for h in hs:
        # enlaces con error de escritura evidente (https// → https://)
        if h.regla == "R11" and h.sugerencia and h.campo in ("Link de la Fuente Oferente", "Cómo aplicar"):
            cambiar(h.campo, h.sugerencia, "R11", "Enlace corregido")
        # un enlace en el campo de correo: el enlace ya está en 'Cómo aplicar'
        if h.regla == "R12" and str(h.valor).lower().startswith("http"):
            cambiar("Email para mayor información", "Sin Email", "R12", "Había un enlace en lugar de un correo")
    # observación de fecha vacía: se deriva de la fecha o de 'permanente'
    if not str(norm.get("Observaciones a la fecha límite de aplicación", "")).strip():
        if norm.get("¿La convocatoria es permanente?") == "Si":
            cambiar("Observaciones a la fecha límite de aplicación", "Convocatoria permanente", "R02", "Derivado de 'permanente'")
        elif norm.get("Fecha Límite de Aplicación"):
            cambiar("Observaciones a la fecha límite de aplicación", f"Cierre el {norm['Fecha Límite de Aplicación']}", "R02",
                    "Derivado de la fecha límite")
    # correo: vacío = 'Sin Email'; texto con correos = solo los correos válidos
    correo = str(norm.get("Email para mayor información", "")).strip()
    if not correo:
        cambiar("Email para mayor información", "Sin Email", "R12", "Correo vacío")
    elif correo != "Sin Email" and not correo.lower().startswith("http"):
        import re
        hallados = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", correo)
        validos = list(dict.fromkeys(h.lower().strip(".") for h in hallados))
        if validos and "; ".join(validos) != correo:
            cambiar("Email para mayor información", "; ".join(validos), "R12", "Se dejaron solo los correos válidos")
    if R.monto(norm.get("Financiación")) is not None and norm.get(R.CAMPO_TIPO_MONTO) not in R.TIPOS_MONTO:
        cambiar(R.CAMPO_TIPO_MONTO, "No especificado", "R13", "Campo nuevo; la base anterior no lo tenía")
    _, hs2 = R.validar(norm, catalogo, base, hoy=hoy, nuevo=False)
    return norm, cambios, _pendientes(hs2)


def migrar(df_crudo, almacen, tipos_corregidos=None, hoy=None, reemplazar=False):
    hoy = hoy or date.today()
    df = df_crudo[df_crudo["Nombre de la Convocatoria"].notna()].reset_index(drop=True)
    existentes = almacen.items()
    if existentes and not reemplazar:
        raise RuntimeError(f"La base ya tiene {len(existentes)} convocatorias. Usa --reemplazar para volver a migrar.")
    catalogo = construir_desde_base(df, tipos_corregidos)
    registros = df.to_dict("records")
    items, filas_cambios, filas_pend = [], [], []
    for i, reg in enumerate(registros):
        datos, cambios, pendientes = corregir(reg, catalogo, registros, hoy)
        datos = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in datos.items()}
        f_reg = R.fecha(datos.get("Fecha de Registro"))
        estado = "Aprobada" if revisada_en_airtable(reg) else "Por revisar"
        item = nuevo_item(datos, ORIGEN if estado == "Aprobada" else ORIGEN + " · revisión incompleta",
                          {"migracion": True, "cambios": cambios, "pendientes": pendientes}, estado=estado)
        item["ingreso"] = f"{f_reg.isoformat()} 00:00" if f_reg else item["ingreso"]
        item["revisado_por"] = str(reg.get("Reportado por") or "")
        item["historial"] = [{"fecha": item["ingreso"], "usuario": "Migración", "accion": "Migrada desde Airtable",
                              "detalle": f"{len(cambios)} correcciones automáticas, {len(pendientes)} pendientes"
                                         + ("" if estado == "Aprobada" else "; sin las tres verificaciones: va a la bandeja")}]
        items.append(item)
        for c in cambios:
            filas_cambios.append({"Fila en el export": i + 2, "Convocatoria": datos.get("Nombre de la Convocatoria"),
                                  "Destino": "Base" if estado == "Aprobada" else "Bandeja de revisión", **c})
        for p in pendientes:
            filas_pend.append({"Fila en el export": i + 2, "Convocatoria": datos.get("Nombre de la Convocatoria"),
                               "Destino": "Base" if estado == "Aprobada" else "Bandeja de revisión",
                               "Campo": p["campo"], "Nivel": p["nivel"], "Regla": p["regla"], "Problema": p["problema"],
                               "Valor actual": p["valor"], "Sugerencia": p["sugerencia"]})
    if reemplazar:
        _vaciar(almacen)
    almacen.reemplazar_catalogo(catalogo)
    almacen.guardar_items(items, f"Migración desde Airtable: {len(items)} convocatorias")
    return catalogo, items, pd.DataFrame(filas_cambios), pd.DataFrame(filas_pend)


def _vaciar(almacen):
    def op(con):
        con.execute("DELETE FROM convocatorias")
        con.execute("DELETE FROM actores")
    almacen._escribir(op, "Vaciar antes de migrar")


def reporte(ruta, catalogo, items, cambios, pendientes):
    from calidad.auditoria import _hoja
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    con_pend = sum(1 for i in items if i["meta"]["pendientes"])
    filas = [
        ("Convocatorias migradas", len(items)),
        ("  · a la base (revisadas en Airtable: las tres verificaciones)", sum(1 for i in items if i["estado"] == "Aprobada")),
        ("  · a la bandeja de revisión (les faltaba alguna verificación)", sum(1 for i in items if i["estado"] == "Por revisar")),
        ("Actores en el catálogo", len(catalogo)),
        ("Correcciones automáticas aplicadas", len(cambios)),
        ("Convocatorias con pendientes de calidad", con_pend),
        ("Pendientes (errores y alertas)", len(pendientes)),
    ]
    ws.append(["Migración y corrección de la base de convocatorias"])
    ws["A1"].font = Font(bold=True, size=14, color="0B2545")
    ws.append([])
    for f in filas:
        ws.append(list(f))
    ws.column_dimensions["A"].width = 66
    ws.append([])
    ws.append(["Los pendientes de la base se corrigen en la página 'Base y calidad'; las de la bandeja, al revisarlas."])
    if len(cambios):
        resumen = cambios.groupby(["regla", "motivo"]).size().reset_index(name="Correcciones")
        ws.append([])
        ws.append(["Correcciones automáticas por tipo"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        for r in resumen.itertuples(index=False):
            ws.append([f"{r.regla} · {r.motivo}", r.Correcciones])
    _hoja(wb.create_sheet("Correcciones aplicadas"),
          cambios.rename(columns={"campo": "Campo", "antes": "Antes", "despues": "Después", "regla": "Regla", "motivo": "Motivo"})
          if len(cambios) else pd.DataFrame(columns=["Sin correcciones"]),
          {"Convocatoria": 45, "Campo": 26, "Antes": 40, "Después": 40, "Motivo": 40})
    _hoja(wb.create_sheet("Pendientes"), pendientes if len(pendientes) else pd.DataFrame(columns=["Sin pendientes"]),
          {"Convocatoria": 45, "Campo": 26, "Problema": 45, "Valor actual": 40, "Sugerencia": 35}, color_col="Nivel")
    act = pd.DataFrame(catalogo.filas())[["nombre", "tipo", "caracter", "estado_ciclope", "alias", "web"]]
    act.columns = ["Actor", "Tipo de actor", "Carácter", "Estado en CICLOPE", "Otras formas en la base", "Sitio web"]
    _hoja(wb.create_sheet("Actores"), act, {"Actor": 55, "Tipo de actor": 26, "Otras formas en la base": 45, "Sitio web": 35})
    wb.save(ruta)
    return ruta


# ---------------------------------------------------------------------------
# Importación masiva posterior (otro export de Airtable)
# ---------------------------------------------------------------------------
def importar(df_crudo, almacen, hoy=None, todo_a_revision=False):
    """Agrega las convocatorias de un export de Airtable que aún no estén en el sistema.

    - Se comparan con todas las del sistema (base, bandeja y descartadas) por enlace y por nombre.
    - Las nuevas se corrigen igual que en la migración; si tenían las tres verificaciones van a la
      base, si no, a la bandeja (o todas a la bandeja con todo_a_revision=True).
    - Los actores nuevos se agregan al catálogo.
    Devuelve una tabla con el resultado de cada fila.
    """
    hoy = hoy or date.today()
    df = df_crudo[df_crudo["Nombre de la Convocatoria"].notna()].reset_index(drop=True)
    catalogo = almacen.catalogo()
    nuevos_actores = []
    for a in construir_desde_base(df).actores.values():
        if not any(catalogo.buscar(n) for n in [a.nombre] + a.alias):
            catalogo.agregar(a)
            nuevos_actores.append(a)
    existentes = almacen.items()
    urls = {str(i["datos"].get("Cómo aplicar", "")).rstrip("/").lower() for i in existentes} - {""}
    nombres = [i["datos"].get("Nombre de la Convocatoria", "") for i in existentes]
    base = [i["datos"] for i in existentes]
    items, resultado = [], []
    for reg in df.to_dict("records"):
        nombre = str(reg.get("Nombre de la Convocatoria", "")).strip()
        url = str(reg.get("Cómo aplicar") or "").strip().rstrip("/").lower()
        if url.startswith("http") and url in urls:
            resultado.append((nombre, "Ya estaba en el sistema", "Mismo enlace"))
            continue
        parecido = next((n for n in nombres if R.similitud(nombre, n) >= 95), None)
        if parecido:
            resultado.append((nombre, "Ya estaba en el sistema", f"Nombre igual o casi igual a «{parecido}»"))
            continue
        datos, cambios, pendientes = corregir(reg, catalogo, base, hoy)
        datos = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in datos.items()}
        estado = "Aprobada" if (revisada_en_airtable(reg) and not todo_a_revision) else "Por revisar"
        item = nuevo_item(datos, "Importación masiva desde Airtable", {"cambios": cambios, "pendientes": pendientes}, estado=estado)
        item["historial"] = [{"fecha": item["ingreso"], "usuario": "Importación", "accion": "Importada desde Airtable",
                              "detalle": f"{len(cambios)} correcciones automáticas"}]
        items.append(item)
        urls.add(url)
        nombres.append(nombre)
        resultado.append((nombre, "Agregada a la base" if estado == "Aprobada" else "Enviada a la bandeja de revisión",
                          f"{len(cambios)} correcciones automáticas, {len(pendientes)} pendientes"))
    for a in nuevos_actores:
        almacen.guardar_actor(a)
    if items:
        almacen.guardar_items(items, f"Importación masiva: {len(items)} convocatorias")
    tabla = pd.DataFrame(resultado, columns=["Convocatoria", "Resultado", "Detalle"])
    return tabla, nuevos_actores
