"""Usuarios del sistema: nombre de usuario y contraseña (sin correos).

Seguridad:
- Contraseñas de al menos 10 caracteres con mayúscula, minúscula, número y símbolo; sin el usuario ni el nombre,
  sin secuencias (1234, abcd), sin repeticiones (aaaa) y que no sean contraseñas comunes.
- Se guardan cifradas con PBKDF2-SHA256 (600.000 iteraciones) y sal propia.
- Las contraseñas que entrega el administrador son temporales: hay que cambiarlas al primer ingreso.
- Después de 5 intentos fallidos la cuenta se bloquea 15 minutos.
- Recuperación sin correo:
    1. Códigos de recuperación de un solo uso (10 códigos, se muestran una sola vez).
    2. El administrador restablece la contraseña (queda una temporal).
    3. Si es el único administrador: python mapeo.py restablecer-clave --usuario ... (en el computador, con los secretos).
- Las cuentas se guardan cifradas en la base cuando existe el secreto USUARIOS_CLAVE (obligatorio si el repositorio
  de datos es público).
"""
import hashlib
import hmac
import re
import secrets
import string
import time

ROLES = {
    "admin": "Administrador del sistema: usuarios, catálogo de actores, configuración del mapeo e importación masiva; también revisa",
    "revisor": "Revisa y aprueba convocatorias, corrige la base, ejecuta el mapeo, consulta el dashboard y genera informes",
}
LARGO_MINIMO = 10
ITERACIONES = 600_000
INTENTOS_MAXIMOS = 5
MINUTOS_BLOQUEO = 15
N_CODIGOS = 10
SIMBOLOS = "!@#$%&*+-_=?.:;"
COMUNES = {"contraseña", "contrasena", "password", "passw0rd", "qwerty", "123456", "admin", "administrador",
           "apccolombia", "apc-colombia", "colombia", "convocatoria", "convocatorias", "bogota", "dgdci", "bienvenido",
           "cambiar", "clave", "secreto", "letmein", "welcome"}
POLITICA = (f"Mínimo {LARGO_MINIMO} caracteres, con al menos una mayúscula, una minúscula, un número y un símbolo "
            f"({SIMBOLOS}). No puede contener tu usuario ni tu nombre, ni secuencias (1234, abcd), ni el mismo carácter "
            "cuatro veces seguidas, ni palabras comunes como «contraseña» o «colombia».")


class ErrorClave(ValueError):
    pass


# --- contraseñas --------------------------------------------------------------
def _hash(clave, sal, iteraciones=ITERACIONES):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), iteraciones).hex()


def _sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _secuencia(t, n=4):
    t = t.lower()
    for i in range(len(t) - n + 1):
        trozo = t[i:i + n]
        if len(set(trozo)) == 1:
            return True
        cods = [ord(c) for c in trozo]
        difs = {b - a for a, b in zip(cods, cods[1:])}
        if difs in ({1}, {-1}) and (trozo.isalpha() or trozo.isdigit()):
            return True
    return False


def problemas_clave(clave, usuario="", nombre=""):
    """Lista de motivos por los que la contraseña no cumple la política (vacía si cumple)."""
    p = []
    if len(clave) < LARGO_MINIMO:
        p.append(f"tiene menos de {LARGO_MINIMO} caracteres")
    if not re.search(r"[A-ZÁÉÍÓÚÑ]", clave):
        p.append("le falta una mayúscula")
    if not re.search(r"[a-záéíóúñ]", clave):
        p.append("le falta una minúscula")
    if not re.search(r"\d", clave):
        p.append("le falta un número")
    if not re.search(r"[^\w\s]|_", clave):
        p.append("le falta un símbolo")
    base = _sin_tildes(clave)
    partes = [x for x in re.split(r"[\s._-]+", _sin_tildes(f"{usuario} {nombre}")) if len(x) >= 4]
    if any(x in base for x in partes):
        p.append("contiene tu usuario o tu nombre")
    if any(c in re.sub(r"[^a-z0-9-]", "", base) for c in COMUNES if len(c) >= 5) or base in COMUNES:
        p.append("contiene una palabra común")
    if _secuencia(clave):
        p.append("tiene una secuencia o un carácter repetido (1234, abcd, aaaa)")
    return p


def validar_clave(clave, usuario="", nombre=""):
    p = problemas_clave(clave, usuario, nombre)
    if p:
        raise ErrorClave("La contraseña no es segura: " + "; ".join(p) + ".")


def generar_clave(largo=14):
    """Contraseña aleatoria que cumple la política (sin caracteres que se confunden: 0/O, 1/l/I)."""
    may, minu, num = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789"
    todos = may + minu + num + SIMBOLOS
    while True:
        c = [secrets.choice(may), secrets.choice(minu), secrets.choice(num), secrets.choice(SIMBOLOS)]
        c += [secrets.choice(todos) for _ in range(largo - 4)]
        secrets.SystemRandom().shuffle(c)
        clave = "".join(c)
        if not problemas_clave(clave):
            return clave


def _codigo():
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    t = "".join(secrets.choice(alfabeto) for _ in range(10))
    return f"{t[:5]}-{t[5:]}"


def _normalizar_codigo(c):
    return re.sub(r"[^A-Z0-9]", "", str(c).upper())


# --- cuentas ------------------------------------------------------------------
def _nueva_sal_hash(clave):
    sal = secrets.token_hex(16)
    return sal, _hash(clave, sal), ITERACIONES


def crear(almacen, usuario, nombre, rol, clave=None, temporal=None):
    """Crea la cuenta o restablece su contraseña. Sin clave se genera una temporal (debe cambiarse al entrar).

    Devuelve la contraseña (para mostrarla una sola vez)."""
    if rol not in ROLES:
        raise ValueError(f"Rol no válido. Usa: {', '.join(ROLES)}")
    usuario = usuario.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,30}", usuario):
        raise ValueError("El usuario debe tener entre 3 y 30 caracteres: letras sin tildes, números, punto, guion o guion bajo")
    if not str(nombre or "").strip():
        raise ValueError("Falta el nombre completo")
    temporal = clave is None if temporal is None else temporal
    clave = clave or generar_clave()
    validar_clave(clave, usuario, nombre)
    previa = almacen.cuentas().get(usuario, {})
    sal, h, it = _nueva_sal_hash(clave)
    almacen.guardar_cuenta({
        "usuario": usuario, "nombre": nombre.strip(), "rol": rol, "sal": sal, "hash": h, "iter": it,
        "activo": 1, "debe_cambiar": bool(temporal), "fallidos": 0, "bloqueado_hasta": 0,
        "codigos": previa.get("codigos", []), "actualizado": time.time()})
    return clave


def restablecer(almacen, usuario):
    """El administrador restablece la contraseña: queda una temporal que se cambia al entrar."""
    c = almacen.cuentas().get(usuario.strip().lower())
    if not c:
        raise ValueError("No existe ese usuario")
    return crear(almacen, c["usuario"], c["nombre"], c["rol"])


def verificar(almacen, usuario, clave):
    """Devuelve (sesión o None, mensaje). Lleva la cuenta de intentos fallidos y bloquea la cuenta."""
    usuario = str(usuario or "").strip().lower()
    c = almacen.cuentas().get(usuario)
    ahora = time.time()
    if not c or not c.get("activo", 1):
        _hash(clave or "x", "00" * 16)  # mismo tiempo de respuesta exista o no la cuenta
        return None, "Usuario o contraseña incorrectos."
    if c.get("bloqueado_hasta", 0) > ahora:
        minutos = int((c["bloqueado_hasta"] - ahora) // 60) + 1
        return None, f"La cuenta está bloqueada por intentos fallidos. Intenta de nuevo en {minutos} minutos."
    if hmac.compare_digest(_hash(clave or "", c["sal"], c.get("iter", 200_000)), c["hash"]):
        if c.get("fallidos") or c.get("bloqueado_hasta"):
            almacen.guardar_cuenta(c | {"fallidos": 0, "bloqueado_hasta": 0})
        return {"usuario": c["usuario"], "nombre": c["nombre"], "rol": c["rol"],
                "debe_cambiar": bool(c.get("debe_cambiar")), "sin_codigos": not any(not x["usado"] for x in c.get("codigos", []))}, ""
    fallidos = c.get("fallidos", 0) + 1
    cambios = {"fallidos": fallidos}
    if fallidos >= INTENTOS_MAXIMOS:
        cambios = {"fallidos": 0, "bloqueado_hasta": ahora + MINUTOS_BLOQUEO * 60}
    almacen.guardar_cuenta(c | cambios)
    if "bloqueado_hasta" in cambios:
        return None, f"Demasiados intentos fallidos: la cuenta queda bloqueada {MINUTOS_BLOQUEO} minutos."
    return None, f"Usuario o contraseña incorrectos. Te quedan {INTENTOS_MAXIMOS - fallidos} intentos."


def cambiar_clave(almacen, usuario, actual, nueva, confirmacion=None):
    c = almacen.cuentas().get(usuario.strip().lower())
    if not c:
        raise ValueError("No existe ese usuario")
    if not hmac.compare_digest(_hash(actual or "", c["sal"], c.get("iter", 200_000)), c["hash"]):
        raise ErrorClave("La contraseña actual no es correcta.")
    _poner_clave(almacen, c, nueva, confirmacion)


def _poner_clave(almacen, c, nueva, confirmacion=None):
    if confirmacion is not None and nueva != confirmacion:
        raise ErrorClave("La nueva contraseña y su confirmación no coinciden.")
    if hmac.compare_digest(_hash(nueva, c["sal"], c.get("iter", 200_000)), c["hash"]):
        raise ErrorClave("La nueva contraseña debe ser distinta de la anterior.")
    validar_clave(nueva, c["usuario"], c["nombre"])
    sal, h, it = _nueva_sal_hash(nueva)
    almacen.guardar_cuenta(c | {"sal": sal, "hash": h, "iter": it, "debe_cambiar": False, "fallidos": 0,
                                "bloqueado_hasta": 0, "actualizado": time.time()})


def generar_codigos(almacen, usuario):
    """Genera códigos de recuperación nuevos (anula los anteriores). Devuelve los códigos para mostrarlos una vez."""
    c = almacen.cuentas().get(usuario.strip().lower())
    if not c:
        raise ValueError("No existe ese usuario")
    codigos, guardados = [], []
    for _ in range(N_CODIGOS):
        cod = _codigo()
        sal = secrets.token_hex(16)
        codigos.append(cod)
        guardados.append({"sal": sal, "hash": _hash(_normalizar_codigo(cod), sal, 100_000), "usado": False})
    almacen.guardar_cuenta(c | {"codigos": guardados})
    return codigos


def recuperar(almacen, usuario, codigo, nueva, confirmacion=None):
    """Recupera el acceso con un código de un solo uso y pone una contraseña nueva."""
    usuario = str(usuario or "").strip().lower()
    c = almacen.cuentas().get(usuario)
    error = ErrorClave("Usuario o código de recuperación incorrectos.")
    if not c or not c.get("activo", 1):
        raise error
    if c.get("bloqueado_hasta", 0) > time.time():
        raise ErrorClave("La cuenta está bloqueada por intentos fallidos. Espera unos minutos.")
    cod = _normalizar_codigo(codigo)
    for i, x in enumerate(c.get("codigos", [])):
        if not x["usado"] and hmac.compare_digest(_hash(cod, x["sal"], 100_000), x["hash"]):
            if confirmacion is not None and nueva != confirmacion:
                raise ErrorClave("La nueva contraseña y su confirmación no coinciden.")
            validar_clave(nueva, c["usuario"], c["nombre"])
            codigos = [dict(y) for y in c["codigos"]]
            codigos[i]["usado"] = True
            c = c | {"codigos": codigos}
            _poner_clave(almacen, c, nueva)
            return sum(1 for y in codigos if not y["usado"])
    fallidos = c.get("fallidos", 0) + 1
    almacen.guardar_cuenta(c | ({"fallidos": 0, "bloqueado_hasta": time.time() + MINUTOS_BLOQUEO * 60}
                                if fallidos >= INTENTOS_MAXIMOS else {"fallidos": fallidos}))
    raise error


def codigos_disponibles(almacen, usuario):
    c = almacen.cuentas().get(usuario.strip().lower(), {})
    return sum(1 for x in c.get("codigos", []) if not x["usado"])


# --- instalación y recuperación del administrador (en línea, con CLAVE_INSTALACION) ----------
def clave_instalacion_correcta(dada, esperada):
    return bool(esperada) and len(esperada) >= 32 and hmac.compare_digest(str(dada or "").strip(), esperada.strip())


def crear_primer_administrador(almacen, clave_instalacion, esperada, usuario, nombre, clave, confirmacion):
    """Solo funciona si no hay ninguna cuenta. Protegida con el secreto CLAVE_INSTALACION."""
    if almacen.cuentas():
        raise ErrorClave("Ya existe al menos una cuenta: el primer administrador ya se creó.")
    if not clave_instalacion_correcta(clave_instalacion, esperada):
        time.sleep(1)
        raise ErrorClave("La clave de instalación no es correcta.")
    if clave != confirmacion:
        raise ErrorClave("La contraseña y su confirmación no coinciden.")
    return crear(almacen, usuario, nombre, "admin", clave=clave, temporal=False)


def recuperar_administrador(almacen, clave_instalacion, esperada, usuario, nueva, confirmacion):
    """Último recurso en línea: el administrador perdió la contraseña y los códigos."""
    if not clave_instalacion_correcta(clave_instalacion, esperada):
        time.sleep(1)
        raise ErrorClave("La clave de instalación no es correcta.")
    c = almacen.cuentas().get(str(usuario or "").strip().lower())
    if not c or c.get("rol") != "admin":
        raise ErrorClave("Ese usuario no es administrador. Los revisores recuperan el acceso con sus códigos o con el administrador.")
    if nueva != confirmacion:
        raise ErrorClave("La nueva contraseña y su confirmación no coinciden.")
    validar_clave(nueva, c["usuario"], c["nombre"])
    sal, h, it = _nueva_sal_hash(nueva)
    almacen.guardar_cuenta(c | {"sal": sal, "hash": h, "iter": it, "activo": 1, "debe_cambiar": False, "fallidos": 0,
                                "bloqueado_hasta": 0, "actualizado": time.time()})
