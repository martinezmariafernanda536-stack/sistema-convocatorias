"""Mapeo de convocatorias internacionales para colombianos · DGDCI · APC-Colombia

Comandos:
  python mapeo.py migrar [export.csv]      Carga la base anterior (export de Airtable) en la base propia, corrigiéndola.
  python mapeo.py importar export.csv      Importación masiva: agrega las convocatorias de un export que aún no estén.
  python mapeo.py publicar-base            Sube la base al repositorio privado de datos (GitHub o Hugging Face).
  python mapeo.py crear-usuario --usuario U --nombre N --rol admin|revisor
  python mapeo.py restablecer-clave --usuario U   Contraseña temporal nueva (recuperación de último recurso).
  python mapeo.py generar-clave-cuentas    Valor aleatorio para el secreto USUARIOS_CLAVE.
  python mapeo.py validar-fuentes          Revisa cada fuente: responde, es del oferente y tiene página de convocatorias.
  python mapeo.py mapear                   Busca becas, subvenciones, cooperación técnica y premios y los deja en la bandeja.
  python mapeo.py completar-pendientes    Reintenta las «Por completar» (en otro idioma o incompletas) y limpia duplicados.
  python mapeo.py buscar-externo           Búsqueda externa con Gemini en sitios oficiales que no son fuentes (requiere GEMINI_API_KEY).
  python mapeo.py informe                  Informe automático en Word y PDF con la base propia.
  python mapeo.py auditar [export.csv]     Auditoría de calidad de un export (antes de migrar).
  streamlit run app.py                     Abre el sistema (dashboard, informes, bandeja y base).

Opciones generales:
  --config RUTA        Otro Excel de configuración del mapeo.
  --csv RUTA           Export anterior de Airtable (por defecto datos/airtable_actual.csv).
  --prueba CARPETA     Usa páginas guardadas en esa carpeta en vez de internet (para probar).
  --hoy AAAA-MM-DD     Fecha de referencia (para probar).
  --grupo NOMBRE       Solo las fuentes de un grupo (Universidades, Gobiernos y agencias…). Se puede repetir.
  --fuente ID          Solo una fuente. Se puede repetir.
"""
import argparse
import re
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from motor import config as cfgmod
from motor import extraer, reglas, salidas
from motor import texto as tx
from motor.historial import Historial
from motor.red import Lector, Respuesta

RAIZ = Path(__file__).resolve().parent
log = logging.getLogger("mapeo")


def crear_lector(cfg, args):
    return Lector(
        agente=cfg.p("Identificación del programa (User-Agent)", "APC-Colombia DGDCI mapeo de convocatorias"),
        pausa=getattr(args, "pausa", None) or cfg.p("Pausa entre solicitudes (segundos)", 2),
        espera=min(float(cfg.p("Tiempo máximo de espera (segundos)", 15) or 15), 15),
        respetar_robots=str(cfg.p("Respetar robots.txt", "Sí")).lower().startswith("s"),
        usar_navegador=str(cfg.p("Usar navegador para páginas dinámicas", "No")).lower().startswith("s"),
        carpeta_prueba=args.prueba,
    )


# --- Ganchos para ejecutar desde la aplicación en segundo plano -----------------
import threading  # noqa: E402

ALMACEN = None                 # base compartida con la aplicación (si no, se abre una)
import builtins as _b  # noqa: E402
# la aplicación lo activa con el botón «Detener»; vive fuera del módulo para que siga sirviendo si el módulo se recarga
DETENER = _b.__dict__.setdefault("_mapeo_detener", threading.Event())
AL_GUARDAR = None              # función(tipo, ruta): la aplicación guarda el avance (config, historial) en la base


def _almacen():
    if ALMACEN is not None:
        return ALMACEN
    from bandeja.almacen import abrir
    return abrir()


def _avisar(tipo, ruta):
    if AL_GUARDAR:
        try:
            AL_GUARDAR(tipo, ruta)
        except Exception as e:  # noqa: BLE001 - guardar el avance nunca debe tumbar la ejecución
            log.warning("No se pudo guardar el avance (%s): %s", tipo, e)


# ---------------------------------------------------------------------------
FALLIDAS = ("Sitio no responde", "Bloqueado por robots", "Redirige a otro dominio", "No oficial", "Falta dominio")


def fuentes_a_revisar(cfg, args, solo_activas=True):
    fuentes = [f for f in cfg.fuentes if f.activa or not solo_activas]
    if solo_activas and not getattr(args, "todas", False):
        fallidas = [f for f in fuentes if f.estado_validacion.startswith(FALLIDAS)]
        if fallidas:
            log.info("Se saltan %d fuentes que fallaron en la última validación (sitio bloqueado o sin respuesta).", len(fallidas))
        fuentes = [f for f in fuentes if f not in fallidas]
    grupos = [g.strip().lower() for g in (getattr(args, "grupo", None) or []) if g.strip()]
    if grupos:
        fuentes = [f for f in fuentes if f.grupo.lower() in grupos]
    ids = [i.strip() for i in (getattr(args, "fuente", None) or []) if i.strip()]
    if ids:
        fuentes = [f for f in fuentes if f.id in ids]
    return fuentes


def en_paralelo(cfg, args, fuentes, tarea):
    """Revisa varias fuentes a la vez. La pausa entre páginas se mantiene por sitio (cada fuente tiene su lector)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    hilos = 1 if args.prueba else max(1, int(getattr(args, "paralelo", None) or cfg.p("Fuentes en paralelo", 10) or 1))
    if hilos == 1:
        for f in fuentes:
            if DETENER.is_set():
                log.warning("Detenido: lo revisado hasta aquí ya quedó guardado.")
                return
            yield f, tarea(f)
        return
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(tarea, f): f for f in fuentes}
        for fut in as_completed(futuros):
            if DETENER.is_set():
                for otro in futuros:
                    otro.cancel()
                log.warning("Detenido: se terminan las fuentes que ya estaban en curso; lo revisado ya quedó guardado.")
                return
            try:
                yield futuros[fut], fut.result()
            except Exception as e:  # noqa: BLE001 - una fuente con error no detiene las demás
                log.warning("%-10s error inesperado: %s", futuros[fut].id, e)


def _palabras_nombre(nombre):
    vacias = {"de", "la", "el", "los", "las", "del", "y", "para", "the", "of", "and", "for", "en", "un", "una",
              "university", "universidad", "universite", "universitat", "fundacion", "foundation", "gobierno", "agencia"}
    return [w for w in tx.normalizar(nombre).replace("-", " ").replace("/", " ").split() if len(w) >= 3 and w not in vacias]


def validar_una(f, cfg, args):
    """Devuelve (estado, url_convocatorias, nombre_del_sitio)."""
    from calidad.dominios import clasificar
    if not f.dominio:
        return "Falta dominio", "", ""
    categoria, _ = clasificar(f.dominio, f.dominio)
    if categoria in ("Acortador", "Agregador / intermediario", "ICETEX"):
        return f"No oficial ({categoria}): cambiar el dominio", "", ""
    lector = crear_lector(cfg, args)
    inicio = lector.leer(f.dominio, forzar_navegador=f.requiere_navegador)
    if inicio.estado == -1:
        return "Bloqueado por robots.txt", "", ""
    if not inicio.ok:
        return f"Sitio no responde ({inicio.estado})", "", ""
    if not extraer.es_del_dominio(inicio.url, f.dominio):
        return f"Redirige a otro dominio: {inicio.url}", "", ""
    sitio = extraer.nombre_del_sitio(inicio.html)
    palabras = _palabras_nombre(f.nombre)
    identifica = not palabras or any(tx.contiene(tx.normalizar(sitio + " " + inicio.url), w) for w in palabras)
    paginas, _ = extraer.descubrir_paginas(f, lector, cfg)
    estado = "Activa" if paginas else "Sin página de convocatorias: completar URL a mano"
    if not identifica:
        estado += " · confirmar que el sitio es del oferente (el título no lo nombra)"
    return estado, "; ".join(paginas) if not f.url_becas else "", sitio


def validar_fuentes(cfg, args):
    respaldo = cfg.ruta.with_name(cfg.ruta.stem + "_respaldo.xlsx")
    shutil.copy(cfg.ruta, respaldo)
    wb = load_workbook(cfg.ruta)
    ws = wb["Fuentes"]
    cab = [c.value for c in ws[1]]
    col = {n: cab.index(n) + 1 for n in cab if n}
    col_url = col.get("URL de convocatorias") or col.get("URL de becas")
    hoy = args.hoy.strftime("%d/%m/%Y")
    fuentes = fuentes_a_revisar(cfg, args, solo_activas=False)
    log.info("Validando %d fuentes…", len(fuentes))
    hechas = 0
    for f, (estado, urls, sitio) in en_paralelo(cfg, args, fuentes, lambda f: validar_una(f, cfg, args)):
        hechas += 1
        if urls:
            ws.cell(row=f.fila, column=col_url).value = urls
        ws.cell(row=f.fila, column=col["Estado de validación"]).value = estado
        ws.cell(row=f.fila, column=col["Última validación"]).value = hoy
        if "Nombre del sitio" in col and sitio:
            ws.cell(row=f.fila, column=col["Nombre del sitio"]).value = sitio
        log.info("%-10s %-55s %s   [%d de %d]", f.id, f.nombre[:55], estado, hechas, len(fuentes))
        if hechas % 10 == 0:  # se guarda el avance: si se interrumpe, no se pierde lo validado
            wb.save(cfg.ruta)
            _avisar("config", cfg.ruta)
    wb.save(cfg.ruta)
    _avisar("config", cfg.ruta)
    log.info("Configuración actualizada: %s (respaldo en %s)", cfg.ruta.name, respaldo.name)


# ---------------------------------------------------------------------------
def candidato_fechas(datos, hoy):
    f = lambda d: f"{d.day}/{d.month}/{d.year}" if d else ""  # noqa: E731
    return {"¿La convocatoria es permanente?": "Si" if datos.get("permanente") else "No",
            "Fecha Límite de Aplicación": f(datos.get("cierre")), "Fecha de Registro": f(hoy)}


def _aniversario(ref, hoy):
    """Días que faltan para el aniversario de la fecha `ref` (entre -60 y 305: negativo = pasó hace poco)."""
    try:
        aniv = ref.replace(year=hoy.year)
    except ValueError:  # 29 de febrero
        aniv = ref.replace(year=hoy.year, day=28)
    d = (aniv - hoy).days
    return d + 365 if d < -60 else d - 365 if d > 305 else d


TEMPORADA = (-60, 120)  # desde 2 meses después hasta 4 meses antes del aniversario del cierre anterior


def url_de(valor):
    """La dirección dentro de «Cómo aplicar», aunque venga con texto («Debe ingresar a … en el link https://…»)."""
    v = str(valor or "").strip()
    m = re.search(r"https?://[^\s<>\"')\]]+", v) or re.search(r"(?<![\w@.])www\.[\w-]+(\.[\w-]+)+[^\s<>\"')\]]*", v)
    if not m:
        return ""
    if m.group(0).startswith("www."):
        return ("https://" + m.group(0)).rstrip(".,;:")
    url = re.split(r"(?<=.)/?https?://", m.group(0))[0]  # dos enlaces pegados: se toma el primero
    return url.rstrip(".,;:")


def url_siguiente_edicion(url, hoy):
    """Si la dirección trae el año de la edición («becas-2026-2027»), la de la edición siguiente («becas-2027-2028»)."""
    anos = [int(a) for a in re.findall(r"(?<!\d)(20\d\d)(?!\d)", url)]
    if not anos or max(anos) > hoy.year + 1:
        return ""
    return re.sub(r"(?<!\d)(20\d\d)(?!\d)", lambda m: str(int(m.group(1)) + 1), url)


def pagina_para_seguir(d):
    """La página oficial que se vuelve a abrir: «Cómo aplicar»; si es un formulario, un PDF, un inicio de sesión o no
    está, el «Link de la Fuente Oferente» (si no es solo la portada del sitio)."""
    from motor.radar import descartable
    for campo in ("Cómo aplicar", "Link de la Fuente Oferente"):
        url = url_de(d.get(campo))
        if url.lower().startswith("http") and not url.lower().split("?")[0].endswith(".pdf") and not descartable(url):
            return url
    return ""


def _seguibles(base, hoy):
    """Convocatorias de la base que pueden repetirse: no permanentes, ya cerradas y con página oficial.

    Devuelve {url: (días al aniversario, fila)}; si la misma página tiene una edición todavía abierta, no se sigue."""
    from calidad.reglas import fecha as _fecha
    abiertas, por_url = set(), {}
    for d in base or []:
        url = pagina_para_seguir(d)
        if not url:
            continue
        if str(d.get("¿La convocatoria es permanente?") or "").strip().lower().startswith("s"):
            continue
        cierre = _fecha(d.get("Fecha Límite de Aplicación"))
        registro = _fecha(d.get("Fecha de Registro"))
        if cierre and cierre >= hoy:
            abiertas.add(url)  # sigue abierta: no hay nueva edición que buscar
            continue
        if not cierre and (not registro or registro.year >= hoy.year):
            continue
        faltan = _aniversario(cierre or registro, hoy)
        previo = por_url.get(url)
        if previo is None or abs(faltan - 30) < abs(previo[0] - 30):
            por_url[url] = (faltan, d)
    return {u: v for u, v in por_url.items() if u not in abiertas}


def ediciones_a_seguir(base, fuentes, historial, hoy, limite=60, cada=14, fuera_de_temporada=60):
    """Convocatorias de la base (incluidas las que vinieron de Airtable) que ya cerraron y pueden abrir una nueva edición.

    Se vuelve a abrir su página oficial («Cómo aplicar») aunque las páginas de las fuentes ya no la enlacen.
    - En temporada (desde 4 meses antes hasta 2 meses después del aniversario de su cierre anterior) se revisa cada
      `cada` días: es cuando las convocatorias anuales publican la edición nueva.
    - Fuera de temporada, cada `fuera_de_temporada` días, por si cambió de calendario.
    Primero las de temporada que nunca se han revisado. Devuelve {id de fuente: (fuente, [(url, nombre)])}."""
    from motor.config import Fuente
    por_url = {}
    for url, (faltan, d) in _seguibles(base, hoy).items():
        en_temporada = TEMPORADA[0] <= faltan <= TEMPORADA[1]
        dias = historial.dias_desde_seguimiento(url, hoy.isoformat())
        if dias is not None and dias < (cada if en_temporada else fuera_de_temporada):
            continue
        por_url[url] = ((not en_temporada, dias is not None, abs(faltan - 30)), d)
    elegidas = sorted(por_url.items(), key=lambda kv: kv[1][0])[: max(0, int(limite))]
    salida = {}
    for url, (_, d) in elegidas:
        f = next((f for f in fuentes if extraer.es_del_dominio(url, f.dominio or f.url_becas)), None)
        if f is None:  # el sitio no está entre las fuentes: se usa una fuente provisional con los datos de la base
            host = extraer.dominio_base(url)
            if not host:
                continue
            nombre = str(d.get("Nombre de la Fuente") or d.get("Nombre de actor en CICLOPE") or host)
            f = Fuente(id="SEG-" + host, activa=True, tipo="Seguimiento de ediciones", nombre=nombre, pais="",
                       dominio=host, url_becas=url, oficial=str(d.get("Oficial / No Oficial") or "No Oficial"),
                       idioma="", requiere_navegador=False, fila=0,
                       actor=str(d.get("Nombre de actor en CICLOPE") or ""))
        nombre = str(d.get("Nombre de la Convocatoria") or "")
        salida.setdefault(f.id, (f, []))[1].append((url, nombre))
        otra = url_siguiente_edicion(url, hoy)
        if otra:  # la edición siguiente suele publicarse en la misma dirección con el año cambiado
            salida[f.id][1].append((otra, nombre))
    return salida


def estado_seguimiento(base, items, seguidas, hoy):
    """Tablero del seguimiento año tras año: qué pasó este ciclo con cada convocatoria de la base que se repite.

    base: filas aprobadas; items: todo lo que hay en el sistema (para ver si ya llegó la edición nueva);
    seguidas: {url: fecha de la última revisión} del historial. Devuelve una lista de diccionarios."""
    from rapidfuzz import fuzz, process
    from calidad.reglas import fecha as _fecha, variantes_nombre
    import unicodedata
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
    norm = lambda t: " ".join("".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())  # noqa: E731
                                      if unicodedata.category(c) != "Mn").split())
    vigentes, urls_vigentes = [], set()  # ediciones de este ciclo: abiertas o llegadas en los últimos 10 meses
    limite = (hoy - pd.Timedelta(days=300)).isoformat()
    for i in items:
        if i.get("estado") == "Descartada":
            continue
        d = i["datos"]
        cierre = _fecha(d.get("Fecha Límite de Aplicación"))
        if (cierre and cierre >= hoy) or (not cierre and str(i.get("ingreso", ""))[:10] >= limite and
                                          not str(i.get("origen", "")).startswith("Migración")):
            vigentes.extend(norm(v) for v in variantes_nombre(d.get("Nombre de la Convocatoria", "")))
            urls_vigentes.add(url_de(d.get("Cómo aplicar")))
    vigentes = [v for v in vigentes if v]
    salida = []
    seg = _seguibles(base, hoy)
    for d in base or []:
        url = pagina_para_seguir(d)
        if url in seg and seg[url][1] is not d:
            continue  # misma página en varias filas: se cuenta una vez
        nombre = d.get("Nombre de la Convocatoria", "")
        if str(d.get("¿La convocatoria es permanente?") or "").lower().startswith("s"):
            continue
        cierre = _fecha(d.get("Fecha Límite de Aplicación"))
        if cierre and cierre >= hoy:
            continue  # sigue abierta: es la edición vigente
        fila = {"Convocatoria": nombre, "Oferente": d.get("Nombre de la Fuente", ""), "Cierre anterior":
                d.get("Fecha Límite de Aplicación", ""), "Página oficial": url}
        if url not in seg:
            fila |= {"Estado": "Sin página oficial para seguirla", "Mes de cierre anterior": "", "Última revisión": "",
                     "Página oficial": url_de(d.get("Cómo aplicar")) or str(d.get("Cómo aplicar") or "")[:120]}
            salida.append(fila)
            continue
        faltan = seg[url][0]
        ref = cierre or _fecha(d.get("Fecha de Registro"))
        fila["Mes de cierre anterior"] = meses[ref.month - 1] if ref else ""
        ya = url in urls_vigentes or any(
            process.extractOne(norm(v), vigentes, scorer=fuzz.token_set_ratio, score_cutoff=92)
            for v in variantes_nombre(nombre) if norm(v) and vigentes)
        cuando = seguidas.get(url, "")
        fila["Última revisión"] = cuando
        if ya:
            fila["Estado"] = "Edición nueva ya en el sistema"
        elif cuando:
            fila["Estado"] = "Revisada: aún sin edición nueva"
        elif TEMPORADA[0] <= faltan <= TEMPORADA[1]:
            fila["Estado"] = "En temporada: se revisa en la próxima búsqueda"
        else:
            fila["Estado"] = "Fuera de temporada: se revisará al acercarse"
        salida.append(fila)
    return salida


def revisar_fuente(fuente, cfg, args, icetex, duplicados, conocidas=frozenset(), completa=True, seguir=(), solo_seguir=False):
    """Lee una fuente y devuelve sus hallazgos sin tocar nada compartido (se puede correr en paralelo).

    Modo rápido (completa=False): solo se abren las convocatorias que no se habían visto antes; las conocidas
    se marcan como «siguen publicadas» sin volver a abrirlas."""
    hoy = args.hoy
    lector = crear_lector(cfg, args)
    # seguir: páginas que se abren directamente aunque la fuente no las enlace: (url, nombre[, html ya leído[, origen]])
    seguir = [tuple(x) + (None,) * (4 - len(x)) for x in seguir]
    forzar = {x[0] for x in seguir}
    if solo_seguir or fuente.tipo == "Seguimiento de ediciones":
        paginas, nota = [], "Seguimiento de ediciones"
    else:
        paginas, nota = extraer.descubrir_paginas(fuente, lector, cfg)
    hallazgos, analizadas, leida, vistas, sin_cambios = [], 0, False, set(), []
    terminos = cfg.palabras_de(fuente.modalidades)

    def analizar(r, url, texto_enlace, pagina, seccion_de="", contexto=""):
        nonlocal analizadas
        analizadas += 1
        if not seccion_de:  # si la página tiene versión en español, se usa esa (menos traducción, mejor información)
            es = extraer.version_en_espanol(r.html, r.url)
            if es and es not in vistas and extraer.es_del_dominio(es, fuente.dominio or r.url):
                r_es = lector.leer(es, forzar_navegador=fuente.requiere_navegador)
                if r_es.ok:
                    vistas.add(es)
                    r = r_es
        datos = extraer.analizar_beca(r, fuente, cfg, hoy, texto_enlace)
        if contexto:  # lo general de la página (calendario, cómo aplicar) solo como contexto para Gemini, no para las fechas
            datos["texto_pagina"] = (datos.get("texto_pagina", "") + "\n\nInformación general de la página (vale para todas "
                                     "sus convocatorias): " + contexto)[:15000]
        if not datos["titulo"]:
            datos["titulo"] = texto_enlace
        elig = reglas.elegibilidad(datos["texto_norm"], cfg)
        # ICETEX solo ofrece becas: la exclusión no aplica a subvenciones, cooperación técnica ni premios
        en_icetex = icetex.revisar(datos["titulo"], r.url, datos) if datos["modalidad"] == "Beca" else (False, "No aplica (no es beca)")
        dup = duplicados.revisar(datos["titulo"], r.url, candidato_fechas(datos, hoy))
        fila = salidas.fila_airtable(datos, r.url, fuente, pagina, cfg, elig, en_icetex, dup, hoy)
        fila["_texto"] = datos.get("texto_pagina", "")
        fila["_enlace"] = url
        if seccion_de:
            fila["[Sistema] Página donde se encontró"] = f"{seccion_de} (sección de una página con varias convocatorias)"
        motivo = ("Está en ICETEX: " + en_icetex[1] if en_icetex[0] else
                  "No elegible para colombianos: " + elig[2] if elig[0] == "No elegible" else
                  dup if dup.startswith("Ya está en la base") else
                  "Convocatoria vencida: " + datos["evidencia_cierre"] if datos["vencida"] else "")
        hallazgos.append(("descartada" if motivo else "revision", r.url, fila, motivo))

    def por_secciones(r, pagina):
        """Si la página reúne varias convocatorias (desplegables, pestañas o secciones), analiza cada una por separado."""
        secs = extraer.secciones(r.html, r.url, terminos)
        if not secs:
            return False
        contexto = extraer.contexto_general(r.html, terminos)
        lang = (re.search(r"<html[^>]*\blang=[\"']?([\w-]+)", r.html[:2000], re.I) or [None, ""])[1]
        base_url = r.url.split("#")[0]
        for titulo, ancla, contenido in secs:
            url_s = f"{base_url}#{ancla}"
            if url_s in vistas:
                continue
            vistas.add(url_s)
            if not completa and url_s in conocidas and url_s not in forzar:
                sin_cambios.append(url_s)
                continue
            sub = Respuesta(url=url_s, estado=200, html=extraer.html_de_seccion(titulo, contenido, "", lang))
            analizar(sub, url_s, titulo, pagina, seccion_de=r.url, contexto=contexto)
        return True

    for pagina in paginas:
        resp = lector.leer(pagina, forzar_navegador=fuente.requiere_navegador)
        if not resp.ok:
            nota += f" | {pagina} no respondió ({resp.estado})"
            continue
        leida = True
        # la página de convocatorias puede tener a la vez desplegables con convocatorias y enlaces a otras páginas:
        # se revisan las dos cosas
        vistas.add(resp.url)
        con_secciones = por_secciones(resp, pagina)
        cands = extraer.candidatas(resp.html, resp.url, fuente, cfg)
        if not cands and not con_secciones:  # la página misma puede ser la convocatoria
            cands = [(resp.url, "")]
            vistas.discard(resp.url)
        for url, texto_enlace in cands:
            if url in vistas:
                continue
            vistas.add(url)
            if not completa and url in conocidas and url not in forzar:
                sin_cambios.append(url)
                continue
            if url.lower().endswith(".pdf"):
                hallazgos.append(("revision", url, salidas.fila_pdf(url, texto_enlace, fuente, pagina, cfg, hoy), ""))
                continue
            r = resp if url == resp.url else lector.leer(url, forzar_navegador=fuente.requiere_navegador)
            if not r.ok:
                continue
            if r is not resp and por_secciones(r, pagina):
                continue
            analizar(r, url, texto_enlace, pagina)
    # seguimiento de ediciones: las que las páginas de la fuente ya no enlazan se abren directamente
    seguidas = []
    from motor import radar as _radar
    for url, nombre, html_listo, origen in seguir:
        if DETENER.is_set():
            break
        seguidas.append(url)
        if url in vistas:
            continue
        vistas.add(url)
        base_url, _, ancla = url.partition("#")
        r = (Respuesta(url=url, estado=200, html=html_listo) if html_listo else
             lector.leer(base_url, forzar_navegador=fuente.requiere_navegador))
        if not r.ok:
            continue
        if fuente.tipo == _radar.TIPO_DESCUBIERTA:
            if _radar.descartable(r.url):  # el enlace terminó en un agregador, una red social o un formulario
                continue
            if fuente.nombre in (fuente.dominio, fuente.dominio.replace("https://", "")):
                fuente.nombre = _radar.nombre_del_sitio(r.html) or fuente.nombre
        leida = leida or solo_seguir or fuente.tipo == "Seguimiento de ediciones"
        origen = origen or f"{base_url} (seguimiento de una convocatoria de la base)"
        if ancla and not html_listo:  # era una sección de una página con varias convocatorias: se busca esa sección
            secs = {a: (t, c) for t, a, c in extraer.secciones(r.html, r.url, terminos)}
            if ancla not in secs:
                continue
            t, c = secs[ancla]
            lang = (re.search(r"<html[^>]*\blang=[\"']?([\w-]+)", r.html[:2000], re.I) or [None, ""])[1]
            sub = Respuesta(url=url, estado=200, html=extraer.html_de_seccion(t, c, "", lang))
            analizar(sub, url, t, origen, seccion_de=base_url, contexto=extraer.contexto_general(r.html, terminos))
        else:
            analizar(r, url, nombre, origen)
    return {"paginas": paginas, "seguidas": seguidas, "nota": nota, "analizadas": analizadas, "leida": leida, "hallazgos": hallazgos,
            "sin_cambios": sin_cambios, "completa": completa}


def revisar_radar(radar, cfg, args, icetex, duplicados, conocidas=frozenset()):
    """Descubrir: lee un agregador (solo como radar) o el portal de la UE y analiza las páginas OFICIALES que encuentra."""
    from motor import radar as R
    lector = crear_lector(cfg, args)
    res = {"paginas": [], "nota": "", "analizadas": 0, "leida": False, "hallazgos": [], "sin_cambios": [], "completa": False}
    objetivos = {}  # url oficial -> (nombre, html ya armado o None, origen)
    if radar.tipo == R.TIPO_UE:
        maximo = int(cfg.p("Convocatorias del portal de la UE por búsqueda", 30) or 30)
        items, nota = R.portal_ue(maximo, args.hoy, getattr(args, "prueba", None))
        res["nota"], res["leida"] = nota, bool(items) or not nota
        for url, titulo, html in items:
            if url not in conocidas:
                objetivos[url] = (titulo, html, f"{radar.nombre} (búsqueda pública del portal)")
    else:
        maximo = int(cfg.p("Publicaciones a revisar por agregador", 40) or 40)
        posts, vistos = [], set()
        for pagina in radar.url_becas.split(";"):
            r = lector.leer(pagina, forzar_navegador=radar.requiere_navegador)
            if not r.ok:
                res["nota"] += f" | {pagina} no respondió ({r.estado})"
                continue
            res["leida"] = True
            res["paginas"].append(pagina)
            for u, t in R.publicaciones(r.html, r.url, maximo * 2):
                if u not in vistos and u not in conocidas:
                    vistos.add(u)
                    posts.append((u, t))
        pendientes, abiertas = posts[:maximo], 0
        while pendientes and abiertas < maximo * 2 and not DETENER.is_set():
            post, _ = pendientes.pop(0)
            abiertas += 1
            res["sin_cambios"].append(post)  # la publicación queda anotada: no se vuelve a abrir en otra búsqueda
            r = lector.leer(post, forzar_navegador=radar.requiere_navegador)
            if not r.ok:
                continue
            externos, internos = R.enlaces_oficiales(r.html, r.url)
            for u, t in externos:
                if u not in conocidas:
                    objetivos.setdefault(u, (t, None, f"{post} (encontrada en {radar.nombre}; se registra la página oficial)"))
            for u, t in internos:  # resúmenes («30 becas abiertas»): sus enlaces llevan a otras publicaciones del agregador
                if u not in vistos and u not in conocidas:
                    vistos.add(u)
                    pendientes.append((u, t))
    por_fuente = {}
    for url, (nombre, html, origen) in objetivos.items():
        f = R.fuente_para(url, cfg.fuentes)
        por_fuente.setdefault(f.id, (f, []))[1].append((url, nombre, html, origen))
    for f, lista in por_fuente.values():
        if DETENER.is_set():
            break
        sub = revisar_fuente(f, cfg, args, icetex, duplicados, conocidas, completa=False, seguir=lista, solo_seguir=True)
        res["analizadas"] += sub["analizadas"]
        res["hallazgos"].extend(sub["hallazgos"])
    res["nota"] = (res["nota"].strip(" |") + f" | {len(objetivos)} páginas oficiales en {len(por_fuente)} sitios").strip(" |")
    return res


def fuentes_sugeridas(pool):
    """Sitios oficiales que no están entre las fuentes y aportaron convocatorias en el descubrimiento."""
    sug = {}
    for f in pool:
        fid = str(f.get("[Sistema] Fuente ID", ""))
        if not fid.startswith("RAD-") or f.get("[Sistema] Resultado") == "Descartada al leerla":
            continue
        s = sug.setdefault(fid, {"Oferente": f.get("Nombre de la Fuente") or fid[4:], "Dominio oficial": "https://" + fid[4:],
                                 "Tipo de actor": "Por clasificar", "País": "", "Actor en el catálogo": "",
                                 "Oficial / No Oficial": f.get("Oficial / No Oficial", ""), "_n": 0, "_b": 0, "_c": []})
        s["_n"] += 1
        s["_b"] += f.get("[Sistema] Resultado") == "Enviada a la bandeja"
        s["_c"].append(str(f.get("Nombre de la Convocatoria", ""))[:90])
    salida = []
    for s in sorted(sug.values(), key=lambda s: (-s["_b"], -s["_n"])):
        salida.append({k: v for k, v in s.items() if not k.startswith("_")} | {
            "Llegaron a la bandeja": s["_b"], "Candidatas": s["_n"], "Convocatorias encontradas": "; ".join(s["_c"][:5])})
    return salida


def mapear(cfg, args):
    hoy = args.hoy
    icetex = reglas.IndiceIcetex(cfg, crear_lector(cfg, args))
    for nota in icetex.notas:
        log.warning(nota)
    base = _almacen().base()
    df_air = pd.DataFrame(base) if base else (pd.read_csv(args.csv) if args.csv and Path(args.csv).exists() else None)
    if df_air is None:
        log.warning("La base está vacía: no se revisarán duplicados.")
    duplicados = reglas.IndiceAirtable(df_air, cfg.p("Umbral de duplicado Airtable (0-100)", 90))
    import os
    historial = Historial(os.environ.get("MAPEO_HISTORIAL") or RAIZ / "datos" / "historial.json")

    descubrir = getattr(args, "modo", "") == "descubrir"
    fuentes = [] if descubrir else fuentes_a_revisar(cfg, args)
    radares = [r for r in cfg.radar if r.activa] if descubrir else []
    if descubrir and not radares:
        log.warning("No hay agregadores ni portales activos en la hoja «Radar» de la configuración.")
    conocidas = frozenset(historial.conocidas())
    cada = int(cfg.p("Días entre revisiones completas", 30) or 30)
    completa = {f.id: bool(getattr(args, "completo", False)) or (d := historial.dias_desde_completa(f.id, hoy.isoformat())) is None
                or d >= cada for f in fuentes}
    n_rapidas = sum(1 for v in completa.values() if not v)
    if descubrir:
        log.info("Descubriendo convocatorias fuera de las fuentes en %d sitios de radar (%s). Solo se registran las "
                 "páginas oficiales de los oferentes, nunca las del agregador.", len(radares),
                 ", ".join(r.nombre for r in radares))
    else:
        log.info("Revisando %d fuentes (becas, subvenciones, cooperación técnica y premios)…", len(fuentes))
    if n_rapidas:
        log.info("Modo rápido en %d fuentes: solo se abren las convocatorias nuevas. Las demás %d tienen revisión completa "
                 "(cada %d días).", n_rapidas, len(fuentes) - n_rapidas, cada)
    from calidad.reglas import CATALOGOS
    from motor import externo
    usar_gemini = (not getattr(args, "sin_gemini", False)
                   and str(cfg.p("Completar campos con Gemini en el mapeo", "Sí")).lower().startswith("s")
                   and bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("MAPEO_GEMINI_PRUEBA_COMPLETAR")))
    # meta: cuántas convocatorias completas deben llegar a la bandeja; tope: consultas a Gemini, para cuidar el cupo diario
    meta = int(getattr(args, "maximo_nuevas", None) or cfg.p("Convocatorias completas por búsqueda", 20) or 20)
    tope = int(cfg.p("Máximo de consultas a Gemini por búsqueda", 120) or 120)
    maximo_nuevas = meta
    externo.reiniciar_corrida()
    CONTEO.update(bandeja=0, por_completar=0, duplicadas=0)
    if descubrir:
        pass  # el descubrimiento usa todo el cupo de Gemini en lo nuevo
    elif not getattr(args, "sin_bandeja", False) and usar_gemini:
        # primero, unas pocas de las que quedaron pendientes (y se limpia la bandeja de duplicados e incompletas)
        completar_pendientes(cfg, args, hoy, maximo=max(5, maximo_nuevas // 4))
    elif not getattr(args, "sin_bandeja", False):
        limpiar_bandeja(_almacen(), hoy)
    if not usar_gemini:
        log.info("Sin Gemini en esta corrida: solo pasan las convocatorias que ya están en español y completas en su página; "
                 "las demás se vuelven a considerar en la próxima búsqueda con Gemini.")

    # 1b. seguimiento de ediciones: convocatorias de la base ya cerradas cuya página se vuelve a abrir (año tras año)
    seguir = {}
    n_seg = int(cfg.p("Ediciones anteriores a revisar por búsqueda", 60) or 0)
    registros_base = df_air.fillna("").to_dict("records") if df_air is not None else []
    if not descubrir and registros_base and n_seg > 0 and not getattr(args, "fuente", None) and not getattr(args, "grupo", None):
        seguir = ediciones_a_seguir(registros_base, fuentes, historial, hoy, n_seg)
        total = sum(len(v[1]) for v in seguir.values())
        if total:
            log.info("Seguimiento de ediciones: se vuelven a abrir %d convocatorias de la base ya cerradas, para ver si "
                     "publicaron una nueva edición (primero las que están en su temporada de apertura).", total)
    extra = [f for f, _ in seguir.values() if f not in fuentes] + radares

    # 1. recorrer las fuentes y reunir candidatas (todavía no se guarda nada en la bandeja)
    filas, descartadas, resumen, leidas, vistas, pool = [], [], [], set(), set(), []
    enviadas_total = hechas = 0
    todas = fuentes + extra
    seg_tot = [0, 0]
    def tarea(f):
        if f in radares:
            return revisar_radar(f, cfg, args, icetex, duplicados, conocidas)
        return revisar_fuente(f, cfg, args, icetex, duplicados, conocidas, completa.get(f.id, False),
                              seguir.get(f.id, (f, []))[1])
    for fuente, res in en_paralelo(cfg, args, todas, tarea):
        hechas += 1
        for url in res.get("seguidas", []):
            historial.marcar_seguida(url, hoy.isoformat())
        for url in res["sin_cambios"]:
            historial.marcar_visto(url, fuente.id, hoy.isoformat())
        if res["completa"] and res["leida"] and fuente in fuentes:
            historial.marcar_completa(fuente.id, hoy.isoformat())
        revision = desc = 0
        if res["leida"] and fuente in fuentes:  # las provisionales del seguimiento no cuentan para «ya no aparecen»
            leidas.add(fuente.id)
        for tipo, url, fila, motivo in res["hallazgos"]:
            if url in vistas:  # la misma convocatoria publicada en dos fuentes
                continue
            vistas.add(url)
            enlace = fila.pop("_enlace", url)
            if tipo == "descartada":  # descartada por las reglas: no hace falta volver a abrirla
                historial.registrar(url, fuente.id, fila, hoy.isoformat())
                if enlace != url:
                    historial.marcar_visto(enlace, fuente.id, hoy.isoformat())
                descartadas.append((motivo, fila["Nombre de la Convocatoria"], url, fuente.id))
                desc += 1
                continue
            estado = historial.estado(url, fila)
            if estado == "Sin cambios":
                historial.registrar(url, fuente.id, fila, hoy.isoformat())
                continue
            fila["[Sistema] Estado"] = estado
            fila["_url"], fila["_enlace"] = url, enlace
            fila["_fuente"] = fila.get("[Sistema] Fuente ID") or fuente.id  # en el radar, el sitio oficial (no el agregador)
            fila["[Sistema] Resultado"] = "Para la próxima búsqueda (no alcanzó el cupo de esta)"
            pool.append(fila)
            revision += 1
        historial.guardar()
        _avisar("historial", historial.ruta)
        resumen.append((fuente.id, fuente.nombre, fuente.tipo, len(res["paginas"]), res["analizadas"], revision, desc, res["nota"]))
        if fuente not in fuentes and fuente not in radares:  # abierto solo por el seguimiento de ediciones: se resume al final
            seg_tot[0] += res["analizadas"]
            seg_tot[1] += revision
            continue
        log.info("%-10s páginas %d · abiertas %d · ya conocidas %d · candidatas %d · descartadas %d   [%d de %d]", fuente.id,
                 len(res["paginas"]), res["analizadas"], len(res["sin_cambios"]), revision, desc, hechas, len(todas))

    if seguir:
        urls_seg = {u for _, lista in seguir.values() for u, _ in lista}
        nuevas_ed = [f for f in pool if f["_url"] in urls_seg]
        for f in nuevas_ed:
            f["[Sistema] Estado"] = "Nueva edición (seguimiento)"
        log.info("Seguimiento de ediciones: %d revisadas; %d publicaron una edición nueva o cambiaron y pasan a completarse "
                 "(las demás siguen cerradas: se vuelven a mirar en 14 días si están en temporada, o en 60 si no).", len(urls_seg), len(nuevas_ed))

    # 2. elegir las mejores candidatas: no hace falta traer cientos; mejor pocas y completas
    # la misma convocatoria publicada en varios idiomas en el mismo sitio: se deja una (en español si la hay)
    from calidad.entrada import idioma as _idioma
    por_nucleo, unicas = {}, []
    for f in sorted(pool, key=lambda f: (_idioma(f["Nombre de la Convocatoria"]) != "es", -prioridad(f, hoy))):
        clave = (f["_fuente"], extraer.nucleo(f["Nombre de la Convocatoria"].split(" (")[0]))
        if len(clave[1]) >= 2 and clave in por_nucleo:
            f["[Sistema] Resultado"] = "Misma convocatoria en otro idioma: se usó «" + por_nucleo[clave][:80] + "»"
            historial.registrar(f["_url"], f["_fuente"], f, hoy.isoformat())
            continue
        if len(clave[1]) >= 2:
            por_nucleo[clave] = f["Nombre de la Convocatoria"]
        unicas.append(f)
    if len(unicas) < len(pool):
        log.info("%d candidatas eran la misma convocatoria en otro idioma: no se gastan consultas en ellas.", len(pool) - len(unicas))
    elegidas = sorted(unicas, key=lambda f: prioridad(f, hoy), reverse=True)
    log.info("Se encontraron %d candidatas. Se completan, de la más prometedora a la menos (abiertas, con fecha y elegibles "
             "primero), hasta que %d lleguen completas a la bandeja.", len(unicas), meta)

    # 3. completar (traducir con Gemini) y guardar solo lo que quede completo, hasta llegar a la meta
    consultas, motivo_fin, no_conv = 0, "", {}
    sin_exito, ultimo_conteo, sin_consultar = 0, 0, 0
    for k, fila in enumerate(elegidas, 1):
        if DETENER.is_set():
            log.warning("Detenido: lo completado hasta aquí ya quedó guardado.")
            motivo_fin = "se detuvo"
            break
        if CONTEO["bandeja"] >= meta and not getattr(args, "sin_bandeja", False):
            break  # meta cumplida: las demás candidatas quedan para la próxima búsqueda
        if usar_gemini and consultas >= tope:
            motivo_fin = f"se llegó al tope de {tope} consultas a Gemini por búsqueda"
            break
        if usar_gemini and externo.SUSPENDIDO["motivo"]:
            log.warning("Gemini dejó de responder (%s): las %d candidatas restantes se consideran en la próxima búsqueda.",
                        externo.SUSPENDIDO["motivo"][:200], len(elegidas) - k + 1)
            motivo_fin = "Gemini dejó de responder: " + externo.SUSPENDIDO["motivo"][:160]
            break
        if usar_gemini and sin_exito >= 30:
            motivo_fin = ("30 consultas seguidas no trajeron ninguna convocatoria completa: las candidatas que quedan son poco "
                          "prometedoras (noticias, listados, páginas sin fecha). Se detuvo para no gastar el cupo de Gemini")
            break
        url, fuente_id = fila["_url"], fila["_fuente"]
        if (razon := parece_no_convocatoria(fila, hoy)):
            historial.registrar(url, fuente_id, fila, hoy.isoformat())
            fila["[Sistema] Resultado"] = "Descartada al leerla"
            descartadas.append(("No es una convocatoria (sin consultar a Gemini): " + razon, fila["Nombre de la Convocatoria"],
                                url, fuente_id))
            sin_consultar += 1
            continue
        if no_conv.get(fuente_id, 0) >= 3:  # esa fuente solo devuelve menús o páginas generales: no gastar más consultas
            fila["[Sistema] Resultado"] = "Para la próxima búsqueda (su fuente devolvió páginas sin convocatoria)"
            continue
        if not str(fila.get("_texto", "")).strip():  # un PDF u otra página sin texto legible: no se puede completar sola
            historial.registrar(url, fuente_id, fila, hoy.isoformat())
            fila["[Sistema] Resultado"] = "Descartada al leerla"
            descartadas.append(("Documento sin texto legible (por ejemplo, un PDF): revisarlo a mano si interesa",
                                fila["Nombre de la Convocatoria"], url, fuente_id))
            continue
        intento_gemini = False
        if usar_gemini:
            consultas += 1
            sin_exito = 0 if CONTEO["bandeja"] > ultimo_conteo else sin_exito + 1
            ultimo_conteo = CONTEO["bandeja"]
            intento_gemini = externo.completar_mapeo([fila], cfg, CATALOGOS, hoy, maximo=1) > 0
            if not intento_gemini and externo.SUSPENDIDO["motivo"]:
                fila["[Sistema] Resultado"] = "Para la próxima búsqueda (Gemini no respondió)"
                continue  # se avisa arriba en la siguiente vuelta
            v = fila.get("_veredicto") or {}
            from calidad.reglas import fecha as _fecha
            cierre = _fecha(fila.get("Fecha Límite de Aplicación", ""))
            if cierre and cierre < hoy and not str(fila.get("¿La convocatoria es permanente?", "")).lower().startswith("s"):
                v = v | {"estado": "cerrada", "motivo": v.get("motivo") or f"la fecha límite ({fila['Fecha Límite de Aplicación']}) ya pasó"}
            if not v.get("es_convocatoria", True):
                no_conv[fuente_id] = no_conv.get(fuente_id, 0) + 1
            motivo = ("No es una convocatoria: " if not v.get("es_convocatoria", True) else
                      "No elegible para Colombia: " if v.get("colombia") == "no elegible" else
                      "Convocatoria cerrada: " if v.get("estado") == "cerrada" else "")
            if motivo:
                historial.registrar(url, fuente_id, fila, hoy.isoformat())
                fila["[Sistema] Resultado"] = "Descartada al leerla"
                descartadas.append((motivo + (v.get("motivo") or "según la lectura de Gemini"), fila["Nombre de la Convocatoria"],
                                    url, fuente_id))
                log.info("  Descartada al leerla: %s · %s", fila["Nombre de la Convocatoria"][:60], motivo + v.get("motivo", "")[:120])
                log.info("  Completas {%d de %d} · consultas a Gemini %d · resultado: a la bandeja %d · por completar %d",
                         min(CONTEO["bandeja"], meta), meta, consultas, CONTEO["bandeja"], CONTEO["por_completar"])
                continue
        if not getattr(args, "sin_bandeja", False):
            # sin Gemini, lo incompleto no se guarda: se vuelve a considerar cuando Gemini pueda completarlo
            origen_b = ("Descubrimiento fuera de las fuentes" if descubrir else
                        "Mapeo automático · nueva edición" if fila.get("[Sistema] Estado") == "Nueva edición (seguimiento)"
                        else "Mapeo automático")
            guardada = enviar_a_bandeja(cfg, [fila], origen=origen_b, guardar_incompletas=intento_gemini)
            if not guardada["guardada"]:
                if guardada["motivo"] == "duplicada":
                    historial.registrar(url, fuente_id, fila, hoy.isoformat())
                    fila["[Sistema] Resultado"] = "Ya registrada este año"
                else:
                    fila["[Sistema] Resultado"] = "Incompleta o en otro idioma: se completa en una búsqueda con Gemini"
                continue
            enviadas_total += guardada["a_bandeja"]
            fila["[Sistema] Resultado"] = "Enviada a la bandeja" if guardada["a_bandeja"] else "Por completar"
        else:
            fila["[Sistema] Resultado"] = "Encontrada (prueba sin bandeja)"
        historial.registrar(url, fuente_id, fila, hoy.isoformat())
        if fila["_enlace"] != url:
            historial.marcar_visto(fila["_enlace"], fuente_id, hoy.isoformat())
        historial.guardar()
        _avisar("historial", historial.ruta)
        log.info("  Completas {%d de %d} · consultas a Gemini %d · resultado: a la bandeja %d · por completar %d",
                 min(CONTEO["bandeja"], meta), meta, consultas, CONTEO["bandeja"], CONTEO["por_completar"])
    if sin_consultar:
        log.info("%d candidatas se descartaron sin gastar consultas a Gemini (noticias, ganadores, resultados o ediciones "
                 "pasadas).", sin_consultar)
    if CONTEO["bandeja"] < meta and not getattr(args, "sin_bandeja", False):
        motivo_fin = motivo_fin or ("no había más candidatas nuevas en las fuentes" if usar_gemini else
                                    "Gemini está apagado: solo pasa lo que ya está en español y completo")
        log.warning("Llegaron %d de las %d convocatorias completas buscadas: %s.", CONTEO["bandeja"], meta, motivo_fin)
    filas = [f for f in pool if f["[Sistema] Resultado"] != "Descartada al leerla"]  # el reporte muestra todo lo encontrado
    for f in pool:
        for c in ("_texto", "_url", "_enlace", "_fuente", "_veredicto"):
            f.pop(c, None)

    retiradas = historial.retiradas(leidas)
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"{'descubrimiento' if descubrir else 'revision'}_{hoy.isoformat()}.xlsx"
    salidas.escribir_revision(ruta, filas, descartadas, resumen, retiradas)
    if descubrir:
        sug = fuentes_sugeridas(filas)
        with pd.ExcelWriter(ruta, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
            pd.DataFrame(sug, columns=["Oferente", "Dominio oficial", "Oficial / No Oficial", "Llegaron a la bandeja",
                                       "Candidatas", "Convocatorias encontradas", "Tipo de actor", "País",
                                       "Actor en el catálogo"]).to_excel(w, sheet_name="Fuentes sugeridas", index=False)
        if sug:
            log.info("Fuentes sugeridas: %d sitios oficiales que no están entre las fuentes aportaron convocatorias "
                     "(el administrador puede agregarlos desde la página de búsqueda).", len(sug))
    historial.guardar()
    log.info("Listo: %d candidatas encontradas, %d descartadas por las reglas, %d ya no aparecen en su sitio.", len(filas),
             len(descartadas), len(retiradas))
    if not getattr(args, "sin_bandeja", False):
        log.info("%d convocatorias completas enviadas a la bandeja de revisión; %d quedaron «Por completar» y %d ya estaban "
                 "registradas este año.", enviadas_total, CONTEO["por_completar"], CONTEO["duplicadas"])
        log.info("Reporte de la corrida: %s", ruta.name)
    return ruta


def enviar_a_bandeja(cfg, filas, origen="Mapeo automático", guardar_incompletas=True):
    """Las convocatorias mapeadas nunca van directo a la base: entran a la bandeja para revisión humana.
    Devuelve {"guardada", "a_bandeja", "motivo"}."""
    from bandeja import flujo
    almacen = _almacen()
    from calidad.reglas import IndiceDuplicados
    ya = IndiceDuplicados(i["datos"] for i in almacen.items())  # incluye descartadas: lo descartado este año no vuelve
    with almacen.lote(f"{origen}: {len(filas)} convocatorias"):
        return _enviar(cfg, filas, origen, almacen, ya, flujo, guardar_incompletas)


def _meta(fila):
    return {"elegibilidad": f"{fila['[Sistema] Elegibilidad Colombia']} · {fila['[Sistema] Motivo elegibilidad']}",
            "modalidad": fila.get("[Sistema] Motivo modalidad", ""),
            "icetex": f"{fila['[Sistema] ¿Está en ICETEX?']} {fila['[Sistema] Motivo ICETEX']}".strip(),
            "pagina": fila["[Sistema] Página donde se encontró"], "nivel": fila["[Sistema] Nivel"],
            "duplicado": fila["[Sistema] Duplicado en Airtable"], "alerta_cierre": fila["[Sistema] Alerta de cierre"],
            "gemini": fila.get("[Sistema] Propuesta de Gemini", "")}


def _datos_de(cfg, fila):
    from calidad.reglas import CAMPO_APERTURA, CAMPO_REQUISITOS
    datos = {c: fila.get(c, "") for c in cfg.columnas_airtable}
    for extra in ("Tipo de monto", CAMPO_APERTURA, CAMPO_REQUISITOS):
        if fila.get(extra):
            datos[extra] = fila[extra]
    # Las verificaciones las confirma quien revisa, no el programa
    for c in ("VERIFICACIÓN: Colombia hace parte de los países beneficiarios", "VERIFICACIÓN: Página web correcta y activa",
              "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria"):
        datos[c] = ""
    return datos


CONTEO = {"bandeja": 0, "por_completar": 0, "duplicadas": 0}


_ADMINISTRATIVAS = ("tuition", "fees", "cost calculator", "calculadora", "student employment", "empleo estudiantil",
                    "returning students", "current students", "financial aid materials", "consumer", "disclosure", "policy",
                    "política", "politica", "matrícula", "matricula", "tarifas", "how to pay", "refund", "faq",
                    "preguntas frecuentes", "contact", "contacto", "news", "noticias", "events", "eventos", "terms and conditions",
                    "términos y condiciones", "privacy", "privacidad", "login", "apply now", "admissions")


_NO_CONV_TITULO = re.compile(
    r"(\S\s+(recibe|receives|wins|gana)\s.{0,40}\b(premio|beca|award|prize|galard[oó]n|reconocimiento|fellowship))|"
    r"\b(anuncia\w*|announc\w*|congratulat\w*|felicita\w*|celebrates)\b|"
    r"\b(ganadores|winners|finalistas|finalists|seleccionad[oa]s|premiad[oa]s)\b|"
    r"\bresultados de (la |las |los )?(convocatoria|selecci[oó]n|evaluaci[oó]n)|\b(selection )?results (of|announced)\b|"
    r"\b(informe de resultados|annual report|informe anual|newsletter|bolet[ií]n|webinar|podcast|entrevista|interview|"
    r"cohorte actual|current cohort|meet the|conoce a|about us|qui[eé]nes somos|our story|nuestra historia|"
    r"testimonios?|testimonials?)\b", re.I)
_LLAMADO = re.compile(r"\b(convocatoria|call for|apply|postula|applications? (are )?open|abiertas?|open call)\b", re.I)
_NO_CONV_RUTA = re.compile(r"/(news|noticias|press|prensa|press-releases?|blog|stories|historias|events?|eventos|"
                           r"podcasts?|webinars?|winners|ganadores|finalists|about-us|acerca-de|"
                           r"quienes-somos|annual-report|informe-anual|testimonials)(/|$)", re.I)


def parece_no_convocatoria(fila, hoy):
    """Noticias, ganadores, resultados, informes o ediciones de años pasados: se descartan sin gastar una consulta.

    Solo si la página no trae una fecha límite futura (una convocatoria abierta nunca se descarta por el título)."""
    from calidad.reglas import fecha as a_fecha
    cierre = a_fecha(fila.get("Fecha Límite de Aplicación", ""))
    if cierre and cierre >= hoy:
        return ""
    titulo = str(fila.get("Nombre de la Convocatoria", ""))
    if (m := _NO_CONV_TITULO.search(titulo)) and not _LLAMADO.search(titulo):
        return f"el título indica una noticia o un resultado («{m.group(0).strip()[:40]}»)"
    from urllib.parse import urlparse
    ruta = urlparse(str(fila.get("_url", ""))).path
    if m := _NO_CONV_RUTA.search(ruta):
        return f"la página está en la sección «{m.group(1)}» del sitio (noticias, eventos o resultados)"
    anos = [int(a) for a in re.findall(r"(?<!\d)(20\d\d)(?!\d)", titulo)]
    if anos and max(anos) < hoy.year:
        return f"es de una edición pasada ({max(anos)})"
    return ""


def prioridad(fila, hoy):
    """Qué candidatas completar primero: abiertas con fecha próxima, elegibles y con página rica en información."""
    from calidad.reglas import fecha as a_fecha
    p = 0.0
    elig = str(fila.get("[Sistema] Elegibilidad Colombia", ""))
    p += {"Elegible": 3, "Probable": 1.5}.get(elig, 0)
    if str(fila.get("[Sistema] Duplicado en Airtable", "")).startswith("Nueva edición") or \
            fila.get("[Sistema] Estado") == "Nueva edición (seguimiento)":
        p += 8  # edición nueva de una convocatoria que ya está en la base: se completa antes que cualquier otra
    cierre = a_fecha(fila.get("Fecha Límite de Aplicación", ""))
    if cierre and cierre >= hoy:
        dias = (cierre - hoy).days
        p += 3 + (1 if 7 <= dias <= 120 else 0)
    elif str(fila.get("¿La convocatoria es permanente?", "")).lower().startswith("s"):
        p += 1.5
    from motor.extraer import nucleo
    titulo = str(fila.get("Nombre de la Convocatoria", "")).lower()
    if any(w in titulo for w in _ADMINISTRATIVAS):
        p -= 6  # matrícula, costos, empleo estudiantil, políticas, formularios: casi nunca son convocatorias
    propias = nucleo(fila.get("Nombre de la Convocatoria", "").split(" (")[0])
    if not propias:
        p -= 5  # «Call for Proposals», «Grants Calls», «Becas»: casi siempre una página de listado, no una convocatoria
    elif len(propias) == 1:
        p -= 1
    largo = len(str(fila.get("_texto", "")))
    p += 1 if largo > 1500 else (-2 if largo < 400 else 0)
    if "título" in str(fila.get("[Sistema] Motivo modalidad", "")).lower():
        p += 0.5
    if str(fila.get("_url", "")).lower().endswith(".pdf"):
        p -= 1
    return p


def _enviar(cfg, filas, origen, almacen, ya, flujo, guardar_incompletas=True):
    """Solo pasa a la bandeja lo que llega en español y completo; lo demás queda «Por completar» (fuera de la bandeja),
    o no se guarda si guardar_incompletas es False. Lo que ya está en el sistema para el mismo año no entra."""
    from calidad import entrada
    from calidad.reglas import buscar_duplicado
    catalogo, base = almacen.catalogo(), almacen.base()
    res = {"guardada": False, "a_bandeja": 0, "motivo": ""}
    for fila in filas:
        if fila.get("[Sistema] Estado") == "Sin cambios":
            continue
        tipo, otro = ya.buscar(fila) if hasattr(ya, "buscar") else buscar_duplicado(fila, ya)
        if tipo in ("mismo_año", "nombre_mismo_año"):
            CONTEO["duplicadas"] += 1
            res["motivo"] = "duplicada"
            log.info("  Ya registrada este año (no entra): %s = %s", fila["Nombre de la Convocatoria"][:60],
                     (otro or {}).get("Nombre de la Convocatoria", "")[:60])
            continue
        datos = _datos_de(cfg, fila)
        meta = _meta(fila)
        norm, hallazgos = flujo.evaluar(almacen, datos, catalogo=catalogo, base=base)
        faltan = entrada.faltantes(norm, hallazgos)
        if faltan and not guardar_incompletas:
            res["motivo"] = "incompleta"
            continue
        if faltan:  # el texto de la página no se guarda (haría pesada la base); al reintentar se vuelve a leer
            meta |= {"faltantes": faltan, "intentos": 1}
            CONTEO["por_completar"] += 1
            log.info("  Por completar (no pasa a la bandeja): %s · falta: %s", fila["Nombre de la Convocatoria"][:60],
                     "; ".join(faltan)[:200])
        flujo.ingresar(almacen, datos, f"{origen} · {fila.get('[Sistema] Fuente ID', '')}", origen, meta,
                       estado=entrada.ESTADO if faltan else "Por revisar", catalogo=catalogo, base=base)
        ya.agregar(datos) if hasattr(ya, "agregar") else ya.append(datos)
        res["guardada"] = True
        if not faltan:
            res["a_bandeja"] += 1
            CONTEO["bandeja"] += 1
    return res


def _texto_de_la_pagina(lector, url):
    from motor.extraer import _sopa, _texto_visible
    import unicodedata
    r = lector.leer(url)
    return unicodedata.normalize("NFC", _texto_visible(_sopa(r.html)))[:12000] if r.ok else ""


def limpiar_bandeja(almacen, hoy=None):
    """Lo que llegó solo y nadie ha tocado: se descarta si es un duplicado del mismo año y vuelve a «Por completar»
    si no está en español o le faltan datos. Lo que una persona ya editó no se mueve. Cada convocatoria se revisa
    una sola vez (queda marcada), y los duplicados se buscan con un índice: sirve igual con miles."""
    from bandeja import flujo
    from calidad import entrada
    from calidad.reglas import IndiceDuplicados
    todos = sorted(almacen.items(), key=lambda i: i["ingreso"])
    por_revisar = [i for i in todos if i["estado"] in ("Por revisar", entrada.ESTADO) and flujo.es_automatica(i)
                   and not flujo.tocada_por_persona(i) and not i["meta"].get("limpieza")]
    if not por_revisar:
        return 0, 0
    log.info("Revisando %d convocatorias automáticas de la bandeja (duplicados e incompletas)…", len(por_revisar))
    catalogo, base = almacen.catalogo(), almacen.base()
    indice = IndiceDuplicados()
    posicion, orden = {}, {}
    for n, item in enumerate(todos):
        indice.agregar(item["datos"])
        posicion[item["id"]] = n
        orden[id(item["datos"])] = n
    duplicadas = devueltas = 0
    with almacen.lote("Limpieza de la bandeja"):
        for item in por_revisar:
            n = posicion[item["id"]]
            tipo, otro = indice.buscar(item["datos"], excluir=item["datos"])
            anterior = otro is not None and orden.get(id(otro), n + 1) < n
            cambio = False
            if tipo in ("mismo_año", "nombre_mismo_año") and anterior:
                flujo.descartar(almacen, item, "Sistema", "Duplicado: ya estaba registrada este año como «"
                                + (otro or {}).get("Nombre de la Convocatoria", "")[:90] + "»")
                duplicadas += 1
                continue
            if item["estado"] == "Por revisar":
                norm, hallazgos = flujo.evaluar(almacen, item["datos"], hoy, catalogo, base)
                faltan = entrada.faltantes(norm, hallazgos)
                if faltan:
                    item["estado"] = entrada.ESTADO
                    item["meta"] |= {"faltantes": faltan, "intentos": 0}
                    flujo._evento(item, "Sistema", "Ingreso", "Devuelta a «Por completar»: " + "; ".join(faltan)[:300])
                    devueltas += 1
                    cambio = True
            if item["meta"].pop("texto_pagina", None) is not None:
                cambio = True
            item["meta"]["limpieza"] = True
            almacen.guardar_item(item)
    log.info("Limpieza: %d duplicadas descartadas y %d incompletas o en otro idioma sacadas de la bandeja.", duplicadas, devueltas)
    return duplicadas, devueltas


def completar_pendientes(cfg, args, hoy=None, maximo=None):
    """Vuelve a intentar las convocatorias «Por completar»: Gemini lee su página y, si quedan en español y completas,
    pasan a la bandeja. Devuelve (pasaron, siguen)."""
    from bandeja import flujo
    from calidad import entrada
    from calidad.reglas import CATALOGOS, buscar_duplicado
    from motor import externo
    hoy = hoy or getattr(args, "hoy", None) or date.today()
    almacen = _almacen()
    limpiar_bandeja(almacen, hoy)
    forzar = getattr(args, "reintentar_todas", False)
    pendientes = [i for i in almacen.items(entrada.ESTADO) if forzar or i["meta"].get("intentos", 0) < entrada.INTENTOS_MAXIMOS]
    if getattr(args, "sin_gemini", False) or not pendientes:
        return 0, len(pendientes), 0
    maximo = maximo if maximo is not None else int(cfg.p("Máximo de convocatorias a completar con Gemini por corrida", 80) or 0)
    pendientes = pendientes[:maximo]
    if not pendientes:
        return 0, len(almacen.items(entrada.ESTADO)), 0
    log.info("Completando %d convocatorias que estaban «Por completar»…", len(pendientes))
    lector = None
    catalogo, base = almacen.catalogo(), almacen.base()
    from calidad.reglas import IndiceDuplicados
    indice = IndiceDuplicados(i["datos"] for i in almacen.items())
    pasaron = 0
    for item in pendientes:
        if DETENER.is_set() or externo.SUSPENDIDO["motivo"]:
            break
        fila = dict(item["datos"])
        fila["_texto"] = item["meta"].get("texto_pagina", "")
        if not fila["_texto"] and str(fila.get("Cómo aplicar", "")).startswith("http"):
            lector = lector or crear_lector(cfg, args)
            fila["_texto"] = _texto_de_la_pagina(lector, fila["Cómo aplicar"])
        fila["[Sistema] Estado"] = "Nueva"
        if fila["_texto"]:
            externo.completar_mapeo([fila], cfg, CATALOGOS, hoy, maximo=1)
        datos = {k: fila[k] for k in fila if not k.startswith(("_", "[Sistema]"))}
        tipo, otro = indice.buscar(datos, excluir=item["datos"])
        if tipo in ("mismo_año", "nombre_mismo_año"):  # ya traducida, resultó ser una que ya estaba
            flujo.descartar(almacen, item, "Sistema", "Duplicado: ya estaba registrada este año como «"
                            + (otro or {}).get("Nombre de la Convocatoria", "")[:90] + "»")
            continue
        norm, hallazgos = flujo.evaluar(almacen, datos, hoy, catalogo, base)
        faltan = entrada.faltantes(norm, hallazgos)
        item["datos"] = norm
        item["meta"]["intentos"] = item["meta"].get("intentos", 0) + 1
        item["meta"].pop("texto_pagina", None)
        if fila.get("[Sistema] Propuesta de Gemini"):
            item["meta"]["gemini"] = fila["[Sistema] Propuesta de Gemini"]
        if faltan:
            item["meta"]["faltantes"] = faltan
            log.info("  Sigue por completar: %s · falta: %s", datos.get("Nombre de la Convocatoria", "")[:60], "; ".join(faltan)[:200])
        else:
            item["estado"] = "Por revisar"
            item["meta"].pop("faltantes", None)
            item["meta"]["hallazgos_ingreso"] = [h.__dict__ for h in hallazgos]
            item["meta"].pop("pendientes", None)
            flujo._evento(item, "Sistema", "Ingreso", "Completada y enviada a la bandeja")
            pasaron += 1
            CONTEO["bandeja"] += 1  # cuenta para la meta de la búsqueda
        almacen.guardar_item(item)
        _avisar("item", None)
    siguen = len(almacen.items(entrada.ESTADO))
    log.info("Por completar: %d pasaron a la bandeja, %d siguen esperando.", pasaron, siguen)
    return pasaron, siguen, len(pendientes)


# ---------------------------------------------------------------------------
def buscar_externo(cfg, args):
    """Búsqueda externa con Gemini: encuentra convocatorias en sitios oficiales que no están entre las fuentes."""
    from calidad.reglas import CATALOGOS
    from motor import externo
    hoy = args.hoy
    almacen = _almacen()
    lector = crear_lector(cfg, args)
    icetex = reglas.IndiceIcetex(cfg, lector)
    base = almacen.base()
    duplicados = reglas.IndiceAirtable(pd.DataFrame(base) if base else None, cfg.p("Umbral de duplicado Airtable (0-100)", 90))
    try:
        filas, descartadas, sugeridas, candidatos, prompt = externo.buscar(
            cfg, lector, icetex, duplicados, almacen.catalogo(), CATALOGOS, hoy=hoy, modalidades=args.modalidad,
            tema=args.tema or "", region=args.region or "", maximo=args.maximo)
    except externo.ErrorGemini as e:
        log.error("%s", e)
        raise SystemExit(str(e)) from e
    for f in filas:
        f["[Sistema] Estado"] = "Nueva"
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"busqueda_externa_{hoy.isoformat()}.xlsx"
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        pd.DataFrame(filas or [{"Nombre de la Convocatoria": "(ninguna pasó la verificación)"}]).to_excel(w, sheet_name="Para revisión", index=False)
        pd.DataFrame(descartadas, columns=["Motivo", "Convocatoria", "Enlace", "Fuente"]).to_excel(w, sheet_name="Descartadas", index=False)
        pd.DataFrame(sugeridas, columns=["Dominio oficial", "Oferente", "Tipo de actor", "País", "Actor en el catálogo",
                                         "Convocatorias encontradas"]).to_excel(w, sheet_name="Fuentes sugeridas", index=False)
        pd.DataFrame(candidatos).to_excel(w, sheet_name="Propuesta de Gemini", index=False)
        pd.DataFrame({"Instrucción enviada a Gemini": prompt.splitlines()}).to_excel(w, sheet_name="Instrucción", index=False)
    log.info("Verificadas: %d para revisión · %d descartadas · %d sitios nuevos sugeridos como fuente.",
             len(filas), len(descartadas), len(sugeridas))
    for motivo, nombre, url, _ in descartadas:
        log.info("  Descartada: %s · %s", nombre[:70], motivo)
    if not getattr(args, "sin_bandeja", False):
        n = enviar_a_bandeja(cfg, filas, origen="Búsqueda externa (Gemini)")["a_bandeja"]
        log.info("%d convocatorias enviadas a la bandeja de revisión.", n)
    return ruta


def agregar_fuentes(ruta_config, sugeridas, origen="Búsqueda externa (Gemini)"):
    """Agrega sitios sugeridos como fuentes nuevas (activas) en la configuración."""
    from openpyxl import load_workbook
    from calidad.actores import caracter_de
    wb = load_workbook(ruta_config)
    ws = wb["Fuentes"]
    cab = [c.value for c in ws[1]]
    ids = [str(ws.cell(r, 1).value or "") for r in range(2, ws.max_row + 1)]
    n = max([int(i.split("-")[1]) for i in ids if i.startswith("EXT-") and i.split("-")[1].isdigit()] or [0])
    grupos = {"Gobierno / agencia bilateral": "Gobiernos y agencias", "Organismo multilateral": "Organismos multilaterales",
              "Academia / investigación": "Universidades y centros de investigación"}
    for s in sugeridas:
        n += 1
        tipo = s.get("Tipo de actor", "Por clasificar")
        valores = {"ID": f"EXT-{n:03d}", "Activa": "Sí", "Tipo de fuente": tipo, "Nombre": s.get("Actor en el catálogo") or s["Oferente"],
                   "País": s.get("País", ""), "Dominio oficial": s["Dominio oficial"], "Oficial / No Oficial": caracter_de(tipo) or s.get("Oficial / No Oficial") or "No Oficial",
                   "Requiere navegador": "No", "Estado de validación": "Por validar", "Modalidades a buscar": "Todas",
                   "Grupo": grupos.get(tipo, "Fundaciones, ONG y empresas"), "Actor en el catálogo": s.get("Actor en el catálogo", ""),
                   "Origen": origen, "Verificación del dominio": "Sugerida por " + origen.lower() + ": validar",
                   "Notas": "Convocatorias encontradas: " + str(s.get("Convocatorias encontradas", ""))}
        fila = ws.max_row + 1
        for k, v in valores.items():
            if k in cab:
                ws.cell(fila, cab.index(k) + 1).value = v
    wb.save(ruta_config)
    return n


# ---------------------------------------------------------------------------
def auditar(cfg, args):
    """Auditoría de calidad de la base actual (Excel con hallazgos y catálogo de actores propuesto)."""
    from analitica.datos import cargar_tabla_tipos
    from calidad import auditoria as AU
    df = pd.read_csv(args.archivo or args.csv)
    tipos = {k: v[0] for k, v in cargar_tabla_tipos().items() if v[1] == "Tabla"}
    catalogo, hallazgos, cambios, base = AU.auditar(df, tipos, hoy=args.hoy)
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = AU.escribir(carpeta / f"auditoria_calidad_{args.hoy.isoformat()}.xlsx", catalogo, hallazgos, cambios, base)
    afectadas = hallazgos["Fila en el export"].nunique() if len(hallazgos) else 0
    log.info("%d hallazgos en %d de %d convocatorias. Actores: %d.", len(hallazgos), afectadas, len(base), len(catalogo))
    log.info("Auditoría: %s", ruta)
    return ruta


def migrar(cfg, args):
    """Carga la base anterior en la base propia, con las correcciones automáticas y un reporte."""
    from analitica.datos import cargar_tabla_tipos
    from bandeja.almacen import abrir
    from calidad import migracion as MG
    df = pd.read_csv(args.archivo or args.csv)
    tipos = {k: v[0] for k, v in cargar_tabla_tipos().items() if v[1] == "Tabla"}
    almacen = abrir()
    try:
        catalogo, items, cambios, pendientes = MG.migrar(df, almacen, tipos, hoy=args.hoy, reemplazar=args.reemplazar)
    except RuntimeError as e:
        sys.exit(str(e))
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = MG.reporte(carpeta / f"migracion_{args.hoy.isoformat()}.xlsx", catalogo, items, cambios, pendientes)
    con_pend = sum(1 for i in items if i["meta"]["pendientes"])
    log.info("%d convocatorias y %d actores cargados. %d correcciones automáticas; %d convocatorias con pendientes.",
             len(items), len(catalogo), len(cambios), con_pend)
    log.info("Reporte: %s", ruta)
    return ruta


def importar(cfg, args):
    """Importación masiva de un export de Airtable: agrega solo lo que aún no está en el sistema."""
    from bandeja.almacen import abrir
    from calidad.migracion import importar as imp
    if not args.archivo:
        sys.exit("Uso: python mapeo.py importar ruta/al/export.csv [--todo-a-revision]")
    tabla, nuevos = imp(pd.read_csv(args.archivo), abrir(), hoy=args.hoy, todo_a_revision=args.todo_a_revision)
    for res, n in tabla["Resultado"].value_counts().items():
        log.info("%s: %d", res, n)
    log.info("Actores nuevos en el catálogo: %d", len(nuevos))


def publicar_base(cfg, args):
    """Sube el archivo local de la base al repositorio privado (GitHub o Hugging Face): primera vez o para restaurar."""
    import os
    from bandeja.almacen import RAIZ as R0, crear_sincronizador, sincronizador_configurado
    if not sincronizador_configurado():
        sys.exit("Define GITHUB_DATA_REPO y GITHUB_TOKEN (o HF_DATASET_REPO y HF_TOKEN). Ver LEEME.md.")
    ruta = Path(os.environ.get("BASE_DATOS") or R0 / "datos" / "convocatorias.db")
    if not ruta.exists():
        sys.exit(f"No existe {ruta}. Primero ejecuta: python mapeo.py migrar")
    sync = crear_sincronizador()
    from bandeja.almacen import AlmacenSQLite
    AlmacenSQLite(ruta)  # deja las cuentas cifradas con USUARIOS_CLAVE antes de subir el archivo
    if getattr(sync, "publico", False):
        import sqlite3
        con = sqlite3.connect(ruta)
        valor = (con.execute("SELECT valor FROM privado WHERE clave='cuentas'").fetchone() or [""])[0]
        tabla = con.execute("SELECT name FROM sqlite_master WHERE name='usuarios'").fetchone()
        con.close()
        if tabla or (valor and not valor.startswith("fernet:")):
            sys.exit("El repositorio de datos es público y las cuentas no están cifradas: define USUARIOS_CLAVE.")
    sync.sha = sync.remoto()
    sync.subir(ruta, "Base inicial corregida")
    destino = (f"https://github.com/{os.environ['GITHUB_DATA_REPO']}" if sincronizador_configurado() == "GitHub"
               else f"https://huggingface.co/datasets/{os.environ['HF_DATASET_REPO']}")
    log.info("Base subida a %s (privado).", destino)


def crear_usuario(cfg, args):
    from bandeja import usuarios
    from bandeja.almacen import abrir
    if not (args.usuario and args.nombre and args.rol):
        sys.exit("Uso: python mapeo.py crear-usuario --usuario nata --nombre \"Natalia Gómez\" --rol admin")
    try:
        clave = usuarios.crear(abrir(), args.usuario, args.nombre, args.rol, args.clave, temporal=True)
    except ValueError as e:
        sys.exit(str(e))
    log.info("Usuario %s (%s) creado. Contraseña temporal: %s", args.usuario, args.rol, clave)
    log.info("Guárdala: no se vuelve a mostrar. Al entrar por primera vez el sistema pide cambiarla.")


def generar_clave_cuentas(cfg, args):
    """Genera un valor aleatorio para el secreto USUARIOS_CLAVE (cifra las cuentas de usuario)."""
    import secrets
    print(secrets.token_urlsafe(48))
    log.info("Guárdalo como secreto USUARIOS_CLAVE. Si se pierde, las cuentas no se pueden leer y hay que crearlas de nuevo.")


def restablecer_clave(cfg, args):
    """Recuperación de último recurso (por ejemplo, si el único administrador olvidó su contraseña y no tiene códigos)."""
    from bandeja import usuarios
    from bandeja.almacen import abrir
    if not args.usuario:
        sys.exit("Uso: python mapeo.py restablecer-clave --usuario nata")
    try:
        clave = usuarios.restablecer(abrir(), args.usuario)
    except ValueError as e:
        sys.exit(str(e))
    log.info("Contraseña de %s restablecida. Contraseña temporal: %s (se cambia al entrar).", args.usuario, clave)


def informe(cfg, args):
    """Informe automático (Word y PDF) con las convocatorias aprobadas de la base propia."""
    from analitica import datos as D
    from analitica import informe as INF
    from bandeja.almacen import abrir
    df = D.preparar(pd.read_csv(args.archivo)) if args.archivo else D.desde_almacen(abrir())
    if df.empty:
        sys.exit("La base está vacía. Primero ejecuta: python mapeo.py migrar")
    ruta = RAIZ / "salidas" / f"Informe_convocatorias_{args.hoy.isoformat()}.docx"
    docx, pdf = INF.generar(df, ruta, pdf=not args.sin_pdf)
    log.info("Informe en Word: %s", docx)
    log.info("Informe en PDF: %s", pdf or "no se generó (instala LibreOffice o Word, o guárdalo como PDF desde Word)")
    return docx


def externo_reiniciar():
    from motor import externo
    externo.reiniciar_corrida()


# ---------------------------------------------------------------------------
VERSION = "2026-11-23f"  # la pantalla de búsqueda la compara para avisar si faltan archivos por actualizar


class _Argumentos(argparse.ArgumentParser):
    def error(self, message):
        raise SystemExit("La búsqueda no arrancó: el programa no reconoce una opción (" + message + "). Casi siempre es "
                         "porque en GitHub quedaron archivos de versiones distintas: vuelve a subir mapeo.py y las "
                         "carpetas motor/, calidad/ y paginas/ del último paquete.")


def main(argv=None):
    p = _Argumentos(description="Mapeo de convocatorias internacionales para Colombia")
    p.add_argument("comando", choices=["migrar", "importar", "publicar-base", "crear-usuario", "restablecer-clave", "generar-clave-cuentas", "validar-fuentes", "mapear", "descubrir", "buscar-externo", "completar-pendientes", "informe", "auditar"])
    p.add_argument("archivo", nargs="?", help="Export CSV (para migrar, auditar o informe desde un archivo)")
    p.add_argument("--config", default=str(cfgmod.RUTA_CONFIG))
    p.add_argument("--csv", default=str(RAIZ / "datos" / "airtable_actual.csv"))
    p.add_argument("--prueba", default=None)
    p.add_argument("--hoy", default=None)
    p.add_argument("--sin-pdf", action="store_true", help="Informe solo en Word")
    p.add_argument("--sin-bandeja", action="store_true", help="Mapear sin enviar a la bandeja (solo Excel)")
    p.add_argument("--reemplazar", action="store_true", help="migrar: borrar la base propia y volver a cargarla")
    p.add_argument("--todo-a-revision", action="store_true", help="importar: enviar todas las nuevas a la bandeja")
    p.add_argument("--maximo-nuevas", type=int, help="mapear: cuántas convocatorias completas deben llegar a la bandeja (meta)")
    p.add_argument("--sin-gemini", action="store_true", help="mapear: no completar campos con Gemini en esta corrida")
    p.add_argument("--completo", action="store_true", help="mapear: revisión completa (vuelve a abrir también las convocatorias ya conocidas)")
    p.add_argument("--reintentar-todas", action="store_true", help="completar-pendientes: también las que ya agotaron los intentos")
    p.add_argument("--todas", action="store_true", help="mapear: incluye las fuentes que fallaron en la última validación")
    p.add_argument("--paralelo", type=int, help="fuentes que se revisan a la vez")
    p.add_argument("--pausa", type=float, help="segundos entre páginas del mismo sitio")
    p.add_argument("--grupo", action="append", help="validar-fuentes/mapear: solo las fuentes de este grupo (se puede repetir)")
    p.add_argument("--fuente", action="append", help="validar-fuentes/mapear: solo esta fuente por ID (se puede repetir)")
    p.add_argument("--modalidad", action="append", help="buscar-externo: Beca, Subvención, Cooperación técnica o Premio (se puede repetir)")
    p.add_argument("--tema", help="buscar-externo: tema de interés (opcional)")
    p.add_argument("--region", help="buscar-externo: país o región del oferente (opcional)")
    p.add_argument("--maximo", type=int, default=10, help="buscar-externo: convocatorias que se piden a Gemini")
    p.add_argument("--usuario")
    p.add_argument("--nombre")
    p.add_argument("--rol", help="admin | revisor")
    p.add_argument("--clave", help="Opcional; si no se da, se genera una")
    args = p.parse_args(argv)
    args.hoy = date.fromisoformat(args.hoy) if args.hoy else date.today()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = cfgmod.cargar(args.config)
    if args.comando == "descubrir":
        args.modo = "descubrir"
    return {"validar-fuentes": validar_fuentes, "mapear": mapear, "descubrir": mapear, "buscar-externo": buscar_externo,
            "completar-pendientes": lambda c, a: (externo_reiniciar(), completar_pendientes(c, a))[1], "informe": informe, "auditar": auditar,
            "migrar": migrar, "importar": importar, "publicar-base": publicar_base, "crear-usuario": crear_usuario,
            "restablecer-clave": restablecer_clave, "generar-clave-cuentas": generar_clave_cuentas}[args.comando](cfg, args)


if __name__ == "__main__":
    main()
