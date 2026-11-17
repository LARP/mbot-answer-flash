"""
Banco de pruebas reproducible: v1 (asistente_v1.py) contra v2 (asistente.py).
NO ejecuta ningun comando: solo llama a buscar()/decidir()/planear(). Usa memorias temporales.
Uso: python bench.py [-v]   (-v lista cada fallo)
"""
import json, os, re, statistics, sys, tempfile, time, tracemalloc
from datetime import datetime
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asistente as v2
import asistente_v1 as v1

VERBOSE = "-v" in sys.argv
FUSION = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--fusion=")), "max")   # max (actual) | rrf (experimento)
import mbot_answer_flash.config as _cfg
_cfg.FUSION = FUSION
TMP = tempfile.mkdtemp(prefix="bench_asistente_")
HOME = os.path.expanduser("~")
CARP = v2.resolver_carpetas()
LNK_CHROME = r'start "" "C:\Fake\Google Chrome.lnk"'
LNK_SPOTIFY = r'start "" "C:\Fake\Spotify.lnk"'
APPS_SINTETICAS = [["Google Chrome", LNK_CHROME, "chrome.exe", "lnk"],
                   ["Spotify", LNK_SPOTIFY, "spotify.exe", "lnk"],
                   ["Visual Studio Code", 'start "" "C:\\Fake\\Visual Studio Code.lnk"', "code.exe", "lnk"]]

# ---- enseñanza previa (igual para v1 y v2) ----
ENSENAR = [("dibujar algo en paint", "start mspaint"), ("pintar un dibujo", "start mspaint"),
           ("escuchar musica", "start wmplayer"), ("reproducir musica", "start wmplayer"),
           ("limpiar la pantalla", "cls"), ("revisar el estado del disco duro", "chkdsk")]
ENSENAR_V2 = [("ver el tamano de Descargas", f'dir /s "{CARP["descargas"]}"'),
              ("ver el tamano de Documentos", f'dir /s "{CARP["documentos"]}"')]

# (categoria, frase, esperado)   esperado: str | list (plan) | set (help) | None (no debe coincidir)
Q = []
def q(cat, frase, esp): Q.append((cat, frase, esp))

for f, e in [("abre el bloc de notas", "start notepad"), ("abrir calculadora", "start calc"),
             ("quiero ver mi ip", "ipconfig"), ("ejecuta el administrador de tareas", "start taskmgr"),
             ("abre el explorador de archivos", "start explorer"), ("muestra la configuracion de red", "ipconfig"),
             ("necesito la calculadora", "start calc"), ("lanza notepad", "start notepad"),
             ("dime mi ip", "ipconfig"), ("abre el administrador de tareas", "start taskmgr"),
             ("inicia el explorador", "start explorer"), ("revisar la conexion de red", "ipconfig")]:
    q("base", f, e)
for f, e in [("abre blok de notas", "start notepad"), ("abrir calculadroa", "start calc"),
             ("abre el administrdor de tareas", "start taskmgr"), ("muestrame mi ip", "ipconfig"),
             ("abre el esplorador de archivos", "start explorer"), ("ejecuta notepd", "start notepad"),
             ("abir calculadora", "start calc"), ("abre calculdora", "start calc")]:
    q("typos", f, e)
for f, e in [("quiero dibujar", "start mspaint"), ("necesito pintar algo", "start mspaint"),
             ("hacer un dibujo", "start mspaint"), ("dibujar", "start mspaint"), ("pintar", "start mspaint"),
             ("limpia la pantalla por favor", "cls"), ("quiero limpiar", "cls"),
             ("quiero abrir algo para dibujar", "start mspaint"), ("abre algo para pintar", "start mspaint"),
             ("quiero escuchar algo", "start wmplayer"), ("ponme musica", "start wmplayer"),
             ("reproduce algo de musica", "start wmplayer"), ("musica", "start wmplayer"),
             ("estado del disco", "chkdsk"), ("revisar disco", "chkdsk"), ("necesito revisar el disco duro", "chkdsk")]:
    q("red", f, e)
for f, e in [("quien soy yo", "whoami"), ("limpiar la consola", "cls"), ("dime la informacion del sistema", "systeminfo"),
             ("abre el panel de control", "start control"), ("ver el nombre del equipo", "hostname")]:
    q("base_ext", f, e)
q("params", "cierra crhome", "taskkill /im chrome.exe")
q("params", "abre spotfy", LNK_SPOTIFY)
q("params", "abre la carpeta Descargas", f'start "" "{CARP["descargas"]}"')
q("params", "abre la carpeta Documentos", f'start "" "{CARP["documentos"]}"')
q("params", "abre el escritorio", f'start "" "{CARP["escritorio"]}"')
q("params", "abre mi carpeta de imágenes", f'start "" "{CARP["imagenes"]}"')
q("params", "cierra chrome", "taskkill /im chrome.exe")
q("params", "cierra spotify", "taskkill /im spotify.exe")
q("params", "abre chrome", LNK_CHROME)
q("params", "abre spotify", LNK_SPOTIFY)
q("params", "chrome", LNK_CHROME)
q("params", "haz ping a google.com", "ping google.com")
q("params", "haz ping a 8.8.8.8", "ping 8.8.8.8")
q("params", "hacer ping a www.microsoft.com", "ping www.microsoft.com")
q("params", 'busca en google "recetas de cocina"', 'start "" "https://www.google.com/search?q=recetas+de+cocina"')
q("params", 'crea la carpeta "proyectos"', 'mkdir "proyectos"')
q("params", r"abre el archivo C:\temp\nota.txt", r'start "" "C:\temp\nota.txt"')
q("params", "abre https://www.python.org", 'start "" "https://www.python.org"')
q("params", "espera 5 segundos", "timeout /t 5")
q("induccion", "ver el tamano de Escritorio", f'dir /s "{CARP["escritorio"]}"')
q("induccion", "ver el tamano de Musica", f'dir /s "{CARP["musica"]}"')
q("multi", "abre el bloc de notas y luego la calculadora", ["start notepad", "start calc"])
q("multi", "abre notepad; abre calculadora", ["start notepad", "start calc"])
q("multi", "abre la calculadora, despues abre el bloc de notas", ["start calc", "start notepad"])
q("multi", "ver mi ip y despues abrir el administrador de tareas", ["ipconfig", "start taskmgr"])
q("multi", "abre el explorador y también la calculadora", ["start explorer", "start calc"])
q("multi", "primero abre la calculadora y luego cierra chrome", ["start calc", "taskkill /im chrome.exe"])
q("multi", "abre notepad, haz ping a google.com", ["start notepad", "ping google.com"])
for f in ["cuál es la capital de Francia", "cuéntame un chiste", "qué tiempo hará mañana",
          "qué película me recomiendas", "cómo se cocina un arroz", "dime quién ganó el mundial",
          "traduce hello world al francés", "escribe un poema sobre el mar", "cuántos días faltan para navidad",
          "mándale un mensaje a mi mamá", "abre la puerta del garage", "cierra la ventana",
          "quiero ver una película", "ayúdame con mi tarea de matemáticas", "hazme un café", "qué hora es en tokio"]:
    q("negativas", f, None)
for f in ["abre algo", "ver algo", "ejecuta"]:
    q("ambiguas", f, "AMBIGUA")
AYUDA = [("copiar archivos", {"copy", "xcopy"}), ("cambiar de directorio", {"cd", "chdir", "pushd"}),
         ("borrar la pantalla", {"cls"}), ("mostrar la fecha", {"date"}), ("comparar dos archivos", {"comp", "fc"}),
         ("renombrar un archivo", {"ren", "rename"}), ("crear un directorio", {"md", "mkdir"}),
         ("mostrar el contenido de un archivo de texto", {"type"}), ("cambiar el nombre de un archivo", {"ren", "rename"})]

# ---- Desarrollo (antiguo holdout, abierto tras usar casos para ajustar la consola).
DEL_T = 'del "C:\\temp\\viejo.txt"'
DESARROLLO = [
 ("necesito sumar unos numeros", "start calc"), ("necesito hacer una resta", "start calc"),
 ("enciende la calculadora", "start calc"), ("prende la calculadora", "start calc"),
 ("pon algo de musica por favor", "start wmplayer"), ("quiero oir una cancion", "start wmplayer"),
 ("reproduce una cancion", "start wmplayer"), ("quiero escuchar una rola", "start wmplayer"),
 ("ilustrar una idea en paint", "start mspaint"), ("me gustaria pintar un cuadro", "start mspaint"),
 ("quiero diseñar un logo", "start mspaint"),
 ("anotar una idea rapida", "start notepad"), ("quiero redactar una carta", "start notepad"),
 ("abre el editor de texto", "start notepad"),
 ("mostrame mi direccion ip", "ipconfig"), ("cual es mi ip", "ipconfig"), ("chequea la conexion", "ipconfig"),
 ("como se llama mi computadora", "hostname"),
 ("limpia la consola", "cls"), ("vacia la pantalla", "cls"),
 ("abre el gestor de tareas", "start taskmgr"),
 ("termina el programa spotify", "taskkill /im spotify.exe"), ("finaliza chrome", "taskkill /im chrome.exe"),
 ("ve a github", "start https://github.com"), ("entra a wikipedia", "start https://es.wikipedia.org"),
 ("quiero ver netflix", "start https://www.netflix.com"), ("abre mi correo gmail", "start https://mail.google.com"),
 ("apaga la computadora", "shutdown /s /t 0"), ("reinicia el equipo", "shutdown /r /t 0"),
 ("bloquea el pc", "rundll32.exe user32.dll,LockWorkStation"),
 ("elimina el archivo C:\\temp\\viejo.txt", DEL_T), ("suprime un fichero", 'del "{ruta}"'),
 ("abre la carpeta de Descargas", f'start "" "{CARP["descargas"]}"'), ("haz ping a yahoo.com", "ping yahoo.com"),
 # negativas
 ("cuanto cuesta un dolar", None), ("enciende la luz del cuarto", None), ("apaga la television", None),
 ("borra mi historial de conversaciones con Juan", None), ("pinta la pared de blanco", None),
 ("mándame un correo con el reporte", None), ("qué significa la palabra ubuntu", None),
 ("cuenta hasta diez", None), ("dime un chiste de pepito", None), ("mueve la silla", None),
]
# ---- DEV semantica (memoria NUEVA; aqui si se ajusto): los 7 fallos reales + variantes
SEM = [("quiero pintar", "start mspaint"), ("voy a dibujar", "start mspaint"),
       ("quiero escuchar musica", "start wmplayer"), ("borrar un archivo", 'del "{ruta}"'),
       ("mata el proceso notepad", "taskkill /im notepad.exe"), ("abre youtube", "start https://www.youtube.com"),
       ("apaga el computador", "shutdown /s /t 0"),
       ("abre la carpeta Música", f'start "" "{CARP["musica"]}"'),
       ("abre la pagina fooo", "start https://{host}"),
       ("borra el archivo C:\\temp\\x.txt", 'del "C:\\temp\\x.txt"')]

V1_CATS = {"base", "typos", "red", "negativas", "ambiguas"}


# ---------------------------------------------------------------- PERSONAL (escrito ANTES de implementar mbot_answer_flash/personal.py)
# Escenario ordenado sobre UNA instancia con reloj inyectable (determinista). Cada paso: (frase | accion, comprobacion(a, r)).
# a = Asistente; r = a.personal.procesar(frase) (None si la frase no es personal) o lo que devuelva la accion.
# Reloj inicial: miercoles 2026-03-11 10:00.
AHORA0 = datetime(2026, 3, 11, 10, 0)
LNK_VSC = 'start "" "C:\\Fake\\Visual Studio Code.lnk"'
GOOGLE = "start https://www.google.com"


def _act(a, slot):
    h = a.personal.activo(slot)
    return h["valor"] if h else "<sin hecho>"


def _hist(a, slot):
    return [h["valor"] for h in a.personal.historicos(slot)]


def _rec(a, texto):
    return next((x for x in a.personal.recordatorios if x["texto"] == texto and x.get("estado", "pendiente") == "pendiente"), None)


def _runs(a, texto, run, rec=None):
    x = _rec(a, texto)
    return bool(x and x["next_run"].startswith(run) and (rec is None or x["recurrencia"] == rec))


def _avisos(a, estado, texto):
    return any(v["estado"] == estado and v["texto"] == texto for v in a.personal.ultimos_avisos)


PERSONAL = []     # (etiqueta, frase | callable(a, reloj), comprobacion)
def pp(etq, frase, chk): PERSONAL.append((etq, frase, chk))

# hechos y slots
pp("hecho", "prefiero firefox", lambda a, r: r and r.tipo == "hecho" and _act(a, "navegador") == "firefox")
pp("hecho", "mi nombre es Carlos Ruiz", lambda a, r: r and _act(a, "nombre") == "Carlos Ruiz")
pp("hecho", "mi correo es carlos@ejemplo.com", lambda a, r: r and _act(a, "correo") == "carlos@ejemplo.com")
pp("hecho", "trabajo en Acme Corp", lambda a, r: r and _act(a, "trabajo") == "Acme Corp")
pp("hecho", "uso spotify para escuchar música", lambda a, r: r and _act(a, "musica") == "spotify")
pp("hecho", "me gusta el jazz", lambda a, r: r and _act(a, "gusto") == "el jazz")
pp("hecho", "mi editor es vscode", lambda a, r: r and _act(a, "editor") == "vscode")
pp("hecho", "vivo en Lima", lambda a, r: r and _act(a, "ciudad") == "Lima")
# supersesion (nunca se borra)
pp("super", "ahora uso chrome como navegador", lambda a, r: r and _act(a, "navegador") == "chrome"
   and _hist(a, "navegador") == ["firefox"]
   and a.personal.historicos("navegador")[0]["superseded_by"] == a.personal.activo("navegador")["id"])
pp("super", "me mudé a Madrid", lambda a, r: r and _act(a, "ciudad") == "Madrid" and _hist(a, "ciudad") == ["Lima"])
pp("super", "ya no uso spotify", lambda a, r: r and _act(a, "musica") is None and _hist(a, "musica") == ["spotify"])
pp("super", "me gusta el rock", lambda a, r: r and len([h for h in a.personal.hechos if h["slot"] == "gusto" and h["estado"] == "activo"]) == 2)
pp("super", lambda a, rel: a.personal._forzar_ciclo(),            # A->B->A: la cadena debe cortar sola (tope 50)
   lambda a, r: (lambda res: res[1] and len(res[0]) <= 50)(a.personal.cadena(r)))
# consultas e intencion historica
pp("consulta", "¿cuál es mi navegador?", lambda a, r: r and "chrome" in r.texto and "firefox" not in r.texto)
pp("consulta", "¿qué navegador usaba antes?", lambda a, r: r and "firefox" in r.texto)
pp("consulta", "¿qué sabes de mí?", lambda a, r: r and all(x in r.texto for x in ("Carlos Ruiz", "Acme Corp", "Madrid"))
   and "Lima" not in r.texto and "firefox" not in r.texto)
pp("consulta", "!yo", lambda a, r: r and "Carlos Ruiz" in r.texto and "carlos@ejemplo.com" in r.texto)
pp("consulta", "¿dónde vivía antes?", lambda a, r: r and "Lima" in r.texto)
pp("consulta", "¿cómo me llamo?", lambda a, r: r and "Carlos Ruiz" in r.texto)
pp("olvido", "!olvida trabajo en Acme", lambda a, r: r and r.tipo == "olvido" and a.personal.activo("trabajo") is None
   and len(a.personal.historicos("trabajo")) == 1)
pp("olvido", "!olvida 9999", lambda a, r: r and r.tipo == "error")
# recordatorios (miercoles 2026-03-11 10:00)
pp("recordatorio", "recuérdame mañana a las 9 llamar a Juan", lambda a, r: r and _runs(a, "llamar a Juan", "2026-03-12T09:00"))
pp("recordatorio", "recuérdame en 20 minutos sacar la ropa", lambda a, r: r and _runs(a, "sacar la ropa", "2026-03-11T10:20"))
pp("recordatorio", "recuérdame el viernes pagar la luz", lambda a, r: r and _runs(a, "pagar la luz", "2026-03-13T09:00"))
pp("recordatorio", "recuérdame todos los lunes a las 8 revisar correo",
   lambda a, r: r and _runs(a, "revisar correo", "2026-03-16T08:00", "semanal:0"))
pp("recordatorio", "recuérdame hoy a las 9pm cenar", lambda a, r: r and _runs(a, "cenar", "2026-03-11T21:00"))
pp("recordatorio", "recuérdame pasado mañana a las 7:30 de la tarde ir al gimnasio",
   lambda a, r: r and _runs(a, "ir al gimnasio", "2026-03-13T19:30"))
pp("recordatorio", "recuérdame en 2 horas apagar el horno", lambda a, r: r and _runs(a, "apagar el horno", "2026-03-11T12:00"))
pp("recordatorio", "recuérdame a las 9 beber agua", lambda a, r: r and _runs(a, "beber agua", "2026-03-12T09:00"))
pp("recordatorio", "recuérdame cada día a las 7 hacer ejercicio",
   lambda a, r: r and _runs(a, "hacer ejercicio", "2026-03-12T07:00", "diaria"))
pp("recordatorio", "!recordatorios", lambda a, r: r and "llamar a Juan" in r.texto and "sacar la ropa" in r.texto
   and r.texto.index("sacar la ropa") < r.texto.index("apagar el horno"))
pp("recordatorio", "!borrar_recordatorio 2", lambda a, r: r and _rec(a, "apagar el horno") is None and _rec(a, "sacar la ropa"))
# avance del reloj: vencidos recientes = atrasados (se muestran); > 24 h = perdidos (no se disparan); recurrentes avanzan
pp("vencidos", lambda a, rel: (rel.__setitem__(0, datetime(2026, 3, 11, 10, 30)), a.personal.avisos())[1],
   lambda a, r: _avisos(a, "atrasado", "sacar la ropa") and len(a.personal.ultimos_avisos) == 1 and _rec(a, "sacar la ropa") is None)
pp("vencidos", lambda a, rel: (rel.__setitem__(0, datetime(2026, 3, 12, 9, 5)), a.personal.avisos())[1],
   lambda a, r: all(_avisos(a, "atrasado", t) for t in ("llamar a Juan", "beber agua", "hacer ejercicio", "cenar"))
   and _runs(a, "hacer ejercicio", "2026-03-13T07:00", "diaria"))
pp("vencidos", lambda a, rel: (rel.__setitem__(0, datetime(2026, 3, 16, 10, 0)), a.personal.avisos())[1],
   lambda a, r: _avisos(a, "perdido", "pagar la luz") and _avisos(a, "perdido", "ir al gimnasio")
   and _avisos(a, "atrasado", "revisar correo") and not _avisos(a, "atrasado", "pagar la luz")
   and _runs(a, "revisar correo", "2026-03-23T08:00", "semanal:0") and _runs(a, "hacer ejercicio", "2026-03-17T07:00", "diaria"))
# negativas: NO son hechos ni recordatorios
for f in ["recuérdame cómo se hace", "me gusta que funcione", "prefiero no hablar de eso", "mi navegador no funciona",
          "mi nombre es", "uso la computadora todos los días", "recuérdame que soy genial", "abre el navegador"]:
    pp("negativa", f, lambda a, r: r is None)
# !hoy: recordatorios de hoy + comandos mas usados a esta hora
pp("hoy", lambda a, rel: (a.personal.procesar("recuérdame hoy a las 18 sacar la basura"),
                          [a.aprender("abre la calculadora", "start calc") for _ in range(3)])[0],
   lambda a, r: bool(r))
pp("hoy", "!hoy", lambda a, r: r and "sacar la basura" in r.texto and "start calc" in r.texto)
# las preferencias influyen en las acciones (y !porque lo muestra)
pp("pref", lambda a, rel: (a.personal.procesar("ahora uso chrome"), a.decidir("abre el navegador"))[1],
   lambda a, r: r.cmd == LNK_CHROME and r.accion == "ejecutar" and "preferencia navegador=chrome" in a.explicar(r))
pp("pref", lambda a, rel: a.decidir("abre youtube"), lambda a, r: r.cmd == "start https://www.youtube.com")
pp("pref", lambda a, rel: a.decidir("abre el editor de texto"), lambda a, r: r.cmd == LNK_VSC and r.accion == "ejecutar")
pp("pref", lambda a, rel: (a.personal.procesar("prefiero spotify"), a.decidir("ponme música"))[1],
   lambda a, r: r.cmd == LNK_SPOTIFY and "preferencia musica=spotify" in a.explicar(r))
pp("pref", lambda a, rel: (a.personal.procesar("ya no uso spotify"), a.decidir("ponme música"))[1],
   lambda a, r: r.cmd == "start wmplayer")
pp("pref", lambda a, rel: (a.personal.procesar("!recuerda mi navegador es zzfox"), a.decidir("abre el navegador"))[1],
   lambda a, r: r.cmd == GOOGLE and "preferencia" not in a.explicar(r))          # zzfox no esta instalado -> comportamiento actual
pp("pref", "!recuerda prefiero brave", lambda a, r: r and _act(a, "navegador") == "brave")
pp("pref", lambda a, rel: a.decidir("abre el navegador"), lambda a, r: r.cmd == GOOGLE)   # brave tampoco


def bloque_personal(det_p):
    """Corre PERSONAL y el barrido de intrusion. Devuelve (ok, n, intrusion, n_sweep, lat_procesar, lat_decidir_pref, fallos)."""
    rel = [AHORA0]
    a = v2.Asistente(os.path.join(TMP, "mp.json"), det_p, auto_descubrir=False, reloj=lambda: rel[0])
    ok, fallos = 0, []
    for k, (etq, fr, chk) in enumerate(PERSONAL, 1):
        try:
            if callable(fr):
                r = fr(a, rel)
                txt = "<accion>"
            else:
                r = a.personal.procesar(fr)
                txt = fr
            good = bool(chk(a, r))
        except Exception as e:                      # un fallo de API cuenta como fallo; no rompe el bench
            good, txt = False, f"{fr if not callable(fr) else '<accion>'} -> {type(e).__name__}: {e}"
        ok += good
        if not good:
            fallos.append((f"{etq}#{k}", txt))
    # instancia SIN preferencias: el comportamiento actual no cambia
    a0 = v2.Asistente(os.path.join(TMP, "mp0.json"), det_p, auto_descubrir=False, reloj=lambda: AHORA0)
    n = len(PERSONAL) + 1
    if a0.decidir("abre el navegador").cmd == GOOGLE:
        ok += 1
    else:
        fallos.append(("pref", "sin preferencias 'abre el navegador' debe seguir abriendo google"))
    # intrusion: ninguna frase de los bancos anteriores es personal
    frases = [x[1] for x in Q] + [f for f, _ in DESARROLLO] + [f for f, _ in SEM] + \
             ["cual es mi ip", "como se llama mi computadora", "quien soy yo", "qué hora es en tokio", "me gustaria pintar un cuadro"]
    intr = [f for f in frases if a0.personal.procesar(f) is not None]
    lp = []
    for _ in range(3):
        for f in frases:
            t = perf_counter(); a0.personal.procesar(f); lp.append((perf_counter() - t) * 1000)
    for f in ("!recuerda mi navegador es chrome", "!recuerda mi editor es vscode", "!recuerda mi reproductor de música es spotify"):
        a.personal.procesar(f)
    ld = []
    for _ in range(3):
        for cat, f, esp in Q:
            if not isinstance(esp, list):
                t = perf_counter(); a.decidir(f); ld.append((perf_counter() - t) * 1000)
    return ok, n, intr, len(frases), lp, ld, fallos


# ---------------------------------------------------------------- PERSONAL_HOLDOUT2 (escrito ANTES de corregir; revision del coordinador)
SEGURIDAD_CHARLA = ["cual es mi navegador", "que navegador uso", "mi navegador", "¿cuál es mi navegador?",
                    "¿cu\ufffdl es mi navegador?", "mi navegador favorito es firefox", "navegador", "mi editor es vscode",
                    "prefiero chrome", "me gusta el navegador", "uso chrome para navegar", "cuál es mi reproductor de música",
                    "abre el navegador\ufffd", "dónde está mi navegador", "quién es mi navegador"]


def _nuevo(det_p, nombre):
    return v2.Asistente(os.path.join(TMP, nombre), det_p, auto_descubrir=False, reloj=lambda: AHORA0)


def bloque_holdout2(det_p):
    """Devuelve (ok, n, fallos)."""
    res = []

    def chk(etq, cond):
        res.append((etq, bool(cond)))

    def con_prefs(nombre):
        a = _nuevo(det_p, nombre)
        for f in ("!recuerda mi navegador es chrome", "!recuerda mi editor es vscode", "!recuerda mi reproductor de música es spotify"):
            a.personal.procesar(f)
        return a
    a, a0 = con_prefs("h2a.json"), _nuevo(det_p, "h2b.json")
    # 1. seguridad: preguntas y charla nunca 'ejecutar' (ni con preferencias ni sin ellas)
    for f in SEGURIDAD_CHARLA:
        for nom, eng in (("con prefs", a), ("sin prefs", a0)):
            d = eng.decidir(f)
            chk(f"seguridad {nom} {f!r} -> {d.accion}", d.accion != "ejecutar")
    chk("seguridad: 'abre el navegador' sigue ejecutando", a.decidir("abre el navegador").accion == "ejecutar")
    # 2. validacion de comandos escritos a mano
    from mbot_answer_flash.ejecucion import parece_comando
    for c, esp in [("mi nombre es Ana", False), ("hola como estas hoy", False), ("ipconfig /all", True), ("start notepad", True),
                   ("dir C:\\temp", True), ("calc", True), ("ping google.com", True), ("echo hola mundo", True)]:
        chk(f"parece_comando({c!r})", parece_comando(a, c) == esp)
    # 3. supersesion con 'en vez de', 'por', 'ya no ..., uso ...'
    for f in ("ahora uso chrome en vez de firefox", "cambié firefox por chrome", "ya no uso firefox, uso chrome"):
        x = _nuevo(det_p, "h2s.json")
        x.personal.hechos.clear(); x.personal.procesar("mi navegador es firefox")
        r = x.personal.procesar(f)
        chk(f"supersede {f!r}", r and _act(x, "navegador") == "chrome" and _hist(x, "navegador") == ["firefox"])
    # 4. slot por la app conocida
    for f, slot, val in [("prefiero usar firefox", "navegador", "firefox"), ("prefiero usar vscode", "editor", "vscode"),
                         ("prefiero vlc", "musica", "vlc"), ("prefiero usar notepad++", "editor", "notepad++"),
                         ("prefiero usar edge", "navegador", "edge")]:
        x = _nuevo(det_p, "h2c.json"); x.personal.hechos.clear()
        r = x.personal.procesar(f)
        chk(f"slot {f!r}", r and _act(x, slot) == val)
    # 5. tiempo
    for f, run, txt in [("recuérdame dentro de media hora apagar el horno", "2026-03-11T10:30", "apagar el horno"),
                        ("recuérdame en un cuarto de hora llamar a Ana", "2026-03-11T10:15", "llamar a Ana"),
                        ("recuérdame dentro de una hora sacar la ropa", "2026-03-11T11:00", "sacar la ropa"),
                        ("recuérdame dentro de 3 días pagar la luz", "2026-03-14T09:00", "pagar la luz"),
                        ("recuérdame en media hora tomar agua", "2026-03-11T10:30", "tomar agua")]:
        x = _nuevo(det_p, "h2t.json"); x.personal.recordatorios.clear()
        r = x.personal.procesar(f)
        chk(f"tiempo {f!r}", r and _runs(x, txt, run))
    # 6. ruido: 'me gusta' + clausula no es un hecho
    for f in ["me gusta cuando funciona rápido", "me gusta si llueve", "me gusta como cocinas", "me gusta correr por la mañana",
              "me gusta que me llames"]:
        chk(f"ruido {f!r}", _nuevo(det_p, "h2r.json").personal.procesar(f) is None)
    chk("'me gusta el cine' si es hecho", _nuevo(det_p, "h2r.json").personal.procesar("me gusta el cine"))
    # 7. preferencia en sinonimos (cualquier tarea NAVEGAR generica); sitios concretos no se tocan
    d = a.decidir("quiero navegar por internet")
    chk(f"sinonimo navegar -> {d.cmd} {d.accion}", d.cmd == LNK_CHROME and d.accion == "ejecutar")
    d = a.decidir("quiero escuchar algo")
    chk(f"sinonimo escuchar -> {d.cmd}", d.cmd == LNK_SPOTIFY)
    chk("sitio concreto intacto", a.decidir("abre youtube").cmd == "start https://www.youtube.com")
    chk("sin prefs 'quiero navegar por internet' = comportamiento actual", a0.decidir("quiero navegar por internet").cmd == GOOGLE)
    ok = sum(c for _e, c in res)
    return ok, len(res), [e for e, c in res if not c]


# ---------------------------------------------------------------- BLOQUE 2: HERRAMIENTAS (escrito ANTES de implementar)
# Nada de esto ejecuta comandos reales: runner/disk_usage/reloj/tasklist se inyectan; los archivos viven en una carpeta temporal.
PEDIDOS_OK = ["¿puedes abrir la calculadora?", "¿me abres el bloc de notas?", "¿podrías abrir paint?",
              "¿me puedes abrir el explorador?", "puedes abrir la calculadora"]
PEDIDOS_CHARLA = ["¿cuál es mi navegador?", "¿qué navegador uso?", "¿cuál es mi reproductor de música?"]


def bloque_pedidos(det_p):
    """Paso 0: pedidos amables en forma de pregunta valen el umbral normal; las preguntas sobre el usuario siguen siendo charla."""
    a = _nuevo(det_p, "ped.json")
    res = []
    for f in PEDIDOS_OK:
        d = a.decidir(f)
        res.append((f"pedido {f!r} -> {d.accion} {d.cmd}", d.accion == "ejecutar"))
    for f in PEDIDOS_CHARLA:
        d = a.decidir(f)
        res.append((f"charla {f!r} -> {d.accion}", d.accion != "ejecutar"))
    d = a.decidir("¿puedes borrar el archivo C:\\temp\\x.txt?")
    res.append((f"pedido peligroso nunca ejecuta -> {d.accion}", d.accion in ("confirmar", "preguntar")))
    return res


GB = 1024 ** 3


class _Mundo:
    """Arbol temporal + asistente con todo inyectado para el bloque HERRAMIENTAS."""
    def __init__(self, det_p, nombre="herr.json"):
        self.raiz = os.path.join(TMP, "mundo_" + nombre)
        self.dl = os.path.join(self.raiz, "Descargas")
        os.makedirs(os.path.join(self.dl, "sub"), exist_ok=True)
        self.tam = {"a.pdf": 1000, "sub/b.pdf": 2000, "c.jpg": 300, "sub/d.JPG": 400, "e.txt": 50}
        for rel, n in self.tam.items():
            with open(os.path.join(self.dl, *rel.split("/")), "wb") as f:
                f.write(b"x" * n)
        self.a = _nuevo(det_p, nombre)
        self.a.carpetas = dict(self.a.carpetas, descargas=self.dl)
        self.a._cache_an.clear()
        c = self.a.ctx
        c.reloj = lambda: AHORA0
        c.disk_usage = lambda p: (500 * GB, 200 * GB, 300 * GB)
        c.uptime_s = lambda: 90061
        c.usuario, c.equipo, c.so = "ana", "PC-ANA", "Windows 10"
        c.notas_path = os.path.join(self.raiz, "notas.json")
        self.llamadas = []
        self.salida_clip = b""
        def runner(args, entrada=None):
            self.llamadas.append((list(args), entrada))
            return 0, self.salida_clip
        c.runner = runner
        self.t = [1000.0]
        self.a.reloj_ts = lambda: self.t[0]

    def correr(self, frase):
        d = self.a.decidir(frase)
        return d, (self.a.ejecutar_herramienta(d) if d.herr else None)


HSEL = [   # (frase, herramienta esperada)  -> decidir() debe elegirla y marcarla "ejecutar"
    ("dime la hora", "hora"), ("qué hora es", "hora"), ("qué día es hoy", "fecha"), ("dime la fecha", "fecha"),
    ("cuánto espacio me queda", "espacio"), ("cuánto espacio libre hay en el disco", "espacio"),
    ("cuánto es 2+2", "calcular"), ("cuánto es 15% de 230", "calcular"), ("calcula 3*(4+5)", "calcular"),
    ("copia hola al portapapeles", "portapapeles_copiar"), ("qué hay en el portapapeles", "portapapeles_leer"),
    ("busca mis fotos jpg en Descargas", "buscar_archivos"), ("busca archivos pdf en Descargas", "buscar_archivos"),
    ("anota que mañana hay reunión", "nota_agregar"), ("anota comprar pan", "nota_agregar"), ("mis notas", "nota_listar"),
    ("cuánto pesa la carpeta Descargas", "tamano_carpeta"), ("lista la carpeta Descargas", "listar_carpeta"),
    ("cuánto tiempo lleva encendido el equipo", "sistema"), ("info rápida del sistema", "sistema"),
    ("tira un dado", "dado"),
]
HNEG = [    # frases que NO deben elegir ninguna herramienta ni ejecutarla
    "qué hora es en tokio", "cuántos días faltan para navidad", "abre la calculadora", "abre el bloc de notas",
    "anotar una idea rapida", "busca una receta de pasta", "dime la informacion del sistema", "mis notas son importantes",
    "calcula", "borra mi historial de conversaciones con Juan", "quiero ver una película",
]
MALICIOSAS = ["__import__('os').system('calc')", "().__class__.__bases__", "2**999999", "9**9**9", "10**10**10",
              "(1).__class__", "[x for x in ()]", "lambda: 1", "open('x.txt')", "'a'*10**9", "1e999999*1e999999",
              "(" * 3000 + "1" + ")" * 3000, "abs.__call__(1)", "exec('1')", "os.system('dir')", "1/0", "sqrt(-1)",
              "2**2**2**2**2", "1" * 400, "a.b", "pi.real", "[1][0]", "{1:2}", "1 if 1 else 2", "x", "", "   "]


def _junction(link, destino):
    """Symlink o junction (sin admin) de prueba, dentro de la carpeta temporal. None si el sistema no deja crear ninguno."""
    try:
        os.symlink(destino, link, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        pass
    try:
        import subprocess
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, destino], capture_output=True, timeout=10)
        return "junction" if r.returncode == 0 and os.path.exists(link) else None
    except Exception:
        return None


def bloque_herramientas(det_p):
    """Devuelve (res_funcional, res_seguridad, lat_ms): listas de (etiqueta, bool)."""
    from unittest import mock
    from mbot_answer_flash import herramientas as H
    from mbot_answer_flash.registro import Registro, DetectorBucles
    from mbot_answer_flash.verificacion import Verificador
    from mbot_answer_flash.tools_locales import calcular_seguro
    res, seg = [], []

    def chk(etq, f, dest=res):
        try:
            ok = bool(f())
        except Exception as e:
            ok, etq = False, f"{etq} [{type(e).__name__}: {e}]"
        dest.append((etq, ok))

    w = _Mundo(det_p)
    a = w.a
    lat = []
    # 1. eleccion por sinonimos + marco explicado
    for f, h in HSEL:
        def _t(f=f, h=h):
            t = perf_counter(); d = a.decidir(f); lat.append((perf_counter() - t) * 1000)
            return d.herr == h and d.accion == "ejecutar" and d.cmd.startswith("@" + h)
        chk(f"elige @{h} <- {f!r}", _t)
    for f in HNEG:
        chk(f"negativa {f!r}", lambda f=f: (lambda d: d.herr is None and d.accion != "ejecutar" or (d.herr is None and not d.cmd.startswith("@")))(a.decidir(f)))
    chk("!porque muestra herramienta + marco",
        lambda: "herramienta @calcular elegida por marco (CALCULAR, *)" in a.explicar(a.decidir("calcula 3*(4+5)")))
    chk("!porque con senal (sin marco)", lambda: "herramienta @hora elegida por" in a.explicar(a.decidir("qué hora es")))
    # 2. resultados (todo inyectado)
    chk("hora -> 10:00", lambda: "10:00" in w.correr("qué hora es")[1].texto)
    chk("fecha -> 11 de marzo de 2026", lambda: "11 de marzo de 2026" in w.correr("qué día es hoy")[1].texto)
    chk("espacio -> 300 GB libres", lambda: "300" in w.correr("cuánto espacio me queda")[1].texto)
    chk("calc 2+2 = 4", lambda: w.correr("cuánto es 2+2")[1].datos["valor"] == 4)
    chk("calc 15% de 230 = 34.5", lambda: w.correr("cuánto es 15% de 230")[1].datos["valor"] == 34.5)
    chk("calc 3*(4+5) = 27", lambda: w.correr("calcula 3*(4+5)")[1].datos["valor"] == 27)
    chk("clip copiar: usa 'clip' con el texto", lambda: (w.correr("copia hola al portapapeles"),
        w.llamadas[-1][0][0].lower().startswith("clip") and b"hola" in (w.llamadas[-1][1] or b"").replace(b"\x00", b""))[1])

    def _leer():
        w.salida_clip = "hola mundo\r\n".encode("utf-8")
        r = w.correr("qué hay en el portapapeles")[1]
        return "powershell" in w.llamadas[-1][0][0].lower() and "hola mundo" in r.texto
    chk("clip leer: powershell Get-Clipboard", _leer)
    chk("buscar jpg: 2 (insensible a mayusculas, recursivo)", lambda: len(w.correr("busca mis fotos jpg en Descargas")[1].datos["encontrados"]) == 2)
    chk("buscar pdf: 2", lambda: len(w.correr("busca archivos pdf en Descargas")[1].datos["encontrados"]) == 2)
    chk("tamano carpeta = suma exacta", lambda: w.correr("cuánto pesa la carpeta Descargas")[1].datos["bytes"] == sum(w.tam.values()))
    chk("listar carpeta incluye a.pdf", lambda: "a.pdf" in w.correr("lista la carpeta Descargas")[1].texto)
    chk("sistema: usuario, equipo, uptime 1 d 1 h", lambda: (lambda t: "ana" in t and "PC-ANA" in t and "1 d 1 h" in t)(w.correr("info rápida del sistema")[1].texto))
    def _notas():
        w.correr("anota comprar pan"); w.correr("anota que mañana hay reunión")
        t = w.correr("mis notas")[1].texto
        d = w.a.decidir("borra la nota 2")
        borrada = w.a.ejecutar_herramienta(d).ok
        t2 = w.correr("mis notas")[1].texto
        return ("comprar pan" in t and "mañana hay reunión" in t and d.herr == "nota_borrar" and d.accion == "confirmar"
                and borrada and "reunión" not in t2 and "comprar pan" in t2)
    chk("notas: anota x2, lista, borra la 2 (confirmar)", _notas)
    chk("notas.json existe y es JSON valido", lambda: isinstance(json.load(open(w.a.ctx.notas_path, encoding="utf-8")), (list, dict)))
    # 3. validacion
    chk("faltan slots -> ConfigField obligatorio", lambda: (lambda d: d.herr == "portapapeles_copiar" and "texto" in d.falta
        and d.accion != "ejecutar" and d.faltan[0].obligatorio and d.faltan[0].tipo == "texto")(a.decidir("copia al portapapeles")))
    chk("busca archivos sin patron -> falta patron", lambda: "patron" in a.decidir("busca archivos en Descargas").falta
        or a.decidir("busca archivos en Descargas").herr is None)
    chk("slot opcional toma su defecto", lambda: (lambda vals, faltan: not faltan and vals.get("unidad"))(*H.resolver_slots(H.REGISTRO["espacio"], {})))
    chk("estado: necesita configuracion (bin inexistente)", lambda: (H.herramienta("zz_falsa", verbos=("*",), objetos=("HORA",), requiere=("bin:no_existe_zz_123",))(lambda ctx: "x"),
        H.estado(H.REGISTRO.pop("zz_falsa"))[0] == "necesita configuracion")[1])
    def _on_off():
        antes = a.herr.estado("hora")[0] == "habilitada"
        a.herr.poner("hora", False)
        off = a.herr.estado("hora")[0] == "deshabilitada" and a.decidir("qué hora es").herr is None
        a.herr.poner("hora", True)
        return antes and off and a.decidir("qué hora es").herr == "hora"
    chk("estado: habilitada / deshabilitada (y deja de elegirse)", _on_off)
    chk("!herramienta off persiste", lambda: (a.comando_acciones("!herramienta off fecha"),
        H.GestorHerramientas(a.herr.ruta).estado("fecha")[0] == "deshabilitada", a.comando_acciones("!herramienta on fecha"))[1])
    chk("!herramientas lista las 14+ herramientas", lambda: all(n in a.comando_acciones("!herramientas") for n in ("hora", "calcular", "nota_agregar", "dado")))
    chk("validar: del en C:\\Windows rechazado", lambda: not H.validar_comando('del "C:\\Windows\\System32\\x.dll"')[0])
    chk("validar: rmdir /s raiz de disco rechazado", lambda: not H.validar_comando('rmdir /s "C:\\"')[0])
    chk("validar: Program Files rechazado", lambda: not H.validar_comando('del "C:\\Program Files\\app\\x.exe"')[0])
    chk("validar: inexistente rechazado en del", lambda: not H.validar_comando(f'del "{w.dl}\\no_existe.txt"')[0])
    chk("validar: existente aceptado (realpath)", lambda: H.validar_comando(f'del "{w.dl}\\e.txt"')[0])
    chk("validar: lectura en C:\\Windows permitida", lambda: H.validar_comando('type "C:\\Windows\\win.ini"')[0])
    chk("decidir borra C:\\Windows\\notepad.exe -> nunca ejecutar y la validacion lo rechaza (antes 'confirmar', ahora 'rechazar')",
        lambda: (lambda d: d.accion in ("confirmar", "rechazar") and not a.validar_decision(d)[0])(a.decidir("borra el archivo C:\\Windows\\notepad.exe")))
    # 4. verificacion inyectada
    def V(vivo=True, rc=0):
        return Verificador(tasklist=lambda img: vivo, existe=os.path.exists, dormir=lambda s: None, reloj=iter(x * 0.5 for x in range(1000)).__next__)
    class R:        # resultado de ejecucion falso
        def __init__(s, rc=0, proc=None): s.ok, s.rc, s.proc, s.salida = rc == 0, rc, proc, ""
    chk("verif start: proceso visto -> ok", lambda: V(True).verificar(V().preparar("start notepad"), R(0), [])[0] == "ok")
    chk("verif start: no visto, rc 0 -> parcial", lambda: V(False).verificar(V().preparar("start notepad"), R(0), [])[0] == "parcial")
    chk("verif start: rc 1 -> fallo", lambda: V(False).verificar(V().preparar("start noexiste"), R(1), [])[0] == "fallo")
    chk("verif start url -> desconocido", lambda: V().verificar(V().preparar("start https://www.python.org"), R(0), [])[0] == "desconocido")
    chk("verif start: espera <= timeout (sin bloquear)", lambda: (lambda n: n[0] <= 8)((lambda c: (Verificador(tasklist=lambda i: False, dormir=lambda s: c.__setitem__(0, c[0] + 1),
        reloj=iter(x * 0.5 for x in range(1000)).__next__, timeout=3.0).verificar({"tipo": "start", "imagenes": ["x.exe"]}, R(0), []), c)[1])([0])))
    def _archivo(accion):
        p = os.path.join(w.raiz, "ver_" + accion)
        v = V()
        if accion == "mkdir":
            sp = v.preparar(f'mkdir "{p}"'); os.makedirs(p, exist_ok=True); e1 = v.verificar(sp, R(0), [])[0]
            sp = v.preparar(f'mkdir "{p}_no"'); e2 = v.verificar(sp, R(0), [])[0]
            sp = v.preparar(f'mkdir "{p}"'); e3 = v.verificar(sp, R(0), [])[0]       # ya existia: no cambio nada
            return (e1, e2, e3) == ("ok", "fallo", "parcial")
        open(p, "w").close()
        sp = v.preparar(f'del "{p}"'); os.remove(p); e1 = v.verificar(sp, R(0), [])[0]
        open(p, "w").close(); sp = v.preparar(f'del "{p}"'); e2 = v.verificar(sp, R(0), [])[0]
        os.remove(p)
        return (e1, e2) == ("ok", "fallo")
    chk("verif mkdir: ok / fallo / ya existia=parcial", lambda: _archivo("mkdir"))
    chk("verif del: ok / sigue existiendo=fallo", lambda: _archivo("del"))
    chk("verif comando con salida: rc", lambda: (V().verificar(V().preparar("ipconfig"), R(0), [])[0], V().verificar(V().preparar("ipconfig"), R(1), [])[0]) == ("ok", "fallo"))

    def _g():
        x = _nuevo(det_p, "g_ver.json")
        x.aprender("abre blah", "start fakeapp")
        d0 = x.decidir("abre blah")
        for _ in range(3):
            x.aplicar_verificacion(d0, "fallo")
        c1 = x.decidir("abre blah").conf
        x.aplicar_verificacion(x.decidir("abre blah"), "ok"); x.aplicar_verificacion(x.decidir("abre blah"), "parcial")
        c2 = x.decidir("abre blah").conf
        t = x.tareas[x._tarea("start fakeapp")]
        return d0.conf >= 0.99 and c1 < d0.conf and abs(c2 - c1) < 1e-9 and t["f"] >= 2.5 and x.decidir("abre la calculadora").cmd == "start calc"
    chk("G: 3 fallos verificados restan; ok/parcial no; otras tareas intactas", _g)
    # 5. estados de ejecucion
    rp = os.path.join(w.raiz, "ejec.json")
    def _reg():
        r = Registro(rp, reloj=lambda: 5.0)
        i = r.iniciar("abre algo"); r.paso(i, "start calc", "running", 0)
        r2 = Registro(rp, reloj=lambda: 6.0)
        return r2.ultimas(1)[0]["estado"] == "interrupted" and r2.pendientes() == [] and r2.ultimas(1)[0]["id"] == i
    chk("registro: running -> interrupted al arrancar y no se reintenta", _reg)
    def _estados():
        r = Registro(os.path.join(w.raiz, "e3.json"))
        i = r.iniciar("x"); r.paso(i, "a", "ok", 1); r.cerrar(i)
        i = r.iniciar("y"); r.paso(i, "a", "ok", 1); r.paso(i, "b", "fallo", 1); r.cerrar(i)
        i = r.iniciar("z"); r.paso(i, "a", "fallo", 1); r.cerrar(i)
        return [e["estado"] for e in r.ultimas(3)][::-1] == ["done", "partial", "failed"]
    chk("registro: estados done/partial/failed", _estados)
    chk("registro: tope 200 entradas", lambda: (lambda r: ([r.cerrar(r.iniciar(f"f{k}")) for k in range(260)], len(r.entradas) == 200 and r.entradas[-1]["frase"] == "f259")[1])(Registro(os.path.join(w.raiz, "e4.json"))))
    chk("!historial: ultimas 10", lambda: (lambda r: ([r.cerrar(r.iniciar(f"frase{k}")) for k in range(12)],
        (lambda t: "'frase11'" in t and "'frase2'" in t and "'frase1'" not in t and "'frase0'" not in t)(r.texto_historial(10)))[1])(Registro(os.path.join(w.raiz, "e5.json"))))
    def _bucle():
        t = [0.0]
        d = DetectorBucles(reloj=lambda: t[0], limite=3, ttl=60)
        r1 = [d.registrar("start x", False) for _ in range(3)]
        b = d.bloqueado("start x")
        otro = d.bloqueado("start y")
        t[0] = 61
        libre = d.bloqueado("start x")
        d2 = DetectorBucles(reloj=lambda: 0.0)
        d2.registrar("c", False); d2.registrar("c", False); d2.registrar("c", True); d2.registrar("c", False); d2.registrar("c", False)
        return r1 == [False, False, True] and b > 0 and not otro and not libre and not d2.bloqueado("c")
    chk("bucles: 3 fallos seguidos bloquean 60 s; ok reinicia; args distintos no", _bucle)

    def _correr_bucle():
        x = _nuevo(det_p, "bucle.json"); x.reloj_ts = lambda: 0.0
        n = [0]
        def fallo(cmd, **kw):
            n[0] += 1
            return type("R", (), dict(ok=False, rc=1, proc=None, salida="x"))()
        for _ in range(5):
            x.correr("start noexiste", "abre noexiste", runner=fallo)
        return n[0] == 3 and x.correr("start noexiste", "abre noexiste", runner=fallo).estado == "bloqueado"
    chk("correr: tras 3 fallos el 4o no se ejecuta (bloqueado)", _correr_bucle)
    # 6. TTL de planes
    def _plan():
        x = _nuevo(det_p, "plan.json"); t = [1000.0]; x.reloj_ts = lambda: t[0]
        n = []
        runner = lambda cmd, **kw: (n.append(cmd), type("R", (), dict(ok=True, rc=0, proc=None, salida=""))())[1]
        b = x.proponer_plan("abre el bloc de notas y luego la calculadora")
        t[0] += 60
        est, ds = x.confirmar_plan(b.id)
        if est != "ok" or [d.cmd for d in ds] != ["start notepad", "start calc"]:
            return False
        x.correr_plan(ds, "abre el bloc de notas y luego la calculadora", runner=runner)
        est2, ds2 = x.confirmar_plan(b.id)                       # repetida: no se reejecuta
        b2 = x.proponer_plan("abre el bloc de notas y luego la calculadora"); t[0] += 121
        est3, _ = x.confirmar_plan(b2.id)                        # tardia
        est4, _ = x.confirmar_plan(None)
        return est2 == "repetido" and ds2 is None and est3 == "expirado" and n == ["start notepad", "start calc"] and est4 in ("inexistente", "expirado", "repetido")
    chk("plan: confirma 1 vez; repetida=repetido; tardia (>2 min)=expirado; no reejecuta", _plan)
    chk("plan: un plan nuevo reemplaza al borrador anterior", lambda: (lambda x: (lambda b1, b2: x.confirmar_plan(b1.id)[0] != "ok" and x.confirmar_plan(b2.id)[0] == "ok")(
        x.proponer_plan("abre notepad; abre calculadora"), x.proponer_plan("ver mi ip y despues abrir el administrador de tareas")))(_nuevo(det_p, "plan2.json")))
    chk("plugin de usuario: carga desde carpeta con importlib", lambda: (lambda carp: (os.makedirs(carp, exist_ok=True),
        open(os.path.join(carp, "p1.py"), "w", encoding="utf-8").write(
            "from mbot_answer_flash.herramientas import herramienta\n@herramienta('zz_plug', verbos=('*',), objetos=('HORA',), descripcion='t')\n"
            "def f(ctx):\n    return 'plug'\n"),
        open(os.path.join(carp, "roto.py"), "w", encoding="utf-8").write("raise RuntimeError('x')\n"),
        (lambda nombres, errores: ("zz_plug" in nombres and len(errores) == 1 and "zz_plug" in H.REGISTRO and H.REGISTRO.pop("zz_plug")))(*H.cargar_plugins(carp)))[-1])(os.path.join(w.raiz, "plugins")))
    # ---------------- seguridad
    with mock.patch("os.system", side_effect=AssertionError("os.system")), mock.patch("subprocess.Popen", side_effect=AssertionError("Popen")), \
            mock.patch("subprocess.run", side_effect=AssertionError("run")):
        for e in MALICIOSAS:
            def _m(e=e):
                try:
                    calcular_seguro(e)
                except ValueError:
                    return True
                return False
            chk(f"calculadora rechaza {e[:30]!r}", _m, seg)
        chk("calculadora acepta lo legitimo", lambda: [calcular_seguro(x) for x in ("2+2", "3*(4+5)", "2**10", "-(3-5)", "10/4", "7//2", "10%3", "sqrt(16)", "2,5+1")] == [4, 27, 1024, 2, 2.5, 3, 1, 4, 3.5], seg)
        for fr in ["calcula __import__('os').system('calc')", "cuánto es 9**9**9", "calcula 2**999999", "calcula ().__class__"]:
            def _f(fr=fr):
                d = a.decidir(fr)
                if not d.herr:
                    return "__" not in (d.cmd or "") and "class" not in (d.cmd or "")          # (calcula -> abre la app calc: comando fijo e inofensivo)
                if d.falta:
                    return True
                r = a.ejecutar_herramienta(d)
                return not r.ok
            chk(f"calculadora por frase {fr!r}", _f, seg)
    base = os.path.join(w.raiz, "caja"); os.makedirs(os.path.join(base, "sub"), exist_ok=True)
    chk("ruta con .. hacia C:\\Windows rechazada (escritura)", lambda: not H.validar_ruta(os.path.join(base, "sub", *([".."] * 14), "Windows", "x"), escritura=True)[0], seg)
    chk("ruta con .. que sale de la caja rechazada", lambda: not H.validar_ruta(os.path.join(base, "sub", "..", "..", "fuera.txt"), dentro_de=base)[0], seg)
    chk("ruta con .. que se queda dentro aceptada", lambda: H.validar_ruta(os.path.join(base, "sub", "..", "ok.txt"), dentro_de=base)[0], seg)
    chk("C:\\ y C:/ raiz rechazadas (escritura)", lambda: not H.validar_ruta("C:\\", escritura=True)[0] and not H.validar_ruta("C:/", escritura=True)[0], seg)
    chk("rutas de sistema rechazadas (escritura), permitidas (lectura)", lambda: not H.validar_ruta("C:\\Windows\\System32\\drivers\\etc\\hosts", escritura=True)[0]
        and H.validar_ruta("C:\\Windows\\System32\\drivers\\etc", escritura=False)[0], seg)
    kind = _junction(os.path.join(base, "enlace"), "C:\\Windows")
    if kind:
        chk(f"{kind} a C:\\Windows rechazado (escritura)", lambda: not H.validar_ruta(os.path.join(base, "enlace", "System32", "x.dll"), escritura=True)[0], seg)
        chk(f"{kind} que sale de la caja rechazado (dentro_de)", lambda: not H.validar_ruta(os.path.join(base, "enlace", "Temp"), dentro_de=base)[0], seg)
        chk(f"validar_comando del por {kind} rechazado", lambda: not H.validar_comando(f'del "{base}\\enlace\\System32\\x.dll"')[0], seg)
        try:
            os.rmdir(os.path.join(base, "enlace"))          # quita el enlace, no el destino
        except OSError:
            pass
    else:
        seg.append(("symlink/junction no disponible en este sistema (omitido)", True))
    return res, seg, lat


# ---------------------------------------------------------------- BLOQUE 3, PARTE 0: CORRECCIONES (escrito ANTES de corregir)
SIN_VERBO_APAGAR = ["info del equipo", "estado del equipo", "equipo", "mi pc", "datos de mi computadora", "ver el equipo",
                    "como esta el equipo", "revisar el pc", "el computador", "informacion del equipo", "reporte del equipo",
                    "que equipo tengo", "cuanto dura el equipo encendido", "mi laptop", "equipo apagado"]


def bloque_correcciones(det_p):
    """Parte 0 del bloque 3. Devuelve lista de (etiqueta, bool). Nada se ejecuta: runner/ctx inyectados."""
    res = []

    def chk(etq, f):
        try:
            ok = bool(f())
        except Exception as e:
            ok, etq = False, f"{etq} [{type(e).__name__}: {e}]"
        res.append((etq, ok))

    w = _Mundo(det_p, "corr.json")
    a = w.a

    # 1. validacion previa (antes de pedir confirmacion)
    def _boom(cmd, **kw):
        raise AssertionError("no debia ejecutarse: " + cmd)
    for fr in ["borra el archivo C:\\Windows\\win.ini", "borra la carpeta C:\\Program Files", "borra la carpeta C:\\Windows\\System32",
               "elimina el archivo C:\\Program Files (x86)\\algo\\x.exe", "borra la carpeta C:\\"]:
        def _t(fr=fr):
            d = a.decidir(fr)
            return d.accion == "rechazar" and d.rechazo and not a.validar_decision(d)[0]
        chk(f"1. decidir rechaza antes de preguntar: {fr!r}", _t)
    chk("1. el motivo dice 'ruta de sistema protegida'", lambda: "ruta de sistema protegida" in a.decidir("borra el archivo C:\\Windows\\win.ini").rechazo)
    chk("1. _paso tambien rechaza sin ejecutar (doble barrera)", lambda: (lambda c: c.estado == "rechazado" and "protegida" in str(c.detalle))(
        a.correr('del "C:\\Windows\\win.ini"', runner=_boom)))
    f_ok = os.path.join(w.raiz, "borrable.txt")
    open(f_ok, "w").close()
    chk("1. un archivo normal sigue pidiendo confirmacion (no rechaza)", lambda: (lambda d: d.accion == "confirmar" and not d.rechazo)(a.decidir(f"borra el archivo {f_ok}")))
    chk("1. lectura en C:\\Windows no se rechaza", lambda: a.decidir("muestra el contenido del archivo C:\\Windows\\win.ini").accion != "rechazar")

    # 2. rutas con espacios sin comillas
    esp = os.path.join(w.raiz, "con espacios")
    d1, d2 = os.path.join(esp, "Mi Carpeta"), os.path.join(esp, "Mi Carpeta Con Espacios")
    os.makedirs(d1, exist_ok=True)
    os.makedirs(d2, exist_ok=True)
    f2 = os.path.join(d2, "nota 1.txt")
    open(f2, "w").close()

    def val_ruta(fr):
        an = a.analizar(fr)
        return [s["val"] for s in an.slots.values() if s["tipo"] == "ruta"]
    chk("2. 'C:\\Program Files' completo (no 'C:\\Program')", lambda: val_ruta("borra la carpeta C:\\Program Files") == ["C:\\Program Files"])
    chk("2. 'C:\\Program Files (x86)' con parentesis", lambda: val_ruta("borra la carpeta C:\\Program Files (x86)") == ["C:\\Program Files (x86)"])
    chk("2. elige la ruta mas larga que exista (Mi Carpeta vs Mi Carpeta Con Espacios)", lambda: val_ruta(f"abre la carpeta {d2}") == [d2])
    chk("2. se detiene en un conector ('y luego')", lambda: val_ruta(f"abre {d2} y luego la calculadora") == [d2])
    chk("2. se detiene en 'por favor'", lambda: val_ruta(f"borra la carpeta {d2} por favor") == [d2])
    chk("2. archivo con espacio en el nombre", lambda: val_ruta(f"abre el archivo {f2}") == [f2])
    chk("2. si ninguna existe, el resto de la frase", lambda: val_ruta("borra la carpeta C:\\No Existe Aqui") == ["C:\\No Existe Aqui"])
    chk("2. ruta con extension no se extiende", lambda: val_ruta("borra el archivo C:\\temp\\x.txt por favor") == ["C:\\temp\\x.txt"])
    chk("2. entre comillas no cambia", lambda: val_ruta('abre "C:\\Program Files"') == ["C:\\Program Files"])
    chk("2. comando final: rmdir /s con la ruta completa", lambda: a.decidir(f"borra la carpeta {d2}").cmd == f'rmdir /s "{d2}"')

    # 3. huecos de herramientas
    def _elige(fr, h, **slots):
        d = a.decidir(fr)
        return d.herr == h and d.accion == "ejecutar" and all(str(d.hslots.get(k)) == str(v) for k, v in slots.items())
    chk("3. 'a qué fecha estamos' -> @fecha", lambda: _elige("a qué fecha estamos", "fecha"))
    chk("3. 'a qué día estamos' -> @fecha", lambda: _elige("a qué día estamos", "fecha"))
    chk("3. 'raiz de 144' -> @calcular = 12", lambda: _elige("raiz de 144", "calcular") and w.correr("raiz de 144")[1].datos["valor"] == 12)
    chk("3. 'raíz cuadrada de 2' -> @calcular = 1.4142135624", lambda: _elige("raíz cuadrada de 2", "calcular")
        and abs(w.correr("raíz cuadrada de 2")[1].datos["valor"] - 2 ** 0.5) < 1e-9)
    chk("3. sqrt en la lista blanca de la calculadora", lambda: __import__("mbot_answer_flash.tools_locales", fromlist=["x"]).calcular_seguro("sqrt(16)") == 4)
    chk("3. 'encuentra los pdf en Descargas' -> @buscar_archivos *.pdf (2 hallados)", lambda: _elige("encuentra los pdf en Descargas", "buscar_archivos", patron="*.pdf")
        and len(w.correr("encuentra los pdf en Descargas")[1].datos["encontrados"]) == 2)
    chk("3. 'localiza los pdf en Descargas' -> @buscar_archivos", lambda: _elige("localiza los pdf en Descargas", "buscar_archivos"))
    chk("3. 'dónde está el archivo informe.docx' -> @buscar_archivos", lambda: _elige("dónde está el archivo informe.docx", "buscar_archivos", patron="informe.docx"))
    chk("3. 'tira un dado de 20 caras' -> @dado caras=20", lambda: _elige("tira un dado de 20 caras", "dado", caras=20)
        and 1 <= w.correr("tira un dado de 20 caras")[1].datos["valor"] <= 20)
    chk("3. 'tira un dado' sigue en 6 caras", lambda: _elige("tira un dado", "dado", caras=6))
    chk("3. 'cuánto ram tengo' -> @memoria", lambda: _elige("cuánto ram tengo", "memoria"))
    chk("3. 'memoria libre' -> @memoria", lambda: _elige("memoria libre", "memoria"))
    chk("3. @memoria con ctx inyectado", lambda: (setattr(w.a.ctx, "memoria", lambda: {"total": 16 * GB, "libre": 6 * GB, "uso_pct": 62}),
        (lambda r: "6.0 GB libres" in r.texto and "16.0 GB" in r.texto and r.datos["libre"] == 6 * GB)(w.correr("memoria libre")[1]))[1])

    def _real():
        from mbot_answer_flash.tools_locales import _memoria_win
        m = _memoria_win()
        return m["total"] > 0 and 0 <= m["libre"] <= m["total"] and 0 <= m["uso_pct"] <= 100
    chk("3. @memoria real (ctypes GlobalMemoryStatusEx): total>0, libre<=total", _real)
    chk("3. 'info del equipo' -> @sistema (no shutdown)", lambda: _elige("info del equipo", "sistema") and "shutdown" not in a.decidir("info del equipo").cmd)
    chk("3. 'dime la informacion del sistema' sigue en systeminfo (sin herramienta)", lambda: a.decidir("dime la informacion del sistema").herr is None)
    chk("3. 'mis notas' / 'qué hora es' intactas", lambda: _elige("mis notas", "nota_listar") and _elige("qué hora es", "hora"))
    # barrido: ninguna frase sin verbo de apagar/reiniciar propone shutdown (ni como candidato)
    for eng_nom, eng in (("memoria nueva", a), ("con tareas aprendidas", _nuevo(det_p, "corr2.json"))):
        if eng_nom != "memoria nueva":
            for f_, c_ in [("apagar el equipo en la noche", "shutdown /s /t 0"), ("cerrar sesion del pc", "shutdown /l"), ("reiniciar el pc", "shutdown /r /t 0")]:
                eng.aprender(f_, c_)
        bad = [(f_, c["cmd"]) for f_ in SIN_VERBO_APAGAR for c in eng.decidir(f_).cands if "shutdown" in c["cmd"]]
        chk(f"3. barrido shutdown ({eng_nom}): {len(SIN_VERBO_APAGAR)} frases sin verbo, ningun candidato shutdown {bad[:2]}", lambda bad=bad: not bad)
    chk("3. con verbo, shutdown sigue proponiendose y confirma", lambda: (lambda d: "shutdown" in d.cmd and d.accion == "confirmar")(a.decidir("apaga el equipo")))
    chk("3. 'reinicia el equipo' sigue en confirmar", lambda: (lambda d: d.cmd == "shutdown /r /t 0" and d.accion == "confirmar")(a.decidir("reinicia el equipo")))
    return res


# ---------------------------------------------------------------- BLOQUE 3, PARTE 1: CONOCIMIENTO (escrito ANTES de implementar)
D_DEF = datetime(2026, 1, 15, 12, 0)
CORPUS = {   # nombre -> (texto, mtime)
    "wifi.md": ("# Contraseña del wifi\n\nLa clave de la red inalámbrica de casa está en la etiqueta del router TP-Link del salón. El nombre de la red es CasaLuna y usa cifrado WPA2. Si cambias el router, recuerda actualizar la contraseña en el televisor y en la impresora.\n\n## Invitados\n\nPara los invitados existe una red aparte con otra clave sencilla.", D_DEF),
    "receta_pasta.md": ("# Pasta carbonara\n\nIngredientes: espaguetis, huevos, panceta, queso pecorino y pimienta negra. Hierve la pasta en agua con sal. Mientras tanto fríe la panceta y mezcla los huevos con el queso. Une todo fuera del fuego para que la salsa quede cremosa, sin nata.", D_DEF),
    "recetas_postres.md": ("# Postres\n\n## Tarta de manzana\n\nPela las manzanas, córtalas en láminas y colócalas sobre la masa quebrada con azúcar y canela. Hornea a 180 grados durante cuarenta minutos. Receta de la abuela para el domingo.", D_DEF),
    "viaje_lima.txt": ("Viaje a Lima en marzo. Vuelo el día 14 por la mañana, hotel en Miraflores cerca del malecón. Quiero probar el ceviche y visitar el museo Larco. Reservar el taxi del aeropuerto con antelación.", datetime(2026, 3, 5, 10, 0)),
    "coche.md": ("# Mantenimiento del coche\n\nCambio de aceite cada diez mil kilómetros y revisión de los neumáticos antes del viaje largo. El taller recomendó cambiar las pastillas de freno. La ITV del auto vence en junio.", datetime(2026, 3, 11, 8, 0)),
    "python_notas.md": ("# Python\n\nLos decoradores envuelven funciones para añadir comportamiento. Las listas por comprensión son más claras que los bucles. Recordar usar entornos virtuales para cada proyecto y fijar las versiones de las dependencias.", D_DEF),
    "reunion_marzo.md": ("# Reunión de equipo\n\nSe acordó revisar el presupuesto del segundo trimestre y contratar a una persona de soporte. Juan presentará la propuesta de proveedores el viernes. Pendiente: definir el calendario de lanzamiento.", datetime(2026, 3, 10, 14, 0)),
    "presupuesto_2025.txt": ("Presupuesto anual 2025: alquiler, comida, transporte, seguros y ahorro. Meta de ahorro: diez por ciento del salario. Revisar gastos hormiga cada mes.", datetime(2025, 6, 15, 9, 0)),
    "salud.txt": ("Cita con el médico el jueves por el dolor de espalda. Recomendó estiramientos diarios y caminar media hora. Pedir análisis de sangre y la receta del antiinflamatorio.", datetime(2026, 2, 12, 9, 0)),
    "libros.md": ("# Libros por leer\n\nCien años de soledad, El nombre de la rosa y Rayuela. Terminar primero la novela que dejé a medias en la mesita de noche.", D_DEF),
    "jardin.txt": ("Regar los tomates temprano, abonar las macetas del balcón cada quince días y podar el romero. Las lechugas necesitan sombra en verano.", D_DEF),
    "finanzas.md": ("# Finanzas personales\n\nPagar la factura de la luz antes del día 10. Mover el ahorro al fondo indexado y revisar las comisiones del banco. Declarar la renta en abril.", D_DEF),
    "gimnasio.txt": ("Rutina de ejercicios: lunes pecho y tríceps, miércoles espalda y bíceps, viernes piernas. Calentar diez minutos y estirar al terminar. Beber agua.", D_DEF),
    "proyecto_xchat.md": ("# Proyecto xchat\n\nAsistente de consola sin LLM que traduce frases a comandos. Usa SQLite con FTS5 para buscar en las notas y archivos. Falta añadir lectores de docx y pdf.\n\n## Ideas\n\nIncluir recordatorios por voz y un resumen diario.", D_DEF),
    "contactos.txt": ("Juan Pérez, teléfono 555 0101, trabaja en Acme. María López, correo maria@ejemplo.com, vive en Sevilla. Fontanero: Pedro 555 0199.", D_DEF),
    "docker.md": ("# Docker compose\n\nLos contenedores se levantan con docker compose up. Definir volúmenes para la base de datos y exponer solo los puertos necesarios. Usar imágenes ligeras en producción.", D_DEF),
    "musica.txt": ("Practicar acordes de guitarra: do, sol, re menor y la menor. Aprender la canción favorita de oído y grabar una maqueta con el móvil.", D_DEF),
    "ideas.md": ("# Ideas para el blog\n\n- Tutorial sobre automatizar tareas con scripts.\n- Reseña de libros del año.\n- Mis rutinas de productividad.", D_DEF),
    # fixtures de ranking y de lectores
    "ajedrez_apertura.md": ("Apuntes de aperturas. Revisar la defensa siciliana, el gambito de dama y los finales de torre. Practicar tres partidas al día con reloj y analizarlas con calma el fin de semana.", D_DEF),
    "torneo.md": ("# Torneo del club\n\nInscripciones abiertas hasta el viernes. Se juega por equipos de cuatro tableros con ritmo rápido, y el sábado hay ajedrez relámpago, comida compartida y entrega de premios al terminar.", D_DEF),
    "gato_viejo.md": ("Los gatos necesitan vacunas anuales y una visita al veterinario. Cepillar el pelo cada semana y cambiar el arenero a diario.", datetime(2025, 1, 5, 9, 0)),
    "gato_nuevo.md": ("Los gatos necesitan vacunas anuales y una visita al veterinario. Cepillar el pelo cada semana y cambiar el arenero a diario.", datetime(2026, 3, 1, 9, 0)),
    "datos.csv": ("nombre,ciudad,saldo\nAna,Quito,120\nLuis,Bogota,80\nRosa,Quito,300\n", D_DEF),
    "config.json": ('{"servidor": "produccion", "puerto": 8080, "descripcion": "balanceador de carga principal"}', D_DEF),
    "app.log": ("2026-01-15 10:00:01 INFO arranque correcto\n2026-01-15 10:00:05 ERROR fallo de conexion con la impresora\n", D_DEF),
}
N_CORPUS = len(CORPUS)


def _palabras_lorem(n, semilla):
    import random
    r = random.Random(semilla)
    base = ("casa tiempo proyecto cuenta mesa viaje libro idea clase correo reunion plan costo ruta mapa lista dato web "
            "nube motor piso cable carta foto nota fecha hora sala lote pago taller marca tabla clave grupo equipo juego "
            "ciudad campo rio monte playa banco calle plaza torre puente tren barco avion clima fruta sopa pan queso").split()
    return " ".join(r.choice(base) + (str(r.randint(1, 9)) if r.random() < 0.1 else "") for _ in range(n))


def crear_corpus(raiz):
    os.makedirs(raiz, exist_ok=True)
    for nom, (txt, mt) in CORPUS.items():
        p = os.path.join(raiz, nom)
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
        ts = mt.timestamp()
        os.utime(p, (ts, ts))
    # lo que NO debe indexarse
    for sub, nom, txt in [(".git", "secreto.txt", "secretooculto uno"), ("node_modules", "x.md", "secretooculto dos"),
                          ("AppData", "y.txt", "secretooculto tres"), ("", "foto.png", "secretooculto cuatro")]:
        d = os.path.join(raiz, sub) if sub else raiz
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, nom), "w") as f:
            f.write(txt)
    with open(os.path.join(raiz, "enorme.txt"), "w") as f:       # > 5 MB: se omite
        f.write("secretooculto cinco " + "x" * (5 * 1024 * 1024 + 10))
    os.makedirs(os.path.join(raiz, "sub", "hondo"), exist_ok=True)
    with open(os.path.join(raiz, "sub", "hondo", "profundo.md"), "w", encoding="utf-8") as f:
        f.write("# Archivo profundo\n\nEste texto vive en una subcarpeta con la palabra zarzuela.")
    return raiz


def bloque_conocimiento(det_p):
    """~90 comprobaciones del buscador de conocimiento + latencias. Devuelve (res, info)."""
    import shutil
    from mbot_answer_flash import conocimiento as K
    from mbot_answer_flash import herramientas as H
    res, info = [], {}

    def chk(etq, f):
        try:
            ok = bool(f())
        except Exception as e:
            ok, etq = False, f"{etq} [{type(e).__name__}: {e}]"
        res.append((etq, ok))

    raiz = crear_corpus(os.path.join(TMP, "corpus"))
    a = _nuevo(det_p, "conoc.json")
    a.ctx.reloj = lambda: AHORA0
    a.ctx.notas_path = os.path.join(TMP, "conoc.notas.json")
    C = a.conocimiento
    st = {}
    chk("FTS5 disponible en este SQLite", lambda: C.disponible)

    # ---- indexado
    def _idx():
        st.update(C.indexar_carpeta(raiz))
        return st["archivos"] == N_CORPUS + 1 and st["trozos"] >= N_CORPUS + 1
    chk(f"indexar: {N_CORPUS + 1} archivos validos (omite .git, node_modules, AppData, png y >5 MB)", _idx)
    chk("indexar: los omitidos por tamano se cuentan", lambda: st.get("omitidos", 0) >= 1)
    chk("lo omitido no aparece nunca ('secretooculto')", lambda: not C.buscar("secretooculto").hallazgos)
    chk("subcarpetas se recorren (zarzuela)", lambda: any(h.ruta.endswith("profundo.md") for h in C.buscar("zarzuela").hallazgos))

    def B(q, **kw):
        return C.buscar(q, **kw)

    def top(q, n=1):
        return [os.path.basename(h.ruta) for h in B(q).hallazgos[:n]]

    def nombres(q):
        return [os.path.basename(h.ruta) for h in B(q).hallazgos]
    chk("registro de lectores extensible (.txt .md .csv .json .log) + registrar_lector", lambda: {".txt", ".md", ".csv", ".json", ".log"} <= set(K.LECTORES) and callable(K.registrar_lector))
    chk("lectores: csv, json y log se indexan", lambda: top("Quito saldo") == ["datos.csv"] and top("balanceador") == ["config.json"] and top("impresora conexion") == ["app.log"])

    # ---- troceo
    def _troceo():
        parr = " ".join(["palabra"] * 60)
        tr = K.trocear("\n\n".join([parr] * 5), "x")
        n = [len(t.split()) for _t, t in tr]
        return all(x <= 150 for x in n) and all(x >= 80 for x in n[:-1]) and len(tr) >= 2
    chk("troceo: trozos de 80-150 palabras (menos el ultimo)", _troceo)
    chk("troceo: corta por titulos markdown y usa el titulo", lambda: (lambda t: len(t) == 2 and "Uno" in t[0][0] and "Dos" in t[1][0])(K.trocear("# Uno\n\nalfa beta\n\n# Dos\n\ngamma delta", "f")))
    chk("troceo: texto largo sin saltos de linea tambien se corta (<=150)", lambda: all(len(t.split()) <= 150 for _t, t in K.trocear(" ".join(["w"] * 1000), "x")))

    # ---- ranking y consultas
    chk("busca 'contraseña del wifi' -> wifi.md primero", lambda: top("contraseña del wifi") == ["wifi.md"])
    chk("sinonimo: 'password del router' -> wifi.md", lambda: "wifi.md" in top("password del router", 3))
    chk("sinonimo: 'cambio de aceite del automovil' -> coche.md", lambda: top("cambio de aceite del automovil") == ["coche.md"])
    chk("tildes: 'revision de neumaticos' (sin tildes) -> coche.md", lambda: top("revision de neumaticos") == ["coche.md"])
    chk("plural/raiz: 'recetas de pasta' -> receta_pasta.md", lambda: top("recetas de pasta") == ["receta_pasta.md"])

    def _typo():
        r = B("tarta de mazana")
        return [os.path.basename(h.ruta) for h in r.hallazgos[:1]] == ["recetas_postres.md"] and r.corregida and r.corregida[0][1] == "manzana"
    chk("typo: 'tarta de mazana' -> manzana (aviso de correccion)", _typo)
    chk("typo: 'rutina gimnacio' -> gimnasio.txt", lambda: top("rutina gimnacio") == ["gimnasio.txt"])
    chk("frase exacta: \"red inalámbrica\" encuentra wifi.md", lambda: top('"red inalámbrica"') == ["wifi.md"])
    chk("frase exacta respeta el orden: \"inalámbrica red\" no encuentra nada", lambda: not B('"inalámbrica red"').hallazgos)
    chk("exclusion: 'receta' da pasta y postres; 'receta -tarta' quita los postres", lambda: (
        lambda a1, a2: {"receta_pasta.md", "recetas_postres.md"} <= set(a1) and "recetas_postres.md" not in a2 and "receta_pasta.md" in a2)(nombres("receta"), nombres("receta -tarta")))
    chk("exclusion de frase: -\"queso pecorino\"", lambda: "receta_pasta.md" not in nombres('receta -"queso pecorino"') and "recetas_postres.md" in nombres('receta -"queso pecorino"'))
    chk("ext:txt solo devuelve .txt; ext:md solo .md", lambda: (lambda t, m: t and m and all(h.ruta.endswith(".txt") for h in t) and all(h.ruta.endswith(".md") for h in m))(
        B("ejercicios espalda ext:txt").hallazgos, B("receta ext:md").hallazgos))
    chk("ext inexistente -> sin resultados", lambda: not B("receta ext:pdf").hallazgos)
    # tiempo (reloj = miercoles 2026-03-11 10:00)
    chk("tiempo 'presupuesto de ayer' -> reunion_marzo.md solo", lambda: nombres("presupuesto de ayer") == ["reunion_marzo.md"])
    chk("tiempo 'presupuesto en 2025' -> presupuesto_2025.txt solo", lambda: nombres("presupuesto en 2025") == ["presupuesto_2025.txt"])
    chk("tiempo 'viaje la semana pasada' -> viaje_lima.txt", lambda: nombres("viaje la semana pasada") == ["viaje_lima.txt"])
    chk("tiempo 'médico del mes pasado' -> salud.txt", lambda: nombres("médico del mes pasado") == ["salud.txt"])
    chk("tiempo 'aceite de hoy' -> coche.md; 'esta semana' lista lo de esta semana", lambda: nombres("aceite de hoy") == ["coche.md"]
        and set(nombres("esta semana")) == {"reunion_marzo.md", "coche.md"})
    chk("en:archivos / en:notas / en:memoria filtran la fuente", lambda: B("receta en:archivos").hallazgos and all(h.fuente == "archivos" for h in B("receta en:archivos").hallazgos)
        and not B("receta en:notas").hallazgos and not B("receta en:memoria").hallazgos)
    chk("hasta 5 resultados, documentos distintos", lambda: (lambda r: 1 <= len(r) <= 5 and len({h.ruta for h in r}) == len(r))(B("ahorro casa cada").hallazgos or B("cada").hallazgos))
    chk("resultado trae fuente, ruta, fecha y snippet resaltado \u00ab\u2026\u00bb", lambda: (lambda h: h.fuente == "archivos" and h.ruta.endswith("wifi.md") and h.fecha and "\u00ab" in h.snippet)(B("router").hallazgos[0]))
    chk("bonus por titulo: 'ajedrez' -> ajedrez_apertura.md (titulo) antes que torneo.md (1 vez en el cuerpo)", lambda: top("ajedrez", 2) == ["ajedrez_apertura.md", "torneo.md"])
    chk("recencia: textos identicos -> gato_nuevo.md antes que gato_viejo.md", lambda: top("gatos veterinario", 2) == ["gato_nuevo.md", "gato_viejo.md"])
    chk("RRF puro: k=60", lambda: abs(K.rrf([["a", "b"], ["b", "a"]], [1, 1])["a"] - (1 / 61 + 1 / 62)) < 1e-12)

    # ---- negativas y sugerencias
    chk("negativa: tema ausente 'cohetes espaciales' -> nada", lambda: not B("cohetes espaciales").hallazgos)
    chk("negativa: 'cual es la capital de Francia' -> nada", lambda: not B("cual es la capital de Francia").hallazgos)
    chk("negativa: gibberish 'xqzjw plmkk' -> nada, sin excepcion", lambda: not B("xqzjw plmkk").hallazgos)
    chk("negativa: consulta vacia / solo relleno -> nada", lambda: not B("").hallazgos and not B("busca que sabes sobre").hallazgos)
    chk("sugerencia: 'jardinero' -> \u00bfquisiste decir 'jardin'?", lambda: (lambda r: not r.hallazgos and "jardin" in (r.sugerencia or ""))(B("jardinero")))
    chk("sin sugerencias ruidosas: 'capital de Francia' no sugiere palabras lejanas", lambda: not B("cual es la capital de Francia").sugerencia)
    chk("relacionados: 'wifi telescopio' (AND falla) -> wifi.md marcado como relacionado", lambda: (lambda r: r.relacionados and any(h.ruta.endswith("wifi.md") for h in r.hallazgos))(B("wifi telescopio")))

    # ---- inyeccion FTS5 / SQL
    HOSTILES = ['" OR 1=1 --', "NEAR(wifi router)", "*", "^wifi", "wifi OR router", ";DROP TABLE docs;--", '"sin cerrar', "'; DELETE FROM meta; --",
                "((((", "wifi AND NOT", "titulo:wifi", "{titulo texto}: wifi", "wifi*", '"" ""', "NOT wifi", "-", "- -", "wifi NEAR/5 router",
                "a" * 5000, "\x00wifi", "ext:'; DROP TABLE meta;--", "en:notas|'--", "\\", "wifi) OR (1", "docs MATCH 'x'", "\u202ewifi"]
    pat = re.compile(r'(?:"[^\W_]+(?: [^\W_]+)*"\*?|[()]|\s|AND|OR|NOT)*')

    def _hostiles():
        n0 = C._db.execute("SELECT COUNT(*) FROM docs").fetchone()[0], C._db.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        for h in HOSTILES:
            C.buscar(h)                                                 # no debe lanzar
            m = C.match_de(K.parsear_consulta(h, AHORA0))
            if m is not None and not pat.fullmatch(m):
                return False
        n1 = C._db.execute("SELECT COUNT(*) FROM docs").fetchone()[0], C._db.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        return n0 == n1 and n0[0] > 0
    chk(f"inyeccion: {len(HOSTILES)} entradas hostiles no lanzan, el MATCH solo tiene terminos entre comillas + operadores fijos, la base intacta", _hostiles)
    chk("inyeccion: 'wifi OR router' no es operador del usuario (OR/AND/NOT/NEAR se descartan como relleno)", lambda: K.parsear_consulta("wifi OR router NEAR ab AND cd NOT ef", AHORA0).terminos == ["wifi", "router", "ab", "cd", "ef"])
    chk("inyeccion: tablas siguen existiendo tras ';DROP TABLE'", lambda: (C.buscar(";DROP TABLE docs;--"), {r[0] for r in C._db.execute("SELECT name FROM sqlite_master")} >= {"docs", "meta"})[1])
    chk("inyeccion: 'titulo:wifi' no es filtro de columna (no lanza y busca 'titulo' y 'wifi')", lambda: K.parsear_consulta("titulo:wifi", AHORA0).terminos == ["titulo", "wifi"])

    # ---- parser
    def P(t):
        return K.parsear_consulta(t, AHORA0)
    chk("parser: relleno 'qué sé sobre el wifi' -> ['wifi']", lambda: P("qué sé sobre el wifi").terminos == ["wifi"])
    chk("parser: 'encuentra info de docker' -> ['docker']", lambda: P("encuentra info de docker").terminos == ["docker"])
    chk("parser: '¿qué comando abre paint?' -> ['paint']", lambda: P("¿qué comando abre paint?").terminos == ["paint"])
    chk("parser: frase exacta, -excluir, ext:, en:", lambda: (lambda q: q.frases == ["clave de la red"] and q.excluir == ["router"] and q.ext == ["pdf"] and q.fuentes == {"notas", "memoria"})(
        P('busca "clave de la red" -router ext:pdf en:notas|memoria')))
    chk("parser: fechas relativas (ayer, hoy, semana, semana pasada, mes pasado, año)", lambda: (P("x de ayer").desde, P("x de ayer").hasta) == ("2026-03-10", "2026-03-11")
        and (P("x esta semana").desde, P("x esta semana").hasta) == ("2026-03-09", "2026-03-16")
        and (P("x la semana pasada").desde, P("x la semana pasada").hasta) == ("2026-03-02", "2026-03-09")
        and (P("x del mes pasado").desde, P("x del mes pasado").hasta) == ("2026-02-01", "2026-03-01")
        and (P("x en 2025").desde, P("x en 2025").hasta) == ("2025-01-01", "2026-01-01")
        and (P("x de hoy").desde, P("x de hoy").hasta) == ("2026-03-11", "2026-03-12"))

    # ---- fuentes internas: notas, memoria, tareas (se reindexan solas)
    def _notas():
        f = H.REGISTRO["nota_agregar"].fn
        f(a.ctx, texto="la llave del trastero esta en el cajon azul")
        r1 = [h.fuente for h in C.buscar("trastero").hallazgos]
        H.REGISTRO["nota_borrar"].fn(a.ctx, n=1)
        return r1 == ["notas"] and not C.buscar("trastero").hallazgos
    chk("notas: agregar -> se encuentra solo; borrar -> desaparece (sin !reindexar)", _notas)

    def _memoria():
        a.personal.procesar("prefiero firefox")
        r1 = C.buscar("firefox").hallazgos
        a.personal.procesar("ahora uso chrome en vez de firefox")
        r2 = [h for h in C.buscar("firefox").hallazgos if h.fuente == "memoria"]
        r3 = C.buscar("chrome").hallazgos
        hist = [h for h in r2 if "historico" in h.ruta]
        return bool(r1 and r1[0].fuente == "memoria" and "activo" in r1[0].ruta and hist and "(historico)" in hist[0].etiqueta()
                    and r3 and r3[0].fuente == "memoria" and "activo" in r3[0].ruta)
    chk("memoria: hechos activos e historicos marcados, se reindexan solos", _memoria)

    def _tareas():
        a.aprender("abre el bloc de notas rapido", "start notepad")
        r = C.buscar("¿qué comando abre paint?")
        return r.hallazgos and r.hallazgos[0].fuente == "tareas" and "mspaint" in r.hallazgos[0].ruta
    chk("tareas: '¿qué comando abre paint?' -> start mspaint", _tareas)
    chk("tareas: '¿cómo hago ping?' -> ping {host}", lambda: any(h.fuente == "tareas" and "ping" in h.ruta for h in C.buscar("¿cómo hago ping?").hallazgos))

    # ---- !fuentes / !desindexar / incremental (sobre una copia)
    raiz2 = os.path.join(TMP, "corpus2")
    shutil.copytree(raiz, raiz2)
    b = _nuevo(det_p, "conoc2.json")
    b.ctx.reloj = lambda: AHORA0
    C2 = b.conocimiento
    C2.indexar_carpeta(raiz2)
    rr = C2.reindexar()
    chk("!reindexar sin cambios: 0 nuevos, 0 modificados, 0 borrados", lambda: (rr["nuevos"], rr["modificados"], rr["borrados"]) == (0, 0, 0) and rr["sin_cambios"] >= N_CORPUS)
    p = os.path.join(raiz2, "jardin.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("Plantar calabacines y pimientos; regar con manguera cada dos dias. Las petunias necesitan sol.")
    r1 = C2.reindexar()
    chk("modificar: 1 modificado; lo nuevo se encuentra y lo viejo ya no", lambda: r1["modificados"] == 1 and C2.buscar("calabacines").hallazgos and not C2.buscar("lechugas").hallazgos)
    ts = time.time() + 5
    os.utime(p, (ts, ts))
    r2 = C2.reindexar()
    chk("touch (mtime cambia, sha1 igual): sin retrozear (modificados 0, tocados 1)", lambda: r2["modificados"] == 0 and r2["tocados"] == 1)
    os.remove(os.path.join(raiz2, "contactos.txt"))
    r3 = C2.reindexar()
    chk("borrar archivo: 1 borrado (poda); ya no se encuentra", lambda: r3["borrados"] == 1 and not C2.buscar("fontanero").hallazgos)
    with open(os.path.join(raiz2, "nuevo.md"), "w", encoding="utf-8") as f:
        f.write("# Telescopio\n\nComprar un telescopio para ver saturno.")
    r4 = C2.reindexar()
    chk("añadir archivo: 1 nuevo y se encuentra", lambda: r4["nuevos"] == 1 and C2.buscar("telescopio saturno").hallazgos)
    chk("!fuentes: lista carpeta, archivos y trozos + internas", lambda: (lambda t: os.path.realpath(raiz2) in t and "notas" in t and "memoria" in t and "tareas" in t)(b.comando_acciones("!fuentes")))
    chk("comandos de consola: !indexar / !reindexar responden texto", lambda: all(isinstance(x, str) and x for x in (
        b.comando_acciones(f"!indexar {raiz2}"), b.comando_acciones("!reindexar"))))
    n_antes = len(C2.buscar("receta").hallazgos)
    chk("!desindexar quita la carpeta: sin filas ni meta", lambda: (b.comando_acciones(f"!desindexar {raiz2}"), not C2.buscar("receta en:archivos").hallazgos and n_antes > 0
        and C2._db.execute("SELECT COUNT(*) FROM meta WHERE raiz IS NOT NULL").fetchone()[0] == 0)[1])
    chk("!indexar carpeta inexistente / raiz de disco / ruta de sistema -> rechazado con mensaje", lambda: all("rechaz" in x.lower() or "no existe" in x.lower() for x in (
        b.comando_acciones("!indexar C:\\no_existe_zz_123"), b.comando_acciones("!indexar C:\\"), b.comando_acciones("!indexar C:\\Windows"))))

    # ---- integracion con el razonamiento (decidir) y desambiguacion
    def _d(fr):
        return a.decidir(fr)
    for fr in ["qué sé sobre el wifi", "busca en mis notas la receta", "qué dice mi archivo sobre docker", "¿cómo hago una copia de seguridad?",
               "¿dónde anoté la clave del wifi?", "¿qué comando abre paint?", "qué anoté ayer", "busca información sobre docker compose",
               "qué sé sobre mi proyecto", "dime qué anoté hoy", "busca en mis archivos vacaciones", "dónde guardé las llaves"]:
        chk(f"decidir -> @buscar ejecutar: {fr!r}", lambda fr=fr: (lambda d: d.herr == "buscar" and d.accion == "ejecutar")(_d(fr)))
    for fr, h in [("busca archivos pdf en Descargas", "buscar_archivos"), ("busca mis fotos jpg en Descargas", "buscar_archivos"),
                  ("encuentra los pdf en Descargas", "buscar_archivos"), ("dónde está el archivo informe.docx", "buscar_archivos"),
                  ("dime la hora", "hora"), ("mis notas", "nota_listar")]:
        chk(f"no roba: {fr!r} sigue en @{h}", lambda fr=fr, h=h: _d(fr).herr == h)
    chk("no roba a Google: 'busca en google \"recetas de cocina\"' -> google, sin herramienta", lambda: (lambda d: d.herr is None and "google.com/search" in d.cmd)(_d('busca en google "recetas de cocina"')))
    chk("no roba a Google (sin comillas): 'busca recetas en google' no es @buscar", lambda: _d("busca recetas en google").herr != "buscar")
    for fr in ["¿cuál es mi navegador?", "qué sabes de mí", "¿dónde vivo?", "qué navegador uso", "cómo me llamo", "qué sabes de mi navegador"]:
        chk(f"no roba a lo personal: {fr!r}", lambda fr=fr: _d(fr).herr != "buscar")
    chk("negativa: 'busca una receta de pasta' no elige ninguna herramienta", lambda: _d("busca una receta de pasta").herr is None)
    chk("negativa: 'cuál es la capital de Francia' / 'cómo se cocina un arroz' no ejecutan", lambda: all(_d(f).accion != "ejecutar" for f in ["cuál es la capital de Francia", "cómo se cocina un arroz"]))
    chk("ejecutar @buscar: Resultado ok con la ruta del archivo", lambda: (lambda r: r.ok and "wifi.md" in r.texto and r.datos.get("hallazgos"))(
        a.ejecutar_herramienta(_d("qué sé sobre el wifi"))))
    chk("ejecutar @buscar sin resultados: ok y dice que no hay nada", lambda: (lambda r: r.ok and "no encontr" in r.texto.lower())(a.ejecutar_herramienta(_d("qué sé sobre cohetes espaciales"))))
    chk("!porque muestra la herramienta @buscar", lambda: "herramienta @buscar" in a.explicar(_d("qué sé sobre el wifi")))
    chk("!herramientas lista @buscar y @memoria", lambda: all(n in a.comando_acciones("!herramientas") for n in ("@buscar", "@memoria")))

    # ---- latencias: ~1000 archivos sinteticos
    raiz3 = os.path.join(TMP, "sintetico")
    for i in range(1000):
        d = os.path.join(raiz3, f"c{i % 20}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"doc{i}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Documento {i} {_palabras_lorem(2, i)}\n\n" + _palabras_lorem(160, i) + "\n\n" + _palabras_lorem(180, i + 5000) + " clave" + str(i) + "\n")
    c3 = _nuevo(det_p, "conoc3.json").conocimiento
    t0 = perf_counter()
    s3 = c3.indexar_carpeta(raiz3)
    info["idx_s"] = perf_counter() - t0
    info["idx_n"], info["idx_trozos"] = s3["archivos"], s3["trozos"]
    t0 = perf_counter()
    r_inc = c3.reindexar()
    info["reidx_s"] = perf_counter() - t0
    consultas = ["clave" + str(i * 37 % 1000) for i in range(25)] + ["casa tiempo proyecto", "viaje playa tren", "reunion plan costo", "\"mesa viaje\"",
                 "taller marca -tabla", "fruta sopa ext:md", "documento 500", "cable carta foto nube", "sopa de fruta con queso", "plan de viaje a la playa",
                 "proyeto casa", "clase corre", "xqzj", "banco calle plaza torre puente", "nota fecha hora sala"] * 3
    lat = []
    for q in consultas:
        t0 = perf_counter()
        c3.buscar(q)
        lat.append((perf_counter() - t0) * 1000)
    info["q_lat"] = lat
    chk(f"incremental sin cambios sobre {info['idx_n']} archivos: 0 modificados, 0 nuevos ({info['reidx_s']:.2f} s)", lambda: r_inc["modificados"] == 0 and r_inc["nuevos"] == 0 and r_inc["sin_cambios"] == 1000)
    chk(f"1000 archivos sinteticos indexados ({info['idx_s']:.1f} s)", lambda: info["idx_n"] == 1000 and info["idx_s"] < 60)
    chk(f"latencia de consulta p95 < 30 ms (p95 {p95(lat):.1f} ms)", lambda: p95(lat) < 30)
    return res, info


# ---------------------------------------------------------------- BLOQUE 4, PARTE 0: CORRECCIONES (escritas ANTES de corregir)
from urllib.parse import quote_plus as _qp


def _g(q):
    return f'start "" "https://www.google.com/search?q={_qp(q)}"'


QA_DOCS = {   # carpeta de conocimiento para las preguntas abiertas
    "pan.md": "# Pan casero\n\nPara hacer el pan casero precalienta el horno a 220 grados y hornea durante 35 minutos. La temperatura del horno debe ser alta para que la corteza quede crujiente.",
    "postgres.md": "# Postgres\n\nEl servidor PostgreSQL corre por defecto en el puerto 5432. Para cambiarlo edita el archivo postgresql.conf y reinicia el servicio.",
    "wifi.md": CORPUS["wifi.md"][0], "coche.md": CORPUS["coche.md"][0], "receta_pasta.md": CORPUS["receta_pasta.md"][0],
    "viaje_lima.txt": CORPUS["viaje_lima.txt"][0], "salud.txt": CORPUS["salud.txt"][0], "docker.md": CORPUS["docker.md"][0],
}
PREGUNTAS_SIN_RESPUESTA = ["cuál es la capital de Francia", "qué película me recomiendas", "cuántos días faltan para navidad",
                           "cómo se cocina un arroz", "qué tiempo hará mañana", "quién ganó el mundial", "qué significa la palabra ubuntu",
                           "cuál es la raíz cuadrada de la luna", "dónde queda la estación espacial", "cuánto cuesta un dólar"]


def bloque_correcciones4(det_p):
    """Parte 0 del bloque 4. Devuelve [(etiqueta, bool)]. Nada se ejecuta."""
    res = []

    def chk(etq, f):
        try:
            ok = bool(f())
        except Exception as e:
            ok, etq = False, f"{etq} [{type(e).__name__}: {e}]"
        res.append((etq, ok))

    a = _nuevo(det_p, "c4.json")
    # 1. Google sin comillas
    for fr, q_ in [("busca recetas de pan en google", "recetas de pan"), ("búscame en google cómo hacer pan", "cómo hacer pan"),
                   ("googlea precio del dólar", "precio del dólar"), ("busca en google recetas de pan", "recetas de pan"),
                   ("buscame pan casero en google", "pan casero"), ("buscar en google el clima de hoy", "el clima de hoy"),
                   ('busca en google "recetas de cocina"', "recetas de cocina")]:
        def _t(fr=fr, q_=q_):
            d = a.decidir(fr)
            return d.cmd == _g(q_) and d.accion == "ejecutar" and d.herr is None
        chk(f"1. google sin comillas: {fr!r}", _t)
    chk("1. 'busca en mis notas pan' sigue en @buscar", lambda: a.decidir("busca en mis notas pan").herr == "buscar")
    chk("1. 'busca archivos pdf en Descargas' sigue en @buscar_archivos", lambda: a.decidir("busca archivos pdf en Descargas").herr == "buscar_archivos")
    chk("1. 'busca' sin 'google' no abre Google solo", lambda: "google.com/search" not in str(a.decidir("busca una receta de pasta").cmd))

    def _codif():
        d = a.decidir("busca a&b>c|d en google")
        return "google.com/search" not in str(d.cmd) or not (set(d.cmd.split("?q=", 1)[1]) & set("&>|<^"))
    chk("1. el texto de busqueda se codifica (nada de & | > en la URL)", _codif)

    # 2. preguntas abiertas
    raiz = os.path.join(TMP, "qa_corpus")
    os.makedirs(raiz, exist_ok=True)
    for nom, txt in QA_DOCS.items():
        with open(os.path.join(raiz, nom), "w", encoding="utf-8") as f:
            f.write(txt)
    b = _nuevo(det_p, "c4b.json")
    b.conocimiento.indexar_carpeta(raiz)
    llam = []
    orig = b.conocimiento.responder if hasattr(b.conocimiento, "responder") else None
    if orig:
        b.conocimiento.responder = lambda *x, **k: (llam.append(1), orig(*x, **k))[1]

    def _abierta(fr, esperado):
        del llam[:]
        d = b.decidir(fr)
        if llam or not (d.accion == "ensenar" and getattr(d, "abierta", False)):
            return False
        d2 = b.responder_pregunta(d)
        return d2.accion == "responder" and esperado in d2.respuesta.texto and d2.cmd is None and d2.herr is None
    chk("2. 'a qué temperatura horneo el pan' -> responder (220)", lambda: _abierta("a qué temperatura horneo el pan", "220"))
    chk("2. 'en qué puerto corre postgres' -> responder (5432)", lambda: _abierta("en qué puerto corre postgres", "5432"))
    chk("2. '¿en qué puerto corre postgres?' con signos", lambda: _abierta("¿en qué puerto corre postgres?", "5432"))
    chk("2. 'cuál es el cambio de aceite del coche en kilómetros' -> diez mil", lambda: _abierta("cuál es el cambio de aceite del coche en kilómetros", "diez mil"))
    chk("2. si otra capa llega a 'preguntar' (>= 0.3) esa decision se respeta: no es pregunta abierta", lambda: (lambda d: d.accion == "preguntar" and not d.abierta)(b.decidir("cuál es el nombre de la red wifi de casa")))

    def _no_consulta():
        del llam[:]
        b.decidir("a qué temperatura horneo el pan")
        return not llam
    chk("2. decidir() NO consulta el indice (la consulta ocurre en responder_pregunta)", _no_consulta)
    chk("2. la respuesta cita el archivo de origen", lambda: "pan.md" in b.responder_pregunta(b.decidir("a qué temperatura horneo el pan")).respuesta.texto)
    for fr in PREGUNTAS_SIN_RESPUESTA:
        def _t(fr=fr):
            d = b.decidir(fr)
            if d.accion != "ensenar":
                return True                      # otra capa la toma (preguntar): no es una pregunta abierta
            d2 = b.responder_pregunta(d)
            return d2.accion == "ensenar" and d2.cmd is None
        chk(f"2. sin respuesta en el indice, sigue el flujo (ensenar sin comando): {fr!r}", _t)
    chk("2. una frase no interrogativa no se consulta ('el pan se hornea a 220')", lambda: not getattr(b.decidir("el pan se hornea a 220 grados"), "abierta", True))
    chk("2. una orden de cmd no es pregunta abierta ('abre la calculadora')", lambda: not getattr(b.decidir("abre la calculadora"), "abierta", True))
    chk("2. 'responder' nunca ejecuta: sin comando ni herramienta", lambda: (lambda d: d.accion == "responder" and d.cmd is None and d.herr is None and not d.falta)(
        b.responder_pregunta(b.decidir("en qué puerto corre postgres"))))
    # nunca un comando con confianza < 0.3 como sugerencia
    frases = [f for _c, f, e in Q if e is None] + [f for f, e in DESARROLLO if e is None] + PREGUNTAS_SIN_RESPUESTA + \
             ["a qué temperatura horneo el pan", "en qué puerto corre postgres"]
    malos = [(f, d.cmd) for f in frases for d in [a.decidir(f)] if d.accion == "ensenar" and (d.cmd or d.falta or d.herr or d.ayuda)]
    chk(f"2. ningun 'ensenar' arrastra un comando basura ({len(frases)} frases) {malos[:2]}", lambda: not malos)
    chk("2. 'abre algo' no se vuelve responder", lambda: b.responder_pregunta(b.decidir("abre algo")).accion != "responder")
    # la consola: una pregunta abierta se contesta con el indice (E/S simuladas; nada se ejecuta)
    def _consola():
        import builtins, contextlib
        from mbot_answer_flash import consola as _co
        entradas = iter(["en qué puerto corre postgres", "!porque", "!salir"])
        sal = _io_.StringIO()
        orig_in, orig_as = builtins.input, _co.Asistente
        builtins.input = lambda *_a: next(entradas)
        _co.Asistente = lambda silencioso=False: b
        try:
            with contextlib.redirect_stdout(sal):
                _co.main()
        finally:
            builtins.input, _co.Asistente = orig_in, orig_as
        t = sal.getvalue()
        return "5432" in t and "no ejecuto nada" in t and "Respuesta del indice" in t
    chk("2. consola: la pregunta abierta se responde por el indice y !porque explica la fuente", _consola)
    return res


# ---------------------------------------------------------------- BLOQUE 4, PARTE 1: DOCUMENTOS (escrito ANTES de implementar)
import io as _io, zipfile as _zf, zlib as _zl
_io_ = _io
from xml.sax.saxutils import escape as _esc

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _zip(archivos, comp=_zf.ZIP_DEFLATED):
    bio = _io.BytesIO()
    with _zf.ZipFile(bio, "w", comp) as z:
        for n, c in archivos.items():
            z.writestr(n, c)
    return bio.getvalue()


def _wp(txt, estilo=None):
    ppr = f'<w:pPr><w:pStyle w:val="{estilo}"/></w:pPr>' if estilo else ""
    m = len(txt) // 2
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{_esc(txt[:m])}</w:t></w:r><w:r><w:t xml:space="preserve">{_esc(txt[m:])}</w:t></w:r></w:p>'


def _wtbl(filas):
    return "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc>{_wp(c)}</w:tc>" for c in f) + "</w:tr>" for f in filas) + "</w:tbl>"


DOCX_ESTILOS = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles {_W}>'
                '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                '<w:style w:type="paragraph" w:styleId="Ttulo1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
                '<w:style w:type="paragraph" w:styleId="Ttulo2"><w:name w:val="Título 2"/></w:style>'
                '<w:style w:type="paragraph" w:styleId="SubX"><w:name w:val="Mi Subtitulo"/><w:basedOn w:val="Ttulo2"/></w:style></w:styles>')
FRASE_CLAVE = "La clave del resultado fue el control del presupuesto en cada trimestre."
DOCX_CUERPO = [
    ("Informe de ventas 2025", "Ttulo1"),
    ("Este informe resume las ventas del año. El presupuesto anual fue de $1.500.000 y se ejecutó al 92%. " + FRASE_CLAVE, None),
    ("Presupuesto", "Ttulo1"),
    ("El presupuesto de marketing aumentó un 15% respecto al año anterior. El presupuesto total asignado fue de 2.300.000 CLP.", None),
    ("Contacto: ana@ejemplo.com, teléfono +56 9 1234 5678. Alternativo 22 345 6789.", None),
    ("Detalle trimestral", "SubX"),
    ("Los montos por trimestre se muestran en la tabla.", None),
    ("TABLA", None),
    ("Conclusiones", "Ttulo1"),
    ("RUT de la empresa 12.345.678-5. RUT erróneo 12.345.678-9. DNI del gerente 12345678Z y otro 12345678A. Fecha de cierre 15/03/2025 y revisión el 12 de abril de 2025. Más información en https://ejemplo.com/informe.", None),
]
DOCX_TABLA = [["Trimestre", "Monto"], ["Q1", "300.000"], ["Q2", "450.000"], ["Q3", "520.000"]]


def docx_bytes(cuerpo=DOCX_CUERPO, estilos=DOCX_ESTILOS, tabla=DOCX_TABLA, core=True):
    partes = "".join(_wtbl(tabla) if t == "TABLA" else _wp(t, e) for t, e in cuerpo)
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {_W}><w:body>{partes}</w:body></w:document>'
    arch = {"word/document.xml": doc}
    if estilos:
        arch["word/styles.xml"] = estilos
    if core:
        arch["docProps/core.xml"] = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                     'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
                                     '<dc:title>Informe anual de ventas</dc:title><dc:creator>Ana Pérez</dc:creator>'
                                     '<dcterms:created>2025-03-01T10:00:00Z</dcterms:created></cp:coreProperties>')
    return _zip(arch)


def _fila_x(r, celdas):
    out = []
    for col, v in celdas:
        ref = f"{col}{r}"
        if isinstance(v, tuple) and v[0] == "s":
            out.append(f'<c r="{ref}" t="s"><v>{v[1]}</v></c>')
        elif isinstance(v, tuple) and v[0] == "i":
            out.append(f'<c r="{ref}" t="inlineStr"><is><t>{_esc(v[1])}</t></is></c>')
        else:
            out.append(f'<c r="{ref}"><v>{v}</v></c>')
    return f'<row r="{r}">' + "".join(out) + "</row>"


XLSX_SS = ["Gastos del año 2025", "Fecha", "Concepto", "Monto", "Cantidad", "Costo USD", "01/02/2025", "Arriendo", "1.234,56", "1,234.50",
           "05/02/2025", "Comida", "2.000,00", "2,000.00", "09/02/2025", "Transporte", "500,50", "300.25"]


def xlsx_bytes():
    S = lambda t: ("s", XLSX_SS.index(t))
    gastos = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
              + _fila_x(1, [("A", S("Gastos del año 2025"))])
              + _fila_x(3, [("A", S("Fecha")), ("B", S("Concepto")), ("C", S("Monto")), ("D", S("Cantidad")), ("E", S("Costo USD"))])
              + _fila_x(4, [("A", S("01/02/2025")), ("B", S("Arriendo")), ("C", S("1.234,56")), ("D", 1), ("E", S("1,234.50"))])
              + _fila_x(5, [("A", S("05/02/2025")), ("B", S("Comida")), ("C", S("2.000,00")), ("D", 3), ("E", S("2,000.00"))])
              + _fila_x(6, [("A", S("09/02/2025")), ("B", S("Transporte")), ("C", S("500,50")), ("D", 2), ("E", S("300.25"))])
              + "</sheetData></worksheet>")
    ventas = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
              + _fila_x(1, [("A", ("i", "Producto")), ("B", ("i", "Ventas"))])
              + _fila_x(2, [("A", ("i", "Lápiz")), ("B", 100)]) + _fila_x(3, [("A", ("i", "Cuaderno")), ("B", 250.5)])
              + _fila_x(4, [("A", ("i", "Mochila")), ("B", 300)]) + "</sheetData></worksheet>")
    ss = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' + "".join(f"<si><t>{_esc(t)}</t></si>" for t in XLSX_SS) + "</sst>"
    wb = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="Gastos" sheetId="1" r:id="rId1"/><sheet name="Ventas" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" Target="worksheets/sheet2.xml"/><Relationship Id="rId2" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
    return _zip({"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/sharedStrings.xml": ss,
                 "xl/worksheets/sheet2.xml": gastos, "xl/worksheets/sheet1.xml": ventas})


_NA = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def _slide(titulo, lineas):
    cuerpo = "".join(f"<a:p><a:r><a:t>{_esc(x)}</a:t></a:r></a:p>" for x in lineas)
    return (f'<p:sld {_NA}><p:cSld><p:spTree>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="T"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:bodyPr/><a:p><a:r><a:t>{_esc(titulo)}</a:t></a:r></a:p></p:txBody></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="C"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr><p:txBody><a:bodyPr/>{cuerpo}</p:txBody></p:sp>'
            '</p:spTree></p:cSld></p:sld>')


def pptx_bytes():
    pres = ('<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<p:sldIdLst><p:sldId id="256" r:id="rId10"/><p:sldId id="257" r:id="rId11"/><p:sldId id="258" r:id="rId12"/></p:sldIdLst></p:presentation>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId10" Type="x" Target="slides/slide3.xml"/><Relationship Id="rId11" Type="x" Target="slides/slide1.xml"/>'
            '<Relationship Id="rId12" Type="x" Target="slides/slide2.xml"/></Relationships>')
    return _zip({"ppt/presentation.xml": pres, "ppt/_rels/presentation.xml.rels": rels,
                 "ppt/slides/slide1.xml": _slide("Plan de trabajo", ["Fase uno: levantamiento de requisitos", "Fase dos: desarrollo del prototipo"]),
                 "ppt/slides/slide2.xml": _slide("Cierre", ["Gracias por su atención", "Preguntas al final"]),
                 "ppt/slides/slide3.xml": _slide("Resumen ejecutivo", ["El proyecto reduce costos un 20%", "Inversión inicial de 50.000 USD"])})


_NO = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
       'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"')


def odt_bytes():
    c = (f'<office:document-content {_NO}><office:body><office:text>'
         '<text:h text:outline-level="1">Acta de reunión</text:h>'
         '<text:p>Siendo las 10:00 horas se reúnen los asistentes<text:s text:c="2"/>de la <text:span>comisión</text:span> directiva.</text:p>'
         '<text:h text:outline-level="2">Acuerdos</text:h><text:p>Se aprueba el orden del día y los acuerdos de la sesión.</text:p>'
         '<table:table table:name="T1"><table:table-row><table:table-cell><text:p>Nombre</text:p></table:table-cell><table:table-cell><text:p>Cargo</text:p></table:table-cell></table:table-row>'
         '<table:table-row><table:table-cell><text:p>Marta</text:p></table:table-cell><table:table-cell><text:p>Secretaria</text:p></table:table-cell></table:table-row></table:table>'
         '</office:text></office:body></office:document-content>')
    m = (f'<office:document-meta {_NO}><office:meta><dc:title>Acta de la comisión</dc:title><dc:creator>Marta</dc:creator>'
         '<meta:creation-date>2025-02-02T09:00:00</meta:creation-date></office:meta></office:document-meta>')
    return _zip({"content.xml": c, "meta.xml": m, "mimetype": "application/vnd.oasis.opendocument.text"})


def ods_bytes():
    c = (f'<office:document-content {_NO}><office:body><office:spreadsheet><table:table table:name="Datos">'
         '<table:table-row><table:table-cell office:value-type="string"><text:p>Item</text:p></table:table-cell><table:table-cell office:value-type="string"><text:p>Precio</text:p></table:table-cell>'
         '<table:table-cell table:number-columns-repeated="1000000"/></table:table-row>'
         '<table:table-row><table:table-cell office:value-type="string"><text:p>Taza</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="12.5"><text:p>12,5</text:p></table:table-cell></table:table-row>'
         '<table:table-row><table:table-cell office:value-type="string"><text:p>Plato</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="7.5"><text:p>7,5</text:p></table:table-cell></table:table-row>'
         '<table:table-row table:number-rows-repeated="1048576"><table:table-cell/></table:table-row>'
         '</table:table></office:spreadsheet></office:body></office:document-content>')
    return _zip({"content.xml": c})


def pdf_bytes(paginas, info=None, trailer_extra=b"", flate=True):
    """PDF minimo escrito a mano. `paginas`: contenidos (bytes) en orden logico; los objetos se numeran al reves para que el orden
    de objetos NO coincida con el de paginas."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    n = 4 + 2 * len(paginas)
    pgs = []
    for s in paginas:
        n -= 2
        pn, cn = n, n + 1
        data = _zl.compress(s) if flate else s
        objs[cn] = b"<< /Length %d %s>>\nstream\n" % (len(data), b"/Filter /FlateDecode " if flate else b"") + data + b"\nendstream"
        objs[pn] = b"<< /Type /Page /Parent 2 0 R /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>" % cn
        pgs.append(pn)
    objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in pgs) + b"] /Count %d >>" % len(pgs)
    nid = max(objs) + 1
    tr = b"/Root 1 0 R"
    if info:
        objs[nid] = b"<< " + info + b" >>"
        tr += b" /Info %d 0 R" % nid
    out = b"%PDF-1.4\n"
    for k in sorted(objs):
        out += b"%d 0 obj\n" % k + objs[k] + b"\nendobj\n"
    return out + b"trailer\n<< /Size %d %s %s >>\nstartxref\n0\n%%%%EOF\n" % (nid + 1, tr, trailer_extra)


PDF_P1 = b"BT /F1 12 Tf 72 720 Td (Contrato de arrendamiento) Tj 0 -14 Td [(El plazo del ) -10 (contrato es de doce meses \\(prorrogables\\).)] TJ ET"
PDF_P2 = b"BT /F1 12 Tf 72 720 Td (Segunda p\\341gina: la renta mensual es de 450.000 pesos.) Tj ET"
PDF_CID = b"BT /F1 12 Tf 72 720 Td <000300040005000600070008000900010002000B000C000D> Tj ET"
PDF_IMG = b"q 612 0 0 792 0 0 cm /Im0 Do Q"


def pdf_objstm_bytes():
    """PDF 1.5: el catalogo, el arbol de paginas y la pagina viven dentro de un ObjStm comprimido."""
    o1, o2, o4 = b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /Contents 5 0 R >>"
    cab = b"1 0 2 %d 4 %d " % (len(o1) + 1, len(o1) + len(o2) + 2)
    st = _zl.compress(cab + o1 + b" " + o2 + b" " + o4)
    s5 = _zl.compress(b"BT /F1 12 Tf 72 720 Td (Texto dentro de un ObjStm) Tj ET")
    return (b"%%PDF-1.5\n6 0 obj\n<< /Type /ObjStm /N 3 /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (len(cab), len(st)) + st
            + b"\nendstream\nendobj\n5 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(s5) + s5 + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%EOF\n")


def zip_bomba():
    return _zip({"word/document.xml": b"A" * (80 * 1024 * 1024)})


def zip_muchas():
    bio = _io.BytesIO()
    with _zf.ZipFile(bio, "w", _zf.ZIP_STORED) as z:
        for i in range(6000):
            z.writestr(f"x/{i}.txt", b"")
    return bio.getvalue()


DOCX_ENTIDAD = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY boom "EXPANDIDO"><!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>'
                f'<w:document {_W}><w:body><w:p><w:r><w:t>&boom;&xxe;</w:t></w:r></w:p></w:body></w:document>')

TIPOS_TXT = {
    "factura": "Factura N° 1234\nCliente: Comercial Sur. RUT 76.123.456-7\nDetalle de productos. Subtotal 100.000 IVA 19.000 Total a pagar 119.000. Folio 998.",
    "contrato": "Contrato de arrendamiento. Entre el arrendador y el arrendatario se acuerdan las siguientes cláusulas. Cláusula primera: la vigencia será de doce meses. Las partes firman en señal de conformidad.",
    "cv": "Curriculum Vitae. Perfil profesional: ingeniero. Experiencia laboral: cinco años en desarrollo. Formación académica: universidad. Habilidades: Python, SQL. Idiomas: inglés. Referencias disponibles.",
    "informe": "Informe técnico. Resumen ejecutivo. Introducción y metodología. Análisis de resultados. Conclusiones y recomendaciones del equipo.",
    "receta": "Receta de pan. Ingredientes: harina, agua, sal. Preparación: amasar y hornear durante 35 minutos. Rinde 8 porciones.",
    "acta": "Acta de reunión. Asistentes: Ana, Luis. Orden del día. Acuerdos adoptados. Siendo las 11:00 se levanta la sesión.",
    "otro": "Lista de la compra con cosas varias para el fin de semana en el mercado del barrio.",
}


class _MundoDoc:
    """Carpeta Descargas temporal con documentos de todos los formatos + asistente con todo inyectado (nada se ejecuta)."""
    def __init__(self, det_p, nombre, extra=None):
        self.raiz = os.path.join(TMP, "docs_" + nombre)
        self.dl = os.path.join(self.raiz, "Descargas")
        os.makedirs(self.dl, exist_ok=True)
        self.archivos = {"informe.docx": docx_bytes(), "gastos.xlsx": xlsx_bytes(), "plan.pptx": pptx_bytes(), "acta.odt": odt_bytes(),
                         "contrato.pdf": pdf_bytes([PDF_P1, PDF_P2], info=b"/Title (Contrato de prueba) /Author (Luis)"),
                         "factura.docx": docx_bytes([("Factura 1234", "Ttulo1"), (TIPOS_TXT["factura"], None)], tabla=[["a"]]),
                         "receta_pan.docx": docx_bytes([("Receta de pan", "Ttulo1"), (TIPOS_TXT["receta"], None)], tabla=[["a"]])}
        self.archivos.update(extra or {})
        for n, d in self.archivos.items():
            with open(os.path.join(self.dl, n), "wb") as f:
                f.write(d)
        self.a = _nuevo(det_p, nombre + ".json")
        self.a.carpetas = dict(self.a.carpetas, descargas=self.dl)
        self.a._cache_an.clear()
        c = self.a.ctx
        c.reloj = lambda: AHORA0
        c.carpetas = dict(c.carpetas, descargas=self.dl)
        c.notas_path = os.path.join(self.raiz, "notas.json")
        self.st = self.a.conocimiento.indexar_carpeta(self.dl)

    def correr(self, frase):
        d = self.a.decidir(frase)
        return d, (self.a.ejecutar_herramienta(d) if d.herr else None)


def bloque_documentos(det_p):
    """~90 comprobaciones del bloque 4 (lectura de documentos). Devuelve (res, info)."""
    import time as _t
    from mbot_answer_flash import documentos as D
    from mbot_answer_flash import conocimiento as K
    res, info = [], {}

    def chk(etq, f):
        try:
            ok = bool(f())
        except Exception as e:
            ok, etq = False, f"{etq} [{type(e).__name__}: {e}]"
        res.append((etq, ok))

    L = lambda datos, ext, nom="x": D.leer_bytes(datos, ext, nom)
    chk("lectores registrados en LECTORES: docx xlsx pptx odt ods pdf", lambda: {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".pdf"} <= set(K.LECTORES))
    # ---- DOCX
    dx = L(docx_bytes(), ".docx", "informe.docx")
    chk("DOCX: texto con la frase clave (runs concatenados, tildes)", lambda: FRASE_CLAVE in dx.texto())
    chk("DOCX: 4 secciones por titulo (outlineLvl, nombre 'Titulo 2' y basedOn)", lambda: [s.titulo for s in dx.secciones] ==
        ["Informe de ventas 2025", "Presupuesto", "Detalle trimestral", "Conclusiones"])
    chk("DOCX: niveles 1,1,2,1 (el nivel 2 sale de basedOn)", lambda: [s.nivel for s in dx.secciones] == [1, 1, 2, 1])
    chk("DOCX: tabla detectada con cabecera y 3 filas", lambda: len(dx.tablas) == 1 and dx.tablas[0].cabecera == ["Trimestre", "Monto"] and len(dx.tablas[0].filas) == 3)
    chk("DOCX: la tabla esta dentro de su seccion", lambda: "Q2" in dx.secciones[2].texto and "450.000" in dx.secciones[2].texto)
    chk("DOCX: metadatos titulo, autor y fecha (core.xml)", lambda: dx.meta.get("titulo") == "Informe anual de ventas" and dx.meta.get("autor") == "Ana Pérez" and "2025-03-01" in dx.meta.get("fecha", ""))
    chk("DOCX sin styles.xml: Heading1 por styleId", lambda: (lambda d: [s.titulo for s in d.secciones] == ["Uno", "Dos"])(
        L(docx_bytes([("Uno", "Heading1"), ("texto a", None), ("Dos", "Heading1"), ("texto b", None)], estilos=None, tabla=[["a"]], core=False), ".docx")))
    # ---- XLSX
    xl = L(xlsx_bytes(), ".xlsx", "gastos.xlsx")
    chk("XLSX: hojas Gastos y Ventas (nombres desde workbook.xml + rels)", lambda: [t.nombre for t in xl.tablas] == ["Gastos", "Ventas"])
    chk("XLSX: salta la fila de titulo de una celda y detecta la cabecera", lambda: xl.tablas[0].cabecera == ["Fecha", "Concepto", "Monto", "Cantidad", "Costo USD"] and len(xl.tablas[0].filas) == 3)
    chk("XLSX: strings compartidos, inlineStr y numeros", lambda: xl.tablas[0].filas[0][1] == "Arriendo" and xl.tablas[1].filas[0][0] == "Lápiz" and float(xl.tablas[1].filas[1][1]) == 250.5)
    chk("XLSX: cada hoja es una seccion '# Hoja: nombre' en el texto indexable", lambda: "# Hoja: Gastos" in str(K.LECTORES[".xlsx"](xlsx_bytes())) and "Arriendo" in str(K.LECTORES[".xlsx"](xlsx_bytes())))
    # ---- PPTX / ODT / ODS
    px = L(pptx_bytes(), ".pptx", "plan.pptx")
    chk("PPTX: diapositivas en el orden de presentation.xml (no el de los archivos)", lambda: [s.titulo for s in px.secciones] ==
        ["Diapositiva 1: Resumen ejecutivo", "Diapositiva 2: Plan de trabajo", "Diapositiva 3: Cierre"])
    chk("PPTX: texto a:t de cada diapositiva", lambda: "Inversión inicial de 50.000 USD" in px.secciones[0].texto and "Fase dos" in px.secciones[1].texto)
    od = L(odt_bytes(), ".odt", "acta.odt")
    chk("ODT: titulos por outline-level, text:s y spans, tabla y metadatos", lambda: [s.nivel for s in od.secciones] == [1, 2] and "asistentes  de la comisión directiva" in od.secciones[0].texto
        and od.tablas and od.tablas[0].filas[0] == ["Marta", "Secretaria"] and od.meta.get("autor") == "Marta")
    t0 = _t.perf_counter()
    ds = L(ods_bytes(), ".ods", "x.ods")
    chk("ODS: filas/celdas repetidas (1e6) no explotan y la cabecera se detecta", lambda: _t.perf_counter() - t0 < 1.0 and ds.tablas[0].cabecera == ["Item", "Precio"] and len(ds.tablas[0].filas) == 2)
    # ---- PDF
    pdf = D.leer_bytes(pdf_bytes([PDF_P1, PDF_P2], info=b"/Title (Contrato de prueba) /Author (Luis)"), ".pdf", "c.pdf", usar_pypdf=False)
    chk("PDF: Tj y TJ extraidos, escapes \\( \\) y espacios del TJ", lambda: "Contrato de arrendamiento" in pdf.texto() and "El plazo del contrato es de doce meses (prorrogables)." in pdf.texto())
    chk("PDF: escape octal \\341 -> 'á' y paginas en el orden del arbol /Kids", lambda: "Segunda página" in pdf.secciones[1].texto and pdf.secciones[0].titulo == "Página 1" and "Contrato" in pdf.secciones[0].texto)
    chk("PDF: /Info titulo y autor", lambda: pdf.meta.get("titulo") == "Contrato de prueba" and pdf.meta.get("autor") == "Luis")
    pdf_plano = D.leer_bytes(pdf_bytes([PDF_P1], flate=False), ".pdf", "c.pdf", usar_pypdf=False)
    chk("PDF sin compresion tambien", lambda: "Contrato de arrendamiento" in pdf_plano.texto())
    imp = D.leer_bytes(pdf_bytes([PDF_CID]), ".pdf", "cid.pdf", usar_pypdf=False)
    chk("PDF imposible (CID): sin texto y aviso claro", lambda: not imp.texto().strip() and any("CID" in x or "escane" in x.lower() for x in imp.avisos))
    esc = D.leer_bytes(pdf_bytes([PDF_IMG]), ".pdf", "img.pdf", usar_pypdf=False)
    chk("PDF escaneado (solo imagen): sin texto y aviso", lambda: not esc.texto().strip() and any("escane" in x.lower() for x in esc.avisos))
    cif = D.leer_bytes(pdf_bytes([PDF_P1], trailer_extra=b"/Encrypt 99 0 R"), ".pdf", "cif.pdf", usar_pypdf=False)
    chk("PDF cifrado: aviso de cifrado y sin texto", lambda: not cif.texto().strip() and any("cifrad" in x.lower() for x in cif.avisos))
    chk("PDF: pypdf es opcional (el modulo importa sin exigirlo)", lambda: hasattr(D, "PYPDF"))

    pdf_tm = D.leer_bytes(pdf_bytes([b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Primera linea) Tj 1 0 0 1 72 700 Tm (Segunda linea) Tj 14 TL (Tercera con comilla) ' ET"]),
                          ".pdf", "tm.pdf", usar_pypdf=False)
    chk("PDF: Tm cambia de linea (y distinta) y el operador ' tambien", lambda: "Primera linea\nSegunda linea\nTercera con comilla" in pdf_tm.texto())
    chk("PDF 1.5: pagina y arbol dentro de un ObjStm comprimido", lambda: "Texto dentro de un ObjStm" in D.leer_bytes(pdf_objstm_bytes(), ".pdf", "o.pdf", usar_pypdf=False).texto())
    chk("PDF: cadenas hex UTF-16 (<FEFF...> y sin BOM) son texto", lambda: "Hello world" in D.leer_bytes(pdf_bytes([b"BT /F1 12 Tf <FEFF00480065006C006C006F> Tj <00200077006F0072006C0064> Tj ET"]), ".pdf", "u.pdf", usar_pypdf=False).texto())
    # ---- seguridad
    def _falla(datos, ext, frag):
        t = _t.perf_counter()
        try:
            L(datos, ext)
        except D.DocError as e:
            return frag in str(e).lower() and _t.perf_counter() - t < 3.0
        return False
    bomba = zip_bomba()
    chk(f"ZIP bomb ({len(bomba) // 1024} KB -> 80 MB): rechazada rapido por tamano descomprimido", lambda: _falla(bomba, ".docx", "descomprim"))
    chk("ZIP con 6000 entradas: rechazado por numero de entradas", lambda: _falla(zip_muchas(), ".docx", "entradas"))
    chk("DOCX con DOCTYPE/ENTITY: rechazado (nada se expande)", lambda: _falla(_zip({"word/document.xml": DOCX_ENTIDAD}), ".docx", "doctype"))
    chk("archivo que no es zip: DocError claro (no excepcion cruda)", lambda: _falla(b"esto no es un zip", ".docx", "zip"))

    def _sin_hojas():
        try:
            return not L(_zip({"x": "y"}), ".xlsx").tablas
        except D.DocError:
            return True
    chk("xlsx sin hojas legibles: DocError o documento vacio, nunca excepcion cruda", _sin_hojas)

    # ---- indexado con los lectores
    w = _MundoDoc(det_p, "d1", extra={"bomba.docx": bomba, "entidad.docx": _zip({"word/document.xml": DOCX_ENTIDAD}), "imposible.pdf": pdf_bytes([PDF_CID])})
    C = w.a.conocimiento
    chk(f"indexar: formatos nuevos entran; bomba y DOCTYPE se omiten sin romper ({w.st})", lambda: w.st["omitidos"] >= 2 and w.st["archivos"] >= 8)
    nom = lambda q: [os.path.basename(h.ruta) for h in C.buscar(q).hallazgos]
    chk("indexado: contenido de DOCX ('control del presupuesto')", lambda: nom("control del presupuesto trimestre")[:1] == ["informe.docx"])
    chk("indexado: celda de XLSX ('Transporte')", lambda: "gastos.xlsx" in nom("Transporte"))
    chk("indexado: diapositiva de PPTX ('levantamiento de requisitos')", lambda: nom("levantamiento de requisitos")[:1] == ["plan.pptx"])
    chk("indexado: ODT ('comisión directiva')", lambda: "acta.odt" in nom("comision directiva"))
    chk("indexado: PDF ('prorrogables')", lambda: nom("prorrogables")[:1] == ["contrato.pdf"])
    chk("indexado: el titulo del trozo lleva la seccion ('› Presupuesto')", lambda: any("› Presupuesto" in h.titulo for h in C.buscar("marketing aumentó").hallazgos))
    chk("indexado: lo rechazado no deja texto ('EXPANDIDO' no existe)", lambda: not C.buscar("EXPANDIDO").hallazgos)
    r2 = C.reindexar()
    chk("reindexar sin cambios: 0 nuevos y 0 modificados", lambda: r2["nuevos"] == 0 and r2["modificados"] == 0)

    # ---- resumen
    txt = dx.texto()
    rs = D.resumir(txt, n=4)
    chk("resumen: 3-5 frases y contiene la frase clave", lambda: 3 <= len(rs) <= 5 and any(FRASE_CLAVE in x for x in rs))
    chk("resumen: frases en su orden original", lambda: [txt.index(x) for x in rs] == sorted(txt.index(x) for x in rs))
    chk("resumen textrank: contiene la frase clave", lambda: any(FRASE_CLAVE in x for x in D.resumir(txt, n=4, metodo="textrank")))
    chk("resumen: texto vacio o de una frase no falla", lambda: D.resumir("", 3) == [] and len(D.resumir("Solo una frase corta aqui.", 3)) == 1)
    # ---- pregunta sobre el documento
    rp = D.responder_doc(dx, "presupuesto de marketing")
    chk("preguntar_doc: la mejor frase habla del marketing (15%) y trae su seccion", lambda: rp and "15%" in rp[0][1] and rp[0][0] == "Presupuesto")
    chk("preguntar_doc: maximo 3 frases", lambda: 1 <= len(rp) <= 3)
    chk("preguntar_doc: tema ausente -> lista vacia", lambda: D.responder_doc(dx, "cohetes espaciales") == [])
    chk("preguntar_doc en PPTX: 'inversión inicial' -> diapositiva 1", lambda: (lambda r: r and "50.000" in r[0][1] and r[0][0].startswith("Diapositiva 1"))(D.responder_doc(px, "inversión inicial")))
    # ---- entidades
    en = D.entidades(txt)
    v = lambda k: [x[0] for x in en[k]]
    chk("entidades: fechas dd/mm/aaaa y '12 de abril de 2025'", lambda: "15/03/2025" in v("fechas") and "12 de abril de 2025" in v("fechas"))
    chk("entidades: montos con $, CLP y USD", lambda: any("1.500.000" in x for x in v("montos")) and any("2.300.000" in x for x in v("montos")) and any("50.000" in x[0] for x in D.entidades("Inversión de 50.000 USD")["montos"]))
    chk("entidades: monto normalizado (1.234,56 -> 1234.56)", lambda: D.entidades("Total $1.234,56")["montos"][0][1] == 1234.56)
    chk("entidades: email y telefono (+56 9 1234 5678)", lambda: v("emails") == ["ana@ejemplo.com"] and any("+56 9 1234 5678" in x for x in v("telefonos")))
    chk("entidades: el telefono no confunde fechas, RUT ni montos", lambda: not any(x for x in v("telefonos") if "2025" in x or "12.345" in x or "1.500" in x))
    chk("entidades: RUT valido 12.345.678-5 marcado valido", lambda: ("12.345.678-5", True) in [(x[0], x[1]) for x in en["ruts"]])
    chk("entidades: RUT invalido 12.345.678-9 marcado invalido", lambda: ("12.345.678-9", False) in [(x[0], x[1]) for x in en["ruts"]])
    chk("entidades: RUT 11.111.111-1 valido", lambda: D.entidades("rut 11.111.111-1")["ruts"][0][1] is True)
    chk("entidades: DNI 12345678Z valido y 12345678A invalido", lambda: ("12345678Z", True) in [(x[0], x[1]) for x in en["dnis"]] and ("12345678A", False) in [(x[0], x[1]) for x in en["dnis"]])
    chk("entidades: URL sin la puntuacion final", lambda: v("urls") == ["https://ejemplo.com/informe"])
    chk("entidades: texto sin entidades -> todo vacio", lambda: all(not x for x in D.entidades("hola que tal").values()))
    # ---- tablas
    chk("tabla: suma de Monto en es-CL (1.234,56 + 2.000,00 + 500,50 = 3735.06)", lambda: abs(D.operar_columna(xl, "Monto", "suma")["valor"] - 3735.06) < 1e-9)
    chk("tabla: promedio de Ventas (hoja Ventas) = 216.83", lambda: abs(D.operar_columna(xl, "Ventas", "promedio")["valor"] - 216.8333333) < 1e-5)
    chk("tabla: nombre de columna difuso ('monto', 'Mnto', 'cantidad')", lambda: D.operar_columna(xl, "monto", "suma")["columna"] == "Monto" and D.operar_columna(xl, "Mnto", "suma")["columna"] == "Monto"
        and D.operar_columna(xl, "cantidad", "suma")["valor"] == 6)
    chk("tabla: formato en-US en la columna 'Costo USD' (1,234.50 + 2,000.00 + 300.25)", lambda: abs(D.operar_columna(xl, "Costo USD", "suma")["valor"] - 3534.75) < 1e-9)
    chk("tabla: minimo, maximo y conteo", lambda: D.operar_columna(xl, "Ventas", "min")["valor"] == 100 and D.operar_columna(xl, "Ventas", "max")["valor"] == 300 and D.operar_columna(xl, "Ventas", "conteo")["valor"] == 3)
    chk("tabla: DOCX tambien (suma Monto de la tabla = 1.270.000)", lambda: D.operar_columna(dx, "Monto", "suma")["valor"] == 1270000)
    chk("tabla: columna inexistente -> error legible, sin excepcion", lambda: (lambda r: r.get("error") and "Zzz" in r["error"])(D.operar_columna(xl, "Zzz", "suma")))
    chk("numeros: 1.234,56 | 1,234.56 | 1.234 | (1.500) | $ 2.000 | abc", lambda: [D.parsear_numero(x) for x in ("1.234,56", "1,234.56", "1.234", "(1.500)", "$ 2.000", "abc")] == [1234.56, 1234.56, 1234, -1500, 2000, None])
    chk("numeros: 0,5 es decimal y 1.234.567 es miles", lambda: D.parsear_numero("0,5") == 0.5 and D.parsear_numero("1.234.567") == 1234567)
    # ---- clasificacion, tipo: y estadisticas
    chk("clasificacion: factura, contrato, cv, informe, receta, acta y otro", lambda: all(D.clasificar(t) == k for k, t in TIPOS_TXT.items()))
    chk("clasificacion de los documentos de prueba (informe/contrato)", lambda: D.clasificar(txt, "informe.docx") == "informe" and D.clasificar(D.leer_bytes(pdf_bytes([PDF_P1]), ".pdf", "c.pdf", usar_pypdf=False).texto()) == "contrato")
    tipo = lambda q: sorted(os.path.basename(h.ruta) for h in C.buscar(q).hallazgos)
    chk("tipo:factura filtra solo la factura", lambda: tipo("tipo:factura") == ["factura.docx"])
    chk("tipo:receta + terminos ('harina tipo:receta')", lambda: tipo("harina tipo:receta") == ["receta_pan.docx"])
    chk("tipo:contrato no devuelve la factura; tipo inexistente -> nada", lambda: "factura.docx" not in tipo("tipo:contrato") and not tipo("tipo:marciano"))
    est = D.estadisticas(txt)
    chk("estadisticas: palabras, minutos de lectura >= 1, idioma es y top de terminos", lambda: est["palabras"] > 80 and est["minutos"] >= 1 and est["idioma"] == "es" and "presupuesto" in [t for t, _n in est["top"]])
    chk("estadisticas: texto en ingles -> en", lambda: D.estadisticas("The report shows that the budget was spent in the first quarter and the team is happy with the results of the year")["idioma"] == "en")

    # ---- herramientas y decidir (nada se ejecuta fuera de Python)
    sel = lambda fr, h: (lambda d: d.herr == h and d.accion == "ejecutar")(w.a.decidir(fr))
    chk("'lee el informe.docx' -> @leer", lambda: sel("lee el informe.docx", "leer"))
    r = w.correr("lee el informe.docx")[1]
    chk("@leer: metadatos, indice de secciones con palabras, tipo, tiempo de lectura y resumen", lambda: r.ok and "Informe anual de ventas" in r.texto and "Presupuesto" in r.texto and "palabras" in r.texto
        and "tipo: informe" in r.texto.lower() and "min" in r.texto and FRASE_CLAVE in r.texto)
    chk("'abre y resume Descargas\\gastos.xlsx' -> @leer (alias de carpeta)", lambda: sel("abre y resume Descargas\\gastos.xlsx", "leer"))
    chk("@leer de un XLSX lista las hojas", lambda: "Gastos" in w.correr("lee gastos.xlsx")[1].texto and "Ventas" in w.correr("lee gastos.xlsx")[1].texto)
    chk("'resume el contrato' (nombre sin extension) -> @leer del contrato.pdf", lambda: "prorrogables" in w.correr("resume el contrato")[1].texto)
    chk("'muéstrame la sección 3' (tras leer el informe) -> 'Detalle trimestral'", lambda: (w.correr("lee el informe.docx"), "Detalle trimestral" in w.correr("muéstrame la sección 3")[1].texto and sel("muéstrame la sección 3", "seccion"))[1])
    chk("@seccion fuera de rango -> error legible", lambda: (lambda r: not r.ok and "9" in r.texto)(w.correr("muéstrame la sección 9 del informe.docx")[1]))
    chk("'¿qué dice el informe.docx sobre el presupuesto?' -> @preguntar_doc (no @buscar)", lambda: sel("¿qué dice el informe.docx sobre el presupuesto?", "preguntar_doc"))
    rq = w.correr("¿qué dice el informe.docx sobre el presupuesto de marketing?")[1]
    chk("@preguntar_doc responde con frase y seccion", lambda: rq.ok and "15%" in rq.texto and "Presupuesto" in rq.texto)
    chk("'¿qué fechas aparecen en el informe.docx?' -> @entidades fechas", lambda: sel("¿qué fechas aparecen en el informe.docx?", "entidades") and "15/03/2025" in w.correr("¿qué fechas aparecen en el informe.docx?")[1].texto)
    chk("'qué RUT hay en el informe.docx' lista el valido y el invalido", lambda: (lambda t: "12.345.678-5" in t and "12.345.678-9" in t and "inv" in t.lower())(w.correr("qué RUT hay en el informe.docx")[1].texto))
    chk("'¿cuánto suma la columna Monto en gastos.xlsx?' -> @tabla = 3.735,06", lambda: sel("¿cuánto suma la columna Monto en gastos.xlsx?", "tabla") and "3.735,06" in w.correr("¿cuánto suma la columna Monto en gastos.xlsx?")[1].texto)
    chk("'promedio de Ventas' tras leer gastos.xlsx -> @tabla (documento reciente)", lambda: (w.correr("lee gastos.xlsx"), sel("promedio de Ventas", "tabla") and "216,83" in w.correr("promedio de Ventas")[1].texto)[1])
    chk("'el máximo de la columna Cantidad en gastos.xlsx' -> 3", lambda: w.correr("el máximo de la columna Cantidad en gastos.xlsx")[1].datos.get("valor") == 3)
    # desambiguacion
    w2 = _MundoDoc(det_p, "d2", extra={"informe_ventas.docx": docx_bytes(), "informe_gastos.docx": docx_bytes()})
    chk("desambiguacion: 'lee el informe' con 3 coincidencias pregunta cual (no elige)", lambda: (lambda r: not r.ok and "informe_ventas.docx" in r.texto and "informe_gastos.docx" in r.texto and "cual" in r.texto.lower())(w2.correr("lee el informe")[1]))
    chk("desambiguacion: nombre unico ('el contrato') se resuelve solo", lambda: w.correr("lee el contrato")[1].ok)
    chk("desambiguacion: documento inexistente -> mensaje, sin excepcion", lambda: (lambda r: not r.ok and "no encuentro" in r.texto.lower())(w.correr("lee el pagare.docx")[1]))
    # no robar frases
    chk("'abre el archivo informe.docx' sigue abriendo (no @leer)", lambda: w.a.decidir("abre el archivo informe.docx").herr is None)
    chk("@buscar intacto: 'que se sobre el wifi' y 'qué dice mi archivo sobre el wifi'", lambda: w.a.decidir("que se sobre el wifi").herr == "buscar" and w.a.decidir("qué dice mi archivo sobre el wifi").herr == "buscar")
    chk("buscar archivos y Google intactos", lambda: w.a.decidir("busca archivos pdf en Descargas").herr == "buscar_archivos" and w.a.decidir("busca recetas de pan en google").cmd.startswith('start "" "https://www.google.com'))
    chk("calculadora intacta: 'cuánto es 2+2' y 'cuánto suma 2+2'", lambda: w.a.decidir("cuánto es 2+2").herr == "calcular" and w.a.decidir("cuánto suma 2+2").herr != "tabla")
    negs = ["lee un libro", "resume la historia de roma", "lee mi navegador", "qué dice el periódico", "extrae las muelas", "suma de gastos del mes",
            "cuánto suma el total de la factura de la luz", "qué fechas hay en navidad"]
    chk("negativas: ninguna herramienta de documentos con frases cotidianas", lambda: not [f for f in negs if w.a.decidir(f).herr in ("leer", "seccion", "preguntar_doc", "entidades", "tabla")])
    chk("'promedio de mis notas' sin documento reciente no toma @tabla", lambda: _nuevo(det_p, "d3.json").decidir("promedio de mis notas").herr != "tabla")

    # seguridad de rutas / formatos
    def _no_lee(fr, frag=None):
        d, r_ = w.correr(fr)
        return r_ is None or (not r_.ok and (frag is None or frag in r_.texto.lower()))
    chk("@leer no lee un archivo que no es documento (win.ini)", lambda: _no_lee("lee C:\\Windows\\win.ini"))
    chk("@leer de una ruta inexistente: mensaje claro", lambda: _no_lee("lee C:\\no\\existe\\x.docx"))
    chk("@leer de la bomba: error legible, no cuelga", lambda: (lambda r_: r_ is not None and not r_.ok and "descomprim" in r_.texto.lower())(w.correr("lee bomba.docx")[1]))
    chk("ninguna decision de documentos es peligrosa (siempre una herramienta interna @)", lambda: w.correr("lee gastos.xlsx") and all(not w.a.decidir(f).peligroso and str(w.a.decidir(f).cmd).startswith("@") for f in ("lee el informe.docx", "promedio de Ventas", "¿qué fechas aparecen en el informe.docx?")))
    barrido = [f for f in [x[1] for x in Q if isinstance(x[2], (str, type(None)))] + [f for f, _e in DESARROLLO] + HNEG + [f for f, _h in HSEL] + PREGUNTAS_SIN_RESPUESTA
               if w.a.decidir(f).herr in ("leer", "seccion", "preguntar_doc", "entidades", "tabla")]
    chk(f"barrido: ninguna frase de los bancos Q+DESARROLLO+HNEG+HSEL elige una herramienta de documentos {barrido[:2]}", lambda: not barrido)
    # !porque
    w.correr("¿qué dice el informe.docx sobre el presupuesto de marketing?")
    chk("!porque explica documento y seccion usados", lambda: (lambda t: "informe.docx" in t and "Presupuesto" in t)(w.a.explicar(w.a.ultima_decision)))

    # ---- latencia de lectura de un DOCX de ~50 paginas
    cuerpo = []
    for i in range(1, 51):
        cuerpo.append((f"Capítulo {i}", "Ttulo1"))
        for j in range(10):
            cuerpo.append((_palabras_lorem(55, i * 100 + j) + ".", None))
    grande = docx_bytes(cuerpo, tabla=[["a"]])
    t0 = _t.perf_counter()
    dg = L(grande, ".docx", "grande.docx")
    lect = _t.perf_counter() - t0
    t0 = _t.perf_counter()
    D.resumir(dg.texto(), 4)
    resm = _t.perf_counter() - t0
    info.update(docx_kb=len(grande) // 1024, docx_palabras=len(dg.texto().split()), docx_s=lect, resumen_s=resm, docx_sec=len(dg.secciones))
    chk(f"DOCX de ~50 paginas ({info['docx_palabras']} palabras, {info['docx_sec']} secciones): lectura {lect * 1000:.0f} ms < 1 s, resumen {resm * 1000:.0f} ms < 1 s",
        lambda: lect < 1.0 and resm < 1.0 and info["docx_sec"] == 50)
    return res, info



# ---------------------------------------------------------------- adaptadores
class E1:
    nombre = "v1"
    def __init__(s, ruta):
        s.m = v1.Memoria(ruta)
        for f, c in ENSENAR: s.m.aprender(f, c)
    def decidir(s, frase):
        r = s.m.buscar(frase)
        conf, i = r[0] if r else (0.0, -1)
        acc = "ejecutar" if conf >= v1.UMBRAL_EJECUTAR else "preguntar" if conf >= v1.UMBRAL_PREGUNTAR else "ensenar"
        return acc, (s.m.tareas[i]["cmd"] if i >= 0 else None), conf


class E2:
    nombre = "v2"
    def __init__(s, ruta, desc, ens=None):
        s.a = v2.Asistente(ruta, desc, auto_descubrir=False)
        for f, c in (ENSENAR + ENSENAR_V2 if ens is None else ens): s.a.aprender(f, c)
    def decidir(s, frase):
        d = s.a.decidir(frase)
        return d.accion, d.cmd, d.conf
    def plan(s, frase):
        p = s.a.planear(frase)
        return [d.cmd for d in p] if p else None


# ---------------------------------------------------------------- BLOQUE 5: CONVERSACION (capa K) -- escrito ANTES de implementar mbot_answer_flash/conversacion.py
# Todo con la API y con la consola de mentira: `input` y el ejecutor (ejecucion.ejecutar_ex) simulados; NUNCA se lanza un proceso ni se lee stdin.
import builtins, contextlib, io, types as _types
from datetime import timedelta

CONV_INTENCIONES = [      # (intencion, variantes con typos y alargamientos): detecta(frase) debe contener la intencion
    ("saludo", ["hola", "holaaa", "Buenas tardes!", "buenos días", "qué tal", "wena", "ola"]),
    ("despedida", ["chao", "adiós", "nos vemos", "hasta luego", "chaooo"]),
    ("agradecimiento", ["gracias", "graciass", "muchas gracias", "te pasaste", "genial gracias", "gracais"]),
    ("estado", ["cómo estás", "como estas?", "como andas", "que tal estas", "komo estas"]),
    ("identidad", ["quién eres", "como te llamas", "quien eres tu", "kien eres"]),
    ("capacidad", ["qué puedes hacer", "ayuda", "que sabes hacer", "ayudaa", "para qué sirves"]),
    ("afirmacion", ["sí", "ok", "dale", "okey", "siii"]),
    ("negacion", ["no", "nada", "nop", "no gracias"]),
    ("elogio", ["bien", "buena", "eres genial", "buen trabajo", "geniall"]),
    ("queja", ["no sirves", "tonto", "eres inútil", "no funciona", "no entiendes nada"]),
    ("risa", ["jaja", "jsjs", "jajajaja", "jejeje", "lol"]),
    ("disculpa", ["perdón", "perdon", "disculpa", "lo siento", "perdoon"]),
    ("perdido", ["no sé qué hacer", "estoy aburrido", "me aburro", "no se que hacer"]),
    ("fechahora", ["que ora es", "q dia es hoy", "qué fecha es"]),
]


def _consola_falsa(a, frase, resp=(), log=None):
    """Procesa UNA linea con la consola real (consola.procesar_linea) pero con input y ejecutor simulados.
    Devuelve SimpleNamespace(out, ran, prompts, eof). `ran` = comandos que habrian llegado al shell."""
    from mbot_answer_flash import consola, ejecucion
    it = iter(resp)
    prompts, ran = [], []

    def falso_input(p=""):
        prompts.append(p)
        if log is not None:
            log.append(("input", p))
        try:
            return next(it)
        except StopIteration:
            raise EOFError("sin mas respuestas simuladas")

    def falso_exec(cmd, imprimir=True):
        ran.append(cmd)
        if log is not None:
            log.append(("exec", cmd))
        return ejecucion.EjecRes(True, 0, "")
    a.verificador.verificar_async = lambda *x, **k: None
    old = (builtins.input, ejecucion.ejecutar_ex)
    builtins.input, ejecucion.ejecutar_ex = falso_input, falso_exec
    buf, eof = io.StringIO(), False
    try:
        with contextlib.redirect_stdout(buf):
            consola.procesar_linea(a, frase)
    except EOFError:
        eof = True
    finally:
        builtins.input, ejecucion.ejecutar_ex = old
    return _types.SimpleNamespace(out=buf.getvalue(), ran=ran, prompts=prompts, eof=eof)


def _tarea_de(a, cmd):
    i = a._tarea(cmd)
    return a.tareas[i] if i is not None else None


def bloque_peticiones(det_p):
    """Comprueba desde la consola que la intención se distinga antes de elegir un comando."""
    casos = [
        ("¿Cómo abro la calculadora?", "«Calculadora»", []),
        ("Dime cómo puedo abrir el bloc de notas", "«Bloc de notas»", []),
        ("Explícame cómo se abre el explorador", "«Explorador de archivos»", []),
        ("¿Cómo hago para iniciar Paint?", "«Paint»", []),
        ("¿Cómo abrir el programa que me mandaron?", "¿Es una aplicación", []),
        ("Abre la calculadora", "start calc", ["start calc"]),
        ("No abras la calculadora", "omito esa acción", []),
        ("No me abras el bloc de notas", "omito esa acción", []),
        ("No quiero que apagues la computadora", "omito esa acción", []),
        ("Porfa, no abras la calculadora", "omito esa acción", []),
        ("No abras la calculadora, dime cuánto es 17 por 9", "= 153", []),
        ("No la abras, solo dime cuánto es 17 por 9", "= 153", []),
        ("No cierres el programa y dime cuánto da 4 por 12", "= 48", []),
        ("No abras la calculadora. ¿Cuánto es 2,5 por 4?", "= 10", []),
        ("No abras Paint, solo dime cuánto es 9 dividido por 0", "fallo", []),
    ]
    a = _nuevo(det_p, "peticiones.json")
    res = []
    for frase, esperado, acciones in casos:
        s = _consola_falsa(a, frase)
        res.append((frase, esperado in s.out and s.ran == acciones and not s.prompts))
    s = _consola_falsa(a, "!porque")
    res.append(("!porque describe la negación y el cálculo", "negar una acción y pedir un cálculo" in s.out))
    a.herr.poner("calcular", False)
    s = _consola_falsa(a, "No abras Paint, dime cuánto es 3 por 4")
    res.append(("respeta que @calcular está deshabilitada", "deshabilitada" in s.out and not s.ran and not s.prompts))
    return res


def bloque_eleccion_respuesta(det_p):
    """Pares en español que comparten palabras y exigen respuestas distintas."""
    a = _nuevo(det_p, "eleccion_respuesta.json")
    casos = [
        ("Quiero apuntar una idea", ("Comprar té",), "guardada: Comprar té", [], "¿Qué quieres anotar?"),
        ("Necesito dejar anotado algo", ("Revisar los apuntes",), "guardada: Revisar los apuntes", [], "¿Qué quieres anotar?"),
        ("Quisiera anotar algo rápido", ("",), "Cancelado", [], "¿Qué quieres anotar?"),
        ("Anotar una idea rapida", ("",), "Cancelado", [], "¿Qué quieres anotar?"),
        ("Anota llamar a Antonia", (), "guardada: llamar a Antonia", [], ""),
        ("Abre el bloc de notas", (), "start notepad", ["start notepad"], ""),
        ("Pinta la muralla de verde", (), "fuera de mi alcance", [], ""),
        ("Píntame la puerta de blanco", (), "fuera de mi alcance", [], ""),
        ("Apaga la tele", (), "fuera de mi alcance", [], ""),
        ("Necesito encender la estufa", (), "fuera de mi alcance", [], ""),
        ("¿Puedes prender el ventilador?", (), "fuera de mi alcance", [], ""),
        ("Abre Paint", (), "start mspaint", ["start mspaint"], ""),
        ("No prendas la televisión", (), "omito esa acción", [], ""),
        ("!porque", (), "negar una acción", [], ""),
        ("¿Cómo abro el bloc de notas?", (), "«Bloc de notas»", [], ""),
    ]
    res = []
    for frase, respuestas, texto, acciones, prompt in casos:
        s = _consola_falsa(a, frase, resp=respuestas)
        res.append((frase, texto in s.out and s.ran == acciones and not s.eof
                    and (len(s.prompts) == 1 and prompt in s.prompts[0] if prompt else not s.prompts)))
    a.aprender("prende el ventilador", "start ventilador")
    s = _consola_falsa(a, "prende el ventilador")
    res.append(("una asociación exacta aprendida se respeta", s.ran == ["start ventilador"] and not s.prompts))
    a.herr.poner("nota_agregar", False)
    s = _consola_falsa(a, "quisiera anotar una idea")
    res.append(("respeta que @nota_agregar está deshabilitada",
                "deshabilitada" in s.out and not s.ran and not s.prompts))
    return res


def bloque_aprendizaje(det_p):
    """Casos de desarrollo con una asociación incorrecta sembrada por escenario."""
    casos = [
        ("abre mi editor de apuntes", "start mspaint", "start notepad",
         ("abre el editor para mis apuntes", "inicia mi editor de apuntes", "quiero abrir el editor de apuntes")),
        ("abre mi herramienta de cuentas", "start notepad", "start calc",
         ("inicia mi herramienta de cuentas", "abre la herramienta para mis cuentas", "pon mi herramienta de cuentas")),
        ("abre mi espacio de dibujo", "start calc", "start mspaint",
         ("inicia mi espacio de dibujo", "quiero abrir mi espacio de dibujo", "abre el espacio para dibujar")),
    ]
    ajenas = ("dime mi ip", "abre el explorador", "qué hora es", "cuánto es 5 por 3")
    resultados = []
    for n, (frase, previo, objetivo, variantes) in enumerate(casos):
        a = _nuevo(det_p, f"aprendizaje_{n}.json")
        a.aprender(frase, previo)

        def resultado(f):
            d = a.decidir(f)
            return d.accion, d.cmd

        antes = [resultado(f) for f in ajenas]
        base = _consola_falsa(a, frase)
        antes_variantes = [resultado(f) == ("ejecutar", objetivo) for f in variantes]
        correccion = _consola_falsa(a, "no", resp=(objetivo,))
        corregida = resultado(frase) == ("ejecutar", objetivo)
        despues_variantes = [resultado(f) == ("ejecutar", objetivo) for f in variantes]
        ajenas_intactas = sum(resultado(f) == esp for f, esp in zip(ajenas, antes))

        # Una segunda corrección restaura la asociación anterior mediante el mismo flujo.
        seguida = _consola_falsa(a, frase)
        reparacion = _consola_falsa(a, "no", resp=(previo,))
        revertida = (seguida.ran == [objetivo] and "Aprendido" in reparacion.out
                     and resultado(frase) == ("ejecutar", previo))
        resultados.append((base.ran == [previo] and "Aprendido" in correccion.out and corregida,
                           sum(antes_variantes), sum(despues_variantes), ajenas_intactas, revertida))
    columnas = [sum(xs) for xs in zip(*resultados)]
    corregidas, antes, despues, intactas, revertidas = columnas
    n, v = len(casos), sum(len(c[3]) for c in casos)
    print(f"APRENDIZAJE (desarrollo): frases corregidas {corregidas}/{n}, paráfrasis {antes}/{v} -> {despues}/{v}, "
          f"frases ajenas intactas {intactas}/{n * len(ajenas)}, restauradas por segunda corrección {revertidas}/{n}.")


def bloque_conversacion(det_p, frases_previas):
    """Devuelve (resultados, info). `frases_previas`: todas las frases que vieron decidir()/personal.procesar() en los bloques anteriores."""
    res = []

    def chk(etq, cond):
        res.append((etq, bool(cond)))

    def nuevo(nombre, nombre_usuario=None):
        x = _nuevo(det_p, nombre)
        x.personal.hechos.clear()
        if nombre_usuario:
            x.personal.procesar(f"mi nombre es {nombre_usuario}")
        x.conv.reloj = lambda: AHORA0
        return x
    a = nuevo("conv1.json")
    # ---- 1. intenciones: 3 a 5 variantes con typos y alargamientos por intencion
    for it, vs in CONV_INTENCIONES:
        mal = [v for v in vs if it not in (a.conv.detecta(v) or [])]
        chk(f"intencion {it}: {len(vs)} variantes (fallan {mal})", not mal)
    # fechahora: NO se roban; lo que ya resuelven las herramientas sigue siendo de ellas
    mal = []
    for f, h in [("que hora es", "hora"), ("qué día es hoy", "fecha"), ("dime la hora", "hora"), ("dime la fecha", "fecha")]:
        d = a.decidir(f)
        k = a.conv.atender(f, d)
        if not (d.herr == h and d.accion == "ejecutar" and k is None):
            mal.append(f)
    chk(f"hora/fecha: la herramienta sigue ganando y K no responde ({mal})", not mal)
    a.ctx.reloj = lambda: AHORA0
    s = _consola_falsa(a, "que ora es")
    chk(f"'que ora es' (typo) se reencamina a @hora ({s.out.strip()[:40]!r})", "10:00" in s.out and not s.prompts)
    # varias intenciones en una frase
    chk("'hola, como estas' = saludo + estado", {"saludo", "estado"} <= set(a.conv.detecta("hola, ¿cómo estás?") or []))
    chk("'abre la calculadora, gracias' NO es conversacion pura", a.conv.detecta("abre la calculadora, gracias") is None)

    # ---- 2. saludo con contexto: hora del dia, nombre, recordatorios, primer saludo del dia
    def saluda(x, hora, dia=0, frase="hola"):
        x.conv.reloj = lambda: AHORA0.replace(hour=hora) + timedelta(days=dia)
        k = x.conv.atender(frase, x.decidir(frase))
        return k.texto if k else ""
    b = nuevo("conv2.json", "Ana")
    t = saluda(b, 10)
    chk(f"saludo 10h con nombre -> {t[:45]!r}", "Buenos días" in t and "Ana" in t)
    t = saluda(nuevo("conv3.json", "Ana"), 15)
    chk(f"saludo 15h -> buenas tardes, Ana ({t[:45]!r})", "Buenas tardes" in t and "Ana" in t)
    t = saluda(nuevo("conv4.json", "Ana"), 22)
    chk(f"saludo 22h -> buenas noches ({t[:45]!r})", "Buenas noches" in t)
    t = saluda(nuevo("conv5.json"), 15)
    chk(f"saludo sin nombre: sin 'None', sin coma-nombre ({t[:45]!r})", "None" not in t and "Ana" not in t and "Buenas tardes" in t)
    t = saluda(nuevo("conv5b.json", "ana maria"), 15, frase="buenas")
    chk(f"nombre compuesto en minusculas -> 'Ana' capitalizado ({t[:45]!r})", "Ana" in t)
    r = nuevo("conv6.json", "Ana")
    r.personal.procesar("recuérdame hoy a las 15 llamar a Juan")
    t1 = saluda(r, 11)
    chk(f"primer saludo del dia: recordatorio de hoy + !hoy ({t1[-90:]!r})", "llamar a Juan" in t1 and "!hoy" in t1)
    t2 = saluda(r, 11)
    chk(f"segundo saludo del mismo dia: sin resumen ({t2!r})", "!hoy" not in t2 and "Juan" not in t2)
    t3 = saluda(r, 11, dia=1)
    chk(f"al dia siguiente vuelve el resumen (sin recordatorios hoy) ({t3[-70:]!r})", "!hoy" in t3 and "Juan" not in t3)
    seguidos = [saluda(r, 16) for _ in range(8)]
    chk(f"8 saludos seguidos: nunca dos iguales consecutivos ({len(set(seguidos))} distintos)",
        all(x != y for x, y in zip(seguidos, seguidos[1:])) and len(set(seguidos)) >= 3)
    seg_g = []
    for f in ["gracias", "gracias", "gracias", "gracias", "gracias"]:
        k = r.conv.atender(f, r.decidir(f))
        seg_g.append(k.texto if k else "")
    chk("5 agradecimientos seguidos: nunca repite la ultima plantilla", all(x != y for x, y in zip(seg_g, seg_g[1:])))

    # ---- 3. "que puedes hacer": generado del registro real, siempre al dia
    c = nuevo("conv7.json")
    for _ in range(4):
        c.aprender("prende el ventilador", "start ventilador")
    k = c.conv.atender("qué puedes hacer", c.decidir("qué puedes hacer"))
    txt = k.texto if k else ""
    n_ej = txt.count("«")
    chk(f"'que puedes hacer': de 4 a 6 ejemplos concretos ({n_ej})", 4 <= n_ej <= 6)
    chk("refleja el plugin dado (tira un dado)", "tira un dado" in txt)
    chk("refleja lo aprendido ('prende el ventilador')", "prende el ventilador" in txt)
    c.herr.poner("dado", False)
    c._cache_an.clear()
    txt2 = c.conv.atender("que puedes hacer", c.decidir("que puedes hacer")).texto
    chk("tras '!herramienta off dado' ya no lo menciona", "tira un dado" not in txt2)
    c.herr.poner("dado", True)
    from mbot_answer_flash import herramientas as _H
    _H._ORIGEN[0] = "plugin:demo.py"
    try:
        @_H.herramienta("demo_k", verbos=("*",), objetos=("*",), descripcion="plugin de prueba: 'saluda al planeta'")
        def _demo_k(ctx):
            return "x"
    finally:
        _H._ORIGEN[0] = "interna"
    try:
        txt3 = c.conv.atender("ayuda", c.decidir("ayuda")).texto
        chk("un plugin registrado en caliente aparece sin tocar texto fijo", "saluda al planeta" in txt3)
    finally:
        _H.REGISTRO.pop("demo_k", None)
    txts = {c.conv.atender("que sabes hacer", c.decidir("que sabes hacer")).texto for _ in range(4)}
    chk("la respuesta rota ejemplos (no es un texto fijo)", len(txts) >= 2)

    # ---- 4. queja: humildad, !porque, y conexion con el refuerzo G
    q = nuevo("conv8.json")
    k = q.conv.atender("no sirves", q.decidir("no sirves"))
    chk(f"queja sin accion previa: humilde y ofrece !porque ({(k.texto if k else '')[:50]!r})",
        k is not None and "!porque" in k.texto and not k.corregir)
    s0 = _consola_falsa(q, "abre el bloc de notas")
    t0 = _tarea_de(q, "start notepad")
    f0 = t0["f"]
    s = _consola_falsa(q, "no sirves", resp=[""])
    chk(f"queja justo tras una accion: se conecta con G (fallos {f0} -> {_tarea_de(q, 'start notepad')['f']:.1f})",
        _tarea_de(q, "start notepad")["f"] > f0 and "cuál era el comando correcto" in " ".join(s.prompts).lower() and not s.ran)
    q2 = nuevo("conv9.json")
    _consola_falsa(q2, "abre el bloc de notas")
    f1 = _tarea_de(q2, "start notepad")["f"]
    s = _consola_falsa(q2, "eso no", resp=[""])
    chk("el flujo 'eso no' de G sigue intacto (penaliza y pregunta)", _tarea_de(q2, "start notepad")["f"] > f1 and s.prompts)
    q3 = nuevo("conv10.json")
    _consola_falsa(q3, "abre el bloc de notas")
    f2 = _tarea_de(q3, "start notepad")["f"]
    s = _consola_falsa(q3, "tonto")
    chk("un insulto no penaliza la tarea ni pregunta nada", _tarea_de(q3, "start notepad")["f"] == f2 and not s.prompts and not s.ran)
    q4 = nuevo("conv11.json")
    _consola_falsa(q4, "abre el bloc de notas")
    _consola_falsa(q4, "jaja")
    f3 = _tarea_de(q4, "start notepad")["f"]
    _consola_falsa(q4, "no sirves", resp=[""])
    chk("queja con una charla en medio ya no es 'justo antes': no penaliza", _tarea_de(q4, "start notepad")["f"] == f3)

    # ---- 5. gracias tras una accion exitosa: acierto suave en G (documentado en conversacion.py)
    g = nuevo("conv12.json")
    _consola_falsa(g, "abre el bloc de notas")
    a0 = _tarea_de(g, "start notepad")["a"]
    _consola_falsa(g, "gracias")
    a1 = _tarea_de(g, "start notepad")["a"]
    _consola_falsa(g, "gracias")
    a2 = _tarea_de(g, "start notepad")["a"]
    chk(f"gracias tras accion exitosa suma un acierto suave ({a0:.2f} -> {a1:.2f}), una sola vez ({a2:.2f})", 0 < a1 - a0 <= 0.5 and a2 == a1)
    g2 = nuevo("conv13.json")
    a0 = _tarea_de(g2, "start notepad")["a"]
    _consola_falsa(g2, "gracias")
    chk("gracias sin accion previa no toca ninguna tarea", _tarea_de(g2, "start notepad")["a"] == a0)

    # ---- 6. fallback: charla frente a orden
    f = nuevo("conv14.json")
    mal = []
    for fr in ["quiero un café", "el cielo está nublado", "necesito pizza", "mañana será otro día"]:
        s = _consola_falsa(f, fr)
        if s.prompts or s.ran or "comando CMD" in s.out or "enseñas" in s.out:
            mal.append(fr)
    chk(f"charla: responde sin pedir 'el comando CMD' ({mal})", not mal)
    s = _consola_falsa(f, "quiero un café")
    chk(f"charla sin pistas: 'No estoy seguro' + salida util ({s.out.strip()[:70]!r})", "No estoy seguro" in s.out and ("qué puedes hacer" in s.out.lower() or "ayuda" in s.out.lower()))
    s = _consola_falsa(f, "tengo un archivo")
    chk(f"charla con candidatos cercanos: ofrece 1 a 3 sugerencias ({s.out.strip()[:100]!r})",
        re.search(r"(Querías decir|Quizá): ", s.out) and 1 <= s.out.count(" / ") + 1 <= 3 and not s.ran and not s.prompts)
    mal = []
    for fr in ["imprime el informe", "quiero reservar un vuelo", "necesito traducir esto", "cuéntame un chiste"]:
        s = _consola_falsa(f, fr, resp=[""])
        if not (len(s.prompts) == 1 and "¿Me enseñas el comando?" in s.prompts[0] and "Enter para saltar" in s.prompts[0] and f"«{fr}»" in s.prompts[0]):
            mal.append((fr, s.prompts))
    chk(f"orden que no sabe: pide confirmacion 'No sé hacer «X». ¿Me enseñas el comando? (Enter para saltar)' ({mal})", not mal)
    s = _consola_falsa(f, "imprime el informe", resp=["sí", ""])
    chk(f"'sí' en el aviso de enseñanza NO se ejecuta como comando ({s.ran})", not s.ran and len(s.prompts) == 2)
    s = _consola_falsa(f, "imprime el informe", resp=["no"])
    chk("'no' en el aviso de enseñanza salta sin ejecutar", not s.ran and len(s.prompts) == 1)
    s = _consola_falsa(f, "imprime el informe", resp=["echo hola"])
    chk(f"enseñar un comando real si funciona (ejecuta y aprende) ({s.ran})", s.ran == ["echo hola"] and _tarea_de(f, "echo hola") is not None)
    for fr in ["cuál es la capital de Francia", "qué película me recomiendas"]:
        s = _consola_falsa(f, fr)
        chk(f"pregunta sin respuesta {fr!r}: no pide enseñar comando", not s.prompts and not s.ran and "comando CMD" not in s.out)
    mal = []
    for fr in ["asdf", "...", "qwerty", "???", "kjhgf"]:
        s = _consola_falsa(f, fr)
        if "No entendí" not in s.out or s.prompts or s.ran:
            mal.append(fr)
    chk(f"frases vacias de sentido -> 'No entendí' ({mal})", not mal)

    # ---- 7. memoria de dialogo corto y referencias
    m = nuevo("conv15.json")
    s = _consola_falsa(m, "otra vez")
    chk("'otra vez' sin nada previo: avisa y no ejecuta", not s.ran and not s.prompts and s.out.strip())
    _consola_falsa(m, "abre el bloc de notas")
    s = _consola_falsa(m, "otra vez")
    chk(f"'otra vez' repite la ultima accion ({s.ran})", s.ran == ["start notepad"])
    s = _consola_falsa(m, "de nuevo")
    chk("'de nuevo' tambien", s.ran == ["start notepad"])
    s = _consola_falsa(m, "y ahora la calculadora")
    chk(f"'y ahora la calculadora' hereda el verbo ({s.ran})", s.ran == ["start calc"])
    _consola_falsa(m, "cierra chrome")
    s = _consola_falsa(m, "y ahora spotify", resp=["s"])
    chk(f"'y ahora spotify' tras 'cierra chrome' hereda CERRAR, con confirmacion ({s.ran}, {len(s.prompts)} pregunta)",
        s.ran == ["taskkill /im spotify.exe"] and len(s.prompts) == 1)
    s = _consola_falsa(m, "y ahora la carpeta Música")
    chk("'y ahora la carpeta Música' tras cerrar: no ejecuta sin confirmar", not s.ran or s.prompts)
    _consola_falsa(m, "abre el bloc de notas")
    s = _consola_falsa(m, "y ahora abre la calculadora")
    chk("'y ahora abre la calculadora' (con verbo propio) = orden normal", s.ran == ["start calc"])
    m2 = nuevo("conv16.json")
    _consola_falsa(m2, "pon algo de musica por favor")
    s = _consola_falsa(m2, "la otra", resp=["n"])
    chk(f"'la otra' ofrece el siguiente candidato de la ultima decision (o dice que no hay) ({s.out.strip()[:60]!r} {s.prompts})",
        not s.ran and (s.prompts or "otra opción" in s.out))
    m3 = nuevo("conv17.json")
    s = _consola_falsa(m3, "tengo un archivo")
    s = _consola_falsa(m3, "la primera", resp=["s"])
    chk(f"'la primera' elige la primera sugerencia del fallback, con confirmacion ({s.ran}, {s.prompts})", s.ran == ["start explorer"] and len(s.prompts) == 1)
    m4 = nuevo("conv18.json")
    _consola_falsa(m4, "abre el bloc de notas")
    s1 = _consola_falsa(m4, "!porque")
    s2 = _consola_falsa(m4, "¿por qué?")
    chk("'¿por qué?' equivale a !porque", s1.out and s1.out == s2.out and "start notepad" in s2.out)
    _consola_falsa(m4, "holaaa")
    sp = _consola_falsa(m4, "!porque")
    chk(f"!porque tras una charla muestra la intencion y el patron ({sp.out.strip()[:80]!r})", "saludo" in sp.out and "patrón" in sp.out and "hola" in sp.out)
    sp2 = _consola_falsa(m4, "por qué")
    chk("'por qué' tras charla = lo mismo", "saludo" in sp2.out)

    # ---- 8. seguridad: nada peligroso sin confirmar; sí/dale sueltos no ejecutan
    d = nuevo("conv19.json")
    ruta = os.path.join(TMP, "borrame.txt")
    open(ruta, "w").write("x")
    d.aprender("borra mi archivo de prueba", f'del "{ruta}"')
    log = []
    s = _consola_falsa(d, "borra mi archivo de prueba", log=log)
    log.clear()
    s = _consola_falsa(d, "otra vez", resp=["n"], log=log)
    chk(f"'otra vez' tras un comando peligroso pregunta y con 'n' no ejecuta ({s.ran}, {s.prompts})", not s.ran and len(s.prompts) == 1 and "⚠" in s.prompts[0])
    log.clear()
    s = _consola_falsa(d, "otra vez", resp=[], log=log)
    chk("'otra vez' peligroso sin respuesta (EOF) no ejecuta", not s.ran)
    log.clear()
    s = _consola_falsa(d, "de nuevo", resp=["s"], log=log)
    orden = [x[0] for x in log]
    chk(f"con 's' si ejecuta, pero SOLO despues de preguntar ({orden})", s.ran and orden and orden[0] == "input" and orden.index("exec") > orden.index("input"))
    mal = []
    for fr in ["dale", "sí", "si", "ok", "okey", "claro", "vale", "listo", "adelante", "hazlo", "confirmo", "procede"]:
        s = _consola_falsa(d, fr)
        if s.ran or s.prompts:
            mal.append((fr, s.ran, s.prompts))
    chk(f"'sí'/'dale'/'ok' sueltos tras una accion peligrosa: no ejecutan ni preguntan ({mal})", not mal)
    e = nuevo("conv20.json")
    mal = []
    for fr in ["dale", "sí", "no", "ok", "nada", "claro"]:
        s = _consola_falsa(e, fr)
        if s.ran or s.prompts:
            mal.append((fr, s.ran, s.prompts))
    chk(f"sin pregunta pendiente 'sí/dale/no' no ejecutan nada ({mal})", not mal)
    e2 = nuevo("conv21.json")
    s = _consola_falsa(e2, "tengo un archivo")
    s = _consola_falsa(e2, "dale")
    chk(f"con VARIAS sugerencias pendientes 'dale' no elige por su cuenta: pregunta cual y no ejecuta ({s.ran}, {s.out.strip()[:50]!r})",
        not s.ran and not s.prompts and "¿Cuál" in s.out)
    s = _consola_falsa(e2, "mi disco esta lleno")
    s = _consola_falsa(e2, "dale")
    chk(f"con UNA sugerencia pendiente 'dale' la acepta; si es solo una pista de herramienta no la ejecuta ({s.ran}, {s.out.strip()[:60]!r})",
        not s.ran and "Dilo así" in s.out)
    mal = []
    for fr in ["otra vez", "de nuevo", "la otra", "y ahora el bloc de notas", "la segunda", "repite"]:
        s = _consola_falsa(nuevo("conv22.json"), fr)
        if s.ran:
            mal.append((fr, s.ran))
    chk(f"seguimientos sin historial no ejecutan nada ({mal})", not mal)

    # ---- 9. NO-ROBO: las frases de los bloques existentes no cambian por la capa K
    k_ = nuevo("conv23.json")
    vistas = sorted({f for f in frases_previas if isinstance(f, str) and f.strip()})
    robadas = [f for f in vistas if set(k_.conv.detecta(f) or []) - {"fechahora"}]          # fechahora: K lo detecta pero cede a @hora/@fecha (se comprueba abajo)
    cedidas = [f for f in vistas if k_.conv.atender(f, k_.decidir(f)) is not None]
    chk(f"NO-ROBO: {len(vistas)} frases de los bloques anteriores (principal, holdout, herramientas, personal, conocimiento, documentos): K no detecta ninguna ({robadas[:5]}); atender() cede en todas ({cedidas[:5]})", not robadas and not cedidas)
    muestra = vistas[:400]
    antes = [(x.accion, x.cmd, round(x.conf, 6)) for x in (k_.decidir(f) for f in muestra)]
    for f in muestra:
        k_.conv.atender(f, k_.decidir(f))
    despues = [(x.accion, x.cmd, round(x.conf, 6)) for x in (k_.decidir(f) for f in muestra)]
    chk(f"NO-ROBO: decidir() da lo mismo antes y despues de pasar por K ({len(muestra)} frases)", antes == despues)
    # latencia de la capa K (atender sobre frases de todo tipo)
    lat = []
    for _ in range(3):
        for f in vistas[:300] + [x for _it, vs in CONV_INTENCIONES for x in vs]:
            dd = k_.decidir(f)
            t = perf_counter()
            k_.conv.atender(f, dd)
            lat.append((perf_counter() - t) * 1000)
    return res, {"lat": lat, "n_frases": len(vistas)}


def evaluar(eng, qs):
    res = []
    for cat, f, esp in qs:
        if isinstance(esp, list):
            got = eng.plan(f)
            ok = got == esp
            res.append((cat, f, ok, False, None, 0.0, "plan" if got else "ensenar", got or []))
            continue
        acc, cmd, conf = eng.decidir(f)
        if esp is None:
            ok = acc == "ensenar"
            fp = acc == "ejecutar"
        elif esp == "AMBIGUA":
            ok = acc != "ejecutar"
            fp = acc == "ejecutar"
        else:
            ok = acc != "ensenar" and cmd == esp
            fp = acc == "ejecutar" and cmd != esp
        res.append((cat, f, ok, fp, cmd, conf, acc, esp))
    return res


def latencias(eng, qs, vueltas=3):
    frio, caliente = [], []
    for v in range(vueltas):
        for cat, f, esp in qs:
            t = perf_counter()
            if isinstance(esp, list):
                eng.plan(f)
            else:
                eng.decidir(f)
            ms = (perf_counter() - t) * 1000
            (frio if v == 0 else caliente).append(ms)
    return frio, caliente


def p95(x):
    x = sorted(x)
    return x[min(len(x) - 1, int(0.95 * len(x)))]


def kb(p):
    return os.path.getsize(p) / 1024 if os.path.exists(p) else 0


def main():
    # ---- grabadora de frases (para el barrido NO-ROBO del bloque CONVERSACION): todo lo que ven decidir() y personal.procesar()
    from mbot_answer_flash.personal import Personal as _P
    frases_vistas = []
    _dec0, _proc0 = v2.Asistente.decidir, _P.procesar
    def _dec(self, texto):
        frases_vistas.append(texto)
        return _dec0(self, texto)
    def _proc(self, frase):
        frases_vistas.append(frase)
        return _proc0(self, frase)
    v2.Asistente.decidir, _P.procesar = _dec, _proc
    # ---- descubrimiento real (E) + cache determinista para el resto
    real_p = os.path.join(TMP, "real.json")
    t = perf_counter(); real = v2.descubrir(real_p); dt = perf_counter() - t
    det = dict(real); det["apps"] = APPS_SINTETICAS + [a for a in real["apps"]]
    det_p = os.path.join(TMP, "det.json")
    v2.guardar_json(det_p, det)

    tracemalloc.start()
    e1 = E1(os.path.join(TMP, "m1.json"))
    m1 = tracemalloc.get_traced_memory()[0] / 1024
    tracemalloc.reset_peak()
    base = tracemalloc.get_traced_memory()[0]
    e2 = E2(os.path.join(TMP, "m2.json"), det_p)
    m2 = (tracemalloc.get_traced_memory()[0] - base) / 1024
    tracemalloc.stop()

    r1 = evaluar(e1, [x for x in Q if x[0] in V1_CATS])
    r2 = evaluar(e2, Q)
    cats = ["base", "base_ext", "typos", "red", "params", "induccion", "multi", "negativas", "ambiguas"]
    print(f"\n{'categoria':<11}{'n':>3} | {'v1 top1':>8}{'v1 FP':>6} | {'v2 top1':>8}{'v2 FP':>6}")
    tot = {"v1": [0, 0, 0], "v2": [0, 0, 0]}
    for c in cats:
        a = [x for x in r1 if x[0] == c]; b = [x for x in r2 if x[0] == c]
        n = len(b)
        s1 = f"{sum(x[2] for x in a)}/{len(a)}" if a else "n/a"
        f1 = str(sum(x[3] for x in a)) if a else "n/a"
        print(f"{c:<11}{n:>3} | {s1:>8}{f1:>6} | {sum(x[2] for x in b):>5}/{n:<2}{sum(x[3] for x in b):>6}")
        for k, rr in (("v1", a), ("v2", b)):
            tot[k][0] += sum(x[2] for x in rr); tot[k][1] += len(rr); tot[k][2] += sum(x[3] for x in rr)
    # comparable: solo categorias de v1
    c1 = [x for x in r2 if x[0] in V1_CATS]
    print(f"\nComparables (base+typos+red+negativas+ambiguas, {len(c1)} frases): v1 {tot['v1'][0]}/{tot['v1'][1]} ok, "
          f"FP {tot['v1'][2]} | v2 {sum(x[2] for x in c1)}/{len(c1)} ok, FP {sum(x[3] for x in c1)}")
    print(f"Total v2: {tot['v2'][0]}/{tot['v2'][1]} ok, falsos positivos {tot['v2'][2]} "
          f"({100*tot['v2'][2]/tot['v2'][1]:.1f}%); total frases con ayuda (E) aparte: {len(AYUDA)}")
    d1 = {(x[0], x[1]): x for x in r1}
    reg = [x for x in c1 if (x[0], x[1]) in d1 and d1[(x[0], x[1])][2] and not x[2]]
    print("Regresiones v2 vs v1:", [x[1] for x in reg] or "ninguna")
    fp2 = [x for x in r2 if x[3]]
    print("Falsos positivos v2:", [(x[1], x[4]) for x in fp2] or "ninguno")
    # soft: negativas que preguntan
    soft = [x[1] for x in r2 if x[0] == "negativas" and x[6] == "preguntar"]
    soft1 = [x[1] for x in r1 if x[0] == "negativas" and x[6] == "preguntar"]
    print(f"Negativas que al menos preguntan (ruido): v1 {len(soft1)}/{sum(1 for x in Q if x[0]=='negativas')}"
          f" v2 {len(soft)}")
    if VERBOSE:
        for x in r2:
            if not x[2]:
                print("  FALLO v2:", x[0], repr(x[1]), "->", x[6], x[4], f"{x[5]:.2f}", "esperado", x[7])
        for x in r1:
            if not x[2]:
                print("  FALLO v1:", x[0], repr(x[1]), "->", x[6], x[4], f"{x[5]:.2f}")
    # directa (red)
    rd2 = [x for x in r2 if x[0] == "red"]
    print(f"Red de conceptos: top1 {sum(x[2] for x in rd2)}/{len(rd2)}, ejecucion directa correcta "
          f"{sum(1 for x in rd2 if x[2] and x[6]=='ejecutar')}/{len(rd2)}  (v1: "
          f"{sum(1 for x in r1 if x[0]=='red' and x[2] and x[6]=='ejecutar')} directas)")

    # ---- desarrollo + semantica + peligrosos
    rh = evaluar(e2, [("desarrollo", f, e) for f, e in DESARROLLO])
    ph = [x for x in rh if x[7] is not None]; nh = [x for x in rh if x[7] is None]
    print(f"\nDESARROLLO (antes holdout, {len(rh)} frases): ok {sum(x[2] for x in rh)}/{len(rh)} (positivas {sum(x[2] for x in ph)}/{len(ph)}, "
          f"negativas {sum(x[2] for x in nh)}/{len(nh)}), FP {sum(x[3] for x in rh)}")
    for x in rh:
        if VERBOSE and not x[2]:
            print("   dev FALLO:", repr(x[1]), "->", x[6], x[4], f"{x[5]:.2f}", "esperado", x[7])
    es = E2(os.path.join(TMP, "ms.json"), det_p, ens=[("quiero dibujar un gato", "start mspaint")])
    rs = evaluar(es, [("sem", f, e) for f, e in SEM])
    rs = [x if x[2] and (x[5] >= 0.6 or "{" in str(x[4])) else (x[0], x[1], False) + x[3:] for x in rs]   # exige confianza >= 0.6
    print(f"SEMANTICA memoria nueva ({len(rs)}): ok {sum(x[2] for x in rs)}/{len(rs)}, FP {sum(x[3] for x in rs)}")
    for x in rs:
        if VERBOSE or not x[2]:
            print("   sem", "OK " if x[2] else "FALLO", repr(x[1]), "->", x[6], x[4], f"{x[5]:.2f}")
    PEL = v2.PELIGROSO
    viol = [(x[1], x[4]) for x in r2 + rh + rs if x[4] and PEL.search(str(x[4])) and x[6] == "ejecutar"]
    print("Peligrosos con accion 'ejecutar' sin confirmar:", viol or "ninguno")
    # barrido: cada frase de cada tarea peligrosa (huecos rellenados) y sus variantes nunca deben salir como 'ejecutar'
    barrido = []
    for t in es.a.tareas + e2.a.tareas:
        if PEL.search(t["cmd"]):
            for fr in t["frases"] + ["por favor " + t["frases"][0], t["frases"][0] + " ahora"]:
                fr = fr.replace("{ruta}", "C:/temp/x.txt").replace("{app}", "chrome").replace("{carpeta}", "Descargas")
                for eng in (es, e2):
                    d = eng.a.decidir(fr)
                    if d.cmd and PEL.search(d.cmd) and d.accion == "ejecutar":
                        barrido.append((fr, d.cmd))
    print("Barrido de frases de tareas peligrosas ->", barrido or "ninguna sale como 'ejecutar'")
    # barrido shutdown: ninguna frase SIN verbo de apagar/reiniciar propone `shutdown` (ni siquiera como candidato)
    sd = [(fr, c["cmd"]) for fr in SIN_VERBO_APAGAR + [f for _c, f, _e in Q if isinstance(_e, (str, type(None)))] + [f for f, _ in DESARROLLO]
          for eng in (es, e2) for c in eng.a.decidir(fr).cands if "shutdown" in c["cmd"]
          and not any(k in ("APAGAR", "REINICIAR") and not w.endswith(("ado", "ada", "ido", "ida")) for w, k in eng.a.analizar(fr).marco.via)]
    print("Barrido shutdown (frases sin verbo de apagar/reiniciar, bancos Q+DESARROLLO+extra) ->", sd or "ningun candidato shutdown")

    # ---- similitud distribucional (segundo orden): palabras que nunca aparecen juntas
    ed = v2.Asistente(os.path.join(TMP, "md.json"), det_p, auto_descubrir=False)
    for f, c in [("retocar una foto", "start mspaint"), ("editar una foto", "start mspaint"), ("editar un texto", "start notepad"),
                 ("dibujar un paisaje", "start mspaint"), ("pincelar un paisaje", "start mspaint")]:
        ed.aprender(f, c)
    s_r = dict(ed.red.simil("retoc", top=8)); s_e = dict(ed.red.simil("edit", top=8))
    inf = ed._inferir(v2.marco_de("pincelar", {}))
    dd = ed.decidir("quiero retocar algo")
    print(f"Distribucional: simil(retoc,edit)={s_r.get('edit', 0):.2f} simil(edit,retoc)={s_e.get('retoc', 0):.2f} (nunca juntas); "
          f"'pincelar' inferido como clase {inf[0] if inf else None} (cos {inf[1] if inf else 0:.2f} con '{inf[3] if inf else ''}'); "
          f"'quiero retocar algo' -> {dd.accion} {dd.cmd} {dd.conf:.2f}")

    # ---- induccion: una sola tarea generalizada
    plant = [t for t in e2.a.tareas if t["cmd"].startswith("dir /s")]
    print("Induccion:", "OK una plantilla " + plant[0]["cmd"] if len(plant) == 1 and "{carpeta}" in plant[0]["cmd"]
          else f"FALLO {[t['cmd'] for t in plant]}")

    # ---- refuerzo (G): 'no' penaliza y reaprende
    eg = v2.Asistente(os.path.join(TMP, "m6.json"), det_p, auto_descubrir=False)
    d0 = eg.decidir("abre el bloc de notas")
    eg.penalizar(d0)
    d1 = eg.decidir("abre el bloc de notas")
    eg.aprender("abre el bloc de notas", "start wordpad")
    d2 = eg.decidir("abre el bloc de notas")
    d3 = eg.decidir("abre la calculadora")
    print(f"Refuerzo: antes {d0.cmd} ({d0.conf:.2f}) -> tras 'no' {d1.accion} {d1.conf:.2f} -> tras corregir {d2.cmd} ({d2.accion}); "
          f"calculadora intacta: {d3.cmd == 'start calc'}  =>",
          "OK" if d0.cmd == "start notepad" and d1.accion != "ejecutar" and d2.cmd == "start wordpad" and d3.cmd == "start calc" else "FALLO")
    print("Explicacion (!porque) de 'quiero dibujar':")
    print(chr(10).join("   " + x for x in e2.a.explicar(e2.a.decidir("quiero dibujar")).encode("ascii", "replace").decode().splitlines()))
    # ---- ayuda (E) en memoria limpia
    ef = E2.__new__(E2); ef.a = v2.Asistente(os.path.join(TMP, "m3.json"), det_p, auto_descubrir=False, herramientas=False)   # capa E aislada: con herramientas 'mostrar la fecha' va a @fecha, mejor que `date`
    ok_a, no_dir, fails = 0, 0, []
    for f, st in AYUDA:
        d = ef.a.decidir(f)
        if d.cmd in st:
            ok_a += 1
        else:
            fails.append((f, d.cmd))
        if d.accion == "ejecutar" and d.ayuda:           # solo cuenta la capa E (help); una tarea semilla como cls si ejecuta
            no_dir += 1
    print(f"Ayuda de cmd (capa E): top1 {ok_a}/{len(AYUDA)}, ejecutarian directo {no_dir}"
          + (f", fallos {fails}" if fails else ""))
    # ---- descubrimiento real
    napps = len(real["apps"]); nlnk = sum(1 for a in real["apps"] if a[3] == "lnk")
    print(f"Descubrimiento real: {dt:.2f}s (meta <2s), {napps} apps ({nlnk} lnk, {napps-nlnk} App Paths), "
          f"{len(real['ayuda'])} comandos help, cache {kb(real_p):.1f} KB")
    ex = [a for a in real["apps"] if a[3] == "lnk" and re.fullmatch(r"[A-Za-z0-9 ]+", a[0]) and len(a[0]) >= 4][:6]
    er = v2.Asistente(os.path.join(TMP, "m4.json"), real_p, auto_descubrir=False)
    h = 0
    for a in ex:
        d = er.decidir("abre " + a[0])
        good = d.cmd == a[1]
        h += good
        print(f"   'abre {a[0]}' -> {d.accion} {d.conf:.2f} {'OK' if good else 'DISTINTO: ' + str(d.cmd)}")
    print(f"   apps reales resueltas: {h}/{len(ex)} (sin ejecutar)")
    t = perf_counter(); v2.Asistente(os.path.join(TMP, "m5.json"), real_p, auto_descubrir=False); arr = perf_counter() - t
    print(f"   arranque con cache: {arr*1000:.0f} ms")

    # ---- PERSONAL (memoria personal, recordatorios, preferencias)
    po, pn, intr, ns, lp, ld, pf = bloque_personal(det_p)
    print(f"\nPERSONAL ({pn} pasos): ok {po}/{pn}; intrusion en frases de otros bancos: {len(intr)}/{ns} {intr or ''}")
    for etq, txt in pf:
        print("   PERSONAL FALLO:", etq, repr(txt))
    print(f"   latencia personal.procesar (ms): media {statistics.mean(lp):.3f} p95 {p95(lp):.3f} max {max(lp):.3f}; "
          f"decidir() con preferencias activas: media {statistics.mean(ld):.2f} p95 {p95(ld):.2f} max {max(ld):.2f}")

    h2o, h2n, h2f = bloque_holdout2(det_p)
    print(f"PERSONAL_HOLDOUT2 ({h2n} comprobaciones): ok {h2o}/{h2n}")
    for e in h2f:
        print("   H2 FALLO:", e.encode("ascii", "replace").decode())

    # ---- BLOQUE 2: pedidos amables, HERRAMIENTAS y barrido de seguridad
    def _informe(nombre, res, extra=""):
        ok = sum(c for _e, c in res)
        print(f"{nombre} ({len(res)} comprobaciones): ok {ok}/{len(res)}{extra}")
        for e, c in res:
            if not c:
                print("   FALLO:", e.encode("ascii", "replace").decode())
        return ok, len(res)
    try:
        rp_ = bloque_pedidos(det_p)
    except Exception as e:
        rp_ = [(f"bloque_pedidos [{type(e).__name__}: {e}]", False)]
    pe_ok, pe_n = _informe("PEDIDOS (paso 0)", rp_)
    try:
        rh_, rs_, lh_ = bloque_herramientas(det_p)
    except Exception as e:
        rh_, rs_, lh_ = [(f"bloque_herramientas [{type(e).__name__}: {e}]", False)], [], [0.0]
    he_ok, he_n = _informe("HERRAMIENTAS", rh_, f"; decidir() sobre frases de herramientas: media {statistics.mean(lh_):.2f} p95 {p95(lh_):.2f} max {max(lh_):.2f} ms")
    se_ok, se_n = _informe("SEGURIDAD (calculadora maliciosa, rutas .., symlinks)", rs_)

    # ---- BLOQUE 3: correcciones (parte 0) y CONOCIMIENTO
    try:
        rc_ = bloque_correcciones(det_p)
    except Exception as e:
        rc_ = [(f"bloque_correcciones [{type(e).__name__}: {e}]", False)]
    co_ok, co_n = _informe("CORRECCIONES (bloque 3, parte 0)", rc_)
    try:
        rk_, ik_ = bloque_conocimiento(det_p)
    except Exception as e:
        import traceback; traceback.print_exc()
        rk_, ik_ = [(f"bloque_conocimiento [{type(e).__name__}: {e}]", False)], {"q_lat": [0.0], "idx_s": 0, "idx_n": 0, "idx_trozos": 0, "reidx_s": 0}
    kn_ok, kn_n = _informe("CONOCIMIENTO", rk_, f"; indexado de {ik_['idx_n']} archivos sinteticos ({ik_['idx_trozos']} trozos): {ik_['idx_s']:.2f} s, "
                           f"reindexar sin cambios {ik_['reidx_s']:.2f} s; consulta media {statistics.mean(ik_['q_lat']):.2f} p95 {p95(ik_['q_lat']):.2f} max {max(ik_['q_lat']):.2f} ms")

    # ---- BLOQUE 4: correcciones (parte 0) y DOCUMENTOS
    try:
        rc4_ = bloque_correcciones4(det_p)
    except Exception as e:
        import traceback; traceback.print_exc()
        rc4_ = [(f"bloque_correcciones4 [{type(e).__name__}: {e}]", False)]
    c4_ok, c4_n = _informe("CORRECCIONES (bloque 4, parte 0)", rc4_)
    try:
        rd_, id_ = bloque_documentos(det_p)
    except Exception as e:
        import traceback; traceback.print_exc()
        rd_, id_ = [(f"bloque_documentos [{type(e).__name__}: {e}]", False)], {"docx_kb": 0, "docx_palabras": 0, "docx_s": 0.0, "resumen_s": 0.0, "docx_sec": 0}
    do_ok, do_n = _informe("DOCUMENTOS", rd_, f"; DOCX sintetico de {id_['docx_kb']} KB ({id_['docx_palabras']} palabras, {id_['docx_sec']} secciones): lectura {id_['docx_s'] * 1000:.0f} ms, resumen {id_['resumen_s'] * 1000:.0f} ms")

    # ---- BLOQUE 5: CONVERSACION (capa K)
    snapshot = list(frases_vistas)
    v2.Asistente.decidir, _P.procesar = _dec0, _proc0
    try:
        rv_, iv_ = bloque_conversacion(det_p, snapshot)
    except Exception as e:
        import traceback; traceback.print_exc()
        rv_, iv_ = [(f"bloque_conversacion [{type(e).__name__}: {e}]", False)], {"lat": [0.0], "n_frases": 0}
    cv_ok, cv_n = _informe("CONVERSACION (bloque 5, capa K)", rv_, f"; K.atender(): media {statistics.mean(iv_['lat']):.3f} p95 {p95(iv_['lat']):.3f} max {max(iv_['lat']):.3f} ms ({iv_['n_frases']} frases del barrido NO-ROBO)")
    pet_ok, pet_n = _informe("PETICIONES (consola)", bloque_peticiones(det_p))
    er_ok, er_n = _informe("ELECCION DE RESPUESTA (consola)", bloque_eleccion_respuesta(det_p))
    bloque_aprendizaje(det_p)

    # ---- latencia / memoria
    f1, c1_ = latencias(e1, [x for x in Q if x[0] in V1_CATS])
    f2, c2_ = latencias(e2, Q)
    fr = f1 + c1_; f2a = f2 + c2_
    print(f"\nLatencia por consulta (ms)      media   p95   max")
    print(f"  v1 (todas las pasadas)        {statistics.mean(fr):6.2f} {p95(fr):6.2f} {max(fr):6.2f}")
    print(f"  v2 primera pasada (cache fria){statistics.mean(f2):6.2f} {p95(f2):6.2f} {max(f2):6.2f}")
    print(f"  v2 pasadas calientes          {statistics.mean(c2_):6.2f} {p95(c2_):6.2f} {max(c2_):6.2f}")
    print(f"Memoria (archivo): v1 {kb(os.path.join(TMP,'m1.json')):.1f} KB | v2 {kb(os.path.join(TMP,'m2.json')):.1f} KB"
          f" (+ cache descubrimiento {kb(det_p):.1f} KB) | RAM python v1 {m1:.0f} KB, v2 {m2:.0f} KB")
    print(f"Red de conceptos v2: {len(e2.a.red.ww)} aristas palabra-palabra, {len(e2.a.red.wc)} palabra-comando")
    print(f"(archivos temporales en {TMP})")

    # ---- RESUMEN (misma tabla para comparar fusion max vs rrf: python bench.py --fusion=rrf)
    filas = [("principal (88 frases)", tot["v2"][0], tot["v2"][1], f"FP {tot['v2'][2]}"),
             ("desarrollo (antes holdout)", sum(x[2] for x in rh), len(rh), f"FP {sum(x[3] for x in rh)}"),
             ("semantica", sum(x[2] for x in rs), len(rs), f"FP {sum(x[3] for x in rs)}"),
             ("ayuda cmd (E)", ok_a, len(AYUDA), ""),
             ("PERSONAL", po, pn, f"intrusion {len(intr)}/{ns}"), ("PERSONAL_HOLDOUT2", h2o, h2n, ""), ("PEDIDOS", pe_ok, pe_n, ""),
             ("HERRAMIENTAS", he_ok, he_n, ""), ("SEGURIDAD", se_ok, se_n, ""),
             ("CORRECCIONES (parte 0)", co_ok, co_n, ""), ("CONOCIMIENTO", kn_ok, kn_n, ""),
             ("CORRECCIONES4 (parte 0)", c4_ok, c4_n, ""), ("DOCUMENTOS", do_ok, do_n, ""),
             ("CONVERSACION (K)", cv_ok, cv_n, f"K.atender p95 {p95(iv_['lat']):.2f} ms"),
             ("PETICIONES (consola)", pet_ok, pet_n, ""),
             ("ELECCION DE RESPUESTA", er_ok, er_n, "")]
    print(f"\nRESUMEN (fusion = {FUSION})")
    print(f"  {'bloque':<26}{'ok':>9}  nota")
    for nom, o, n, nota in filas:
        print(f"  {nom:<26}{f'{o}/{n}':>9}  {nota}")
    print(f"  {'TOTAL':<26}{f'{sum(f[1] for f in filas)}/{sum(f[2] for f in filas)}':>9}")
    print(f"  latencia decidir() p95: principal {p95(c2_):.2f} ms, herramientas {p95(lh_):.2f} ms, con preferencias {p95(ld):.2f} ms (limite 3 ms)")


if __name__ == "__main__":
    if "--piloto" in sys.argv or "--aprendizaje" in sys.argv:
        det_p = os.path.join(TMP, "piloto_desc.json")
        v2.guardar_json(det_p, {"apps": APPS_SINTETICAS, "ayuda": []})
        if "--aprendizaje" in sys.argv:
            bloque_aprendizaje(det_p)
        else:
            from evaluar_piloto import ejecutar_banco
            ejecutar_banco(lambda nombre: _nuevo(det_p, nombre), _consola_falsa, lambda: AHORA0,
                           sin_eleccion="--sin-eleccion" in sys.argv, fusion=FUSION)
    else:
        main()
