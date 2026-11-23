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
    vistos = [i["datos"] for i in existentes]
    base = [i["datos"] for i in existentes]
    items, resultado = [], []
    for reg in df.to_dict("records"):
        nombre = str(reg.get("Nombre de la Convocatoria", "")).strip()
        limpio = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in reg.items()}
        tipo, otro = R.buscar_duplicado(limpio, vistos, 95)
        if tipo in ("mismo_año", "nombre_mismo_año"):
            motivo = "Mismo enlace" if tipo == "mismo_año" else f"Nombre igual o casi igual a «{otro.get('Nombre de la Convocatoria', '')}»"
            resultado.append((nombre, "Ya estaba en el sistema", f"{motivo} ({R.describir_periodo(otro)})"))
            continue
        datos, cambios, pendientes = corregir(reg, catalogo, base, hoy)
        datos = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in datos.items()}
        estado = "Aprobada" if (revisada_en_airtable(reg) and not todo_a_revision) else "Por revisar"
        item = nuevo_item(datos, "Importación masiva desde Airtable", {"cambios": cambios, "pendientes": pendientes}, estado=estado)
        item["historial"] = [{"fecha": item["ingreso"], "usuario": "Importación", "accion": "Importada desde Airtable",
                              "detalle": f"{len(cambios)} correcciones automáticas"}]
        items.append(item)
        vistos.append(datos)
        resultado.append((nombre, "Agregada a la base" if estado == "Aprobada" else "Enviada a la bandeja de revisión",
                          f"{len(cambios)} correcciones automáticas, {len(pendientes)} pendientes"
                          + (f" · nueva edición (ya estaba la de {R.describir_periodo(otro)})" if tipo == "edicion_anterior" else "")))
    for a in nuevos_actores:
        almacen.guardar_actor(a)
    if items:
        almacen.guardar_items(items, f"Importación masiva: {len(items)} convocatorias")
    tabla = pd.DataFrame(resultado, columns=["Convocatoria", "Resultado", "Detalle"])
    return tabla, nuevos_actores


# --- actualizar desde un export nuevo de Airtable (sin borrar nada) ------------------------
_ACCIONES_DEL_SISTEMA = {"Ingreso", "Migrada desde Airtable", "Actualizada desde Airtable", "Importada desde Airtable"}


def editada_en_el_sistema(item):
    """True si alguien la editó, revisó, aprobó o descartó en este sistema (entonces Airtable no la pisa)."""
    return any(e.get("accion") not in _ACCIONES_DEL_SISTEMA for e in item.get("historial", []))


def _clave(nombre, registro):
    import unicodedata
    n = "".join(c for c in unicodedata.normalize("NFD", str(nombre or "").lower()) if unicodedata.category(c) != "Mn")
    n = " ".join("".join(ch if ch.isalnum() else " " for ch in n).split())
    f = R.fecha(registro)
    return f"{n}|{f.isoformat() if f else ''}"


def _filas_export(df_crudo):
    df = df_crudo[df_crudo["Nombre de la Convocatoria"].notna()].reset_index(drop=True)
    df = df[df["Nombre de la Convocatoria"].astype(str).str.strip() != ""].reset_index(drop=True)
    return df, df.to_dict("records")


def _emparejar(registros, items):
    """Para cada fila del export, la convocatoria del sistema que le corresponde (o None)."""
    from calidad.reglas import IndiceDuplicados
    por_clave = {}
    for i in items:
        d = i["datos"]
        por_clave.setdefault(_clave(d.get("Nombre de la Convocatoria"), d.get("Fecha de Registro")), i)
    indice, por_id = IndiceDuplicados(), {}
    for i in items:
        if i.get("estado") != "Descartada" or str(i.get("origen", "")).startswith(ORIGEN):
            indice.agregar(i["datos"])
            por_id[id(i["datos"])] = i
    pares = []  # (item, exacta): exacta = mismo nombre y misma fecha de registro (la misma fila de Airtable)
    for n, reg in enumerate(registros):
        clave = _clave(reg.get("Nombre de la Convocatoria"), reg.get("Fecha de Registro"))
        item = por_clave.get(clave)
        exacta = item is not None
        limpio = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in reg.items()}
        if item is None:
            tipo, otro = indice.buscar(limpio)
            if tipo in ("mismo_año", "nombre_mismo_año") and otro is not None:
                item = por_id.get(id(otro))
        if item is None:
            # nueva: se recuerda, para que una fila repetida más abajo en el mismo export no entre dos veces
            marca = {"id": f"{REPETIDA}{n}", "datos": limpio, "estado": "nueva"}
            por_clave.setdefault(clave, marca)
            indice.agregar(limpio)
            por_id[id(limpio)] = marca
        pares.append((item, exacta))
    return pares


REPETIDA = "repetida-en-el-export-"


def _repetida(item):
    return item is not None and str(item.get("id", "")).startswith(REPETIDA)


def revisar_actualizacion(df_crudo, almacen):
    """Vista previa, sin cambiar nada: cuántas filas del export son nuevas y cuántas ya están."""
    _, registros = _filas_export(df_crudo)
    pares = _emparejar(registros, almacen.items())
    nuevas = sum(1 for p, _ in pares if p is None)
    editadas = sum(1 for p, _ in pares if p is not None and not _repetida(p) and editada_en_el_sistema(p))
    parecidas = sum(1 for p, e in pares if p is not None and (_repetida(p) or not e and not editada_en_el_sistema(p)))
    return {"filas": len(registros), "nuevas": nuevas, "ya_estan": len(registros) - nuevas,
            "se_pueden_actualizar": len(registros) - nuevas - editadas - parecidas, "editadas_aqui": editadas,
            "iguales_a_otra": parecidas}


def actualizar(df_crudo, almacen, hoy=None, tipos_corregidos=None, todo_a_revision=False):
    """Trae lo último de un export de Airtable SIN borrar nada del sistema.

    - Convocatoria que no está: se agrega como en la migración (a la base si tenía las tres verificaciones; si no, a
      Revisar convocatorias), con las mismas correcciones automáticas.
    - Convocatoria que ya está y nadie ha tocado en este sistema: se actualiza con lo que cambió en Airtable.
    - Convocatoria que ya se editó, revisó, aprobó o descartó aquí: no se toca (manda lo del sistema).
    - Actores nuevos del export: se agregan al catálogo; los que ya existen no se modifican.
    Devuelve (resumen, tabla de detalle)."""
    from bandeja.almacen import ahora
    hoy = hoy or date.today()
    df, registros = _filas_export(df_crudo)
    items = almacen.items()
    pares = _emparejar(registros, items)
    catalogo = almacen.catalogo()
    del_export = construir_desde_base(df, tipos_corregidos)
    actores_nuevos = [a for a in del_export.actores.values()
                      if not any(catalogo.buscar(n) for n in [a.nombre] + list(a.alias))]
    for a in actores_nuevos:
        catalogo.agregar(a)
    cambiar, detalle = [], []
    res = {"filas": len(registros), "nuevas": 0, "a_la_base": 0, "a_revisar": 0, "actualizadas": 0,
           "sin_cambios": 0, "editadas_aqui": 0, "iguales_a_otra": 0, "actores_nuevos": len(actores_nuevos)}
    tocados = set()
    for n, (reg, (item, exacta)) in enumerate(zip(registros, pares)):
        datos, cambios, pendientes = corregir(reg, catalogo, [], hoy)
        datos = {k: ("" if (isinstance(v, float) and v != v) else v) for k, v in datos.items()}
        nombre = datos.get("Nombre de la Convocatoria", "")
        revisada = revisada_en_airtable(reg)
        if item is None:
            revisada = revisada and not todo_a_revision
            estado = "Aprobada" if revisada else "Por revisar"
            nuevo = nuevo_item(datos, ORIGEN if revisada else ORIGEN + " · revisión incompleta",
                               {"migracion": True, "cambios": cambios, "pendientes": pendientes}, estado=estado)
            f_reg = R.fecha(datos.get("Fecha de Registro"))
            nuevo["ingreso"] = f"{f_reg.isoformat()} 00:00" if f_reg else nuevo["ingreso"]
            nuevo["revisado_por"] = str(reg.get("Reportado por") or "")
            nuevo["historial"] = [{"fecha": ahora(), "usuario": "Migración", "accion": "Migrada desde Airtable",
                                   "detalle": "Agregada al actualizar desde un export nuevo de Airtable"}]
            cambiar.append(nuevo)
            res["nuevas"] += 1
            res["a_la_base" if revisada else "a_revisar"] += 1
            detalle.append({"Fila": n + 2, "Convocatoria": nombre, "Resultado": "Nueva: " + (
                "entra a la base" if revisada else "va a Revisar convocatorias (no tenía las tres verificaciones)")})
            continue
        if _repetida(item):
            res["iguales_a_otra"] += 1
            detalle.append({"Fila": n + 2, "Convocatoria": nombre,
                            "Resultado": "Repetida en este mismo export (otra fila es la misma convocatoria): no se agrega dos veces"})
            continue
        if not exacta or item["id"] in tocados:
            # otra fila con la misma convocatoria del mismo año (por ejemplo, el mismo enlace): no se duplica ni se
            # mezcla con la que ya está
            res["iguales_a_otra"] += 1
            detalle.append({"Fila": n + 2, "Convocatoria": nombre, "Resultado": "Ya está en el sistema como «"
                            + str(item["datos"].get("Nombre de la Convocatoria", ""))[:80] + "» (mismo año): no se agrega"})
            continue
        tocados.add(item["id"])
        if editada_en_el_sistema(item):
            res["editadas_aqui"] += 1
            detalle.append({"Fila": n + 2, "Convocatoria": nombre,
                            "Resultado": "Ya estaba y se editó en este sistema: no se toca"})
            continue
        distintos = [k for k, v in datos.items() if str(item["datos"].get(k, "") or "") != str(v or "")]
        pasa_a_base = revisada and item["estado"] == "Por revisar"
        if not distintos and not pasa_a_base:
            res["sin_cambios"] += 1
            continue
        item["datos"] = {**item["datos"], **{k: datos[k] for k in distintos}}
        item["meta"]["pendientes"] = pendientes
        if pasa_a_base:
            item["estado"] = "Aprobada"
            item["origen"] = ORIGEN
        item.setdefault("historial", []).append({"fecha": ahora(), "usuario": "Migración",
                                                 "accion": "Actualizada desde Airtable",
                                                 "detalle": "Campos: " + ", ".join(distintos)[:300]})
        cambiar.append(item)
        res["actualizadas"] += 1
        detalle.append({"Fila": n + 2, "Convocatoria": nombre, "Resultado": "Actualizada: " + ", ".join(distintos)[:200]
                        + ("; pasó a la base (ya tenía las tres verificaciones)" if pasa_a_base else "")})
    if actores_nuevos:
        almacen.reemplazar_catalogo(catalogo)
    if cambiar:
        almacen.guardar_items(cambiar, f"Actualización desde Airtable: {res['nuevas']} nuevas, "
                                       f"{res['actualizadas']} actualizadas")
    return res, pd.DataFrame(detalle, columns=["Fila", "Convocatoria", "Resultado"])
