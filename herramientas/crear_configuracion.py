"""Genera config/configuracion_mapeo_becas.xlsx a partir del export de Airtable.

Uso:  python herramientas/crear_configuracion.py ruta/al/export_airtable.csv
Solo se corre una vez (o cuando se quiera regenerar la plantilla). Después,
la configuración se edita directamente en el Excel.
"""
import csv
import io
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "config" / "configuracion_mapeo_becas.xlsx"

AZUL = "0B2545"
VERDE_SUAVE = "E1F3F0"
NARANJA_SUAVE = "FBEBDD"

# ---------------------------------------------------------------------------
# Fuentes semilla
# ---------------------------------------------------------------------------
# Solo se escriben dominios raíz oficiales. La página exacta de becas la
# encuentra el sistema con el comando `validar-fuentes`, para no inventar URLs.
# Las cámaras sin dominio confirmado quedan inactivas hasta que se complete.
CAMARAS = [
    ("CAM-DE", "AHK Colombia - Cámara de Industria y Comercio Colombo-Alemana", "Alemania", "https://kolumbien.ahk.de", "Sí", ""),
    ("CAM-US", "AmCham Colombia - Cámara de Comercio Colombo Americana", "Estados Unidos", "https://www.amchamcolombia.co", "Sí", ""),
    ("CAM-CH", "Swiss Cham Colombia - Cámara de Comercio Colombo Suiza", "Suiza", "", "No",
     "Completar dominio. Referencia: https://www.eda.admin.ch/content/countries/colombia/es/home/bilaterale-beziehungen/wirtschaft-export/swiss-cham-colombia.html"),
    ("CAM-FR", "CCI France Colombia - Cámara de Comercio e Industria Franco Colombiana", "Francia", "", "No", "Completar dominio"),
    ("CAM-UK", "BritCham Colombia - Cámara de Comercio Colombo Británica", "Reino Unido", "", "No", "Completar dominio"),
    ("CAM-ES", "Cámara Oficial Española de Comercio en Colombia", "España", "", "No", "Completar dominio"),
    ("CAM-IT", "Cámara de Comercio Colombo Italiana", "Italia", "", "No", "Completar dominio"),
    ("CAM-JP", "Cámara Colombo Japonesa de Comercio e Industria", "Japón", "", "No", "Completar dominio"),
    ("CAM-CN", "Cámara Colombo China de Inversión y Comercio", "China", "", "No", "Completar dominio"),
    ("CAM-CA", "Cámara de Comercio Colombo Canadiense", "Canadá", "", "No", "Completar dominio"),
    ("CAM-PT", "Cámara de Comercio e Industria Luso Colombiana - CCILC", "Portugal", "", "No", "Completar dominio"),
    ("CAM-KR", "Cámara de Comercio Colombo Coreana", "Corea del Sur", "", "No", "Completar dominio"),
    ("CAM-NL", "Cámara de Comercio Colombo Holandesa", "Países Bajos", "", "No", "Completar dominio"),
]

UNIVERSIDADES = [
    ("UNI-UK-01", "University of Oxford", "Reino Unido", "https://www.ox.ac.uk", "Inglés"),
    ("UNI-UK-02", "University of Cambridge", "Reino Unido", "https://www.cam.ac.uk", "Inglés"),
    ("UNI-UK-03", "University of Edinburgh", "Reino Unido", "https://www.ed.ac.uk", "Inglés"),
    ("UNI-UK-04", "University College London", "Reino Unido", "https://www.ucl.ac.uk", "Inglés"),
    ("UNI-NL-01", "Utrecht University", "Países Bajos", "https://www.uu.nl", "Inglés"),
    ("UNI-NL-02", "Leiden University", "Países Bajos", "https://www.universiteitleiden.nl", "Inglés"),
    ("UNI-NL-03", "Delft University of Technology", "Países Bajos", "https://www.tudelft.nl", "Inglés"),
    ("UNI-NL-04", "University of Amsterdam", "Países Bajos", "https://www.uva.nl", "Inglés"),
    ("UNI-DE-01", "Technische Universität München", "Alemania", "https://www.tum.de", "Alemán"),
    ("UNI-DE-02", "Universität Heidelberg", "Alemania", "https://www.uni-heidelberg.de", "Alemán"),
    ("UNI-FR-01", "Sciences Po", "Francia", "https://www.sciencespo.fr", "Francés"),
    ("UNI-FR-02", "Université Paris-Saclay", "Francia", "https://www.universite-paris-saclay.fr", "Francés"),
    ("UNI-ES-01", "Universidad de Salamanca", "España", "https://www.usal.es", "Español"),
    ("UNI-ES-02", "Universidad Complutense de Madrid", "España", "https://www.ucm.es", "Español"),
    ("UNI-CH-01", "ETH Zürich", "Suiza", "https://ethz.ch", "Inglés"),
    ("UNI-CH-02", "EPFL", "Suiza", "https://www.epfl.ch", "Inglés"),
    ("UNI-SE-01", "Lund University", "Suecia", "https://www.lunduniversity.lu.se", "Inglés"),
    ("UNI-SE-02", "Uppsala University", "Suecia", "https://www.uu.se", "Inglés"),
    ("UNI-BE-01", "KU Leuven", "Bélgica", "https://www.kuleuven.be", "Inglés"),
    ("UNI-IT-01", "Politecnico di Milano", "Italia", "https://www.polimi.it", "Italiano"),
    ("UNI-IT-02", "Università di Bologna", "Italia", "https://www.unibo.it", "Italiano"),
    ("UNI-CA-01", "University of Toronto", "Canadá", "https://www.utoronto.ca", "Inglés"),
    ("UNI-CA-02", "University of British Columbia", "Canadá", "https://www.ubc.ca", "Inglés"),
    ("UNI-US-01", "Stanford University - Knight-Hennessy Scholars", "Estados Unidos", "https://knight-hennessy.stanford.edu", "Inglés"),
    ("UNI-AU-01", "University of Melbourne", "Australia", "https://www.unimelb.edu.au", "Inglés"),
    ("UNI-AU-02", "Australian National University", "Australia", "https://www.anu.edu.au", "Inglés"),
    ("UNI-JP-01", "University of Tokyo", "Japón", "https://www.u-tokyo.ac.jp", "Inglés"),
    ("UNI-KR-01", "KAIST", "Corea del Sur", "https://www.kaist.ac.kr", "Inglés"),
]

PALABRAS_BECA = [
    ("Español", "beca; becas; programa de becas; ayuda económica; ayudas al estudio; convocatoria de becas"),
    ("Inglés", "scholarship; scholarships; fellowship; fellowships; bursary; bursaries; studentship; funding for students; financial aid; award for international students"),
    ("Francés", "bourse; bourses; bourse d'études; bourses d'excellence; aide financière"),
    ("Alemán", "Stipendium; Stipendien; Förderprogramm; Studienförderung"),
    ("Italiano", "borsa di studio; borse di studio; esonero"),
    ("Portugués", "bolsa de estudo; bolsas de estudo; bolsas"),
    ("Neerlandés", "beurs; beurzen; studiebeurs"),
]
PALABRAS_EXCLUSION = (
    "login; log in; sign in; iniciar sesión; news archive; press release; "
    "student loan; préstamo; crédito educativo; staff only; employees only; job; vacancy; empleo"
)

ELEGIBILIDAD = [
    # (Regla, Términos separados por ;, Puntos, Explicación)
    ("Menciona a Colombia", "colombia; colombian; colombiano; colombiana; colombianos; kolumbien; colombie; colombiens", 3,
     "La página nombra a Colombia o a los colombianos."),
    ("Menciona América Latina", "latin america; latin american; américa latina; latinoamérica; latinoamericanos; lateinamerika; amérique latine; south america; sudamérica", 2,
     "La beca está abierta a la región."),
    ("Abierta a internacionales", "all nationalities; any nationality; all countries; international students; international applicants; non-eu; non-eea; outside the eu; todas las nacionalidades; estudiantes internacionales; étudiants internationaux; internationale studierende; developing countries; países en desarrollo; low and middle income countries; lmic; oda-eligible; dac list", 1,
     "Abierta a estudiantes internacionales o de países en desarrollo."),
    ("Restringida a otros", "eu students only; eea students only; uk students only; home students only; home fee status; only for citizens of; must be a citizen of; nationals of the eu; eu/eea nationals; solo para ciudadanos; réservée aux ressortissants; nur für deutsche", -3,
     "Restringe la postulación a nacionalidades que no incluyen a Colombia."),
]

ICETEX_PALABRAS = "icetex; a través del icetex; postúlate en icetex; convocatoria icetex; web.icetex.gov.co"

TEMATICAS = [
    ("Cambio Climático", "climate; clima; climático; climat; klima"),
    ("Medio Ambiente, biodiversidad y conservación", "environment; environmental; biodiversity; conservation; medio ambiente; biodiversidad; ecology; sustainability"),
    ("Salud", "health; medicine; medical; public health; salud; medicina; santé"),
    ("Ciencia, Tecnología , Innovación, Investigación (STEM)", "science; engineering; technology; stem; research; ciencia; ingeniería; tecnología; investigación; physics; chemistry; mathematics"),
    ("Derechos Humanos", "human rights; derechos humanos; droits de l'homme"),
    ("Paz", "peace; paz; conflict resolution; peacebuilding"),
    ("Género", "gender; women; mujeres; género; female"),
    ("Agricultura y Desarrollo Rural", "agriculture; agricultural; rural; agricultura; agronomy; food systems"),
    ("Energía", "energy; energía; renewable; renovable"),
    ("Agua y saneamiento / WASH", "water; sanitation; agua; saneamiento; wash"),
    ("Periodismo", "journalism; journalist; periodismo"),
    ("Arte y cultura", "art; arts; culture; music; cultura; arte; design"),
    ("Liderazgo", "leadership; leaders; liderazgo"),
    ("Emprendimiento", "entrepreneurship; entrepreneur; emprendimiento; startup"),
    ("Desarrollo Económico", "economics; economy; business; management; mba; economía; finance"),
    ("Democracia y Gobernanza", "public policy; governance; government; política pública; gobernanza; public administration; law"),
    ("Habilidades digitales e Inteligencia Artificial", "artificial intelligence; machine learning; ai; digital; computer science; inteligencia artificial"),
    ("Datos", "data science; data; datos; statistics"),
    ("Movilidad Humana (desplazamientos, migraciones, refugiados)", "migration; refugee; refugees; migración; refugiados"),
    ("Desarrollo Sostenible", "sustainable development; desarrollo sostenible; sdg; development studies"),
]

PARAMETROS = [
    ("Reportado por", "Mapeo automático DGDCI", "Valor de la columna 'Reportado por' en Airtable."),
    ("Identificación del programa (User-Agent)", "APC-Colombia DGDCI - mapeo de convocatorias (uso institucional)",
     "Nombre con el que el programa se presenta a cada sitio. No usar correos personales."),
    ("Pausa entre solicitudes (segundos)", 3, "Espera entre una página y otra del mismo sitio."),
    ("Tiempo máximo de espera (segundos)", 20, "Si un sitio no responde en este tiempo, se marca como caído."),
    ("Máximo de páginas de becas por fuente", 3, "Páginas de listado que se revisan por cada fuente."),
    ("Máximo de convocatorias por página", 25, "Enlaces de becas que se abren por cada página de listado."),
    ("Días mínimos antes del cierre", 15, "Convocatorias que cierran antes de este plazo se marcan 'Cierre muy próximo'."),
    ("Umbral de similitud ICETEX (0-100)", 85, "Similitud mínima del nombre para considerar que una beca ya está en ICETEX."),
    ("Umbral de duplicado Airtable (0-100)", 90, "Similitud mínima del nombre para marcar posible duplicado."),
    ("Respetar robots.txt", "Sí", "Si el sitio no permite programas automáticos en esa página, no se lee."),
    ("Usar navegador para páginas dinámicas", "No", "Sí = usa Playwright cuando la página llega vacía. Requiere instalarlo."),
    ("Clave API de búsqueda (variable de entorno)", "BUSCADOR_API_KEY", "Próxima fase: búsqueda abierta de oferentes nuevos con la API de un buscador."),
]


def dividir(v):
    return [x.strip() for x in next(csv.reader(io.StringIO(str(v)), skipinitialspace=True)) if x.strip()]


def encabezado(ws, columnas, anchos):
    ws.append(columnas)
    for i, ancho in enumerate(anchos, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 32


def ajustar(ws):
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def lista(ws, rango, opciones):
    dv = DataValidation(type="list", formula1='"' + ",".join(opciones) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(rango)


def main(ruta_csv):
    df = pd.read_csv(ruta_csv)
    becas = df[df["Modalidad"] == "Beca"]
    wb = Workbook()

    # LEEME --------------------------------------------------------------
    ws = wb.active
    ws.title = "LEEME"
    ws.column_dimensions["A"].width = 120
    lineas = [
        ("Configuración del mapeo de becas internacionales · DGDCI · APC-Colombia", True),
        ("", False),
        ("Este archivo controla qué revisa el sistema y cómo llena las columnas de Airtable. Se edita aquí; el código no se toca.", False),
        ("", False),
        ("Hojas", True),
        ("Fuentes: cámaras binacionales y universidades. 'Activa = Sí' para que se revisen. 'URL de becas' la completa validar-fuentes si está vacía.", False),
        ("Palabras_beca / Palabras_exclusion: términos que identifican un enlace o página de becas, por idioma.", False),
        ("Elegibilidad: reglas que puntúan si un colombiano puede postularse. Puntaje ≥ 2 = Elegible; 1 = Probable; 0 = Revisar; negativo = No elegible.", False),
        ("ICETEX_exclusiones: becas que ya ofrece ICETEX (nombre o URL). Las que coincidan se excluyen.", False),
        ("ICETEX_paginas: páginas de ICETEX con listados de becas en el exterior que el sistema lee para comparar.", False),
        ("Tematicas: palabras que asignan las áreas temáticas del catálogo de Airtable.", False),
        ("Alineacion_sugerida: valores de ENCI, PMI, Sector, ODS, PND y CAD por temática (por defecto, los más usados en becas).", False),
        ("Catalogos: valores permitidos en Airtable, tomados del export actual.", False),
        ("Mapeo_Airtable: cómo se llena cada columna de Airtable.", False),
        ("Parametros: pausas, umbrales y valores por defecto.", False),
        ("", False),
        ("Reglas de oro", True),
        ("1. Solo fuentes oficiales (dominio de la universidad o de la cámara). Agregadores y blogs no se usan.", False),
        ("2. Toda beca debe ser abierta a colombianos y no estar ofrecida por ICETEX.", False),
        ("3. Nada se carga a Airtable sin aprobación humana en el Excel de revisión.", False),
    ]
    for texto, negrita in lineas:
        ws.append([texto])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=negrita, size=14 if ws.max_row == 1 else 11)

    # Fuentes ------------------------------------------------------------
    ws = wb.create_sheet("Fuentes")
    cols = ["ID", "Activa", "Tipo de fuente", "Nombre", "País", "Dominio oficial", "URL de becas",
            "Oficial / No Oficial", "Idioma principal", "Requiere navegador", "Estado de validación",
            "Última validación", "Notas"]
    encabezado(ws, cols, [11, 8, 18, 46, 15, 36, 50, 14, 12, 11, 18, 14, 50])
    for id_, nombre, pais, dom, activa, nota in CAMARAS:
        ws.append([id_, activa, "Cámara binacional", nombre, pais, dom, "", "No Oficial", "Español", "No",
                   "Por validar" if dom else "Falta dominio", "", nota])
    for id_, nombre, pais, dom, idioma in UNIVERSIDADES:
        ws.append([id_, "Sí", "Universidad", nombre, pais, dom, "", "No Oficial", idioma, "No", "Por validar", "", ""])
    ajustar(ws)
    n = ws.max_row
    lista(ws, f"B2:B{n + 200}", ["Sí", "No"])
    lista(ws, f"C2:C{n + 200}", ["Cámara binacional", "Universidad", "Otra fuente oficial"])
    lista(ws, f"H2:H{n + 200}", ["Oficial", "No Oficial"])
    lista(ws, f"J2:J{n + 200}", ["Sí", "No"])

    # Palabras -----------------------------------------------------------
    ws = wb.create_sheet("Palabras_beca")
    encabezado(ws, ["Idioma", "Términos (separados por ;)"], [14, 110])
    for fila in PALABRAS_BECA:
        ws.append(list(fila))
    ajustar(ws)
    ws = wb.create_sheet("Palabras_exclusion")
    encabezado(ws, ["Términos que descartan un enlace (separados por ;)"], [120])
    ws.append([PALABRAS_EXCLUSION])
    ajustar(ws)

    # Elegibilidad -------------------------------------------------------
    ws = wb.create_sheet("Elegibilidad")
    encabezado(ws, ["Regla", "Términos (separados por ;)", "Puntos", "Explicación"], [24, 90, 8, 50])
    for fila in ELEGIBILIDAD:
        ws.append(list(fila))
    ajustar(ws)

    # ICETEX -------------------------------------------------------------
    ws = wb.create_sheet("ICETEX_exclusiones")
    encabezado(ws, ["Nombre de la beca en ICETEX", "URL en ICETEX", "Fecha de registro", "Registrado por"], [60, 60, 16, 22])
    ws = wb.create_sheet("ICETEX_paginas")
    encabezado(ws, ["URL de listado de ICETEX", "Activa", "Notas"], [80, 8, 60])
    ws.append(["", "No", "Pegar aquí la URL de la página de ICETEX con las becas vigentes en el exterior y poner Activa = Sí."])
    ws.append(["Palabras que indican ICETEX en la página de una beca:", "", ICETEX_PALABRAS])
    ajustar(ws)

    # Temáticas y alineación --------------------------------------------
    ws = wb.create_sheet("Tematicas")
    encabezado(ws, ["Área temática (catálogo Airtable)", "Términos (separados por ;)"], [55, 95])
    for fila in TEMATICAS:
        ws.append(list(fila))
    ajustar(ws)

    campos_alin = ["Linea Prioritaria ENCI", "Plan Marco de Implementación", "Sector Gobierno", "ODS",
                   "Metas PND", "Comite de Ayuda al Desarrollo"]
    moda = {c: becas[c].astype(str).str.strip().value_counts().index[0] for c in campos_alin}
    overrides = {
        "Cambio Climático": {"Linea Prioritaria ENCI": "1. Lucha contra el cambio climático y la justicia ambiental y transformación productiva",
                             "Sector Gobierno": "Ambiente y Desarrollo Sostenible", "ODS": "13. Acción por el Clima",
                             "Metas PND": "7. Transformación Productiva, Internacionalización y Acción Climática",
                             "Comite de Ayuda al Desarrollo": "Protección General Del Medio Ambiente"},
        "Salud": {"Sector Gobierno": "Salud y Protección Social", "ODS": "3. Salud y Bienestar", "Comite de Ayuda al Desarrollo": "Salud"},
        "Ciencia, Tecnología , Innovación, Investigación (STEM)": {"Sector Gobierno": "Ciencia, Tecnología e Innovación",
                                                                   "ODS": "9. Industria Innovación e Infrastructura"},
        "Paz": {"Linea Prioritaria ENCI": "3. Cultura de paz, justicia y lucha contra la desigualdad", "Metas PND": "5. Paz Total e Integral",
                "ODS": "16. Promover sociedades justas, pacíficas e inclusivas", "Comite de Ayuda al Desarrollo": "Gobierno Y Sociedad Civil"},
        "Agricultura y Desarrollo Rural": {"Sector Gobierno": "Agricultura y Desarrollo rural", "ODS": "2. Hambre Cero",
                                           "Metas PND": "3. Derecho Humano A La Alimentación", "Comite de Ayuda al Desarrollo": "Agricultura"},
        "Energía": {"Sector Gobierno": "Minas y Energía", "ODS": "7. Energía asequible y no contaminante",
                    "Comite de Ayuda al Desarrollo": "Generación De Energía, Distribución Y Eficiencia"},
    }
    ws = wb.create_sheet("Alineacion_sugerida")
    encabezado(ws, ["Temática"] + campos_alin, [40] + [36] * len(campos_alin))
    ws.append(["(Por defecto)"] + [moda[c] for c in campos_alin])
    for tema, valores in overrides.items():
        ws.append([tema] + [valores.get(c, "") for c in campos_alin])
    ajustar(ws)

    # Catálogos ---------------------------------------------------------
    ws = wb.create_sheet("Catalogos")
    multi = ["Dirigida a (tipo de publico)", "Esta convocatoria prioriza alguna de las siguientes poblaciones?",
             "Áreas temáticas de interés", "Idioma/s"]
    simples = ["Modalidad", "Oficial / No Oficial", "Ámbito Geográfico"] + campos_alin
    catalogos = {}
    for c in multi:
        catalogos[c] = sorted(Counter(x for v in df[c].dropna() for x in dividir(v)))
    for c in simples:
        catalogos[c] = sorted(df[c].dropna().astype(str).str.strip().unique())
    encabezado(ws, list(catalogos), [34] * len(catalogos))
    largo = max(len(v) for v in catalogos.values())
    for i in range(largo):
        ws.append([v[i] if i < len(v) else "" for v in catalogos.values()])

    # Mapeo Airtable ----------------------------------------------------
    ws = wb.create_sheet("Mapeo_Airtable")
    encabezado(ws, ["Columna de Airtable", "Cómo se llena", "Valor / regla"], [52, 18, 90])
    reglas = {
        "Nombre de la Convocatoria": ("Automático", "Título de la página de la beca."),
        "Modalidad": ("Fijo", "Beca"),
        "Fecha de Registro": ("Automático", "Fecha del mapeo (d/m/aaaa)."),
        "Reportado por": ("Parámetro", "Hoja Parametros."),
        "Oficial / No Oficial": ("Por fuente", "Columna 'Oficial / No Oficial' de la hoja Fuentes."),
        "¿La convocatoria es permanente?": ("Automático", "Sí si la página dice 'rolling', 'abierta todo el año' o similar; si no, No."),
        "Fecha Límite de Aplicación": ("Automático", "Fecha detectada cerca de 'deadline', 'fecha límite', 'date limite', 'Bewerbungsschluss'…"),
        "¿Se puede publicar en la web?": ("Revisión", "Vacío: lo marca quien revisa."),
        "Nombre de la Fuente": ("Por fuente", "Nombre de la fuente."),
        "Nombre de actor en CICLOPE": ("Por fuente", "Nombre de la fuente (ajustar al nombre en CICLOPE al revisar)."),
        "Descripción": ("Automático", "Descripción de la página o primeros párrafos."),
        "Objetivos General y Específicos": ("Revisión", "Vacío: se completa al revisar."),
        "Dirigida a (tipo de publico)": ("Automático", "Ciudadanos; + Academia/Universidades si menciona investigadores o docentes; + Funcionarios Públicos si menciona servidores públicos."),
        "Esta convocatoria prioriza alguna de las siguientes poblaciones?": ("Automático", "Mujeres, Jovenes, Indigenas, etc., si la página lo menciona."),
        "Áreas temáticas de interés": ("Automático", "Hoja Tematicas. Siempre incluye Educación."),
        "Financiación": ("Automático", "Mayor monto en USD. Si está en otra moneda queda vacío y el monto se copia en Observaciones para convertirlo al revisar."),
        "Observaciones sobre el financiamiento": ("Automático", "Frase donde aparece el monto o la cobertura."),
        "Ámbito Geográfico": ("Automático", "Global; Regional si es solo para América Latina."),
        "Cómo aplicar": ("Automático", "URL oficial de la beca."),
        "Idioma/s": ("Automático", "Idioma de la página / idioma de enseñanza mencionado."),
        "Observaciones a la fecha límite de aplicación": ("Automático", "Frase donde aparece la fecha límite."),
        "Tiempo de vencimiento es mayor a un mes y una semana": ("Automático", "checked si faltan más de 37 días para el cierre."),
        "Email para mayor información": ("Automático", "Primer correo de contacto de la página; si no hay, 'Sin Email'."),
        "Link de la Fuente Oferente": ("Por fuente", "Dominio oficial de la fuente."),
        "Linea Prioritaria ENCI": ("Sugerido", "Hoja Alineacion_sugerida."),
        "Plan Marco de Implementación": ("Sugerido", "Hoja Alineacion_sugerida."),
        "Sector Gobierno": ("Sugerido", "Hoja Alineacion_sugerida."),
        "ODS": ("Sugerido", "Hoja Alineacion_sugerida."),
        "Metas PND": ("Sugerido", "Hoja Alineacion_sugerida."),
        "Comite de Ayuda al Desarrollo": ("Sugerido", "Hoja Alineacion_sugerida."),
        "VERIFICACIÓN: Colombia hace parte de los países beneficiarios": ("Automático", "checked si la elegibilidad es Elegible."),
        "VERIFICACIÓN: Página web correcta y activa": ("Automático", "checked si la página respondió correctamente."),
        "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria": ("Automático", "checked si tiene nombre, descripción, fecha o permanente, y enlace."),
    }
    columnas_airtable = [c for c in df.columns if df[c].notna().any()]
    for c in columnas_airtable:
        como, valor = reglas.get(c, ("Revisión", "Vacío: se completa en Airtable."))
        ws.append([c, como, valor])
    ajustar(ws)

    # Parámetros --------------------------------------------------------
    ws = wb.create_sheet("Parametros")
    encabezado(ws, ["Parámetro", "Valor", "Para qué sirve"], [44, 60, 80])
    for fila in PARAMETROS:
        ws.append(list(fila))
    ajustar(ws)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    wb.save(SALIDA)
    (RAIZ / "config" / "columnas_airtable.txt").write_text("\n".join(columnas_airtable), encoding="utf-8")
    print(f"Configuración creada: {SALIDA}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/airtable.csv")
