"""Indicadores y textos automáticos sobre las convocatorias (los usa el informe y el dashboard)."""
from dataclasses import dataclass, field

import pandas as pd

from .datos import PRIVADOS, explotar

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
CARACTER = ["Oficial", "No Oficial"]


def fecha_larga(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}" if pd.notna(d) else "sin fecha"


def mes_corto(p):
    return f"{MESES[p.month - 1][:3].capitalize()} {str(p.year)[2:]}"


def pct(a, b):
    return 100 * a / b if b else 0


def fmt_pct(v):
    return f"{v:.0f} %".replace(".", ",")


def etiqueta(t):
    """Limpia nombres de catálogo para mostrarlos ('Tecnología , Innovación' -> 'Tecnología, Innovación')."""
    return " ".join(str(t).replace(" ,", ",").split())


def fmt_n(v):
    return f"{int(v):,}".replace(",", ".")


@dataclass
class Indicadores:
    df: pd.DataFrame
    corte: pd.Timestamp
    total: int = 0
    n: dict = field(default_factory=dict)
    textos: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def conteo(self, columna, sub=None, multi=False, top=None):
        d = self.df if sub is None else sub
        if multi:
            d = explotar(d, columna)
            columna = columna + " (valor)"
        s = d[columna].fillna("Sin dato").astype(str).str.strip().replace({"": "Sin dato", "nan": "Sin dato"}).value_counts()
        return s.head(top) if top else s

    def por_caracter(self, columna, multi=False, top=None):
        d = explotar(self.df, columna) if multi else self.df
        col = columna + " (valor)" if multi else columna
        t = pd.crosstab(d[col].fillna("Sin dato").astype(str).str.strip(), d["Carácter"])
        for c in CARACTER:
            if c not in t:
                t[c] = 0
        t = t[CARACTER]
        t["Total"] = t.sum(axis=1)
        t = t.sort_values("Total", ascending=False)
        return t.head(top) if top else t

    def por_mes(self):
        t = pd.crosstab(self.df["Mes"], self.df["Carácter"])
        for c in CARACTER:
            if c not in t:
                t[c] = 0
        rango = pd.period_range(self.df["Mes"].min(), self.df["Mes"].max(), freq="M")
        return t[CARACTER].reindex(rango, fill_value=0)

    def temas_por_trimestre(self, top=8):
        d = explotar(self.df, "Áreas temáticas de interés")
        principales = d["Áreas temáticas de interés (valor)"].value_counts().head(top).index
        t = pd.crosstab(d["Áreas temáticas de interés (valor)"], d["Trimestre"])
        totales = self.df.groupby("Trimestre").size()
        part = (t.loc[principales] / totales * 100).round(0)
        return t.loc[principales], part

    def actores(self, caracter, top=12):
        sub = self.df[self.df["Carácter"] == caracter]
        g = sub.groupby(["Actor", "Tipo de actor"]).size().reset_index(name="Convocatorias")
        return g.sort_values(["Convocatorias", "Actor"], ascending=[False, True]).head(top)

    def inconsistencias(self):
        dobles = self.df.groupby("Actor")["Carácter"].nunique()
        dobles = sorted(dobles[dobles > 1].index)
        no_of_publicos = self.df[(self.df["Carácter"] == "No Oficial") &
                                 self.df["Tipo de actor"].isin(["Gobierno / agencia bilateral", "Organismo multilateral"])]
        return {
            "actores_en_ambos": dobles,
            "no_oficial_con_actor_publico": no_of_publicos[["Actor", "Nombre de la Convocatoria"]],
            "sin_actor": int((self.df["Actor"] == "Sin nombre de actor").sum()),
            "por_clasificar": int((self.df["Tipo de actor"] == "Por clasificar").sum()),
            "tipo_sugerido": int((self.df["Origen del tipo"] == "Sugerido").sum()),
            "sin_fecha_cierre": int(self.df["Cierre"].isna().sum()),
        }


def calcular(df, corte=None):
    corte = pd.Timestamp(corte) if corte is not None else df["Registro"].max()
    ind = Indicadores(df=df, corte=corte, total=len(df))
    n = ind.n
    n["oficial"] = int((df["Carácter"] == "Oficial").sum())
    n["no_oficial"] = int((df["Carácter"] == "No Oficial").sum())
    n["actores"] = df["Actor"].nunique()
    n["actores_oficial"] = df[df["Carácter"] == "Oficial"]["Actor"].nunique()
    n["actores_no_oficial"] = df[df["Carácter"] == "No Oficial"]["Actor"].nunique()
    n["abiertas"] = int((df["Cierre"] >= corte).sum())
    n["permanentes"] = int(df["¿La convocatoria es permanente?"].astype(str).str.lower().str.startswith("s").sum())
    n["desde"], n["hasta"] = df["Registro"].min(), df["Registro"].max()
    no = df[df["Carácter"] == "No Oficial"]
    n["privados"] = int(no["Tipo de actor"].isin(PRIVADOS).sum())
    montos = df["Monto USD"][df["Monto USD"] > 0]
    n["mediana_usd"] = float(montos.median()) if len(montos) else 0.0
    n["con_monto"] = int(len(montos))
    ind.textos = redactar(ind)
    return ind


# ---------------------------------------------------------------------------
def corto(actor):
    """'AECID - Agencia Española…' -> 'AECID'; nombres bilingües 'X / Y' -> 'X'."""
    a = actor.split(" / ")[0].strip()
    if " - " in a:
        partes = [x.strip() for x in a.split(" - ")]
        cortas = [x for x in partes if 2 <= len(x) <= 8 and " " not in x and x.upper() == x and x != "COLOMBIA"]
        if cortas:
            return cortas[0]
    return a


def _lista(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def redactar(ind):
    """Textos automáticos. Cada uno se apoya solo en cifras calculadas aquí."""
    n, T, t = ind.n, ind.total, {}
    if not T:
        return {k: "No hay convocatorias con los filtros seleccionados." for k in
                ("resumen", "oficial", "no_oficial", "tematicas", "tendencia", "modalidad", "publico", "alineacion")}
    t["resumen"] = (
        f"Entre el {fecha_larga(n['desde'])} y el {fecha_larga(n['hasta'])} se registraron {fmt_n(T)} convocatorias "
        f"de {fmt_n(n['actores'])} actores. De ellas, {fmt_n(n['oficial'])} son oficiales ({fmt_pct(pct(n['oficial'], T))}) "
        f"y {fmt_n(n['no_oficial'])} no oficiales ({fmt_pct(pct(n['no_oficial'], T))}). "
        f"Al {fecha_larga(ind.corte)}, {fmt_n(n['abiertas'])} siguen abiertas y {fmt_n(n['permanentes'])} son permanentes."
    )

    of = ind.df[ind.df["Carácter"] == "Oficial"]
    if len(of):
        tipos = of["Tipo de actor"].value_counts()
        top = ind.actores("Oficial", 3)
        t["oficial"] = (
            f"La cooperación oficial suma {fmt_n(len(of))} convocatorias de {fmt_n(n['actores_oficial'])} actores. "
            f"Por tipo de actor, {_lista(f'{k.lower()} ({fmt_n(v)})' for k, v in tipos.head(3).items())}. "
            f"Los actores con más convocatorias son {_lista(f'{corto(a)} ({c})' for a, c in zip(top['Actor'], top['Convocatorias']))}."
        )
    else:
        t["oficial"] = "No hay convocatorias oficiales con los filtros seleccionados."

    no = ind.df[ind.df["Carácter"] == "No Oficial"]
    if len(no):
        tipos = no["Tipo de actor"].value_counts()
        priv = {k: int(tipos.get(k, 0)) for k in PRIVADOS}
        top = ind.actores("No Oficial", 3)
        t["no_oficial"] = (
            f"De las {fmt_n(len(no))} convocatorias no oficiales, {fmt_n(n['privados'])} ({fmt_pct(pct(n['privados'], len(no)))}) "
            f"provienen de actores privados y de la sociedad civil: fundaciones y filantropía ({priv['Fundación / filantropía']}), "
            f"ONG y sociedad civil ({priv['ONG / sociedad civil']}), academia e investigación ({priv['Academia / investigación']}) "
            f"y empresas privadas ({priv['Empresa privada']}). "
            f"Los actores con más convocatorias son {_lista(f'{corto(a)} ({c})' for a, c in zip(top['Actor'], top['Convocatorias']))}."
        )
        publicos = int(no["Tipo de actor"].isin(["Gobierno / agencia bilateral", "Organismo multilateral"]).sum())
        if publicos:
            t["no_oficial"] += (f" Otras {fmt_n(publicos)} están marcadas como no oficiales aunque su actor es un gobierno "
                                f"o un organismo multilateral; conviene revisar esa clasificación.")
    else:
        t["no_oficial"] = "No hay convocatorias no oficiales con los filtros seleccionados."

    temas = ind.por_caracter("Áreas temáticas de interés", multi=True)
    sin_edu = temas.drop(index=[i for i in temas.index if i.lower().startswith("educaci")], errors="ignore")
    if len(temas):
        primero = temas.index[0]
        t["tematicas"] = (
            f"La temática más frecuente es {primero} ({fmt_n(temas.iloc[0]['Total'])} convocatorias, "
            f"{fmt_pct(pct(temas.iloc[0]['Total'], T))} del total). "
            f"Le siguen {_lista(f'{etiqueta(k)} ({fmt_n(v)})' for k, v in sin_edu['Total'].head(3).items() if k != primero)}. "
        )
        if len(sin_edu):
            of_top = sin_edu.sort_values("Oficial", ascending=False).index[0]
            no_top = sin_edu.sort_values("No Oficial", ascending=False).index[0]
            t["tematicas"] += (f"Sin contar Educación, en la oferta oficial destaca {etiqueta(of_top)} y en la no oficial, {etiqueta(no_top)}. "
                               "Una convocatoria puede tener varias temáticas, por eso las cifras no suman el total.")

    trim = ind.df.groupby(["Trimestre", "Carácter"]).size().unstack(fill_value=0)
    _, partes = ind.temas_por_trimestre()
    completos = [q for q in trim.index if ind.corte >= q.end_time.normalize()]
    en_curso = [q for q in trim.index if q not in completos]
    usar = completos if len(completos) >= 2 else list(trim.index)
    if len(usar) >= 2:
        def part(q):
            fila = trim.loc[q]
            return pct(fila.get("No Oficial", 0), fila.sum())
        q0, q1 = usar[0], usar[-1]
        t["tendencia"] = (f"La participación de las convocatorias no oficiales pasó de {fmt_pct(part(q0))} en el "
                          f"T{q0.quarter} {q0.year} a {fmt_pct(part(q1))} en el T{q1.quarter} {q1.year}")
        if en_curso and usar is completos:
            q2 = en_curso[-1]
            t["tendencia"] += f" (en el T{q2.quarter} {q2.year}, aún en curso, va en {fmt_pct(part(q2))})"
        t["tendencia"] += "."
        if q0 in partes.columns and q1 in partes.columns:
            delta = (partes[q1] - partes[q0]).drop(
                index=[i for i in partes.index if i.lower().startswith("educaci")], errors="ignore").sort_values()
            sube, baja = delta.index[-1], delta.index[0]
            if delta.iloc[-1] > 0:
                t["tendencia"] += (f" Entre esos trimestres, {etiqueta(sube)} gana presencia (de {fmt_pct(partes.loc[sube, q0])} "
                                   f"a {fmt_pct(partes.loc[sube, q1])} de las convocatorias)")
            if delta.iloc[0] < 0:
                t["tendencia"] += (f"{' y' if delta.iloc[-1] > 0 else ' En cambio,'} {etiqueta(baja)} la pierde "
                                   f"(de {fmt_pct(partes.loc[baja, q0])} a {fmt_pct(partes.loc[baja, q1])})")
            t["tendencia"] += "."
    else:
        t["tendencia"] = "El periodo filtrado tiene un solo trimestre: no permite ver tendencia."

    mod = ind.conteo("Modalidad")
    t["modalidad"] = ("Por modalidad, " + _lista(f"{k.split(' (')[0].lower()} ({fmt_n(v)}; {fmt_pct(pct(v, T))})" for k, v in mod.items()) + ".")

    pub = ind.conteo("Dirigida a (tipo de publico)", multi=True)
    pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
    pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore")
    t["publico"] = (f"El público más frecuente es {pub.index[0]} ({fmt_n(pub.iloc[0])} convocatorias)"
                    + (f", seguido de {_lista(f'{k} ({fmt_n(v)})' for k, v in pub.iloc[1:3].items())}" if len(pub) > 1 else "") + ". ")
    if len(pobl):
        t["publico"] += f"Las poblaciones más priorizadas son {_lista(f'{k} ({fmt_n(v)})' for k, v in pobl.head(3).items())}."

    cad = ind.conteo("Comite de Ayuda al Desarrollo")
    ods = ind.conteo("ODS")
    t["alineacion"] = (f"En la clasificación CAD predominan {_lista(f'{k} ({fmt_n(v)})' for k, v in cad.head(3).items())}. "
                       f"Frente a los ODS, los más frecuentes son {_lista(f'el {k} ({fmt_n(v)})' for k, v in ods.head(3).items())}.")
    return t
