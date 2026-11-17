"""Estados de ejecucion (ejecuciones.json) y detector de bucles.

Cada ejecucion o plan queda registrado como {id, frase, ts, pasos[{cmd, estado, ms}], estado}.
estado de la entrada: running | done | partial | failed | interrupted.
estado de un paso: running | ok | parcial | fallo | desconocido | rechazado | cancelado.
Al arrancar, lo que quedo en `running` pasa a `interrupted` y NO se reintenta (ningun metodo lo vuelve a lanzar).
"""
import json, os, time

from .memoria import guardar_json

MAX_ENTRADAS = 200
MAL = {"fallo", "rechazado"}


def estado_de(pasos):
    """Estado agregado de una entrada ya cerrada a partir de sus pasos."""
    est = [p["estado"] for p in pasos]
    if not est:
        return "done"
    malos = sum(e in MAL for e in est)
    if malos == len(est):
        return "failed"
    if malos or any(e in ("parcial", "cancelado") for e in est):
        return "partial"
    return "done"


class Registro:
    def __init__(self, ruta, reloj=time.time, maximo=MAX_ENTRADAS):
        self.ruta, self.reloj, self.maximo = ruta, reloj, maximo
        self.entradas, self.ultimo = [], 0
        try:
            with open(ruta, encoding="utf-8") as f:
                d = json.load(f)
            self.entradas = [e for e in d.get("entradas", []) if isinstance(e, dict) and "id" in e]
            self.ultimo = max([d.get("ultimo", 0)] + [e["id"] for e in self.entradas])
        except (OSError, ValueError, AttributeError):
            pass
        cambio = False
        for e in self.entradas:                     # lo que se quedo ejecutando cuando se cerro el programa: interrumpido
            if e.get("estado") == "running":
                e["estado"] = "interrupted"
                cambio = True
                for p in e.get("pasos", []):
                    if p.get("estado") == "running":
                        p["estado"] = "desconocido"
        if cambio:
            self.guardar()

    def guardar(self):
        try:
            guardar_json(self.ruta, {"v": 1, "ultimo": self.ultimo, "entradas": self.entradas})
        except OSError:
            pass

    def _get(self, id_):
        for e in reversed(self.entradas):
            if e["id"] == id_:
                return e
        return None

    def iniciar(self, frase):
        self.ultimo += 1
        self.entradas.append({"id": self.ultimo, "frase": frase, "ts": self.reloj(), "pasos": [], "estado": "running"})
        if len(self.entradas) > self.maximo:
            del self.entradas[:len(self.entradas) - self.maximo]
        self.guardar()
        return self.ultimo

    def paso(self, id_, cmd, estado, ms=0.0):
        """Anade un paso; devuelve su indice."""
        e = self._get(id_)
        if e is None:
            return -1
        e["pasos"].append({"cmd": cmd, "estado": estado, "ms": round(ms, 1)})
        self.guardar()
        return len(e["pasos"]) - 1

    def actualizar_paso(self, id_, k, estado):
        """El resultado de una verificacion llega despues: corrige el paso y, si la entrada ya estaba cerrada, su estado."""
        e = self._get(id_)
        if e is None or not (0 <= k < len(e["pasos"])):
            return
        e["pasos"][k]["estado"] = estado
        if e["estado"] != "running":
            e["estado"] = estado_de(e["pasos"])
        self.guardar()

    def cerrar(self, id_):
        e = self._get(id_)
        if e is not None and e["estado"] == "running":
            e["estado"] = estado_de(e["pasos"])
            self.guardar()
        return e["estado"] if e else None

    def pendientes(self):
        return [e for e in self.entradas if e["estado"] == "running"]

    def ultimas(self, n=10):
        return list(reversed(self.entradas[-n:]))

    def texto_historial(self, n=10):
        if not self.entradas:
            return "  Todavia no hay ejecuciones registradas."
        L = []
        for e in self.ultimas(n):
            L.append(f"  [{e['id']}] {e['estado']:<11} '{e['frase']}'")
            for p in e["pasos"]:
                L.append(f"       - {p['cmd']}  ({p['estado']}, {p['ms']:.0f} ms)")
        return "\n".join(L)


class DetectorBucles:
    """La misma accion con los mismos argumentos que falla `limite` veces seguidas se bloquea `ttl` segundos."""

    def __init__(self, reloj=time.time, limite=3, ttl=60.0):
        self.reloj, self.limite, self.ttl = reloj, limite, ttl
        self.fallos, self.hasta = {}, {}

    @staticmethod
    def clave(cmd):
        return " ".join(cmd.lower().split())

    def registrar(self, cmd, ok):
        """True si este fallo acaba de bloquear la accion."""
        k = self.clave(cmd)
        if ok:
            self.fallos.pop(k, None)
            return False
        self.fallos[k] = self.fallos.get(k, 0) + 1
        if self.fallos[k] >= self.limite:
            self.hasta[k] = self.reloj() + self.ttl
            self.fallos[k] = 0
            return True
        return False

    def bloqueado(self, cmd):
        """Segundos que faltan para que la accion se desbloquee (0 si no esta bloqueada)."""
        k = self.clave(cmd)
        h = self.hasta.get(k)
        if h is None:
            return 0.0
        r = h - self.reloj()
        if r <= 0:
            del self.hasta[k]
            return 0.0
        return r
