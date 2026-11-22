"""El mismo informe de 3 páginas, generado directamente en PDF (sin LibreOffice ni Word).

Usa fpdf2 (librería pequeña) y las letras DejaVu que ya trae matplotlib, así que no agrega peso al servidor.
"""
import os
from datetime import date
from pathlib import Path

import matplotlib
from fpdf import FPDF

from . import graficos as G
from .indicadores import corto, etiqueta, fecha_larga, fmt_n, fmt_pct, pct

NAVY = (11, 37, 69)
GRIS = (82, 81, 78)
CLARO = (238, 243, 249)
FRANJA = (243, 246, 250)
ROJO = (180, 35, 24)
AZUL_ENLACE = (31, 95, 175)
ANCHO = 172  # mm útiles (A4 con márgenes de 19 mm)


class _PDF(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        carpeta = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        for estilo, archivo in (("", "DejaVuSans.ttf"), ("B", "DejaVuSans-Bold.ttf"), ("I", "DejaVuSans-Oblique.ttf"),
                                ("BI", "DejaVuSans-BoldOblique.ttf")):
            self.add_font("Letra", estilo, os.path.join(carpeta, archivo))
        self.set_margins(19, 15, 19)
        self.set_auto_page_break(True, 14)

    def footer(self):
        self.set_y(-11)
        self.set_font("Letra", "", 7)
        self.set_text_color(*GRIS)
        self.cell(0, 4, f"APC-Colombia · DGDCI  |  Informe de convocatorias internacionales  |  Página {self.page_no()}",
                  align="R")


class InformePDF:
    def __init__(self, ind, filtros, fuente_datos="Sistema de convocatorias de la DGDCI"):
        self.ind, self.filtros, self.fuente_datos = ind, filtros, fuente_datos
        self.pdf = _PDF()

    # -- piezas ---------------------------------------------------------------
    def _letra(self, tam, estilo="", color=(27, 42, 58)):
        self.pdf.set_font("Letra", estilo, tam)
        self.pdf.set_text_color(*color)

    def _titulo(self, texto, antes=4):
        self.pdf.ln(antes)
        self._letra(12, "B", NAVY)
        self.pdf.cell(0, 7, texto, new_x="LMARGIN", new_y="NEXT")

    def _parrafo(self, texto, tam=8.8, estilo="", color=(27, 42, 58), alin="J", alto=4.4):
        if texto:
            self._letra(tam, estilo, color)
            self.pdf.multi_cell(0, alto, texto, align=alin, new_x="LMARGIN", new_y="NEXT")

    def _nota(self, texto):
        self._parrafo(texto, tam=6.8, estilo="I", color=GRIS, alin="L", alto=3.4)
        self.pdf.ln(1)

    def _vinetas(self, items, tam=9, ancho=None, x=None):
        for it in items:
            if x is not None:
                self.pdf.set_x(x)
            self._letra(tam)
            y = self.pdf.get_y()
            self.pdf.cell(4, 4.6, "•")
            self.pdf.multi_cell((ancho or ANCHO) - 4, 4.6, it, align="L", new_x="LMARGIN", new_y="NEXT")
            if self.pdf.get_y() == y:
                self.pdf.ln(4.6)

    def _imagen(self, png, ancho=ANCHO, x=None):
        png.seek(0)
        self.pdf.image(png, x=x, w=ancho)
        self.pdf.ln(1)

    # -- página 1 -------------------------------------------------------------
    def _encabezado(self):
        p = self.pdf
        p.set_fill_color(*NAVY)
        p.rect(19, 15, ANCHO, 27, style="F")
        p.set_xy(23, 18)
        self._letra(7.5, "B", (169, 188, 214))
        p.cell(0, 4, "APC-COLOMBIA · DGDCI", new_x="LMARGIN", new_y="NEXT")
        p.set_x(23)
        self._letra(17, "B", (255, 255, 255))
        p.cell(0, 9, "Convocatorias internacionales para Colombia", new_x="LMARGIN", new_y="NEXT")
        p.set_x(23)
        self._letra(8.5, "", (202, 220, 252))
        p.cell(0, 5, f"Becas, subvenciones, premios y cooperación técnica · informe del {fecha_larga(self.ind.hoy)}")
        p.set_y(45)

    def _cifras(self):
        n, p = self.ind.n, self.pdf
        tarjetas = [(fmt_n(self.ind.total), "convocatorias registradas"), (fmt_n(n["abiertas"]), "siguen abiertas"),
                    (fmt_n(n["cierran_30"]), "cierran en los próximos 30 días"), (fmt_n(n["actores"]), "entidades que las ofrecen")]
        ancho, y = (ANCHO - 6) / 4, p.get_y()
        for i, (num, lab) in enumerate(tarjetas):
            x = 19 + i * (ancho + 2)
            p.set_fill_color(*CLARO)
            p.rect(x, y, ancho, 18, style="F")
            p.set_xy(x, y + 2)
            self._letra(17, "B", NAVY)
            p.cell(ancho, 8, num, align="C")
            p.set_xy(x + 2, y + 10.5)
            self._letra(7, "", GRIS)
            p.multi_cell(ancho - 4, 3.2, lab, align="C")
            p.set_xy(x, y)
        p.set_y(y + 21)

    def pagina_1(self):
        self.pdf.add_page()
        self._encabezado()
        self._cifras()
        self._titulo("Principales resultados", antes=1)
        self._vinetas(self.ind.textos["mensajes"])
        self._titulo("Tipos de convocatoria y ritmo de registro", antes=3)
        self._imagen(G.panel_resumen(self.ind))
        self._nota("Una convocatoria se cuenta en el mes en que se registró en el sistema. La línea muestra el promedio de tres "
                   "meses; el número en negrita, el mes con más registros.")
        self._parrafo(self.ind.textos["lecturas"]["resumen"])

    # -- página 2 -------------------------------------------------------------
    def pagina_2(self):
        ind, p = self.ind, self.pdf
        p.add_page()
        self._titulo("¿Quién ofrece y en qué temas?", antes=0)
        of = ind.df[ind.df["Carácter"] == "Oficial"]["Tipo de actor"].value_counts()
        no = ind.df[ind.df["Carácter"] == "No Oficial"]["Tipo de actor"].value_counts()
        partes = []
        if len(of):
            partes.append(f"En la oferta oficial predominan {of.index[0].lower()} ({fmt_n(of.iloc[0])} convocatorias)")
        if len(no):
            partes.append(f"en la no oficial, {no.index[0].lower()} ({fmt_n(no.iloc[0])})")
        if partes:
            self._parrafo("; ".join(partes) + ". Una convocatoria puede tener varios temas, por eso los temas no suman el total.")
        p.ln(1)
        self._imagen(G.panel_quien(ind))
        self._parrafo(ind.textos["lecturas"]["quien"])
        self._titulo("¿A quién se dirigen?", antes=4)
        pub = ind.conteo("Dirigida a (tipo de publico)", multi=True).drop(index=["Sin dato"], errors="ignore").head(6)
        pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
        pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore").head(5)
        y0 = p.get_y()
        if len(pub):
            self._imagen(G.barras_publico(pub, ind.total), ancho=86, x=19)
        y_fin_img = p.get_y()
        x = 19 + 90
        p.set_xy(x, y0)
        self._letra(9, "B", NAVY)
        p.cell(ANCHO - 90, 5, "Poblaciones que se priorizan", new_x="LMARGIN", new_y="NEXT")
        if len(pobl):
            self._vinetas([f"{etiqueta(k)}: {fmt_n(v)} ({fmt_pct(pct(v, ind.total))})" for k, v in pobl.items()],
                          tam=8.5, ancho=ANCHO - 90, x=x)
        ods = ind.conteo("ODS").drop(index=["Sin dato"], errors="ignore")
        cad = ind.conteo("Comite de Ayuda al Desarrollo").drop(index=["Sin dato"], errors="ignore")
        alin = []
        if len(ods):
            alin.append(f"el objetivo de desarrollo sostenible más frecuente es {ods.index[0]}")
        if len(cad):
            alin.append(f"el sector más frecuente es {cad.index[0]}")
        if alin:
            p.ln(2)
            p.set_x(x)
            self._letra(8.5)
            p.multi_cell(ANCHO - 90, 4.4, "**Alineación:** " + "; ".join(alin) + ".", align="L", markdown=True,
                         new_x="LMARGIN", new_y="NEXT")
        p.set_y(max(p.get_y(), y_fin_img) + 2)
        self._parrafo(ind.textos["lecturas"]["publico"])

    # -- página 3 -------------------------------------------------------------
    def _tabla_abiertas(self, prox):
        p, ind = self.pdf, self.ind
        anchos = [76, 39, 21, 36]
        p.set_fill_color(*NAVY)
        self._letra(8, "B", (255, 255, 255))
        for w, h in zip(anchos, ("Convocatoria", "Quién la ofrece", "Tipo", "Cierra")):
            p.cell(w, 6, h, border=0, fill=True)
        p.ln(6)
        for k, (_, f) in enumerate(prox.iterrows()):
            nombre = str(f["Nombre de la Convocatoria"]).split(" (")[0]
            nombre = nombre if len(nombre) <= 80 else nombre[:78].rsplit(" ", 1)[0] + "…"
            actor = corto(str(f["Actor"]))
            actor = actor if len(actor) <= 38 else actor[:36].rsplit(" ", 1)[0] + "…"
            dias = (f["Cierre"] - ind.hoy).days
            valores = [nombre, actor, str(f["Modalidad"]).split(" (")[0],
                       f"{f['Cierre']:%d/%m/%Y}" + (f" · {dias} días" if dias <= 30 else "")]
            self._letra(7.8)
            lineas = [len(p.multi_cell(w - 2, 3.8, v, dry_run=True, output="LINES")) for w, v in zip(anchos, valores)]
            alto = max(lineas) * 3.8 + 2
            if p.get_y() + alto > p.h - 16:
                p.add_page()
            x, y = p.l_margin, p.get_y()
            if k % 2:
                p.set_fill_color(*FRANJA)
                p.rect(x, y, sum(anchos), alto, style="F")
            url = str(f.get("Cómo aplicar", ""))
            for i, (w, v) in enumerate(zip(anchos, valores)):
                p.set_xy(x + 1, y + 1)
                if i == 0 and url.startswith("http"):
                    self._letra(7.8, "U", AZUL_ENLACE)
                    p.multi_cell(w - 2, 3.8, v, link=url, align="L")
                elif i == 3 and dias <= 15:
                    self._letra(7.8, "B", ROJO)
                    p.multi_cell(w - 2, 3.8, v, align="L")
                else:
                    self._letra(7.8)
                    p.multi_cell(w - 2, 3.8, v, align="L")
                x += w
            p.set_draw_color(214, 220, 228)
            p.line(p.l_margin, y + alto, p.l_margin + sum(anchos), y + alto)
            p.set_xy(p.l_margin, y + alto)
        p.ln(1)

    def pagina_3(self):
        ind, p = self.ind, self.pdf
        p.add_page()
        self._titulo("Convocatorias abiertas: las que cierran primero", antes=0)
        prox = ind.proximas(8)
        if prox.empty:
            self._parrafo("No hay convocatorias abiertas con fecha límite en los filtros seleccionados.")
        else:
            self._parrafo(f"De las {fmt_n(ind.n['abiertas'])} convocatorias abiertas, estas son las {len(prox)} que cierran "
                          "primero. El nombre lleva a la página oficial para postularse.", alin="L")
            p.ln(1)
            self._tabla_abiertas(prox)
            self._nota("En rojo: cierran en 15 días o menos.")
        cm = ind.cierres_por_mes(6)
        if len(cm) and cm.values.sum():
            self._titulo("¿Cuándo cierran las convocatorias abiertas?", antes=2)
            self._imagen(G.cierres_mes(cm))
        self._parrafo(ind.textos["lecturas"]["abiertas"])
        self._titulo("Notas metodológicas", antes=4)
        filas = [
            ("Oficial / no oficial", "Oficial: la ofrecen gobiernos, agencias de cooperación, Naciones Unidas o bancos "
                                     "multilaterales. No oficial: fundaciones, ONG, universidades o empresas."),
            ("Abierta", f"Su fecha límite es igual o posterior a hoy, {fecha_larga(ind.hoy)}. Las permanentes no tienen fecha "
                        "límite y no se cuentan como próximas a cerrar."),
            ("De dónde salen los datos", f"{self.fuente_datos}: cada convocatoria fue revisada por la DGDCI antes de entrar a "
                                         "la base. Filtros: " + self.filtros + "."),
        ]
        for k, v in filas:
            self._letra(7.8)
            alto = max(len(p.multi_cell(138, 3.8, v, dry_run=True, output="LINES")),
                       len(p.multi_cell(30, 3.8, k, dry_run=True, output="LINES"))) * 3.8 + 2
            x, y = p.l_margin, p.get_y()
            p.set_fill_color(*CLARO)
            p.rect(x, y, 32, alto, style="F")
            p.set_xy(x + 1, y + 1)
            self._letra(7.8, "B", NAVY)
            p.multi_cell(30, 3.8, k, align="L")
            p.set_xy(x + 34, y + 1)
            self._letra(7.8)
            p.multi_cell(138, 3.8, v, align="L")
            p.set_xy(x, y + alto + 0.8)
        self._nota(f"Informe generado automáticamente el {fecha_larga(date.today())}.")

    def construir(self, ruta):
        self.pdf.set_title("Convocatorias internacionales para Colombia")
        self.pdf.set_author("APC-Colombia · DGDCI")
        self.pagina_1()
        self.pagina_2()
        self.pagina_3()
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.pdf.output(str(ruta))
        return ruta
