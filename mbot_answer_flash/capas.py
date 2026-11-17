"""Capas D, E y S: cada una aporta candidatos a la fusion."""
import math, re
from urllib.parse import quote_plus

from .config import TOPE_AYUDA
from .herramientas import extraer_slots, formato_cmd, plano_alineado, puntuar_herr, resolver_slots
from .lexico import ACCIONES, APP_EXE, GENERICAS, clases_de, puntuar_marco
from .slots import CHARS_PELIGRO
from .texto import STOP, _palabra, cercano, parecido, sin_tildes


_CONTORNO = " \t\n¿?¡!.,;:"


# Busqueda en Google sin comillas: "busca recetas de pan en google", "buscame en google como hacer pan", "googlea precio del dolar".
# Es una senal propia de la capa S (la plantilla 'buscar {texto} en google' solo rellena su hueco con texto entre comillas).
_GV = r"(?:busca\w*|googlea\w*|googlee\w*)"
_RX_GOOGLE = (re.compile(r"^(?:por\s+favor\s+|porfa\s+)?" + _GV + r"\s+(?:me\s+)?en\s+google\s+(?:(?:sobre|acerca\s+de)\s+)?(?P<q>.+)$"),
              re.compile(r"^(?:por\s+favor\s+|porfa\s+)?" + _GV + r"\s+(?:me\s+)?(?P<q>.+?)\s+en\s+google$"),
              re.compile(r"^(?:por\s+favor\s+|porfa\s+)?googlea\w*\s+(?P<q>.+)$"))
_TPL_GOOGLE = 'start "" "https://www.google.com/search?q={texto_url}"'
_CORTA_GOOGLE = re.compile(r"[;]|\b(?:y\s+(?:luego|despues|tambien))\b")


class CapasMixin:
    def peso(self, w):
        return self.idf.get(w, math.log(1 + self.n))

    def _corregir(self, toks):
        qs = {}
        for w in toks:
            if w in self.idf:
                qs[w] = 1.0
            elif w.startswith("{"):
                qs[w] = 0.0
            else:
                if w not in self._fix:
                    c = cercano(w, self.vocab, 0.75)
                    self._fix[w] = (c, parecido(w, c)) if c else None
                f = self._fix[w]
                if f:
                    qs[f[0]] = max(qs.get(f[0], 0), f[1])
                else:
                    qs[w] = 0.0
        return qs

    def _capa_d(self, an, add, llenar, d):
        if not self.red.wc:
            return
        info = {}
        for modo, toks in (("lit", an.lit), ("slot", an.stok)):
            if modo == "slot" and an.stok == an.lit:
                continue
            ps = []
            for w in toks:
                if w.startswith("{"):
                    continue
                w2 = self.red.corregir(w)
                ps.append((w2, w))
            if not ps:
                continue
            tot = sum(self.peso(w) for _w2, w in ps)
            acum, contrib = {}, {}
            for w2, w in ps:
                if w2 is None:
                    continue
                for cmd, (p, via) in self.red.walk(w2).items():
                    i = self.cmd_idx.get(cmd)
                    if i is None or (self.tpl[i] != (modo == "slot")):
                        continue
                    acum[cmd] = acum.get(cmd, 0) + self.peso(w) * p
                    contrib.setdefault(cmd, []).append((w, round(p, 3), via))
            for cmd, s in acum.items():
                i = self.cmd_idx[cmd]
                f = llenar(i)
                if f is None:
                    continue
                add(f, "D", s / tot, i, cmd, extra={"D": contrib[cmd]})

    # ---- S: semantica
    def _app_libre(self, m):
        """Nombre de proceso suelto de 'mata el proceso notepad' (solo con la palabra proceso/programa)."""
        c = [w for w, cl in m.cont if cl is None or not ({"PROCESO"} | set(ACCIONES)) & set(cl)]
        if len(c) != 1:
            return None
        w = APP_EXE.get(c[0], c[0])
        w = w[:-4] if w.endswith(".exe") else w
        return w if re.fullmatch(r"[a-z0-9._-]+", w) else None

    def _llenar_s(self, i, an, m):
        cmd = self.tareas[i]["cmd"]
        if not self.tpl[i]:
            return cmd, []
        falta = []

        def rep(mm):
            nom = mm.group(1)
            if nom == "app_start":
                s = an.slots.get("{app}")
                v = s["start"] if s else None
            elif nom == "texto_url":
                s = an.slots.get("{texto}")
                v = quote_plus(s["val"]) if s else None
            else:
                s = an.slots.get("{%s}" % nom)
                v = s["val"] if s else None
                if v is None and nom == "app" and "PROCESO" in m.objs:
                    v = self._app_libre(m)
                elif v is not None and s["tipo"] != "app" and set(v) & CHARS_PELIGRO:
                    v = None
            if v is None:
                falta.append(nom)
                return mm.group(0)
            return v
        return re.sub(r"\{([a-z_]+\d*)\}", rep, cmd), falta

    def _inferir(self, m):
        """Verbo desconocido pero visto en la red: (clase, coseno, palabra, parecida) por similitud distribucional."""
        mejor = None
        for r in m.resid:
            w = _palabra(r)
            if not w or (w not in self.red.nb and w not in self.red.cm):
                continue
            for w2, cos in self.red.simil(w, 0.45, 3):
                cl = clases_de(w2)
                k = next((x for x in (cl or ()) if x in ACCIONES and x not in GENERICAS), None)
                if k and (mejor is None or cos > mejor[1]):
                    mejor = (k, cos, r, w2)
        return mejor

    def _herr_s(self, an, add):
        """Herramientas internas (@hora...): sus verbos/objetos entran como marcos de la capa S y sus disparadores como senales."""
        activas = self.herr.activas() if self.usar_herramientas else ()
        if not activas:
            return
        t = an.texto
        ini = len(t) - len(t.lstrip(_CONTORNO))
        fin = len(t.rstrip(_CONTORNO))
        orig = t[ini:fin]
        plano = plano_alineado(orig)
        m = an.marco
        for h in activas:
            if h.condicion is not None and not h.condicion(self.ctx, plano):
                continue
            sc, via = puntuar_herr(m, h, plano)
            if sc <= 0:
                continue
            grupos, da_slots = None, False
            if via[0] == "senal":
                rx = next(r for r in h.disparadores if r.pattern == via[1])
                mm, da_slots = rx.search(plano), bool(rx.groupindex)
                grupos = {k: orig[mm.start(k):mm.end(k)] for k in mm.groupdict() if mm.group(k)}
            vals = extraer_slots(h, an, self.ctx, orig, plano, grupos)
            vals, faltan = resolver_slots(h, vals)
            if faltan and ((via[0] == "marco" and via[1][1] is None) or (via[0] == "senal" and not da_slots)):
                continue                      # sin objeto propio ("abre la calculadora") o senal que no trae slots: no es para esta herramienta
            nombres = [f.nombre for f in faltan]
            add(formato_cmd(h, vals), "S", sc, extra={"S": {"herr": h.nombre, "via": via},
                                                      "H": {"nombre": h.nombre, "slots": vals, "faltan": faltan},
                                                      **({"falta": nombres} if nombres else {})})

    def _google_s(self, an, add):
        """'busca X en google' sin comillas -> la plantilla de Google con X codificado (quote_plus: nada de & | > en la URL)."""
        t = an.texto
        ini = len(t) - len(t.lstrip(_CONTORNO))
        orig = t[ini:len(t.rstrip(_CONTORNO))]
        plano = plano_alineado(orig)
        if "google" not in plano and "googl" not in plano:
            return
        for rx in _RX_GOOGLE:
            mm = rx.match(plano)
            if mm:
                q = orig[mm.start("q"):mm.end("q")].strip().strip("\"'“”«»¿?¡!. ").strip()
                if not re.search(r"\w", q) or len(q) > 200 or _CORTA_GOOGLE.search(plano[mm.start("q"):mm.end("q")]):
                    return
                i = self.cmd_idx.get(_TPL_GOOGLE)
                add('start "" "https://www.google.com/search?q=' + quote_plus(q) + '"', "S", 0.9, i, _TPL_GOOGLE,
                    extra={"S": {"sitio": "busqueda en Google", "via": ()}})
                return

    def _capa_s(self, an, add):
        self._herr_s(an, add)
        self._google_s(an, add)
        m = an.marco
        if not (m.acts or m.sitio or m.resid):
            return
        permitidas = {"ABRIR", "NAVEGAR", "VER", "REPRODUCIR"}
        if m.sitio and "BUSCAR" not in m.acts and set(m.acts) <= permitidas:
            sc = (0.9 if m.acts else 0.8) - 0.05 * min(len(m.resid), 3)
            add("start " + m.sitio[1], "S", sc, extra={"S": {"sitio": m.sitio[0], "via": m.via}})
        elif (not m.sitio and set(m.acts) <= permitidas and len(m.resid) == 1 and re.fullmatch(r"[a-z0-9-]{2,}", m.resid[0])
              and any(cl and "SITIO" in cl for _w, cl in m.cont)):
            add("start https://{host}", "S", 0.65, extra={"S": {"desconocido": m.resid[0], "via": m.via}, "falta": ["host"]})
        if not self.marcos:
            return
        inf = None
        if (m.prim is None or m.prim in GENERICAS) and m.resid:
            inf = self._inferir(m)
        for i, a_t, o_t in self.marcos:
            sc = puntuar_marco(m, a_t, o_t)
            info = {"marco": (a_t, o_t), "via": m.via, "prim": m.prim, "obj": m.obj}
            if sc <= 0 and inf:
                k, cos, r, w2 = inf
                resid = [x for x in m.resid if x != r]
                sc = puntuar_marco(m, a_t, o_t, prim=k, acts=[k] + m.acts, resid=resid) * cos * 0.7
                info.update(prim=k, inferida=(r, w2, cos))
            if sc <= 0:
                continue
            filled, falta = self._llenar_s(i, an, m)
            if falta and o_t is None:
                continue
            if not self.tpl[i] and m.nslots:
                sc *= 0.5
            add(filled, "S", sc, i, self.tareas[i]["cmd"], extra={"S": info, **({"falta": falta} if falta else {})})

    def _capa_e(self, an, add):
        # apps: solo se nombra la app (o "abrir app") -> lanzarla
        if "{app}" in an.slots and not any(s["tipo"] != "app" for s in an.slots.values()):
            resto = [w for w in an.stok if not w.startswith("{") and w != "abrir"]
            if not resto:
                add(an.slots["{app}"]["start"], "E", 0.85, None, extra={"E": "app instalada: " + an.slots["{app}"]["nombre"]})
        # help de cmd: nunca ejecuta directo
        q = [w for w in an.lit if not w.startswith("{")]
        if not q or not self.ayuda:
            return
        cands, tot = set(), 0.0
        qh = []
        for w in q:
            if w not in self.hidf and len(w) >= 5:
                if w not in self._hfix:
                    self._hfix[w] = cercano(w, self.hvocab, 0.8)
                w = self._hfix[w] or w
            qh.append(w)
            tot += self.hidf.get(w, self.hmax)
            cands.update(self.hpost.get(w, ()))
        res = []
        raices = [w[:max(4, len(w) - 3)] for w in re.findall(r"[a-z0-9]+", sin_tildes(an.texto.lower()))
                  if len(w) >= 4 and w not in STOP]
        for k in cands:
            nom, desc, ts = self.ayuda[k]
            masa = sum(self.hidf[w] for w in set(qh) if w in ts)
            cov = masa / tot if tot else 0
            info = min(1.0, masa / 3.5)
            spec = 1.0 / (1.0 + 0.03 * max(0, len(ts) - 4))
            if raices:                      # desempata por palabras literales (directorio vs archivos)
                raw = self.ayuda_raw[k]
                spec *= 1.0 + 0.15 * sum(r in raw for r in raices) / len(raices)
            res.append((TOPE_AYUDA * cov * info * spec, nom, desc))
        res.sort(reverse=True)
        for s, nom, desc in res[:4]:
            add(nom, "E", s, None, ayuda=True, extra={"E": f"help: {desc}"})
