"""Memoria entre corridas: qué se vio antes, para saber qué es nuevo, qué cambió y qué desapareció."""
import hashlib
import json
from pathlib import Path


class Historial:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.datos = json.loads(self.ruta.read_text(encoding="utf-8")) if self.ruta.exists() else {}
        self.completas = self.datos.pop("_revision_completa", {})  # fuente -> fecha de la última revisión completa
        self.seguidas = self.datos.pop("_seguimiento_ediciones", {})  # url de la base -> fecha en que se revisó su edición
        self.vistas_hoy = set()

    def conocidas(self):
        return set(self.datos)

    def marcar_visto(self, url, fuente_id, hoy):
        """La convocatoria sigue publicada (modo rápido: no se volvió a abrir porque ya se conocía)."""
        self.vistas_hoy.add(url)
        d = self.datos.setdefault(url, {"fuente": fuente_id, "primera_vez": hoy, "titulo": ""})
        d["ultima_vez"] = hoy

    def dias_desde_completa(self, fuente_id, hoy):
        from datetime import date
        f = self.completas.get(fuente_id)
        if not f:
            return None
        return (date.fromisoformat(hoy) - date.fromisoformat(f)).days

    def marcar_completa(self, fuente_id, hoy):
        self.completas[fuente_id] = hoy

    def dias_desde_seguimiento(self, url, hoy):
        from datetime import date
        f = self.seguidas.get(url)
        return None if not f else (date.fromisoformat(hoy) - date.fromisoformat(f)).days

    def marcar_seguida(self, url, hoy):
        self.seguidas[url] = hoy

    @staticmethod
    def huella(fila):
        clave = "|".join(str(fila.get(k, "")) for k in ("Nombre de la Convocatoria", "Fecha Límite de Aplicación",
                                                         "Observaciones sobre el financiamiento", "[Sistema] Elegibilidad Colombia"))
        return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]

    def estado(self, url, fila):
        """Como registrar, pero sin anotar nada: 'Nueva', 'Actualizada' o 'Sin cambios'."""
        previo = self.datos.get(url)
        if previo is None:
            return "Nueva"
        return "Sin cambios" if previo.get("huella") == self.huella(fila) else "Actualizada"

    def olvidar(self, urls):
        """Para que el mapeo vuelva a encontrarlas como nuevas."""
        for u in urls:
            self.datos.pop(u, None)

    def registrar(self, url, fuente_id, fila, hoy):
        """Devuelve 'Nueva', 'Actualizada' o 'Sin cambios'."""
        self.vistas_hoy.add(url)
        h = self.huella(fila)
        previo = self.datos.get(url)
        if previo is None:
            estado = "Nueva"
            self.datos[url] = {"fuente": fuente_id, "primera_vez": hoy, "titulo": fila["Nombre de la Convocatoria"]}
        else:
            estado = "Sin cambios" if previo.get("huella") == h else "Actualizada"
        self.datos[url].update({"huella": h, "ultima_vez": hoy, "titulo": fila["Nombre de la Convocatoria"]})
        return estado

    def retiradas(self, fuentes_leidas):
        """Becas que antes aparecían en fuentes leídas hoy y ya no aparecen."""
        return [(u, d["fuente"], d.get("titulo", ""), d.get("ultima_vez", ""))
                for u, d in self.datos.items() if d.get("fuente") in fuentes_leidas and u not in self.vistas_hoy]

    def guardar(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.datos | {"_revision_completa": self.completas,
                                                     "_seguimiento_ediciones": self.seguidas}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
