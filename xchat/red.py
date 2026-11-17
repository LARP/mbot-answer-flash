"""Capa D: red de conceptos con activacion propagada."""
import math

from .config import SEMIVIDA_RED
from .refuerzo import decaer
from .texto import cercano


class Red:
    DECAY = (1.0, 0.6, 0.5)      # factor por salto
    FAN = 24                     # aristas maximas por palabra
    MAX_ARISTAS = 6000
    MIN_PESO = 0.06

    def __init__(self, datos=None):
        self.ww, self.wc = {}, {}
        if datos:
            for k, v in datos.get("ww", {}).items():
                a, b = k.split("\t")
                self.ww[(a, b)] = v
            for k, v in datos.get("wc", {}).items():
                w, c = k.split("\t", 1)
                self.wc[(w, c)] = v
        self._adj()

    def _adj(self):
        self.nb, self.cm, self._walk, self._fix = {}, {}, {}, {}
        self._sim, self._inv, self._nrm = {}, None, {}
        for (a, b), e in self.ww.items():
            self.nb.setdefault(a, {})[b] = e
            self.nb.setdefault(b, {})[a] = e
        for (w, c), e in self.wc.items():
            self.cm.setdefault(w, {})[c] = e

    def datos(self):
        r3 = lambda e: [round(x, 3) if isinstance(x, float) else x for x in e]
        return {"ww": {f"{a}\t{b}": r3(e) for (a, b), e in self.ww.items()},
                "wc": {f"{w}\t{c}": r3(e) for (w, c), e in self.wc.items()}}

    def vocab(self):
        return set(self.nb) | set(self.cm)

    def corregir(self, w):
        """Palabra -> palabra conocida de la red (typos) o None."""
        if w in self.nb or w in self.cm:
            return w
        if w not in self._fix:
            self._fix[w] = cercano(w, list(self.vocab()), 0.8) if len(w) >= 4 else None
        return self._fix[w]

    def enlazar(self, palabras, cmd, ahora):
        ps = list(dict.fromkeys(p for p in palabras if not p.startswith("{")))
        for w in ps:
            e = self.wc.get((w, cmd))
            if e is None:
                e = self.wc[(w, cmd)] = [0.0, 0.0, 0.0, ahora]
                self.cm.setdefault(w, {})[cmd] = e
            e[0] += 1.0 / (1.0 + e[0])          # crece con el uso, con rendimientos decrecientes
            e[3] = ahora
        for i, a in enumerate(ps):
            for b in ps[i + 1:]:
                k = (a, b) if a < b else (b, a)
                e = self.ww.get(k)
                if e is None:
                    e = self.ww[k] = [0.0, ahora]
                    self.nb.setdefault(a, {})[b] = e
                    self.nb.setdefault(b, {})[a] = e
                e[0] += 0.5 / (1.0 + e[0])
                e[1] = ahora
        self._walk.clear(); self._fix.clear(); self._sim.clear(); self._inv = None; self._nrm.clear()

    def premiar(self, palabras, cmd, ok, ahora):
        for w in palabras:
            e = self.wc.get((w, cmd))
            if e:
                e[1], e[2] = decaer(e[1], e[2], e[3], ahora)
                e[3] = ahora
                if ok:
                    e[1] += 1
                else:
                    e[2] += 1
                    e[0] *= 0.7
        self._walk.clear(); self._sim.clear(); self._inv = None; self._nrm.clear()

    def renombrar(self, viejo, nuevo):
        for (w, c) in [k for k in self.wc if k[1] == viejo]:
            e = self.wc.pop((w, c))
            o = self.wc.get((w, nuevo))
            if o:
                o[0] = max(o[0], e[0]); o[1] += e[1]; o[2] += e[2]
            else:
                self.wc[(w, nuevo)] = e
        self._adj()

    def borrar_cmd(self, cmd):
        for k in [k for k in self.wc if k[1] == cmd]:
            del self.wc[k]
        self._adj()

    def podar(self, ahora, cmds_validos=None):
        """Olvida aristas debiles/viejas y limita el tamano del grafo."""
        f = lambda ts: 0.5 ** (max(0.0, ahora - ts) / SEMIVIDA_RED)
        for k, e in list(self.ww.items()):
            if e[0] * f(e[1]) < self.MIN_PESO:
                del self.ww[k]
        for k, e in list(self.wc.items()):
            if e[0] * f(e[3]) < self.MIN_PESO or (cmds_validos is not None and k[1] not in cmds_validos):
                del self.wc[k]
        self._adj()
        for d, claves in ((self.nb, None), (self.cm, None)):          # abanico maximo por palabra
            for w, vec in list(d.items()):
                if len(vec) > self.FAN:
                    for x in sorted(vec, key=lambda z: vec[z][0])[:len(vec) - self.FAN]:
                        self.ww.pop((w, x) if w < x else (x, w), None)
                        self.wc.pop((w, x), None)
        if len(self.ww) + len(self.wc) > self.MAX_ARISTAS:
            for dic in (self.ww, self.wc):
                for k in sorted(dic, key=lambda z: dic[z][0])[:len(dic) // 5]:
                    del dic[k]
        self._adj()

    # ---- similitud distribucional (segundo orden): dos palabras son parecidas si comparten vecinos/comandos
    def _vec(self, w):
        v = {("w", b): e[0] for b, e in self.nb.get(w, {}).items()}
        for c, e in self.cm.get(w, {}).items():
            v[("c", c)] = self._eff(e) * 1.5               # compartir el comando pesa mas que compartir un vecino
        return v

    def _norma(self, w):
        n = self._nrm.get(w)
        if n is None:
            n = self._nrm[w] = math.sqrt(sum(x * x for x in self._vec(w).values())) or 1.0
        return n

    def simil(self, w, minimo=0.45, top=3):
        """[(palabra, coseno)] de las palabras de la red mas parecidas a w por sus contextos (nunca w misma)."""
        r = self._sim.get(w)
        if r is None:
            r = []
            v = self._vec(w)
            if v:
                if self._inv is None:
                    inv = {}
                    for x in self.vocab():
                        for k, val in self._vec(x).items():
                            inv.setdefault(k, []).append((x, val))
                    self._inv = inv
                dots = {}
                for k, val in v.items():
                    for x, val2 in self._inv.get(k, ()):
                        if x != w:
                            dots[x] = dots.get(x, 0.0) + val * val2
                nw = self._norma(w)
                r = sorted(((x, d / (nw * self._norma(x))) for x, d in dots.items()), key=lambda z: -z[1])
                r = [(x, round(c, 3)) for x, c in r if c >= 0.3][:5]
            self._sim[w] = r
        return [(x, c) for x, c in r if c >= minimo][:top]

    def _eff(self, e):
        a, f = e[1], e[2]
        return e[0] * (min(1.1, 0.5 + (a + 1.0) / (a + f + 2.0)))

    def walk(self, w):
        """Propaga la activacion desde la palabra w. Devuelve {cmd: [prob, intermedio]}."""
        r = self._walk.get(w)
        if r is not None:
            return r
        out = {}
        front = {w: 1.0}
        vistos = {w}
        for hop in range(3):
            d = self.DECAY[hop]
            nxt = {}
            for nodo, a in front.items():
                ed = [(b, e[0], False) for b, e in self.nb.get(nodo, {}).items()]
                ed += [(c, self._eff(e), True) for c, e in self.cm.get(nodo, {}).items()]
                tot = sum(x[1] for x in ed)           # efecto abanico: la activacion se reparte
                if tot <= 0:
                    continue
                for b, p, es_cmd in ed:
                    x = a * d * p / tot
                    if es_cmd:
                        o = out.get(b)
                        via = nodo if nodo != w else None
                        if o is None:
                            out[b] = [x, via]
                        else:
                            if x > o[0] / 2 and via:
                                o[1] = via
                            o[0] += x
                    elif b not in vistos:
                        nxt[b] = nxt.get(b, 0.0) + x
            vistos |= set(nxt)
            front = {k: v for k, v in nxt.items() if v > 0.01}
            if not front:
                break
        self._walk[w] = out
        return out
