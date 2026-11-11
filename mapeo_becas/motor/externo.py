"""Búsqueda externa con Gemini (con búsqueda de Google) para encontrar convocatorias fuera de las fuentes configuradas.

Gemini solo PROPONE candidatos. Nada se acepta por lo que diga el modelo:
  1. Se descartan los enlaces que no son de un sitio oficial (acortadores, agregadores, formularios, ICETEX).
  2. El sistema abre cada página él mismo (respetando robots.txt). Si la página no existe, se descarta:
     así se eliminan los enlaces inventados.
  3. A la página se le aplican las mismas reglas del mapeo: modalidad, elegibilidad de Colombia, ICETEX (becas),
     fecha de cierre y duplicados.
  4. Lo que pasa va a la bandeja de revisión, con las verificaciones sin marcar.
Los sitios de oferentes que no están entre las fuentes quedan como "fuentes sugeridas" para que el administrador decida.

Se usa la API de Gemini (generateContent con la herramienta google_search). Variables:
  GEMINI_API_KEY   clave de Google AI Studio (obligatoria)
  GEMINI_MODEL     modelo (si no, el parámetro «Modelo de Gemini» de la configuración)
  MAPEO_GEMINI_PRUEBA  ruta a una respuesta guardada (solo para pruebas; no llama a la API)
"""
import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import requests

from calidad import dominios as DOM
from calidad.reglas import CAMPO_APERTURA, CAMPO_REQUISITOS
from calidad.reglas import PLANTILLAS as PLANT

from . import extraer, reglas, salidas
from .config import MODALIDADES, Fuente, modalidad_de

log = logging.getLogger("mapeo")
URL_API = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELO_POR_DEFECTO = "gemini-2.5-flash"
TIPOS_ACTOR = ["Gobierno / agencia bilateral", "Organismo multilateral", "Fundación / filantropía", "ONG / sociedad civil",
               "Academia / investigación", "Empresa privada"]
_CARACTER = {"Gobierno / agencia bilateral": "Oficial", "Organismo multilateral": "Oficial"}


class ErrorGemini(Exception):
    pass


# --- 1. Instrucción --------------------------------------------------------
def construir_prompt(catalogos, modalidades, hoy, tema="", region="", maximo=10, excluir=()):
    lista = lambda campo: "; ".join(catalogos.get(campo, []))  # noqa: E731
    mods = ", ".join(m.split(" (")[0] for m in modalidades)
    filtro = ""
    if tema:
        filtro += f"\n- Tema de interés: {tema}."
    if region:
        filtro += f"\n- País o región del oferente: {region}."
    excl = ", ".join(sorted(excluir)[:150])
    return f"""Eres analista de la Dirección de Gestión de Demanda de Cooperación Internacional de APC-Colombia.
Usa la búsqueda de Google para encontrar convocatorias internacionales ABIERTAS hoy ({hoy:%d/%m/%Y}) a las que puedan
postularse personas u organizaciones de Colombia. Modalidades a buscar: {mods}.{filtro}

CONDICIONES OBLIGATORIAS (si una convocatoria no las cumple, no la incluyas):
1. Fuente oficial: el enlace debe ser del sitio web oficial del oferente (gobierno, embajada, agencia de cooperación,
   organismo multilateral, fundación, ONG, universidad, empresa o cámara de comercio binacional que ofrece la convocatoria).
   NO uses agregadores ni portales que republican convocatorias de otros (FundsforNGOs, opportunitydesk, opportunitiesforyouth,
   devex, developmentaid, scholars4dev, becas.com, estudiarfuera y similares), ni boletines informativos de otras entidades
   (por ejemplo el Boletín de Oferta Internacional de la Alcaldía de Bogotá, la Cancillería u otras entidades públicas
   colombianas), ni redes sociales, ni acortadores (bit.ly, lnkd.in), ni blogs, ni noticias de prensa. Si encuentras la
   convocatoria en uno de esos sitios, busca y usa el enlace oficial de la entidad que la ofrece.
2. Colombia no debe estar excluida. NO hace falta que la página nombre a Colombia: sirve si está abierta a extranjeros,
   a estudiantes o postulantes internacionales, a todos los países, a América Latina o las Américas, o a países en desarrollo
   (lista CAD de la OCDE), siempre que no excluya a Colombia ni a la región (por ejemplo "solo ciudadanos de la UE" o
   "solo países africanos" no sirve). Copia la frase de la página que muestra quién puede postularse.
3. La convocatoria debe estar abierta (fecha límite posterior a hoy, o permanente) o tener una fecha de apertura
   anunciada oficialmente por el cooperante.
3b. La página debe tener información suficiente sobre las condiciones de participación (requisitos y cómo postularse).
4. Si es una beca, NO debe ofrecerse a través de ICETEX (Colombia).
5. No inventes enlaces: incluye solo URL que hayas visto en los resultados de la búsqueda. Si no estás seguro de la URL exacta
   de la convocatoria, no la incluyas.
6. No incluyas convocatorias de estos sitios, que ya se revisan: {excl or "(ninguno)"}.

Devuelve como máximo {maximo} convocatorias, SOLO como un arreglo JSON (sin texto antes ni después), con estos campos.
Los campos con lista deben usar exactamente uno de los valores indicados:
- "nombre": nombre en español y, entre paréntesis, el nombre original
- "oferente": nombre oficial completo de la organización que ofrece la convocatoria
- "tipo_actor": uno de: {"; ".join(TIPOS_ACTOR)}
- "pais_oferente": país sede del oferente
- "modalidad": uno de: {"; ".join(modalidades)}
- "url_convocatoria": página oficial de la convocatoria
- "url_sitio_oferente": página principal del sitio oficial del oferente
- "fecha_limite": DD/MM/AAAA, o "Permanente"
- "fecha_apertura": DD/MM/AAAA si la página la indica, o ""
- "requisitos": objeto con estos criterios según la modalidad (texto en español; "" si la página no lo dice):
    Subvención: {json.dumps(PLANT["Subvención"], ensure_ascii=False)}
    Beca: {json.dumps(PLANT["Beca"], ensure_ascii=False)}
    Premio: {json.dumps(PLANT["Premio"], ensure_ascii=False)}
    Cooperación técnica: {json.dumps(PLANT["Cooperación Técnica"], ensure_ascii=False)}
- "dirigida_a": uno o varios de: {lista("Dirigida a (tipo de publico)")}
- "poblaciones": cero o varios de: {lista("Esta convocatoria prioriza alguna de las siguientes poblaciones?")}
- "tematicas": hasta 3 de: {lista("Áreas temáticas de interés")}
- "ambito_geografico": uno de: {lista("Ámbito Geográfico")}
- "idiomas": uno o varios de: {lista("Idioma/s")}
- "plan_marco": uno de: {lista("Plan Marco de Implementación")}
- "monto": número sin símbolos, o "" si no se indica
- "moneda": código ISO (USD, EUR…) o ""
- "tipo_monto": uno de: Por beneficiario o proyecto; Presupuesto total de la convocatoria; No especificado
- "observaciones_monto": qué cubre el monto, en español (una frase)
- "email": correo de contacto que aparezca en la página, o ""
- "evidencia_colombia": frase textual de la página que muestra que Colombia es elegible
- "descripcion": 2 o 3 frases en español
- "objetivos": objetivo general y específicos de la convocatoria, en español
"""


# --- 2. Llamada ------------------------------------------------------------
def llamar(prompt, clave, modelo, espera=120, buscar_en_google=True):
    """Devuelve (texto, [(uri, título)] de las páginas que Google usó)."""
    prueba = os.environ.get("MAPEO_GEMINI_PRUEBA" if buscar_en_google else "MAPEO_GEMINI_PRUEBA_COMPLETAR")
    if prueba:
        datos = json.loads(Path(prueba).read_text(encoding="utf-8"))
    else:
        if not clave:
            raise ErrorGemini("Falta la clave de Gemini (GEMINI_API_KEY).")
        cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.2}}
        if buscar_en_google:
            cuerpo["tools"] = [{"google_search": {}}]
        else:
            cuerpo["generationConfig"]["responseMimeType"] = "application/json"
        r = requests.post(URL_API.format(modelo=modelo), json=cuerpo, timeout=espera,
                          headers={"x-goog-api-key": clave, "Content-Type": "application/json"})
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", r.text[:300])
            except ValueError:
                msg = r.text[:300]
            raise ErrorGemini(f"Gemini respondió {r.status_code}: {msg}")
        datos = r.json()
    cand = (datos.get("candidates") or [{}])[0]
    texto = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    meta = cand.get("groundingMetadata") or {}
    fuentes = [(c.get("web", {}).get("uri", ""), c.get("web", {}).get("title", "")) for c in meta.get("groundingChunks", [])]
    if not texto.strip():
        raise ErrorGemini(f"Gemini no devolvió texto (motivo: {cand.get('finishReason', 'desconocido')}).")
    return texto, fuentes


def leer_json(texto):
    """Saca el arreglo JSON de la respuesta, aunque venga entre ```json ... ```."""
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", texto, re.S) or re.search(r"(\[.*\])", texto, re.S)
    if not m:
        raise ErrorGemini("La respuesta de Gemini no trae un arreglo JSON.")
    try:
        datos = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ErrorGemini(f"El JSON de Gemini no es válido: {e}") from e
    return [d for d in datos if isinstance(d, dict)]


# --- 3. Verificación de cada candidato -------------------------------------
def _limpiar_url(u):
    u = str(u or "").strip()
    u = re.sub(r"^(https?)//", r"\1://", u, flags=re.I)
    if u.lower().startswith("www."):
        u = "https://" + u
    return DOM.quitar_rastreo(u)


def _fuente_externa(c, catalogo, n):
    url = _limpiar_url(c.get("url_convocatoria"))
    sitio = _limpiar_url(c.get("url_sitio_oferente")) or url
    tipo = c.get("tipo_actor") if c.get("tipo_actor") in TIPOS_ACTOR else "Por clasificar"
    actor = catalogo.buscar(c.get("oferente", "")) if catalogo else None
    mod = modalidad_de(c.get("modalidad"))
    return Fuente(id=f"EXT-{n:02d}", activa=True, tipo=tipo, nombre=str(c.get("oferente") or DOM.host(url)).strip(),
                  pais=str(c.get("pais_oferente") or ""), dominio="https://" + DOM.host(sitio), url_becas="",
                  oficial=_CARACTER.get(tipo, "No Oficial"), idioma="", requiere_navegador=False, fila=0,
                  modalidades=[mod] + [m for m in MODALIDADES if m != mod] if mod else list(MODALIDADES),
                  grupo="Búsqueda externa", actor=actor.nombre if actor else "")


def _propuesta(c):
    partes = [f"Fecha límite: {c.get('fecha_limite', '')}", f"Monto: {c.get('monto', '')} {c.get('moneda', '')}".strip(),
              f"Dirigida a: {c.get('dirigida_a', '')}", f"Temáticas: {c.get('tematicas', '')}",
              f"Evidencia Colombia: «{str(c.get('evidencia_colombia', ''))[:300]}»"]
    return " · ".join(p for p in partes if not p.endswith(": ") and not p.endswith(": «»"))


def _lista(valor, permitidos, maximo=None):
    """Valores de Gemini que están exactamente en la lista del formulario (insensible a mayúsculas y tildes)."""
    from . import texto as tx
    if isinstance(valor, str):
        valor = [v.strip() for v in re.split(r"[;,]\s*(?=[A-ZÁÉÍÓÚÑ0-9])", valor) if v.strip()]
    mapa = {tx.normalizar(p): p for p in permitidos}
    salida = [mapa[tx.normalizar(v)] for v in (valor or []) if tx.normalizar(v) in mapa]
    salida = list(dict.fromkeys(salida))
    return salida[:maximo] if maximo else salida


def completar(fila, c, catalogos, cfg, texto_norm, modalidad, hoy=None):
    """Llena con la propuesta de Gemini los campos que no se pudieron sacar de la página.

    Lo que se lee en la página manda; Gemini solo completa vacíos (y pone en español el nombre y la descripción).
    Devuelve la lista de campos completados, para que el revisor los confirme."""
    from datetime import datetime
    from . import texto as tx
    from .salidas import _multi
    usados = []

    def poner(campo, valor):
        if valor:
            fila[campo] = valor
            usados.append(campo)

    titulo_pagina = fila["Nombre de la Convocatoria"]
    nombre = str(c.get("nombre") or "").strip()
    if nombre and nombre != titulo_pagina:
        fila["[Sistema] Título en la página"] = titulo_pagina
        poner("Nombre de la Convocatoria", nombre if "(" in nombre or not titulo_pagina else f"{nombre} ({titulo_pagina})")
    if c.get("descripcion"):
        fila["[Sistema] Descripción en la página"] = fila.get("Descripción", "")
        poner("Descripción", str(c["descripcion"]).strip())
    poner("Objetivos General y Específicos", str(c.get("objetivos") or "").strip() if not fila.get("Objetivos General y Específicos") else "")
    if not fila.get("Fecha Límite de Aplicación"):
        f = str(c.get("fecha_limite") or "").strip()
        if f.lower().startswith("perman"):
            poner("¿La convocatoria es permanente?", "Si")
            poner("Observaciones a la fecha límite de aplicación", "Convocatoria permanente (según Gemini)")
        else:
            try:
                d = datetime.strptime(f, "%d/%m/%Y").date()
                poner("Fecha Límite de Aplicación", f"{d.day}/{d.month}/{d.year}")
                fila["Tiempo de vencimiento es mayor a un mes y una semana"] = "checked" if (d - (hoy or date.today())).days > 37 else ""
            except ValueError:
                pass
    if not fila.get(CAMPO_APERTURA):
        try:
            d = datetime.strptime(str(c.get("fecha_apertura") or "").strip(), "%d/%m/%Y").date()
            poner(CAMPO_APERTURA, f"{d.day}/{d.month}/{d.year}")
        except ValueError:
            pass
    if not str(fila.get(CAMPO_REQUISITOS, "")).strip():
        criterios = PLANT.get(modalidad.split(" (")[0], ["Requisitos de participación", "Procedimiento de postulación"])
        req = c.get("requisitos") or {}
        if isinstance(req, str):
            req = {criterios[0]: req}
        lineas = [f"{t}: {str(req.get(t) or '').strip()}" for t in criterios]
        if any(str(req.get(t) or "").strip() for t in criterios):
            poner(CAMPO_REQUISITOS, "\n".join(lineas))
    pub = [p for p in fila.get("Dirigida a (tipo de publico)", "").split(",") if p.strip()]
    if not pub or pub == ["No se especifica el público"]:
        poner("Dirigida a (tipo de publico)", _multi(_lista(c.get("dirigida_a"), catalogos.get("Dirigida a (tipo de publico)", []))))
    if not fila.get("Esta convocatoria prioriza alguna de las siguientes poblaciones?"):
        poner("Esta convocatoria prioriza alguna de las siguientes poblaciones?",
              _multi(_lista(c.get("poblaciones"), catalogos.get("Esta convocatoria prioriza alguna de las siguientes poblaciones?", []))))
    if not fila.get("Áreas temáticas de interés"):
        temas = _lista(c.get("tematicas"), catalogos.get("Áreas temáticas de interés", []), 3)
        if temas:
            poner("Áreas temáticas de interés", _multi(temas))
            for campo, valor in reglas.alineacion(temas, cfg, modalidad).items():
                if campo in fila and not fila[campo]:
                    fila[campo] = valor
    amb = _lista(c.get("ambito_geografico"), catalogos.get("Ámbito Geográfico", []), 1)
    if amb and amb[0] != fila.get("Ámbito Geográfico"):
        poner("Ámbito Geográfico", amb[0])
    if not fila.get("Idioma/s"):
        poner("Idioma/s", _multi(_lista(c.get("idiomas"), catalogos.get("Idioma/s", []))))
    if not fila.get("Plan Marco de Implementación"):
        poner("Plan Marco de Implementación", (_lista(c.get("plan_marco"), catalogos.get("Plan Marco de Implementación", []), 1) or [""])[0])
    monto = re.sub(r"[^\d.]", "", str(c.get("monto") or ""))
    moneda = str(c.get("moneda") or "").upper().strip()
    if not fila.get("Financiación") and monto and moneda in ("", "USD"):
        poner("Financiación", f"${float(monto):.2f}")
    obs = str(c.get("observaciones_monto") or "").strip()
    if obs or (monto and moneda and moneda != "USD"):
        poner("Observaciones sobre el financiamiento",
              "; ".join(x for x in (obs, f"Monto según Gemini: {monto} {moneda}" if monto and moneda != "USD" else "") if x))
    tm = str(c.get("tipo_monto") or "").strip()
    if tm in ("Por beneficiario o proyecto", "Presupuesto total de la convocatoria", "No especificado"):
        poner("Tipo de monto", tm)
    correo = str(c.get("email") or "").strip()
    if fila.get("Email para mayor información", "Sin Email") in ("", "Sin Email") and re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", correo):
        if tx.contiene(texto_norm, correo.lower()):  # solo si el correo aparece en la página
            poner("Email para mayor información", correo)
    # ¿La frase que da Gemini como prueba de elegibilidad está de verdad en la página?
    ev = tx.normalizar(str(c.get("evidencia_colombia") or ""))
    fila["[Sistema] Evidencia de Gemini en la página"] = (
        "Sin frase" if not ev else "Sí: la frase está en la página" if ev[:80] in texto_norm else "No: la frase no aparece en la página")
    fila["[Sistema] Campos completados por Gemini"] = ", ".join(usados)
    return usados


def verificar(candidatos, cfg, lector, icetex, duplicados, catalogo, dominios_fuentes, hoy, google=()):
    """Devuelve (filas para revisión, descartadas, fuentes sugeridas)."""
    filas, descartadas, sugeridas, vistas = [], [], {}, set()
    dominios_google = {DOM.host(t) for _, t in google if t} | {DOM.host(u) for u, _ in google if u and "vertexaisearch" not in u}
    for n, c in enumerate(candidatos, start=1):
        url = _limpiar_url(c.get("url_convocatoria"))
        nombre = str(c.get("nombre") or "").strip()
        if not url.startswith("http") or url.rstrip("/").lower() in vistas:
            continue
        vistas.add(url.rstrip("/").lower())
        categoria, explicacion = DOM.clasificar(url)
        if categoria in ("Acortador", "Agregador / intermediario", "Boletín de otra entidad", "ICETEX", "Plataforma de postulación"):
            descartadas.append((f"No es un sitio oficial ({categoria})", nombre, url, "Gemini"))
            continue
        fuente = _fuente_externa(c, catalogo, n)
        r = lector.leer(url)
        if r.estado == -1:
            descartadas.append(("El sitio no permite programas automáticos (robots.txt): revisar a mano", nombre, url, "Gemini"))
            continue
        if not r.ok:
            descartadas.append((f"La página no existe o no respondió ({r.estado}): posible enlace inventado", nombre, url, "Gemini"))
            continue
        if not extraer.es_del_dominio(r.url, url):
            descartadas.append((f"La página redirige a otro sitio ({DOM.host(r.url)})", nombre, url, "Gemini"))
            continue
        datos = extraer.analizar_beca(r, fuente, cfg, hoy, nombre)
        if not datos["titulo"]:
            datos["titulo"] = nombre
        elig = reglas.elegibilidad(datos["texto_norm"], cfg)
        en_icetex = icetex.revisar(datos["titulo"], r.url, datos) if datos["modalidad"] == "Beca" else (False, "No aplica (no es beca)")
        dup = duplicados.revisar(datos["titulo"], r.url)
        fila = salidas.fila_airtable(datos, r.url, fuente, "Búsqueda externa con Gemini", cfg, elig, en_icetex, dup, hoy)
        catalogos = getattr(cfg, "_catalogos", {}) or {}
        usados = completar(fila, c, catalogos, cfg, datos["texto_norm"], datos["modalidad"], hoy)
        fila["[Sistema] Propuesta de Gemini"] = (
            ("Campos completados por Gemini (confirmar en la página): " + ", ".join(usados) + ". " if usados else "")
            + "Frase de elegibilidad: " + fila["[Sistema] Evidencia de Gemini en la página"] + ". " + _propuesta(c))
        fila["[Sistema] Encontrado en Google"] = "Sí" if DOM.host(r.url) in dominios_google or not google else "No"
        motivo = ("Está en ICETEX: " + en_icetex[1] if en_icetex[0] else
                  "No elegible para colombianos según la página: " + elig[2] if elig[0] == "No elegible" else
                  dup if dup.startswith("Ya está en la base") else
                  "Convocatoria vencida: " + datos["evidencia_cierre"] if datos["vencida"] else "")
        if motivo:
            descartadas.append((motivo, datos["titulo"], r.url, "Gemini"))
            continue
        filas.append(fila)
        h = DOM.host(fuente.dominio)
        if h and not any(h == d or h.endswith("." + d) for d in dominios_fuentes):
            s = sugeridas.setdefault(h, {"Dominio oficial": fuente.dominio, "Oferente": fuente.nombre, "Tipo de actor": fuente.tipo,
                                         "País": fuente.pais, "Actor en el catálogo": fuente.actor, "Convocatorias encontradas": []})
            s["Convocatorias encontradas"].append(datos["titulo"])
    for s in sugeridas.values():
        s["Convocatorias encontradas"] = "; ".join(s["Convocatorias encontradas"])
    return filas, descartadas, list(sugeridas.values())


# --- 4. Orquestación ------------------------------------------------------
def buscar(cfg, lector, icetex, duplicados, catalogo, catalogos, hoy=None, modalidades=None, tema="", region="", maximo=10,
           clave=None, modelo=None):
    hoy = hoy or date.today()
    modalidades = [m for m in (modalidad_de(x) for x in (modalidades or [])) if m] or list(MODALIDADES)
    modelo = modelo or os.environ.get("GEMINI_MODEL") or str(cfg.p("Modelo de Gemini", MODELO_POR_DEFECTO) or MODELO_POR_DEFECTO)
    clave = clave or os.environ.get("GEMINI_API_KEY", "")
    dominios_fuentes = {DOM.host(f.dominio) for f in cfg.fuentes if f.dominio}
    cfg._catalogos = catalogos
    prompt = construir_prompt(catalogos, modalidades, hoy, tema, region, maximo, dominios_fuentes)
    log.info("Consultando a Gemini (%s)…", modelo)
    texto, google = llamar(prompt, clave, modelo)
    candidatos = leer_json(texto)
    log.info("Gemini propuso %d convocatorias (%d páginas de Google consultadas). Verificando cada una en su sitio…",
             len(candidatos), len(google))
    return verificar(candidatos, cfg, lector, icetex, duplicados, catalogo, dominios_fuentes, hoy, google) + (candidatos, prompt)


# --- 5. Completar las convocatorias del mapeo normal --------------------------
def prompt_completar(texto, titulo, url, catalogos, modalidad):
    lista = lambda campo: "; ".join(catalogos.get(campo, []))  # noqa: E731
    return f"""Eres analista de la Dirección de Gestión de Demanda de Cooperación Internacional de APC-Colombia.
Lee SOLO el texto de esta página oficial de una convocatoria ({modalidad.split(" (")[0]}) y llena los campos del formulario.
No busques ni inventes nada: si un dato no está en el texto, deja el campo vacío ("" o []).

Página: {url}
Título: {titulo}
Texto (entre <<< y >>>):
<<<{texto[:12000]}>>>

Devuelve SOLO un objeto JSON con estos campos (los de lista deben usar exactamente los valores indicados):
- "nombre": nombre en español y, entre paréntesis, el nombre original si está en otro idioma
- "descripcion": 2 o 3 frases en español
- "objetivos": objetivo general y específicos, en español
- "fecha_limite": DD/MM/AAAA, o "Permanente", o ""
- "fecha_apertura": DD/MM/AAAA si la página la indica, o ""
- "requisitos": objeto con estos criterios de la modalidad {modalidad.split(" (")[0]} (texto en español; "" si la página no lo dice):
    Subvención: {json.dumps(PLANT["Subvención"], ensure_ascii=False)}
    Beca: {json.dumps(PLANT["Beca"], ensure_ascii=False)}
    Premio: {json.dumps(PLANT["Premio"], ensure_ascii=False)}
    Cooperación técnica: {json.dumps(PLANT["Cooperación Técnica"], ensure_ascii=False)}
- "dirigida_a": lista con valores de: {lista("Dirigida a (tipo de publico)")}
- "poblaciones": lista con valores de: {lista("Esta convocatoria prioriza alguna de las siguientes poblaciones?")}
- "tematicas": hasta 3 valores de: {lista("Áreas temáticas de interés")}
- "ambito_geografico": uno de: {lista("Ámbito Geográfico")}
- "idiomas": lista con valores de: {lista("Idioma/s")}
- "plan_marco": uno de: {lista("Plan Marco de Implementación")}
- "monto": número sin símbolos, o ""
- "moneda": código ISO, o ""
- "tipo_monto": uno de: Por beneficiario o proyecto; Presupuesto total de la convocatoria; No especificado
- "observaciones_monto": qué cubre el monto, en español
- "email": correo de contacto que aparezca en el texto, o ""
- "evidencia_colombia": frase textual que muestra quién puede postularse (Colombia, América Latina, extranjeros, todos los países…), o ""
"""


def leer_objeto(texto):
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ErrorGemini("La respuesta de Gemini no trae un objeto JSON.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ErrorGemini(f"El JSON de Gemini no es válido: {e}") from e


def completar_mapeo(filas, cfg, catalogos, hoy, clave=None, modelo=None):
    """Completa con Gemini las convocatorias encontradas por el mapeo, leyendo su página. Devuelve cuántas completó."""
    import time
    from . import texto as tx
    clave = clave or os.environ.get("GEMINI_API_KEY", "")
    if not str(cfg.p("Completar campos con Gemini en el mapeo", "Sí")).lower().startswith("s"):
        return 0
    if not clave and not os.environ.get("MAPEO_GEMINI_PRUEBA_COMPLETAR"):
        log.info("Sin clave de Gemini: las convocatorias quedan con los campos leídos en la página.")
        return 0
    modelo = modelo or os.environ.get("GEMINI_MODEL") or str(cfg.p("Modelo de Gemini", MODELO_POR_DEFECTO) or MODELO_POR_DEFECTO)
    pausa = float(cfg.p("Pausa entre consultas a Gemini (segundos)", 5) or 0)
    maximo = int(cfg.p("Máximo de convocatorias a completar con Gemini por corrida", 80) or 0)
    pendientes = [f for f in filas if f.get("_texto") and f.get("[Sistema] Estado") != "Sin cambios"][:maximo]
    if pendientes:
        log.info("Completando %d convocatorias con Gemini (%s), leyendo su página…", len(pendientes), modelo)
    hechas = 0
    for i, fila in enumerate(pendientes):
        try:
            texto, _ = llamar(prompt_completar(fila["_texto"], fila["Nombre de la Convocatoria"], fila["Cómo aplicar"],
                                               catalogos, fila["Modalidad"]), clave, modelo, buscar_en_google=False)
            c = leer_objeto(texto)
        except (ErrorGemini, requests.RequestException) as e:
            log.warning("Gemini no pudo completar «%s»: %s", fila["Nombre de la Convocatoria"][:60], e)
            if "429" in str(e):  # límite del plan: no seguir insistiendo
                log.warning("Se alcanzó el límite de Gemini: las demás quedan con los campos leídos en la página.")
                break
            continue
        usados = completar(fila, c, catalogos, cfg, tx.normalizar(fila["_texto"]), fila["Modalidad"], hoy)
        fila["[Sistema] Propuesta de Gemini"] = (
            ("Campos completados por Gemini leyendo la página (confirmar): " + ", ".join(usados) + ". " if usados else "")
            + "Frase de elegibilidad: " + fila["[Sistema] Evidencia de Gemini en la página"] + ".")
        hechas += 1
        if pausa and i < len(pendientes) - 1 and not os.environ.get("MAPEO_GEMINI_PRUEBA_COMPLETAR"):
            time.sleep(pausa)
    return hechas
