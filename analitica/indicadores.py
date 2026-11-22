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
    hoy: pd.Timestamp = None   # «abierta» y «cierra pronto» se miden contra hoy, no contra el último registro
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

    def proximas(self, top=10):
        """Convocatorias abiertas al corte, de la que cierra primero a la última."""
        d = self.df[self.df["Cierre"] >= self.hoy].sort_values("Cierre")
        return d.head(top) if top else d

    def cierres_por_mes(self, meses=6):
        """Cuántas convocatorias abiertas cierran en cada uno de los próximos meses (por modalidad)."""
        d = self.proximas(None)
        if d.empty:
            return pd.DataFrame()
        d = d.assign(MesCierre=d["Cierre"].dt.to_period("M"))
        rango = pd.period_range(self.hoy.to_period("M"), periods=meses, freq="M")
        t = pd.crosstab(d["MesCierre"], d["Modalidad"].fillna("Sin dato")).reindex(rango, fill_value=0)
        return t.loc[:, t.sum() > 0]

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
    from datetime import date as _date
    ind = Indicadores(df=df, corte=corte, total=len(df), hoy=max(corte.normalize(), pd.Timestamp(_date.today())))
    n = ind.n
    n["oficial"] = int((df["Carácter"] == "Oficial").sum())
    n["no_oficial"] = int((df["Carácter"] == "No Oficial").sum())
    n["actores"] = df["Actor"].nunique()
    n["actores_oficial"] = df[df["Carácter"] == "Oficial"]["Actor"].nunique()
    n["actores_no_oficial"] = df[df["Carácter"] == "No Oficial"]["Actor"].nunique()
    n["abiertas"] = int((df["Cierre"] >= ind.hoy).sum())
    n["cierran_30"] = int(((df["Cierre"] >= ind.hoy) & (df["Cierre"] <= ind.hoy + pd.Timedelta(days=30))).sum())
    n["permanentes"] = int(df["¿La convocatoria es permanente?"].astype(str).str.lower().str.startswith("s").sum())
    n["desde"], n["hasta"] = df["Registro"].min(), df["Registro"].max()
    no = df[df["Carácter"] == "No Oficial"]
    n["privados"] = int(no["Tipo de actor"].isin(PRIVADOS).sum())
    montos = df["Monto USD"][df["Monto USD"] > 0]
    n["mediana_usd"] = float(montos.median()) if len(montos) else 0.0
    n["con_monto"] = int(len(montos))
    ind.textos = redactar(ind)
    ind.textos["mensajes"] = mensajes(ind)
    ind.textos["lecturas"] = lecturas(ind)
    return ind


def lecturas(ind):
    """Análisis de cada bloque del informe: qué muestran las cifras y qué significan. Es descriptivo e interpretativo,
    no da instrucciones al lector. Todo sale de las cifras calculadas."""
    n, T, df = ind.n, ind.total, ind.df
    L = {"resumen": "", "quien": "", "publico": "", "abiertas": ""}
    if not T:
        return L
    # 1. tipo de oferta y ritmo
    mod = ind.conteo("Modalidad")
    m1, p1 = str(mod.index[0]).split(" (")[0], pct(mod.iloc[0], T)
    naturaleza = {"Subvención": "un instrumento que financia proyectos y cuyo público natural son las entidades y "
                                "organizaciones que los formulan",
                  "Beca": "un instrumento centrado en la formación de personas",
                  "Premio": "un instrumento que reconoce iniciativas ya en marcha",
                  "Cooperación técnica": "un instrumento de transferencia de capacidades"}
    L["resumen"] = (f"La oferta se concentra en {_modalidad(m1)} ({fmt_pct(p1)}), {naturaleza.get(m1, 'el tipo más frecuente')}"
                    + (f"; le siguen {_lista(f'{_modalidad(k)} ({fmt_pct(pct(v, T))})' for k, v in mod.iloc[1:3].items())}"
                       if len(mod) > 1 else "") + ". ")
    pm = ind.por_mes().sum(axis=1)
    if ind.corte < pm.index[-1].end_time.normalize():
        pm = pm.iloc[:-1]
    if len(pm) >= 6 and pm.iloc[-6:-3].sum():
        reciente, anterior = int(pm.iloc[-3:].sum()), int(pm.iloc[-6:-3].sum())
        cambio = pct(reciente - anterior, anterior)
        pico = pm.idxmax()
        comparacion = (f"{fmt_pct(abs(cambio))} menos que en el trimestre anterior" if cambio <= -5 else
                       f"{fmt_pct(cambio)} más que en el trimestre anterior" if cambio >= 5 else
                       "una cifra similar a la del trimestre anterior")
        L["resumen"] += (f"En el último trimestre completo se registraron {fmt_n(reciente)} convocatorias, {comparacion} "
                         f"({fmt_n(anterior)}). "
                         f"El mes con más registros del periodo fue {MESES[pico.month - 1]} de {pico.year} "
                         f"({fmt_n(pm.max())}).")
    # 2. quién ofrece y en qué temas
    actores = df.groupby("Actor").size().sort_values(ascending=False)
    top5 = pct(actores.head(5).sum(), T)
    L["quien"] = (f"Las cinco entidades con más convocatorias suman el {fmt_pct(top5)} de la oferta, "
                  + ("lo que indica una concentración alta en pocos cooperantes. " if top5 >= 30 else
                     "lo que muestra una oferta diversificada entre muchos cooperantes. "))
    p_no = pct(n["no_oficial"], T)
    L["quien"] += (f"La cooperación no oficial representa el {fmt_pct(p_no)}"
                   + (", una participación menor que la oficial. " if p_no < 45 else
                      ", una participación mayor que la oficial. " if p_no > 55 else ", en equilibrio con la oficial. "))
    temas = ind.conteo("Áreas temáticas de interés", multi=True).drop(index=["Sin dato"], errors="ignore")
    if len(temas) >= 2:
        L["quien"] += (f"{etiqueta(temas.index[0])} ({fmt_pct(pct(temas.iloc[0], T))}) y {etiqueta(temas.index[1])} "
                       f"({fmt_pct(pct(temas.iloc[1], T))}) son los temas con mayor presencia, y reflejan las líneas en que se "
                       "concentra el interés de los cooperantes.")
    # 3. a quién se dirigen
    pub = ind.conteo("Dirigida a (tipo de publico)", multi=True).drop(index=["Sin dato"], errors="ignore")
    if len(pub):
        L["publico"] = f"El público más frecuente es {etiqueta(pub.index[0])} ({fmt_pct(pct(pub.iloc[0], T))}). "
        terr = [k for k in pub.index if "territorial" in str(k).lower()]
        if terr:
            L["publico"] += (f"Las entidades territoriales pueden postularse en el {fmt_pct(pct(pub[terr[0]], T))} de las "
                             "convocatorias. ")
    pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
    pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore")
    if len(pobl):
        L["publico"] += (f"Entre las poblaciones priorizadas sobresalen {_lista(etiqueta(k) for k in pobl.index[:2])}, "
                         "en coherencia con los enfoques diferenciales.")
    # 4. abiertas
    if n["abiertas"]:
        L["abiertas"] = (f"De las {fmt_n(n['abiertas'])} convocatorias abiertas, {fmt_n(n['cierran_30'])} "
                         f"{'cierra' if n['cierran_30'] == 1 else 'cierran'} en los próximos 30 días. ")
        cm = ind.cierres_por_mes(6)
        if len(cm) and cm.values.sum():
            pico = cm.sum(axis=1).idxmax()
            L["abiertas"] += (f"Los cierres se concentran en {MESES[pico.month - 1]} de {pico.year}, con "
                              f"{fmt_n(cm.sum(axis=1).max())} convocatorias.")
    else:
        L["abiertas"] = "Con los filtros seleccionados no hay convocatorias abiertas con fecha límite."
    return L


_PLURAL = {"beca": "becas", "subvención": "subvenciones", "subvencion": "subvenciones", "premio": "premios",
           "cooperación técnica": "ofertas de cooperación técnica", "cooperacion tecnica": "ofertas de cooperación técnica"}


def _modalidad(k):
    k = str(k).split(" (")[0].lower().strip()
    return _PLURAL.get(k, k)


def mensajes(ind):
    """Cuatro o cinco ideas principales, en lenguaje sencillo, para cualquier lector."""
    n, T = ind.n, ind.total
    if not T:
        return ["No hay convocatorias con los filtros seleccionados."]
    m = [f"Hay {fmt_n(T)} convocatorias registradas entre el {fecha_larga(n['desde'])} y el {fecha_larga(n['hasta'])}. "
         f"Hoy, {fecha_larga(ind.hoy)}, {fmt_n(n['abiertas'])} {'sigue abierta' if n['abiertas'] == 1 else 'siguen abiertas'}"
         + (f" y {fmt_n(n['cierran_30'])} {'cierra' if n['cierran_30'] == 1 else 'cierran'} en los próximos 30 días"
            if n["cierran_30"] else "") + "."]
    mod = ind.conteo("Modalidad")
    if len(mod):
        m.append(f"La mayoría son {_modalidad(mod.index[0])} ({fmt_pct(pct(mod.iloc[0], T))})"
                 + (", seguidas de " + _lista(f"{_modalidad(k)} ({fmt_pct(pct(v, T))})" for k, v in mod.iloc[1:3].items())
                    if len(mod) > 1 else "") + ".")
    m.append(f"El {fmt_pct(pct(n['oficial'], T))} viene de gobiernos, agencias de cooperación y organismos internacionales "
             f"(oferta oficial) y el {fmt_pct(pct(n['no_oficial'], T))}, de fundaciones, ONG, universidades y empresas "
             "(oferta no oficial).")
    top = ind.df.groupby("Actor").size().sort_values(ascending=False)
    temas = ind.conteo("Áreas temáticas de interés", multi=True).drop(index=["Sin dato"], errors="ignore")
    if len(top) and len(temas):
        m.append(f"Quien más ofrece es {corto(top.index[0])} ({fmt_n(top.iloc[0])} convocatorias). Los temas más frecuentes son "
                 + _lista(etiqueta(k) for k in temas.index[:3]) + ".")
    pm = ind.por_mes().sum(axis=1)
    if ind.corte < pm.index[-1].end_time.normalize():
        pm = pm.iloc[:-1]  # el mes en curso todavía está incompleto
    if len(pm) >= 6:
        recientes, antes = int(pm.iloc[-3:].sum()), int(pm.iloc[-6:-3].sum())
        if antes:
            cambio = pct(recientes - antes, antes)
            tendencia = ("más" if cambio > 5 else "menos" if cambio < -5 else "casi las mismas")
            m.append(f"En los últimos tres meses completos se registraron {fmt_n(recientes)} convocatorias: {tendencia} que en "
                     f"los tres meses anteriores ({fmt_n(antes)})" + (f", un cambio de {fmt_pct(abs(cambio))}" if tendencia != "casi las mismas" else "") + ".")
    return m[:5]


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
        f"Al {fecha_larga(ind.hoy)}, {fmt_n(n['abiertas'])} siguen abiertas y {fmt_n(n['permanentes'])} son permanentes."
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
