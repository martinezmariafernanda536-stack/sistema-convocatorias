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
