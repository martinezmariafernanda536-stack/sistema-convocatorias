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
DETENER = threading.Event()    # la aplicación lo activa con el botón «Detener»
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


def revisar_fuente(fuente, cfg, args, icetex, duplicados, conocidas=frozenset(), completa=True):
    """Lee una fuente y devuelve sus hallazgos sin tocar nada compartido (se puede correr en paralelo).

    Modo rápido (completa=False): solo se abren las convocatorias que no se habían visto antes; las conocidas
    se marcan como «siguen publicadas» sin volver a abrirlas."""
    hoy = args.hoy
    lector = crear_lector(cfg, args)
    paginas, nota = extraer.descubrir_paginas(fuente, lector, cfg)
    hallazgos, analizadas, leida, vistas, sin_cambios = [], 0, False, set(), []
    terminos = cfg.palabras_de(fuente.modalidades)

    def analizar(r, url, texto_enlace, pagina, seccion_de="", contexto=""):
        nonlocal analizadas
        analizadas += 1
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
            if not completa and url_s in conocidas:
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
            if not completa and url in conocidas:
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
    return {"paginas": paginas, "nota": nota, "analizadas": analizadas, "leida": leida, "hallazgos": hallazgos,
            "sin_cambios": sin_cambios, "completa": completa}


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

    fuentes = fuentes_a_revisar(cfg, args)
    conocidas = frozenset(historial.conocidas())
    cada = int(cfg.p("Días entre revisiones completas", 30) or 30)
    completa = {f.id: bool(getattr(args, "completo", False)) or (d := historial.dias_desde_completa(f.id, hoy.isoformat())) is None
                or d >= cada for f in fuentes}
    n_rapidas = sum(1 for v in completa.values() if not v)
    log.info("Revisando %d fuentes (becas, subvenciones, cooperación técnica y premios)…", len(fuentes))
    if n_rapidas:
        log.info("Modo rápido en %d fuentes: solo se abren las convocatorias nuevas. Las demás %d tienen revisión completa "
                 "(cada %d días).", n_rapidas, len(fuentes) - n_rapidas, cada)
    from calidad.reglas import CATALOGOS
    from motor import externo
    cupo_gemini = 0 if getattr(args, "sin_gemini", False) else int(cfg.p("Máximo de convocatorias a completar con Gemini por corrida", 80) or 0)
    externo.reiniciar_corrida()
    CONTEO.update(bandeja=0, por_completar=0, duplicadas=0)
    if not getattr(args, "sin_bandeja", False):
        # primero, lo que quedó pendiente de corridas anteriores (y se limpia la bandeja de duplicados e incompletas)
        _, _, usadas = completar_pendientes(cfg, args, hoy, maximo=cupo_gemini)
        cupo_gemini = max(0, cupo_gemini - usadas)
    if getattr(args, "sin_gemini", False):
        log.info("Sin Gemini en esta corrida: los campos se llenan solo con lo que se lee en cada página.")
    filas, descartadas, resumen, leidas, vistas = [], [], [], set(), set()
    enviadas_total = hechas = 0
    for fuente, res in en_paralelo(cfg, args, fuentes, lambda f: revisar_fuente(f, cfg, args, icetex, duplicados,
                                                                                   conocidas, completa[f.id])):
        hechas += 1
        for url in res["sin_cambios"]:
            historial.marcar_visto(url, fuente.id, hoy.isoformat())
        if res["completa"] and res["leida"]:
            historial.marcar_completa(fuente.id, hoy.isoformat())
        revision = desc = 0
        por_modalidad, nuevas = {}, []
        if res["leida"]:
            leidas.add(fuente.id)
        for tipo, url, fila, motivo in res["hallazgos"]:
            if url in vistas:  # la misma convocatoria publicada en dos fuentes
                continue
            vistas.add(url)
            fila["[Sistema] Estado"] = historial.registrar(url, fuente.id, fila, hoy.isoformat())
            enlace = fila.pop("_enlace", url)
            if enlace != url:  # el enlace de la lista redirige: se recuerdan los dos
                historial.marcar_visto(enlace, fuente.id, hoy.isoformat())
            if tipo == "descartada":
                descartadas.append((motivo, fila["Nombre de la Convocatoria"], url, fuente.id))
                desc += 1
            else:
                nuevas.append(fila)
                revision += 1
                m = fila["Modalidad"].split(" (")[0]
                por_modalidad[m] = por_modalidad.get(m, 0) + 1
        # se completa y se envía a la bandeja fuente por fuente: si la ejecución se interrumpe, nada de esto se pierde
        if nuevas and cupo_gemini > 0:
            n = externo.completar_mapeo(nuevas, cfg, CATALOGOS, hoy, maximo=cupo_gemini)
            cupo_gemini -= n
        a_bandeja = 0
        if nuevas and not getattr(args, "sin_bandeja", False):
            antes = CONTEO["por_completar"]
            a_bandeja = enviar_a_bandeja(cfg, nuevas)
            enviadas_total += a_bandeja
            por_completar_fuente = CONTEO["por_completar"] - antes
        else:
            por_completar_fuente = 0
        for f in nuevas:
            f.pop("_texto", None)
        filas.extend(nuevas)
        historial.guardar()
        _avisar("historial", historial.ruta)
        nota = res["nota"] + (" | " + ", ".join(f"{k}: {v}" for k, v in por_modalidad.items()) if por_modalidad else "")
        resumen.append((fuente.id, fuente.nombre, fuente.tipo, len(res["paginas"]), res["analizadas"], revision, desc, nota))
        log.info("%-10s páginas %d · abiertas %d · ya conocidas %d · encontradas %d · a la bandeja %d · por completar %d · "
                 "descartadas %d   [%d de %d]", fuente.id, len(res["paginas"]), res["analizadas"], len(res["sin_cambios"]),
                 revision, a_bandeja, por_completar_fuente, desc, hechas, len(fuentes))

    retiradas = historial.retiradas(leidas)
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"revision_{hoy.isoformat()}.xlsx"
    salidas.escribir_revision(ruta, filas, descartadas, resumen, retiradas)
    historial.guardar()
    log.info("Listo: %d convocatorias para revisión, %d descartadas, %d ya no aparecen.", len(filas), len(descartadas), len(retiradas))
    if not getattr(args, "sin_bandeja", False):
        log.info("%d convocatorias completas enviadas a la bandeja de revisión; %d quedaron «Por completar» y %d ya estaban "
                 "registradas este año.", enviadas_total, CONTEO["por_completar"], CONTEO["duplicadas"])
        log.info("Reporte de la corrida: %s", ruta.name)
    return ruta


def enviar_a_bandeja(cfg, filas, origen="Mapeo automático"):
    """Las convocatorias mapeadas nunca van directo a la base: entran a la bandeja para revisión humana."""
    from bandeja import flujo
    almacen = _almacen()
    ya = [i["datos"] for i in almacen.items()]  # incluye descartadas: lo descartado este año no vuelve a llegar
    enviadas = 0
    with almacen.lote(f"{origen}: {len(filas)} convocatorias"):
        enviadas = _enviar(cfg, filas, origen, almacen, ya, flujo)
    return enviadas


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


def _enviar(cfg, filas, origen, almacen, ya, flujo):
    """Solo pasa a la bandeja lo que llega en español y completo; lo demás queda «Por completar» (fuera de la bandeja).
    Lo que ya está en el sistema para el mismo año, con el mismo enlace o casi el mismo nombre, no entra."""
    from calidad import entrada
    from calidad.reglas import buscar_duplicado
    catalogo, base = almacen.catalogo(), almacen.base()
    enviadas = 0
    for fila in filas:
        if fila["[Sistema] Estado"] == "Sin cambios":
            continue
        tipo, otro = buscar_duplicado(fila, ya)
        if tipo in ("mismo_año", "nombre_mismo_año"):
            CONTEO["duplicadas"] += 1
            log.info("  Ya registrada este año (no entra): %s = %s", fila["Nombre de la Convocatoria"][:60],
                     (otro or {}).get("Nombre de la Convocatoria", "")[:60])
            continue
        datos = _datos_de(cfg, fila)
        meta = _meta(fila)
        norm, hallazgos = flujo.evaluar(almacen, datos, catalogo=catalogo, base=base)
        faltan = entrada.faltantes(norm, hallazgos)
        if faltan:
            meta |= {"faltantes": faltan, "intentos": 1, "texto_pagina": str(fila.get("_texto", ""))[:12000]}
            CONTEO["por_completar"] += 1
            log.info("  Por completar (no pasa a la bandeja): %s · falta: %s", fila["Nombre de la Convocatoria"][:60],
                     "; ".join(faltan)[:200])
        flujo.ingresar(almacen, datos, f"{origen} · {fila['[Sistema] Fuente ID']}", origen, meta,
                       estado=entrada.ESTADO if faltan else "Por revisar", catalogo=catalogo, base=base)
        ya.append(datos)
        if not faltan:
            enviadas += 1
            CONTEO["bandeja"] += 1
    return enviadas


def _texto_de_la_pagina(lector, url):
    from motor.extraer import _sopa, _texto_visible
    import unicodedata
    r = lector.leer(url)
    return unicodedata.normalize("NFC", _texto_visible(_sopa(r.html)))[:12000] if r.ok else ""


def limpiar_bandeja(almacen, hoy=None):
    """Lo que llegó solo y nadie ha tocado: se descarta si es un duplicado del mismo año y vuelve a «Por completar»
    si no está en español o le faltan datos. Lo que una persona ya editó no se mueve."""
    from bandeja import flujo
    from calidad import entrada
    from calidad.reglas import buscar_duplicado
    catalogo, base = almacen.catalogo(), almacen.base()
    todos = sorted(almacen.items(), key=lambda i: i["ingreso"])
    duplicadas = devueltas = 0
    with almacen.lote("Limpieza de la bandeja"):
        for n, item in enumerate(todos):
            if item["estado"] not in ("Por revisar", entrada.ESTADO) or not flujo.es_automatica(item) or flujo.tocada_por_persona(item):
                continue
            anteriores = [o["datos"] for o in todos[:n]]  # incluye descartadas: lo descartado este año no vuelve
            tipo, otro = buscar_duplicado(item["datos"], anteriores)
            if tipo in ("mismo_año", "nombre_mismo_año"):
                flujo.descartar(almacen, item, "Sistema", "Duplicado: ya estaba registrada este año como «"
                                + (otro or {}).get("Nombre de la Convocatoria", "")[:90] + "»")
                item["estado"] = "Descartada"
                duplicadas += 1
                continue
            if item["estado"] == "Por revisar":
                norm, hallazgos = flujo.evaluar(almacen, item["datos"], hoy, catalogo, base)
                faltan = entrada.faltantes(norm, hallazgos)
                if faltan:
                    item["estado"] = entrada.ESTADO
                    item["meta"] |= {"faltantes": faltan, "intentos": 0}
                    flujo._evento(item, "Sistema", "Ingreso", "Devuelta a «Por completar»: " + "; ".join(faltan)[:300])
                    almacen.guardar_item(item)
                    devueltas += 1
    if duplicadas or devueltas:
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
        otros = [o["datos"] for o in almacen.items() if o["id"] != item["id"]]
        tipo, otro = buscar_duplicado(datos, otros)
        if tipo in ("mismo_año", "nombre_mismo_año"):  # ya traducida, resultó ser una que ya estaba
            flujo.descartar(almacen, item, "Sistema", "Duplicado: ya estaba registrada este año como «"
                            + (otro or {}).get("Nombre de la Convocatoria", "")[:90] + "»")
            continue
        norm, hallazgos = flujo.evaluar(almacen, datos, hoy, catalogo, base)
        faltan = entrada.faltantes(norm, hallazgos)
        item["datos"] = norm
        item["meta"]["intentos"] = item["meta"].get("intentos", 0) + 1
        item["meta"]["texto_pagina"] = fila["_texto"]
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
        n = enviar_a_bandeja(cfg, filas, origen="Búsqueda externa (Gemini)")
        log.info("%d convocatorias enviadas a la bandeja de revisión.", n)
    return ruta


def agregar_fuentes(ruta_config, sugeridas):
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
                   "País": s.get("País", ""), "Dominio oficial": s["Dominio oficial"], "Oficial / No Oficial": caracter_de(tipo) or "No Oficial",
                   "Requiere navegador": "No", "Estado de validación": "Por validar", "Modalidades a buscar": "Todas",
                   "Grupo": grupos.get(tipo, "Fundaciones, ONG y empresas"), "Actor en el catálogo": s.get("Actor en el catálogo", ""),
                   "Origen": "Búsqueda externa (Gemini)", "Verificación del dominio": "Sugerida por la búsqueda externa: validar",
                   "Notas": "Convocatorias encontradas: " + s.get("Convocatorias encontradas", "")}
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
def main(argv=None):
    p = argparse.ArgumentParser(description="Mapeo de convocatorias internacionales para Colombia")
    p.add_argument("comando", choices=["migrar", "importar", "publicar-base", "crear-usuario", "restablecer-clave", "generar-clave-cuentas", "validar-fuentes", "mapear", "buscar-externo", "completar-pendientes", "informe", "auditar"])
    p.add_argument("archivo", nargs="?", help="Export CSV (para migrar, auditar o informe desde un archivo)")
    p.add_argument("--config", default=str(cfgmod.RUTA_CONFIG))
    p.add_argument("--csv", default=str(RAIZ / "datos" / "airtable_actual.csv"))
    p.add_argument("--prueba", default=None)
    p.add_argument("--hoy", default=None)
    p.add_argument("--sin-pdf", action="store_true", help="Informe solo en Word")
    p.add_argument("--sin-bandeja", action="store_true", help="Mapear sin enviar a la bandeja (solo Excel)")
    p.add_argument("--reemplazar", action="store_true", help="migrar: borrar la base propia y volver a cargarla")
    p.add_argument("--todo-a-revision", action="store_true", help="importar: enviar todas las nuevas a la bandeja")
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
    return {"validar-fuentes": validar_fuentes, "mapear": mapear, "buscar-externo": buscar_externo,
            "completar-pendientes": lambda c, a: (externo_reiniciar(), completar_pendientes(c, a))[1], "informe": informe, "auditar": auditar,
            "migrar": migrar, "importar": importar, "publicar-base": publicar_base, "crear-usuario": crear_usuario,
            "restablecer-clave": restablecer_clave, "generar-clave-cuentas": generar_clave_cuentas}[args.comando](cfg, args)


if __name__ == "__main__":
    main()
