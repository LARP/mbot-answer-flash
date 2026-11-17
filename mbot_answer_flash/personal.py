"""Memoria personal (sin LLM): hechos y preferencias del usuario, supersesion, consultas, recordatorios por reglas
y sugerencias `!hoy`. Persiste en personal.json (aparte de memoria_v2.json; no requiere migracion).

Ideas tomadas del repo talorys (implementacion propia): hechos con slot y estado activo|historico, supersesion que
nunca borra (`superseded_by`), intencion historica por regex, seleccion por IDF + recencia con tope K.

Comandos: !recuerda <texto>  !olvida <id|texto>  !yo  !recordatorios  !borrar_recordatorio N  !hoy
Frases normales: "prefiero X", "mi navegador es X", "uso X para Y", "me gusta X", "mi nombre es X", "trabajo en X",
"mi correo es X", "ya no uso X", "me mude a X", "recuerdame manana a las 9 llamar a Juan", "cual es mi navegador?"...
"""
import math, os, re, unicodedata
from datetime import datetime, timedelta

from .config import BASE, MEM_PATH, PELIGROSO, UMBRAL_PREGUNTAR
from .lexico import ACCIONES, clases_de
from .memoria import guardar_json
from .texto import STOP, sin_tildes

PERSONAL_PATH = os.path.join(BASE, "personal.json")
TOPE_K = 12               # hechos que muestra "que sabes de mi"
TOPE_K_LIBRE = 5          # consultas de texto libre
TOPE_CADENA = 50          # pasos maximos al recorrer superseded_by
GRACIA_PERDIDO = timedelta(hours=24)
SEMIVIDA_HECHO = 30.0     # dias

# ---------------------------------------------------------------- tablas de slots
SLOT_VALORES = {}                  # valor conocido -> slot
for _s, _vs in {
    "navegador": ["firefox", "chrome", "google chrome", "edge", "microsoft edge", "brave", "opera", "vivaldi", "safari", "chromium"],
    "editor": ["vscode", "vs code", "visual studio code", "code", "notepad++", "sublime", "sublime text", "vim", "nvim",
               "neovim", "emacs", "atom", "pycharm"],
    "musica": ["spotify", "vlc", "winamp", "itunes", "youtube music", "deezer", "foobar", "foobar2000", "tidal"],
}.items():
    for _x in _vs:
        SLOT_VALORES[_x] = _s

SLOT_PALABRAS = [          # (slot, palabras clave en una clave o en un "para ...")
    ("navegador", {"navegador", "browser", "navegar", "navegando", "internet"}),
    ("editor", {"editor", "programar", "programando", "codigo", "editar", "editando"}),
    ("musica", {"musica", "reproductor", "player", "escuchar", "escuchando", "canciones", "cancion"}),
    ("correo", {"correo", "email", "mail", "e-mail", "gmail"}),
    ("nombre", {"nombre", "llamo", "llamas"}),
    ("ciudad", {"ciudad", "vivo", "vivir", "vivia", "domicilio"}),
    ("trabajo", {"trabajo", "empleo", "empresa", "trabajar", "trabajaba"}),
]
ETIQUETA = {"navegador": "navegador", "editor": "editor", "musica": "reproductor de musica", "correo": "correo",
            "nombre": "nombre", "ciudad": "ciudad", "trabajo": "trabajo", "gusto": "gusto"}
ORDEN_SLOTS = ["nombre", "correo", "ciudad", "trabajo", "navegador", "editor", "musica", "gusto"]
MULTI = {"gusto"}                 # varios activos a la vez: solo se supersede con marca de cambio + solape de tokens
SLOTS_PREF = ("navegador", "editor", "musica")   # los que influyen en las acciones

RE_MARCA = re.compile(r"\b(?:ya no|deje de|dejo de|ahora|cambie a|me cambie|me pase a|me mude|vendi|desde hoy|a partir de ahora)\b")
RE_HIST = re.compile(r"\b(?:antes|solia|solias|usaba|usabas|anteriormente|que tenia|antiguamente)\b")
RE_PREFIJO = re.compile(r"^(?:ahora|desde hoy|a partir de ahora)\s+")
RE_NEG = re.compile(r"^(?:ya no|deje de|dejo de)\s+(?:(?:uso|usar|usando|tener|tengo|ir a|trabajar en|trabajo en|vivir en|vivo en|"
                    r"escuchar|escucho)\s+)?(?P<v>.+)$")
RE_EN_VEZ = re.compile(r"^(?:uso|utilizo|prefiero)\s+(?:usar\s+)?(?P<v>.+?)\s+(?:en vez de|en lugar de|y no)\s+(?P<o>.+)$")
RE_POR = re.compile(r"^(?:cambie|cambio|reemplace|sustitui)\s+(?P<o>.+?)\s+por\s+(?P<v>.+)$")
RE_NO_COMA = re.compile(r"^ya no\s+(?:uso|usar|utilizo)\s+(?P<o>[^,]+?)\s*,\s*(?:ahora\s+)?(?:uso|utilizo|prefiero)\s+(?:usar\s+)?(?P<v>.+)$")
RE_VENDI = re.compile(r"^vendi\s+(?P<v>.+)$")
RE_MI_ES = re.compile(r"^mi\s+(?P<k>[a-z0-9 ]{2,40}?)\s+(?:es|era|sera)\s+(?P<v>\S.*)$")
RE_ME_LLAMO = re.compile(r"^me llamo\s+(?P<v>\S.*)$")
RE_PREFIERO = re.compile(r"^prefiero\s+(?:usar\s+|utilizar\s+)?(?!no\b|que\b|ir\b|quedarme\b)(?P<v>.+?)(?:\s+(?:como|de|para)\s+(?P<k>.+))?$")
RE_USO_PARA = re.compile(r"^(?:uso|utilizo|suelo usar|siempre uso)\s+(?P<v>.+?)\s+para\s+(?P<k>.+)$")
RE_USO_COMO = re.compile(r"^(?:uso|utilizo)\s+(?P<v>.+?)\s+como\s+(?P<k>.+)$")
RE_USO_APP = re.compile(r"^(?:uso|utilizo)\s+(?P<v>[a-z0-9+ ]{2,30})$")
RE_GUSTA = re.compile(r"^me gustan?\s+(?!(?:que|cuando|si|como|porque|donde|mientras|aunque|cuanto|mucho|poco|nada|ver|hacer|ir)\b)"
                      r"(?![a-z]{3,}(?:ar|er|ir)\b)(?P<v>.+)$")        # "me gusta correr/cuando.../que..." no es un hecho
RE_TRABAJO = re.compile(r"^trabajo\s+(?:en|para|como|de)\s+(?P<v>.+)$")
RE_VIVO = re.compile(r"^(?:vivo en|vivo por|resido en|me mude a)\s+(?P<v>.+)$")
RE_CAMBIE = re.compile(r"^(?:me\s+)?(?:cambie|pase)\s+a\s+(?P<v>.+)$")

# consultas
RE_Q_TODO = re.compile(r"^(?:que|cuanto)\s+(?:sabes|recuerdas|conoces)\s+(?:de|sobre)\s+mi$")
RE_Q_DE_MI = re.compile(r"^(?:que|cuanto)\s+(?:sabes|recuerdas|conoces)\s+(?:de|sobre)\s+mi\s+(?P<k>.+)$")
RE_Q_ES = re.compile(r"^(?:cual|como)\s+es\s+mi\s+(?P<k>[a-z0-9 ]+)$")
RE_Q_QUE = re.compile(r"^que\s+(?P<k>[a-z]+(?:\s+de\s+[a-z]+)?)\s+(?:uso|usaba|usas|prefiero|preferia|tengo|tenia|utilizo)\b")
RE_Q_DONDE = re.compile(r"^donde\s+(?P<v>vivo|vivia|trabajo|trabajaba)\b")
RE_Q_LLAMO = re.compile(r"^como\s+me\s+llamo\b")

# recordatorios
RE_TRIG = re.compile(r"^(?:por favor\s+)?(?:recuerdame|recordame|(?:ponme|crea(?:me)?|agrega(?:me)?|anota)\s+un\s+recordatorio)\b\s*"
                     r"(?:que\b|de\b|para\b)?\s*")
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "sabados": 5, "domingo": 6, "domingos": 6}
DIAS_ABR = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
MESES = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
NUM = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
       "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "media": 0.5}
_DN = "|".join(DIAS)
_NUMS = r"\d+|" + "|".join(NUM)
RX_DIARIA = re.compile(r"\b(?:todos los dias|todas las dias|cada dia|diariamente|a diario)\b")
RX_SEM_DIA = re.compile(r"\b(?:todos los|todas los|cada|los)\s+(" + _DN + r")\b")
RX_SEMANAL = re.compile(r"\b(?:cada semana|semanalmente)\b")
RX_FRANJA = re.compile(r"\b(?:de|por|en) la (manana|tarde|noche|madrugada)\b")
RX_ESTA = re.compile(r"\besta (manana|tarde|noche)\b")
RX_CUARTO = re.compile(r"\b(?:en|dentro de)\s+(?:un\s+)?cuarto de hora\b")
RX_REL = re.compile(r"\b(?:en|dentro de)\s+(" + _NUMS + r")\s*(minutos?|mins?|horas?|hs|dias?|semanas?)\b")
RX_PASADO = re.compile(r"\bpasado manana\b")
RX_MANANA = re.compile(r"\bmanana\b")
RX_HOY = re.compile(r"\bhoy\b")
RX_DIASEM = re.compile(r"\b(?:el\s+)?(?:proximo\s+)?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b")
RX_FECHA = re.compile(r"\b(?:el\s+)?(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\b")
RX_HORA_A = re.compile(r"\ba\s+las?\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|hs|h|horas)?(?![\w:])")
RX_HORA_P = re.compile(r"\ba\s+las?\s+(" + "|".join(k for k in NUM if k not in ("media", "veinte", "treinta", "quince")) +
                       r")(?:\s+y\s+(media|cuarto))?\b")
RX_HORA_AMPM = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b")
RX_HORA_2P = re.compile(r"\b(\d{1,2}):(\d{2})\b")
RX_MEDIO = re.compile(r"\ba\s+(mediodia|medianoche)\b")


def _nfc(t):
    return unicodedata.normalize("NFC", t)


def _plano(t):
    return sin_tildes(_nfc(t)).lower()


def _iso(dt):
    return dt.isoformat(timespec="minutes")


def _desde_iso(s):
    return datetime.fromisoformat(s)


def _tokh(t):
    """Palabras de contenido de un hecho (para el solape de la supersesion y el IDF)."""
    ign = {"uso", "ahora", "ya", "deje", "dejo", "cambie", "mude", "vendi", "siempre", "suelo", "para", "como", "que", "mas",
           "utilizo", "prefiero", "tengo", "voy"}
    return {w for w in re.findall(r"[a-z0-9+@.]+", _plano(t)) if len(w) >= 3 and w not in STOP and w not in ign}


def _solape(a, b):
    """|a & b| / min(|a|, |b|): 1.0 si uno contiene al otro."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def slot_de(texto):
    """Slot a partir de palabras clave de un texto plano; None si no hay ninguna."""
    ws = set(re.findall(r"[a-z0-9\-+]+", texto))
    for slot, claves in SLOT_PALABRAS:
        if ws & claves:
            return slot
    return None


def slot_de_valor(v):
    return SLOT_VALORES.get(v.strip().lower())


# ---------------------------------------------------------------- parser temporal
def _num(s):
    return float(s) if s.replace(".", "").isdigit() else float(NUM[s])


def parsear_tiempo(p, ahora):
    """Texto plano -> (datetime|None, recurrencia|None, spans_consumidos). Regex + datetime, sin librerias externas.
    recurrencia: 'diaria' | 'semanal:N' (0 = lunes). None en el datetime = no hay expresion temporal."""
    q = p
    spans = []

    def tomar(rx):
        nonlocal q
        m = rx.search(q)
        if m:
            spans.append(m.span())
            q = q[:m.start()] + " " * (m.end() - m.start()) + q[m.end():]
        return m

    rec = dia = rel = None
    h = mi = None
    franja = None
    if tomar(RX_DIARIA):
        rec = "diaria"
    else:
        m = tomar(RX_SEM_DIA)
        if m:
            rec = "semanal:%d" % DIAS[m.group(1)]
        elif tomar(RX_SEMANAL):
            rec = "semanal:%d" % ahora.weekday()
    m = tomar(RX_FRANJA)
    if m:
        franja = m.group(1)
    m = tomar(RX_ESTA)
    if m:
        franja, dia = m.group(1), ahora.date()
    if tomar(RX_CUARTO):
        rel = timedelta(minutes=15)
    m = tomar(RX_REL) if rel is None else None
    if m:
        n = _num(m.group(1))
        u = m.group(2)
        if u.startswith(("min", "mi")):
            rel = timedelta(minutes=n)
        elif u.startswith(("hora", "hs")):
            rel = timedelta(hours=n)
        elif u.startswith("dia"):
            dia = (ahora + timedelta(days=n)).date()
        else:
            dia = (ahora + timedelta(weeks=n)).date()
    if dia is None and rel is None:
        if tomar(RX_PASADO):
            dia = (ahora + timedelta(days=2)).date()
        elif tomar(RX_MANANA):
            dia = (ahora + timedelta(days=1)).date()
        elif tomar(RX_HOY):
            dia = ahora.date()
        else:
            m = tomar(RX_FECHA)
            if m and int(m.group(1)) <= 31:
                try:
                    d = datetime(ahora.year, MESES[m.group(2)], int(m.group(1))).date()
                    if d < ahora.date():
                        d = d.replace(year=d.year + 1)
                    dia = d
                except ValueError:
                    pass
            else:
                m = tomar(RX_DIASEM)
                if m:
                    dia = ("dow", DIAS[m.group(1)])
    # hora
    ap = None
    m = tomar(RX_HORA_A)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    else:
        m = tomar(RX_HORA_P)
        if m:
            h = NUM[m.group(1)]
            mi = {"media": 30, "cuarto": 15}.get(m.group(2), 0)
        else:
            m = tomar(RX_HORA_AMPM)
            if m:
                h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
            else:
                m = tomar(RX_HORA_2P)
                if m:
                    h, mi = int(m.group(1)), int(m.group(2))
                else:
                    m = tomar(RX_MEDIO)
                    if m:
                        h, mi = (12, 0) if m.group(1) == "mediodia" else (0, 0)
    if h is not None:
        if h > 23 or mi > 59:
            return None, None, []
        if ap in ("pm", "p.m.") and h < 12:
            h += 12
        elif ap in ("am", "a.m.") and h == 12:
            h = 0
        elif ap is None:
            if franja in ("tarde", "noche") and h < 12:
                h += 12
            elif franja == "noche" and h == 12:
                h = 0
            elif franja is None and 1 <= h <= 6:
                h += 12                                     # "a las 3" sin franja: la tarde es lo comun
    elif franja and (dia is not None or rec):
        h, mi = {"manana": 9, "tarde": 16, "noche": 21, "madrugada": 6}[franja], 0
    if not (rec or dia is not None or rel is not None or h is not None):
        return None, None, []

    # ---- composicion
    if rel is not None:
        dt = (ahora + rel).replace(second=0, microsecond=0)
        return dt, rec, spans
    hh, mm = (h, mi) if h is not None else (9, 0)
    hoy = ahora.date()

    def a_dt(d):
        return datetime(d.year, d.month, d.day, hh, mm)

    if rec:
        if rec == "diaria":
            dt = a_dt(hoy)
            if dt <= ahora:
                dt += timedelta(days=1)
        else:
            dow = int(rec.split(":")[1])
            dt = a_dt(hoy + timedelta(days=(dow - ahora.weekday()) % 7))
            if dt <= ahora:
                dt += timedelta(days=7)
    elif isinstance(dia, tuple):
        dt = a_dt(hoy + timedelta(days=(dia[1] - ahora.weekday()) % 7))
        if dt <= ahora:
            dt += timedelta(days=7)
    elif dia is not None:
        dt = a_dt(dia)
        if dt <= ahora and dia == hoy:
            dt = (ahora + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) if h is None else dt
    else:
        dt = a_dt(hoy)
        if dt <= ahora:
            dt += timedelta(days=1)
    return dt, rec, spans


def siguiente(dt, rec, ahora):
    """Proxima ocurrencia > ahora de un recordatorio recurrente."""
    paso = timedelta(days=1 if rec == "diaria" else 7)
    if dt <= ahora:
        dt += paso * (int((ahora - dt) / paso) + 1)
    return dt


def _txt_rec(rec):
    return "todos los dias" if rec == "diaria" else "cada " + DIAS_ABR[int(rec.split(":")[1])]


def cuando(dt, ahora):
    d = (dt.date() - ahora.date()).days
    base = "hoy" if d == 0 else "manana" if d == 1 else "%s %02d/%02d" % (DIAS_ABR[dt.weekday()], dt.day, dt.month)
    return "%s %02d:%02d" % (base, dt.hour, dt.minute)


class Resp:
    __slots__ = ("tipo", "texto", "datos")

    def __init__(self, tipo, texto, datos=None):
        self.tipo, self.texto, self.datos = tipo, texto, datos

    def __bool__(self):
        return True


# ---------------------------------------------------------------- memoria personal
class Personal:
    def __init__(self, ruta=PERSONAL_PATH, reloj=None):
        self.ruta = ruta
        self.reloj = reloj or datetime.now
        self.hechos, self.recordatorios = [], []
        self.sig_id, self.sig_rec = 1, 1
        self.ultimos_avisos = []
        self.tareas_fn = lambda: []
        self._prefs = None
        self._cargar()

    def ahora(self):
        return self.reloj()

    # ---- persistencia
    def _cargar(self):
        import json
        if os.path.exists(self.ruta):
            try:
                with open(self.ruta, encoding="utf-8") as f:
                    d = json.load(f)
                self.hechos = d.get("hechos", [])
                self.recordatorios = d.get("recordatorios", [])
                self.sig_id = d.get("sig_id", 1)
                self.sig_rec = d.get("sig_rec", 1)
            except (OSError, ValueError):
                pass
        for h in self.hechos:
            h.setdefault("superseded_by", None); h.setdefault("usos", 0); h.setdefault("estado", "activo")
            self.sig_id = max(self.sig_id, h["id"] + 1)
        for r in self.recordatorios:
            r.setdefault("estado", "pendiente"); r.setdefault("recurrencia", None)
            self.sig_rec = max(self.sig_rec, r["id"] + 1)
        cerrados = [r for r in self.recordatorios if r["estado"] != "pendiente"]
        if len(cerrados) > 20:                                  # solo se conservan los 20 ultimos cerrados
            sobran = {r["id"] for r in cerrados[:-20]}
            self.recordatorios = [r for r in self.recordatorios if r["id"] not in sobran]
        self._sanear()

    def guardar(self):
        self._prefs = None
        guardar_json(self.ruta, {"v": 1, "sig_id": self.sig_id, "sig_rec": self.sig_rec,
                                 "hechos": self.hechos, "recordatorios": self.recordatorios})

    def _por_id(self, i):
        for h in self.hechos:
            if h["id"] == i:
                return h
        return None

    # ---- cadena de supersesion (ciclos)
    def cadena(self, id_):
        """Sigue superseded_by desde id_. Devuelve (ids, hay_ciclo); corta al repetir un id o a los 50 pasos."""
        vistos, cur = [], id_
        for _ in range(TOPE_CADENA):
            if cur is None:
                return vistos, False
            if cur in vistos:
                return vistos, True
            vistos.append(cur)
            h = self._por_id(cur)
            cur = h["superseded_by"] if h else None
        return vistos, cur is not None

    def _sanear(self):
        """Rompe ciclos heredados de un archivo corrupto (nunca borra hechos)."""
        for h in self.hechos:
            ids, ciclo = self.cadena(h["id"])
            if ciclo:
                self._por_id(ids[-1])["superseded_by"] = None

    def _forzar_ciclo(self):
        """Solo para pruebas: crea A->B->A y devuelve el id de A."""
        a, b = self.sig_id, self.sig_id + 1
        self.sig_id += 2
        ahora = _iso(self.ahora())
        for i, j in ((a, b), (b, a)):
            self.hechos.append({"id": i, "texto": "ciclo de prueba", "slot": "_ciclo", "valor": "x", "estado": "historico",
                                "superseded_by": j, "creado": ahora, "usos": 0})
        return a

    # ---- hechos
    def activos(self):
        return [h for h in self.hechos if h["estado"] == "activo"]

    def activo(self, slot):
        c = [h for h in self.hechos if h["estado"] == "activo" and h["slot"] == slot]
        return max(c, key=lambda h: h["id"]) if c else None

    def historicos(self, slot):
        return sorted((h for h in self.hechos if h["estado"] == "historico" and h["slot"] == slot), key=lambda h: h["id"])

    @property
    def prefs(self):
        """{slot: valor} de las preferencias activas que influyen en las acciones."""
        if self._prefs is None:
            self._prefs = {}
            for s in SLOTS_PREF:
                h = self.activo(s)
                if h and h["valor"]:
                    self._prefs[s] = h["valor"].strip().lower()
        return self._prefs

    def _retirar(self, viejo, nuevo_id):
        """viejo -> historico (nunca se borra). No enlaza si eso cerraria un ciclo."""
        viejo["estado"] = "historico"
        viejo["retirado"] = _iso(self.ahora())
        if nuevo_id is not None:
            ids, _ = self.cadena(nuevo_id)
            viejo["superseded_by"] = None if viejo["id"] in ids else nuevo_id

    def _agregar(self, texto, slot, valor, marca=False, negacion=False, viejo=None):
        """Inserta un hecho aplicando la supersesion. Devuelve (tipo, hecho|None)."""
        activos = self.activos()
        if not negacion and slot:
            for h in activos:
                if h["slot"] == slot and h["valor"] is not None and valor is not None and _plano(h["valor"]) == _plano(valor):
                    h["usos"] += 1
                    self.guardar()
                    return "repetido", h
        viejos = []
        if negacion:
            tv = _tokh(valor or "")
            for h in activos:
                if h["valor"] is None:
                    continue
                if (slot and h["slot"] == slot and _plano(h["valor"]) == _plano(valor)) or \
                        _solape(tv, _tokh(h["texto"]) | _tokh(h["valor"])) > 0.5:
                    viejos.append(h)
            if not viejos:
                return "nada", None
            slot = slot or viejos[0]["slot"]
            valor = None
        else:
            tn = _tokh(texto)
            for h in activos:
                if slot and h["slot"] == slot and slot not in MULTI:
                    viejos.append(h)
                elif marca and _solape(tn, _tokh(h["texto"])) > 0.5:
                    viejos.append(h)
                elif viejo and h["valor"] is not None and _plano(h["valor"]) == _plano(viejo):
                    viejos.append(h)                 # "chrome en vez de firefox": retira firefox aunque no compartan slot
        nuevo = {"id": self.sig_id, "texto": texto, "slot": slot, "valor": valor, "estado": "activo",
                 "superseded_by": None, "creado": _iso(self.ahora()), "usos": 0}
        self.sig_id += 1
        self.hechos.append(nuevo)
        for v in viejos:
            self._retirar(v, nuevo["id"])
        self.guardar()
        return ("supersede" if viejos else "hecho"), nuevo

    def _extraer(self, t, p):
        """Frase -> dict(slot, valor, marca, negacion) o None. t = original NFC, p = plano (misma longitud)."""
        if not p:
            return None
        marca = bool(RE_MARCA.search(p))
        ini = 0
        m = RE_PREFIJO.match(p)
        if m:
            ini = m.end()
        pr, tr = p[ini:], t[ini:]

        def val(m, g="v", bajo=False):
            v = tr[m.start(g):m.end(g)].strip().strip(" .!?¡¿,;")
            return v.lower() if bajo else v
        for rx in (RE_NO_COMA, RE_EN_VEZ, RE_POR):
            m = rx.match(pr)
            if m:
                v, o = val(m, bajo=True), tr[m.start("o"):m.end("o")].strip(" .!?,;").lower()
                slot = slot_de_valor(v) or slot_de_valor(o)
                return {"slot": slot, "valor": v, "marca": True, "negacion": False, "viejo": o} if v and o else None
        m = RE_NEG.match(pr) or RE_VENDI.match(pr)
        if m:
            v = val(m, bajo=True)
            return {"slot": slot_de_valor(v) or slot_de(pr), "valor": v, "marca": True, "negacion": True} if v else None
        m = RE_MI_ES.match(pr)
        if m:
            k = pr[m.start("k"):m.end("k")]
            v = val(m)
            if v.lower().startswith("que ") or not v:
                return None
            slot = slot_de(k) or ("_".join(k.split()) if len(k.split()) <= 2 else None)
            if slot in SLOTS_PREF:
                v = v.lower()
            return {"slot": slot, "valor": v, "marca": marca, "negacion": False}
        for rx, slot in ((RE_ME_LLAMO, "nombre"), (RE_TRABAJO, "trabajo"), (RE_VIVO, "ciudad"), (RE_GUSTA, "gusto")):
            m = rx.match(pr)
            if m:
                v = val(m)
                return {"slot": slot, "valor": v, "marca": marca, "negacion": False} if v else None
        for rx in (RE_USO_PARA, RE_USO_COMO):
            m = rx.match(pr)
            if m:
                v = val(m, bajo=True)
                k = pr[m.start("k"):m.end("k")]
                slot = slot_de(k) or slot_de_valor(v)
                return {"slot": slot, "valor": v, "marca": marca, "negacion": False} if v else None
        m = RE_PREFIERO.match(pr)
        if m:
            v = val(m, bajo=True)
            k = pr[m.start("k"):m.end("k")] if m.group("k") else ""
            slot = slot_de(k) or slot_de_valor(v)
            return {"slot": slot, "valor": v if slot else val(m), "marca": marca, "negacion": False} if v else None
        m = RE_CAMBIE.match(pr)
        if m:
            v = val(m, bajo=True)
            return {"slot": slot_de_valor(v), "valor": v, "marca": True, "negacion": False} if v else None
        m = RE_USO_APP.match(pr)
        if m and slot_de_valor(pr[m.start("v"):m.end("v")]):
            v = val(m, bajo=True)
            return {"slot": slot_de_valor(v), "valor": v, "marca": marca, "negacion": False}
        return None

    def _hecho(self, t, p, forzar=False):
        e = self._extraer(t, p)
        if e is None:
            if not forzar:
                return None
            e = {"slot": None, "valor": t.strip(), "marca": bool(RE_MARCA.search(p)), "negacion": False}
        tipo, h = self._agregar(t.strip(), e["slot"], e["valor"], e["marca"], e["negacion"], e.get("viejo"))
        if tipo == "nada":
            if not forzar:
                return None
            tipo, h = "hecho", None
            nuevo = {"id": self.sig_id, "texto": t.strip(), "slot": e["slot"], "valor": None, "estado": "activo",
                     "superseded_by": None, "creado": _iso(self.ahora()), "usos": 0}
            self.sig_id += 1
            self.hechos.append(nuevo)
            self.guardar()
            h = nuevo
        et = ETIQUETA.get(h["slot"] or "", h["slot"] or "dato")
        if tipo == "repetido":
            return Resp("repetido", f"Ya lo sabia: {et} = {h['valor']}.", h)
        if h["valor"] is None:
            return Resp("supersede", f"Anotado: ya no (#{h['id']}). Lo anterior queda como historico.", h)
        extra = " (el anterior queda como historico)" if tipo == "supersede" else ""
        return Resp(tipo if tipo == "supersede" else "hecho", f"Anotado #{h['id']}: {et} = {h['valor']}{extra}.", h)

    # ---- consultas
    def _seleccionar(self, qtoks, incluir_hist, K):
        docs = [(h, _tokh(h["texto"]) | _tokh(h["valor"] or "")) for h in self.hechos
                if h["estado"] == "activo" or (incluir_hist and h["estado"] == "historico" and h["slot"] != "_ciclo")]
        n = max(len(docs), 1)
        df = {}
        for _h, ts in docs:
            for w in ts:
                df[w] = df.get(w, 0) + 1
        ahora = self.ahora()
        out = []
        for h, ts in docs:
            dias = max(0.0, (ahora - _desde_iso(h["creado"])).total_seconds() / 86400)
            rec = 0.5 ** (dias / SEMIVIDA_HECHO)
            base = sum(math.log(1 + n / df[w]) for w in qtoks & ts) if qtoks else 1.0
            if base > 0:
                out.append((base * (0.5 + 0.5 * rec), h["id"], h))
        out.sort(key=lambda x: (-x[0], -x[1]))
        return [h for _s, _i, h in out[:K]]

    def _fmt_hecho(self, h):
        if h["valor"] is None:
            return h["texto"]
        if h["slot"] and not h["slot"].startswith("_"):
            return f"{ETIQUETA.get(h['slot'], h['slot'].replace('_', ' '))}: {h['valor']}"
        return h["texto"]

    def _resumen(self, hist=False):
        sel = self._seleccionar(set(), hist, TOPE_K)
        if not sel:
            return Resp("consulta", "Todavia no se nada de ti. Dime cosas como 'prefiero firefox' o '!recuerda mi nombre es Ana'.")
        pri = {s: i for i, s in enumerate(ORDEN_SLOTS)}
        sel.sort(key=lambda h: (pri.get(h["slot"], 99), -h["id"]))
        L = ["Esto es lo que se de ti:"] + [f"  - {self._fmt_hecho(h)}  (#{h['id']})" for h in sel]
        rest = len(self.activos()) - len([h for h in sel if h["estado"] == "activo"])
        if rest > 0:
            L.append(f"  (+{rest} mas)")
        pend = len(self.pendientes())
        if pend:
            L.append(f"  Recordatorios pendientes: {pend} (!recordatorios)")
        return Resp("consulta", "\n".join(L), sel)

    def _responder_slot(self, slot, hist):
        et = ETIQUETA.get(slot, slot.replace("_", " "))
        act, old = self.activo(slot), self.historicos(slot)
        if hist:
            if not old:
                return Resp("consulta", f"No tengo nada anterior sobre tu {et}." + (f" Ahora: {act['valor']}." if act and act["valor"] else ""))
            orden = []
            ids, _ = self.cadena(old[0]["id"])
            for i in ids:
                h = self._por_id(i)
                if h and h in old:
                    orden.append(h)
            orden += [h for h in old if h not in orden]
            partes = [f"{h['valor']} (hasta {h.get('retirado', '?')[:10]})" for h in orden]
            ahora = f"{act['valor']}" if act and act["valor"] else "ninguno"
            return Resp("consulta", f"Antes ({et}): " + " -> ".join(partes) + f". Ahora: {ahora}.", orden)
        if act is None:
            return Resp("consulta", f"No se cual es tu {et}. Dimelo con 'mi {et} es ...'.")
        if act["valor"] is None:
            return Resp("consulta", f"Me dijiste que ya no: «{act['texto']}».", act)
        return Resp("consulta", f"Tu {et} es {act['valor']}.", act)

    def _slot_conocido(self, k):
        """Slot de una clave de consulta si es uno que conozco (tabla o hechos guardados); si no, None."""
        s = slot_de(k)
        if s:
            return s
        c = "_".join(k.split())
        return c if any(h["slot"] == c for h in self.hechos) else None

    def _consulta(self, t, p):
        q = p.strip(" ?!¿¡.")
        if not q:
            return None
        hist = bool(RE_HIST.search(q))
        if RE_Q_TODO.match(q):
            return self._resumen(hist)
        m = RE_Q_DE_MI.match(q)
        if m:
            s = self._slot_conocido(m.group("k"))
            if s:
                return self._responder_slot(s, hist)
            sel = self._seleccionar(_tokh(m.group("k")), hist, TOPE_K_LIBRE)
            return Resp("consulta", "\n".join(f"  - {self._fmt_hecho(h)}" for h in sel) or "No se nada de eso.", sel)
        if RE_Q_LLAMO.match(q):
            return self._responder_slot("nombre", hist)
        m = RE_Q_DONDE.match(q)
        if m:
            return self._responder_slot("ciudad" if m.group("v").startswith("viv") else "trabajo", hist)
        m = RE_Q_ES.match(q) or RE_Q_QUE.match(q)
        if m:
            s = self._slot_conocido(m.group("k"))
            if s:
                return self._responder_slot(s, hist)
        return None

    # ---- olvido explicito
    def olvidar(self, arg):
        arg = arg.strip()
        if not arg:
            return Resp("error", "Uso: !olvida <id|texto> (ver !yo)")
        if arg.isdigit():
            h = self._por_id(int(arg))
            if h is None or h["estado"] != "activo":
                return Resp("error", f"No hay ningun hecho activo con id {arg}.")
            c = [h]
        else:
            pa = _plano(arg)
            ta = _tokh(arg)
            c = [h for h in self.activos() if pa in _plano(h["texto"]) or (h["valor"] and pa == _plano(h["valor"]))
                 or (ta and ta <= _tokh(h["texto"]))]
        if not c:
            return Resp("error", f"No encuentro ningun hecho activo que coincida con «{arg}».")
        if len(c) > 1:
            return Resp("error", "Varios coinciden; usa el id:\n" + "\n".join(f"  #{h['id']} {self._fmt_hecho(h)}" for h in c))
        self._retirar(c[0], None)
        self.guardar()
        return Resp("olvido", f"Hecho #{c[0]['id']} pasado a historico (no se borra): {self._fmt_hecho(c[0])}", c[0])

    # ---- recordatorios
    def pendientes(self):
        return sorted((r for r in self.recordatorios if r["estado"] == "pendiente"), key=lambda r: (r["next_run"], r["id"]))

    def _recordatorio(self, t, p):
        m = RE_TRIG.match(p)
        if not m:
            return None
        if len(p) != len(t):                       # NFC/lower cambian de longitud: se trabaja sobre el texto plano
            t = p
        pr, tr = p[m.end():], t[m.end():]
        ahora = self.ahora().replace(second=0, microsecond=0)
        dt, rec, spans = parsear_tiempo(pr, ahora)
        if dt is None:
            return None
        mask = [False] * len(tr)
        for a, b in spans:
            for i in range(a, b):
                mask[i] = True
        texto = "".join(c for c, x in zip(tr, mask) if not x)
        texto = re.sub(r"\s+", " ", texto).strip(" ,.;:-!¡?¿")
        texto = re.sub(r"^(?:que|de|para|y)\s+", "", texto).strip()
        if not texto:
            return Resp("error", "¿Que quieres que te recuerde? Ej: recuerdame manana a las 9 llamar a Juan")
        r = {"id": self.sig_rec, "texto": texto, "next_run": _iso(dt), "recurrencia": rec, "creado": _iso(ahora),
             "estado": "pendiente", "disparos": 0}
        self.sig_rec += 1
        self.recordatorios.append(r)
        self.guardar()
        rtxt = ", " + _txt_rec(rec) if rec else ""
        return Resp("recordatorio", f"Listo: te recordare «{texto}» {cuando(dt, ahora)}{rtxt}.", r)

    def avisos(self):
        """Dispara los vencidos. <24 h de retraso: 'vencido' (<2 min) o 'atrasado'; mas viejos: 'perdido' sin dispararlos.
        Los recurrentes recalculan next_run. Devuelve [{estado, texto, next_run, minutos}]."""
        ahora = self.ahora()
        out = []
        for r in self.recordatorios:
            if r["estado"] != "pendiente":
                continue
            nr = _desde_iso(r["next_run"])
            if nr > ahora:
                continue
            edad = ahora - nr
            if edad < GRACIA_PERDIDO:
                estado = "vencido" if edad < timedelta(minutes=2) else "atrasado"
                r["disparos"] = r.get("disparos", 0) + 1
            else:
                estado = "perdido"
            out.append({"estado": estado, "texto": r["texto"], "next_run": r["next_run"], "minutos": int(edad.total_seconds() // 60)})
            if r["recurrencia"]:
                r["next_run"] = _iso(siguiente(nr, r["recurrencia"], ahora))
            else:
                r["estado"] = "disparado" if estado != "perdido" else "perdido"
                r["cerrado"] = _iso(ahora)
        self.ultimos_avisos = out
        if out:
            self.guardar()
        return out

    def texto_avisos(self, avisos=None):
        L = []
        for v in (self.avisos() if avisos is None else avisos):
            if v["estado"] == "perdido":
                L.append(f"  [perdido] «{v['texto']}» (era {v['next_run'].replace('T', ' ')}; no se dispara)")
            else:
                cuando_ = "ahora" if v["estado"] == "vencido" else f"hace {v['minutos']} min" if v["minutos"] < 120 \
                    else f"hace {v['minutos'] // 60} h"
                L.append(f"  [{'RECORDATORIO' if v['estado'] == 'vencido' else 'recordatorio atrasado'}] «{v['texto']}» ({cuando_})")
        return "\n".join(L)

    def _listar_recordatorios(self):
        pen = self.pendientes()
        if not pen:
            return Resp("lista", "No hay recordatorios pendientes.")
        ahora = self.ahora()
        L = ["Recordatorios pendientes:"]
        for k, r in enumerate(pen, 1):
            rec = f" ({_txt_rec(r['recurrencia'])})" if r["recurrencia"] else ""
            L.append(f"  {k}. [{cuando(_desde_iso(r['next_run']), ahora)}] {r['texto']}{rec}")
        return Resp("lista", "\n".join(L), pen)

    def _borrar_recordatorio(self, arg):
        pen = self.pendientes()
        try:
            r = pen[int(arg) - 1]
            if int(arg) < 1:
                raise IndexError
        except (ValueError, IndexError):
            return Resp("error", "Uso: !borrar_recordatorio N (el numero de !recordatorios)")
        self.recordatorios = [x for x in self.recordatorios if x["id"] != r["id"]]
        self.guardar()
        return Resp("ok", f"Recordatorio borrado: «{r['texto']}».", r)

    # ---- !hoy
    def hoy(self):
        ahora = self.ahora()
        L, algo = [f"Hoy es {DIAS_ABR[ahora.weekday()]} {ahora.day:02d}/{ahora.month:02d}, {ahora.hour:02d}:{ahora.minute:02d}."], False
        av = self.avisos()
        if av:
            L.append("Atrasados / recien vencidos:")
            L.append(self.texto_avisos(av))
            algo = True
        hoy = [r for r in self.pendientes() if _desde_iso(r["next_run"]).date() == ahora.date()]
        if hoy:
            L.append("Recordatorios de hoy:")
            L += [f"  - {_desde_iso(r['next_run']).strftime('%H:%M')} {r['texto']}" for r in hoy]
            algo = True
        prox = [r for r in self.pendientes() if _desde_iso(r["next_run"]).date() > ahora.date()][:1]
        if prox and not hoy:
            L.append(f"Proximo recordatorio: {prox[0]['texto']} ({cuando(_desde_iso(prox[0]['next_run']), ahora)}).")
            algo = True
        hr = ahora.hour
        hab = []
        for t in self.tareas_fn():
            hh = t.get("h")
            if not hh or "{" in t["cmd"] or PELIGROSO.search(t["cmd"]):
                continue
            sc = hh.get(str(hr), 0) + 0.5 * (hh.get(str((hr - 1) % 24), 0) + hh.get(str((hr + 1) % 24), 0))
            if sc >= 2:
                hab.append((sc, t["cmd"]))
        if hab:
            hab.sort(reverse=True)
            L.append("A esta hora sueles hacer:")
            L += [f"  - {c}  (~{int(round(s))} veces cerca de las {hr:02d}h)" for s, c in hab[:3]]
            algo = True
        rec = [h for h in self.activos() if (ahora - _desde_iso(h["creado"])) <= timedelta(days=7) and h["slot"] != "_ciclo"]
        rec.sort(key=lambda h: -h["id"])
        if rec:
            L.append("Lo ultimo que me contaste:")
            L += [f"  - {self._fmt_hecho(h)}" for h in rec[:3]]
            algo = True
        if not algo:
            L.append("Nada pendiente para hoy.")
        return Resp("hoy", "\n".join(L))

    # ---- punto de entrada
    def comando(self, t):
        partes = t.split(None, 1)
        c, arg = partes[0].lower(), (partes[1] if len(partes) > 1 else "")
        if c == "!recuerda":
            if not arg.strip():
                return Resp("error", "Uso: !recuerda <texto>   (ej. !recuerda mi navegador es firefox)")
            return self._hecho(_nfc(arg), _plano(arg), forzar=True)
        if c == "!olvida":
            return self.olvidar(arg)
        if c == "!yo":
            return self._resumen(False)
        if c == "!recordatorios":
            return self._listar_recordatorios()
        if c == "!borrar_recordatorio":
            return self._borrar_recordatorio(arg.strip())
        if c == "!hoy":
            return self.hoy()
        return None

    def procesar(self, frase):
        """Frase o comando personal -> Resp, o None si no es personal (entonces decide el asistente de comandos)."""
        t = _nfc(frase).strip()
        if not t:
            return None
        if t.startswith("!"):
            return self.comando(t)
        p = _plano(t)
        if len(p) != len(t):                       # caso raro (NFC/lower cambian la longitud): se sigue con el texto plano
            t = p
        return self._recordatorio(t, p) or self._consulta(t, p) or self._hecho(t, p)


# ---------------------------------------------------------------- preferencias -> acciones
CATEGORIAS_PREF = {       # slot -> (palabras exigidas en la frase o None, marco de la tarea generica que se reemplaza)
    "navegador": (None, ["NAVEGAR", None]),                 # cualquier tarea NAVEGAR generica ("quiero navegar por internet")
    "editor": ({"editor"}, ["ESCRIBIR", "TEXTO"]),          # "redactar una carta" no implica el editor preferido
    "musica": (None, ["REPRODUCIR", "MUSICA"]),
}
PALABRAS_CATEGORIA = {"navegador", "browser", "editor", "reproductor"}
RE_INTERROG = re.compile(r"^(?:cual|cuales|que|como|donde|quien|quienes|cuando|cuanto|cuantos|cuantas|por que)\b")
RE_DECLARA = re.compile(r"^(?:mi\s+[a-z0-9 ]{2,40}?\s+(?:es|era|sera)\b|prefiero\b|uso\b|utilizo\b|me gustan?\b|me llamo\b|"
                        r"trabajo en\b|vivo en\b|ahora uso\b|ya no uso\b|cambie\b)")

ALIAS_APP = {"vscode": ["visual studio code", "code"], "vs code": ["visual studio code", "code"],
             "chrome": ["google chrome", "chrome"], "edge": ["microsoft edge", "msedge"],
             "sublime": ["sublime text", "sublime_text"], "youtube music": ["youtube music"], "word": ["word", "winword"]}


RE_PEDIDO = re.compile(r"^(?:(?:me\s+)?(?:puedes|podrias|podria|puede|pudieras|quieres)\b|me\s+\w+(?:es|as)\b)")


def es_pedido(p):
    """Pregunta amable dirigida al asistente ("puedes/podrias/me X-es" + una accion del lexico): es una orden, no charla.
    `p` ya viene sin tildes, en minusculas y sin signos."""
    if not RE_PEDIDO.match(p):
        return False
    ws = re.findall(r"[a-z0-9]+", p)
    return any(any(k in ACCIONES for k in (clases_de(w) or ())) for w in ws[1:])


class PreferenciasMixin:
    def _es_charla(self, an, herr=None):
        """Pregunta, declaracion sobre el usuario, texto roto (U+FFFD) o solo el nombre de una categoria ("mi navegador"):
        nunca debe dar accion 'ejecutar'; como mucho 'preguntar'."""
        t = an.texto
        if "\ufffd" in t:
            return True
        p = _plano(t).strip(" .!\u00bf?\u00a1")
        if herr is not None:                       # herramienta interna: las preguntas ("que hora es") son su uso normal
            return bool(RE_DECLARA.match(p)) or (("?" in t or "\u00bf" in t) and herr.escribe and not es_pedido(p))
        if ("?" in t or "\u00bf" in t) and not es_pedido(p):          # "\u00bfpuedes abrir X?" es un pedido, no charla
            return True
        if RE_INTERROG.match(p) or RE_DECLARA.match(p):
            return True
        ws = [w for w in re.findall(r"[a-z0-9]+", p) if w not in STOP]       # "mi navegador": sin verbo de accion
        return bool(ws) and set(ws) <= PALABRAS_CATEGORIA

    def _app_preferida(self, valor):
        """Comando `start` de la app descubierta (capa E) que corresponde a la preferencia; None si no existe."""
        v = sin_tildes(valor.lower()).strip()
        for c in [v] + ALIAS_APP.get(v, []):
            k = self.app_keys.get(c)
            if k is not None:
                return self.desc["apps"][k][1]
        return None

    def _preferencias(self, an, lista):
        """Si la frase pide la app generica de una categoria y el usuario tiene preferencia instalada, la antepone."""
        top = lista[0]
        if top["idx"] is None or top["ayuda"] or top["conf"] < UMBRAL_PREGUNTAR or self._es_charla(an):
            return
        palabras = None
        for slot, valor in self.personal.prefs.items():
            pal, marco = CATEGORIAS_PREF[slot]
            if palabras is None:
                palabras = set(re.findall(r"[a-z0-9]+", sin_tildes(an.texto.lower())))
            if (pal and not (palabras & pal)) or marco not in self.tareas[top["idx"]].get("marco", []):
                continue
            cmd = self._app_preferida(valor)
            if cmd is None:
                continue
            conf = min(1.0, top["conf"] + 0.1)         # preferencia explicita + palabra de la categoria: algo mas de confianza
            lista.insert(0, {"cmd": cmd, "cmd_t": cmd, "capas": {"P": conf}, "idx": None, "ayuda": False,
                             "ib": -1.0, "extra": {"P": f"preferencia {slot}={valor}"}, "conf": conf})
            return
