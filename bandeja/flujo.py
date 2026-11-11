"""Flujo de revisión (una sola revisión) con bloqueo por actor nuevo.

  Ingreso (mapeo automático o registro manual)
      │
      ▼
  Por revisar ──(revisor corrige, marca la lista de chequeo y aprueba)──► ¿actor creado en CICLOPE?
      │                                                                     │sí                  │no
      │                                                                     ▼                    ▼
      └──(descartar con motivo)──► Descartada                      Aprobada · en la base   Actor pendiente de crear
                                                                                                  │
                                       (se registra el actor como creado en CICLOPE) ─────────────┘
                                       → entra sola a la base si la revisión ya estaba aprobada
"""
from datetime import date

from bandeja.almacen import ahora, nuevo_item
from calidad import reglas as R
from calidad.actores import Actor

# Procedimiento de validación de convocatorias de la DGDCI (numerales 1, 2, 3 y 4).
# Los criterios de socialización (numeral 5) NO están aquí: no deciden si una convocatoria se aprueba.
LISTA_CHEQUEO = [
    "Fuente oficial: el enlace es del cooperante, no de un agregador (FundsforNGOs…) ni de un boletín de otra entidad",
    "Vigencia: la convocatoria está abierta o tiene apertura anunciada oficialmente; fechas de apertura y cierre verificadas",
    "Colombia es elegible: la convocatoria está dirigida a actores colombianos o permite la participación de Colombia",
    "Cooperante: la entidad responsable es el actor correcto",
    "Modalidad, población objetivo y áreas temáticas revisadas",
    "Requisitos, procedimiento de postulación y criterios de la modalidad registrados",
    "Monto de financiación o descripción de los beneficios registrado",
    "La información registrada corresponde con la fuente oficial (nombre en español, descripción, fechas y monto)",
    "Los enlaces de información y de postulación funcionan",
    "Si es beca: no se ofrece vía ICETEX",
    "No está registrada previamente (sin duplicado)",
]


def comprobar_enlaces(datos, espera=15):
    """Abre los enlaces de la convocatoria y dice si responden. Devuelve [(campo, enlace, estado, ok)]."""
    import requests
    from calidad import dominios as DOM
    salida = []
    for campo in ("Cómo aplicar", "Link de la Fuente Oferente"):
        for url in DOM.enlaces(datos.get(campo, ""))[:3]:
            u = url if url.lower().startswith("http") else "https://" + url
            u = u.replace("https//", "https://").replace("http//", "http://")
            try:
                r = requests.get(u, timeout=espera, allow_redirects=True, stream=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; RevisionConvocatoriasDGDCI/1.0)"})
                r.close()
                ok = r.status_code < 400 or r.status_code in (401, 403)  # 401/403: existe pero pide inicio de sesión o bloquea robots
                estado = f"{r.status_code}" + (f" · redirige a {DOM.host(r.url)}" if DOM.host(r.url) != DOM.host(u) else "")
                if r.status_code in (401, 403):
                    estado += " · el sitio no deja revisarlo automáticamente: abrirlo a mano"
            except requests.RequestException as e:
                ok, estado = False, f"No responde ({type(e).__name__})"
            salida.append((campo, url, estado, ok))
    return salida


class ErrorFlujo(Exception):
    pass


def _evento(item, usuario, accion, detalle=""):
    item.setdefault("historial", []).append({"fecha": ahora(), "usuario": usuario, "accion": accion, "detalle": detalle})


def evaluar(almacen, datos, hoy=None, catalogo=None, base=None):
    """Valida con el catálogo y la base actuales (o con copias ya leídas, para no leer la base a cada clic)."""
    catalogo = catalogo if catalogo is not None else almacen.catalogo()
    base = base if base is not None else almacen.base()
    return R.validar(datos, catalogo, base, hoy=hoy or date.today(), nuevo=True)


def ingresar(almacen, datos, origen, usuario, meta=None, hoy=None):
    """Toda convocatoria entra por aquí: nunca directo a la base."""
    norm, hallazgos = evaluar(almacen, datos, hoy)
    item = nuevo_item(norm, origen, meta)
    item["meta"]["hallazgos_ingreso"] = [h.__dict__ for h in hallazgos]
    _evento(item, usuario, "Ingreso", origen)
    almacen.guardar_item(item)
    return item, hallazgos


def guardar_cambios(almacen, item, datos, usuario):
    item["datos"] = dict(datos)
    _evento(item, usuario, "Edición")
    almacen.guardar_item(item)
    return item


def aprobar(almacen, item, datos, usuario, chequeo, hoy=None):
    """Aprueba la revisión. Devuelve (estado_nuevo, hallazgos)."""
    faltan = [c for c in LISTA_CHEQUEO if not chequeo.get(c)]
    if faltan:
        raise ErrorFlujo("Falta marcar en la lista de chequeo: " + "; ".join(faltan))
    norm, hallazgos = evaluar(almacen, datos, hoy)
    bloqueantes = [h for h in hallazgos if h.nivel == "Error" and h.regla != "R07"]
    if bloqueantes:
        raise ErrorFlujo("Corrige primero: " + "; ".join(f"{h.campo}: {h.problema}" for h in bloqueantes))
    item["datos"] = norm
    item["revisado_por"] = usuario
    item["meta"]["revision_aprobada"] = True
    item["meta"]["chequeo"] = {c: True for c in LISTA_CHEQUEO}
    if any(h.regla == "R07" for h in hallazgos):
        item["estado"] = "Actor pendiente de crear"
        _evento(item, usuario, "Revisión aprobada", "En espera: el actor no está creado en CICLOPE")
    else:
        item["id_base"] = almacen.enviar_a_base(norm)
        item["estado"] = "Aprobada"
        _evento(item, usuario, "Aprobada y enviada a la base")
    almacen.guardar_item(item)
    return item["estado"], hallazgos


def descartar(almacen, item, usuario, motivo):
    if not motivo.strip():
        raise ErrorFlujo("Escribe el motivo del descarte")
    item["estado"] = "Descartada"
    item["observacion"] = motivo
    _evento(item, usuario, "Descartada", motivo)
    almacen.guardar_item(item)


def agregar_actor(almacen, nombre, tipo, usuario, pais="", web="", estado="Pendiente de crear"):
    """Agrega un actor nuevo al catálogo (queda pendiente de crear en CICLOPE)."""
    nombre = nombre.strip()
    if not nombre:
        raise ErrorFlujo("Escribe el nombre del actor")
    existente = almacen.catalogo().buscar(nombre)
    if existente:
        return existente
    from calidad.actores import sitio_oficial
    actor = Actor(nombre=nombre, tipo=tipo, estado_ciclope=estado, pais=pais, web=sitio_oficial(web) or "",
                  observaciones=f"Agregado por {usuario} el {ahora()}")
    almacen.guardar_actor(actor)
    return actor


def registrar_actor_creado(almacen, nombre_actual, nombre_en_ciclope, usuario, tipo=None, hoy=None):
    """Marca un actor como creado en CICLOPE y libera las convocatorias que lo esperaban.

    Si la revisión de una convocatoria ya estaba aprobada, entra sola a la base."""
    catalogo = almacen.catalogo()
    actor = catalogo.buscar(nombre_actual)
    if actor is None:
        raise ErrorFlujo(f"No existe el actor «{nombre_actual}» en el catálogo")
    anterior = actor.nombre
    nombre_en_ciclope = nombre_en_ciclope.strip() or anterior
    if nombre_en_ciclope != anterior:
        actor.alias = sorted(set(actor.alias + [anterior]))
        actor.nombre = nombre_en_ciclope
    actor.estado_ciclope = "Creado en CICLOPE"
    if tipo:
        actor.tipo = tipo
    actor.observaciones = (actor.observaciones + f" | Creado en CICLOPE, registrado por {usuario} el {ahora()}").strip(" |")
    almacen.guardar_actor(actor, nombre_anterior=anterior)

    resultados = []
    for item in almacen.items("Actor pendiente de crear"):
        if R.limpiar_nombre(item["datos"].get("Nombre de la Fuente", "")).lower() not in (
                anterior.lower(), nombre_en_ciclope.lower()):
            continue
        item["datos"]["Nombre de la Fuente"] = actor.nombre
        item["datos"]["Nombre de actor en CICLOPE"] = actor.nombre
        norm, hallazgos = evaluar(almacen, item["datos"], hoy)
        bloqueantes = [h for h in hallazgos if h.nivel == "Error"]
        if item["meta"].get("revision_aprobada") and not bloqueantes:
            item["datos"] = norm
            item["id_base"] = almacen.enviar_a_base(norm)
            item["estado"] = "Aprobada"
            _evento(item, usuario, "Actor creado en CICLOPE", "Enviada a la base")
        else:
            item["estado"] = "Por revisar"
            _evento(item, usuario, "Actor creado en CICLOPE", "Vuelve a revisión")
        almacen.guardar_item(item)
        resultados.append((item["id"], item["estado"]))
    return actor, resultados
