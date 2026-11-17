"""Bucle de consola."""
import sys

from .ejecucion import RE_NO, completar, corregir, correr_cmd, preguntar_comando, usar_ayuda
from .herramientas import REGISTRO
from .nucleo import Asistente


def _pedir_slots(A, d):
    """Pide con el esquema ConfigField los slots obligatorios que faltan. True si quedaron completos."""
    resp = {}
    for f in d.faltan:
        pregunta = f.pregunta or f"Falta {f.nombre} ({f.tipo}, obligatorio). {f.pregunta_()}:"
        resp[f.nombre] = input(f"  {pregunta} ").strip()
    ok, motivo = A.completar_herramienta(d, resp)
    if not ok:
        print(f"  Cancelado ({motivo}).")
    return ok


def _usar_herramienta(A, d, frase):
    h = REGISTRO[d.herr]
    if d.faltan:
        if not _pedir_slots(A, d):
            return
    elif d.accion == "preguntar":
        if input(f"  ¿Te refieres a '{d.cmd}'? ({d.conf:.0%}) (s/n) ").strip().lower() != "s":
            print("  Vale, no hago nada.")
            return
    elif d.accion == "confirmar":
        if input(f"  ⚠ @{h.nombre} es delicada ({d.cmd}). ¿Ejecutar? (s/n) ").strip().lower() != "s":
            print("  Cancelado.")
            return
    print(f"  → {d.cmd}  (herramienta interna, confianza {d.conf:.0%})")
    r = A.ejecutar_herramienta(d, frase)
    for linea in r.texto.splitlines() or [""]:
        print(("  " if r.ok else "  ✗ ") + linea)
    A.ultima = None                              # una herramienta no se aprende como comando de cmd ni se corrige con 'no'


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        if not sys.stdin.isatty():                 # stdin en tuberia: UTF-8 (si no, las tildes llegan rotas)
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    A = Asistente(silencioso=False)
    print("Asistente CMD v2. Escribe lo que necesitas "
          "(!lista, !aprender f => cmd, !olvidar N, !descubrir, !porque, !salir)")
    print("Personal: !recuerda <texto>, !olvida <id|texto>, !yo, !recordatorios, !borrar_recordatorio N, !hoy "
          "(y 'recuerdame manana a las 9 ...')")
    print("Herramientas: !herramientas, !herramienta on|off X, !historial  (ej. 'que hora es', 'cuanto es 15% de 230', 'anota comprar pan')")
    print("Conocimiento: !indexar <carpeta>, !reindexar, !fuentes, !desindexar <carpeta>, !buscar X  (ej. 'que se sobre el wifi', 'donde anote la clave')")
    print("Documentos: 'lee el informe.docx', 'muestrame la seccion 3', '¿que dice el informe sobre el presupuesto?', '¿que fechas aparecen en el contrato?', "
          "'¿cuanto suma la columna Monto en gastos.xlsx?'  (docx xlsx pptx odt ods pdf; !indexar los incluye; 'tipo:factura' filtra en !buscar)")
    avisos = A.personal.texto_avisos()
    if avisos:
        print(avisos)
    while True:
        try:
            frase = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        for linea in A.procesar_verificaciones():       # resultados de las verificaciones en segundo plano
            print(linea)
        avisos = A.personal.texto_avisos()       # recordatorios vencidos, en cada turno
        if avisos:
            print(avisos)
        if procesar_linea(A, frase):
            break


SI_K = {"s", "si", "sí", "y", "yes", "claro", "dale", "ok", "okey", "vale"}


def _manejar_k(A, k, frase):
    """Aplica un Turno de la capa K (conversacion.py): imprime, y si hace falta corrige (G), reescribe/reinyecta (con confirmacion) o pide ensenar."""
    if k.porque:                                  # "¿por que?" == !porque
        print(A.conv.explicar() or A.explicar(getattr(A, "ultima_decision", None)))
        return False
    for linea in k.texto.splitlines():
        print("  " + linea)
    if k.corregir:                                # "no sirves" justo tras una accion == "eso no era" (refuerzo G)
        if A.ultima is not None:
            corregir(A, A.ultima)
            A.ultima = None
        return False
    nueva = k.reinyectar or k.reescribir
    if nueva:
        if k.confirmar and input("  " + k.confirmar + " ").strip().lower().strip("¡!.¿?") not in SI_K:
            print("  Vale, no hago nada.")
            return False
        if k.tipo == "seguimiento" and not k.texto:
            print(f"  (entendí: «{nueva}»)")
        return procesar_linea(A, nueva, desde_k=True)        # vuelve a pasar por el flujo completo (peligro, validacion, confirmaciones)
    if k.ensenar:
        preguntar_comando(A, frase)
    return False


PREGUNTA_DEBIL = 0.40   # bajo esto, un "¿te refieres a X?" suele ser ruido: se deriva al fallback conversacional


def procesar_linea(A, frase, desde_k=False):
    """Procesa UNA linea del usuario (todo el razonamiento y los dialogos). True si hay que salir. Separada de main() para poder probarla con
    `input` y el ejecutor simulados (bench.py, bloque CONVERSACION). `desde_k`: la frase la reescribio la capa K (no se vuelve a consultar)."""
    if not frase:
        return False
    if frase == "!salir":
        return True
    if "�" in frase:                      # texto roto: no se ejecuta nada
        print("  No entendí bien el texto (problema de codificación).")
        return False
    if frase == "!lista":
        for i, t in enumerate(A.tareas):
            mk = " ".join(f"({a},{o or '*'})" for a, o in t.get("marco", []))
            print(f"  [{i}] {t['cmd']:<30} usos={t['usos']:<3} ok={t['a']:.1f} mal={t['f']:.1f} {t['frases']}"
                  + (f" marco={mk}" if mk else ""))
        print(f"  (red: {len(A.red.ww)} enlaces palabra-palabra, {len(A.red.wc)} palabra-comando; "
              f"apps descubiertas: {len(A.desc['apps'])}, comandos help: {len(A.desc['ayuda'])})")
        return False
    if frase == "!descubrir":
        d = A.redescubrir()
        print(f"  ✓ {len(d['apps'])} apps y {len(d['ayuda'])} comandos de help en {d['dur']:.2f} s.")
        return False
    if frase == "!porque":
        print(A.conv.explicar() or A.explicar(getattr(A, "ultima_decision", None)))     # capa K si el ultimo turno fue de conversacion
        return False
    if frase.startswith("!"):
        A.conv.registrar_otro()
    r = A.comando_acciones(frase) if frase.startswith("!") else None
    if r is not None:                        # !herramientas, !herramienta on|off X, !historial
        print(r)
        return False
    if frase.startswith("!aprender") and "=>" in frase:
        f, c = frase[len("!aprender"):].split("=>", 1)
        A.aprender(f.strip(), c.strip())
        print("  ✓ Aprendido.")
        return False
    if frase.startswith("!olvidar"):
        try:
            A.olvidar(int(frase.split()[1]))
            print("  ✓ Olvidado.")
        except (IndexError, ValueError):
            print("  Uso: !olvidar N (ver !lista)")
        return False
    if RE_NO.match(frase) and A.ultima is not None:          # flujo G de siempre (la capa K solo atiende el 'no' sin accion previa)
        corregir(A, A.ultima)
        A.ultima = None
        A.conv.registrar_otro()
        return False

    k = A.conv.interpretar_peticion(frase)
    if k is not None:
        A.ultima = None
        return _manejar_k(A, k, frase)

    r = A.personal.procesar(frase)           # hechos, preferencias, consultas y recordatorios
    if r is not None:
        A.conv.registrar_otro()
        for linea in r.texto.splitlines():
            print("  " + linea)
        return False
    previa = getattr(A, "ultima_decision", None)
    d = A.decidir(frase)
    if not desde_k:
        k = A.conv.atender(frase, d)                # capa K: charla y seguimientos (solo si la frase ENTERA lo es)
        if k is not None:
            A.ultima_decision = previa              # una charla no pisa lo que explica !porque
            return _manejar_k(A, k, frase)
    if RE_NO.match(frase):                          # 'no'/'mal' sin accion previa que corregir
        print("  No hay nada que corregir todavía.")
        A.conv.registrar_otro()
        return False
    A.conv.registrar(frase, d)
    if d.accion == "rechazar":              # validacion previa: no se pregunta s/n de algo que se iba a rechazar igualmente
        print(f"  ✗ Rechazado antes de preguntar: {d.rechazo}  ({d.cmd})")
        A.ultima_decision = d
        return False
    if d.abierta:                            # pregunta abierta: se consulta el indice (fuera de decidir(), ver responder_pregunta)
        d = A.responder_pregunta(d)
        if d.accion == "responder":
            A.ultima_decision = d
            print("  " + d.respuesta.texto)
            print(f"  (respuesta del indice, relevancia {d.respuesta.norm:.0%}; no ejecuto nada. !porque explica)")
            return False
    borrador = None
    if d.conf < 0.99:
        borrador = A.proponer_plan(frase)    # un plan es un borrador: 2 minutos para confirmarlo, una sola vez
    if borrador:
        print("  Plan:")
        for k, p in enumerate(borrador.plan, 1):
            print(f"   {k}. {p.cmd}   ({p.conf:.0%})")
        resp = input("  ¿Ejecuto el plan completo? (s/n) ").strip().lower()
        if resp != "s":
            borrador.estado = "descartado"
            return False
        estado, ds = A.confirmar_plan(borrador.id)
        if estado == "ok":
            A.correr_plan(ds, frase, asincrono=True, mostrar=print)
            A.ultima = ds
        elif estado == "expirado":
            print("  El plan expiró (pasaron más de 2 minutos). Pídelo de nuevo.")
        else:
            print(f"  Ese plan ya no se puede ejecutar ({estado}).")
        return False
    A.ultima_decision = d
    if d.herr:
        _usar_herramienta(A, d, frase)
    elif d.falta:
        completar(A, d)
    elif d.accion == "confirmar":
        print(f"  → {d.cmd}  (confianza {d.conf:.0%}, capa {d.capa}; comando delicado, se pedirá confirmación)")
        if correr_cmd(A, d.cmd, frase, d):
            A.aprender(frase, d.cmd)
            A.ultima = d
    elif d.accion == "ejecutar":
        print(f"  → {d.cmd}  (confianza {d.conf:.0%}, capa {d.capa})")
        if correr_cmd(A, d.cmd, frase, d):
            if d.capa != "P":                  # la preferencia no se "hornea" en la memoria de tareas
                A.aprender(frase, d.cmd)
            A.ultima = d
    elif d.accion == "preguntar" and d.conf < PREGUNTA_DEBIL:
        # sugerencia muy floja ("quiero comer" -> schtasks 31%): mejor el fallback de K (charla o "enséñame"), con sugerencias
        return _manejar_k(A, A.conv.fallback(frase, d), frase)
    elif d.accion == "preguntar":
        if d.ayuda:
            if input(f"  ¿Te refieres al comando '{d.cmd}'? ({d.conf:.0%}) (s/n) ").lower() == "s":
                usar_ayuda(A, d)
            else:
                preguntar_comando(A, frase)
        elif input(f"  ¿Te refieres a '{d.cmd}'? ({d.conf:.0%}) (s/n) ").lower() == "s":
            if correr_cmd(A, d.cmd, frase, d):
                A.aprender(frase, d.cmd)
                A.ultima = d
        else:
            preguntar_comando(A, frase)
    else:
        return _manejar_k(A, A.conv.fallback(frase, d), frase)      # charla / pregunta / orden desconocida / sin sentido
    return False
