"""Memoria v2 (tareas + red): carga, guardado, aprendizaje, induccion y penalizacion (capas A/G)."""
import json, os, time

from .config import MAX_FRASES, MEM_PATH, MEM_V1, PELIGROSO
from .lexico import GENERICAS
from .red import Red
from .refuerzo import decaer
from .texto import MARK, tokens


SEMILLA = [
    {"cmd": "start notepad",  "frases": ["abrir bloc de notas"], "marco": [["ESCRIBIR", "TEXTO"]]},
    {"cmd": "start calc",     "frases": ["abrir calculadora"], "marco": [["CALCULAR", None]]},
    {"cmd": "start explorer", "frases": ["abrir explorador de archivos"]},
    {"cmd": "ipconfig",       "frases": ["ver mi ip", "ver configuracion de red"], "marco": [["RED", None]]},
    {"cmd": "start taskmgr",  "frases": ["abrir administrador de tareas"], "marco": [["VER", "PROCESO"]]},
    # extras v2 (literales)
    {"cmd": "hostname",       "frases": ["ver nombre del equipo"]},
    {"cmd": "systeminfo",     "frases": ["ver informacion del sistema"]},
    {"cmd": "whoami",         "frases": ["quien soy"]},
    {"cmd": "cls",            "frases": ["limpiar consola"], "marco": [["LIMPIAR", "PANTALLA"], ["BORRAR", "PANTALLA"]]},
    {"cmd": "start control",  "frases": ["abrir panel de control"]},
    # semantica (S): tareas con marco
    {"cmd": "start wmplayer", "frases": ["reproducir musica"], "marco": [["REPRODUCIR", "MUSICA"], ["REPRODUCIR", "VIDEO"]]},
    {"cmd": 'del "{ruta}"',   "frases": ["borrar archivo {ruta}"], "marco": [["BORRAR", "ARCHIVO"]]},
    {"cmd": 'rmdir /s "{ruta}"', "frases": ["borrar carpeta {ruta}"], "marco": [["BORRAR", "CARPETA"]]},
    {"cmd": "shutdown /s /t 0", "frases": ["apagar el equipo"], "marco": [["APAGAR", "EQUIPO"]]},
    {"cmd": "shutdown /r /t 0", "frases": ["reiniciar el equipo"], "marco": [["REINICIAR", "EQUIPO"]]},
    {"cmd": "rundll32.exe user32.dll,LockWorkStation", "frases": ["bloquear el equipo"],
     "marco": [["BLOQUEAR", "EQUIPO"], ["BLOQUEAR", "PANTALLA"]]},
    {"cmd": "start https://www.google.com", "frases": ["abrir el navegador"], "marco": [["NAVEGAR", None]]},
    {"cmd": "start ms-settings:", "frases": ["abrir configuracion"], "marco": [["CONFIGURAR", None]]},
    {"cmd": "start mspaint",  "frases": ["abrir paint"], "marco": [["DIBUJAR", None]]},
    {"cmd": 'start "" "%USERPROFILE%\\Pictures"', "frases": ["ver mis fotos"], "marco": [["VER", "IMAGEN"]]},
    # plantillas con hueco
    {"cmd": "{app_start}",                "frases": ["abrir {app}"]},
    {"cmd": "taskkill /im {app}.exe",     "frases": ["cerrar {app}"], "marco": [["CERRAR", "PROCESO"]]},
    {"cmd": 'start "" "{carpeta}"',       "frases": ["abrir carpeta {carpeta}", "abrir {carpeta}"], "marco": [["ABRIR", "CARPETA"]]},
    {"cmd": 'dir "{carpeta}"',            "frases": ["ver contenido carpeta {carpeta}", "ver contenido de {carpeta}"]},
    {"cmd": 'start "" "{ruta}"',          "frases": ["abrir archivo {ruta}", "abrir {ruta}", "abrir carpeta {ruta}"],
     "marco": [["ABRIR", "ARCHIVO"]]},
    {"cmd": 'start "" "{url}"',           "frases": ["abrir {url}", "abrir pagina {url}"]},
    {"cmd": 'start "" "https://{host}"',  "frases": ["abrir {host}", "abrir pagina {host}"]},
    {"cmd": "ping {host}",                "frases": ["hacer ping {host}", "ping {host}"]},
    {"cmd": "tracert {host}",             "frases": ["trazar ruta {host}", "tracert {host}"]},
    {"cmd": 'start "" "https://www.google.com/search?q={texto_url}"',
     "frases": ["buscar {texto} en google", "buscar en google {texto}", "buscar {texto}"]},
    {"cmd": 'mkdir "{texto}"',            "frases": ["crear carpeta {texto}"]},
    {"cmd": 'type "{ruta}"',              "frases": ["ver contenido archivo {ruta}"]},
    {"cmd": "timeout /t {n}",             "frases": ["esperar {n} segundos"]},
]


def guardar_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


class MemoriaMixin:
    def _cargar(self, ruta):
        datos = None
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        self.tareas, red = [], None
        if isinstance(datos, dict):
            self.tareas, red = datos.get("tareas", []), datos.get("red")
        else:
            base = [dict(cmd=t["cmd"], frases=list(t["frases"]), marco=[list(x) for x in t.get("marco", [])])
                    for t in SEMILLA]
            if ruta == MEM_PATH and os.path.exists(MEM_V1):         # migra la memoria v1 (solo lectura)
                try:
                    with open(MEM_V1, encoding="utf-8") as f:
                        v1 = json.load(f)
                    for t in v1:
                        for b in base:
                            if b["cmd"].lower() == t["cmd"].lower():
                                b["frases"] += [x for x in t["frases"] if x not in b["frases"]]
                                b["usos"] = t.get("usos", 0)
                                break
                        else:
                            base.append(dict(cmd=t["cmd"], frases=list(t["frases"]), usos=t.get("usos", 0)))
                except Exception:
                    pass
            self.tareas = base
        nuevas = []
        if isinstance(datos, dict) and datos.get("s", 0) < 1:      # memoria v2 anterior a la capa S: anade la semilla con marco
            for t in SEMILLA:
                if t.get("marco") and self._tarea(t["cmd"]) is None:
                    nt = dict(cmd=t["cmd"], frases=list(t["frases"]), marco=[list(x) for x in t["marco"]])
                    self.tareas.append(nt)
                    nuevas.append(nt)
        for t in self.tareas:
            t.setdefault("usos", 0); t.setdefault("a", 0.0); t.setdefault("f", 0.0)
            t.setdefault("ts", time.time()); t.setdefault("veto", {})
        self._cache_an.clear()
        semb = {t["cmd"].lower(): t.get("marco", []) for t in SEMILLA}
        for t in self.tareas:                                       # compat: tareas sin marco -> semilla o derivado de sus frases
            if "marco" not in t:
                t["marco"] = [list(x) for x in semb.get(t["cmd"].lower(), [])]
                for fr in t["frases"]:
                    mk = self._marco_aprendible(self.analizar(fr), t["cmd"])
                    if mk and mk not in t["marco"]:
                        t["marco"].append(mk)
        self.red = Red(red)
        if nuevas:
            ahora = time.time()
            for t in nuevas:
                t.setdefault("usos", 0)
                for fr in t["frases"]:
                    self._enlazar(fr, t["cmd"], ahora)
        if not isinstance(datos, dict) or nuevas:
            ahora = time.time()
            for t in ([] if isinstance(datos, dict) else self.tareas):                          # la semilla tambien siembra la red
                for fr in t["frases"]:
                    self._enlazar(fr, t["cmd"], ahora)
            self.guardar()

    def guardar(self):
        guardar_json(self.ruta, {"v": 2, "s": 1, "tareas": self.tareas, "red": self.red.datos()})

    def _enlazar(self, frase, cmd, ahora):
        an = self.analizar(frase)
        self.red.enlazar(an.stok if MARK.search(cmd) else an.lit, cmd, ahora)

    def _marco_aprendible(self, an, cmd):
        """(ACCION, OBJETO|None) que una frase ensena sobre su comando; None si es demasiado generica."""
        m = an.marco
        if m.prim is None or m.prim in GENERICAS:
            return None
        if m.obj is None and (MARK.search(cmd) or PELIGROSO.search(cmd)):
            return None
        return [m.prim, m.obj]

    def _tarea(self, cmd):
        for i, t in enumerate(self.tareas):
            if t["cmd"].lower() == cmd.lower():
                return i
        return None

    def aprender(self, frase, cmd, guardar=True):
        """Refuerza una tarea existente (misma orden) o crea una nueva; intenta generalizar con slots."""
        an = self.analizar(frase)
        cmd_t = self.templatizar(cmd, an.slots) if an.slots else cmd
        a_guardar, dest = frase, cmd
        if MARK.search(cmd):                                   # el usuario dio una plantilla explicita
            a_guardar = an.slot_text
        elif cmd_t != cmd and self._tarea(cmd_t) is not None:  # ya existe la plantilla correspondiente
            a_guardar, dest = an.slot_text, cmd_t
        norm_nuevo = " ".join(tokens(a_guardar))
        for t in self.tareas:                                  # una frase significa una cosa: corrige otras tareas
            if t["cmd"].lower() != dest.lower():
                t["frases"] = [x for x in t["frases"] if " ".join(tokens(x)) != norm_nuevo]
        self.tareas = [t for t in self.tareas if t["frases"] or t["cmd"].lower() == dest.lower()]
        i = self._tarea(dest)
        ahora = time.time()
        if i is None:
            self.tareas.append({"cmd": dest, "frases": [], "usos": 0, "a": 0.0, "f": 0.0, "ts": ahora, "veto": {}, "marco": []})
            i = len(self.tareas) - 1
        t = self.tareas[i]
        if norm_nuevo and norm_nuevo not in (" ".join(tokens(f)) for f in t["frases"]):
            t["frases"].append(a_guardar)
            t["frases"] = t["frases"][-MAX_FRASES:]
        t["usos"] += 1
        hh = t.setdefault("h", {})                              # refuerzo por hora del dia (para !hoy)
        k = str(self.personal.ahora().hour)
        hh[k] = hh.get(k, 0) + 1
        t["a"], t["f"] = decaer(t["a"], t["f"], t["ts"], ahora)
        t["a"] += 1; t["ts"] = ahora
        t["veto"].pop(norm_nuevo, None)
        mk = self._marco_aprendible(an, dest)
        if mk:                                                 # "quiero dibujar un gato" -> (DIBUJAR,*) -> mspaint
            for u in self.tareas:
                if u is not t and mk in u.get("marco", []):
                    u["marco"].remove(mk)
            t.setdefault("marco", [])
            if mk not in t["marco"]:
                t["marco"].append(mk)
                t["marco"] = t["marco"][-8:]
        self._enlazar(a_guardar, dest, ahora)
        self.red.premiar([w for w in tokens(a_guardar)], dest, True, ahora)
        self._inducir(frase, dest)
        self.red.podar(ahora, {x["cmd"] for x in self.tareas})
        if guardar:
            self.guardar()
        self._indexar()

    def _inducir(self, frase, cmd):
        """Dos frases que difieren solo en un slot + comandos que difieren en ese valor -> una plantilla."""
        an = self.analizar(frase)
        if not an.slots or MARK.search(cmd):
            return
        cmd_t = self.templatizar(cmd, an.slots)
        if cmd_t == cmd:
            return
        i = self._tarea(cmd)
        for u in list(self.tareas):
            if u["cmd"].lower() == cmd.lower() or MARK.search(u["cmd"]):
                continue
            for p in u["frases"]:
                an2 = self.analizar(p)
                if an2.slots and an2.norm_slot == an.norm_slot and self.templatizar(u["cmd"], an2.slots) == cmd_t:
                    t = self.tareas[self._tarea(cmd)]
                    g = self._tarea(cmd_t)
                    if g is None:
                        self.tareas.append({"cmd": cmd_t, "frases": [], "usos": 0, "a": 0.0, "f": 0.0,
                                            "ts": time.time(), "veto": {}, "marco": []})
                        g = len(self.tareas) - 1
                    gt = self.tareas[g]
                    if an.slot_text not in gt["frases"]:
                        gt["frases"].append(an.slot_text)
                    for orig, fr in ((t, frase), (u, p)):
                        orig["frases"] = [x for x in orig["frases"] if x != fr]
                        gt["usos"] += orig["usos"]; gt["a"] += orig["a"]; gt["f"] += orig["f"]
                        if not orig["frases"]:
                            self.red.renombrar(orig["cmd"], cmd_t)
                            self.tareas = [x for x in self.tareas if x is not orig]
                    self._enlazar(an.slot_text, cmd_t, time.time())
                    return True
        return False

    def olvidar(self, i):
        t = self.tareas.pop(i)
        self.red.borrar_cmd(t["cmd"])
        self.guardar()
        self._indexar()

    # ---- refuerzo (G)
    def penalizar_verificado(self, d):
        """Un fallo VERIFICADO (la app no arranco, el archivo no cambio...) resta: deshace el acierto contado al ejecutar y suma un fallo.
        No veta la frase ni toca la red (eso es el 'no' explicito del usuario). Busca la tarea por su comando, no por indice."""
        i = self._tarea(d.cmd_t) if getattr(d, "cmd_t", None) else None
        if i is None:
            return False
        t = self.tareas[i]
        ahora = time.time()
        t["a"], t["f"] = decaer(max(0, t["a"] - 1), t["f"], t["ts"], ahora)
        t["f"] += 1; t["ts"] = ahora
        self.guardar()
        return True

    def penalizar(self, d):
        """El usuario dijo 'no': penaliza asociaciones, veta la frase y quita la variante auto-aprendida."""
        if d.idx is None or d.idx >= len(self.tareas):
            return
        t = self.tareas[d.idx]
        ahora = time.time()
        t["a"], t["f"] = decaer(max(0, t["a"] - 1), t["f"], t["ts"], ahora)
        t["f"] += 1; t["ts"] = ahora
        for k in (d.an.norm_lit, d.an.norm_slot):
            if k:
                t["veto"][k] = t["veto"].get(k, 0) + 1
        resto = [x for x in t["frases"] if " ".join(tokens(x)) not in (d.an.norm_lit, d.an.norm_slot)]
        if resto:
            t["frases"] = resto
        self.red.premiar([w for w in (d.an.stok if self.tpl[d.idx] else d.an.lit)], t["cmd"], False, ahora)
        self.guardar()
        self._indexar()
