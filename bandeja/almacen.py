"""Base de datos propia del sistema (reemplaza a Airtable).

- Un archivo SQLite con dos tablas: 'convocatorias' (todas, con su estado) y 'actores' (catálogo).
- La base de convocatorias publicada = las convocatorias en estado 'Aprobada'.
- En Hugging Face (u otro servidor sin disco permanente) el archivo se sincroniza con un
  repositorio privado de datos en Hugging Face: se descarga al iniciar y se sube después de
  cada cambio. Cada cambio queda como una versión, así que también sirve de respaldo.

Variables de entorno:
  BASE_DATOS        ruta del archivo SQLite (por defecto datos/convocatorias.db)
  HF_DATASET_REPO   repositorio privado de datos, p. ej. "apc-dgdci/convocatorias-datos" (opcional)
  HF_TOKEN          token de Hugging Face con permiso de escritura (si se usa HF_DATASET_REPO)
"""
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from calidad.actores import Actor, Catalogo, caracter_de, limpiar_nombre

RAIZ = Path(__file__).resolve().parents[1]
BASE_INICIAL = RAIZ / "datos" / "base_inicial.db"  # convocatorias migradas de Airtable, sin usuarios
ESTADOS = ["Por revisar", "Actor pendiente de crear", "Aprobada", "Descartada"]
ESQUEMA = """
CREATE TABLE IF NOT EXISTS convocatorias (
  id TEXT PRIMARY KEY, estado TEXT NOT NULL, origen TEXT, ingreso TEXT, revisado_por TEXT, observacion TEXT,
  nombre TEXT, actor TEXT, datos TEXT NOT NULL, meta TEXT, historial TEXT, actualizado TEXT);
CREATE INDEX IF NOT EXISTS idx_estado ON convocatorias(estado);
CREATE TABLE IF NOT EXISTS actores (
  nombre TEXT PRIMARY KEY, tipo TEXT, estado_ciclope TEXT, alias TEXT, pais TEXT, web TEXT, observaciones TEXT);
CREATE TABLE IF NOT EXISTS archivos (nombre TEXT PRIMARY KEY, contenido BLOB, actualizado TEXT);
CREATE TABLE IF NOT EXISTS privado (clave TEXT PRIMARY KEY, valor TEXT);
"""
# Las cuentas de usuario viven en privado['cuentas']: JSON cifrado con USUARIOS_CLAVE ("fernet:..."),
# o JSON sin cifrar ("json:...") solo si la base no se publica en un repositorio público.


def cifrador(clave_secreta):
    """Fernet a partir del secreto USUARIOS_CLAVE (texto largo y aleatorio, mínimo 32 caracteres)."""
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    if len(clave_secreta) < 32:
        raise RuntimeError("USUARIOS_CLAVE debe tener al menos 32 caracteres aleatorios.")
    llave = hashlib.pbkdf2_hmac("sha256", clave_secreta.encode(), b"sistema-convocatorias-dgdci", 200_000)
    return Fernet(base64.urlsafe_b64encode(llave))


class ErrorCuentas(RuntimeError):
    pass


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def nuevo_item(datos, origen, meta=None, estado="Por revisar"):
    return {"id": uuid.uuid4().hex[:10], "estado": estado, "origen": origen, "ingreso": ahora(),
            "datos": datos, "meta": meta or {}, "historial": [], "revisado_por": "", "observacion": ""}


class Conflicto(Exception):
    pass


class SincronizadorHF:
    """Guarda el archivo de la base en un repositorio privado de datos de Hugging Face."""

    def __init__(self, repo_id, token, archivo="convocatorias.db"):
        from huggingface_hub import HfApi
        self.api = HfApi(token=token)
        self.repo_id, self.token, self.archivo = repo_id, token, archivo
        self.sha = None
        self.revisado = 0.0
        self.publico = False
        self.api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
        try:
            self.publico = not self.api.repo_info(repo_id, repo_type="dataset").private
        except Exception:  # noqa: BLE001
            pass

    def remoto(self):
        return self.api.repo_info(self.repo_id, repo_type="dataset").sha

    def existe(self):
        return self.archivo in self.api.list_repo_files(self.repo_id, repo_type="dataset")

    def descargar(self, destino):
        from huggingface_hub import hf_hub_download
        sha = self.remoto()
        if self.existe():
            ruta = hf_hub_download(self.repo_id, self.archivo, repo_type="dataset", revision=sha, token=self.token,
                                   force_download=True)
            Path(destino).write_bytes(Path(ruta).read_bytes())
        self.sha = sha
        self.revisado = time.time()

    def subir(self, origen, mensaje):
        from huggingface_hub import CommitOperationAdd
        from huggingface_hub.errors import HfHubHTTPError
        try:
            info = self.api.create_commit(self.repo_id, repo_type="dataset", commit_message=mensaje[:200],
                                          operations=[CommitOperationAdd(self.archivo, str(origen))],
                                          parent_commit=self.sha)
        except HfHubHTTPError as e:
            if e.response is not None and e.response.status_code in (409, 412):
                raise Conflicto(str(e)) from e
            raise
        self.sha = info.oid
        self.revisado = time.time()


class SincronizadorGitHub:
    """Guarda el archivo de la base en un repositorio PRIVADO de GitHub (API de contenidos).

    Cada cambio es un commit: el historial del repositorio sirve de copia de seguridad.
    Para no pisar cambios de otra persona se envía el sha del archivo que se leyó; si cambió, GitHub
    responde 409 y el almacén vuelve a aplicar el cambio sobre la versión nueva.
    Token: fine-grained, solo para ese repositorio, con permiso Contents: Read and write.
    """
    API = "https://api.github.com"

    def __init__(self, repo, token, archivo="convocatorias.db", rama="main", sesion=None):
        import requests
        self.repo, self.archivo, self.rama = repo.strip().strip("/"), archivo, rama
        self.http = sesion or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
                                  "User-Agent": "sistema-convocatorias-dgdci"})
        self.sha = None
        self.revisado = 0.0
        r = self.http.get(f"{self.API}/repos/{self.repo}", timeout=30)
        if r.status_code == 404:
            raise RuntimeError(f"No existe el repositorio {self.repo} o el token no tiene acceso. Créalo como privado en GitHub.")
        r.raise_for_status()
        self.publico = not r.json().get("private", False)

    def _url(self):
        return f"{self.API}/repos/{self.repo}/contents/{self.archivo}"

    def remoto(self):
        r = self.http.get(self._url(), params={"ref": self.rama}, timeout=30,
                          headers={"Accept": "application/vnd.github.object+json"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("sha")

    def existe(self):
        return self.remoto() is not None

    def descargar(self, destino):
        sha = self.remoto()
        if sha:
            r = self.http.get(self._url(), params={"ref": self.rama}, timeout=120,
                              headers={"Accept": "application/vnd.github.raw+json"})
            r.raise_for_status()
            Path(destino).write_bytes(r.content)
        self.sha = sha
        self.revisado = time.time()

    def subir(self, origen, mensaje):
        import base64
        cuerpo = {"message": mensaje[:200], "branch": self.rama,
                  "content": base64.b64encode(Path(origen).read_bytes()).decode()}
        if self.sha:
            cuerpo["sha"] = self.sha
        r = self.http.put(self._url(), json=cuerpo, timeout=120, headers={"Accept": "application/vnd.github+json"})
        if r.status_code in (409, 422) and ("sha" in r.text.lower() or r.status_code == 409):
            raise Conflicto(r.text[:300])
        r.raise_for_status()
        self.sha = r.json()["content"]["sha"]
        self.revisado = time.time()


class AlmacenSQLite:
    def __init__(self, ruta=None, sincronizador=None, refresco_segundos=30, clave_cuentas=None, base_inicial=None):
        self.ruta = Path(ruta or os.environ.get("BASE_DATOS") or RAIZ / "datos" / "convocatorias.db")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.sync = sincronizador
        self.refresco = refresco_segundos
        clave_cuentas = clave_cuentas if clave_cuentas is not None else os.environ.get("USUARIOS_CLAVE", "")
        self.fernet = cifrador(clave_cuentas) if clave_cuentas else None
        if self.sync and getattr(self.sync, "publico", False) and not self.fernet:
            raise ErrorCuentas("El repositorio de datos es público: define el secreto USUARIOS_CLAVE para que las "
                               "cuentas de usuario se guarden cifradas.")
        if self.sync:
            self.sync.descargar(self.ruta)
        semilla = Path(base_inicial) if base_inicial else None
        if semilla and semilla.exists() and not (self.sync and self.sync.sha) and not self.ruta.exists():
            import shutil
            shutil.copy(semilla, self.ruta)  # primera vez: se parte de las convocatorias migradas
        con = self._abrir()
        con.executescript(ESQUEMA)
        con.commit()
        con.close()
        self._migrar_usuarios_antiguos()
        if self.sync and not self.sync.existe():
            self.sync.subir(self.ruta, "Base inicial")

    # -- conexión y sincronización -----------------------------------------------
    def _abrir(self):
        con = sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA secure_delete=ON")  # lo borrado no queda legible dentro del archivo
        return con

    def _refrescar(self, forzar=False):
        if not self.sync:
            return
        if forzar or time.time() - self.sync.revisado > self.refresco:
            remoto = self.sync.remoto()
            if remoto != self.sync.sha:
                self.sync.descargar(self.ruta)
            self.sync.revisado = time.time()

    def _leer(self, sql, params=()):
        self._refrescar()
        con = self._abrir()
        try:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()

    def _escribir(self, operacion, mensaje):
        """Aplica una operación; si otra persona guardó al mismo tiempo, se vuelve a aplicar sobre su versión."""
        for _ in range(4):
            self._refrescar(forzar=True)
            con = self._abrir()
            try:
                operacion(con)
                con.commit()
            finally:
                con.close()
            if not self.sync:
                return
            try:
                self.sync.subir(self.ruta, mensaje)
                return
            except Conflicto:
                self.sync.descargar(self.ruta)
        raise RuntimeError("No se pudo guardar: hubo demasiados cambios simultáneos. Intenta de nuevo.")

    # -- convocatorias ---------------------------------------------------------
    @staticmethod
    def _item(r):
        return {"id": r["id"], "estado": r["estado"], "origen": r["origen"] or "", "ingreso": r["ingreso"] or "",
                "revisado_por": r["revisado_por"] or "", "observacion": r["observacion"] or "",
                "datos": json.loads(r["datos"]), "meta": json.loads(r["meta"] or "{}"),
                "historial": json.loads(r["historial"] or "[]")}

    def items(self, estado=None):
        if estado:
            filas = self._leer("SELECT * FROM convocatorias WHERE estado=? ORDER BY ingreso", (estado,))
        else:
            filas = self._leer("SELECT * FROM convocatorias ORDER BY ingreso")
        return [self._item(r) for r in filas]

    def item(self, id_):
        filas = self._leer("SELECT * FROM convocatorias WHERE id=?", (id_,))
        return self._item(filas[0]) if filas else None

    @staticmethod
    def _fila(item):
        d = item["datos"]
        return (item["id"], item["estado"], item.get("origen", ""), item.get("ingreso", ""), item.get("revisado_por", ""),
                item.get("observacion", ""), d.get("Nombre de la Convocatoria", ""), d.get("Nombre de la Fuente", ""),
                json.dumps(d, ensure_ascii=False, default=str), json.dumps(item.get("meta", {}), ensure_ascii=False, default=str),
                json.dumps(item.get("historial", []), ensure_ascii=False, default=str), ahora())

    def guardar_item(self, item):
        def op(con):
            con.execute("INSERT OR REPLACE INTO convocatorias VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", self._fila(item))
        self._escribir(op, f"{item['estado']}: {item['datos'].get('Nombre de la Convocatoria', '')}")

    def guardar_items(self, items, mensaje="Carga de convocatorias"):
        def op(con):
            con.executemany("INSERT OR REPLACE INTO convocatorias VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [self._fila(i) for i in items])
        self._escribir(op, mensaje)

    # -- base publicada ----------------------------------------------------------
    def base(self):
        return [i["datos"] | {"_id": i["id"]} for i in self.items("Aprobada")]

    def enviar_a_base(self, datos):
        """En la base propia, aprobar = cambiar el estado; no hay que copiar a otra tabla."""
        return "propia"

    # -- actores ---------------------------------------------------------------
    def catalogo(self):
        filas = self._leer("SELECT * FROM actores")
        return Catalogo.desde_filas(filas)

    def guardar_actor(self, actor, nombre_anterior=None):
        """Guarda un actor y mantiene coherentes sus convocatorias (nombre y carácter)."""
        anterior = nombre_anterior or actor.nombre

        def op(con):
            con.execute("DELETE FROM actores WHERE nombre IN (?, ?)", (anterior, actor.nombre))
            f = actor.a_fila()
            con.execute("INSERT INTO actores VALUES (?,?,?,?,?,?,?)",
                        (f["nombre"], f["tipo"], f["estado_ciclope"], f["alias"], f["pais"], f["web"], f["observaciones"]))
            caracter = caracter_de(actor.tipo)
            for r in con.execute("SELECT id, datos FROM convocatorias WHERE actor IN (?, ?)", (anterior, actor.nombre)).fetchall():
                d = json.loads(r["datos"])
                d["Nombre de la Fuente"] = actor.nombre
                d["Nombre de actor en CICLOPE"] = actor.nombre
                if caracter:
                    d["Oficial / No Oficial"] = caracter
                con.execute("UPDATE convocatorias SET datos=?, actor=?, actualizado=? WHERE id=?",
                            (json.dumps(d, ensure_ascii=False), actor.nombre, ahora(), r["id"]))
        self._escribir(op, f"Actor: {actor.nombre}")

    def reemplazar_catalogo(self, catalogo):
        def op(con):
            con.execute("DELETE FROM actores")
            con.executemany("INSERT INTO actores VALUES (?,?,?,?,?,?,?)",
                            [(f["nombre"], f["tipo"], f["estado_ciclope"], f["alias"], f["pais"], f["web"], f["observaciones"])
                             for f in catalogo.filas()])
        self._escribir(op, "Catálogo de actores")

    # -- usuarios (cuentas) ------------------------------------------------------
    def _leer_cuentas(self, con):
        fila = con.execute("SELECT valor FROM privado WHERE clave='cuentas'").fetchone()
        if not fila or not fila[0]:
            return {}
        valor = fila[0]
        if valor.startswith("fernet:"):
            if not self.fernet:
                raise ErrorCuentas("Las cuentas están cifradas: falta el secreto USUARIOS_CLAVE.")
            from cryptography.fernet import InvalidToken
            try:
                return json.loads(self.fernet.decrypt(valor[7:].encode()).decode())
            except InvalidToken as e:
                raise ErrorCuentas("USUARIOS_CLAVE no coincide con la que cifró las cuentas.") from e
        return json.loads(valor[5:])

    def _escribir_cuentas(self, con, cuentas):
        texto = json.dumps(cuentas, ensure_ascii=False)
        valor = "fernet:" + self.fernet.encrypt(texto.encode()).decode() if self.fernet else "json:" + texto
        con.execute("INSERT OR REPLACE INTO privado VALUES ('cuentas', ?)", (valor,))

    def _migrar_usuarios_antiguos(self):
        """Pasa la tabla 'usuarios' de versiones anteriores a las cuentas (cifradas si hay clave) y la borra del archivo."""
        con = self._abrir()
        try:
            hay = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
            sin_cifrar = con.execute("SELECT valor FROM privado WHERE clave='cuentas' AND valor LIKE 'json:%'").fetchone()
            if not hay and not (sin_cifrar and self.fernet):
                return
            cuentas = self._leer_cuentas(con)
            if hay:
                for f in con.execute("SELECT * FROM usuarios").fetchall():
                    cuentas.setdefault(f["usuario"], {"usuario": f["usuario"], "nombre": f["nombre"], "rol": f["rol"],
                                                      "sal": f["sal"], "hash": f["hash"], "iter": 200_000,
                                                      "activo": f["activo"], "debe_cambiar": True, "fallidos": 0,
                                                      "bloqueado_hasta": 0, "codigos": []})
                con.execute("DROP TABLE usuarios")
            self._escribir_cuentas(con, cuentas)
            con.commit()
            con.execute("VACUUM")
        finally:
            con.close()
        if self.sync:
            self.sync.subir(self.ruta, "Cuentas de usuario protegidas")

    def cuentas(self):
        """{usuario: cuenta} con todas las cuentas (incluye datos de seguridad: no mostrar)."""
        self._refrescar()
        con = self._abrir()
        try:
            return self._leer_cuentas(con)
        finally:
            con.close()

    def usuarios(self):
        return {u: c for u, c in self.cuentas().items() if c.get("activo", 1)}

    def todos_los_usuarios(self):
        return [{"usuario": c["usuario"], "nombre": c["nombre"], "rol": c["rol"], "activo": c.get("activo", 1),
                 "debe_cambiar": c.get("debe_cambiar", False),
                 "bloqueado": c.get("bloqueado_hasta", 0) > time.time(),
                 "codigos": sum(1 for x in c.get("codigos", []) if not x.get("usado"))}
                for c in sorted(self.cuentas().values(), key=lambda c: c["usuario"])]

    def guardar_cuenta(self, cuenta):
        def op(con):
            cuentas = self._leer_cuentas(con)
            cuentas[cuenta["usuario"]] = cuenta
            self._escribir_cuentas(con, cuentas)
        self._escribir(op, "Cuentas de usuario actualizadas")

    def activar_usuario(self, usuario, activo):
        def op(con):
            cuentas = self._leer_cuentas(con)
            if usuario in cuentas:
                cuentas[usuario]["activo"] = 1 if activo else 0
                self._escribir_cuentas(con, cuentas)
        self._escribir(op, "Cuentas de usuario actualizadas")

    # -- archivos de trabajo (configuración e historial del mapeo) --------------
    def leer_archivo(self, nombre):
        filas = self._leer("SELECT contenido FROM archivos WHERE nombre=?", (nombre,))
        return filas[0]["contenido"] if filas else None

    def guardar_archivo(self, nombre, contenido):
        def op(con):
            con.execute("INSERT OR REPLACE INTO archivos VALUES (?,?,?)", (nombre, contenido, ahora()))
        self._escribir(op, f"Archivo: {nombre}")

    def respaldo(self):
        """Bytes del archivo de la base, para descargar una copia."""
        self._refrescar()
        return self.ruta.read_bytes()


CLAVES = ("BASE_DATOS", "GITHUB_DATA_REPO", "GITHUB_TOKEN", "GITHUB_DATA_BRANCH", "HF_DATASET_REPO", "HF_TOKEN",
          "USUARIOS_CLAVE", "CLAVE_INSTALACION", "GEMINI_API_KEY", "GEMINI_MODEL")


def exportar_secretos(secrets):
    """Pasa los secretos de Streamlit a variables de entorno (las usan el mapeo y la sincronización)."""
    for k in CLAVES:
        if k in (secrets or {}) and k not in os.environ:
            os.environ[k] = str(secrets[k])


def sincronizador_configurado():
    """'GitHub', 'Hugging Face' o '' según los secretos."""
    return "GitHub" if os.environ.get("GITHUB_DATA_REPO") else "Hugging Face" if os.environ.get("HF_DATASET_REPO") else ""


def crear_sincronizador():
    if os.environ.get("GITHUB_DATA_REPO"):
        return SincronizadorGitHub(os.environ["GITHUB_DATA_REPO"], os.environ.get("GITHUB_TOKEN", ""),
                                   rama=os.environ.get("GITHUB_DATA_BRANCH") or "main")
    if os.environ.get("HF_DATASET_REPO"):
        return SincronizadorHF(os.environ["HF_DATASET_REPO"], os.environ.get("HF_TOKEN"))
    return None


def abrir(secrets=None):
    """Abre la base según las variables de entorno (o los secrets de Streamlit).

    GITHUB_DATA_REPO + GITHUB_TOKEN: la base vive en un repositorio privado de GitHub.
    HF_DATASET_REPO + HF_TOKEN: la base vive en un repositorio privado de datos de Hugging Face.
    Sin ninguno: la base queda solo en el archivo local (datos/convocatorias.db)."""
    exportar_secretos(dict(secrets or {}))
    semilla = None if os.environ.get("SIN_BASE_INICIAL") else BASE_INICIAL
    return AlmacenSQLite(sincronizador=crear_sincronizador(), base_inicial=semilla)


__all__ = ["AlmacenSQLite", "SincronizadorHF", "SincronizadorGitHub", "crear_sincronizador", "sincronizador_configurado", "abrir", "nuevo_item", "ahora", "ESTADOS", "Actor", "limpiar_nombre"]
