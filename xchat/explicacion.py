"""Capa H: !porque."""
from .config import UMBRAL_EJECUTAR, UMBRAL_PREGUNTAR
from .conocimiento import UMBRAL_RESPUESTA

DOC_TOOLS = {"leer", "seccion", "preguntar_doc", "entidades", "tabla"}


class ExplicacionMixin:
    # ---- explicabilidad (H)
    def explicar(self, d):
        if d is None:
            return "  Todavia no hay ninguna decision que explicar."
        L = [f"  Frase: {d.texto!r}",
             f"  Tokens: {d.an.lit}" + (f"   Con slots: {d.an.slot_text!r}" if d.an.slots else "")]
        for m, s in d.an.slots.items():
            L.append(f"  Slot {m} = {s['val']!r}  (de {s['lit']!r}, tipo {s['tipo']})")
        mk = d.an.marco
        if mk.acts or mk.objs or mk.sitio:
            L.append(f"  Marco detectado: ({mk.prim or '-'}, {mk.obj or '*'})  acciones={mk.acts} objetos={mk.objs}"
                     + (f" sitio={mk.sitio[0]}" if mk.sitio else "") + (f" sin clase={mk.resid}" if mk.resid else ""))
        if not d.cands:
            L.append("  Ninguna capa encontro candidatos.")
        for k, c in enumerate(d.cands[:3]):
            capas = ", ".join(f"{k2}={v:.2f}" for k2, v in sorted(c["capas"].items()))
            L.append(f"  #{k+1} {c['cmd']}  conf={c['conf']:.2f}  capas[{capas}]" + ("  (solo preguntar: help)" if c["ayuda"] else ""))
            for w, p, via in c["extra"].get("D", [])[:6]:
                ruta = f"{w} -> {via} -> comando" if via else f"{w} -> comando"
                L.append(f"       red: {ruta}  prob={p}")
            si = c["extra"].get("S")
            if si:
                if "herr" in si:
                    via = si["via"]
                    if via[0] == "marco":
                        L.append(f"       herramienta @{si['herr']} elegida por marco ({via[1][0]}, {via[1][1] or '*'}) -> comando interno, se ejecuta en Python")
                    else:
                        L.append(f"       herramienta @{si['herr']} elegida por senal /{via[1][:60]}/ -> comando interno, se ejecuta en Python")
                    hx = c["extra"].get("H", {})
                    if hx.get("slots"):
                        L.append(f"          slots: {hx['slots']}")
                elif "sitio" in si:
                    L.append(f"       S: {si['sitio']} -> sitio conocido -> {c['cmd']}")
                elif "desconocido" in si:
                    L.append(f"       S: '{si['desconocido']}' no es un sitio conocido -> pregunto la direccion (no invento)")
                else:
                    a_t, o_t = si["marco"]
                    if "inferida" in si:
                        r, w2, cos = si["inferida"]
                        L.append(f"       S: {r} ~ {w2} (coseno {cos:.2f}, similitud distribucional) -> clase {si['prim']} "
                                 f"(inferida: solo pregunta) -> {c['cmd']}")
                    else:
                        vias = [w for w, k in si["via"] if k == a_t] or [w for w, k in si["via"]]
                        L.append(f"       S: {', '.join(vias[:3])} -> clase {a_t} -> {c['cmd']}")
                    L.append(f"          marco de la tarea: ({a_t}, {o_t or '*'})")
            if c["extra"].get("falta"):
                L.append(f"       falta: {', '.join(c['extra']['falta'])} (se pregunta; no se inventa)")
            if "conflicto" in c["extra"]:
                L.append(f"       penalizada x0.45: choca con lo aprendido para '{c['extra']['conflicto']}'")
            if "P" in c["extra"]:
                L.append(f"       {c['extra']['P']}  (preferencia personal; la app existe en las descubiertas)")
            if "E" in c["extra"]:
                L.append(f"       windows: {c['extra']['E']}")
        docs = getattr(getattr(self, "ctx", None), "docs", None)
        if d.herr in DOC_TOOLS and docs is not None and docs.traza:      # bloque 4: que documento y que seccion se usaron
            for t in docs.traza:
                L.append(f"  Documento: {t['documento']}" + (f"  ({t['ruta']})" if t.get("ruta") else "")
                         + (f"; seccion(es): {', '.join(x or '(sin titulo)' for x in t['secciones'])}" if t.get("secciones") else "") + f"; metodo: {t['metodo']}")
        if d.respuesta is not None:
            r = d.respuesta
            L.append(f"  Respuesta del indice de conocimiento: {r.titulo} ({r.fuente}, {r.ruta}); BM25 normalizado {r.norm:.2f} "
                     f"(umbral {UMBRAL_RESPUESTA}), cobertura de terminos {r.cobertura:.0%}; no se ejecuta nada")
        L.append(f"  Decidio la capa {d.capa}; fusion = max(peso*capa) + 0.1*segundo; accion = {d.accion} "
                 f"(ejecutar >= {UMBRAL_EJECUTAR}, preguntar >= {UMBRAL_PREGUNTAR}); {d.ms:.2f} ms")
        if d.idx is not None:
            t = self.tareas[d.idx]
            L.append(f"  Refuerzo de la tarea: aciertos={t['a']:.1f} fallos={t['f']:.1f} usos={t['usos']}")
        return "\n".join(L)
