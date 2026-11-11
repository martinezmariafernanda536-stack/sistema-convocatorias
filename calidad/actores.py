"""Catálogo de actores: una sola fuente de verdad para el nombre, el tipo y el carácter.

El carácter Oficial / No Oficial ya no se elige por convocatoria: sale del tipo de actor.
  Oficial    = Gobierno / agencia bilateral, Organismo multilateral
  No Oficial = Fundación / filantropía, ONG / sociedad civil, Academia / investigación, Empresa privada
"""
import re
from dataclasses import asdict, dataclass, field

from analitica.datos import TIPOS, norm, tipo_por_reglas

TIPOS_OFICIALES = {"Gobierno / agencia bilateral", "Organismo multilateral"}
ESTADOS = ["Creado en CICLOPE", "Pendiente de crear", "Por confirmar"]

_SUFIJOS = re.compile(r"\((?:[^)]*(?:cread|creaci|c[ií]clope|solicit)[^)]*)\)?$|\((?:[^)]*(?:cread|creaci|c[ií]clope|solicit)[^)]*)\)"
                      r"|/\s*creado\b|\bno est[aá] creado\b", re.I)
_PENDIENTE = re.compile(r"no (est[aá] )?(creado|en c[ií]clope)|en proceso|en creaci[oó]n|se solicit[oó]", re.I)


def caracter_de(tipo):
    if tipo in TIPOS_OFICIALES:
        return "Oficial"
    if tipo in TIPOS and tipo != "Por clasificar":
        return "No Oficial"
    return ""


def limpiar_nombre(t):
    t = str(t or "").replace("​", "").replace("\t", " ").strip().strip('"')
    t = _SUFIJOS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" /-.)")
    if t.count("(") > t.count(")"):
        t += ")"
    return t


def sitio_oficial(url):
    """De un enlace a la página principal del sitio (https://dominio), si puede ser del oferente.

    Acortadores, agregadores, formularios e ICETEX no sirven como sitio del actor."""
    from calidad import dominios as DOM
    u = str(url or "").split(";")[0].strip()
    if not u.lower().startswith("http") and "." not in u:
        return ""
    cat, _ = DOM.clasificar(u)
    if cat in ("ICETEX", "Acortador", "Agregador / intermediario", "Plataforma de postulación", "Sin enlace"):
        return ""
    return "https://" + DOM.host(u)


def clave(t):
    return norm(limpiar_nombre(t)).strip()


@dataclass
class Actor:
    nombre: str                      # nombre exacto como está (o quedará) en CICLOPE
    tipo: str = "Por clasificar"
    estado_ciclope: str = "Por confirmar"
    pais: str = ""
    web: str = ""
    alias: list = field(default_factory=list)
    observaciones: str = ""

    @property
    def caracter(self):
        return caracter_de(self.tipo)

    def a_fila(self):
        d = asdict(self)
        d["alias"] = "; ".join(self.alias)
        d["caracter"] = self.caracter
        return d


class Catalogo:
    def __init__(self, actores=None):
        self.actores = {}
        self._indice = {}
        for a in actores or []:
            self.agregar(a)

    def agregar(self, actor):
        self.actores[actor.nombre] = actor
        for n in [actor.nombre] + list(actor.alias):
            if n:
                self._indice[clave(n)] = actor.nombre

    def buscar(self, nombre):
        """Coincidencia exacta por nombre o alias (sin tildes ni mayúsculas)."""
        k = self._indice.get(clave(nombre))
        return self.actores.get(k) if k else None

    def sugerencias(self, nombre, n=5):
        from calidad.reglas import similitud
        puntajes = sorted(((similitud(nombre, a.nombre), a.nombre) for a in self.actores.values()), reverse=True)
        return [x for s, x in puntajes[:n] if s >= 60]

    def __len__(self):
        return len(self.actores)

    def filas(self):
        return [a.a_fila() for a in sorted(self.actores.values(), key=lambda x: x.nombre.lower())]

    @classmethod
    def desde_filas(cls, filas):
        actores = []
        for f in filas:
            alias = [x.strip() for x in str(f.get("alias") or "").split(";") if x.strip()]
            actores.append(Actor(nombre=str(f["nombre"]).strip(), tipo=f.get("tipo") or "Por clasificar",
                                 estado_ciclope=f.get("estado_ciclope") or "Por confirmar", pais=f.get("pais") or "",
                                 web=f.get("web") or "", alias=alias, observaciones=f.get("observaciones") or ""))
        return cls(actores)


def construir_desde_base(df_crudo, tipos_corregidos=None):
    """Arma el catálogo inicial a partir de la base de convocatorias.

    - Nombre: el de CICLOPE si existe; si no, el de la fuente.
    - Alias: las otras formas en que aparece el actor.
    - Estado: 'Creado en CICLOPE' si el nombre de CICLOPE no indica que está pendiente.
    """
    tipos_corregidos = tipos_corregidos or {}
    grupos = {}
    for _, f in df_crudo.iterrows():
        fuente = limpiar_nombre(f.get("Nombre de la Fuente"))
        bruto_ciclope = str(f.get("Nombre de actor en CICLOPE") or "")
        ciclope = limpiar_nombre(bruto_ciclope)
        if fuente.upper().startswith("*NUEVO") or fuente.lower() in ("nan", "interno"):
            fuente = ""
        if ciclope.lower() in ("nan", ""):
            ciclope = ""
        nombre = ciclope or fuente
        if not nombre:
            continue
        k = clave(fuente) if fuente else clave(nombre)
        g = grupos.setdefault(k, {"nombres": {}, "pendiente": False, "creado": False, "web": set()})
        g["nombres"][nombre] = g["nombres"].get(nombre, 0) + 1
        if fuente:
            g["nombres"].setdefault(fuente, 0)
        if _PENDIENTE.search(bruto_ciclope):
            g["pendiente"] = True
        elif ciclope:
            g["creado"] = True
        link = sitio_oficial(f.get("Link de la Fuente Oferente"))
        if link:
            g["web"].add(link)
    catalogo = Catalogo()
    for g in grupos.values():
        nombre = max(g["nombres"], key=lambda n: (g["nombres"][n], len(n)))
        alias = [n for n in g["nombres"] if n != nombre]
        tipo = tipos_corregidos.get(nombre) or next((tipos_corregidos[a] for a in alias if a in tipos_corregidos), None)
        tipo = tipo or tipo_por_reglas(nombre)[0]
        if tipo == "Por clasificar":
            for a in alias:
                t2 = tipo_por_reglas(a)[0]
                if t2 != "Por clasificar":
                    tipo = t2
                    break
        estado = "Creado en CICLOPE" if g["creado"] else "Pendiente de crear" if g["pendiente"] else "Por confirmar"
        existente = catalogo.buscar(nombre)
        if existente:
            existente.alias = sorted(set(existente.alias + alias + [nombre]) - {existente.nombre})
            catalogo.agregar(existente)
            continue
        catalogo.agregar(Actor(nombre=nombre, tipo=tipo, estado_ciclope=estado, web=sorted(g["web"])[0] if g["web"] else "",
                               alias=alias))
    return catalogo
