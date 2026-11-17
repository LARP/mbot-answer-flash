"""Capa B: slots (ruta, url, host, n, texto, carpeta, app) y analisis de frases."""
import os, re
from urllib.parse import quote_plus

from .lexico import marco_de
from .texto import MARK, SIN, STOP, cercano, sin_tildes, tokens

# ---------------------------------------------------------------- slots (B)
RE_SLOT = re.compile(r'''
 (?P<q>"[^"]*"|“[^”]*”|'[^']*')
|(?P<url>\b(?:https?|ftp)://[^\s"'<>]+)
|(?P<ruta>(?:\b[A-Za-z]:[\\/]|\\\\|~[\\/]|%[A-Za-z_]+%)[^\s"'<>|]*)
|(?P<arch>\b[\w\-]+(?:\.[\w\-]+)*\.(?:txt|docx?|xlsx?|pptx?|pdf|png|jpe?g|gif|mp3|mp4|zip|rar|csv|py|bat|log|json)\b)
|(?P<host>\b(?:\d{1,3}(?:\.\d{1,3}){3}\b|(?:[A-Za-z0-9\-]+\.)+(?:com|net|org|edu|gov|io|es|mx|ar|co|cl|pe|uy|dev|app|info|ai|tv|me|us|uk|de|fr|br|ve|ec|bo)\b))
|(?P<n>(?<![\w.])\d+(?![\w.]))
''', re.X | re.I)
RE_RUTA = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|%[A-Za-z_]+%)")
RE_URL = re.compile(r"^(?:https?|ftp)://", re.I)
FOLDER_ALIAS = {"descargas": "descargas", "downloads": "descargas", "documentos": "documentos",
                "documents": "documentos", "escritorio": "escritorio", "desktop": "escritorio",
                "imagenes": "imagenes", "pictures": "imagenes", "musica": "musica", "music": "musica",
                "videos": "videos"}
FOLDER_DIRS = {"descargas": ["Downloads", "Descargas"], "documentos": ["Documents", "Documentos"],
               "escritorio": ["Desktop", "Escritorio"], "imagenes": ["Pictures", "Imágenes", "Imagenes"],
               "musica": ["Music", "Música", "Musica"], "videos": ["Videos", "Vídeos"]}
FOLDER_REG = {"descargas": "{374DE290-123F-4565-9164-AA2B5C9A0FE8}", "documentos": "Personal",
              "escritorio": "Desktop", "imagenes": "My Pictures", "musica": "My Music", "videos": "My Video"}
CHARS_PELIGRO = set('&|<>^%"')

# rutas sin comillas con espacios ("C:\Program Files"): se extienden palabra a palabra hasta un conector o el fin de la frase
CONECTORES = set("y e o u luego despues entonces ahora por porfa pero tambien que para con si cuando mientras tras antes sin".split())
RE_EXT_FINAL = re.compile(r"\.(?:txt|docx?|xlsx?|pptx?|pdf|png|jpe?g|gif|mp3|mp4|zip|rar|csv|py|bat|log|json|md|exe|ini|dll|sys|cfg|lnk)$", re.I)
MAX_PALABRAS_RUTA = 8
PROHIBIDOS_RUTA = set("\"'<>|")


def _limpiar_ruta(p):
    """Quita puntuacion final; un ')' final solo si no tiene su '(' ("Program Files (x86)" lo conserva)."""
    p = p.rstrip(".,;:!?")
    while p.endswith(")") and p.count(")") > p.count("("):
        p = p[:-1].rstrip(".,;:!?")
    return p


def _extender_ruta(texto, ini, fin):
    """texto[ini:fin] es el primer trozo (hasta un espacio) de una ruta sin comillas. Devuelve el fin de la ruta completa:
    prueba prefijos crecientes (palabra a palabra, hasta un conector, signo de puntuacion o comilla) y elige el MAS LARGO que
    exista; si ninguno existe, el resto de la frase hasta el conector (para que el error diga la ruta entera)."""
    primero = texto[ini:fin]
    if primero[-1:] in ",;" or RE_EXT_FINAL.search(_limpiar_ruta(primero)):
        return fin
    cand, corte = [], None                              # (fin, ruta) de cada prefijo con una palabra mas; corte = hasta donde llega la frase antes del 1er conector
    for m in re.finditer(r"\s+(\S+)", texto[fin:]):
        w = m.group(1)
        pl = sin_tildes(w.lower()).strip(".,;:!?¿¡()")
        if set(w) & PROHIBIDOS_RUTA or RE_URL.match(w) or RE_RUTA.match(w) or len(cand) >= MAX_PALABRAS_RUTA:
            break
        cand.append((fin + m.end(), _limpiar_ruta(texto[ini:fin + m.end()])))
        if corte is None and pl in CONECTORES:           # "Mi Carpeta Con Espacios": un conector puede ser parte del nombre si existe asi
            corte = len(cand) - 1
        if w[-1] in ",;" and corte is None:
            corte = len(cand)
    if not cand:
        return fin
    mejor = None
    for e, r in [(fin, _limpiar_ruta(primero))] + cand:
        try:
            if os.path.exists(os.path.expandvars(os.path.expanduser(r))):
                mejor = e
        except (OSError, ValueError):
            pass
    if mejor is not None:
        return mejor                                     # la ruta mas larga que exista
    hasta = cand if corte is None else cand[:corte]       # ninguna existe: el resto de la frase hasta el conector
    return hasta[-1][0] if hasta else fin


def _sub_slots(texto, cb):
    """Como RE_SLOT.sub(cb, texto), pero las rutas sin comillas pueden llevar espacios (ver _extender_ruta)."""
    out, pos, i = [], 0, 0
    while True:
        m = RE_SLOT.search(texto, i)
        if not m:
            break
        fin = _extender_ruta(texto, m.start(), m.end()) if m.lastgroup == "ruta" else m.end()
        out.append(texto[pos:m.start()])
        out.append(cb(m.lastgroup, texto[m.start():fin]))
        pos = i = fin
    out.append(texto[pos:])
    return "".join(out)


def resolver_carpetas():
    """nombre canonico -> ruta real. expanduser primero, luego carpetas de shell del registro."""
    res = {}
    home = os.path.expanduser("~")
    for k, nombres in FOLDER_DIRS.items():
        for n in nombres:
            p = os.path.join(home, n)
            if os.path.isdir(p):
                res[k] = p
                break
        else:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as kk:
                    p = os.path.expandvars(winreg.QueryValueEx(kk, FOLDER_REG[k])[0])
                    if os.path.isdir(p):
                        res[k] = p
            except Exception:
                pass
    return res


class An:
    """Analisis de una frase: tokens literales, tokens con slots y valores de los slots."""
    __slots__ = ("texto", "lit", "slot_text", "stok", "slots", "slotwords", "norm_lit", "norm_slot", "marco")


def _seguro(v):
    return v and not (set(v) & CHARS_PELIGRO)


class AnalisisMixin:
    def analizar(self, texto):
        an = self._cache_an.get(texto)
        if an is not None:
            return an
        slots, cont = {}, {}

        def nuevo(tipo, val, lit, alts=(), **extra):
            c = cont[tipo] = cont.get(tipo, 0) + 1
            m = "{%s}" % tipo if c == 1 else "{%s%d}" % (tipo, c)
            slots[m] = dict(tipo=tipo, val=val, lit=lit, alts=list(alts), **extra)
            return m

        def cb(g, s):
            if g == "q":
                inner = s[1:-1].strip()
                if not inner:
                    return s
                if RE_URL.match(inner):
                    return nuevo("url", inner, s)
                if RE_RUTA.match(inner):
                    return nuevo("ruta", os.path.expandvars(os.path.expanduser(inner)), s)
                return nuevo("texto", inner, s)
            val = _limpiar_ruta(s) if g == "ruta" else s.rstrip(".,;:!?)")
            resto = s[len(val):]
            if g == "url":
                return nuevo("url", val, val) + resto
            if g == "ruta":
                return nuevo("ruta", os.path.expandvars(os.path.expanduser(val)), val) + resto
            if g == "arch":
                return nuevo("ruta", val, val) + resto
            if g == "host":
                return nuevo("host", val, val) + resto
            return nuevo("n", val, val) + resto

        out = _sub_slots(texto, cb)
        palabras = out.split()
        nw = [re.sub(r"[^a-z0-9{}_]", "", sin_tildes(w.lower())) for w in palabras]
        res, i, conocidas = [], 0, None
        while i < len(palabras):
            w = nw[i]
            if w in FOLDER_ALIAS and FOLDER_ALIAS[w] in self.carpetas:
                k = FOLDER_ALIAS[w]
                res.append(nuevo("carpeta", self.carpetas[k], palabras[i], alts=[k, w]))
                i += 1
                continue
            hit = None
            if self.app_keys and not w.startswith("{"):
                for n in (4, 3, 2, 1):
                    if i + n <= len(nw):
                        k = self.app_keys.get(" ".join(nw[i:i + n]))
                        if k is not None:
                            hit = (k, n)
                            break
                if hit is None and len(w) >= 6 and w not in SIN and w not in STOP and w not in self.vocab_set_safe():
                    if w not in self._appfix:
                        self._appfix[w] = cercano(w, self.app_single, 0.8)
                    if self._appfix[w]:
                        hit = (self.app_keys[self._appfix[w]], 1)
            if hit:
                nombre, cmd, exe, _s = self.desc["apps"][hit[0]]
                base = exe[:-4].lower() if exe else re.sub(r"[^a-z0-9]", "", sin_tildes(nombre.lower()))
                alts = [x for x in (base, sin_tildes(nombre.lower()), nombre.lower()) if x]
                lit = " ".join(palabras[i:i + hit[1]])
                res.append(nuevo("app", base, lit, alts=alts, start=cmd, nombre=nombre))
                i += hit[1]
                continue
            res.append(palabras[i])
            i += 1
        an = An()
        an.texto = texto
        an.slots = slots
        an.slot_text = " ".join(res)
        an.stok = tokens(an.slot_text)
        an.lit = tokens(texto) if slots else list(an.stok)
        an.slotwords = [w for s in slots.values() for w in tokens(s["lit"]) if not w.startswith("{")]
        an.norm_lit = " ".join(an.lit)
        an.norm_slot = " ".join(an.stok)
        an.marco = marco_de(an.slot_text, slots)
        if len(self._cache_an) > 512:
            self._cache_an.clear()
        self._cache_an[texto] = an
        return an

    def vocab_set_safe(self):
        return getattr(self, "vocab_set", ())

    def templatizar(self, cmd, slots):
        """Reemplaza en cmd los valores de los slots por sus marcadores."""
        cands = []
        for m, s in slots.items():
            if s["tipo"] == "app":
                cands.append((s["start"], "{app_start}" if m == "{app}" else m))
                cands += [(a, m) for a in s["alts"]]
            elif s["tipo"] == "texto":
                cands += [(s["val"], m), (quote_plus(s["val"]), "{texto_url}" if m == "{texto}" else m)]
            else:
                cands.append((s["val"], m))
        cands = sorted({c for c in cands if len(c[0]) >= 1}, key=lambda c: -len(c[0]))
        usados = set()
        for val, m in cands:
            if m in usados:
                continue
            nuevo = re.sub(r"(?<![\w{])" + re.escape(val) + r"(?![\w}])", m, cmd, count=1, flags=re.I)
            if nuevo != cmd:
                cmd = nuevo
                usados.add(m)
        return cmd

    def rellenar(self, cmd_t, slots):
        """Rellena los huecos de una plantilla. None si falta un slot o el valor es inseguro."""
        if not MARK.search(cmd_t):
            return cmd_t
        falta = []

        def rep(m):
            nom = m.group(1)
            if nom == "app_start":
                s = slots.get("{app}")
                v = s["start"] if s else None
            elif nom == "texto_url":
                s = slots.get("{texto}")
                v = quote_plus(s["val"]) if s else None
            else:
                s = slots.get("{%s}" % nom)
                v = s["val"] if s else None
                if v is not None and s["tipo"] != "app" and set(v) & CHARS_PELIGRO:
                    v = None
            if v is None:
                falta.append(nom)
                return ""
            return v
        r = re.sub(r"\{([a-z_]+\d*)\}", rep, cmd_t)
        return None if falta else r
