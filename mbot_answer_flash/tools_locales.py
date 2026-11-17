"""Herramientas locales iniciales (sin red): hora, fecha, calculadora segura, disco, portapapeles, archivos, notas, sistema."""
import ast, fnmatch, getpass, json, math, operator, os, platform, re, socket
from datetime import datetime

from .herramientas import ConfigField, Resultado, herramienta
from .memoria import guardar_json

DIAS = "lunes martes miércoles jueves viernes sábado domingo".split()
MESES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


# ---------------------------------------------------------------- calculadora segura (ast + lista blanca; nunca eval)
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNC = {"sqrt": math.sqrt, "abs": abs, "round": round}
_CONST = {"pi": math.pi, "e": math.e}
MAX_LARGO, MAX_PROF, MAX_BITS = 200, 40, 100_000


def normalizar_expresion(t):
    """Texto en espanol -> expresion aritmetica ("15% de 230" -> "(15*230/100)", "2,5 por 3" -> "2.5*3")."""
    t = t.lower().replace("×", "*").replace("÷", "/").replace("^", "**").replace("−", "-")
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:%|por\s*ciento)\s*de\s*(\d+(?:[.,]\d+)?)", r"(\1*\2/100)", t)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", t)
    t = re.sub(r"\braiz(?:\s+cuadrada)?\s+de\s+(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"\belevado\s+a(?:\s+la)?\s+", "**", t)
    for pal, op in ((r"dividido\s+(?:por|entre)", "/"), (r"\bentre\b", "/"), (r"\bpor\b", "*"), (r"\bmas\b|\bmás\b", "+"),
                    (r"\bmenos\b", "-")):
        t = re.sub(pal, op, t)
    return t


def _ev(n, prof=0):
    if prof > MAX_PROF:
        raise ValueError("expresion demasiado anidada")
    if isinstance(n, ast.Expression):
        return _ev(n.body, prof + 1)
    if isinstance(n, ast.Constant):
        if type(n.value) in (int, float):
            if isinstance(n.value, float) and not math.isfinite(n.value):
                raise ValueError("numero fuera de rango")
            return n.value
        raise ValueError("solo se admiten numeros")
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand, prof + 1))
    if isinstance(n, ast.BinOp):
        a, b = _ev(n.left, prof + 1), _ev(n.right, prof + 1)
        if isinstance(n.op, ast.Pow):
            if isinstance(b, int) and isinstance(a, int):
                if abs(b) > 1000 or abs(a).bit_length() * abs(b) > 20_000:
                    raise ValueError("potencia demasiado grande")
            elif abs(b) > 1000:
                raise ValueError("potencia demasiado grande")
            r = a ** b
        elif type(n.op) in _BIN:
            r = _BIN[type(n.op)](a, b)
        else:
            raise ValueError("operador no permitido")
        if isinstance(r, complex):
            raise ValueError("resultado complejo")
        if isinstance(r, int) and r.bit_length() > MAX_BITS:
            raise ValueError("resultado demasiado grande")
        if isinstance(r, float) and not math.isfinite(r):
            raise ValueError("resultado fuera de rango")
        return r
    if isinstance(n, ast.Call):
        if not (isinstance(n.func, ast.Name) and n.func.id in _FUNC and not n.keywords and len(n.args) == 1):
            raise ValueError("funcion no permitida")
        return _FUNC[n.func.id](_ev(n.args[0], prof + 1))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    raise ValueError("expresion no permitida")


def calcular_seguro(expr):
    """Evalua una expresion aritmetica con lista blanca de nodos. Lanza ValueError ante cualquier cosa rara."""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > MAX_LARGO:
        raise ValueError("expresion vacia o demasiado larga")
    try:
        v = _ev(ast.parse(normalizar_expresion(expr).strip(), mode="eval"))
    except ValueError:
        raise
    except (SyntaxError, RecursionError, MemoryError, ZeroDivisionError, OverflowError, TypeError) as e:
        raise ValueError(f"no se pudo calcular ({type(e).__name__})")
    if isinstance(v, float):
        v = round(v, 10)
        if v.is_integer() and abs(v) < 1e15:
            v = int(v)
    return v


_TOK_EXPR = re.compile(r"\d+(?:\.\d+)?|sqrt|abs|round|pi|\*\*|//|[-+*/()%]")


def _extraer_expresion(an, ctx, orig, plano):
    t = normalizar_expresion(plano)
    toks = _TOK_EXPR.findall(t)
    if not any(re.match(r"\d|pi", x) for x in toks) or len(toks) < 2:
        return {}
    return {"expresion": " ".join(toks)}


def _fmt_num(v):
    return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


@herramienta("calcular", verbos=("CALCULAR",), objetos=("*",), slots={"expresion": "expresion"}, extraer=_extraer_expresion,
             descripcion="calculadora segura: 'calcula 3*(4+5)', 'cuanto es 15% de 230'",
             disparadores=(r"^(?:cuanto\s+(?:es|son|da|vale|seria|serian|resulta)|cual\s+es\s+el\s+resultado\s+de|resultado\s+de)\s+"
                           r"(?=.*\d)(?=.*(?:[-+*/%^]|\b(?:por|mas|menos|entre|dividido|elevado|raiz)\b|\d\s*x\s*\d))",
                           r"^(?:cual\s+es\s+)?(?:la\s+)?raiz(?:\s+cuadrada)?\s+de\s+\d"))
def calcular(ctx, expresion):
    v = calcular_seguro(expresion)
    return Resultado(True, f"{expresion} = {_fmt_num(v)}", {"valor": v})


# ---------------------------------------------------------------- hora y fecha
@herramienta("hora", verbos=("*", "VER"), objetos=("HORA",), relleno=("exacta", "actual", "actualmente", "ahorita", "exactamente"),
             descripcion="dice la hora: 'que hora es', 'dime la hora'")
def hora(ctx):
    return f"Son las {ctx.reloj():%H:%M}."


@herramienta("fecha", verbos=("*", "VER"), objetos=("FECHA",), relleno=("actual", "actualmente", "exacta"),
             disparadores=(r"\ba\s+que\s+(?:fecha|dia)\s+(?:estamos|es\s+hoy)\b", r"\bque\s+fecha\s+(?:es|tenemos|estamos)\b"),
             descripcion="dice la fecha: 'que dia es hoy', 'dime la fecha', 'a que fecha estamos'")
def fecha(ctx):
    d = ctx.reloj()
    return f"Hoy es {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}."


# ---------------------------------------------------------------- disco
def _unidad_def():
    return os.environ.get("SystemDrive", "C:")


@herramienta("espacio", verbos=("*", "VER"), objetos=("ESPACIO",), slots={"unidad": ("unidad", _unidad_def)},
             excluye=("TAMANO", "CARPETA"), relleno=("duro",),
             descripcion="espacio libre en disco: 'cuanto espacio me queda' (opcional: 'en D:')")
def espacio(ctx, unidad=None):
    u = (unidad or _unidad_def()).rstrip("\\/")
    total, usado, libre = ctx.disk_usage(u + "\\")
    g = 1024 ** 3
    pct = round(100 * usado / total) if total else 0
    return Resultado(True, f"{u} {libre / g:.1f} GB libres de {total / g:.1f} GB ({pct}% usado).",
                     {"libre": libre, "total": total, "usado": usado})


# ---------------------------------------------------------------- portapapeles
_RX_COPIA = re.compile(r"^\s*(?:copia|copiar|copiame|guarda|pon|mete|manda)\s+(?:el\s+texto\s+)?(?P<t>.+?)\s+(?:al|en\s+el|en|a)\s+(?:el\s+)?"
                       r"(?:portapapeles|clipboard)\s*$", re.I | re.S)


def _extraer_copia(an, ctx, orig, plano):
    q = next((s["val"] for s in an.slots.values() if s["tipo"] == "texto"), None)
    if q:
        return {"texto": q}
    m = _RX_COPIA.match(orig)
    return {"texto": m.group("t").strip().strip("\"'“”")} if m else {}


@herramienta("portapapeles_copiar", verbos=("COPIAR",), objetos=("PORTAPAPELES",), slots={"texto": "texto"}, requiere=("bin:clip",),
             escribe=True, extraer=_extraer_copia, descripcion="copia un texto al portapapeles (clip): 'copia hola al portapapeles'")
def portapapeles_copiar(ctx, texto):
    rc, _out = ctx.runner(["clip"], entrada=texto.encode("utf-16"))
    return Resultado(rc == 0, f"Copiado al portapapeles: {texto[:80]}" if rc == 0 else "No se pudo usar clip.")


@herramienta("portapapeles_leer", verbos=("*", "VER"), objetos=("PORTAPAPELES",), requiere=("bin:powershell",),
             descripcion="lee el portapapeles (Get-Clipboard): 'que hay en el portapapeles'")
def portapapeles_leer(ctx):
    rc, out = ctx.runner(["powershell", "-NoProfile", "-Command",
                          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"])
    if rc != 0:
        return Resultado(False, "No se pudo leer el portapapeles.")
    t = (out or b"").decode("utf-8", errors="replace").strip()
    return Resultado(True, ("Portapapeles: " + t[:500] + ("..." if len(t) > 500 else "")) if t else "El portapapeles esta vacio.", {"texto": t})


# ---------------------------------------------------------------- archivos
def _hum(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


@herramienta("listar_carpeta", verbos=("VER",), objetos=("CARPETA", "ARCHIVO"), slots={"carpeta": "carpeta"}, excluye=("TAMANO", "ESPACIO"),
             disparadores=(r"^que\s+(?:hay|archivos\s+hay|archivos\s+tengo)\s+en\b",),
             descripcion="lista una carpeta: 'lista la carpeta Descargas', 'que hay en Documentos'")
def listar_carpeta(ctx, carpeta):
    try:
        es = sorted(os.scandir(carpeta), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except OSError as e:
        return Resultado(False, f"No se pudo leer la carpeta: {e}")
    L = []
    for e in es[:ctx.tope_res]:
        if e.is_dir(follow_symlinks=False):
            L.append(f"  [carpeta] {e.name}")
        else:
            try:
                L.append(f"  {e.name}  ({_hum(e.stat(follow_symlinks=False).st_size)})")
            except OSError:
                L.append(f"  {e.name}")
    mas = f"\n  ... y {len(es) - ctx.tope_res} mas" if len(es) > ctx.tope_res else ""
    return Resultado(True, f"{carpeta} ({len(es)} elementos):\n" + "\n".join(L) + mas, {"n": len(es)})


@herramienta("tamano_carpeta", verbos=("*", "VER"), objetos=("TAMANO",), slots={"carpeta": "carpeta"}, relleno=("carpeta",),
             descripcion="tamano de una carpeta: 'cuanto pesa la carpeta Descargas'")
def tamano_carpeta(ctx, carpeta):
    t0, total, n, parcial = ctx.mono(), 0, 0, False
    pila = [carpeta]
    while pila and not parcial:
        d = pila.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if ctx.mono() - t0 > ctx.tope_seg:
                        parcial = True
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            pila.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            n += 1
                    except OSError:
                        pass
        except OSError:
            pass
    txt = f"{carpeta}: {_hum(total)} en {n} archivos" + (" (parcial: se agoto el tiempo)" if parcial else ".")
    return Resultado(True, txt, {"bytes": total, "archivos": n, "parcial": parcial})


EXT_TIPO = {"IMAGEN": "*.jpg,*.jpeg,*.png,*.gif,*.bmp", "MUSICA": "*.mp3,*.wav,*.flac,*.m4a", "VIDEO": "*.mp4,*.mkv,*.avi,*.mov"}
EXTS = set("pdf docx doc xlsx xls pptx ppt txt jpg jpeg png gif bmp mp3 wav mp4 mkv avi zip rar csv py bat log json exe md".split())
_NO_NOMBRE = {"archivos", "archivo", "fotos", "foto", "imagenes", "imagen", "musica", "videos", "video"}


_EXT_RE = r"(?:pdf|docx?|xlsx?|pptx?|txt|jpe?g|png|gif|bmp|mp3|wav|mp4|mkv|avi|zip|rar|csv|py|bat|log|json|md)"
_RX_NOMBRE = re.compile(r"^(?:donde\s+\w+|encuentra\w*|localiza\w*|halla\w*)\s+(?:el|la|los|las|mi|mis)\s+(?:archivo|fichero|documento)s?\s+"
                        r"(?:llamad[oa]s?\s+|que\s+se\s+llama\s+|de\s+)?(?P<n>[^\s*?]+)")


def _extraer_patron(an, ctx, orig, plano):
    sin_carpeta = not any(s["tipo"] == "carpeta" for s in an.slots.values())
    r = _extraer_patron_(an, ctx, orig, plano)
    if r and sin_carpeta:                       # un nombre de archivo suelto ("informe.docx") no es la carpeta donde buscar
        r["carpeta"] = os.path.expanduser("~")
    return r


def _extraer_patron_(an, ctx, orig, plano):
    q = next((s["val"] for s in an.slots.values() if s["tipo"] == "texto"), None)
    if q:
        return {"patron": q if re.search(r"[*?.]", q) else f"*{q}*"}
    g = re.search(r"\S*[*?]\S*", plano)
    if g:
        return {"patron": g.group(0)}
    f = next((s["val"] for s in an.slots.values() if s["tipo"] == "ruta" and not re.search(r"[\\/]", s["val"])), None)
    if f:
        return {"patron": f}
    ext = [w for w in re.findall(r"[a-z0-9]+", plano) if w in EXTS]
    if ext:
        return {"patron": ",".join(f"*.{e}" for e in dict.fromkeys(ext))}
    for k, cl in an.marco.cont:
        for c in cl or ():
            if c in EXT_TIPO:
                return {"patron": EXT_TIPO[c]}
    m = re.search(r"\b(?:llamad[oa]s?|que\s+se\s+llam\w+|con\s+(?:el\s+)?nombre)\s+(\S+)", plano)
    if m:
        return {"patron": f"*{m.group(1)}*"}
    m = _RX_NOMBRE.search(plano)                # "donde esta el archivo presupuesto" -> *presupuesto*
    return {"patron": m.group("n") if "." in m.group("n") else f"*{m.group('n')}*"} if m else {}


@herramienta("buscar_archivos", verbos=("BUSCAR",), objetos=("ARCHIVO", "IMAGEN", "MUSICA", "VIDEO"),
             slots={"patron": "patron", "carpeta": ("carpeta", lambda: os.path.expanduser("~"))}, extraer=_extraer_patron,
             disparadores=(r"^(?:encuentra\w*|localiza\w*|busca\w*|halla\w*)\s+(?:todos\s+)?(?:(?:los|las|mis|todos\s+los|todas\s+las)\s+)?"
                           r"(?:(?:archivos|ficheros|documentos)\s+)?" + _EXT_RE + r"s?\b",
                           r"^(?:encuentra\w*|localiza\w*|halla\w*)\s+(?:el|la|los|las|mi|mis)\s+(?:archivo|fichero|documento)s?\b",
                           r"^donde\s+(?:esta|estan|queda|quedan)\s+(?:el|la|los|las|mi|mis)\s+(?:archivo|fichero|documento)s?\b"),
             descripcion="busca archivos por NOMBRE/extension (recursivo, con tope de tiempo): 'busca archivos pdf en Descargas', 'donde esta el archivo x.docx'")
def buscar_archivos(ctx, patron, carpeta):
    pats = [p.strip().lower() for p in patron.split(",") if p.strip()]
    t0, hallados, revisados, parcial = ctx.mono(), [], 0, False
    saltar = {"appdata", "node_modules", "$recycle.bin", "windows", "program files", "program files (x86)"}
    pila = [carpeta]
    while pila and not parcial:
        d = pila.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if ctx.mono() - t0 > ctx.tope_seg or len(hallados) >= ctx.tope_res:
                        parcial = True
                        break
                    revisados += 1
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() not in saltar and not e.name.startswith("."):
                                pila.append(e.path)
                        elif any(fnmatch.fnmatchcase(e.name.lower(), p) for p in pats):
                            hallados.append(e.path)
                    except OSError:
                        pass
        except OSError:
            pass
    cab = f"{len(hallados)} resultado(s) para {patron} en {carpeta}" + (" (parcial: tope de tiempo o de resultados)" if parcial else "")
    return Resultado(True, cab + "".join("\n  " + h for h in hallados[:ctx.tope_res]), {"encontrados": hallados, "parcial": parcial, "revisados": revisados})


# ---------------------------------------------------------------- notas (notas.json; distinto de `personal` y de los recordatorios)
def _leer_notas(ctx):
    try:
        with open(ctx.notas_path, encoding="utf-8") as f:
            d = json.load(f)
        return d["notas"] if isinstance(d, dict) else list(d)
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _guardar_notas(ctx, notas):
    guardar_json(ctx.notas_path, {"v": 1, "notas": notas})


@herramienta("nota_agregar", slots={"texto": ConfigField("texto", pregunta="¿Qué quieres anotar?")}, escribe=True,
             descripcion="guarda una nota: 'anota comprar pan'",
             disparadores=(r"^(?:anota|anotame|apunta|apuntame|toma\s+nota|guarda\s+(?:una\s+)?nota|agrega\s+(?:una\s+)?nota|anade\s+(?:una\s+)?nota|"
                           r"nueva\s+nota|crea\s+(?:una\s+)?nota)(?:\s+que)?(?:\s*:\s*|\s+(?P<texto>.+))?$",))
def nota_agregar(ctx, texto):
    notas = _leer_notas(ctx)
    notas.append({"texto": texto.strip(), "ts": ctx.reloj().isoformat(timespec="minutes")})
    _guardar_notas(ctx, notas)
    return Resultado(True, f"Nota {len(notas)} guardada: {texto.strip()}", {"n": len(notas)})


@herramienta("nota_listar", descripcion="muestra tus notas: 'mis notas'",
             disparadores=(r"^(?:mis\s+notas|ver\s+mis\s+notas|(?:muestra|muestrame|mostrar|lista|listame|dime|revisa|ensename|ver)\s+(?:mis\s+|las\s+)?notas|"
                           r"que\s+notas\s+tengo|cuales\s+son\s+mis\s+notas)$",))
def nota_listar(ctx):
    notas = _leer_notas(ctx)
    if not notas:
        return Resultado(True, "No tienes notas.", {"notas": []})
    return Resultado(True, "Tus notas:\n" + "\n".join(f"  {i}. {n['texto']}  ({n.get('ts', '')[:16].replace('T', ' ')})"
                                                      for i, n in enumerate(notas, 1)), {"notas": notas})


@herramienta("nota_borrar", slots={"n": "n"}, peligro=True, escribe=True, descripcion="borra la nota N (pide confirmacion): 'borra la nota 2'",
             disparadores=(r"^(?:borra|borrar|elimina|eliminar|quita|quitar|suprime|suprimir)(?:me)?\s+(?:la\s+)?nota\s+(?:numero\s+|no\.?\s+|n\s+)?(?P<n>\d+)$",))
def nota_borrar(ctx, n):
    notas = _leer_notas(ctx)
    if not 1 <= n <= len(notas):
        return Resultado(False, f"No existe la nota {n} (tienes {len(notas)}).")
    quitada = notas.pop(n - 1)
    _guardar_notas(ctx, notas)
    return Resultado(True, f"Nota {n} borrada: {quitada['texto']}", {"n": n})


# ---------------------------------------------------------------- sistema
def _dur(s):
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return " ".join(x for x in ((f"{d} d" if d else ""), (f"{h} h" if h or d else ""), f"{m} min") if x)


@herramienta("sistema", descripcion="info rapida: usuario, equipo, SO y uptime ('info rapida del sistema', 'uptime')",
             disparadores=(r"\buptime\b", r"\binfo(?:rmacion)?\s+rapida\b", r"\binfo\s+(?:del|de\s+mi)\s+(?:equipo|pc|sistema|computador\w*|maquina)\b", r"\bresumen\s+del\s+(?:sistema|equipo|pc)\b",
                           r"\btiempo\s+(?:lleva|llevo)\w*.*\b(?:encendid|prendid)\w*", r"\bdesde\s+cuando\s+(?:esta|estoy)\s+(?:encendid|prendid)"))
def sistema(ctx):
    up = ctx.uptime_s()
    L = [f"Usuario: {ctx.usuario or getpass.getuser()}", f"Equipo: {ctx.equipo or socket.gethostname()}",
         f"SO: {ctx.so or platform.platform(terse=True)}"]
    if up is not None:
        L.append(f"Encendido hace {_dur(up)}")
    return Resultado(True, "  ".join(L), {"uptime_s": up})


# ---------------------------------------------------------------- memoria RAM (ctypes GlobalMemoryStatusEx; sin subprocesos)
def _memoria_win():
    """{total, libre, uso_pct} en bytes con GlobalMemoryStatusEx. Lanza OSError si no es Windows."""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise OSError("GlobalMemoryStatusEx fallo")
    return {"total": int(st.ullTotalPhys), "libre": int(st.ullAvailPhys), "uso_pct": int(st.dwMemoryLoad)}


@herramienta("memoria", requiere=("mod:ctypes", "os:win"),
             disparadores=(r"\b(?:cuanta|cuanto)\s+(?:memoria|ram)\b", r"\bram\b", r"\bmemoria\s+(?:ram\s+)?(?:libre|disponible|usada|fisica|total)\b",
                           r"\b(?:uso|consumo)\s+de\s+(?:memoria|ram)\b"),
             descripcion="memoria RAM total, libre y en uso (GlobalMemoryStatusEx): 'cuanta ram tengo', 'memoria libre'")
def memoria(ctx):
    m = (ctx.memoria or _memoria_win)()
    g = 1024 ** 3
    return Resultado(True, f"RAM: {m['libre'] / g:.1f} GB libres de {m['total'] / g:.1f} GB ({m['uso_pct']}% en uso).", dict(m))


# ---------------------------------------------------------------- buscar en el conocimiento (notas, memoria, tareas, carpetas indexadas)
# Desambiguacion (todas las reglas sobre la frase sin tildes):
#  - @buscar_archivos busca archivos por NOMBRE o extension ("busca archivos pdf en Descargas", "encuentra los pdf", "donde esta el archivo x.docx").
#  - @buscar busca por CONTENIDO: "que se sobre X", "que dice mi archivo sobre X", "busca en mis notas X", "como hago X", "que comando abre X",
#    "donde anote X", "que anote ayer", "busca informacion sobre X". Sus disparadores valen 0.95 (ganan un empate con @buscar_archivos).
#  - Google: veta con "en google|internet|youtube|bing|la web|wikipedia" (esa frase es de la tarea 'buscar {texto} en google').
#  - Personal: veta las consultas de personal.py ("cual es mi X", "que sabes de mi", "que X uso", "donde vivo", "como me llamo").
#    "que se sobre mi proyecto" (primera persona, no 'sabes') SI es de conocimiento; "que sabes de mi navegador" es personal.
#  - La ruta por marco (BUSCAR, *) solo vale con una pista de contexto (notas, apuntes, memoria...) y sin objetos de archivo/sitio/proceso:
#    "busca una receta de pasta" a secas no elige ninguna herramienta.
_PIDE = r"(?:sobre|de|del|acerca\s+de)"
_PRE = r"^(?:(?:por\s+favor|dime|dame|oye|quiero\s+saber|me\s+puedes\s+decir|podrias\s+decirme)\s+)?"        # "dime que anote ayer"
_RX_BUSCAR = (
    _PRE + r"que\s+(?:se|anote|apunte|escribi|guarde|tenia\s+anotado)\s+(?:yo\s+)?" + _PIDE + r"\s+\S",          # primera persona: "que se sobre mi proyecto"
    _PRE + r"que\s+(?:sabes|recuerdas)\s+(?:yo\s+)?" + _PIDE + r"\s+(?!mi\b|mis\b|ti\b|mi$)\S",                # segunda persona + mi = personal.py
    r"^(?:busca\w*|encuentra\w*|localiza\w*|consulta\w*|revisa\w*|mira\w*)\s+(?:algo\s+)?en\s+(?:mis|mi|las|los|el|la)\s+"
    r"(?:notas?|apuntes?|anotaciones|memoria|archivos|documentos|textos|recuerdos|base\s+de\s+conocimiento)\b",
    r"\b(?:que\s+)?(?:dice|dicen|decia|decian)\s+(?:mi|mis|el|la|los|las)\s+(?:archivo|archivos|documento|documentos|nota|notas|apunte|apuntes|texto|textos)\b",
    _PRE + r"(?:como|de\s+que\s+manera)\s+(?:hago|hacer|puedo|se\s+hace|se\s+hacia|hice|lo\s+hago|haria)\s+\S",
    _PRE + r"(?:que|cual)\s+comando\s+\S",
    _PRE + r"donde\s+(?:anote|apunte|guarde|escribi|puse|deje|vi|lei|mencione|tengo\s+anotado|esta\s+anotado)\s+\S",
    r"^(?:busca\w*|encuentra\w*|dame|dime)\s+(?:info|informacion|datos|apuntes)\s+" + _PIDE + r"\s+\S",
    _PRE + r"que\s+(?:informacion|info|datos|apuntes|notas)\s+(?:tengo|tenemos|hay|guarde|anote)\s+" + _PIDE + r"\s+\S",
    _PRE + r"(?:que|cuando|donde)\s+(?:anote|apunte|escribi)\b",
)
_VETA_BUSCAR = (
    r"\.(?:docx|docm|xlsx|xlsm|pptx|odt|ods|pdf)\b",                 # un documento concreto: @leer / @preguntar_doc (bloque 4)
    r"\ben\s+(?:google|internet|youtube|bing|la\s+web|wikipedia)\b",
    r"^(?:cual|como|que)\s+(?:es|era|sera)\s+mi\b", r"^como\s+me\s+llamo\b",
    r"^(?:que|cuanto)\s+(?:sabes|recuerdas|conoces)\s+(?:de|sobre)\s+(?:mi|mis|ti)\b",
    r"^que\s+\w+(?:\s+de\s+\w+)?\s+(?:uso|usaba|usas|prefiero|preferia|utilizo)\b",
    r"^donde\s+(?:vivo|vivia|trabajo|trabajaba)\b",
)


def _extraer_buscar(an, ctx, orig, plano):
    from .conocimiento import parsear_consulta
    c = parsear_consulta(orig, ctx.reloj())
    return {"consulta": orig.strip()} if (not c.vacia() or c.hay_filtro()) else {}


@herramienta("buscar", verbos=("BUSCAR",), objetos=("*",), slots={"consulta": "texto"}, extraer=_extraer_buscar, peso_senal=0.95,
             excluye=("ARCHIVO", "IMAGEN", "MUSICA", "VIDEO", "CARPETA", "SITIO", "PROCESO", "DISCO"),
             exige=(r"\b(?:notas?|apuntes?|anotaciones|memoria|recuerdos|conocimiento)\b",), veta=_VETA_BUSCAR, disparadores=_RX_BUSCAR,
             descripcion="busca por contenido en tus notas, memoria, tareas aprendidas y carpetas indexadas (!indexar): 'que se sobre el wifi', "
                         "'busca en mis notas X', 'como hago X', 'donde anote X'")
def buscar(ctx, consulta):
    k = ctx.conocimiento
    if k is None:
        return Resultado(False, "El buscador de conocimiento no esta disponible.")
    r = k.buscar(consulta, ahora=ctx.reloj())
    datos = {"hallazgos": [{"titulo": h.titulo, "fuente": h.fuente, "ruta": h.ruta, "fecha": h.fecha, "snippet": h.snippet} for h in r.hallazgos],
             "corregida": r.corregida, "sugerencia": r.sugerencia, "relacionados": r.relacionados}
    return Resultado(not r.error, r.texto(), datos)
