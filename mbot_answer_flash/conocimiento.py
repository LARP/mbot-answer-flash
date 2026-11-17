"""Busqueda de conocimiento local (bloque 3): indice FTS5 en conocimiento.db, parser de consulta y ranking RRF. Sin LLM.

Ideas del repo mindcli (parser de consulta, FTS5 + BM25, fusion RRF); implementacion propia.

Fuentes (columna `fuente` del indice):
  notas     notas.json (la herramienta @nota_agregar)          -> se reindexa sola al cambiar
  memoria   hechos de personal.json, activos e historicos      -> idem (la marca activo|historico va en `ruta`: hecho:12:historico)
  tareas    frases aprendidas -> comando ("abrir paint" -> start mspaint): responde "como hago X" / "que comando abre X"
  archivos  carpetas que el usuario agrega con !indexar        -> solo con !reindexar (recorrer 20 000 archivos no cabe en una consulta)

Indice: `docs` = fts5(titulo, texto, fuente UNINDEXED, ruta UNINDEXED, fecha UNINDEXED, tokenize='unicode61 remove_diacritics 2')
y `meta(ruta, mtime, sha1, n_trozos, ...)`. Los trozos de un archivo tienen rowids contiguos (meta.rowid0 + n_trozos) para borrarlos
sin recorrer la tabla. Reindexado incremental: si cambia el mtime se mira el sha1; si el sha1 es igual solo se actualiza el mtime.

Lectores por extension (`LECTORES`, extensible con `registrar_lector(".docx", fn)`; fn(bytes) -> str). Hoy: txt md csv json log y, desde el
bloque 4, docx xlsx pptx odt ods pdf (mbot_answer_flash/documentos.py). Un lector puede devolver un `str` con atributo `.tipo` (factura, contrato...):
se guarda en la tabla `doctipo` y se filtra con `tipo:factura` en la consulta.

Preguntas abiertas (bloque 4): `responder(texto)` contesta "a que temperatura horneo el pan" con la mejor frase del indice si el trozo
tiene buena puntuacion BM25 NORMALIZADA (bm25 del trozo / maximo posible para esa consulta, ver `_norma_bm25`). Nunca ejecuta nada.

Seguridad de la consulta: el texto del usuario NUNCA llega al MATCH tal cual. Se extraen terminos con `[^\\W_]+` (letras y digitos),
cada uno se emite entre comillas ("palabra", "raiz"*) y los unicos operadores son los fijos (AND, OR, NOT, parentesis) que
pone el programa. NEAR( * ^ : { } - " ; ' ya no existen despues de tokenizar. Los filtros (fuente, fecha, extension) y los
valores van siempre como parametros `?`; ningun valor del usuario se concatena en SQL.

Ranking: RRF (k=60) entre (1) bm25(docs, 3.0, 1.0) (titulo pesa mas), (2) cobertura del titulo (solo los trozos que tienen
un termino en el titulo: es un bonus) y (3) recencia (peso 0.2). Los empates comparten rango. Top 5, un trozo por documento.
"""
import difflib, hashlib, json, math, os, re, sqlite3, time
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .texto import STOP, sin_tildes

MAX_ARCHIVO = 5 * 1024 * 1024          # bytes por archivo
MAX_ARCHIVOS = 20000                   # archivos por carpeta
MIN_PAL, MAX_PAL = 80, 150             # palabras por trozo
RRF_K = 60
PESOS_RRF = (1.0, 1.0, 0.2)            # bm25, bonus de titulo, recencia
TOPE_CANDIDATOS = 60
OMITIR_CARPETAS = {".git", "node_modules", "appdata", "__pycache__", "$recycle.bin", ".venv", "venv", "system volume information"}
CORTE_AUTO, CORTE_SUGERIR = 0.84, 0.75  # similitud para corregir solo / solo sugerir
MARCA_A, MARCA_B = "«", "»"

SINONIMOS = [
    "contrasena clave password pass passwd", "coche auto carro automovil vehiculo", "computadora computador pc ordenador laptop portatil",
    "telefono celular movil smartphone", "dinero plata efectivo", "trabajo empleo laburo chamba", "reunion junta meeting",
    "foto fotografia imagen", "correo email mail", "viaje vacaciones", "factura recibo boleta", "medico doctor", "router modem",
    "contenedor container", "ahorro ahorros", "musica cancion", "receta recetario",
]
SIN_DE = {}
for _g in SINONIMOS:
    _ws = _g.split()
    for _w in _ws:
        SIN_DE[_w] = _ws

EXTRA_RELLENO = set("""sobre acerca info informacion datos busca buscar busco buscame encuentra encuentrame encontrar localiza consulta
dime dame dice dicen decia hago hacer puedo comando donde anote apunte guarde escribi puse deje mencione archivo archivos documento
documentos mis tus tu hay tengo tienes tenia sabes sabe muestra muestrame lista favor quiero necesito cuando algo todo toda todos
todas tiene tienen son ser fue era han ha he sus nuestro nuestra""".split())
RELLENO = set(STOP) | EXTRA_RELLENO
OPERADORES = {"and", "or", "not", "near"}

# ---------------------------------------------------------------- lectores por extension
LECTORES = {}


def registrar_lector(ext, fn):
    """Registra `fn(bytes) -> str` para una extension (".docx"...). El bloque 4 anade docx/xlsx/pptx/pdf aqui."""
    LECTORES[("." + ext.lstrip(".")).lower()] = fn


def _decodificar(datos):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            pass
    return datos.decode("latin-1", errors="replace")


def _leer_texto(datos):
    return _decodificar(datos)


def _leer_json(datos):
    txt = _decodificar(datos)
    try:
        obj = json.loads(txt)
    except (ValueError, RecursionError):
        return txt
    lineas, pila, n = [], [("", obj, 0)], 0
    while pila and n < 200000:
        k, v, prof = pila.pop()
        if prof > 30:
            continue
        if isinstance(v, dict):
            pila.extend((str(kk), vv, prof + 1) for kk, vv in reversed(list(v.items())))
        elif isinstance(v, list):
            pila.extend((k, vv, prof + 1) for vv in reversed(v))
        elif v is not None:
            s = f"{k}: {v}" if k else str(v)
            lineas.append(s)
            n += len(s)
    return "\n".join(lineas)


for _e in (".txt", ".md", ".csv", ".log"):
    registrar_lector(_e, _leer_texto)
registrar_lector(".json", _leer_json)


# ---------------------------------------------------------------- troceo
RE_TITULO = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)")


def _npal(t):
    return len(t.split())


def _partir(par, mx):
    """Parrafo -> trozos de <= mx palabras (por lineas, luego por frases, luego por palabras)."""
    if _npal(par) <= mx:
        return [par]
    lineas = par.split("\n")
    piezas = lineas if len(lineas) > 1 else re.split(r"(?<=[.!?;])\s+", par)
    if len(piezas) == 1:
        ws = par.split()
        return [" ".join(ws[i:i + 120]) for i in range(0, len(ws), 120)]
    out, cur, n = [], [], 0
    for p in piezas:
        for q in (_partir(p, mx) if _npal(p) > mx else [p]):
            w = _npal(q)
            if cur and n + w > 120:
                out.append(" ".join(cur))
                cur, n = [], 0
            cur.append(q)
            n += w
    if cur:
        out.append(" ".join(cur))
    return out


def trocear(texto, base=""):
    """texto -> [(titulo, trozo)] de 80-150 palabras (el ultimo de cada seccion puede ser menor). Corta por titulos markdown
    (el titulo pasa a ser el del trozo) y por parrafos; los parrafos largos se parten por lineas, frases o palabras."""
    secciones, titulo, parr, buf = [], "", [], []

    def cerrar_parrafo():
        if buf:
            parr.append("\n".join(buf))
            buf.clear()
    for linea in texto.splitlines():
        m = RE_TITULO.match(linea)
        if m:
            cerrar_parrafo()
            secciones.append((titulo, parr[:]))
            parr.clear()
            titulo = re.sub(r"[*_`]", "", m.group(1)).strip()
        elif not linea.strip():
            cerrar_parrafo()
        else:
            buf.append(linea.rstrip())
    cerrar_parrafo()
    secciones.append((titulo, parr[:]))
    out = []
    for tit, ps in secciones:
        if not ps:
            continue
        nombre = f"{base} › {tit}" if base and tit else (base or tit)
        piezas = [q for p in ps for q in _partir(p, MAX_PAL)]
        cur, n = [], 0
        for q in piezas:
            w = _npal(q)
            if cur and n + w > MAX_PAL:
                out.append((nombre, "\n".join(cur)))
                cur, n = [], 0
            cur.append(q)
            n += w
        if cur:
            out.append((nombre, "\n".join(cur)))
    return out


# ---------------------------------------------------------------- parser de consulta
@dataclass
class Consulta:
    original: str = ""
    terminos: list = field(default_factory=list)       # palabras de contenido (sin tildes, minusculas)
    frases: list = field(default_factory=list)         # "frase exacta"
    excluir: list = field(default_factory=list)        # -palabra / -"frase"
    ext: list = field(default_factory=list)            # ext:pdf
    fuentes: set = field(default_factory=set)          # en:notas|archivos|memoria|tareas
    desde: object = None                               # 'YYYY-MM-DD' (incluido)
    hasta: object = None                               # 'YYYY-MM-DD' (excluido)
    tipos: list = field(default_factory=list)          # tipo:factura (clasificacion de documentos)
    modo: str = ""                                     # "como": "como hago X" / "que comando abre X" (prefiere las tareas)

    def vacia(self):
        return not (self.terminos or self.frases)

    def hay_filtro(self):
        return bool(self.desde or self.ext or self.fuentes or self.tipos)


RE_TOK = re.compile(r"[^\W_]+")
RE_FRASE = re.compile(r'(-?)"([^"]*)"')
RE_EXCL = re.compile(r"(?<![\w-])-([^\W_]{2,})")
RE_EXT = re.compile(r"\bext:([a-z0-9.|,]+)")
RE_EN = re.compile(r"\ben:([a-z|,]+)")
RE_TIPO = re.compile(r"\btipo:([a-z0-9|,]+)")
RE_FUENTE_NAT = re.compile(r"\ben\s+(?:mis|mi|las|los|el|la)\s+(notas|apuntes|anotaciones|archivos|archivo|documentos|memoria|recuerdos|tareas|comandos)\b")
RE_DICE = re.compile(r"\bque\s+dice\w*\s+(?:mi|mis|el|la|los|las)\s+(archivos?|documentos?|notas?|apuntes?|textos?)\b")
FUENTE_DE = {"notas": {"notas", "archivos"}, "nota": {"notas", "archivos"}, "apuntes": {"notas", "archivos"}, "apunte": {"notas", "archivos"},
             "anotaciones": {"notas", "archivos"}, "archivos": {"archivos"}, "archivo": {"archivos"}, "documentos": {"archivos"},
             "documento": {"archivos"}, "textos": {"archivos"}, "texto": {"archivos"}, "memoria": {"memoria"}, "recuerdos": {"memoria"},
             "tareas": {"tareas"}, "comandos": {"tareas"}}
FUENTE_EN = {"notas": "notas", "nota": "notas", "memoria": "memoria", "hechos": "memoria", "personal": "memoria", "recuerdos": "memoria",
             "archivos": "archivos", "archivo": "archivos", "docs": "archivos", "documentos": "archivos", "files": "archivos",
             "tareas": "tareas", "comandos": "tareas"}
RE_HOY = re.compile(r"\b(?:(?:de|del\s+dia\s+de)\s+)?hoy\b")
RE_AYER = re.compile(r"\b(?:de\s+)?ayer\b")
RE_SEMANA = re.compile(r"\b(?:de\s+)?est[ae]\s+semana\b")
RE_SEMANA_P = re.compile(r"\b(?:de\s+|en\s+)?la\s+semana\s+pasada\b")
RE_MES_P = re.compile(r"\b(?:de|del|en|el)\s+mes\s+pasado\b|\bmes\s+pasado\b")
RE_MES = re.compile(r"\b(?:de|en)\s+est[ae]\s+mes\b|\best[ae]\s+mes\b")
RE_ANO_P = re.compile(r"\b(?:de|del|en|el)?\s*ano\s+pasado\b")
RE_ANO = re.compile(r"\b(?:en|del|de|durante)\s+(?:el\s+)?(?:ano\s+)?((?:19|20)\d\d)\b")
RE_COMO = re.compile(r"^\s*(?:como|de\s+que\s+manera)\s+(?:hago|hacer|puedo|se\s+hace|se\s+hacia|hice|lo\s+hago|haria)\b|^\s*(?:que|cual)\s+comando\b")
PREFIJOS = [re.compile(x) for x in (
    r"^\s*(?:por\s+favor|porfa|oye|hey|hola|asistente|ok|vale)\b[\s,]*",
    r"^\s*(?:busca\w*|encuentra\w*|localiza\w*|consulta\w*|revisa\w*|muestra\w*|dime|dame|ensena\w*)\b\s*",
    r"^\s*que\s+(?:se|sabes|recuerdas|tengo|tenia|hay|dice\w*|decia|anote|apunte|escribi|guarde|escribimos)\b\s*(?:yo\s+)?(?:(?:sobre|de|del|acerca\s+de|en)\b\s*)?",
    r"^\s*(?:cuanto|cuando|donde)\s+(?:se|sabes|anote|apunte|escribi|guarde|puse|deje|vi|lei|mencione|tengo\s+anotado|esta\s+anotado)\b\s*",
    r"^\s*(?:info|informacion|datos|apuntes|notas)\s+(?:sobre|de|del|acerca\s+de)\b\s*",
    r"^\s*(?:como|de\s+que\s+manera)\s+(?:hago|hacer|puedo|se\s+hace|se\s+hacia|hice|lo\s+hago|haria)\b\s*",
    r"^\s*(?:que|cual)\s+comando\s+(?:abre|usa|uso|usar|sirve\s+para|hace|ejecuta|puedo\s+usar\s+para|se\s+usa\s+para|era|es)?\b\s*",
    r"^\s*(?:sobre|acerca\s+de)\b\s*",
)]


def _ayer(d):
    return d - timedelta(days=1)


def _rango_tiempo(p, ahora):
    """Quita de `p` (texto plano) la expresion temporal y devuelve (p_sin_ella, desde, hasta); fechas 'YYYY-MM-DD'."""
    hoy = ahora.date()
    iso = lambda d: d.isoformat()
    for rx, f in (
        (RE_ANO, lambda m: (datetime(int(m.group(1)), 1, 1).date(), datetime(int(m.group(1)) + 1, 1, 1).date())),
        (RE_ANO_P, lambda m: (datetime(hoy.year - 1, 1, 1).date(), datetime(hoy.year, 1, 1).date())),
        (RE_SEMANA_P, lambda m: (hoy - timedelta(days=hoy.weekday() + 7), hoy - timedelta(days=hoy.weekday()))),
        (RE_SEMANA, lambda m: (hoy - timedelta(days=hoy.weekday()), hoy - timedelta(days=hoy.weekday()) + timedelta(days=7))),
        (RE_MES_P, lambda m: ((hoy.replace(day=1) - timedelta(days=1)).replace(day=1), hoy.replace(day=1))),
        (RE_MES, lambda m: (hoy.replace(day=1), (hoy.replace(day=28) + timedelta(days=4)).replace(day=1))),
        (RE_AYER, lambda m: (_ayer(hoy), hoy)),
        (RE_HOY, lambda m: (hoy, hoy + timedelta(days=1))),
    ):
        try:
            m = rx.search(p)
            if m:
                d, h = f(m)
                return p[:m.start()] + " " + p[m.end():], iso(d), iso(h)
        except ValueError:
            continue
    return p, None, None


def parsear_consulta(texto, ahora=None):
    """Texto libre -> Consulta (determinista). Reconoce "frase exacta", -excluir, ext:pdf, en:notas|archivos|memoria|tareas,
    tiempo (de hoy, de ayer, esta semana, la semana pasada, del mes pasado, en 2025) y quita palabras de relleno."""
    ahora = ahora or datetime.now()
    c = Consulta(original=str(texto)[:500])
    t = re.sub(r"[\x00-\x1f\x7f]", " ", c.original).replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    t = sin_tildes(t.lower()).replace("¿", " ").replace("¡", " ").replace("?", " ").replace("!", " ")
    for m in RE_FRASE.finditer(t):                                   # "frase exacta" y -"frase"
        ws = RE_TOK.findall(m.group(2))
        if ws:
            fr = " ".join(w[:40] for w in ws[:12])
            (c.excluir if m.group(1) else c.frases).append(fr)
    t = RE_FRASE.sub(" ", t).replace('"', " ")
    for m in RE_EXT.finditer(t):
        for e in re.split(r"[|,]", m.group(1)):
            e = re.sub(r"[^a-z0-9]", "", e)
            if e and e not in c.ext and len(c.ext) < 5:
                c.ext.append(e[:8])
    t = RE_EXT.sub(" ", t)
    for m in RE_TIPO.finditer(t):
        for e in re.split(r"[|,]", m.group(1)):
            if e and e not in c.tipos and len(c.tipos) < 5:
                c.tipos.append(e[:20])
    t = RE_TIPO.sub(" ", t)
    for m in RE_EN.finditer(t):
        for e in re.split(r"[|,]", m.group(1)):
            if e in FUENTE_EN:
                c.fuentes.add(FUENTE_EN[e])
    t = RE_EN.sub(" ", t)
    for m in RE_EXCL.finditer(t):
        if m.group(1) not in c.excluir and len(c.excluir) < 8:
            c.excluir.append(m.group(1)[:40])
    t = RE_EXCL.sub(" ", t)
    t = re.sub(r"[.,;:]+", " ", t)
    t, c.desde, c.hasta = _rango_tiempo(t, ahora)
    for rx in (RE_FUENTE_NAT, RE_DICE):
        m = rx.search(t)
        if m:
            c.fuentes |= FUENTE_DE.get(m.group(1), set())
            t = t[:m.start()] + " " + t[m.end():]
    if RE_COMO.match(t):
        c.modo = "como"
    for _ in range(6):                                               # prefijos de relleno ("que se sobre", "busca", "como hago")
        for rx in PREFIJOS:
            m = rx.match(t)
            if m and m.end() > 0:
                t = t[m.end():]
                break
        else:
            break
    vistos = set(w for f in c.frases for w in f.split())
    for w in RE_TOK.findall(t):
        w = w[:40]
        if (len(w) < 2 and not w.isdigit()) or w in RELLENO or w in OPERADORES or w in c.terminos:
            continue
        c.terminos.append(w)
        if len(c.terminos) >= 10:
            break
    return c


# ---------------------------------------------------------------- terminos: raiz, formas, sinonimos
_SUF = tuple(sorted("amientos amiento imientos imiento aciones uciones iciones acion ucion icion ciones cion siones sion mente adores adora ador "
                    "ables able ibles ible idades idad ando iendo aron ieron ados adas idos idas ado ada ido ida ar er ir as es os a e o s".split(),
                    key=len, reverse=True))


def raiz(w):
    """Raiz ligera (>= 4 letras) para consultas por prefijo: recetas/receta -> recet, cocinar/cocina -> cocin."""
    if len(w) < 5:
        return w
    for s in _SUF:
        if w.endswith(s) and len(w) - len(s) >= 4:
            return w[:-len(s)]
    return w


def _formas(w):
    f = {w}
    if len(w) >= 3:
        f |= {w + "s", w + "es"}
    if w.endswith("s") and len(w) > 3:
        f.add(w[:-1])
    if w.endswith("es") and len(w) > 4:
        f.add(w[:-2])
    return f


def _palabras_de(term):
    """El termino y sus sinonimos."""
    return SIN_DE.get(term, [term])


def _fragmentos(term):
    """Fragmentos MATCH (ya entre comillas) que casan con el termino o sus sinonimos: formas exactas y prefijo de la raiz."""
    fr = []
    for w in _palabras_de(term):
        fr += [f'"{x}"' for x in sorted(_formas(w))]
        r = raiz(w)
        if len(r) >= 5:
            fr.append(f'"{r}"*')
    return fr


def _grupo(term):
    return "(" + " OR ".join(_fragmentos(term)) + ")"


# ---------------------------------------------------------------- RRF
def rrf(listas, pesos=None, k=RRF_K):
    """Reciprocal Rank Fusion: score(x) = sum(peso_i / (k + rango_i(x))). Cada lista va de mejor a peor; sus elementos son ids
    o (id, clave_de_empate): los que comparten clave consecutiva comparten rango. Devuelve {id: score}."""
    pesos = pesos or [1.0] * len(listas)
    out = {}
    for lst, w in zip(listas, pesos):
        rango, prev = 0, object()
        for pos, it in enumerate(lst):
            ident, clave = it if isinstance(it, tuple) else (it, pos)
            if clave != prev:
                rango, prev = pos, clave
            out[ident] = out.get(ident, 0.0) + w / (k + rango + 1)
    return out


# ---------------------------------------------------------------- resultados
@dataclass
class Hallazgo:
    titulo: str
    fuente: str
    ruta: str
    fecha: str = ""
    snippet: str = ""
    score: float = 0.0
    rowid: int = 0

    def etiqueta(self):
        t = self.titulo
        if self.fuente == "memoria" and ":historico" in self.ruta:
            t += " (historico)"
        return t

    def linea(self):
        if self.fuente == "tareas":
            return f"[tareas] {self.titulo}  =>  {self.ruta}"
        extra = f"  {self.ruta}" if self.fuente == "archivos" else ""
        return f"[{self.fuente}] {self.etiqueta()}  ({self.fecha[:10]}){extra}"


@dataclass
class Respuesta:
    consulta: object = None
    hallazgos: list = field(default_factory=list)
    corregida: list = field(default_factory=list)        # [(escrito, corregido)]
    sugerencia: object = None                            # "¿quisiste decir ...?"
    relacionados: bool = False                           # el AND no dio nada: son trozos que comparten algun termino
    error: str = ""

    def texto(self):
        c = self.consulta
        q = " ".join((c.terminos + [f'"{x}"' for x in c.frases])) if c else ""
        if self.error:
            return self.error
        if not self.hallazgos:
            L = [f"No encontre nada sobre «{q.strip()}»."] if q.strip() or (c and c.hay_filtro()) else ["Dime que buscar (ej. 'que se sobre el wifi')."]
            if self.sugerencia:
                L.append(self.sugerencia)
            return "\n".join(L)
        L = []
        cab = f"{len(self.hallazgos)} resultado(s) para «{q.strip()}»" if q.strip() else f"{len(self.hallazgos)} resultado(s)"
        if self.relacionados:
            cab = f"No hay coincidencia exacta de todo; {len(self.hallazgos)} relacionado(s) que comparten terminos con «{q.strip()}»"
        if self.corregida:
            cab += " (corregido: " + ", ".join(f"{a} -> {b}" for a, b in self.corregida) + ")"
        L.append(cab + ":")
        for i, h in enumerate(self.hallazgos, 1):
            L.append(f"  {i}. {h.linea()}")
            if h.snippet and h.fuente != "tareas":
                L.append("     " + " ".join(h.snippet.split()))
        return "\n".join(L)


# ---------------------------------------------------------------- preguntas abiertas: responder con la mejor frase del indice
PREGUNTA_PAL = set("que cual cuales como donde cuando cuanto cuanta cuantos cuantas quien quienes porque por".split())
UMBRAL_RESPUESTA = 0.50                 # bm25 normalizado minimo del mejor trozo
COBERTURA_RESPUESTA = 0.60              # fraccion minima de terminos de la pregunta presentes en el trozo
BM25_K1, BM25_B = 1.2, 0.75
RE_FRASES = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ0-9\"'¿¡])")


@dataclass
class RespuestaDirecta:
    """Respuesta a una pregunta abierta: la(s) mejor(es) frase(s) del trozo mejor puntuado. Es solo texto: no ejecuta nada."""
    texto: str
    ruta: str = ""
    titulo: str = ""
    fuente: str = ""
    frases: list = field(default_factory=list)
    norm: float = 0.0                   # bm25 normalizado (0..1)
    cobertura: float = 0.0              # fraccion de terminos de la pregunta que aparecen en el trozo

    @property
    def datos(self):
        return {"ruta": self.ruta, "titulo": self.titulo, "fuente": self.fuente, "frases": list(self.frases),
                "norm": self.norm, "cobertura": self.cobertura}


def _casa(term, toks):
    """Cuantas palabras de `toks` (ya sin tildes) casan con el termino (o sus sinonimos): forma exacta o prefijo de la raiz."""
    pref = []
    for w in _palabras_de(term):
        r = raiz(w)
        pref.append((_formas(w), r if len(r) >= 5 else None))
    n = 0
    for t in toks:
        for fm, r in pref:
            if t in fm or (r and t.startswith(r)):
                n += 1
                break
    return n


def dividir_frases(texto):
    """Texto -> frases (sin las lineas de titulo markdown)."""
    out = []
    for linea in texto.splitlines():
        if RE_TITULO.match(linea):
            continue
        out += [x.strip() for x in RE_FRASES.split(linea) if x.strip()]
    return out


def mejores_frases(texto, terminos, n=2):
    """Las `n` frases de `texto` con mas terminos distintos de la consulta (empate: mas apariciones, luego las primeras),
    en su orden original. [] si ninguna frase contiene un termino."""
    frases = dividir_frases(texto)
    pts = []
    for i, f in enumerate(frases):
        toks = RE_TOK.findall(sin_tildes(f.lower()))
        hits = [_casa(t, toks) for t in terminos]
        dist = sum(1 for h in hits if h)
        if dist:
            pts.append((-dist, -sum(hits), i))
    pts.sort()
    return [frases[i] for _d, _s, i in sorted(pts[:n], key=lambda x: x[2])]


def _norma_bm25(tfs, idfs, dl, avgdl):
    """BM25 normalizado en [0, 1]: la puntuacion BM25 del trozo (sum idf*tf*(k1+1)/(tf+K)) dividida por la de un trozo de longitud media que
    contuviera cada termino de la consulta una vez (= sum idf). 1 = todos los terminos (ponderados por idf) en un trozo normal; un termino
    raro ausente pesa mucho, uno comun poco, y un trozo muy largo puntua menos. No depende del tamano del indice (el bm25() de FTS5
    trunca el idf a ~0 en indices pequenos y no sirve para un umbral absoluto)."""
    K = BM25_K1 * (1 - BM25_B + BM25_B * dl / max(avgdl, 1.0))
    tot = sum(idfs)
    if tot <= 0:
        return 0.0
    return min(1.0, sum(i * tf * (BM25_K1 + 1) / (tf + K) for tf, i in zip(tfs, idfs) if tf > 0) / tot)


class RespondeMixin:
    """Metodos de `Conocimiento` para preguntas abiertas y para listar archivos indexados."""

    def archivos_indexados(self, exts=None):
        """[(ruta, mtime)] de los archivos indexados (opcionalmente solo con esas extensiones), los mas recientes primero."""
        if not self.disponible:
            return []
        filas = self._con().execute("SELECT ruta, mtime FROM meta WHERE fuente = 'archivos' ORDER BY mtime DESC").fetchall()
        if exts:
            exts = {e.lower() for e in exts}
            filas = [f for f in filas if os.path.splitext(f[0])[1].lower() in exts]
        return filas

    def responder(self, texto, ahora=None, umbral=UMBRAL_RESPUESTA):
        """Pregunta abierta -> RespuestaDirecta (la mejor frase del indice) o None. Solo notas, memoria y archivos (nunca las tareas
        aprendidas: eso seria proponer un comando). Se acepta el mejor trozo si su BM25 normalizado >= `umbral` y contiene al menos
        el 60% de los terminos de la pregunta."""
        if not self.disponible:
            return None
        r = self.buscar(texto, k=8, ahora=ahora)
        if r.error or not r.hallazgos or r.consulta is None:
            return None
        arreglo = dict(r.corregida)
        terminos = [arreglo.get(t, t) for t in r.consulta.terminos if t not in PREGUNTA_PAL]
        if not terminos:
            return None
        cand = [h for h in r.hallazgos if h.fuente != "tareas"][:5]
        if not cand:
            return None
        db = self._con()
        n_total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0] or 1
        avgdl = (db.execute("SELECT AVG(length(texto)) FROM docs").fetchone()[0] or 600.0) / 6.0
        idfs = []
        for t in terminos:
            try:
                n_t = db.execute("SELECT COUNT(*) FROM docs WHERE docs MATCH ?", (_grupo(t),)).fetchone()[0]
            except sqlite3.Error:
                n_t = 0
            idfs.append(math.log(1 + (n_total - n_t + 0.5) / (n_t + 0.5)))
        mejor = None
        for h in cand:
            fila = db.execute("SELECT texto FROM docs WHERE rowid = ?", (h.rowid,)).fetchone()
            if not fila:
                continue
            toks = RE_TOK.findall(sin_tildes((fila[0] or "").lower())) + RE_TOK.findall(sin_tildes(h.titulo.lower()))
            tfs = [_casa(t, toks) for t in terminos]
            cob = sum(1 for x in tfs if x) / len(terminos)
            norm = _norma_bm25(tfs, idfs, len(toks), avgdl)
            if cob >= COBERTURA_RESPUESTA and norm >= umbral and (mejor is None or norm > mejor[0]):
                mejor = (norm, cob, h, fila[0])
        if mejor is None:
            return None
        norm, cob, h, cuerpo = mejor
        frases = mejores_frases(cuerpo, terminos, 2)
        if not frases:
            return None
        origen = os.path.basename(h.ruta) if h.fuente == "archivos" else h.etiqueta()
        sec = h.titulo.split(" › ", 1)[1] if h.fuente == "archivos" and " › " in h.titulo else ""
        cab = f"Segun {origen}" + (f" (seccion «{sec}»)" if sec else "") + ":"
        return RespuestaDirecta(cab + " " + " ".join(frases), h.ruta, h.titulo, h.fuente, frases, round(norm, 3), round(cob, 2))


# ---------------------------------------------------------------- el indice
ESQUEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(titulo, texto, fuente UNINDEXED, ruta UNINDEXED, fecha UNINDEXED,
                                                   tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS meta(ruta TEXT PRIMARY KEY, mtime REAL, sha1 TEXT, n_trozos INTEGER, rowid0 INTEGER, fuente TEXT, raiz TEXT);
CREATE TABLE IF NOT EXISTS carpetas(ruta TEXT PRIMARY KEY, agregada TEXT);
CREATE TABLE IF NOT EXISTS doctipo(ruta TEXT PRIMARY KEY, tipo TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS vocab USING fts5vocab(docs, 'row');
"""


def _iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _sha1(datos):
    return hashlib.sha1(datos).hexdigest()


def _like_ext(e):
    return "%." + e


class Conocimiento(RespondeMixin):
    def __init__(self, ruta_db, notas_fn=None, hechos_fn=None, tareas_fn=None, reloj=None):
        self.ruta = ruta_db
        self.notas_fn = notas_fn or (lambda: [])
        self.hechos_fn = hechos_fn or (lambda: [])
        self.tareas_fn = tareas_fn or (lambda: [])
        self.reloj = reloj or datetime.now
        self.max_archivo, self.max_archivos = MAX_ARCHIVO, MAX_ARCHIVOS
        self._db, self._fts, self._rowid, self._vocab = None, None, 1, None

    # ---- conexion
    def _con(self):
        if self._db is not None:
            return self._db
        for intento in (0, 1):
            try:
                db = sqlite3.connect(self.ruta, check_same_thread=False)
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                try:
                    db.executescript(ESQUEMA)
                    self._fts = True
                except sqlite3.OperationalError as e:
                    if "fts5" in str(e).lower():
                        self._fts = False
                    else:
                        raise
                self._db = db
                if self._fts:
                    self._rowid = (db.execute("SELECT COALESCE(MAX(rowid), 0) FROM docs").fetchone()[0] or 0) + 1
                return db
            except sqlite3.DatabaseError:                              # archivo corrupto: se aparta y se rehace
                try:
                    db.close()
                except Exception:
                    pass
                if intento:
                    raise
                try:
                    os.replace(self.ruta, self.ruta + ".corrupta")
                except OSError:
                    pass
        return self._db

    @property
    def disponible(self):
        self._con()
        return bool(self._fts)

    def cerrar(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    def _cambio(self):
        self._vocab = None

    # ---- escritura
    def _insertar(self, filas):
        """filas: [(titulo, texto, fuente, ruta, fecha)] con rowids contiguos. Devuelve el primer rowid."""
        r0 = self._rowid
        self._con().executemany("INSERT INTO docs(rowid, titulo, texto, fuente, ruta, fecha) VALUES (?,?,?,?,?,?)",
                                [(r0 + i,) + tuple(f) for i, f in enumerate(filas)])
        self._rowid += len(filas)
        return r0

    def _borrar_meta(self, ruta):
        db = self._con()
        m = db.execute("SELECT rowid0, n_trozos FROM meta WHERE ruta = ?", (ruta,)).fetchone()
        if m:
            if m[1]:
                db.execute("DELETE FROM docs WHERE rowid BETWEEN ? AND ?", (m[0], m[0] + m[1] - 1))
            db.execute("DELETE FROM meta WHERE ruta = ?", (ruta,))
        db.execute("DELETE FROM doctipo WHERE ruta = ?", (ruta,))
        return bool(m)

    def _poner(self, ruta, mtime, sha, filas, fuente, raiz_):
        self._borrar_meta(ruta)
        r0 = self._insertar(filas) if filas else 0
        self._con().execute("INSERT INTO meta(ruta, mtime, sha1, n_trozos, rowid0, fuente, raiz) VALUES (?,?,?,?,?,?,?)",
                            (ruta, mtime, sha, len(filas), r0, fuente, raiz_))
        self._cambio()

    # ---- fuentes internas: notas, memoria, tareas (se reindexan solas cuando cambian)
    def _filas_notas(self, datos):
        return [(f"Nota {i}", n["texto"], "notas", f"nota:{i}", n.get("ts") or "") for i, n in enumerate(datos, 1) if n.get("texto")]

    def _filas_memoria(self, datos):
        out = []
        for h in datos:
            if h.get("slot") == "_ciclo":
                continue
            txt = h.get("texto") or ""
            v = h.get("valor")
            if v and sin_tildes(str(v).lower()) not in sin_tildes(txt.lower()):
                txt += f" {v}"
            out.append((h.get("slot") or "dato", txt, "memoria", f"hecho:{h['id']}:{'historico' if h.get('estado') == 'historico' else 'activo'}",
                        h.get("creado") or ""))
        return out

    def _filas_tareas(self, datos):
        out = []
        for t in datos:
            fr = [re.sub(r"\s+", " ", f) for f in t["frases"]]
            if not fr:
                continue
            out.append((fr[0], " | ".join(fr) + " => " + t["cmd"], "tareas", t["cmd"], _iso(t["ts"]) if t.get("ts") else ""))
        return out

    def _sync_internas(self):
        """Compara una huella (sha1) de cada fuente interna y reindexa solo la que cambio."""
        sincros = (("@notas", lambda: [(n.get("texto"), n.get("ts")) for n in self.notas_fn()], self.notas_fn, self._filas_notas),
                   ("@memoria", lambda: [(h.get("id"), h.get("texto"), h.get("valor"), h.get("estado"), h.get("creado"), h.get("slot")) for h in self.hechos_fn()],
                    self.hechos_fn, self._filas_memoria),
                   ("@tareas", lambda: [(t["cmd"], t["frases"]) for t in self.tareas_fn()], self.tareas_fn, self._filas_tareas))
        db = self._con()
        n = 0
        for clave, huella_fn, datos_fn, filas_fn in sincros:
            sig = _sha1(json.dumps(huella_fn(), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
            m = db.execute("SELECT sha1 FROM meta WHERE ruta = ?", (clave,)).fetchone()
            if m and m[0] == sig:
                continue
            with db:
                self._poner(clave, time.time(), sig, filas_fn(datos_fn()), clave[1:], None)
            n += 1
        return n

    # ---- carpetas
    def _validar_carpeta(self, ruta):
        """(ok, real, motivo): una carpeta que exista y no sea la raiz de un disco ni una ruta de sistema."""
        v = (ruta or "").strip().strip('"')
        if not v or "\0" in v:
            return False, None, "Rechazado: ruta vacia"
        real = os.path.realpath(os.path.expandvars(os.path.expanduser(v)))
        if not os.path.isdir(real):
            return False, None, f"No existe la carpeta: {real}"
        if os.path.splitdrive(real)[1] in ("", "\\", "/"):
            return False, None, "Rechazado: no se indexa la raiz de un disco"
        from .herramientas import _rutas_sistema
        n = os.path.normcase(real)
        for p in _rutas_sistema():
            if n == p or n.startswith(p + os.sep):
                return False, None, f"Rechazado: ruta de sistema protegida ({real})"
        return True, real, ""

    def _recorrer(self, raiz_):
        """Genera (ruta, mtime, size) de los archivos con lector, sin entrar en carpetas omitidas ni en enlaces; cuenta los omitidos."""
        pila, n, self._omitidos, self._tope = [raiz_], 0, 0, False
        while pila:
            d = pila.pop()
            try:
                with os.scandir(d) as it:
                    ents = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            for e in ents:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                            continue
                        if e.name.lower() not in OMITIR_CARPETAS and not e.name.startswith("."):
                            pila.append(e.path)
                    elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in LECTORES:
                        st = e.stat(follow_symlinks=False)
                        if st.st_size > self.max_archivo:
                            self._omitidos += 1
                            continue
                        if n >= self.max_archivos:
                            self._tope = True
                            return
                        n += 1
                        yield e.path, st.st_mtime, st.st_size
                except OSError:
                    self._omitidos += 1

    def _indexar_raiz(self, raiz_, st):
        """Reindexa solo lo que cambio dentro de `raiz_` (mtime -> sha1) y poda lo que ya no existe."""
        db = self._con()
        previos = {r[0]: (r[1], r[2]) for r in db.execute("SELECT ruta, mtime, sha1 FROM meta WHERE raiz = ?", (raiz_,))}
        vistos = set()
        with db:
            for ruta, mtime, _sz in self._recorrer(raiz_):
                vistos.add(ruta)
                prev = previos.get(ruta)
                if prev is not None and prev[0] == mtime:
                    st["sin_cambios"] += 1
                    continue
                try:
                    with open(ruta, "rb") as f:
                        datos = f.read(self.max_archivo + 1)
                except OSError:
                    st["omitidos"] += 1
                    continue
                sha = _sha1(datos)
                if prev is not None and prev[1] == sha:                   # solo cambio la fecha: no se vuelve a trocear
                    db.execute("UPDATE meta SET mtime = ? WHERE ruta = ?", (mtime, ruta))
                    st["tocados"] += 1
                    continue
                try:
                    txt = LECTORES[os.path.splitext(ruta)[1].lower()](datos)
                except Exception:
                    st["omitidos"] += 1
                    continue
                base = re.sub(r"[_\-.]+", " ", os.path.splitext(os.path.basename(ruta))[0]).strip()
                fecha = _iso(mtime)
                filas = [(t, x, "archivos", ruta, fecha) for t, x in trocear(txt, base)]
                self._poner(ruta, mtime, sha, filas, "archivos", raiz_)
                tipo = getattr(txt, "tipo", None)                            # clasificacion del lector de documentos (factura, contrato...)
                if tipo:
                    db.execute("INSERT OR REPLACE INTO doctipo(ruta, tipo) VALUES (?, ?)", (ruta, str(tipo)[:20]))
                st["nuevos" if prev is None else "modificados"] += 1
            for ruta in set(previos) - vistos:                            # poda: el archivo ya no existe (o salio de los topes)
                self._borrar_meta(ruta)
                st["borrados"] += 1
        st["omitidos"] += self._omitidos
        st["tope"] = st["tope"] or self._tope
        self._cambio()

    def _stats(self):
        return {"nuevos": 0, "modificados": 0, "tocados": 0, "borrados": 0, "sin_cambios": 0, "omitidos": 0, "tope": False}

    def _contar(self, raiz_):
        r = self._con().execute("SELECT COUNT(*), COALESCE(SUM(n_trozos), 0) FROM meta WHERE raiz = ?", (raiz_,)).fetchone()
        return r[0], r[1]

    def indexar_carpeta(self, ruta):
        """!indexar <carpeta>: la registra y la indexa. -> stats (+ archivos, trozos). Lanza ValueError si se rechaza."""
        ok, real, motivo = self._validar_carpeta(ruta)
        if not ok:
            raise ValueError(motivo)
        if not self.disponible:
            raise ValueError("Este SQLite no tiene FTS5")
        self._con().execute("INSERT OR IGNORE INTO carpetas(ruta, agregada) VALUES (?, ?)", (real, self.reloj().isoformat(timespec="seconds")))
        self._con().commit()
        st = self._stats()
        self._indexar_raiz(real, st)
        st["archivos"], st["trozos"] = self._contar(real)
        return st

    def reindexar(self):
        """!reindexar: solo cambios en todas las carpetas registradas (y las fuentes internas)."""
        st = self._stats()
        if not self.disponible:
            return st
        st["internas"] = self._sync_internas()
        for (c,) in self._con().execute("SELECT ruta FROM carpetas ORDER BY ruta").fetchall():
            if os.path.isdir(c):
                self._indexar_raiz(c, st)
            else:                                                         # la carpeta desaparecio: se poda todo lo suyo
                with self._db:
                    for (r,) in self._db.execute("SELECT ruta FROM meta WHERE raiz = ?", (c,)).fetchall():
                        self._borrar_meta(r)
                        st["borrados"] += 1
                self._cambio()
        return st

    def desindexar(self, ruta):
        """!desindexar <carpeta>: borra sus trozos, su meta y su registro. -> numero de archivos quitados (None si no estaba registrada)."""
        real = os.path.realpath(os.path.expandvars(os.path.expanduser((ruta or "").strip().strip('"'))))
        db = self._con()
        if not db.execute("SELECT 1 FROM carpetas WHERE ruta = ?", (real,)).fetchone():
            return None
        n = 0
        with db:
            for (r,) in db.execute("SELECT ruta FROM meta WHERE raiz = ?", (real,)).fetchall():
                self._borrar_meta(r)
                n += 1
            db.execute("DELETE FROM carpetas WHERE ruta = ?", (real,))
        self._cambio()
        return n

    def fuentes(self):
        """[(nombre, archivos, trozos, detalle)]: las internas y cada carpeta."""
        if not self.disponible:
            return []
        self._sync_internas()
        db = self._con()
        out = []
        for clave in ("@notas", "@memoria", "@tareas"):
            r = db.execute("SELECT n_trozos FROM meta WHERE ruta = ?", (clave,)).fetchone()
            det = ""
            if clave == "@memoria":
                h = db.execute("SELECT COUNT(*) FROM docs WHERE fuente = 'memoria' AND ruta LIKE '%:historico'").fetchone()[0]
                det = f"{(r[0] if r else 0) - h} activos, {h} historicos"
            out.append((clave[1:], None, r[0] if r else 0, det))
        for (c,) in db.execute("SELECT ruta FROM carpetas ORDER BY ruta").fetchall():
            a, t = self._contar(c)
            out.append((c, a, t, "" if os.path.isdir(c) else "(la carpeta ya no existe: !reindexar la poda)"))
        return out

    def texto_fuentes(self):
        if not self.disponible:
            return "  Este SQLite no tiene FTS5: el buscador de conocimiento no esta disponible."
        L = [f"  Fuentes de conocimiento ({os.path.basename(self.ruta)}):"]
        for nom, a, t, det in self.fuentes():
            L.append(f"   {nom:<10} " + (f"{a} archivos, " if a is not None else "") + f"{t} trozos" + (f"  {det}" if det else ""))
        L.append("  !indexar <carpeta>   !reindexar   !desindexar <carpeta>")
        return "\n".join(L)

    # ---- vocabulario del indice (para typos y sugerencias)
    def _vocabulario(self):
        if self._vocab is None:
            ts = sorted(r[0] for r in self._con().execute("SELECT term FROM vocab"))
            self._vocab = (ts, set(ts))
        return self._vocab

    def _conocido(self, term):
        ts, st = self._vocabulario()
        for w in _palabras_de(term):
            if st & _formas(w):
                return True
            r = raiz(w)
            if len(r) >= 5:
                i = bisect_left(ts, r)
                if i < len(ts) and ts[i].startswith(r):
                    return True
        return False

    def _cerca(self, w, corte):
        ts, _st = self._vocabulario()
        n = len(w)
        c = [v for v in ts if abs(len(v) - n) <= max(2, n // 3) and (v[0] == w[0] or v[-1] == w[-1])]
        r = difflib.get_close_matches(w, c, n=1, cutoff=corte) if c else []
        return r[0] if r else None

    # ---- consulta
    def match_de(self, c, terminos=None, modo="and"):
        """MATCH seguro de FTS5 para la Consulta `c` (None si no hay nada positivo que buscar)."""
        terminos = c.terminos if terminos is None else terminos
        grupos = [_grupo(t) for t in terminos] + [f'"{f}"' for f in c.frases]
        if not grupos:
            return None
        m = (" OR " if modo == "or" else " AND ").join(grupos)
        if c.excluir:
            ex = [f'"{e}"' if " " in e else _grupo(e) for e in c.excluir]
            m = f"(({m}) NOT ({' OR '.join(ex)}))"
        return m

    def _filtros(self, c, fuentes):
        sql, par = [], []
        if fuentes:
            fs = sorted(fuentes)
            sql.append("fuente IN (%s)" % ",".join("?" * len(fs)))
            par += fs
        if c.desde:
            sql.append("fecha >= ? AND fecha < ?")
            par += [c.desde, c.hasta]
        if c.ext:
            sql.append("fuente = 'archivos' AND (%s)" % " OR ".join("lower(ruta) LIKE ?" for _ in c.ext))
            par += [_like_ext(e) for e in c.ext]
        if c.tipos:
            sql.append("fuente = 'archivos' AND ruta IN (SELECT ruta FROM doctipo WHERE tipo IN (%s))" % ",".join("?" * len(c.tipos)))
            par += list(c.tipos)
        return (" AND " + " AND ".join(sql)) if sql else "", par

    def _consultar(self, match, c, fuentes):
        filtro, par = self._filtros(c, fuentes)
        return self._con().execute(
            "SELECT rowid, titulo, fuente, ruta, fecha, bm25(docs, 3.0, 1.0) FROM docs WHERE docs MATCH ?" + filtro +
            " ORDER BY bm25(docs, 3.0, 1.0) LIMIT ?", [match] + par + [TOPE_CANDIDATOS]).fetchall()

    def _cobertura_titulo(self, titulo, grupos):
        """Fraccion de terminos de la consulta presentes en el titulo (palabra exacta o prefijo de la raiz)."""
        toks = RE_TOK.findall(sin_tildes(titulo.lower()))
        if not grupos or not toks:
            return 0.0
        conj = set(toks)
        hit = 0
        for t in grupos:
            for w in _palabras_de(t):
                r = raiz(w)
                if conj & _formas(w) or (len(r) >= 5 and any(x.startswith(r) for x in toks)):
                    hit += 1
                    break
        return hit / len(grupos)

    def _ranking(self, filas, c, terminos, k):
        if not filas:
            return []
        bm = {r[0]: round(r[5], 9) for r in filas}
        l1 = [(r[0], bm[r[0]]) for r in sorted(filas, key=lambda r: (bm[r[0]], r[0]))]
        cov = {r[0]: self._cobertura_titulo(r[1], terminos) for r in filas}
        l2 = [(i, cov[i]) for i in sorted((i for i in cov if cov[i] > 0), key=lambda i: (-cov[i], bm[i], i))]
        l3 = [(r[0], (r[4] or "")[:10]) for r in sorted(filas, key=lambda r: r[4] or "", reverse=True)]
        sc = rrf([l1, l2, l3], PESOS_RRF)
        vistos, out = set(), []
        for r in sorted(filas, key=lambda r: (-sc[r[0]], bm[r[0]], r[0])):
            if r[3] in vistos:
                continue
            vistos.add(r[3])
            out.append(Hallazgo(r[1], r[2], r[3], r[4] or "", "", sc[r[0]], r[0]))
            if len(out) >= k:
                break
        return out

    def _snippets(self, hs, match, c, fuentes):
        if not hs:
            return
        ids = [h.rowid for h in hs]
        marca = ",".join("?" * len(ids))
        if match:
            filas = self._con().execute(f"SELECT rowid, snippet(docs, 1, ?, ?, '…', 24) FROM docs WHERE docs MATCH ? AND rowid IN ({marca})",
                                        [MARCA_A, MARCA_B, match] + ids).fetchall()
        else:
            filas = self._con().execute(f"SELECT rowid, substr(texto, 1, 160) FROM docs WHERE rowid IN ({marca})", ids).fetchall()
        sn = dict(filas)
        for h in hs:
            h.snippet = sn.get(h.rowid, "") or ""

    def _recientes(self, c, k):
        filtro, par = self._filtros(c, c.fuentes)
        filas = self._con().execute("SELECT rowid, titulo, fuente, ruta, fecha, 0 FROM docs WHERE 1=1" + filtro +
                                    " ORDER BY fecha DESC LIMIT 200", par).fetchall()
        vistos, out = set(), []
        for r in filas:
            if r[3] in vistos:
                continue
            vistos.add(r[3])
            out.append(Hallazgo(r[1], r[2], r[3], r[4] or "", "", 0.0, r[0]))
            if len(out) >= k:
                break
        self._snippets(out, None, c, None)
        return out

    def buscar(self, texto, k=5, ahora=None):
        """Busca en el conocimiento. Nunca lanza por culpa del texto. -> Respuesta."""
        c = parsear_consulta(texto, ahora or self.reloj())
        r = Respuesta(consulta=c)
        try:
            if not self.disponible:
                r.error = "Este SQLite no tiene FTS5: el buscador de conocimiento no esta disponible."
                return r
            self._sync_internas()
            if c.vacia():
                if c.hay_filtro() and not c.excluir:
                    r.hallazgos = self._recientes(c, k)
                return r
            terminos, sugerir = [], []
            for t in c.terminos:                                          # typos: se corrigen con el vocabulario del indice
                if self._conocido(t):
                    terminos.append(t)
                    continue
                cor = self._cerca(t, CORTE_AUTO) if len(t) >= 5 else None
                if cor:
                    terminos.append(cor)
                    r.corregida.append((t, cor))
                    continue
                terminos.append(t)
                sug = self._cerca(t, CORTE_SUGERIR) if len(t) >= 4 else None
                if sug:
                    sugerir.append((t, sug))
            etapas = [("and", c.fuentes)]
            if c.modo == "como" and not c.fuentes:
                etapas.insert(0, ("and", {"tareas"}))
            if len(terminos) > 1:
                etapas.append(("or", c.fuentes))
            filas, match, fu = [], None, None
            for modo, fuentes in etapas:
                match = self.match_de(c, terminos, modo)
                filas = self._consultar(match, c, fuentes) if match else []
                if filas:
                    fu = fuentes
                    r.relacionados = modo == "or"
                    break
            if filas:
                r.hallazgos = self._ranking(filas, c, terminos, k)
                self._snippets(r.hallazgos, match, c, fu)
            elif sugerir:
                q = " ".join(dict(sugerir).get(t, t) for t in c.terminos)
                r.sugerencia = f"¿Quisiste decir «{q}»?"
        except sqlite3.Error as e:                                        # una consulta rara nunca tumba el asistente
            r.hallazgos, r.error = [], f"No pude buscar ({type(e).__name__})."
        return r
