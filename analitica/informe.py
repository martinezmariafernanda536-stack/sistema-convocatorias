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

    # -- secciones ---------------------------------------------------------
    def portada(self):
        ind, n = self.ind, self.ind.n
        t = self.doc.add_table(rows=1, cols=1)
        self._sin_bordes(t)
        c = t.rows[0].cells[0]
        self._sombra(c, "0B2545")
        c.width = Cm(16.6)
        p = c.paragraphs[0]
        p.paragraph_format.space_before = Pt(28)
        r = p.add_run("APC-COLOMBIA · DGDCI")
        r.font.size, r.bold = Pt(10), True
        r.font.color.rgb = RGBColor(0xA9, 0xBC, 0xD6)
        for texto, tam, color, neg in (
            ("Informe de convocatorias internacionales", 26, RGBColor(0xFF, 0xFF, 0xFF), True),
            ("Oferta oficial y no oficial: actores, temáticas, tendencia y alineación", 13, RGBColor(0xCA, 0xDC, 0xFC), False),
        ):
            q = c.add_paragraph()
            q.paragraph_format.space_before = Pt(10)
            rr = q.add_run(texto)
            rr.font.size, rr.bold = Pt(tam), neg
            rr.font.color.rgb = color
        q = c.add_paragraph()
        q.paragraph_format.space_before = Pt(36)
        q.paragraph_format.space_after = Pt(24)
        rr = q.add_run(f"Dirección de Gestión de Demanda de Cooperación Internacional\nCorte al {fecha_larga(ind.corte)}")
        rr.font.size = Pt(10.5)
        rr.font.color.rgb = RGBColor(0xCA, 0xDC, 0xFC)

        self._texto("", despues=10)
        # tarjetas de cifras
        tarjetas = [(fmt_n(ind.total), "convocatorias"), (fmt_n(n["oficial"]), f"oficiales · {fmt_pct(pct(n['oficial'], ind.total))}"),
                    (fmt_n(n["no_oficial"]), f"no oficiales · {fmt_pct(pct(n['no_oficial'], ind.total))}"),
                    (fmt_n(n["actores"]), "actores distintos")]
        tt = self.doc.add_table(rows=1, cols=4)
        self._sin_bordes(tt)
        for i, (num, lab) in enumerate(tarjetas):
            c = tt.rows[0].cells[i]
            self._sombra(c, "F3F6FA")
            c.width = Cm(4.1)
            p = c.paragraphs[0]
            p.paragraph_format.space_before = Pt(8)
            r = p.add_run(num)
            r.font.size, r.bold = Pt(24), True
            r.font.color.rgb = NAVY
            q = c.add_paragraph()
            q.paragraph_format.space_after = Pt(8)
            rr = q.add_run(lab)
            rr.font.size = Pt(9)
            rr.font.color.rgb = GRIS
        self._texto("", despues=6)
        self.doc.add_picture(G.proporcion(n["oficial"], n["no_oficial"]), width=Cm(16.4))
        self._texto(f"Filtros: {self.filtros}", tam=8.5, color=GRIS, cursiva=True, despues=18)
        self._texto("Contenido", tam=11, color=NAVY, negrita=True, despues=4)
        for linea in ("Ficha técnica y resumen ejecutivo", "1. Panorama general: modalidad y tendencia",
                      "2. Cooperación oficial: agencias y tipos de actor",
                      "3. Cooperación no oficial: actores privados y sociedad civil",
                      "4. Temáticas y tendencia internacional", "5. Público dirigido y poblaciones priorizadas",
                      "6. Alineación con el CAD y los ODS", "7. Calidad del dato y notas"):
            self._texto(linea, tam=9.5, color=GRIS, despues=1)
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def ficha_tecnica(self):
        ind, n, inc = self.ind, self.ind.n, self.ind.inconsistencias()
        self.doc.add_heading("Ficha técnica", level=1)
        filas = [
            ("Objetivo", "Caracterizar la oferta de convocatorias internacionales registrada por la DGDCI: quién la ofrece, "
                         "en qué temáticas, para qué público y con qué alineación."),
            ("Fuente de información", self.fuente_datos + "."),
            ("Periodo de referencia", f"Fecha de registro entre el {fecha_larga(n['desde'])} y el {fecha_larga(n['hasta'])}."),
            ("Fecha de corte", fecha_larga(ind.corte)),
            ("Unidad de análisis", "Convocatoria registrada (una fila de la base)."),
            ("Universo", f"{fmt_n(ind.total)} convocatorias de {fmt_n(n['actores'])} actores."),
            ("Filtros aplicados", self.filtros),
            ("Variables", "Oficial / No Oficial, actor (fuente), tipo de actor, modalidad, fecha de registro, áreas temáticas, "
                          "público dirigido, poblaciones priorizadas, CAD y ODS."),
            ("Clasificación oficial / no oficial", "Derivada del tipo de actor: gobiernos, agencias de cooperación, Naciones "
                                                   "Unidas y banca multilateral son oficiales; fundaciones, ONG, academia y "
                                                   "empresas son no oficiales."),
            ("Tipo de actor", "Catálogo de actores del sistema, revisado por la DGDCI."
                              + (f" {fmt_n(inc['tipo_sugerido'])} convocatorias tienen tipo sugerido por reglas." if inc['tipo_sugerido'] else "")),
            ("Control de calidad", "Toda convocatoria pasa por la bandeja de revisión y por 16 reglas de calidad antes de entrar a la base."),
            ("Variables de selección múltiple", "Temáticas, público y poblaciones admiten varios valores por convocatoria; "
                                                "sus conteos no suman el total."),
            ("Tendencia", "Conteos por mes y participación por trimestre según la fecha de registro. "
                          "El último mes o trimestre puede estar incompleto."),
            ("Generado", f"Automáticamente el {fecha_larga(date.today())} con el sistema de convocatorias de la DGDCI."),
        ]
        t = self.doc.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in filas:
            c = t.add_row().cells
            c[0].text, c[1].text = "", ""
            r = c[0].paragraphs[0].add_run(k)
            r.bold, r.font.size = True, Pt(9)
            r.font.color.rgb = NAVY
            self._sombra(c[0], "F3F6FA")
            c[1].paragraphs[0].add_run(v).font.size = Pt(9)
        self._anchos(t, [4.6, 12])

    def resumen(self):
        tx = self.ind.textos
        self.doc.add_heading("Resumen ejecutivo", level=1)
        for clave in ("resumen", "oficial", "no_oficial", "tematicas", "tendencia", "modalidad", "publico", "alineacion"):
            p = self.doc.add_paragraph(style="List Bullet")
            p.add_run(tx[clave]).font.size = Pt(10)

    def panorama(self):
        ind = self.ind
        self.doc.add_heading("1. Panorama general", level=1)
        self._texto(ind.textos["modalidad"])
        self._grafico("Convocatorias por modalidad y carácter", G.barras_por_caracter(ind.por_caracter("Modalidad")))
        self.doc.add_heading("Tendencia de registro", level=2)
        self._texto(ind.textos["tendencia"])
        self._grafico("Convocatorias registradas por mes, oficiales y no oficiales", G.tendencia_mensual(ind.por_mes(), ind.corte),
                      "El área gris marca el mes en curso, todavía incompleto.")

    def oficial(self):
        ind = self.ind
        self.doc.add_heading("2. Cooperación oficial", level=1)
        self._texto(ind.textos["oficial"])
        of = ind.df[ind.df["Carácter"] == "Oficial"]
        if not len(of):
            return
        self._grafico("Convocatorias oficiales por tipo de actor",
                      G.barras_simples(of["Tipo de actor"].value_counts(), G.AZUL, total=len(of)))
        top = ind.actores("Oficial", 12)
        serie = top.set_index("Actor")["Convocatorias"]
        self._grafico("Agencias y actores con más convocatorias oficiales",
                      G.barras_simples(serie, G.AZUL, {a: t.split(" /")[0] for a, t in zip(top["Actor"], top["Tipo de actor"])}))

    def no_oficial(self):
        ind = self.ind
        self.doc.add_heading("3. Cooperación no oficial: actores privados y sociedad civil", level=1)
        self._texto(ind.textos["no_oficial"])
        no = ind.df[ind.df["Carácter"] == "No Oficial"]
        if not len(no):
            return
        self._grafico("Convocatorias no oficiales por tipo de actor",
                      G.barras_simples(no["Tipo de actor"].value_counts(), G.NARANJA, total=len(no)),
                      "Fundaciones, ONG, academia y empresas son los actores privados y de la sociedad civil.")
        top = ind.actores("No Oficial", 12)
        serie = top.set_index("Actor")["Convocatorias"]
        self._grafico("Actores con más convocatorias no oficiales",
                      G.barras_simples(serie, G.NARANJA, {a: t.split(" /")[0] for a, t in zip(top["Actor"], top["Tipo de actor"])}))
        priv = no[no["Tipo de actor"].isin(PRIVADOS)]
        if len(priv):
            filas = []
            for tipo in PRIVADOS:
                g = priv[priv["Tipo de actor"] == tipo].groupby("Actor").size().sort_values(ascending=False)
                if len(g):
                    actores = "; ".join(etiqueta(a).split(" / ")[0] + (f" ({k})" if k > 1 else "") for a, k in g.items())
                    filas.append((tipo, int(g.sum()), actores))
            self._tabla("Actores privados y de la sociedad civil con convocatorias no oficiales",
                        ["Tipo de actor", "Convocatorias", "Actores (entre paréntesis, si tienen más de una)"], filas,
                        [3.4, 2.7, 10.5])

    def tematicas(self):
        ind = self.ind
        self.doc.add_heading("4. Temáticas y tendencia internacional", level=1)
        self._texto(ind.textos["tematicas"])
        self._grafico("Temáticas más frecuentes, oficiales y no oficiales",
                      G.barras_por_caracter(ind.por_caracter("Áreas temáticas de interés", multi=True, top=10)),
                      "Una convocatoria puede tener varias temáticas.")
        conteos, partes = ind.temas_por_trimestre()
        if partes.shape[1] >= 2:
            self.doc.add_heading("Cómo cambian las temáticas en el tiempo", level=2)
            self._texto("El cuadro muestra qué porcentaje de las convocatorias de cada trimestre incluye cada temática "
                        "(entre paréntesis, el número de convocatorias). Un tono más oscuro indica más presencia.")
            self._grafico("Participación de las temáticas principales por trimestre", G.mapa_calor_temas(partes, conteos, ind.corte))

    def publico(self):
        ind = self.ind
        self.doc.add_heading("5. Público dirigido y poblaciones priorizadas", level=1)
        self._texto(ind.textos["publico"])
        self._grafico("Público al que se dirigen las convocatorias",
                      G.barras_por_caracter(ind.por_caracter("Dirigida a (tipo de publico)", multi=True, top=10)),
                      "Una convocatoria puede dirigirse a varios públicos.")
        pobl = ind.conteo("Esta convocatoria prioriza alguna de las siguientes poblaciones?", multi=True)
        pobl = pobl.drop(index=[i for i in pobl.index if i.lower().startswith(("ninguna", "sin dato"))], errors="ignore").head(10)
        if len(pobl):
            self._grafico("Poblaciones priorizadas", G.barras_simples(pobl, G.AZUL, total=ind.total),
                          "Porcentaje sobre el total de convocatorias.")

    def alineacion(self):
        ind = self.ind
        self.doc.add_heading("6. Alineación con el CAD y los ODS", level=1)
        self._texto(ind.textos["alineacion"])
        self._grafico("Sectores CAD más frecuentes", G.barras_por_caracter(ind.por_caracter("Comite de Ayuda al Desarrollo", top=10)))
        self._grafico("Objetivos de Desarrollo Sostenible más frecuentes", G.barras_por_caracter(ind.por_caracter("ODS", top=10)))

    def calidad(self):
        inc = self.ind.inconsistencias()
        self.doc.add_heading("7. Calidad del dato y notas", level=1)
        puntos = []
        if inc["actores_en_ambos"]:
            puntos.append(f"{len(inc['actores_en_ambos'])} actores aparecen a la vez como oficiales y no oficiales: "
                          + ", ".join(corto(a) for a in inc["actores_en_ambos"]) + ". Conviene unificar el criterio.")
        if len(inc["no_oficial_con_actor_publico"]):
            puntos.append(f"{len(inc['no_oficial_con_actor_publico'])} convocatorias no oficiales tienen como actor un gobierno "
                          "o un organismo multilateral (por ejemplo, embajadas, la Unión Europea o la CAF).")
        if inc["sin_actor"]:
            puntos.append(f"{inc['sin_actor']} convocatorias no tienen nombre de actor (fuente marcada como *NUEVO y sin "
                          "nombre en CICLOPE).")
        if inc["por_clasificar"]:
            puntos.append(f"{inc['por_clasificar']} convocatorias tienen un actor sin tipo asignado. Se completa en el "
                          "catálogo de actores del sistema.")
        if inc["sin_fecha_cierre"]:
            puntos.append(f"{inc['sin_fecha_cierre']} convocatorias no tienen fecha límite (incluye las permanentes).")
        puntos.append(f"El monto de financiación mezcla presupuestos totales de convocatorias y montos por proyecto; por eso "
                      f"no se suma. La mediana del monto reportado es USD {fmt_n(self.ind.n['mediana_usd'])} "
                      f"({fmt_n(self.ind.n['con_monto'])} convocatorias con monto).")
        for p in puntos:
            q = self.doc.add_paragraph(style="List Bullet")
            q.add_run(p).font.size = Pt(10)

    # -- todo -------------------------------------------------------------
    def construir(self, ruta):
        self._pie_pagina()
        self.portada()
        self.ficha_tecnica()
        self.resumen()
        self.panorama()
        self.oficial()
        self.no_oficial()
        self.tematicas()
        self.publico()
        self.alineacion()
        self.calidad()
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
    ruta_pdf = convertir_pdf(ruta) if pdf else None
    return ruta, ruta_pdf
