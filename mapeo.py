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
from motor.red import Lector

RAIZ = Path(__file__).resolve().parent
log = logging.getLogger("mapeo")


def crear_lector(cfg, args):
    return Lector(
        agente=cfg.p("Identificación del programa (User-Agent)", "APC-Colombia DGDCI mapeo de convocatorias"),
        pausa=cfg.p("Pausa entre solicitudes (segundos)", 3),
        espera=cfg.p("Tiempo máximo de espera (segundos)", 20),
        respetar_robots=str(cfg.p("Respetar robots.txt", "Sí")).lower().startswith("s"),
        usar_navegador=str(cfg.p("Usar navegador para páginas dinámicas", "No")).lower().startswith("s"),
        carpeta_prueba=args.prueba,
    )


# ---------------------------------------------------------------------------
def fuentes_a_revisar(cfg, args, solo_activas=True):
    fuentes = [f for f in cfg.fuentes if f.activa or not solo_activas]
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
    hilos = 1 if args.prueba else max(1, int(cfg.p("Fuentes en paralelo", 6) or 1))
    if hilos == 1:
        for f in fuentes:
            yield f, tarea(f)
        return
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(tarea, f): f for f in fuentes}
        for fut in as_completed(futuros):
            yield futuros[fut], fut.result()


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
    for f, (estado, urls, sitio) in en_paralelo(cfg, args, fuentes, lambda f: validar_una(f, cfg, args)):
        if urls:
            ws.cell(row=f.fila, column=col_url).value = urls
        ws.cell(row=f.fila, column=col["Estado de validación"]).value = estado
        ws.cell(row=f.fila, column=col["Última validación"]).value = hoy
        if "Nombre del sitio" in col and sitio:
            ws.cell(row=f.fila, column=col["Nombre del sitio"]).value = sitio
        log.info("%-10s %-55s %s", f.id, f.nombre[:55], estado)
    wb.save(cfg.ruta)
    log.info("Configuración actualizada: %s (respaldo en %s)", cfg.ruta.name, respaldo.name)


# ---------------------------------------------------------------------------
def revisar_fuente(fuente, cfg, args, icetex, duplicados):
    """Lee una fuente y devuelve sus hallazgos sin tocar nada compartido (se puede correr en paralelo)."""
    hoy = args.hoy
    lector = crear_lector(cfg, args)
    paginas, nota = extraer.descubrir_paginas(fuente, lector, cfg)
    hallazgos, analizadas, leida, vistas = [], 0, False, set()
    for pagina in paginas:
        resp = lector.leer(pagina, forzar_navegador=fuente.requiere_navegador)
        if not resp.ok:
            nota += f" | {pagina} no respondió ({resp.estado})"
            continue
        leida = True
        cands = extraer.candidatas(resp.html, resp.url, fuente, cfg)
        if not cands:  # la página misma puede ser la convocatoria
            cands = [(resp.url, "")]
        for url, texto_enlace in cands:
            if url in vistas:
                continue
            vistas.add(url)
            if url.lower().endswith(".pdf"):
                hallazgos.append(("revision", url, salidas.fila_pdf(url, texto_enlace, fuente, pagina, cfg, hoy), ""))
                continue
            r = resp if url == resp.url else lector.leer(url, forzar_navegador=fuente.requiere_navegador)
            if not r.ok:
                continue
            analizadas += 1
            datos = extraer.analizar_beca(r, fuente, cfg, hoy, texto_enlace)
            if not datos["titulo"]:
                datos["titulo"] = texto_enlace
            elig = reglas.elegibilidad(datos["texto_norm"], cfg)
            # ICETEX solo ofrece becas: la exclusión no aplica a subvenciones, cooperación técnica ni premios
            en_icetex = icetex.revisar(datos["titulo"], r.url, datos) if datos["modalidad"] == "Beca" else (False, "No aplica (no es beca)")
            dup = duplicados.revisar(datos["titulo"], r.url)
            fila = salidas.fila_airtable(datos, r.url, fuente, pagina, cfg, elig, en_icetex, dup, hoy)
            fila["_texto"] = datos.get("texto_pagina", "")
            motivo = ("Está en ICETEX: " + en_icetex[1] if en_icetex[0] else
                      "No elegible para colombianos: " + elig[2] if elig[0] == "No elegible" else
                      dup if dup.startswith("Ya está en la base") else
                      "Convocatoria vencida: " + datos["evidencia_cierre"] if datos["vencida"] else "")
            hallazgos.append(("descartada" if motivo else "revision", r.url, fila, motivo))
    return {"paginas": paginas, "nota": nota, "analizadas": analizadas, "leida": leida, "hallazgos": hallazgos}


def mapear(cfg, args):
    hoy = args.hoy
    icetex = reglas.IndiceIcetex(cfg, crear_lector(cfg, args))
    for nota in icetex.notas:
        log.warning(nota)
    from bandeja.almacen import abrir
    base = abrir().base()
    df_air = pd.DataFrame(base) if base else (pd.read_csv(args.csv) if args.csv and Path(args.csv).exists() else None)
    if df_air is None:
        log.warning("La base está vacía: no se revisarán duplicados.")
    duplicados = reglas.IndiceAirtable(df_air, cfg.p("Umbral de duplicado Airtable (0-100)", 90))
    import os
    historial = Historial(os.environ.get("MAPEO_HISTORIAL") or RAIZ / "datos" / "historial.json")

    fuentes = fuentes_a_revisar(cfg, args)
    log.info("Revisando %d fuentes (becas, subvenciones, cooperación técnica y premios)…", len(fuentes))
    filas, descartadas, resumen, leidas, vistas = [], [], [], set(), set()
    for fuente, res in en_paralelo(cfg, args, fuentes, lambda f: revisar_fuente(f, cfg, args, icetex, duplicados)):
        revision = desc = 0
        por_modalidad = {}
        if res["leida"]:
            leidas.add(fuente.id)
        for tipo, url, fila, motivo in res["hallazgos"]:
            if url in vistas:  # la misma convocatoria publicada en dos fuentes
                continue
            vistas.add(url)
            fila["[Sistema] Estado"] = historial.registrar(url, fuente.id, fila, hoy.isoformat())
            if tipo == "descartada":
                descartadas.append((motivo, fila["Nombre de la Convocatoria"], url, fuente.id))
                desc += 1
            else:
                filas.append(fila)
                revision += 1
                m = fila["Modalidad"].split(" (")[0]
                por_modalidad[m] = por_modalidad.get(m, 0) + 1
        nota = res["nota"] + (" | " + ", ".join(f"{k}: {v}" for k, v in por_modalidad.items()) if por_modalidad else "")
        resumen.append((fuente.id, fuente.nombre, fuente.tipo, len(res["paginas"]), res["analizadas"], revision, desc, nota))
        log.info("%-10s páginas %d · analizadas %d · para revisión %d · descartadas %d", fuente.id, len(res["paginas"]),
                 res["analizadas"], revision, desc)

    from calidad.reglas import CATALOGOS
    from motor import externo
    n_gem = externo.completar_mapeo(filas, cfg, CATALOGOS, hoy)
    if n_gem:
        log.info("%d convocatorias completadas con Gemini.", n_gem)
    for f in filas:
        f.pop("_texto", None)
    retiradas = historial.retiradas(leidas)
    carpeta = RAIZ / "salidas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"revision_{hoy.isoformat()}.xlsx"
    salidas.escribir_revision(ruta, filas, descartadas, resumen, retiradas)
    historial.guardar()
    log.info("Listo: %d convocatorias para revisión, %d descartadas, %d ya no aparecen.", len(filas), len(descartadas), len(retiradas))
    if not getattr(args, "sin_bandeja", False):
        n = enviar_a_bandeja(cfg, filas)
        log.info("%d convocatorias nuevas o actualizadas enviadas a la bandeja de revisión.", n)
        log.info("Reporte de la corrida: %s", ruta.name)
    return ruta


def enviar_a_bandeja(cfg, filas, origen="Mapeo automático"):
    """Las convocatorias mapeadas nunca van directo a la base: entran a la bandeja para revisión humana."""
    from bandeja import flujo
    from bandeja.almacen import abrir
    almacen = abrir()
    ya = {i["datos"].get("Cómo aplicar", "").rstrip("/").lower() for i in almacen.items()}
    enviadas = 0
    for fila in filas:
        if fila["[Sistema] Estado"] == "Sin cambios":
            continue
        url = fila.get("Cómo aplicar", "").rstrip("/").lower()
        if url in ya:
            continue
        datos = {c: fila.get(c, "") for c in cfg.columnas_airtable}
        from calidad.reglas import CAMPO_APERTURA, CAMPO_REQUISITOS
        for extra in ("Tipo de monto", CAMPO_APERTURA, CAMPO_REQUISITOS):
            if fila.get(extra):
                datos[extra] = fila[extra]
        # Las verificaciones las confirma quien revisa, no el programa
        for c in ("VERIFICACIÓN: Colombia hace parte de los países beneficiarios", "VERIFICACIÓN: Página web correcta y activa",
                  "VERIFICACIÓN: Presenta información completa relacionada en la convocatoria"):
            datos[c] = ""
        meta = {"elegibilidad": f"{fila['[Sistema] Elegibilidad Colombia']} · {fila['[Sistema] Motivo elegibilidad']}",
                "modalidad": fila.get("[Sistema] Motivo modalidad", ""),
                "icetex": f"{fila['[Sistema] ¿Está en ICETEX?']} {fila['[Sistema] Motivo ICETEX']}".strip(),
                "pagina": fila["[Sistema] Página donde se encontró"], "nivel": fila["[Sistema] Nivel"],
                "duplicado": fila["[Sistema] Duplicado en Airtable"], "alerta_cierre": fila["[Sistema] Alerta de cierre"],
                "gemini": fila.get("[Sistema] Propuesta de Gemini", "")}
        flujo.ingresar(almacen, datos, f"{origen} · {fila['[Sistema] Fuente ID']}", origen, meta)
        ya.add(url)
        enviadas += 1
    return enviadas


# ---------------------------------------------------------------------------
def buscar_externo(cfg, args):
    """Búsqueda externa con Gemini: encuentra convocatorias en sitios oficiales que no están entre las fuentes."""
    from bandeja.almacen import abrir
    from calidad.reglas import CATALOGOS
    from motor import externo
    hoy = args.hoy
    almacen = abrir()
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


# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="Mapeo de convocatorias internacionales para Colombia")
    p.add_argument("comando", choices=["migrar", "importar", "publicar-base", "crear-usuario", "restablecer-clave", "generar-clave-cuentas", "validar-fuentes", "mapear", "buscar-externo", "informe", "auditar"])
    p.add_argument("archivo", nargs="?", help="Export CSV (para migrar, auditar o informe desde un archivo)")
    p.add_argument("--config", default=str(cfgmod.RUTA_CONFIG))
    p.add_argument("--csv", default=str(RAIZ / "datos" / "airtable_actual.csv"))
    p.add_argument("--prueba", default=None)
    p.add_argument("--hoy", default=None)
    p.add_argument("--sin-pdf", action="store_true", help="Informe solo en Word")
    p.add_argument("--sin-bandeja", action="store_true", help="Mapear sin enviar a la bandeja (solo Excel)")
    p.add_argument("--reemplazar", action="store_true", help="migrar: borrar la base propia y volver a cargarla")
    p.add_argument("--todo-a-revision", action="store_true", help="importar: enviar todas las nuevas a la bandeja")
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
    return {"validar-fuentes": validar_fuentes, "mapear": mapear, "buscar-externo": buscar_externo, "informe": informe, "auditar": auditar,
            "migrar": migrar, "importar": importar, "publicar-base": publicar_base, "crear-usuario": crear_usuario,
            "restablecer-clave": restablecer_clave, "generar-clave-cuentas": generar_clave_cuentas}[args.comando](cfg, args)


if __name__ == "__main__":
    main()
