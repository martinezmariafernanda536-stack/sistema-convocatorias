"""Prepara el export de Airtable para el dashboard y los informes.

- Nombre del actor: 'Nombre de la Fuente' o, si dice *NUEVO, 'Nombre de actor en CICLOPE'.
- Tipo de actor: tabla editable config/tipos_actor.xlsx. Lo que no está en la tabla
  se clasifica con reglas por palabras del nombre y queda marcado como 'sugerido'.
"""
import csv
import io
import re
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RUTA_TIPOS = RAIZ / "config" / "tipos_actor.xlsx"

TIPOS = ["Gobierno / agencia bilateral", "Organismo multilateral", "Fundación / filantropía",
         "ONG / sociedad civil", "Academia / investigación", "Empresa privada", "Por clasificar"]
PRIVADOS = ["Fundación / filantropía", "ONG / sociedad civil", "Empresa privada", "Academia / investigación"]

MULTI = ["Dirigida a (tipo de publico)", "Esta convocatoria prioriza alguna de las siguientes poblaciones?",
         "Áreas temáticas de interés", "Idioma/s"]

# Reglas por palabras del nombre, en orden: la primera que coincide manda.
REGLAS = [
    ("Organismo multilateral", ["naciones unidas", "onu ", "onu-", "unesco", "unicef", "fao ", "fao -", "pnud", "undp", "pnuma",
                                "mptf", "oacnudh", "union europea", "comision europea", "banco interamericano", " bid",
                                "banco de desarrollo de america latina", "caf", "oei ", "oei -", "iila", "pifcss", "segib",
                                "iberescena", "fondo de adaptacion", "adaptation fund", "gef", "global environment facility",
                                "common fund for commodities", "fontagro", "banco mundial", "world bank", "fida", "ifad",
                                "oim", "oit", "ops", "oms", "habitat", "programa iberoamericano"]),
    ("Gobierno / agencia bilateral", ["agencia", "embajada", "gobierno", "ministerio", "aecid", "koica", "giz", "jica",
                                      "usaid", "aics", "seco", "camoes", "global affairs", "british council", "mext",
                                      "fulbright", "france volontaires", "international climate initiative", "iki",
                                      "coalar", "goethe", "innovation norway", "reino unido", "irlanda", "cncdh",
                                      "comision nacional consultiva", "icip", "instituto catalan", "secretaria de estado",
                                      "innovate uk", "zayed"]),
    ("Fundación / filantropía", ["fundacion", "foundation", "stiftung", "wellcome", "trust", "philanthrop", "endowment",
                                 "earthshot", "fund for innovation in development"]),
    ("Academia / investigación", ["universidad", "university", "universiteit", "universite", "academia", "academy",
                                  "instituto tecnologico", "sciences po", "estudios politicos", "asociacion universitaria",
                                  "auip", "fapesp", "research", "investigacion"]),
    ("ONG / sociedad civil", ["mercy corps", "wwf", "red ", "network", "iucn", "forum", "foro", "people powered", "asociacion",
                              "association", "society", "collective", "comite", "committee", "justice fund", "earthna",
                              "ejn", "sociedad", "operadores turisticos", "ciudadania", "d-prize"]),
    ("Empresa privada", [" s.a", " inc", " ltd", "gmbh", "credit", "roche", "cartier", "ifdesign", "honeycomb"]),
]


def norm(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"\s+", " ", t.lower()).strip() + " "


def tipo_por_reglas(nombre):
    n = norm(nombre)
    for tipo, claves in REGLAS:
        for c in claves:
            c = c.strip()
            if c and re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", n):
                return tipo, f"Regla: «{c}»"
    return "Por clasificar", "Sin regla"


def dividir(v):
    if pd.isna(v) or not str(v).strip():
        return []
    return [x.strip() for x in next(csv.reader(io.StringIO(str(v)), skipinitialspace=True)) if x.strip()]


_RUIDO = re.compile(r"\((?:[^)]*creaci[oó]n[^)]*|\s*en creaci[oó]n\s*|\s*no creado\s*|\s*creado\s*|[^)]*se solicit[oó][^)]*)\)"
                   r"|/\s*creado|no esta creado", re.I)


def _limpio(t):
    t = str(t or "").replace("\u200b", "").strip().strip('"')
    t = _RUIDO.sub("", t)
    t = re.sub(r"\s*[.)]+\s*[.]*$", "", t) if re.search(r"[.)]\s*[.]$|\s\)$", t) else t
    return re.sub(r"\s+", " ", t).strip(" /\t-")


def desde_almacen(almacen, incluir_revision=False):
    """Convocatorias de la base propia (aprobadas y, si se pide, también las que están en revisión)."""
    cat = almacen.catalogo()
    estados = ("Aprobada", "Por revisar", "Actor pendiente de crear") if incluir_revision else ("Aprobada",)
    filas = [i["datos"] | {"_id": i["id"], "Estado en el sistema": i["estado"]} for i in almacen.items() if i["estado"] in estados]
    if not filas:
        return pd.DataFrame(columns=["Nombre de la Convocatoria"])
    tipos = {a.nombre: a.tipo for a in cat.actores.values()}
    return preparar(pd.DataFrame(filas), tipos_por_actor=tipos)


def limpiar_actor(fila):
    fuente = _limpio(fila.get("Nombre de la Fuente"))
    if not fuente or "NUEVO" in fuente.upper() or fuente.lower() in ("nan", "interno"):
        alterno = _limpio(fila.get("Nombre de actor en CICLOPE"))
        if alterno and alterno.lower() != "nan":
            return alterno
        return "Sin nombre de actor"
    return fuente


def cargar_tabla_tipos(ruta=RUTA_TIPOS):
    if not Path(ruta).exists():
        return {}
    t = pd.read_excel(ruta, dtype=str).fillna("")
    salida = {}
    for _, f in t.iterrows():
        tipo = f.get("Tipo de actor (corregido)") or f.get("Tipo de actor (sugerido)")
        if f.get("Actor") and tipo:
            salida[f["Actor"].strip()] = (tipo.strip(), "Tabla" if f.get("Tipo de actor (corregido)") else "Sugerido")
    return salida


def preparar(df, ruta_tipos=RUTA_TIPOS, tipos_por_actor=None):
    """tipos_por_actor: {actor: tipo} del catálogo de la base propia (si se da, manda sobre la tabla y las reglas)."""
    df = df.copy()
    df = df[df["Nombre de la Convocatoria"].notna() & (df["Nombre de la Convocatoria"].astype(str).str.strip() != "")]
    df["Actor"] = df.apply(limpiar_actor, axis=1)
    tabla = {a: (t, "Catálogo") for a, t in tipos_por_actor.items()} if tipos_por_actor else cargar_tabla_tipos(ruta_tipos)
    tipos, origen = [], []
    for a in df["Actor"]:
        if a in tabla:
            t, o = tabla[a]
        else:
            t, o = tipo_por_reglas(a)[0], "Sugerido"
        tipos.append(t)
        origen.append(o)
    df["Tipo de actor"] = tipos
    df["Origen del tipo"] = origen
    df["Carácter"] = df["Oficial / No Oficial"].fillna("Sin dato").str.strip()
    df["Registro"] = pd.to_datetime(df["Fecha de Registro"], dayfirst=True, errors="coerce")
    df["Cierre"] = pd.to_datetime(df["Fecha Límite de Aplicación"], dayfirst=True, errors="coerce")
    df["Mes"] = df["Registro"].dt.to_period("M")
    df["Trimestre"] = df["Registro"].dt.to_period("Q")
    for c in MULTI:
        if c in df:
            df[c + " [lista]"] = df[c].apply(dividir)
    df["Monto USD"] = pd.to_numeric(df.get("Financiación", pd.Series(dtype=str)).astype(str)
                                    .str.replace(r"[$,\s]", "", regex=True), errors="coerce")
    return df


def explotar(df, columna):
    """Una fila por valor de una columna de selección múltiple."""
    col = columna + " [lista]"
    return df[[c for c in df.columns if c != col] + [col]].explode(col).rename(columns={col: columna + " (valor)"}).dropna(subset=[columna + " (valor)"]).reset_index(drop=True)


def crear_tabla_tipos(df_prep, ruta=RUTA_TIPOS):
    """Crea o completa la tabla editable de tipos de actor sin borrar correcciones."""
    previas = pd.read_excel(ruta, dtype=str).fillna("") if Path(ruta).exists() else pd.DataFrame(
        columns=["Actor", "Tipo de actor (sugerido)", "Regla aplicada", "Tipo de actor (corregido)", "Convocatorias"])
    conteo = df_prep.groupby("Actor").size()
    filas = []
    for actor, n in conteo.sort_values(ascending=False).items():
        tipo, regla = tipo_por_reglas(actor)
        prev = previas[previas["Actor"] == actor]
        corregido = prev["Tipo de actor (corregido)"].iloc[0] if len(prev) else ""
        filas.append([actor, tipo, regla, corregido, int(n)])
    t = pd.DataFrame(filas, columns=["Actor", "Tipo de actor (sugerido)", "Regla aplicada", "Tipo de actor (corregido)", "Convocatorias"])
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        t.to_excel(w, index=False, sheet_name="Tipos de actor")
        pd.DataFrame({"Tipos permitidos": TIPOS}).to_excel(w, index=False, sheet_name="Tipos permitidos")
        ws = w.sheets["Tipos de actor"]
        from openpyxl.worksheet.datavalidation import DataValidation
        dv = DataValidation(type="list", formula1="'Tipos permitidos'!$A$2:$A$8", allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"D2:D{len(t) + 300}")
        for col, ancho in zip("ABCDE", (70, 30, 30, 30, 14)):
            ws.column_dimensions[col].width = ancho
    return ruta
