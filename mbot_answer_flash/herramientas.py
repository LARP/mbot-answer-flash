"""Registro de herramientas (comandos internos "@nombre" que se ejecutan en Python, no en cmd), validacion de rutas y plugins.

    @herramienta("hora", verbos=("*", "VER"), objetos=("HORA",), descripcion="dice la hora")
    def hora(ctx): return "Son las 10:00"

- `verbos` / `objetos`: clases del lexico (ABRIR, ARCHIVO...), palabras sueltas, o "*" (sin requisito). Se inyectan como marcos en
  la capa S (ver `capas._herr_s`), asi que la eleccion de herramienta pasa por el razonamiento normal. `disparadores` son regex
  (sobre la frase sin tildes) para las frases que el lexico no puede expresar ("cuanto es 2+2").
- `slots={nombre: tipo}`: tipo "carpeta" | "ruta" | "n" | "texto" | "patron" | "expresion" | "unidad"; un "?" final lo hace opcional,
  `(tipo, defecto)` da un valor por defecto, o un ConfigField completo. Si falta uno obligatorio se pregunta con ese esquema.
- `peligro=True`: nunca sale como "ejecutar" (siempre "confirmar").
- `requiere=("bin:powershell", "mod:ctypes", "os:win")`: `estado()` dice habilitada / deshabilitada / necesita configuracion.
- `veta=(regex,)`: si alguna casa con la frase (sin tildes) la herramienta NO compite (ej. @buscar se aparta de "busca X en google").
- `exige=(regex,)`: la ruta por marco (verbo, objeto) solo vale si alguna casa (una pista de contexto); los disparadores no la necesitan.
- `peso_senal`: puntaje de sus disparadores (0.9 por defecto); una herramienta mas especifica puede ganar un empate (0.95).
- `condicion`: callable(ctx, plano) -> bool; si da False la herramienta no compite (se evalua en la capa S, debe ser barato).
"""
import importlib.util, json, os, re, shutil, subprocess, sys, time
from dataclasses import dataclass, field
from datetime import datetime

from .config import BASE, DATA, S_BASE
from .lexico import ACCIONES, GENERICAS, OBJETOS
from .memoria import guardar_json
from .texto import sin_tildes
from .verificacion import partir_args, verbo_de

PREFIJO = "@"
PLUGINS_DIR = os.path.join(BASE, "plugins")
TIPOS_LIBRES = {"texto", "patron", "expresion"}          # slots de texto libre: las palabras sueltas de la frase son su contenido


@dataclass
class ConfigField:
    """Esquema de un slot (como ConfigField de RoninAgent): tipo, obligatorio, por defecto, pregunta."""
    nombre: str
    tipo: str = "texto"
    obligatorio: bool = True
    defecto: object = None
    pregunta: str = ""

    def pregunta_(self):
        return self.pregunta or {"carpeta": "Que carpeta", "ruta": "Que ruta", "n": "Que numero", "texto": "Que texto",
                                 "patron": "Que buscar (ej. pdf, *.jpg, informe)", "expresion": "Que operacion",
                                 "unidad": "Que unidad (ej. C:)"}.get(self.tipo, f"Valor de {self.nombre}")


@dataclass
class Resultado:
    ok: bool
    texto: str = ""
    datos: dict = field(default_factory=dict)


@dataclass
class Herramienta:
    nombre: str
    verbos: tuple = ()
    objetos: tuple = ()
    slots: dict = field(default_factory=dict)
    peligro: bool = False
    requiere: tuple = ()
    descripcion: str = ""
    fn: object = None
    escribe: bool = False
    disparadores: tuple = ()
    extraer: object = None
    relleno: frozenset = frozenset()
    excluye: tuple = ()
    origen: str = "interna"
    veta: tuple = ()
    exige: tuple = ()
    peso_senal: float = 0.9
    condicion: object = None             # callable(ctx, plano) -> bool: si da False la herramienta no compite (ej. @tabla sin documento reciente)

    @property
    def libre(self):
        return any(f.tipo in TIPOS_LIBRES for f in self.slots.values())


REGISTRO = {}
_ORIGEN = ["interna"]


def _campo(nombre, v):
    if isinstance(v, ConfigField):
        return v
    if isinstance(v, (tuple, list)):
        return ConfigField(nombre, v[0].rstrip("?"), False, v[1])
    obligatorio = not v.endswith("?")
    return ConfigField(nombre, v.rstrip("?"), obligatorio)


def herramienta(nombre, verbos=(), objetos=(), slots=None, peligro=False, requiere=(), descripcion="", *,
                escribe=False, disparadores=(), extraer=None, relleno=(), excluye=(), veta=(), exige=(), peso_senal=0.9, condicion=None):
    """Decorador: registra la funcion `fn(ctx, **slots) -> str | Resultado` como herramienta `@nombre`."""
    def deco(fn):
        REGISTRO[nombre] = Herramienta(
            nombre, tuple(verbos), tuple(objetos), {k: _campo(k, v) for k, v in (slots or {}).items()}, peligro,
            tuple(requiere), descripcion, fn, escribe,
            tuple(re.compile(d) if isinstance(d, str) else d for d in disparadores), extraer, frozenset(relleno),
            tuple(excluye), _ORIGEN[0],
            tuple(re.compile(d) if isinstance(d, str) else d for d in veta),
            tuple(re.compile(d) if isinstance(d, str) else d for d in exige), float(peso_senal), condicion)
        return fn
    return deco


# ---------------------------------------------------------------- estado y gestor (habilitar / deshabilitar, persistente)
def estado(h, off=()):
    """('habilitada' | 'deshabilitada' | 'necesita configuracion', detalle)."""
    if h.nombre in off:
        return "deshabilitada", "desactivada con !herramienta off"
    faltan = []
    for r in h.requiere:
        tipo, _, v = r.partition(":")
        if tipo == "bin" and not shutil.which(v):
            faltan.append(f"programa '{v}' no encontrado en el PATH")
        elif tipo == "mod" and importlib.util.find_spec(v) is None:
            faltan.append(f"modulo '{v}' no instalado")
        elif tipo == "os" and not (v == "win" and sys.platform == "win32"):
            faltan.append(f"solo disponible en {v}")
    if faltan:
        return "necesita configuracion", "; ".join(faltan)
    return "habilitada", ""


class GestorHerramientas:
    def __init__(self, ruta):
        self.ruta, self.off, self._cache = ruta, set(), None
        try:
            with open(ruta, encoding="utf-8") as f:
                self.off = set(json.load(f).get("off", []))
        except (OSError, ValueError, AttributeError):
            pass

    def estado(self, nombre):
        h = REGISTRO.get(nombre)
        return estado(h, self.off) if h else ("desconocida", "no existe")

    def poner(self, nombre, activa):
        if nombre not in REGISTRO:
            return False
        (self.off.discard if activa else self.off.add)(nombre)
        self._cache = None
        try:
            guardar_json(self.ruta, {"off": sorted(self.off)})
        except OSError:
            pass
        return True

    def activas(self):
        clave = (frozenset((k, id(v)) for k, v in REGISTRO.items()), frozenset(self.off))
        if self._cache is None or self._cache[0] != clave:
            self._cache = (clave, [h for h in REGISTRO.values() if estado(h, self.off)[0] == "habilitada"])
        return self._cache[1]

    def texto(self):
        L = ["  Herramientas (comandos internos, se ejecutan en Python):"]
        for n in sorted(REGISTRO):
            h = REGISTRO[n]
            est, det = estado(h, self.off)
            L.append(f"   @{n:<20} {est:<22} {h.descripcion}" + (f"  [{det}]" if det else "")
                     + ("  (peligrosa: confirma)" if h.peligro else "") + (f"  [{h.origen}]" if h.origen != "interna" else ""))
        L.append("  Usa: !herramienta on|off <nombre>")
        return "\n".join(L)

    def comando(self, arg):
        p = arg.split()
        if len(p) != 2 or p[0].lower() not in ("on", "off"):
            return "  Uso: !herramienta on|off <nombre>"
        n = p[1].lstrip("@")
        if not self.poner(n, p[0].lower() == "on"):
            return f"  No existe la herramienta '{n}'. (!herramientas)"
        return f"  Herramienta @{n}: {'habilitada' if p[0].lower() == 'on' else 'deshabilitada'}."


# ---------------------------------------------------------------- plugins de usuario
_PLUGIN_VISTOS = {}


def cargar_plugins(carpeta):
    """Importa cada .py de `carpeta` (que usa @herramienta). Devuelve (nombres registrados, [(archivo, error)]).
    Los plugins son codigo del usuario: se ejecutan con sus permisos (no hay sandbox)."""
    nombres, errores = [], []
    if not os.path.isdir(carpeta):
        return nombres, errores
    for f in sorted(os.listdir(carpeta)):
        if not f.endswith(".py") or f.startswith("_"):
            continue
        ruta = os.path.join(carpeta, f)
        antes = {k: id(v) for k, v in REGISTRO.items()}
        _ORIGEN[0] = "plugin:" + f
        try:
            spec = importlib.util.spec_from_file_location("mbot_answer_flash_plugin_" + f[:-3], ruta)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except (Exception, SystemExit) as e:             # un plugin roto no tumba el asistente
            errores.append((f, f"{type(e).__name__}: {e}"))
        finally:
            _ORIGEN[0] = "interna"
        nombres += [k for k, v in REGISTRO.items() if antes.get(k) != id(v)]
    return nombres, errores


# ---------------------------------------------------------------- contexto inyectable
def _uptime():
    try:
        import ctypes
        f = ctypes.windll.kernel32.GetTickCount64
        f.restype = ctypes.c_uint64
        return f() / 1000.0
    except Exception:
        return None


def _runner(args, entrada=None):
    """(rc, salida_bytes). Sin shell: args es una lista."""
    r = subprocess.run(list(args), input=entrada, capture_output=True, timeout=8)
    return r.returncode, r.stdout


@dataclass
class Ctx:
    reloj: object = datetime.now
    disk_usage: object = shutil.disk_usage
    runner: object = _runner
    uptime_s: object = _uptime
    mono: object = time.monotonic
    usuario: str = ""
    equipo: str = ""
    so: str = ""
    notas_path: str = os.path.join(DATA, "notas.json")
    carpetas: object = field(default_factory=dict)
    home: str = os.path.expanduser("~")
    tope_seg: float = 3.0
    tope_res: int = 50
    conocimiento: object = None          # buscador de conocimiento (mbot_answer_flash.conocimiento.Conocimiento), lo pone el Asistente
    memoria: object = None               # () -> {total, libre, uso_pct}; None = GlobalMemoryStatusEx (ver tools_locales)
    docs: object = None                  # SesionDocs (documento reciente, cache y traza de !porque); lo crea mbot_answer_flash.documentos al primer uso


# ---------------------------------------------------------------- validacion de rutas (estilo RoninAgent validatePath)
def _rutas_sistema():
    pf = [os.environ.get(k) for k in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")]
    pf += ["C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData", "C:\\System Volume Information"]
    return {os.path.normcase(os.path.realpath(p)) for p in pf if p}


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def validar_ruta(valor, requiere_existir=False, escritura=False, dentro_de=None, existe=os.path.exists):
    """-> (ok, ruta_real | None, motivo). Resuelve con os.path.realpath (quita .. y sigue symlinks/junctions)."""
    v = (valor or "").strip().strip('"')
    if not v or "\0" in v:
        return False, None, "ruta vacia o invalida"
    real = os.path.realpath(os.path.expandvars(os.path.expanduser(v)))
    n = os.path.normcase(real)
    if dentro_de is not None:
        base = _norm(dentro_de)
        try:
            ok = os.path.commonpath([n, base]) == base
        except ValueError:
            ok = False
        if not ok:
            return False, None, f"fuera de la carpeta permitida ({dentro_de})"
    if escritura:
        drive, resto = os.path.splitdrive(real)
        if resto in ("", "\\", "/"):
            return False, None, "no se escribe ni se borra en la raiz de un disco"
        for p in _rutas_sistema():
            if n == p or n.startswith(p + os.sep):
                return False, None, f"ruta de sistema protegida ({real})"
        home = os.path.normcase(os.path.realpath(os.path.expanduser("~")))
        if n in (home, os.path.dirname(home)):
            return False, None, "no se escribe ni se borra en la carpeta de usuario completa"
    if requiere_existir and not existe(real):
        return False, None, f"no existe: {real}"
    return True, real, ""


VERBOS_ESCRIBE = {"del", "erase", "rd", "rmdir", "mkdir", "md", "copy", "xcopy", "move", "ren", "rename"}
VERBOS_EXISTE = {"del", "erase", "rd", "rmdir", "type", "move", "ren", "rename"}
VERBOS_LECTURA = {"type", "dir"}


def validar_comando(cmd, existe=os.path.exists):
    """Valida las rutas de un comando de archivos antes de ejecutarlo.
    -> (ok, motivo, cmd_con_rutas_resueltas). Los comandos que no tocan rutas pasan tal cual."""
    v = verbo_de(cmd)
    if v not in VERBOS_ESCRIBE and v not in VERBOS_LECTURA:
        return True, "", cmd
    args = partir_args(cmd)[1:]
    rutas = [(val, crudo) for val, crudo in args if val and not (val.startswith("/") and len(val) <= 4) and not val.startswith("-")]
    if v in ("ren", "rename"):
        rutas = rutas[:1]
    nuevo = cmd
    for val, crudo in rutas:
        comodin = bool(re.search(r"[*?]", val))
        if set(val) & set('&|<>^"'):
            return False, f"caracteres no permitidos en la ruta {val!r}", cmd
        ruta = os.path.dirname(val) or "." if comodin else val
        ok, real, motivo = validar_ruta(ruta, requiere_existir=(v in VERBOS_EXISTE) or comodin,
                                        escritura=(v in VERBOS_ESCRIBE), existe=existe)
        if not ok:
            return False, motivo, cmd
        if not comodin:
            nuevo = nuevo.replace(crudo, f'"{real}"', 1)
    return True, "", nuevo


# ---------------------------------------------------------------- slots: extraccion, esquema y formato
def plano_alineado(t):
    """Minusculas sin tildes con la MISMA longitud que `t` (los indices valen para el texto original)."""
    out = []
    for c in t:
        s = sin_tildes(c).lower()
        out.append(s if len(s) == 1 else c.lower())
    return "".join(out)


def extraer_slots(h, an, ctx, orig, plano, grupos=None):
    """Valores de los slots de `h` para la frase `an` (orig/plano: frase sin signos de contorno). {} si no hay."""
    vals = {k: v.strip() for k, v in (grupos or {}).items() if v and v.strip() and k in h.slots}
    sl = list(an.slots.values())
    for nom, f in h.slots.items():
        if nom in vals:
            continue
        v = None
        if f.tipo in ("carpeta", "ruta"):
            v = next((s["val"] for s in sl if s["tipo"] == f.tipo), None) or next((s["val"] for s in sl if s["tipo"] in ("carpeta", "ruta")), None)
        elif f.tipo == "n":
            n = next((s["val"] for s in sl if s["tipo"] == "n"), None)
            v = int(n) if n and n.isdigit() else None
        elif f.tipo == "texto":
            v = next((s["val"] for s in sl if s["tipo"] == "texto"), None)
        elif f.tipo == "unidad":
            m = re.search(r"\b([a-z]):(?![\\/\w])", plano)
            v = m.group(1).upper() + ":" if m else None
        if v not in (None, ""):
            vals[nom] = v
    if h.extraer:
        for k, v in (h.extraer(an, ctx, orig, plano) or {}).items():
            if v not in (None, "") and k in h.slots:
                vals[k] = v
    return vals


def resolver_slots(h, vals):
    """Aplica los valores por defecto. -> (valores, [ConfigField que faltan])."""
    out, faltan = dict(vals), []
    for nom, f in h.slots.items():
        if out.get(nom) in (None, ""):
            out.pop(nom, None)
            if f.defecto is not None:
                out[nom] = f.defecto() if callable(f.defecto) else f.defecto
            elif f.obligatorio:
                faltan.append(f)
    return out, faltan


def formato_cmd(h, vals):
    """Texto del comando interno: '@calcular expresion=3*(4+5)'."""
    partes = [PREFIJO + h.nombre]
    for nom in h.slots:
        if nom in vals:
            v = str(vals[nom])
            partes.append(f'{nom}="{v}"' if re.search(r"\s", v) else f"{nom}={v}")
    return " ".join(partes)


def es_herramienta(cmd):
    return bool(cmd) and cmd.lstrip().startswith(PREFIJO) and cmd.lstrip()[1:].split(" ", 1)[0] in REGISTRO


# ---------------------------------------------------------------- puntuacion de marcos (capa S)
def puntuar_herr(m, h, plano):
    """(puntaje, via) de la herramienta `h` para el marco `m` y el texto `plano`; (0, None) si no encaja.
    via = ("marco", (verbo, objeto)) | ("senal", patron)."""
    mejor, via = 0.0, None
    usadas = set()
    if h.veta and any(rx.search(plano) for rx in h.veta):
        return 0.0, None
    if (h.verbos or h.objetos) and (not h.exige or any(rx.search(plano) for rx in h.exige)):
        prim_ok = m.prim is None or m.prim in GENERICAS or not h.verbos or m.prim in h.verbos or any(
            v not in ACCIONES and v != "*" for v in h.verbos)
        if prim_ok:
            palabras = {w for w, _cl in m.cont}
            for v in (h.verbos or ("*",)):
                for o in (h.objetos or ("*",)):
                    if v == "*" and o == "*":
                        continue
                    if v == "*":
                        fa = 0.85
                    elif v in ACCIONES:
                        fa = 1.0 if v == m.prim else 0.9 if v in m.acts else 0.0
                    else:
                        fa = 1.0 if v in palabras else 0.0
                    if fa <= 0:
                        continue
                    if o == "*":
                        fo = 1.0
                    elif o in OBJETOS:
                        fo = 1.0 if o in m.objs else 0.0
                    else:
                        fo = 1.0 if o in palabras else 0.0
                    if fo <= 0:
                        continue
                    sc = S_BASE * fa * fo
                    if sc > mejor:
                        mejor, via = sc, ("marco", (v, None if o == "*" else o))
                        usadas = {x for x in (v, o) if x not in ACCIONES and x not in OBJETOS and x != "*"}
        if mejor and any(x in m.objs for x in h.excluye):
            mejor, via = 0.0, None
        if mejor and not h.libre:
            sueltas = [w for w in m.resid if w not in usadas and len(w) > 1 and w not in h.relleno]
            if sueltas:
                mejor, via = 0.0, None             # palabras que la herramienta no entiende: no se adivina
    for rx in h.disparadores:
        if h.peso_senal > mejor and rx.search(plano):
            mejor, via = h.peso_senal, ("senal", rx.pattern)
    return mejor, via


# ---------------------------------------------------------------- ejecucion
def ejecutar(h, vals, ctx):
    """Valida los slots de ruta y llama a la funcion. Nunca lanza: devuelve Resultado."""
    vals = dict(vals)
    for nom, f in h.slots.items():
        if nom in vals and f.tipo in ("carpeta", "ruta"):
            ok, real, motivo = validar_ruta(str(vals[nom]), requiere_existir=True, escritura=h.escribe)
            if not ok:
                return Resultado(False, f"Ruta rechazada: {motivo}")
            vals[nom] = real
        elif nom in vals and f.tipo == "n":
            try:
                vals[nom] = int(vals[nom])
            except (TypeError, ValueError):
                return Resultado(False, f"'{vals[nom]}' no es un numero")
    try:
        r = h.fn(ctx, **vals)
    except Exception as e:
        return Resultado(False, f"La herramienta @{h.nombre} fallo: {type(e).__name__}: {e}")
    if isinstance(r, Resultado):
        return r
    if isinstance(r, tuple) and len(r) == 2:
        return Resultado(bool(r[0]), str(r[1]))
    return Resultado(True, str(r))
