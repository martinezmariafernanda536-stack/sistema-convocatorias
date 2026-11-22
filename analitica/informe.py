"""Informe automático de convocatorias en Word (y PDF si hay LibreOffice o Word instalado)."""
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import graficos as G
from .datos import PRIVADOS
from .indicadores import CARACTER, corto, etiqueta, fecha_larga, fmt_n, fmt_pct, pct

NAVY = RGBColor(0x0B, 0x25, 0x45)
GRIS = RGBColor(0x52, 0x51, 0x4E)
FUENTE = "Arial"


class Informe:
    def __init__(self, ind, filtros="Sin filtros (todas las convocatorias)", fuente_datos="Sistema de convocatorias de la DGDCI"):
        self.ind = ind
        self.filtros = filtros
        self.fuente_datos = fuente_datos
        self.doc = Document()
        self.n_graf = 0
        self.n_tabla = 0
        self._estilos()

    # -- estilos ---------------------------------------------------------
    def _estilos(self):
        d = self.doc
        sec = d.sections[0]
        sec.page_width, sec.page_height = Cm(21), Cm(29.7)
        for m in ("left_margin", "right_margin"):
            setattr(sec, m, Cm(2.2))
        sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2)
        st = d.styles["Normal"]
        st.font.name = FUENTE
        st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = 1.15
        for nivel, tam in ((1, 16), (2, 12.5)):
            h = d.styles[f"Heading {nivel}"]
            h.font.name, h.font.size, h.font.bold = FUENTE, Pt(tam), True
            h.font.color.rgb = NAVY
            h.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
            h.paragraph_format.space_before = Pt(16 if nivel == 1 else 10)
            h.paragraph_format.space_after = Pt(6)
            h.paragraph_format.keep_with_next = True

    @staticmethod
    def _sombra(celda, color):
        tc = celda._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), color)
        tc.append(shd)

    @staticmethod
    def _sin_bordes(tabla):
        tbl = tabla._tbl
        pr = tbl.tblPr
        bordes = OxmlElement("w:tblBorders")
        for b in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{b}")
            e.set(qn("w:val"), "nil")
            bordes.append(e)
        pr.append(bordes)

    def _texto(self, texto, tam=10.5, color=None, negrita=False, cursiva=False, alin=None, despues=6):
        p = self.doc.add_paragraph()
        r = p.add_run(texto)
        r.font.size, r.bold, r.italic = Pt(tam), negrita, cursiva
        if color:
            r.font.color.rgb = color
        if alin:
            p.alignment = alin
        p.paragraph_format.space_after = Pt(despues)
        return p

    def _grafico(self, titulo, png, nota=None, ancho=16.4):
        self.n_graf += 1
        p = self._texto(f"Gráfico {self.n_graf}. {titulo}", tam=9.5, color=NAVY, negrita=True, despues=2)
        p.paragraph_format.keep_with_next = True
        self.doc.add_picture(png, width=Cm(ancho))
        self.doc.paragraphs[-1].paragraph_format.keep_with_next = True
        fuente = f"Fuente: {self.fuente_datos}, corte al {fecha_larga(self.ind.corte)}." + (f" {nota}" if nota else "")
        self._texto(fuente, tam=8, color=GRIS, despues=10)

    def _tabla(self, titulo, encabezados, filas, anchos):
        self.n_tabla += 1
        p = self._texto(f"Tabla {self.n_tabla}. {titulo}", tam=9.5, color=NAVY, negrita=True, despues=2)
        p.paragraph_format.keep_with_next = True
        t = self.doc.add_table(rows=1, cols=len(encabezados))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(encabezados):
            c = t.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(h)
            r.bold, r.font.size = True, Pt(8.5)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            self._sombra(c, "0B2545")
        for k, fila in enumerate(filas):
            celdas = t.add_row().cells
            for i, v in enumerate(fila):
                celdas[i].text = ""
                r = celdas[i].paragraphs[0].add_run(str(v))
                r.font.size = Pt(8.5)
                if k % 2:
                    self._sombra(celdas[i], "F3F6FA")
        self._anchos(t, anchos)
        self._texto("", despues=4)
        return t

    @staticmethod
    def _anchos(t, anchos):
        """Anchos fijos de columna (Word y LibreOffice los respetan solo así)."""
        t.autofit = False
        grid = t._tbl.tblGrid
        for i, gc in enumerate(grid.findall(qn("w:gridCol"))):
            gc.set(qn("w:w"), str(int(Cm(anchos[i]).twips)))
        for fila in t.rows:
            for i, a in enumerate(anchos):
                fila.cells[i].width = Cm(a)

    def _pie_pagina(self):
        sec = self.doc.sections[0]
        pie = sec.footer.paragraphs[0]
        pie.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = pie.add_run("APC-Colombia · DGDCI  |  Informe de convocatorias internacionales  |  Página ")
        r.font.size, r.font.color.rgb = Pt(8), GRIS
        for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
            run = pie.add_run()
            run.font.size, run.font.color.rgb = Pt(8), GRIS
            if tipo:
                f = OxmlElement("w:fldChar")
                f.set(qn("w:fldCharType"), tipo)
                run._r.append(f)
            else:
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = texto
                run._r.append(it)

    # -- piezas ------------------------------------------------------------
    def _enlace(self, parrafo, texto, url, tam=8.5):
        """Hipervínculo en Word (python-docx no lo trae)."""
        rid = parrafo.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                                     is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        for etiqueta, valor in (("w:color", "1F5FAF"), ("w:u", "single"), ("w:sz", str(int(tam * 2)))):
            e = OxmlElement(etiqueta)
            e.set(qn("w:val"), valor)
            rpr.append(e)
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = texto
        r.append(t)
        h.append(r)
        parrafo._p.append(h)

    def _titulo(self, texto, antes=10):
        p = self._texto(texto, tam=13, color=NAVY, negrita=True, despues=3)
        p.paragraph_format.space_before = Pt(antes)
        p.paragraph_format.keep_with_next = True
        return p

    def _salto(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def _imagen(self, png, ancho=17.2):
        self.doc.add_picture(png, width=Cm(ancho))
        self.doc.paragraphs[-1].paragraph_format.space_after = Pt(2)

    def _lectura(self, texto):
        """Párrafo de análisis debajo de la gráfica: qué muestran las cifras y qué significan."""
        if texto:
            p = self._texto(texto, tam=9.5, despues=6)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def _nota(self, texto):
        return self._texto(texto, tam=7.5, color=GRIS, cursiva=True, despues=6)

    # -- página 1: lo más importante --------------------------------------------
    def encabezado(self):
        ind = self.ind
        t = self.doc.add_table(rows=1, cols=1)
        self._sin_bordes(t)
        c = t.rows[0].cells[0]
        self._sombra(c, "0B2545")
        p = c.paragraphs[0]
        p.paragraph_format.space_before = Pt(8)
        r = p.add_run("APC-COLOMBIA · DGDCI")
        r.font.size, r.bold = Pt(8.5), True
        r.font.color.rgb = RGBColor(0xA9, 0xBC, 0xD6)
        q = c.add_paragraph()
        rr = q.add_run("Convocatorias internacionales para Colombia")
        rr.font.size, rr.bold = Pt(19), True
        rr.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        q = c.add_paragraph()
        q.paragraph_format.space_after = Pt(8)
        rr = q.add_run(f"Becas, subvenciones, premios y cooperación técnica · informe del {fecha_larga(ind.hoy)}")
        rr.font.size = Pt(9.5)
        rr.font.color.rgb = RGBColor(0xCA, 0xDC, 0xFC)
        self._texto("", despues=2)

    def cifras(self):
        n = self.ind.n
        tarjetas = [(fmt_n(self.ind.total), "convocatorias registradas"), (fmt_n(n["abiertas"]), "siguen abiertas"),
                    (fmt_n(n["cierran_30"]), "cierran en los próximos 30 días"), (fmt_n(n["actores"]), "entidades que las ofrecen")]
        tt = self.doc.add_table(rows=1, cols=4)
        self._sin_bordes(tt)
        for i, (num, lab) in enumerate(tarjetas):
            c = tt.rows[0].cells[i]
            self._sombra(c, "EEF3F9")
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(5)
            r = p.add_run(num)
            r.font.size, r.bold = Pt(20), True
            r.font.color.rgb = NAVY
            q = c.add_paragraph()
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            q.paragraph_format.space_after = Pt(5)
            rr = q.add_run(lab)
            rr.font.size = Pt(8)
            rr.font.color.rgb = GRIS
        self._anchos(tt, [4.3] * 4)

    def lo_mas_importante(self):
        self._titulo("Principales resultados", antes=10)
        for m in self.ind.textos["mensajes"]:
            p = self.doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(3)
            p.add_run(m).font.size = Pt(10)
        self._titulo("Tipos de convocatoria y ritmo de registro", antes=8)
        self._imagen(G.panel_resumen(self.ind))
        self._nota("Una convocatoria se cuenta en el mes en que se registró en el sistema. La línea muestra el promedio de tres "
                   "meses; el número en negrita, el mes con más registros.")
        self._lectura(self.ind.textos["lecturas"]["resumen"])


    # -- página 2: quién, qué y para quién ------------------------------------------
    def quien_y_que(self):
        ind = self.ind
        self._titulo("¿Quién ofrece y en qué temas?", antes=0)
        of = ind.df[ind.df["Carácter"] == "Oficial"]["Tipo de actor"].value_counts()
        no = ind.df[ind.df["Carácter"] == "No Oficial"]["Tipo de actor"].value_counts()
        texto = []
        if len(of):
            texto.append(f"En la oferta oficial predominan {of.index[0].lower()} ({fmt_n(of.iloc[0])} convocatorias)")
        if len(no):
            texto.append(f"en la no oficial, {no.index[0].lower()} ({fmt_n(no.iloc[0])})")
        if texto:
            self._texto("; ".join(texto) + ". Una convocatoria puede tener varios temas, por eso los temas no suman el total.",
                        tam=9.5, despues=4)
        self._imagen(G.panel_quien(ind))
        self._lectura(ind.textos["lecturas"]["quien"])
        self._titulo("¿A quién se dirigen?", antes=8)
        pub = ind.conteo("Dirigida a (tipo de publico)", multi=True).drop(index=["Sin dato"], errors="ignore").head(6)
        pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
        pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore").head(5)
        t = self.doc.add_table(rows=1, cols=2)
        self._sin_bordes(t)
        izq, der = t.rows[0].cells
        if len(pub):
            izq.paragraphs[0].add_run().add_picture(G.barras_publico(pub, ind.total), width=Cm(8.4))
        p = der.paragraphs[0]
        r = p.add_run("Poblaciones que se priorizan")
        r.bold, r.font.size = True, Pt(9.5)
        r.font.color.rgb = NAVY
        if len(pobl):
            for k, v in pobl.items():
                q = der.add_paragraph(style="List Bullet")
                q.paragraph_format.space_after = Pt(1)
                q.add_run(f"{etiqueta(k)}: {fmt_n(v)} ({fmt_pct(pct(v, ind.total))})").font.size = Pt(9)
        else:
            der.add_paragraph("Ninguna convocatoria indica una población prioritaria.").runs[0].font.size = Pt(9)
        q = der.add_paragraph()
        q.paragraph_format.space_before = Pt(6)
        cad = ind.conteo("Comite de Ayuda al Desarrollo").drop(index=["Sin dato"], errors="ignore")
        ods = ind.conteo("ODS").drop(index=["Sin dato"], errors="ignore")
        r = q.add_run("Alineación: ")
        r.bold, r.font.size = True, Pt(9)
        r.font.color.rgb = NAVY
        partes = []
        if len(ods):
            partes.append(f"el objetivo de desarrollo sostenible más frecuente es {ods.index[0]}")
        if len(cad):
            partes.append(f"el sector más frecuente es {cad.index[0]}")
        q.add_run(("; ".join(partes) + ".") if partes else "sin datos.").font.size = Pt(9)
        self._anchos(t, [8.8, 8.4])
        self._lectura(ind.textos["lecturas"]["publico"])

    # -- página 3: lo que está abierto --------------------------------------------
    def abiertas(self):
        ind = self.ind
        self._titulo("Convocatorias abiertas: las que cierran primero", antes=0)
        prox = ind.proximas(8)
        if prox.empty:
            self._texto("No hay convocatorias abiertas con fecha límite en los filtros seleccionados.", tam=9.5)
        else:
            self._texto(f"De las {fmt_n(ind.n['abiertas'])} convocatorias abiertas, estas son las {len(prox)} que cierran "
                        "primero. El nombre lleva a la página oficial para postularse.", tam=9.5, despues=4)
            t = self.doc.add_table(rows=1, cols=4)
            t.style = "Table Grid"
            for i, h in enumerate(("Convocatoria", "Quién la ofrece", "Tipo", "Cierra")):
                c = t.rows[0].cells[i]
                c.text = ""
                r = c.paragraphs[0].add_run(h)
                r.bold, r.font.size = True, Pt(8.5)
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                self._sombra(c, "0B2545")
            for k, (_, f) in enumerate(prox.iterrows()):
                celdas = t.add_row().cells
                nombre = str(f["Nombre de la Convocatoria"]).split(" (")[0]
                nombre = nombre if len(nombre) <= 80 else nombre[:78].rsplit(" ", 1)[0] + "…"
                url = str(f.get("Cómo aplicar", ""))
                celdas[0].text = ""
                if url.startswith("http"):
                    self._enlace(celdas[0].paragraphs[0], nombre, url)
                else:
                    celdas[0].paragraphs[0].add_run(nombre).font.size = Pt(8.5)
                dias = (f["Cierre"] - ind.hoy).days
                actor = corto(str(f["Actor"]))
                actor = actor if len(actor) <= 38 else actor[:36].rsplit(" ", 1)[0] + "…"
                valores = (actor, str(f["Modalidad"]).split(" (")[0],
                           f"{f['Cierre']:%d/%m/%Y}" + (f" · {dias} días" if dias <= 30 else ""))
                for i, v in enumerate(valores, start=1):
                    celdas[i].text = ""
                    r = celdas[i].paragraphs[0].add_run(v)
                    r.font.size = Pt(8.5)
                    if i == 3 and dias <= 15:
                        r.bold, r.font.color.rgb = True, RGBColor(0xB4, 0x23, 0x18)
                if k % 2:
                    for c in celdas:
                        self._sombra(c, "F3F6FA")
            self._anchos(t, [7.6, 3.9, 2.1, 3.6])
            self._nota("En rojo: cierran en 15 días o menos.")
        cm = ind.cierres_por_mes(6)
        if len(cm) and cm.values.sum():
            self._titulo("¿Cuándo cierran las convocatorias abiertas?", antes=6)
            self._imagen(G.cierres_mes(cm))
        self._lectura(ind.textos["lecturas"]["abiertas"])

    def como_leer(self):
        self._titulo("Notas metodológicas", antes=8)
        filas = [
            ("Oficial / no oficial", "Oficial: la ofrecen gobiernos, agencias de cooperación, Naciones Unidas o bancos "
                                     "multilaterales. No oficial: fundaciones, ONG, universidades o empresas."),
            ("Abierta", f"Su fecha límite es igual o posterior a hoy, {fecha_larga(self.ind.hoy)}. Las permanentes no tienen "
                        "fecha límite y no se cuentan como próximas a cerrar."),
            ("De dónde salen los datos", f"{self.fuente_datos}: cada convocatoria fue revisada por la DGDCI antes de entrar a "
                                         "la base. Filtros: " + self.filtros + "."),
        ]
        t = self.doc.add_table(rows=0, cols=2)
        self._sin_bordes(t)
        for k, v in filas:
            c = t.add_row().cells
            c[0].text, c[1].text = "", ""
            r = c[0].paragraphs[0].add_run(k)
            r.bold, r.font.size = True, Pt(8.5)
            r.font.color.rgb = NAVY
            self._sombra(c[0], "EEF3F9")
            c[1].paragraphs[0].add_run(v).font.size = Pt(8.5)
        self._anchos(t, [3.6, 13.6])
        self._nota(f"Informe generado automáticamente el {fecha_larga(date.today())}.")

    # -- todo -------------------------------------------------------------
    def construir(self, ruta):
        sec = self.doc.sections[0]
        for m in ("left_margin", "right_margin"):
            setattr(sec, m, Cm(1.9))
        sec.top_margin, sec.bottom_margin = Cm(1.6), Cm(1.5)
        self._pie_pagina()
        self.encabezado()
        self.cifras()
        self.lo_mas_importante()
        self._salto()
        self.quien_y_que()
        self._salto()
        self.abiertas()
        self.como_leer()
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(ruta)
        return ruta


def convertir_pdf(ruta_docx):
    """Convierte a PDF con LibreOffice o con Word (docx2pdf). Devuelve la ruta o None."""
    ruta_docx = Path(ruta_docx)
    candidatos = [os.environ.get("SOFFICE"), shutil.which("soffice"), shutil.which("libreoffice"),
                  r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for exe in [c for c in candidatos if c and Path(c).exists() or (c and shutil.which(c))]:
        try:
            subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(ruta_docx.parent), str(ruta_docx)],
                           check=True, timeout=180, capture_output=True)
            pdf = ruta_docx.with_suffix(".pdf")
            if pdf.exists():
                return pdf
        except (subprocess.SubprocessError, OSError):
            continue
    try:
        from docx2pdf import convert
        convert(str(ruta_docx), str(ruta_docx.with_suffix(".pdf")))
        return ruta_docx.with_suffix(".pdf")
    except Exception:  # noqa: BLE001 - sin Word ni LibreOffice no hay PDF
        return None


def generar(df_preparado, ruta_docx, filtros="Sin filtros (todas las convocatorias)", pdf=True, corte=None):
    from .indicadores import calcular
    ind = calcular(df_preparado, corte)
    ruta = Informe(ind, filtros).construir(ruta_docx)
    ruta_pdf = None
    if pdf:
        try:  # PDF directo en Python: no necesita LibreOffice ni Word
            from .informe_pdf import InformePDF
            ruta_pdf = InformePDF(ind, filtros).construir(Path(ruta).with_suffix(".pdf"))
        except Exception:  # noqa: BLE001 - si falla, se intenta con LibreOffice o Word
            ruta_pdf = convertir_pdf(ruta)
    return ruta, ruta_pdf
