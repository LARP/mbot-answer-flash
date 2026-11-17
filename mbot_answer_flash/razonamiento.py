"""Fusion de capas: indexado, decidir() y umbrales."""
import math, re, time
from time import perf_counter

from . import config as CFG
from .config import PELIGROSO, PESO_CAPA, es_peligroso, TOPE_AYUDA, UMBRAL_EJECUTAR, UMBRAL_PREGUNTAR
from .herramientas import REGISTRO, validar_comando
from .lexico import GENERICAS
from .refuerzo import decaer, fac_beta
from .texto import MARK, sin_tildes, tokens

SHUTDOWN = re.compile(r"\bshutdown\b", re.I)
VERBOS_APAGAR = {"APAGAR", "REINICIAR"}
PARTICIPIOS = ("ado", "ada", "ados", "adas", "ido", "ida", "idos", "idas")
# pregunta abierta: interrogativa (?) o empieza por qué/cuál/cuánto/dónde/cómo/cuándo/quién (con preposicion opcional: "en qué puerto...")
RE_ABIERTA = re.compile(r"^\W*(?:(?:oye|por\s+favor|porfa|dime|dame|a\s+ver|sabes|me\s+dices|podrias\s+decirme)\s+)?"
                        r"(?:(?:a|en|de|del|con|para|por|desde|hasta|sobre)\s+)?(?:que|cual|cuales|cuanto|cuanta|cuantos|cuantas|donde|como|cuando|quien|quienes)\b")


class Decision:
    def __init__(self):
        self.texto = ""; self.an = None; self.cands = []; self.accion = "ensenar"
        self.cmd = None; self.cmd_t = None; self.conf = 0.0; self.capa = "-"; self.ayuda = False
        self.ms = 0.0; self.d_info = {}; self.idx = None; self.nota = ""
        self.falta = []; self.peligroso = False
        self.rechazo = ""                                        # motivo si la validacion previa rechazo el comando (accion "rechazar")
        self.herr = None; self.hslots = {}; self.faltan = []     # herramienta interna elegida, sus slots y los ConfigField que faltan
        self.abierta = False                                     # "ensenar" y la frase es una pregunta: candidata a responder desde el indice (ver responder_pregunta)
        self.respuesta = None                                    # accion "responder": objeto con .texto/.ruta/.titulo (nunca ejecuta nada)
        self.descartado = None                                   # comando de baja confianza (< UMBRAL_PREGUNTAR) que ya NO se propone


class RazonamientoMixin:
    def _indexar(self):
        self._cache_an.clear()
        self._indexar_apps()
        self.fr, self.post, self.exact, self.exact_t, self.req = [], {}, {}, {}, []
        self.cmd_idx = {t["cmd"]: i for i, t in enumerate(self.tareas)}
        self.tpl = [bool(MARK.search(t["cmd"])) for t in self.tareas]
        df = {}
        for i, t in enumerate(self.tareas):
            lista, union = [], set()
            for j, f in enumerate(t["frases"]):
                an = self.analizar(f)
                toks = an.stok if self.tpl[i] else an.lit
                ts = frozenset(toks)
                sw = frozenset(an.slotwords) if not self.tpl[i] else frozenset()
                norm = " ".join(toks)
                lista.append((ts, sw, norm))
                union |= ts
                for w in ts:
                    self.post.setdefault(w, []).append((i, j))
                (self.exact_t if self.tpl[i] else self.exact).setdefault(norm, []).append(i)
            self.fr.append(lista)
            for w in union:
                df[w] = df.get(w, 0) + 1
            self.req.append(self._requeridos(t["cmd"]) if self.tpl[i] else ())
        self.marcos = [(i, a, o) for i, t in enumerate(self.tareas) for a, o in t.get("marco", [])]
        n = max(len(self.tareas), 1)
        self.n = n
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}
        self.vocab = [w for w in df if not w.startswith("{")]
        self.vocab_set = set(self.vocab)
        self._fix = {}
        # capa E: indice de `help`
        self.ayuda, self.ayuda_raw = [], []
        hdf = {}
        for nom, desc in self.desc.get("ayuda", []):
            ts = set(tokens(desc)) | {nom}
            self.ayuda.append((nom, desc, ts))
            self.ayuda_raw.append(sin_tildes(desc.lower()))
            for w in ts:
                hdf[w] = hdf.get(w, 0) + 1
        nh = max(len(self.ayuda), 1)
        self.hidf = {w: math.log(1 + nh / c) for w, c in hdf.items()}
        self.hmax = math.log(1 + nh)
        self.hpost = {}
        for k, (_n, _d, ts) in enumerate(self.ayuda):
            for w in ts:
                self.hpost.setdefault(w, []).append(k)
        self.hvocab = list(hdf)
        self._hfix = {}

    def _requeridos(self, cmd):
        r = set()
        for m in re.findall(r"\{([a-z_]+\d*)\}", cmd):
            r.add("{app}" if m == "app_start" else "{texto}" if m == "texto_url" else "{%s}" % m)
        return tuple(r)

    def decidir(self, texto):
        t0 = perf_counter()
        an = self.analizar(texto)
        d = Decision()
        d.texto, d.an = texto, an
        cand = {}

        def add(filled, capa, score, idx=None, cmd_t=None, ayuda=False, extra=None):
            if score <= 0:
                return
            c = cand.get(filled)
            if c is None:
                c = cand[filled] = {"cmd": filled, "cmd_t": filled, "capas": {}, "idx": None,
                                    "ayuda": ayuda, "extra": {}, "ib": -1.0}
            if score > c["capas"].get(capa, 0):
                c["capas"][capa] = score
            if idx is not None:
                c["ayuda"] = False
                if score > c["ib"]:
                    c["idx"], c["cmd_t"], c["ib"] = idx, (cmd_t or filled), score
            if extra:
                c["extra"].update(extra)

        def llenar(i):
            t = self.tareas[i]
            if self.tpl[i]:
                for r in self.req[i]:
                    if r not in an.slots:
                        return None
                return self.rellenar(t["cmd"], an.slots)
            return t["cmd"]

        # A: exacta / plantilla
        for i in self.exact.get(an.norm_lit, ()):
            add(self.tareas[i]["cmd"], "A", 1.0, i)
        if an.stok:
            for i in self.exact_t.get(an.norm_slot, ()):
                f = llenar(i)
                if f is not None:
                    add(f, "A", 0.97, i, self.tareas[i]["cmd"])
        # B / C: IDF con typos
        qs_lit = self._corregir(an.lit)
        qs_slot = qs_lit if an.stok == an.lit else self._corregir(an.stok)
        vistos = set()
        for w in set(qs_lit) | set(qs_slot):
            for ij in self.post.get(w, ()):
                vistos.add(ij)
        mejor = {}
        for i, j in vistos:
            tpl = self.tpl[i]
            qs = qs_slot if tpl else qs_lit
            ts, sw, _n = self.fr[i][j]
            comun = sum(self.peso(w) * s for w, s in qs.items() if w in ts)
            if comun <= 0:
                continue
            union = sum(self.peso(w) for w in set(qs) | ts)
            sc = comun / union if union else 0
            if not tpl and sw and an.slotwords and sw != set(an.slotwords):
                sc *= 0.4                                    # mismo molde, distinto valor (Descargas vs Documentos)
            if sc > mejor.get(i, 0):
                mejor[i] = sc
        for i, sc in mejor.items():
            f = llenar(i)
            if f is None:
                continue
            t = self.tareas[i]
            sc = min(1.0, sc + min(0.05, 0.01 * math.log1p(t["usos"])))
            add(f, "B" if self.tpl[i] else "C", sc, i, t["cmd"])
        # D: red de conceptos
        self._capa_d(an, add, llenar, d)
        # E: apps y help de Windows
        self._capa_e(an, add)
        # S: semantica (marcos accion x objeto, sitios, similitud distribucional)
        self._capa_s(an, add)
        # fusion
        ahora = time.time()
        lista = []
        esp_q = an.marco.prim is not None and an.marco.prim not in GENERICAS
        for c in cand.values():
            ws = sorted((PESO_CAPA[k] * v for k, v in c["capas"].items()), reverse=True)
            fin = ws[0] + (0.1 * ws[1] if len(ws) > 1 else 0.0)
            i = c["idx"]
            if i is not None:
                t = self.tareas[i]
                a, f = decaer(t["a"], t["f"], t["ts"], ahora)
                fin *= fac_beta(a, f) if (a or f) else 1.0
                if an.norm_lit in t["veto"] or (self.tpl[i] and an.norm_slot in t["veto"]):
                    fin *= 0.2
                if esp_q and t.get("marco") and "A" not in c["capas"] and "S" not in c["capas"]:
                    fin *= 0.6                         # la accion de la frase no es la de esta tarea (escuchar != abrir carpeta)
            else:
                tope = 0.9
                hx = c["extra"].get("H")
                if hx and REGISTRO[hx["nombre"]].peso_senal >= 0.97:      # herramienta muy especifica (@leer, @tabla...): puede ganar a una plantilla generica (abrir {ruta})
                    tope = REGISTRO[hx["nombre"]].peso_senal
                fin = min(fin, TOPE_AYUDA if c["ayuda"] else tope)
            c["raw"] = max(ws[0] + (0.1 * ws[1] if len(ws) > 1 else 0.0), 1e-9)
            c["conf"] = min(1.0, fin)
            lista.append(c)
        # nunca se propone apagar/reiniciar sin un verbo de apagar/reiniciar (o una frase aprendida exacta):
        # "info del equipo" compartia la palabra 'equipo' con "reiniciar el equipo"
        if any(SHUTDOWN.search(c["cmd"]) for c in lista) and not any(
                k in VERBOS_APAGAR and not w.endswith(PARTICIPIOS) for w, k in an.marco.via):    # "equipo apagado" (participio) no es una orden
            lista = [c for c in lista if not SHUTDOWN.search(c["cmd"]) or "A" in c["capas"]]
        # conflicto: una plantilla generica cede ante conocimiento ensenado que comparte la palabra del slot
        # ("pon musica" -> el usuario enseno 'escuchar musica', no 'abrir la carpeta Musica')
        if an.slotwords:
            sw = set(an.slotwords)
            for c in lista:
                if c["idx"] is not None and self.tpl[c["idx"]] and c["conf"] >= UMBRAL_EJECUTAR:
                    for r in lista:
                        if (r is not c and r["idx"] is not None and not self.tpl[r["idx"]] and r["conf"] >= 0.45
                                and sw & set().union(*(f[0] for f in self.fr[r["idx"]]))):
                            c["conf"] *= 0.45
                            c["extra"]["conflicto"] = r["cmd"]
                            break
        if CFG.FUSION == "rrf" and len(lista) > 1:
            self._ordenar_rrf(lista)
        else:
            lista.sort(key=lambda c: (-c["conf"], c["ayuda"], -c["capas"].get("S", 0.0)))   # empate exacto: gana el que casa el marco ("borra la CARPETA" -> rmdir, no del)
        if lista and self.personal.prefs:
            self._preferencias(an, lista)         # preferencia personal (navegador/editor/musica) -> app instalada
        d.cands = lista[:5]
        if lista:
            top = lista[0]
            d.cmd, d.cmd_t, d.conf, d.ayuda, d.idx = top["cmd"], top["cmd_t"], top["conf"], top["ayuda"], top["idx"]
            d.capa = max(top["capas"], key=lambda k: PESO_CAPA[k] * top["capas"][k])
            d.falta = list(top["extra"].get("falta", ()))
            hx = top["extra"].get("H")
            if hx:
                d.herr, d.hslots, d.faltan = hx["nombre"], hx["slots"], hx["faltan"]
            if d.conf >= UMBRAL_EJECUTAR and not d.ayuda and not d.falta:
                d.accion = "ejecutar"
            elif d.conf >= UMBRAL_PREGUNTAR:
                d.accion = "preguntar"
            d.peligroso = REGISTRO[d.herr].peligro if d.herr else es_peligroso(d.cmd)
            if d.accion != "ensenar" and not d.herr and not d.falta and "{" not in d.cmd:
                ok, motivo, _c = validar_comando(d.cmd, existe=lambda _p: True)   # barrera previa: solo reglas de proteccion (la existencia la mira _paso)
                if not ok:
                    d.rechazo, d.accion = motivo, "rechazar"
                    d.ms = (perf_counter() - t0) * 1000
                    self.ultima_decision = d
                    return d
            if d.accion == "ejecutar" and self._es_charla(an, REGISTRO[d.herr] if d.herr else None):
                d.accion = "preguntar"                 # preguntas y declaraciones sobre el usuario no ejecutan nada
            if d.peligroso and d.accion == "ejecutar":
                d.accion = "confirmar"                 # nunca se ejecuta lo destructivo sin pedir confirmacion
        if d.accion == "ensenar":
            # nunca se propone un comando con confianza < UMBRAL_PREGUNTAR (ni su hueco, herramienta o ayuda): "enseñar" arrastraba basura
            d.descartado = d.cmd
            d.cmd = d.cmd_t = None
            d.falta, d.faltan, d.herr, d.hslots, d.ayuda, d.idx, d.peligroso = [], [], None, {}, False, None, False
            # la consulta al indice NO ocurre aqui (decidir() debe seguir por debajo de 3 ms): solo se marca; ver Asistente.responder_pregunta
            d.abierta = "?" in texto or bool(RE_ABIERTA.match(sin_tildes(texto.lower())))
        d.ms = (perf_counter() - t0) * 1000
        self.ultima_decision = d
        return d

    def _ordenar_rrf(self, lista):
        """Experimento: orden por Reciprocal Rank Fusion sobre el ranking de cada capa (k = RRF_K). Los modificadores
        multiplicativos (Beta, veto, conflicto, topes) se aplican al puntaje RRF; la confianza (umbrales) no cambia."""
        k = CFG.RRF_K
        por_capa = {}
        for c in lista:
            for capa, v in c["capas"].items():
                por_capa.setdefault(capa, []).append((PESO_CAPA[capa] * v, c))
        rr = {id(c): 0.0 for c in lista}
        for items in por_capa.values():
            items.sort(key=lambda x: -x[0])
            rango, prev = 0, None
            for pos, (v, c) in enumerate(items):
                if v != prev:
                    rango, prev = pos, v
                rr[id(c)] += 1.0 / (k + rango + 1)
        lista.sort(key=lambda c: (-rr[id(c)] * c["conf"] / c["raw"], -c["conf"], c["ayuda"]))

    def _consultar(self, texto):
        return self.decidir(texto)

    # ---- compatibilidad con la v1
    def buscar(self, texto):
        d = self.decidir(texto)
        return [(c["conf"], c) for c in d.cands]
