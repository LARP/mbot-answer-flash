"""API de turnos SIN efectos: `proponer(A, frase)` decide qué haría el asistente y lo devuelve como datos (serializables a JSON).

Nunca ejecuta nada por sí misma: ni comandos de cmd, ni herramientas con efectos. Quien la llama (por ejemplo, el plugin mbot_lite de Marley Bot)
decide si ejecuta lo propuesto y con qué confirmación. Solo se evalúan herramientas internas PURAS (hora, fecha, cálculo, espacio en disco...).

Resultado: {"tipo", "texto", "propuesta": None | {"comando", "riesgo", "confianza", "capa"}}.
  tipo: "charla" | "respuesta" | "propuesta" | "duda" | "falta_dato" | "rechazado" | "no_se" | "aviso"
  riesgo: "normal" | "delicado" (borrar, formatear, apagar...: el host debe pedir confirmación siempre)
"""
from .config import es_peligroso

# Herramientas internas sin efectos y sin leer contenido ajeno. Todo lo demás (archivos, documentos, portapapeles, notas) NO se evalúa aquí.
HERRAMIENTAS_PURAS = frozenset({"calcular", "hora", "fecha", "espacio", "sistema", "memoria"})
MAX_FRASE = 500


def _r(tipo, texto, propuesta=None):
    return {"tipo": tipo, "texto": texto, "propuesta": propuesta}


def _propuesta(d):
    return {"comando": d.cmd, "riesgo": "delicado" if (d.peligroso or d.accion == "confirmar" or es_peligroso(d.cmd or "")) else "normal",
            "confianza": round(float(d.conf), 2), "capa": d.capa}


def proponer(A, frase: str) -> dict:
    frase = (frase or "").strip()[:MAX_FRASE]
    if not frase:
        return _r("aviso", "La frase está vacía.")
    if "�" in frase:
        return _r("aviso", "No entendí bien el texto (problema de codificación). Escríbelo de nuevo.")
    if frase.startswith("!"):
        return _r("aviso", "Los comandos con ! no se usan desde aquí: usa las herramientas de enseñar, olvidar, lista y por qué.")
    k = A.conv.interpretar_peticion(frase)
    if k is not None:
        A.ultima = None
        return _r("charla", k.texto or "Entendido.")
    d = A.decidir(frase)
    k = A.conv.atender(frase, d)
    if k is not None:
        return _r("charla", k.texto or "Entendido.")
    A.conv.registrar(frase, d)
    if d.accion == "rechazar":
        return _r("rechazado", f"Rechazado antes de proponerlo: {d.rechazo}")
    if d.herr:
        if d.herr in HERRAMIENTAS_PURAS and d.accion == "ejecutar" and not d.faltan:
            res = A.ejecutar_herramienta(d, frase)
            return _r("respuesta", res.texto if res.ok else f"No pude: {res.texto}")
        return _r("no_se", f"Eso lo resolvería la herramienta interna @{d.herr}, que no está disponible en Mbot Lite. Pídeselo al modelo principal.")
    if d.abierta:
        return _r("no_se", "Esa es una pregunta abierta y Mbot Lite no consulta documentos ni notas. Pídeselo al modelo principal.")
    if d.falta:
        return _r("falta_dato", f"Entendí «{d.cmd}» pero falta: {', '.join(d.falta)}. Dime el dato y lo vuelvo a intentar.")
    if d.conf < 0.99 and A.proponer_plan(frase):
        return _r("no_se", "Eso son varios pasos y Mbot Lite hace un paso por vez: pídelos por separado.")
    if d.accion in ("ejecutar", "confirmar") and d.cmd:
        return _r("propuesta", f"Propongo: {d.cmd}", _propuesta(d))
    if d.accion == "preguntar" and d.cmd and d.conf >= 0.40 and not d.ayuda:
        return _r("duda", f"¿Te refieres a «{d.cmd}»? ({d.conf:.0%}) No es seguro.", _propuesta(d))
    k = A.conv.fallback(frase, d)
    return _r("no_se", k.texto or "No lo entendí.")
