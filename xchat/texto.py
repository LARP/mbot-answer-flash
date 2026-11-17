"""Normalizacion de texto: tildes, tokens con raiz ligera, typos."""
import difflib, re, unicodedata

STOP = set("""el la los las un una unos unas de del al a en y o u que por para con sin mi mis me te se
lo le les necesito quiero queria puedes podrias puede favor porfa ayudame dame hazme haz algo
como es esto eso este esta ese esa ahora rapido please tu su sus yo uno otra otro mas cual cuales quien cuanto cuantos
voy vamos quisiera gustaria deseo""".split())

SIN = {}
for _canon, _vars in {
    "abrir":   "abre abri abras abrir ejecuta ejecutar inicia iniciar lanza lanzar arranca arrancar corre correr pon",
    "cerrar":  "cierra cerrar mata matar termina terminar finaliza",
    "ver":     "muestra mostrar ver lista listar dime enseña ensena revisa revisar consulta",
    "notepad": "bloc notas notepad",
    "calc":    "calculadora calc calcular",
    "carpeta": "carpeta carpetas directorio explorador archivos",
    "red":     "red ip internet conexion wifi",
    "tareas":  "tareas procesos administrador",
}.items():
    for _v in _vars.split():
        SIN[_v] = _canon
SIN_KEYS = list(SIN)

MARK = re.compile(r"\{[a-z_]+\d*\}")
TOK_RE = re.compile(r"\{[a-z_]+\d*\}|[a-z0-9]+")


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- texto
_TOK_CACHE = {}


def _palabra(w):
    """Normaliza una palabra (cache). Devuelve '' si es palabra vacia."""
    r = _TOK_CACHE.get(w)
    if r is not None:
        return r
    orig = w
    if w in STOP:
        r = ""
    elif w.startswith("{"):
        r = w
    else:
        if w not in SIN and w.endswith("me") and w[:-2] in SIN:
            w = w[:-2]
        if w not in SIN and len(w) >= 4:
            cerca = difflib.get_close_matches(w, SIN_KEYS, n=1, cutoff=0.75)
            if cerca:
                w = cerca[0]
        mapeada = w in SIN
        w = SIN.get(w, w)
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        if not mapeada and not w.isdigit():            # raiz ligera: copiar/copia -> copi
            if len(w) >= 6 and w.endswith(("ando", "iendo")):
                w = w[:-4]
            elif len(w) >= 5 and w.endswith(("ar", "er", "ir")):
                w = w[:-2]
            elif len(w) >= 4 and w[-1] in "aeo":
                w = w[:-1]
        r = w
    _TOK_CACHE[orig] = r
    return r


def tokens(texto):
    t = sin_tildes(texto.lower())
    out = []
    for w in TOK_RE.findall(t):
        p = _palabra(w)
        if p:
            out.append(p)
    return out


def parecido(a, b):
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def cercano(w, lista, cutoff):
    """Palabra mas parecida de `lista` (prefiltra por longitud y extremos: los typos casi nunca cambian ambos)."""
    n = len(w)
    c = [v for v in lista if abs(len(v) - n) <= 2 and (v[0] == w[0] or v[-1] == w[-1])]
    r = difflib.get_close_matches(w, c, n=1, cutoff=cutoff) if c else []
    return r[0] if r else None
