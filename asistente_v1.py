"""
Asistente CMD con aprendizaje liviano (sin dependencias, solo Python estandar).

Como "razona":
  1. Normaliza la frase (minusculas, sin tildes, quita palabras vacias, unifica sinonimos).
  2. Compara contra la memoria con similitud ponderada (IDF) + tolerancia a errores de
     escritura (trigramas de caracteres).
  3. Segun la confianza: ejecuta, pregunta "¿te refieres a...?", o pide que le enseñes.
  4. Cada solicitud resuelta se guarda como variante de la tarea -> la proxima vez la reconoce mejor.

Comandos especiales:
  !lista                      ver lo aprendido
  !aprender frase => comando  enseñar directamente
  !olvidar N                  borrar la tarea N
  !salir
"""
import difflib, json, math, os, re, subprocess, sys, unicodedata

MEM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memoria.json")
MAX_FRASES = 15          # variantes guardadas por tarea (memoria acotada)
UMBRAL_EJECUTAR = 0.60   # confianza para ejecutar directo
UMBRAL_PREGUNTAR = 0.30  # confianza para preguntar "¿te refieres a...?"

STOP = set("""el la los las un una unos unas de del al a en y o u que por para con sin mi mis me te se
lo le les necesito quiero queria puedes podrias puede favor porfa ayudame dame hazme haz algo
como es esto eso este esta ese esa ahora rapido please tu su sus yo""".split())

# Sinonimos -> palabra canonica (aqui va el "conocimiento base" barato)
SIN = {}
for canon, variantes in {
    "abrir":   "abre abri abras abrir ejecuta ejecutar inicia iniciar lanza lanzar arranca arrancar corre correr pon",
    "cerrar":  "cierra cerrar mata matar termina terminar finaliza",
    "ver":     "muestra mostrar ver lista listar dime enseña ensena revisa revisar consulta",
    "notepad": "bloc notas notepad",
    "calc":    "calculadora calc calcular",
    "carpeta": "carpeta carpetas directorio explorador archivos",
    "red":     "red ip internet conexion wifi",
    "tareas":  "tareas procesos administrador",
}.items():
    for v in variantes.split():
        SIN[v] = canon
SIN_KEYS = list(SIN)

PELIGROSO = re.compile(r"\b(del|erase|rd|rmdir|format|shutdown|diskpart|bcdedit|cipher|takeown|icacls|reg\s+delete)\b", re.I)

SEMILLA = [
    {"cmd": "start notepad",  "frases": ["abrir bloc de notas"], "usos": 0},
    {"cmd": "start calc",     "frases": ["abrir calculadora"], "usos": 0},
    {"cmd": "start explorer", "frases": ["abrir explorador de archivos"], "usos": 0},
    {"cmd": "ipconfig",       "frases": ["ver mi ip", "ver configuracion de red"], "usos": 0},
    {"cmd": "start taskmgr",  "frases": ["abrir administrador de tareas"], "usos": 0},
]

# ---------------------------------------------------------------- texto
def tokens(texto):
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    out = []
    for w in re.findall(r"[a-z0-9]+", t):
        if w in STOP:
            continue
        if w not in SIN and w.endswith("me") and w[:-2] in SIN:   # muestrame -> muestra
            w = w[:-2]
        if w not in SIN and len(w) >= 4:                          # tolera typos: blok -> bloc
            cerca = difflib.get_close_matches(w, SIN_KEYS, n=1, cutoff=0.75)
            if cerca:
                w = cerca[0]
        w = SIN.get(w, w)
        if len(w) > 4 and w.endswith("s"):   # plural basico
            w = w[:-1]
        out.append(w)
    return out

def parecido(a, b):
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()

# ---------------------------------------------------------------- memoria
class Memoria:
    def __init__(self, ruta=MEM_PATH):
        self.ruta = ruta
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.tareas = json.load(f)
        else:
            self.tareas = [dict(t, frases=list(t["frases"])) for t in SEMILLA]
            self.guardar()
        self._indexar()

    def _indexar(self):
        # Precalcula tokens y frecuencia de documento (IDF) una vez: busqueda en microsegundos.
        self.tok = [[set(tokens(f)) for f in t["frases"]] for t in self.tareas]
        df = {}
        for frases in self.tok:
            for w in set().union(*frases) if frases else ():
                df[w] = df.get(w, 0) + 1
        n = max(len(self.tareas), 1)
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}
        self.vocab = list(df)

    def peso(self, w):
        return self.idf.get(w, math.log(1 + max(len(self.tareas), 1)))

    def guardar(self):
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.tareas, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)

    def buscar(self, texto):
        """Devuelve [(confianza, indice_tarea)] ordenado de mayor a menor."""
        q = tokens(texto)
        if not q:
            return []
        # Corrige errores de tipeo: palabra desconocida -> la mas parecida del vocabulario
        qs = {}
        for w in q:
            if w in self.idf:
                qs[w] = 1.0
            else:
                mejor = max(self.vocab, key=lambda v: parecido(w, v), default=None)
                s = parecido(w, mejor) if mejor else 0
                if s >= 0.75:
                    qs[mejor] = max(qs.get(mejor, 0), s)
                else:
                    qs[w] = 0.0  # palabra desconocida: penaliza pero no suma
        res = []
        for i, frases in enumerate(self.tok):
            mejor = 0.0
            for f in frases:
                comun = sum(self.peso(w) * s for w, s in qs.items() if w in f)
                union = sum(self.peso(w) for w in set(qs) | f)
                mejor = max(mejor, comun / union if union else 0)
            if mejor > 0:
                bonus = min(0.05, 0.01 * math.log1p(self.tareas[i]["usos"]))
                res.append((min(1.0, mejor + bonus), i))
        return sorted(res, reverse=True)

    def aprender(self, frase, cmd):
        """Refuerza una tarea existente (misma orden) o crea una nueva."""
        for t in self.tareas:
            if t["cmd"].lower() == cmd.lower():
                break
        else:
            t = {"cmd": cmd, "frases": [], "usos": 0}
            self.tareas.append(t)
        norm = " ".join(tokens(frase))
        if norm and norm not in (" ".join(tokens(f)) for f in t["frases"]):
            t["frases"].append(frase)
            t["frases"] = t["frases"][-MAX_FRASES:]   # olvida las variantes mas viejas
        t["usos"] += 1
        self.guardar()
        self._indexar()

    def olvidar(self, i):
        del self.tareas[i]
        self.guardar()
        self._indexar()

# ---------------------------------------------------------------- ejecucion
def ejecutar(cmd):
    if PELIGROSO.search(cmd) and input(f"  ⚠ '{cmd}' puede ser destructivo. ¿Ejecutar? (s/n) ").lower() != "s":
        print("  Cancelado.")
        return False
    try:
        if cmd.lower().startswith("start "):
            subprocess.Popen(cmd, shell=True)            # apps: no bloquea el chat
        else:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=30, encoding="cp850", errors="replace")
            print((r.stdout + r.stderr).rstrip() or "  (sin salida)")
            return r.returncode == 0
        return True
    except subprocess.TimeoutExpired:
        print("  Tiempo agotado.")
        return False

def preguntar_comando(mem, frase):
    cmd = input("  No sé hacer eso todavía. Escribe el comando CMD (Enter para cancelar): ").strip()
    if cmd and ejecutar(cmd):
        mem.aprender(frase, cmd)
        print("  ✓ Aprendido.")

def main():
    mem = Memoria()
    print("Asistente CMD. Escribe lo que necesitas (!lista, !aprender, !olvidar N, !salir)")
    while True:
        try:
            frase = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not frase:
            continue
        if frase == "!salir":
            break
        if frase == "!lista":
            for i, t in enumerate(mem.tareas):
                print(f"  [{i}] {t['cmd']:<30} usos={t['usos']:<3} {t['frases']}")
            continue
        if frase.startswith("!aprender") and "=>" in frase:
            f, c = frase[len("!aprender"):].split("=>", 1)
            mem.aprender(f.strip(), c.strip())
            print("  ✓ Aprendido.")
            continue
        if frase.startswith("!olvidar"):
            try:
                mem.olvidar(int(frase.split()[1]))
                print("  ✓ Olvidado.")
            except (IndexError, ValueError):
                print("  Uso: !olvidar N (ver !lista)")
            continue

        res = mem.buscar(frase)
        conf, i = res[0] if res else (0.0, -1)
        if conf >= UMBRAL_EJECUTAR:
            cmd = mem.tareas[i]["cmd"]
            print(f"  → {cmd}  (confianza {conf:.0%})")
            if ejecutar(cmd):
                mem.aprender(frase, cmd)            # cada acierto refuerza la memoria
        elif conf >= UMBRAL_PREGUNTAR:
            cmd = mem.tareas[i]["cmd"]
            if input(f"  ¿Te refieres a '{cmd}'? ({conf:.0%}) (s/n) ").lower() == "s":
                if ejecutar(cmd):
                    mem.aprender(frase, cmd)
            else:
                preguntar_comando(mem, frase)
        else:
            preguntar_comando(mem, frase)

if __name__ == "__main__":
    main()
