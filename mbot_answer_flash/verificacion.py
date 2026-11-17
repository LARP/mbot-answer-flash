"""Verificacion posterior a la ejecucion ("sin verificar no cuenta como hecho").

  start app      -> `tasklist /fi "imagename eq X"` (sondeo corto, max `timeout` s, en un hilo si se pide) + codigo de retorno
  archivos       -> os.path.exists antes/despues (del, rmdir, mkdir, copy, move, ren)
  con salida     -> codigo de retorno
Resultado: ("ok" | "parcial" | "fallo" | "desconocido", detalle).  Todo lo que toca el sistema es inyectable.
"""
import os, re, subprocess, threading, time

ALIAS_IMAGEN = {            # `start X` no siempre lanza X.exe (apps de la tienda, shims)
    "calc": ["calc.exe", "calculatorapp.exe", "calculator.exe"],
    "notepad": ["notepad.exe"],
    "mspaint": ["mspaint.exe", "paintapp.exe"],
    "wmplayer": ["wmplayer.exe"],
    "taskmgr": ["taskmgr.exe"],
}
SIN_PROCESO_PROPIO = {"explorer", "control", "cmd"}      # abren ventanas de un proceso que ya existe: no se puede ver
VERBOS_ARCHIVO = {"del": "no_existe", "erase": "no_existe", "rd": "no_existe", "rmdir": "no_existe",
                  "mkdir": "existe", "md": "existe", "copy": "existe", "xcopy": "existe", "move": "existe",
                  "ren": "existe", "rename": "existe"}
RE_IMG = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def partir_args(cmd):
    """cmd -> [(valor, crudo), ...] respetando comillas dobles. El primero es el verbo."""
    out = []
    for m in re.finditer(r'"([^"]*)"|(\S+)', cmd):
        out.append((m.group(1) if m.group(1) is not None else m.group(2), m.group(0)))
    return out


def verbo_de(cmd):
    a = partir_args(cmd)
    if not a:
        return ""
    v = a[0][0].lower()
    return v[:-4] if v.endswith(".exe") else v


def _rutas_args(cmd):
    """Argumentos que son rutas (sin las opciones /x ni -x)."""
    return [v for v, _c in partir_args(cmd)[1:] if v and not (v[0] == "/" and len(v) <= 4) and not v.startswith("-")]


def imagenes_de_start(cmd, apps=()):
    """Nombres de imagen (proceso) que `start ...` deberia dejar en marcha; [] si no se puede saber."""
    a = partir_args(cmd)
    if len(a) < 2 or a[0][0].lower() != "start":
        return []
    for nom, c, exe, _s in apps:                           # accesos .lnk / App Paths conocidos
        if c == cmd and exe:
            return [exe.lower()]
    args = [v for v, _c in a[1:] if v != ""]
    if not args:
        return []
    obj = args[0]
    if re.match(r"^[a-z][a-z0-9+.-]*:(//|$)", obj, re.I) or obj.endswith(":") or obj.lower().startswith(("ms-", "http")):
        return []                                          # url o esquema (ms-settings:)
    base = os.path.basename(obj.replace("/", "\\").rstrip("\\")).lower()
    if not base:
        return []
    stem = base[:-4] if base.endswith(".exe") else base
    if stem in SIN_PROCESO_PROPIO:
        return []
    if stem in ALIAS_IMAGEN:
        return ALIAS_IMAGEN[stem]
    if base.endswith(".exe"):
        return [base]
    if "." not in base and "\\" not in obj and "/" not in obj:
        return [base + ".exe"]
    return []                                              # carpetas, .lnk desconocidos, documentos


def _tasklist(img):
    if not RE_IMG.match(img):
        return False
    try:
        r = subprocess.run(["tasklist", "/fi", f"imagename eq {img}", "/nh"], capture_output=True, timeout=2,
                           text=True, errors="replace")
        return img.lower() in r.stdout.lower()
    except Exception:
        return False


class Verificador:
    def __init__(self, tasklist=None, existe=None, dormir=None, reloj=None, timeout=3.0, paso=0.5):
        self.tasklist = tasklist or _tasklist
        self.existe = existe or os.path.exists
        self.dormir = dormir or time.sleep
        self.reloj = reloj or time.monotonic
        self.timeout, self.paso = timeout, paso

    # ---- antes de ejecutar: que se espera y como estaba el mundo
    def preparar(self, cmd, apps=()):
        v = verbo_de(cmd)
        if v == "start":
            return {"tipo": "start", "imagenes": imagenes_de_start(cmd, apps)}
        esp = VERBOS_ARCHIVO.get(v)
        if esp:
            rutas = _rutas_args(cmd)
            if rutas:
                if v in ("ren", "rename") and len(rutas) >= 2:
                    ruta = os.path.join(os.path.dirname(os.path.abspath(rutas[0])), rutas[1])
                elif v in ("copy", "xcopy", "move") and len(rutas) >= 2:
                    ruta = rutas[-1]
                else:
                    ruta = rutas[0]
                if not re.search(r"[*?]", ruta):
                    ruta = os.path.abspath(ruta)
                    return {"tipo": "archivo", "ruta": ruta, "esperado": esp, "antes": bool(self.existe(ruta))}
        return {"tipo": "salida"}

    # ---- despues de ejecutar
    def _rc(self, res):
        rc = getattr(res, "rc", None)
        proc = getattr(res, "proc", None)
        if rc is None and proc is not None:
            try:
                rc = proc.wait(timeout=1.0)
            except Exception:
                rc = None
        return rc

    def verificar(self, spec, res, *_):
        rc = self._rc(res)
        t = spec.get("tipo")
        if t == "start":
            if rc not in (None, 0):
                return "fallo", f"el comando devolvio {rc}"
            imgs = spec.get("imagenes") or []
            if not imgs:
                return "desconocido", "no se puede comprobar que proceso lanza"
            t0 = self.reloj()
            while True:
                if any(self.tasklist(i) for i in imgs):
                    return "ok", f"proceso {imgs[0]} en ejecucion"
                if self.reloj() - t0 >= self.timeout:
                    break
                self.dormir(self.paso)
            return "parcial", f"se lanzo (codigo {rc if rc is not None else '?'}) pero no se ve {imgs[0]} tras {self.timeout:g} s"
        if t == "archivo":
            ahora = bool(self.existe(spec["ruta"]))
            cumple = ahora == (spec["esperado"] == "existe")
            if rc not in (None, 0) and not cumple:
                return "fallo", f"el comando devolvio {rc}"
            if not cumple:
                return "fallo", ("la ruta sigue existiendo" if ahora else "la ruta no existe") + f": {spec['ruta']}"
            if spec["antes"] == ahora:
                return "parcial", "no hubo cambio (ya estaba asi)"
            return "ok", "cambio comprobado"
        if rc is None:
            return "desconocido", "sin codigo de retorno"
        return ("ok", "codigo 0") if rc == 0 else ("fallo", f"codigo de retorno {rc}")

    def verificar_async(self, spec, res, callback):
        """Verifica en un hilo (daemon) para no bloquear la respuesta; callback(estado, detalle)."""
        def run():
            try:
                est, det = self.verificar(spec, res)
            except Exception as e:                  # una verificacion rota nunca penaliza
                est, det = "desconocido", f"{type(e).__name__}: {e}"
            callback(est, det)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        return th
