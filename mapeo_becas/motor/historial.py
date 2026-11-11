"""Memoria entre corridas: qué se vio antes, para saber qué es nuevo, qué cambió y qué desapareció."""
import hashlib
import json
from pathlib import Path


class Historial:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.datos = json.loads(self.ruta.read_text(encoding="utf-8")) if self.ruta.exists() else {}
        self.vistas_hoy = set()

    @staticmethod
    def huella(fila):
        clave = "|".join(str(fila.get(k, "")) for k in ("Nombre de la Convocatoria", "Fecha Límite de Aplicación",
                                                         "Observaciones sobre el financiamiento", "[Sistema] Elegibilidad Colombia"))
        return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]

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
        self.ruta.write_text(json.dumps(self.datos, ensure_ascii=False, indent=1), encoding="utf-8")
