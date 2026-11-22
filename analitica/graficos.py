"""Gráficos del informe (matplotlib → PNG). Paleta validada para daltonismo.

Reglas: Oficial = azul y No Oficial = naranja en todos los gráficos; una sola
escala por gráfico; valores escritos sobre las barras; rejilla tenue.
"""
import io
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .indicadores import CARACTER, corto, etiqueta, mes_corto  # noqa: E402

AZUL, NARANJA = "#2a78d6", "#eb6834"
COLOR = {"Oficial": AZUL, "No Oficial": NARANJA}
TINTA, TINTA2, REJILLA, FONDO = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
AZULES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

from matplotlib import font_manager as _fm  # noqa: E402

_DISPONIBLES = {f.name for f in _fm.fontManager.ttflist}
_LETRA = next((f for f in ("Arial", "Liberation Sans", "Carlito", "DejaVu Sans") if f in _DISPONIBLES), "sans-serif")

plt.rcParams.update({
    "font.family": _LETRA,
    "font.size": 9, "axes.edgecolor": REJILLA, "axes.labelcolor": TINTA2, "xtick.color": TINTA2,
    "ytick.color": TINTA, "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "figure.facecolor": FONDO, "axes.facecolor": FONDO, "savefig.facecolor": FONDO,
})


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    buf.seek(0)
    return buf


def _envolver(t, ancho=34):
    return "\n".join(textwrap.wrap(etiqueta(t), ancho)) or t


def _leyenda(ax, series):
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=COLOR[s], label=s) for s in series], loc="lower right", frameon=False,
              fontsize=8.5, ncol=len(series), bbox_to_anchor=(1, 1.0))


def barras_por_caracter(tabla, titulo=None, ancho_etiqueta=34, alto_fila=0.42):
    """Barras horizontales agrupadas Oficial / No Oficial, ordenadas por total."""
    t = tabla.iloc[::-1]
    filas = len(t)
    fig, ax = plt.subplots(figsize=(6.6, max(1.6, 0.55 + alto_fila * filas)))
    y = np.arange(filas)
    h = 0.36
    maximo = max(1, t[CARACTER].values.max())
    for i, serie in enumerate(CARACTER):
        desp = h / 2 + 0.02 if i == 0 else -(h / 2 + 0.02)
        vals = t[serie].values
        ax.barh(y + desp, vals, height=h, color=COLOR[serie], zorder=2)
        for yy, v in zip(y + desp, vals):
            if v:
                ax.text(v + maximo * 0.012, yy, str(int(v)), va="center", fontsize=8, color=TINTA2)
    ax.set_yticks(y, [_envolver(i, ancho_etiqueta) for i in t.index], fontsize=8.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, maximo * 1.12)
    ax.xaxis.grid(True, color=REJILLA, lw=0.6, zorder=0)
    ax.tick_params(axis="x", labelsize=8)
    _leyenda(ax, CARACTER)
    if titulo:
        ax.set_title(titulo, loc="left", fontsize=10, color=TINTA, pad=14, fontweight="bold")
    return _png(fig)


def barras_simples(serie, color=AZUL, etiquetas_extra=None, ancho_etiqueta=40, total=None):
    """Barras horizontales de una sola serie (un solo color), con valor y porcentaje."""
    s = serie.iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.6, max(1.4, 0.5 + 0.34 * len(s))))
    y = np.arange(len(s))
    ax.barh(y, s.values, height=0.62, color=color, zorder=2)
    maximo = max(1, s.values.max())
    for yy, (k, v) in zip(y, s.items()):
        txt = str(int(v)) + (f"  ({100 * v / total:.0f} %)" if total else "")
        if etiquetas_extra is not None and k in etiquetas_extra:
            txt += f"  · {etiquetas_extra[k]}"
        ax.text(v + maximo * 0.012, yy, txt, va="center", fontsize=8, color=TINTA2)
    ax.set_yticks(y, [_envolver(corto(k) if len(k) > 45 else k, ancho_etiqueta) for k in s.index], fontsize=8.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, maximo * (1.55 if etiquetas_extra else 1.2))
    ax.xaxis.grid(True, color=REJILLA, lw=0.6, zorder=0)
    ax.tick_params(axis="x", labelsize=8)
    return _png(fig)


def tendencia_mensual(tabla_mes, corte):
    """Líneas por mes: Oficial y No Oficial, con etiqueta directa al final."""
    fig, ax = plt.subplots(figsize=(6.6, 2.7))
    x = np.arange(len(tabla_mes))
    for serie in CARACTER:
        v = tabla_mes[serie].values
        ax.plot(x, v, color=COLOR[serie], lw=2, marker="o", ms=4.5, zorder=3,
                markeredgecolor=FONDO, markeredgewidth=1.2)
        ax.annotate(f"{serie} ({int(v[-2] if len(v) > 1 and _mes_parcial(tabla_mes, corte) else v[-1])})",
                    (x[-2] if len(x) > 1 and _mes_parcial(tabla_mes, corte) else x[-1],
                     v[-2] if len(v) > 1 and _mes_parcial(tabla_mes, corte) else v[-1]),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=TINTA)
    if _mes_parcial(tabla_mes, corte):
        ax.axvspan(x[-1] - 0.5, x[-1] + 0.5, color="#f0efec", zorder=0)
        ax.text(x[-1], ax.get_ylim()[1] * 0.96, "mes\nen curso", ha="center", va="top", fontsize=7, color=TINTA2)
    ax.set_xticks(x, [mes_corto(p) for p in tabla_mes.index], fontsize=8)
    ax.yaxis.grid(True, color=REJILLA, lw=0.6, zorder=0)
    ax.set_ylim(0, max(1, tabla_mes.values.max()) * 1.2)
    ax.set_xlim(-0.4, len(x) - 0.4 + 1.3)
    ax.set_ylabel("Convocatorias registradas", fontsize=8)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", labelsize=8, length=0)
    return _png(fig)


def _mes_parcial(tabla_mes, corte):
    ultimo = tabla_mes.index[-1]
    return corte < ultimo.end_time.normalize()


def mapa_calor_temas(partes, conteos, corte):
    """Participación de cada temática por trimestre (% de convocatorias), escala de un solo azul."""
    p = partes.copy()
    fig, ax = plt.subplots(figsize=(6.6, 0.55 + 0.36 * len(p)))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("azules", AZULES)
    vmax = max(1, np.nanmax(p.values))
    ax.imshow(p.values, aspect="auto", cmap=cmap, vmin=0, vmax=vmax)
    for i in range(p.shape[0]):
        for j in range(p.shape[1]):
            v = p.values[i, j]
            ax.text(j, i, f"{v:.0f} %\n({int(conteos.values[i, j])})", ha="center", va="center", fontsize=7.5,
                    color="#ffffff" if v > vmax * 0.55 else TINTA)
    cols = []
    for q in p.columns:
        cols.append(f"T{q.quarter} {q.year}" + ("\n(en curso)" if corte < q.end_time.normalize() else ""))
    ax.set_xticks(range(p.shape[1]), cols, fontsize=8)
    ax.set_yticks(range(p.shape[0]), [_envolver(i, 38) for i in p.index], fontsize=8.5)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks(np.arange(-0.5, p.shape[1]), minor=True)
    ax.set_yticks(np.arange(-0.5, p.shape[0]), minor=True)
    ax.grid(which="minor", color=FONDO, lw=2)
    ax.tick_params(which="minor", length=0)
    return _png(fig)


def proporcion(n_oficial, n_no_oficial):
    """Barra única 100 % Oficial / No Oficial con etiquetas."""
    total = max(1, n_oficial + n_no_oficial)
    fig, ax = plt.subplots(figsize=(6.6, 0.75))
    ax.barh([0], [n_oficial], color=AZUL, height=0.6)
    ax.barh([0], [n_no_oficial], left=[n_oficial + total * 0.004], color=NARANJA, height=0.6)
    ax.text(n_oficial / 2, 0, f"Oficial  {n_oficial}  ({100 * n_oficial / total:.0f} %)", ha="center", va="center",
            color="#ffffff", fontsize=9, fontweight="bold")
    ax.text(n_oficial + n_no_oficial / 2, 0, f"No Oficial  {n_no_oficial}  ({100 * n_no_oficial / total:.0f} %)",
            ha="center", va="center", color=TINTA, fontsize=9, fontweight="bold")
    ax.set_xlim(0, total * 1.005)
    ax.axis("off")
    return _png(fig)


# --- gráficos compactos del informe de 3 páginas ------------------------------------------
NAVY_G = "#0B2545"
MODALIDAD_COLOR = {"Beca": "#2a78d6", "Subvención": "#eb6834", "Premio": "#1a9e77", "Cooperación técnica": "#8a63d2"}


def _color_mod(k):
    return MODALIDAD_COLOR.get(str(k).split(" (")[0], "#9aa4b1")


def _barras_h(ax, serie, colores, total=None, ancho=30, fuente=8):
    s = serie.iloc[::-1]
    y = np.arange(len(s))
    ax.barh(y, s.values, height=0.62, color=colores[::-1] if isinstance(colores, list) else colores, zorder=2)
    maximo = max(1, s.values.max())
    for yy, v in zip(y, s.values):
        ax.text(v + maximo * 0.02, yy, f"{int(v)}" + (f" ({100 * v / total:.0f} %)" if total else ""), va="center",
                fontsize=fuente - 0.5, color=TINTA2)
    ax.set_yticks(y, [_envolver(corto(k) if len(str(k)) > 45 else k, ancho) for k in s.index], fontsize=fuente)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", labelsize=7, colors="#9aa4b1")
    ax.set_xlim(0, maximo * 1.35)
    ax.xaxis.grid(True, color=REJILLA, lw=0.5, zorder=0)
    ax.spines["bottom"].set_visible(False)


def panel_resumen(ind):
    """Izquierda: convocatorias por modalidad. Derecha: registradas por mes."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.1, 2.6), gridspec_kw={"width_ratios": [1, 1.5], "wspace": 0.4})
    mod = ind.conteo("Modalidad")
    colores = [_color_mod(k) for k in mod.index]
    mod.index = [str(k).split(" (")[0] for k in mod.index]
    _barras_h(a, mod, colores, total=ind.total, ancho=22)
    a.set_title("Convocatorias por tipo", loc="left", fontsize=9, fontweight="bold", color=NAVY_G)
    pm = ind.por_mes().sum(axis=1)
    parcial = ind.corte < pm.index[-1].end_time.normalize()
    x = np.arange(len(pm))
    colores = [AZUL] * len(pm)
    if parcial:
        colores[-1] = "#bcd3f0"
    b.bar(x, pm.values, color=colores, width=0.7, zorder=2)
    completos = pm.iloc[:-1] if parcial else pm
    if len(completos) >= 3:  # tendencia: promedio de tres meses
        media = completos.rolling(3, min_periods=3).mean()
        b.plot(x[:len(media)], media.values, color=NAVY_G, lw=1.8, zorder=3, label="Promedio de 3 meses")
        b.legend(frameon=False, fontsize=6.5, loc="upper right")
    imax = int(np.argmax(pm.values))
    for xx, v in zip(x, pm.values):
        if v:
            b.text(xx, v + max(1, pm.max()) * 0.03, str(int(v)), ha="center", fontsize=6.5,
                   color=NAVY_G if xx == imax else TINTA2, fontweight="bold" if xx == imax else "normal")
    paso = max(1, -(-len(pm) // 6))
    b.set_xticks(x[::paso], [mes_corto(p) for p in pm.index][::paso], fontsize=7)
    b.tick_params(axis="y", labelsize=7, colors="#9aa4b1", length=0)
    b.yaxis.grid(True, color=REJILLA, lw=0.5, zorder=0)
    b.set_ylim(0, max(1, pm.max()) * 1.3)
    b.spines["left"].set_visible(False)
    b.set_title("Registradas por mes" + ("  ·  barra clara: mes en curso" if parcial else ""), loc="left",
                fontsize=9, fontweight="bold", color=NAVY_G)
    return _png(fig)


def panel_quien(ind, top=8):
    """Izquierda: oferentes con más convocatorias (azul oficial, naranja no oficial). Derecha: temas más frecuentes."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.1, 0.75 + 0.27 * top), gridspec_kw={"wspace": 0.95})
    g = ind.df.groupby(["Actor", "Carácter"]).size().reset_index(name="n").sort_values("n", ascending=False)
    g = g.drop_duplicates("Actor").head(top)
    serie = pd.Series(g["n"].values, index=[corto(x) for x in g["Actor"]])
    _barras_h(a, serie, [COLOR.get(c, AZUL) for c in g["Carácter"]], ancho=26, fuente=7.5)
    a.set_title("Entidades con más convocatorias", loc="left", fontsize=9, fontweight="bold", color=NAVY_G)
    from matplotlib.patches import Patch
    a.legend(handles=[Patch(color=AZUL, label="Oficial"), Patch(color=NARANJA, label="No oficial")], loc="lower right",
             frameon=False, fontsize=7, ncol=2, bbox_to_anchor=(1.05, -0.2))
    temas = ind.conteo("Áreas temáticas de interés", multi=True).drop(index=["Sin dato"], errors="ignore").head(top)
    _barras_h(b, temas, "#256abf", total=ind.total, ancho=26, fuente=7.5)
    b.set_title("Temas más frecuentes (% del total)", loc="left", fontsize=9, fontweight="bold", color=NAVY_G)
    return _png(fig)


def barras_publico(serie, total):
    fig, ax = plt.subplots(figsize=(3.4, 0.45 + 0.27 * len(serie)))
    _barras_h(ax, serie, "#1a9e77", total=total, ancho=24, fuente=7.5)
    return _png(fig)


def cierres_mes(tabla):
    """Convocatorias abiertas según el mes en que cierran, apiladas por modalidad."""
    fig, ax = plt.subplots(figsize=(7.1, 1.55))
    x = np.arange(len(tabla))
    base = np.zeros(len(tabla))
    for col in tabla.columns:
        ax.bar(x, tabla[col].values, bottom=base, color=_color_mod(col), width=0.6, label=str(col).split(" (")[0], zorder=2)
        base += tabla[col].values
    for xx, v in zip(x, base):
        if v:
            ax.text(xx, v + max(1, base.max()) * 0.04, str(int(v)), ha="center", fontsize=7, color=TINTA2)
    ax.set_xticks(x, [mes_corto(p) for p in tabla.index], fontsize=7.5)
    ax.tick_params(axis="y", labelsize=7, colors="#9aa4b1", length=0)
    ax.yaxis.grid(True, color=REJILLA, lw=0.5, zorder=0)
    ax.set_ylim(0, max(1, base.max()) * 1.3)
    ax.spines["left"].set_visible(False)
    ax.legend(frameon=False, fontsize=7, ncol=len(tabla.columns), loc="upper right")
    return _png(fig)
