"""Capa K (conversacion): charla basica util, SIN LLM. Se consulta DESPUES de decidir() y ANTES de pedir que le ensenen un comando.

Flujo (ver consola.procesar_linea): interpretar_peticion -> personal.procesar -> decidir() -> atender() -> fallback.
  - atender(): intenciones conversacionales (saludo, despedida, gracias, como estas, quien eres, que puedes hacer, si/no sueltos, elogio,
    queja, risa, disculpa, "no se que hacer", fecha/hora) y seguimientos ("otra vez", "y ahora X", "la otra", "la segunda", "por que").
    Solo responde si la frase ENTERA es conversacion (patrones anclados + muletillas): nunca roba frases con otro contenido.
    Las intenciones se saltan si decidir() ya eligio ejecutar/confirmar/rechazar (lo aprendido o las herramientas ganan siempre);
    fecha/hora jamas se responden aqui: la herramienta @hora/@fecha manda (un typo se reescribe a la frase canonica y vuelve a decidir()).
  - fallback(): reemplaza el "escribe el comando CMD" de todas las frases. Orden (verbo de accion o "quiero/necesito + infinitivo") que no
    se supo resolver -> "No se hacer «X». ¿Me enseñas el comando? (Enter para saltar)"; pregunta -> sin pedir comando (+ @buscar);
    charla -> "No estoy seguro. ¿Querías decir: A / B?" con 1 a 3 sugerencias de baja confianza; sin sentido ("asdf", "...") -> "No entendí".

Normalizacion y typos: texto.sin_tildes, repeticiones de letras colapsadas ("holaaa", "graciass"), abreviaturas ("k tal"), y correccion difusa
(texto.cercano) de palabras sueltas contra el vocabulario de los patrones. Los patrones se escriben en español normal y se compilan colapsados.

Memoria de dialogo: ultimas 5 interacciones en RAM (`mem`). "otra vez/de nuevo" repite la ultima orden (con confirmacion si era delicada);
"y ahora X" hereda el verbo de la ultima orden y la pasa otra vez por decidir() (cerrar/borrar/mover... piden confirmacion antes);
"eso no / la otra / la segunda" eligen la siguiente alternativa de la ultima decision (o de las sugerencias del fallback) y SIEMPRE confirman;
"¿por qué?" = !porque. Todo lo que se re-ejecuta vuelve a pasar por el flujo completo (validacion, peligro, confirmaciones).

Refuerzo G: "no sirves"/"te equivocaste" justo despues de una accion = "eso no era" (corregir). "gracias" justo despues de una accion exitosa suma
SUAVE (+0.25, una sola vez por accion) a esa tarea; un insulto no penaliza. Un turno de charla en medio rompe el "justo antes".

Limitaciones: "primer saludo del dia" vive en RAM (por sesion); no hay desambiguacion por contexto largo (solo 5 turnos).
"""
import random
import re
from collections import deque
from enum import Enum

from .config import es_peligroso
from .herramientas import REGISTRO
from .lexico import ACCIONES, clases_de
from .personal import _desde_iso, es_pedido
from .razonamiento import Decision
from .refuerzo import decaer
from .texto import MARK, STOP, cercano, sin_tildes, tokens

MEM_TURNOS = 5
REFUERZO_SUAVE = 0.25
CONF_ALT = 0.2                       # confianza minima de una alternativa tras una decision ("la otra")
CONF_SUG = 0.2                       # confianza minima de una sugerencia del fallback (siempre < UMBRAL_PREGUNTAR)
DELICADAS = {"BORRAR", "APAGAR", "REINICIAR", "CERRAR", "MOVER", "LIMPIAR"}   # clases de verbo que piden confirmacion si se heredan/repiten

_COMO_ABRIR = re.compile(
    r"^(?:(?:dime|explicame|me puedes decir)\s+)?como\s+(?:(?:puedo|se puede|hago para)\s+)?"
    r"(?:abrir|abro|se abre|iniciar|inicio)\s+(?:(?:la|el|un|una)\s+)?(?P<objeto>.+)$"
)
_APPS_INICIO = {
    "calculadora": "Calculadora",
    "bloc de notas": "Bloc de notas",
    "notepad": "Bloc de notas",
    "explorador": "Explorador de archivos",
    "explorador de archivos": "Explorador de archivos",
    "paint": "Paint",
}
_ORDEN_NEGADA = re.compile(
    r"^(?:(?:oye|por favor|porfa),?\s+)?no\s+(?:quiero\s+que\s+)?(?:me\s+)?(?:(?:lo|la|los|las)\s+)?"
    r"(?:abras?|cierres?|ejecutes?|inicies?|lances?|borres?|elimines?|apagues?|reinicies?|guardes?|"
    r"crees?|muevas?|copies?|anotes?|hagas?|prendas?|enciendas?)\b"
)
_CALCULO_TRAS_NEGACION = re.compile(
    r'(?:[;,.]\s*|\s+(?:pero|solo|y)\s+)(?:pero\s+)?(?:solo\s+)?[¿¡]?'
    r'(?:dime\s+)?[¿¡]?(?:cuanto\s+(?:es|da|son)|cual\s+es\s+el\s+resultado\s+de)\s+(?P<expresion>.+)$'
)
_VERBO_PETICION = r"(?:(?:quiero|quisiera|necesito|puedes|podrias|me gustaria)\s+)?"
_VERBO_NOTA = re.compile(
    r"^" + _VERBO_PETICION +
    r"(?:anota|anotar|anotame|apunta|apuntar|apuntame|dejar anotad[oa]|tomar nota de)\s+"
)
_NOTA_SIN_TEXTO = re.compile(
    r"(?:(?:una|mi)\s+idea|mis\s+ideas|algo|esto)(?:\s+(?:rapid[oa]|breve|cortit[oa]))?"
)
_VERBO_PINTAR = re.compile(r"^" + _VERBO_PETICION + r"(?:pinta|pintame|pintar)\s+")
_SUPERFICIE_FISICA = re.compile(
    r"(?:la|el|una|un|mi)\s+(?:muro|pared|muralla|puerta|techo|reja)\b"
)
_VERBO_ENERGIA = re.compile(
    r"^" + _VERBO_PETICION + r"(?:apaga|apagar|prende|prender|enciende|encender)\s+"
)
_APARATO_FISICO = re.compile(
    r"(?:la|el|una|un|mi)\s+(?:tele|televisor|television|estufa|ventilador|luz|lampara|horno)\b"
)
_MENCION_PAINT = re.compile(r"\b(?:en|usando|con)\s+(?:ms)?paint\b")


class Peticion(Enum):
    INSTRUCCIONES = "pedir instrucciones"
    NEGACION = "negar una acción"
    NOTA = "tomar una nota sin indicar el texto"
    FISICA = "pedir una acción física"
    CONTINUAR = "seguir el flujo habitual"


def elegir_peticion(plano):
    """Puntúa opciones cerradas con señales locales. Los puntajes no son probabilidades."""
    nota = _VERBO_NOTA.match(plano)
    pintar = _VERBO_PINTAR.match(plano)
    energia = _VERBO_ENERGIA.match(plano)
    accion_fisica = bool(pintar or energia)
    objeto_fisico = bool(
        (pintar and _SUPERFICIE_FISICA.match(plano, pintar.end()) and not _MENCION_PAINT.search(plano))
        or (energia and _APARATO_FISICO.match(plano, energia.end()))
    )
    puntajes = {
        Peticion.INSTRUCCIONES: 4 * bool(_COMO_ABRIR.fullmatch(plano)),
        Peticion.NEGACION: 4 * bool(_ORDEN_NEGADA.match(plano)),
        Peticion.NOTA: 2 * bool(nota) + 2 * bool(nota and _NOTA_SIN_TEXTO.fullmatch(plano, nota.end())),
        Peticion.FISICA: 2 * accion_fisica + 2 * objeto_fisico,
        Peticion.CONTINUAR: 2,
    }
    primera, segunda = sorted(puntajes, key=puntajes.get, reverse=True)[:2]
    eleccion = primera if puntajes[primera] - puntajes[segunda] >= 2 else Peticion.CONTINUAR
    return eleccion, puntajes

ABREV = {"k": "que", "q": "que", "ke": "que", "kien": "quien", "komo": "como", "kmo": "como", "cmo": "como", "pq": "por que",
         "xq": "por que", "porq": "por que", "xfa": "por favor", "grax": "gracias", "tks": "gracias", "tnks": "gracias",
         "thx": "gracias", "bn": "bien", "ola": "hola", "ora": "hora", "tas": "estas", "estai": "estas", "estay": "estas", "andai": "andas", "salu2": "saludos", "wn": "wena"}
RELLENO = set("""pues oye eh ah oh uf a todos todas amigo amiga asistente bot xchat crack jefe bro hermano hermana compa master maquina
mi por favor porfa entonces ahora y bueno""".split()) - {"bueno"}


def _col(s):
    return re.sub(r"([a-z])\1+", r"\1", s)


def normalizar(t):
    """Minusculas, sin tildes ni signos, letras repetidas colapsadas, abreviaturas expandidas."""
    t = sin_tildes(t.lower())
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = _col(t)
    return " ".join(" ".join(ABREV.get(w, w) for w in t.split()).split())


class Patron:
    __slots__ = ("grupo", "intent", "nombre", "src", "rx")

    def __init__(self, grupo, intent, nombre, src):
        self.grupo, self.intent, self.nombre, self.src = grupo, intent, nombre, _col(src)
        self.rx = re.compile(r"(?<![a-z0-9])(?:" + self.src + r")(?![a-z0-9])")


PATRONES = []


def _p(intent, nombre, src, grupo="int"):
    PATRONES.append(Patron(grupo, intent, nombre, src))


# ---- intenciones conversacionales (grupo "int")
_p("saludo", "buenos_dias", r"buen(?:os|as)?\s+(?:dias?|tardes?|noches?)")
_p("saludo", "hola", r"hola|ola|holi|holis|hello|hi|hey|ey|wena|wenas|weno|buenas|saludos|salu|aloha|que onda|que hubo|que pasa|"
                     r"que hay|quiubo|quihubo|que tal|como va|buen dia|que mas")
_p("despedida", "adios", r"chao|chau|ciao|adios|bye|byebye|bai|nos vemos|hasta (?:luego|pronto|manana|la proxima|mas tarde|otro dia|la vista)|"
                         r"me voy|me retiro|cuidate|nos hablamos|nos leemos|que descanses")
_p("agradecimiento", "gracias", r"(?:(?:muchas|mil|muchisimas)\s+)?gracias(?:\s+por\s+(?:todo|la ayuda|eso|tu ayuda|avisar|tu tiempo|ayudarme))?|"
                                r"thanks|thank you|agradecido|agradecida|te agradezco|muy amable|te pasaste|te pasas|me salvaste")
_p("estado", "como_estas", r"como (?:estas|andas|te va|te encuentras|te sientes|te fue|vas|has estado|amaneciste|va todo|esta todo|te ha ido|"
                           r"andamos|estamos|estan)|que tal (?:estas|andas|tu|va todo|todo|el dia|tu dia)|todo bien|todo en orden|y tu|y vos|"
                           r"que cuentas|que hay de nuevo")
_p("identidad", "quien_eres", r"quien eres(?: tu)?|quien sos|como te llamas|cual es tu nombre|tu nombre|como te dicen|que eres(?: tu)?|"
                              r"eres (?:un )?(?:robot|bot|humano|humana|persona|ia|real|maquina|programa)|con quien hablo|presentate|"
                              r"quien te (?:creo|hizo|programo)|como te llaman|dime tu nombre|que nombre tienes")
_p("capacidad", "que_puedes", r"que (?:puedes|sabes|podes|haces|puedo)(?: hacer(?: por mi)?| hacerme)?|que sabes hacer|que cosas (?:puedes|sabes) hacer|"
                              r"para que sirves|para que sirve|en que (?:me ayudas|puedes ayudarme|me puedes ayudar)|como (?:funcionas|te uso)|"
                              r"que (?:comandos|opciones|funciones) (?:hay|tienes)|que me ofreces|que ofreces|(?:(?:necesito|quiero|pido) )?ayuda(?:me)?|"
                              r"ayudita|help|comandos|opciones|menu|instrucciones|manual|me ayudas|me puedes ayudar|puedes ayudarme")
_p("afirmacion", "si", r"si|sip|sipi|claro|ok|okey|oki|dale|vale|listo|va|sale|aja|aha|afirmativo|por supuesto|obvio|exacto|de acuerdo|"
                       r"esta bien|ya|entendido|entiendo|comprendo|correcto|asi es|eso es|yes|yep|yeah|seguro|con gusto|adelante|hazlo|procede|"
                       r"continua|sigue|confirmo|confirmado")
_p("negacion", "no", r"no gracias|no por ahora|no quiero|no deseo|no hace falta|no es necesario|nada mas|nada gracias|nada|no|nop|nope|nel|nah|"
                     r"negativo|para nada|nunca|tampoco|ninguno|ninguna|olvidalo|olvida eso|dejalo(?: asi)?|da igual|cancela|cancelar|cancelado|"
                     r"mejor no|todavia no|aun no")
_p("elogio", "bien", r"muy bien|bien hecho|bien|buena|bueno|buen trabajo|buen bot|buen chico|buenisimo|excelente|genial|estupendo|fantastico|"
                     r"asombroso|increible|chevere|bacan|bacano|super|wow|bravo|felicidades|perfecto|que bien|que buena|que bueno|"
                     r"eres (?:muy |tan |un |una |el |la |lo )*(?:genial|bueno|buena|mejor|crack|inteligente|listo|lista|util|increible|maximo|"
                     r"grande|capo|maquina|excelente|fantastico|brillante)|te quiero|me gustas|mejor asistente|buen asistente|buena respuesta|"
                     r"asi me gusta|lo haces bien|de lujo")
_p("queja", "queja_error", r"no sirves(?: para nada)?|no sirve(?: para nada)?|no funciona|no funcionas|no entiendes(?: nada)?|no entendiste(?: nada)?|"
                           r"no me entiendes|no me entendiste|no sabes nada|no haces nada|te equivocaste|te equivocas|estas mal|estuvo mal|esta mal|"
                           r"eso estuvo mal|eso esta mal|salio mal|mal hecho|que mal|que malo|fallaste|fallas|me fallas|no es lo que pedi|no pedi eso|"
                           r"no hiciste lo que pedi|hiciste mal|muy mal|mal|incorrecto|error|equivocado")
_p("queja", "queja_insulto", r"tonto|tonta|bobo|boba|inutil|estupido|estupida|idiota|imbecil|burro|burra|torpe|malo|mala|pesimo|pesima|horrible|"
                             r"basura|asqueroso|lento|lenta|inservible|porqueria|desastre|mierda|cabeza hueca|que asco|que horror|que lento|"
                             r"eres (?:muy |tan |un |una |el |la )*(?:tonto|tonta|bobo|boba|inutil|estupido|estupida|idiota|imbecil|burro|burra|"
                             r"torpe|malo|mala|pesimo|pesima|horrible|basura|asco|lento|lenta|inservible|porqueria|desastre|mierda|lo peor|peor)|"
                             r"maldito bot|te odio|odio este bot|callate")
_p("risa", "jaja", r"a?(?:[jh][aeiosu]){2,}[jh]?|jsj\w*|lol|lmao|xd+|haha+|kk+|me rei|que risa")
_p("disculpa", "perdon", r"perdon|perdona|perdoname|perdonen|disculpa|disculpame|disculpas|disculpen|lo siento|sorry|mi culpa|me equivoque|"
                         r"lamento|excusame|mil disculpas|ups|oops")
_p("perdido", "no_se_que_hacer", r"no se que hacer(?: ahora)?|estoy aburrido|estoy aburrida|aburrido|aburrida|me aburro|me aburre|que hago(?: ahora)?|"
                                 r"que hacemos|que puedo hacer ahora|no tengo nada que hacer|nada que hacer|sin ideas|estoy sin ideas|"
                                 r"dame (?:una )?ideas?|dame algo que hacer|sugiere(?:me)? algo|dime algo|hazme compania|entretenme|"
                                 r"quiero entretenerme|aburrimiento|no tengo ideas|estoy perdido|estoy perdida|no se que quiero|no se que pedir")
_p("fechahora", "hora", r"que horas? (?:es|son|tienes|tiene)(?: ahora)?|tienes hora|sabes que hora es|me das la hora|dime la hora|la hora|hora|"
                        r"que hora|hora actual")
_p("fechahora", "fecha", r"que dia es(?: hoy)?|que fecha es(?: hoy)?|que fecha|a que fecha estamos|a cuantos estamos|en que dia estamos|que dia|"
                         r"fecha|la fecha|dime la fecha|fecha de hoy|dia de hoy|hoy que dia es|dime que dia es")
# ---- seguimientos (grupo "seg"): solo valen si son la frase entera
_p("repetir", "otra_vez", r"otra vez(?: por favor)?|de nuevo|una vez mas|dale otra vez|dale de nuevo|hazlo (?:otra vez|de nuevo)|haz lo mismo|"
                          r"lo mismo(?: otra vez| de nuevo)?|repite|repitelo|repite eso|repite lo|repetir|repitela|vuelve a hacerlo|nuevamente|"
                          r"igual que antes", "seg")
_p("porque", "por_que", r"por que|porque|por que lo hiciste|por que hiciste eso|por que eso|por que dices eso|por que me dijiste eso|y por que|"
                        r"como asi|como llegaste a eso|por que entendiste eso|explicame|explicate|explica eso|por que asi|y eso por que|por que razon",
   "seg")
_p("seleccion", "otra_opcion", r"eso no|no es eso|no era eso|esa no|no esa|la otra|el otro|otra opcion|otra|otro|la siguiente|el siguiente|siguiente|"
                               r"la primera|el primero|la segunda|el segundo|la tercera|el tercero|la cuarta|el cuarto|la ultima|opcion \d|"
                               r"la opcion \d|numero \d|la \d|el \d|la uno|la dos|la tres|la cuatro", "seg")

FUERTES = {"saludo", "despedida", "agradecimiento", "estado", "identidad", "capacidad", "queja", "disculpa", "perdido", "fechahora"}
DEBILES = {"afirmacion", "negacion", "elogio", "risa"}
SEGUIMIENTOS = {"repetir", "porque", "seleccion"}
ORDEN_PRIO = ["saludo", "despedida", "agradecimiento", "estado", "identidad", "capacidad", "queja", "disculpa", "perdido",
              "afirmacion", "negacion", "elogio", "risa"]
VOCAB = sorted({w for p in PATRONES for w in re.findall(r"[a-z]{4,}", p.src)} - {"para", "como", "todo", "mas", "una", "otra", "otro"})
_VOCAB_SET = set(VOCAB) | RELLENO | STOP

RE_Y = re.compile(r"^y\s+(?:ahora\s+|luego\s+|despues\s+|tambien\s+|entonces\s+)?(?P<resto>\S.*)$")
RE_INTERROG = re.compile(r"^(?:que|cual|cuales|como|donde|cuando|quien|quienes|cuanto|cuantos|cuantas|por que|para que|si|no)\b")
RE_QUIERO = re.compile(r"\b(?:quiero|necesito|quisiera|me gustaria|voy a|tengo que|hay que|debo|puedes|podrias|puedo|podria|me puedes|me podrias|"
                       r"vamos a|queria)\s+(?:[a-z]+\s+){0,2}?([a-z]+(?:ar|er|ir)(?:me|te|lo|la|le|se|nos)?)\b")
VERBOS_EXTRA = set("""imprime imprimir envia enviar manda mandar llama llamar descarga descargar instala instalar actualiza actualizar guarda guardar
sube subir baja bajar cambia cambiar compra comprar reserva reservar traduce traducir conecta conectar desconecta sincroniza comprime
descomprime renombra renombrar pega pegar agenda agendar programa programar cuenta cuentame cuentale lee leer recomienda recomiendame
pasa pasame lleva llevame ayudame hazme haz dame dime prepara preparame cocina contesta responde saca sacame toma tomame mandame
mandale enviame traeme busca buscame ponme muestrame hablame escribeme llamame recuerdame cantame""".split())
SUSTANTIVOS_ACCION = set("""calculadora calculator calc navegador browser internet buscador ip red redes wifi conexion conectividad dns router lan
network notas nota configuracion configuraciones ajustes opciones preferencias settings operacion operaciones porcentaje ilustracion
diseno dibujos dibujo garabato pintura paint mspaint latencia""".split())
PREVIOS_NOMBRE = {"la", "el", "los", "las", "un", "una", "mi", "tu", "su", "de", "del", "al"}
DOC_TOOLS = {"leer", "seccion", "preguntar_doc", "entidades", "tabla"}
BANG = [("!hoy", "tu resumen del día"), ("!yo", "lo que sé de ti"), ("!recordatorios", "tus recordatorios"),
        ("!herramientas", "las herramientas disponibles"), ("!lista", "lo que me enseñaste"), ("!buscar wifi", "buscar en tus notas"),
        ("!porque", "por qué entendí algo")]
FILAS_TECLADO = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
TRIOS_TECLADO = {f[i:i + 3] for f in FILAS_TECLADO + tuple(x[::-1] for x in FILAS_TECLADO) for i in range(len(f) - 2)} - \
    {"ert", "wer", "rty", "tyu", "yui", "uio", "iop", "opi", "ytr", "poi", "oiu", "iuy", "uyt", "ewq", "rew", "tre"}
CUATROS_TECLADO = {f[i:i + 4] for f in FILAS_TECLADO + tuple(x[::-1] for x in FILAS_TECLADO) for i in range(len(f) - 3)}
VOCALES = set("aeiou")


def _basura(w):
    """Palabra sin sentido: sin vocales, aporreo de teclado o casi sin vocales."""
    if len(w) < 2:
        return True
    if not (set(w) & VOCALES):
        return True
    if any(w[i:i + 4] in CUATROS_TECLADO for i in range(len(w) - 3)):
        return True
    if any(w[i:i + 3] in TRIOS_TECLADO for i in range(len(w) - 2)) and len(w) <= 8:
        return True
    return len(w) >= 5 and sum(c in VOCALES for c in w) / len(w) < 0.2


def sin_sentido(t):
    """True si la frase no tiene ninguna palabra reconocible (solo signos, letras sueltas o aporreo de teclado)."""
    p = re.sub(r"[^a-z0-9\s]", " ", sin_tildes(t.lower()))
    ws = [w for w in p.split() if not w.isdigit()]
    if not ws:
        return not any(c.isdigit() for c in p)
    return all(_basura(w) for w in ws)


def _verbos(ws):
    """Palabras de la frase que son verbos de accion del lexico (no sustantivos como 'calculadora', 'navegador', 'red')."""
    out = []
    for i, w in enumerate(ws):
        if w in SUSTANTIVOS_ACCION or (i and ws[i - 1] in PREVIOS_NOMBRE):
            continue
        cl = clases_de(w)
        if cl and any(k in ACCIONES for k in cl):
            out.append((w, [k for k in cl if k in ACCIONES]))
    return out


def _palabras(t):
    return re.sub(r"[^a-z0-9\s]", " ", sin_tildes(t.lower())).split()


def _quitar_muletillas(ws):
    while ws and ws[0] in {"oye", "por", "favor", "porfa", "a", "ver", "pues", "ya", "eh", "entonces"}:
        ws = ws[1:]
    return ws


def tiene_verbo_orden(frase):
    """True si la frase tiene verbo de accion (lexico, imperativo comun o 'quiero/necesito + infinitivo')."""
    ws = _quitar_muletillas(_palabras(frase))
    if not ws:
        return False
    if _verbos(ws):
        return True
    if ws[0] in VERBOS_EXTRA or (re.match(r"^[a-z]{3,}[ae](?:me|nos|te)$", ws[0]) and ws[0] not in STOP and not RE_INTERROG.match(ws[0])):
        return True
    return RE_QUIERO.search(" ".join(ws)) is not None


class Turno:
    """Resultado de la capa K. La consola imprime `texto` y, segun el caso, corrige (G), reescribe, reinyecta o pide ensenar."""
    __slots__ = ("tipo", "texto", "intents", "reescribir", "reinyectar", "confirmar", "corregir", "porque", "ensenar", "info")

    def __init__(self, tipo, texto="", intents=(), **kw):
        self.tipo, self.texto, self.intents = tipo, texto, list(intents)
        self.reescribir = self.reinyectar = self.confirmar = None
        self.corregir = self.porque = self.ensenar = False
        self.info = kw.get("info", {})
        for k, v in kw.items():
            if k != "info":
                setattr(self, k, v)


PLANTILLAS = {
    "saludo": ["¡{buenas}{coma}!", "¡{buenas}{coma}! ¿En qué te ayudo?", "Hola{coma}. {buenas}. ¿Qué necesitas hoy?",
               "¡Hola{coma}! {buenas}, ¿qué hacemos?", "{buenas}{coma}. Aquí estoy; dime qué necesitas.", "¡{buenas}{coma}! Cuando quieras, empezamos."],
    "despedida": ["¡Hasta luego{coma}!", "Chao{coma}, que te vaya bien.", "{despedida_franja}", "Nos vemos{coma}. Aquí estaré.", "¡Cuídate{coma}!"],
    "agradecimiento": ["¡De nada{coma}!", "Para eso estoy.", "Con gusto. ¿Algo más?", "No hay de qué{coma}.", "¡A ti por usarme! ¿Seguimos?"],
    "estado": ["Muy bien, gracias por preguntar. ¿Y tú{coma}?", "Todo en orden por aquí. ¿En qué te ayudo?",
               "Bien, listo para ayudarte. ¿Qué necesitas?", "¡Bien! Sin LLM, pero con ganas. ¿Y tú cómo estás?"],
    "identidad": ["Soy mbot-answer-flash, un asistente de consola en español. No uso un LLM: razono con reglas, mi memoria local y tus herramientas. "
                  "Pregúntame «qué puedes hacer».",
                  "Me llamo mbot-answer-flash. Entiendo lo que pides con reglas y con lo que me has enseñado (sin LLM, todo local). "
                  "Dime «qué puedes hacer» y te cuento.",
                  "Soy mbot-answer-flash: abro cosas, consulto tus notas y aprendo de lo que me enseñas. No soy un modelo de lenguaje."],
    "afirmacion": ["No tengo ninguna pregunta pendiente{coma}. ¿Qué necesitas?", "Vale. ¿Qué hago ahora?", "Perfecto. Dime qué necesitas.",
                   "De acuerdo. Cuando quieras, dime qué hacer."],
    "negacion": ["Vale, no hago nada.", "Entendido, no toco nada.", "De acuerdo, lo dejo así.", "Ok, sin problema."],
    "elogio": ["¡Gracias{coma}! ¿Algo más?", "Me alegra{coma}. ¿Seguimos?", "¡Qué amable! Aquí sigo para lo que necesites.",
               "Gracias, hago lo que puedo. ¿Algo más?"],
    "risa": ["¡Jaja!", "Jeje, me alegra que te rías.", "Me alegra sacarte una sonrisa.", "Jaja, ¿y ahora qué hacemos?"],
    "disculpa": ["No pasa nada{coma}.", "Tranquilo{coma}, no hay problema.", "Sin problema, seguimos cuando quieras.", "Nada que perdonar{coma}."],
    "queja": ["Perdona{coma}, a veces me equivoco. Escribe !porque y te muestro cómo razoné, o enséñame qué querías y lo aprendo.",
              "Tienes razón en quejarte{coma}: no soy perfecto. Prueba con !porque para ver cómo entendí tu frase, o dime el comando correcto y lo guardo.",
              "Lo siento{coma}. Puedo mejorar si me ayudas: !porque explica mi razonamiento y puedes enseñarme la acción con !aprender frase => comando."],
    "queja_g": ["Perdona{coma}. Lo último que hice («{ultima}») no era lo que querías; lo corrijo.",
                "Lo siento{coma}, me equivoqué con «{ultima}». Lo anoto como fallo y dime qué era.",
                "Tienes razón{coma}: «{ultima}» no era lo correcto. Vamos a corregirlo."],
    "perdido": ["Si no sabes qué hacer{coma}, prueba con {ejemplos} o escribe !hoy para ver tu resumen.",
                "Te propongo algo{coma}: {ejemplos}. También puedes escribir !hoy.",
                "Hay cosas que puedo hacer ahora mismo: {ejemplos}. Y con !hoy ves tu día."],
    "no_entendi": ["No entendí.", "No entendí eso. ¿Puedes decirlo de otra forma?", "No entendí. Prueba con «qué puedes hacer»."],
    "charla_sin": ["No estoy seguro de qué quieres decir. Prueba con «qué puedes hacer».", "No estoy seguro{coma}. Dime «qué puedes hacer» y te cuento lo que sé hacer.",
                   "No estoy seguro de lo que me pides. Con «ayuda» te muestro ejemplos."],
    "charla_con": ["No estoy seguro. ¿Querías decir: {sug}?", "Mmm, no lo tengo claro. ¿Querías decir: {sug}?", "No estoy seguro{coma}. ¿Quizá: {sug}?"],
}


class Conversacion:
    def __init__(self, A, reloj=None, semilla=None):
        self.A = A
        self.reloj = reloj or (lambda: A.personal.ahora())          # inyectable (en las pruebas: reloj fijo)
        self.rng = random.Random(semilla)
        self.mem = deque(maxlen=MEM_TURNOS)                          # ultimas interacciones de ordenes
        self._ultima_plantilla = {}
        self._saludo_dia = None
        self._cache = {}
        self._n_cap = 0
        self.pend_si = None                                          # sugerencias del fallback del turno anterior
        self.alt = None                                              # {"pool", "ptr", "d"}: alternativas para "la otra"/"la segunda"
        self.k_vigente = False                                       # el ultimo turno lo respondio K (para !porque)
        self.ult = None                                              # explicacion del ultimo turno de K
        self._n_k = 0                                                # turnos de K desde la ultima orden (0 = "justo antes")

    # ------------------------------------------------------------ clasificacion
    def _extra_relleno(self):
        n = self._nombre()
        return {n.lower()} if n else set()

    def _corregir_typos(self, norm):
        out, cambio = [], False
        for w in norm.split():
            if len(w) >= 4 and w not in _VOCAB_SET and not w.isdigit():
                c = cercano(w, VOCAB, 0.8)
                if c:
                    w, cambio = c, True
            out.append(w)
        return " ".join(out), cambio

    def _segmentar(self, norm, extra):
        if not norm or len(norm.split()) > 9:
            return None
        spans = []
        for p in PATRONES:
            for m in p.rx.finditer(norm):
                spans.append((m.start(), m.end(), p, m.group()))
        if not spans:
            return None
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        sel, fin = [], -1
        for st, en, p, txt in spans:
            if st >= fin:
                sel.append((st, en, p, txt))
                fin = en
        resto, pos = [], 0
        for st, en, _p_, _t in sel:
            resto += norm[pos:st].split()
            pos = en
        resto += norm[pos:].split()
        if any(w not in RELLENO and w not in extra for w in resto):
            return None
        return sel

    def clasificar(self, frase):
        """-> dict(intents, partes, norm, corregida) o None. Solo si la frase ENTERA es conversacion."""
        r = self._cache.get(frase, 0)
        if r != 0:
            return r
        norm = normalizar(frase)
        extra = self._extra_relleno()
        sel = self._segmentar(norm, extra)
        corr = False
        if sel is None:
            n2, cambio = self._corregir_typos(norm)
            if cambio:
                sel = self._segmentar(n2, extra)
                if sel is not None:
                    norm, corr = n2, True
        res = None
        if sel:
            partes = [(p.intent, p.nombre, txt, p.grupo) for _s, _e, p, txt in sel]
            ints = []
            for it, _n, _t, _g in partes:
                if it not in ints:
                    ints.append(it)
            seg = [i for i in ints if i in SEGUIMIENTOS]
            if seg:
                if len(partes) == 1:
                    res = {"intents": seg, "partes": partes, "norm": norm, "corregida": corr}
            else:
                if any(i in FUERTES for i in ints):
                    ints = [i for i in ints if i not in DEBILES]
                res = {"intents": ints, "partes": partes, "norm": norm, "corregida": corr}
        if len(self._cache) > 3000:
            self._cache.clear()
        self._cache[frase] = res
        return res

    def _y_ahora(self, frase):
        """('y ahora X') -> X o None. Solo frases cortas que empiezan por 'y' y cuyo resto no es una pregunta."""
        t = normalizar(frase)
        m = RE_Y.match(t)
        if not m:
            return None
        resto = m.group("resto").strip()
        if not resto or len(resto.split()) > 7 or RE_INTERROG.match(resto):
            return None
        return resto

    def detecta(self, frase):
        """Intenciones (lista) si la frase entera es conversacion o seguimiento; None si no. Sin efectos."""
        c = self.clasificar(frase)
        if c:
            return list(c["intents"])
        if self._y_ahora(frase) is not None:
            return ["seguimiento_y"]
        return None

    # ------------------------------------------------------------ contexto
    def _nombre(self):
        try:
            h = self.A.personal.activo("nombre")
        except Exception:
            return ""
        if not h or not h.get("valor"):
            return ""
        m = re.search(r"[^\W\d_]+", str(h["valor"]))
        return m.group(0).capitalize() if m else ""

    def _franja(self):
        h = self.reloj().hour
        return "dias" if 5 <= h < 12 else "tardes" if 12 <= h < 20 else "noches"

    def _resumen_hoy(self):
        hoy = self.reloj().date()
        try:
            pen = [r for r in self.A.personal.pendientes() if _desde_iso(r["next_run"]).date() == hoy]
        except Exception:
            pen = []
        if not pen:
            return "No tienes recordatorios para hoy. Si quieres ver tu resumen del día, escribe !hoy."
        det = ", ".join(f"{_desde_iso(r['next_run']).strftime('%H:%M')} {r['texto']}" for r in pen[:3]) + (f" (+{len(pen) - 3} más)" if len(pen) > 3 else "")
        return f"Hoy tienes {len(pen)} recordatorio{'s' if len(pen) != 1 else ''} pendiente{'s' if len(pen) != 1 else ''}: {det}. Escribe !hoy para ver tu resumen del día."

    def _plantilla(self, clave, ctx=None):
        """Elige una plantilla distinta de la ultima usada para esa clave. -> (texto, indice, total)."""
        lista = PLANTILLAS[clave]
        ult = self._ultima_plantilla.get(clave)
        i = self.rng.choice([k for k in range(len(lista)) if k != ult] or [0])
        self._ultima_plantilla[clave] = i
        nombre = self._nombre()
        c = {"coma": f", {nombre}" if nombre else "", "nombre": nombre}
        fr = self._franja()
        c["buenas"] = {"dias": "Buenos días", "tardes": "Buenas tardes", "noches": "Buenas noches"}[fr]
        c["despedida_franja"] = ("¡Hasta mañana" + c["coma"] + "! Que descanses.") if fr == "noches" else ("¡Que tengas una buena " + ("mañana" if fr == "dias" else "tarde") + c["coma"] + "!")
        c.update(ctx or {})
        return lista[i].format(**c), i, len(lista)

    # ------------------------------------------------------------ "que puedes hacer" (del registro real)
    @staticmethod
    def _ejemplo(h):
        for e in re.findall(r"'([^']{3,70})'", h.descripcion or ""):
            e = e.strip().lstrip("¿�").rstrip("?").strip()
            if e and not e.startswith("(") and not e.lower().startswith(("opcional", "en d:")):
                return e
        return None

    def _pool_ejemplos(self):
        """(herramientas, tareas, comandos): ejemplos reales leidos AHORA del registro, de las tareas aprendidas y de los comandos '!'."""
        try:
            activas = list(self.A.herr.activas())
        except Exception:
            activas = [h for h in REGISTRO.values()]
        herr = []
        for h in activas:
            if h.peligro:
                continue
            e = self._ejemplo(h)
            if e:
                herr.append((h, e))
        herr.sort(key=lambda x: (x[0].origen == "interna", x[0].nombre in DOC_TOOLS, x[0].nombre))     # plugins primero; las de documentos (piden un archivo) al final
        tareas = []
        for t in sorted(self.A.tareas, key=lambda t: (-t["usos"], t["cmd"])):
            if MARK.search(t["cmd"]) or es_peligroso(t["cmd"]) or "shutdown" in t["cmd"].lower():
                continue
            fr = [f for f in t["frases"] if "{" not in f]
            if fr:
                tareas.append(fr[0])
        return herr, tareas, list(BANG)

    def capacidades(self, solo_ejemplos=False):
        herr, tareas, bang = self._pool_ejemplos()
        self._n_cap += 1
        n = self._n_cap
        plug = [x for x in herr if x[0].origen != "interna"]
        internas = [x for x in herr if x[0].origen == "interna"]
        if plug:
            k = (n - 1) % len(plug)
            plug = plug[k:] + plug[:k]
        if internas:
            base = [x for x in internas if x[0].nombre not in DOC_TOOLS]
            k = (n * 3) % len(base) if base else 0
            internas = base[k:] + base[:k] + [x for x in internas if x[0].nombre in DOC_TOOLS]
        elegidas = plug[:2]
        elegidas += internas[:max(0, 3 - len(elegidas))]
        if tareas:                                              # lo mas usado primero; rota para variar
            k = (n - 1) % len(tareas)
            tareas = tareas[k:] + tareas[:k]
        tareas = tareas[:2]
        nb = min(len(bang), max(1, min(6 - len(elegidas) - len(tareas), 2)))
        if len(elegidas) + len(tareas) + nb < 4:
            nb = min(len(bang), 4 - len(elegidas) - len(tareas))
        if bang:
            k = (n - 1) % len(bang)
            bang = (bang[k:] + bang[:k])[:nb]
        L = []
        if elegidas:
            L.append("Herramientas: " + ", ".join(f"«{e}»" + (" (plugin)" if h.origen != "interna" else "") for h, e in elegidas))
        if tareas:
            L.append("Lo que me has enseñado: " + ", ".join(f"«{t}»" for t in tareas))
        if bang:
            L.append("Comandos: " + ", ".join(f"«{c}» ({d})" for c, d in bang))
        ej = [f"«{e}»" for _h, e in elegidas] + [f"«{t}»" for t in tareas]
        if solo_ejemplos:
            return ej + [f"«{c}»" for c, _d in bang]
        total_h, total_t = len(herr), len(self.A.tareas)
        return ("Puedo ayudarte con cosas como:\n" + "\n".join("  - " + x for x in L) +
                f"\n({total_h} herramientas activas y {total_t} tareas aprendidas; !herramientas y !lista las muestran.)")

    # ------------------------------------------------------------ memoria de dialogo
    def _tick(self):
        """Cada turno: lo pendiente del turno anterior se consume."""
        p, self.pend_si = self.pend_si, None
        return p

    def _verbo_de(self, frase, d):
        ws = _quitar_muletillas(_palabras(frase))
        v = _verbos(ws)
        if v:
            return v[0][0], v[0][1]
        if ws and ws[0] in VERBOS_EXTRA:
            return ws[0], []
        return None, []

    def registrar(self, frase, d):
        """Turno normal (K no lo atendio): lo que ve la memoria de dialogo."""
        self.pend_si = None
        self.k_vigente = False
        self._n_k = 0
        orden = d is not None and d.accion in ("ejecutar", "confirmar", "preguntar") and bool(d.cmd)
        v, cl = self._verbo_de(frase, d) if orden else (None, [])
        rec = {"frase": frase, "tipo": "orden" if orden else "otro", "d": d, "verbo": v, "clases": cl, "reforzada": False}
        self.mem.append(rec)
        self.alt = {"d": d, "pool": None, "ptr": 0} if d is not None and d.cands else None
        return rec

    def registrar_otro(self):
        """Turno que no es una orden (personal, comandos '!'...): corta el 'justo antes' y las referencias."""
        self.pend_si = None
        self.k_vigente = False
        self._n_k = 0
        self.alt = None
        self.mem.append({"frase": "", "tipo": "otro", "d": None, "verbo": None, "clases": [], "reforzada": False})

    def _ultima_orden(self, solo_ultimo=True):
        """Registro de la ultima orden; con solo_ultimo, exige que el ultimo turno de la memoria sea esa orden."""
        if not self.mem:
            return None
        if solo_ultimo:
            r = self.mem[-1]
            return r if r["tipo"] == "orden" else None
        for r in reversed(self.mem):
            if r["tipo"] == "orden":
                return r
        return None

    def _delicada(self, rec):
        d = rec["d"]
        return bool(d and (d.peligroso or (d.cmd and es_peligroso(d.cmd)) or (d.herr and REGISTRO.get(d.herr) and REGISTRO[d.herr].peligro)
                           or set(rec["clases"]) & DELICADAS))

    def _justo_antes(self):
        """Registro de la accion ejecutada con exito en el turno anterior (A.ultima), si ningun turno de charla se interpuso."""
        r = self._ultima_orden(True)
        if r is None or self._n_k != 0:
            return None
        u = getattr(self.A, "ultima", None)
        if u is not None and not isinstance(u, list) and r["d"] is u:
            return r
        return None

    def _refuerzo_suave(self, rec):
        """'gracias' tras una accion exitosa: +REFUERZO_SUAVE de acierto (una vez) en G. No toca frases, vetos ni la red."""
        d = rec["d"]
        if rec["reforzada"] or d is None or d.herr or not getattr(d, "cmd_t", None):
            return False
        i = self.A._tarea(d.cmd_t)
        if i is None:
            return False
        import time
        t = self.A.tareas[i]
        ahora = time.time()
        t["a"], t["f"] = decaer(t["a"], t["f"], t["ts"], ahora)
        t["a"] += REFUERZO_SUAVE
        t["ts"] = ahora
        rec["reforzada"] = True
        self.A.guardar()
        self.A._indexar()
        return True

    # ------------------------------------------------------------ etiquetas de candidatos
    def _etiqueta(self, c):
        """(texto, tipo) de un candidato de decidir() que se puede ofrecer; None si no: 'frase' (tarea aprendida: se reinyecta) o
        'pista' (herramienta: solo se muestra como decirlo; nunca se ejecuta a partir de una conjetura)."""
        cmd = c["cmd"]
        if c.get("ayuda") or es_peligroso(cmd) or "shutdown" in cmd.lower():
            return None
        hx = c["extra"].get("H")
        if hx:
            h = REGISTRO.get(hx["nombre"])
            if h is None or h.peligro:
                return None
            e = self._ejemplo(h)
            return (e, "pista") if e else None
        i = c["idx"]
        if i is not None and i < len(self.A.tareas) and not self.A.tpl[i]:
            fr = [f for f in self.A.tareas[i]["frases"] if "{" not in f]
            if fr:
                return (min(fr, key=len), "frase")
        return None

    def _pool_alternativas(self, d, excluir_actual=True, minimo=None):
        minimo = CONF_ALT if minimo is None else minimo
        pool, vistos = [], set()
        for c in d.cands:
            if excluir_actual and d.cmd and c["cmd"] == d.cmd:
                continue
            if c["conf"] < minimo:
                continue
            e = self._etiqueta(c)
            if e and e[0].lower() not in vistos:
                vistos.add(e[0].lower())
                pool.append({"label": e[0], "tipo": e[1], "reinyectar": e[0] if e[1] == "frase" else None})
        return pool

    def _pistas_herramientas(self, frase, excluir):
        """Herramientas parecidas por palabras de contenido compartidas con su descripcion (solo para sugerir)."""
        qt = {w for w in tokens(frase) if len(w) >= 4}
        if not qt:
            return []
        out = []
        for h in (self.A.herr.activas() if hasattr(self.A, "herr") else REGISTRO.values()):
            if h.peligro:
                continue
            e = self._ejemplo(h)
            if not e or e.lower() in excluir:
                continue
            ht = {w for w in tokens(re.sub(r"\(.*?\)", " ", h.descripcion) + " " + e) if len(w) >= 4}
            sc = len(qt & ht)
            if sc:
                out.append((sc, e))
        out.sort(key=lambda x: -x[0])
        return [{"label": e, "tipo": "pista", "reinyectar": None} for _s, e in out]

    def interpretar_peticion(self, frase):
        """Elige una respuesta conversacional antes de derivar al motor de comandos."""
        plano = " ".join(sin_tildes(frase.lower()).strip(" ¿?¡!.").split())
        eleccion, puntajes = elegir_peticion(plano)
        intent = eleccion.value
        reescribir = None
        if eleccion == Peticion.INSTRUCCIONES:
            pregunta = _COMO_ABRIR.fullmatch(plano)
            app = _APPS_INICIO.get(pregunta["objeto"])
            if app:
                texto = f"En Windows, abre Inicio, escribe «{app}» y selecciona el resultado."
            else:
                d = Decision()
                d.texto, d.abierta = frase, True
                self.A.responder_pregunta(d)
                texto = (d.respuesta.texto if d.respuesta else
                         "No tengo instrucciones para ese caso. ¿Es una aplicación de Windows o un archivo? "
                         "Si es un archivo, dime su extensión.")
        elif eleccion == Peticion.NEGACION:
            texto = "Entendido, omito esa acción."
            calculo = _CALCULO_TRAS_NEGACION.search(plano)
            if calculo:
                intent += " y pedir un cálculo"
                if self.A.usar_herramientas:
                    d = Decision()
                    d.herr, d.hslots = "calcular", {"expresion": calculo["expresion"]}
                    texto += "\n" + self.A.ejecutar_herramienta(d, frase).texto
                else:
                    texto += "\nLa calculadora interna está deshabilitada."
        elif eleccion == Peticion.NOTA:
            if self.A.usar_herramientas and self.A.herr.estado("nota_agregar")[0] == "habilitada":
                texto, reescribir = "", "toma nota"
            else:
                texto = "La herramienta de notas está deshabilitada."
        elif eleccion == Peticion.FISICA:
            d = self.A.decidir(frase)
            if d.capa == "A" or (d.herr and d.accion in ("ejecutar", "confirmar")):
                return None      # una asociación exacta o una herramienta explícita puede cubrir la acción
            texto = "Esa acción física está fuera de mi alcance."
        else:
            return None

        self.registrar_otro()
        info = {"frase": frase, "norm": plano,
                "partes": [{"intent": intent, "patron": "interpretar petición", "coincidio": plano}],
                "puntajes": {opcion.value: valor for opcion, valor in puntajes.items()},
                "hora": self.reloj().strftime("%H:%M"), "nombre": self._nombre()}
        return self._marcar(Turno("peticion", texto, (intent,), reescribir=reescribir), info)

    # ------------------------------------------------------------ atender (intenciones y seguimientos)
    def atender(self, frase, d, seguimiento=True):
        """Turno de K o None. `d` = decidir(frase). Nunca ejecuta nada por si misma."""
        pend = self._tick()
        t = (frase or "").strip()
        if not t or t.startswith("!"):
            return None
        c = self.clasificar(t)
        aprendida = d is not None and d.accion in ("ejecutar", "confirmar") and d.capa == "A"
        if c:
            ints = c["intents"]
            if any(i in SEGUIMIENTOS for i in ints):
                if not seguimiento or aprendida:
                    return None
                return self._seguimiento(ints[0], c, t, d, pend)
            if d is not None and (d.accion in ("ejecutar", "confirmar", "rechazar", "responder")):
                return None                                    # lo aprendido y las herramientas ganan
            if "fechahora" in ints and d is not None and d.herr in ("hora", "fecha"):
                return None
            return self._intencion(c, t, d, pend)
        if seguimiento and not aprendida:
            resto = self._y_ahora(t)
            if resto is not None:
                return self._y_ahora_turno(t, resto)
        return None

    def _info(self, c, frase, extra=None):
        i = {"frase": frase, "norm": c["norm"], "corregida": c["corregida"],
             "partes": [{"intent": it, "patron": f"{it}/{nom}", "coincidio": txt} for it, nom, txt, _g in c["partes"]],
             "hora": self.reloj().strftime("%H:%M"), "nombre": self._nombre()}
        i.update(extra or {})
        return i

    def _marcar(self, turno, info):
        self.ult = {"tipo": turno.tipo, "info": info, "intents": turno.intents}
        self.k_vigente = True
        self._n_k += 1
        return turno

    def _intencion(self, c, frase, d, pend):
        ints = [i for i in ORDEN_PRIO if i in c["intents"]][:2]
        hay_fh = "fechahora" in c["intents"]
        partes, plant = [], {}
        justo = self._justo_antes()
        corregir = False
        for it in ints:
            if it == "saludo":
                txt, i, n = self._plantilla("saludo")
                hoy = self.reloj().date()
                if self._saludo_dia != hoy:
                    txt += "\n" + self._resumen_hoy()
                    self._saludo_dia = hoy
                    plant["resumen"] = "primer saludo del día"
                partes.append(txt)
            elif it == "capacidad":
                i, n = 0, 1
                partes.append(self.capacidades())
            elif it == "perdido":
                ej = self.capacidades(solo_ejemplos=True)
                txt, i, n = self._plantilla("perdido", {"ejemplos": ", ".join(ej[:3])})
                partes.append(txt)
            elif it == "queja":
                error = any(nom == "queja_error" for it2, nom, _t, _g in c["partes"] if it2 == "queja")
                if error and justo is not None:
                    ultima = justo["frase"] or (justo["d"].cmd if justo["d"] else "")
                    txt, i, n = self._plantilla("queja_g", {"ultima": ultima})
                    corregir = True
                else:
                    txt, i, n = self._plantilla("queja")
                partes.append(txt)
            elif it == "afirmacion" and pend:
                return self._afirma_pendiente(c, frase, pend)
            elif it == "agradecimiento":
                if justo is not None and self._refuerzo_suave(justo):
                    plant["refuerzo"] = f"+{REFUERZO_SUAVE} acierto suave a {justo['d'].cmd_t!r} (G)"
                txt, i, n = self._plantilla("agradecimiento")
                partes.append(txt)
            elif it in PLANTILLAS:
                txt, i, n = self._plantilla(it)
                partes.append(txt)
            else:
                continue
            plant[it] = f"plantilla {i + 1} de {n}"
        reescribir = None
        if hay_fh:
            fecha = any(nom == "fecha" for it2, nom, _t, _g in c["partes"] if it2 == "fechahora")
            reescribir = "que dia es hoy" if fecha else "que hora es"
        turno = Turno("intencion", "\n".join(partes), c["intents"], corregir=corregir, reescribir=reescribir)
        return self._marcar(turno, self._info(c, frase, {"respuestas": plant, "reescribe": reescribir}))

    def _afirma_pendiente(self, c, frase, pend):
        """'sí/dale' con sugerencias pendientes del fallback del turno anterior."""
        if len(pend) == 1:
            s = pend[0]
            if s["reinyectar"]:
                t = Turno("seguimiento", f"Entonces: «{s['label']}».", ["afirmacion"], reinyectar=s["reinyectar"])
            else:
                t = Turno("seguimiento", f"Dilo así y lo hago: «{s['label']}».", ["afirmacion"])
        else:
            t = Turno("seguimiento", "¿Cuál de ellas? Dime «la primera» o «la segunda».", ["afirmacion"])
            self.pend_si = pend
        return self._marcar(t, self._info(c, frase, {"seguimiento": "acepta la sugerencia pendiente", "sugerencias": [s["label"] for s in pend]}))

    # ------------------------------------------------------------ seguimientos
    def _seguimiento(self, kind, c, frase, d, pend):
        if kind == "porque":
            t = Turno("seguimiento", "", ["porque"], porque=True)
            return t                                           # no cuenta como turno de K: no altera lo que explica !porque
        if kind == "repetir":
            rec = self._ultima_orden(True)
            if rec is None:
                t = Turno("seguimiento", self._plantilla_texto(["Todavía no hice nada que pueda repetir.", "No hay una acción anterior que repetir."]), ["repetir"])
                return self._marcar(t, self._info(c, frase, {"seguimiento": "otra vez sin acción previa"}))
            delicada = self._delicada(rec)
            conf = f"⚠ La última acción fue delicada ({rec['d'].cmd}). ¿Repetirla? (s/n)" if delicada else None
            t = Turno("seguimiento", f"Repito: «{rec['frase']}».", ["repetir"], reinyectar=rec["frase"], confirmar=conf)
            self.pend_si = None
            return self._marcar(t, self._info(c, frase, {"seguimiento": f"repetir «{rec['frase']}»", "delicada": delicada}))
        return self._seleccion(c, frase, d, pend)

    def _plantilla_texto(self, lista):
        return self.rng.choice(lista)

    @staticmethod
    def _ordinal(txt):
        m = re.search(r"\d", txt)
        if m:
            return int(m.group())
        for k, v in (("primer", 1), ("segund", 2), ("tercer", 3), ("cuart", 4), ("uno", 1), ("dos", 2), ("tres", 3), ("cuatro", 4)):
            if k in txt:
                return v
        if "ultima" in txt:
            return -1
        return None                                            # "la otra", "eso no", "siguiente"

    def _seleccion(self, c, frase, d, pend):
        txt = next((t for it, _n, t, _g in c["partes"] if it == "seleccion"), "")
        u = getattr(self.A, "ultima", None)
        if pend:                                               # sugerencias del fallback del turno anterior
            pool, origen = pend, "sugerencias del fallback"
            self.alt = {"d": None, "pool": pend, "ptr": 0}
        else:
            if self.alt is None:
                t = Turno("seguimiento", "No tengo opciones de la última vez. Dime qué quieres hacer.", ["seleccion"])
                return self._marcar(t, self._info(c, frase, {"seguimiento": "sin decisión previa"}))
            if self.alt["pool"] is None:
                self.alt["pool"] = self._pool_alternativas(self.alt["d"]) if self.alt["d"] is not None else []
            pool, origen = self.alt["pool"], "alternativas de la última decisión"
        ptr = self.alt["ptr"] if self.alt else 0
        n = self._ordinal(txt)
        k = (len(pool) - 1 if n == -1 else n - 1) if n is not None else ptr
        # "eso no" / "la otra" tras una accion ejecutada = "eso no era": la tarea se penaliza (G) como en 'no'
        penaliza = False
        r = self._ultima_orden(True)
        if txt.startswith(("eso no", "no es eso", "no era eso", "esa no", "no esa", "la otra", "el otro", "otra", "otro")) and r is not None \
                and u is not None and not isinstance(u, list) and r["d"] is u:
            penaliza = True
        if not pool or k < 0 or k >= len(pool):
            t = Turno("seguimiento", "No tengo otra opción cercana que ofrecerte. Dime qué querías (o enséñame el comando).", ["seleccion"])
            return self._marcar(t, self._info(c, frase, {"seguimiento": f"{origen}: sin más candidatos", "opciones": [p['label'] for p in pool]}))
        s = pool[k]
        if self.alt:
            self.alt["ptr"] = k + 1
        if penaliza:
            self.A.penalizar(u)
            self.A.ultima = None
        if s["reinyectar"]:
            t = Turno("seguimiento", f"Otra opción: «{s['label']}».", ["seleccion"], reinyectar=s["reinyectar"],
                      confirmar=f"¿Te refieres a «{s['label']}»? (s/n)")
        else:
            t = Turno("seguimiento", f"Otra opción: «{s['label']}». No la ejecuto a partir de una suposición; dilo así y lo hago.", ["seleccion"])
        return self._marcar(t, self._info(c, frase, {"seguimiento": f"{origen}: opción {k + 1} de {len(pool)}",
                                                      "opciones": [p['label'] for p in pool], "penaliza_g": penaliza}))

    def _y_ahora_turno(self, frase, resto):
        rec = self._ultima_orden(True)           # solo si el turno anterior fue esa orden (un turno fallido o de otro tipo corta la herencia)
        info = {"frase": frase, "norm": normalizar(frase), "corregida": False, "partes": [{"intent": "seguimiento_y", "patron": "seguimiento/y_ahora", "coincidio": "y ahora"}],
                "hora": self.reloj().strftime("%H:%M"), "nombre": self._nombre()}
        ws = _palabras(resto)
        if _verbos(_quitar_muletillas(ws)) or (ws and ws[0] in VERBOS_EXTRA):
            nueva = resto if resto == frase else " ".join(resto.split())      # ya trae su verbo: es una orden normal
            t = Turno("seguimiento", "", ["seguimiento_y"], reescribir=_restaurar(frase, nueva))
            info["seguimiento"] = "'y' + orden con verbo propio: orden normal"
            return self._marcar_silencioso(t, info)
        if rec is None or not rec["verbo"]:
            t = Turno("seguimiento", f"No sé qué hacer con «{resto}»; dime la acción completa (por ejemplo «abre {resto}»).", ["seguimiento_y"])
            info["seguimiento"] = "sin orden previa de la que heredar el verbo"
            return self._marcar(t, info)
        delicado = bool(set(rec["clases"]) & DELICADAS)
        nueva = f"{rec['verbo']} {_restaurar(frase, resto)}"
        conf = f"Entiendo «{nueva}», que es una acción delicada. ¿Seguimos? (s/n)" if delicado else None
        t = Turno("seguimiento", "", ["seguimiento_y"], reescribir=None if delicado else nueva, reinyectar=nueva if delicado else None, confirmar=conf)
        info["seguimiento"] = f"hereda el verbo «{rec['verbo']}» de «{rec['frase']}» -> «{nueva}»" + (" (delicado: confirma)" if delicado else "")
        return self._marcar_silencioso(t, info)

    def _marcar_silencioso(self, t, info):
        self.ult = {"tipo": t.tipo, "info": info, "intents": t.intents}
        return t

    # ------------------------------------------------------------ fallback
    def fallback(self, frase, d):
        """La frase no se entendio (accion 'ensenar' sin respuesta del indice). -> Turno: no_entendi | orden | pregunta | charla."""
        t = (frase or "").strip()
        info = {"frase": t, "hora": self.reloj().strftime("%H:%M"), "nombre": self._nombre()}
        if t.startswith("!"):
            return Turno("fallback", "", ensenar=True, info=info)
        if sin_sentido(t):
            txt, i, n = self._plantilla("no_entendi")
            info["fallback"] = "sin palabras reconocibles (solo signos, letras sueltas o aporreo de teclado)"
            return self._marcar(Turno("fallback", txt, ["no_entendi"]), info)
        abierta = bool(d is not None and d.abierta)
        p = sin_tildes(t.lower()).strip(" .!¿?¡")
        orden = tiene_verbo_orden(t) and (not abierta or es_pedido(p))
        if orden:
            info["fallback"] = "parece una orden: tiene un verbo de acción y no se supo resolver"
            self.k_vigente = True
            self.ult = {"tipo": "fallback_orden", "info": info, "intents": ["orden"]}
            return Turno("fallback", "", ["orden"], ensenar=True, info=info)
        sug = []
        vistos = set()
        if d is not None:
            for s in self._pool_alternativas(d, excluir_actual=False, minimo=CONF_SUG):
                if s["label"].lower() not in vistos:
                    vistos.add(s["label"].lower())
                    sug.append(s)
        if abierta:
            if getattr(self.A, "conocimiento", None) is not None and self.A.conocimiento.disponible:
                q = t.strip().strip("¿?").strip()
                sug = sug[:2] + [{"label": "buscar en tus notas", "tipo": "buscar", "reinyectar": "!buscar " + q}]
        else:
            for s in self._pistas_herramientas(t, vistos):
                if len(sug) >= 3:
                    break
                sug.append(s)
        sug = sug[:3]
        pre = "No encuentro la respuesta en tus notas ni en lo indexado (!indexar <carpeta>). " if abierta else ""
        if sug:
            txt, i, n = self._plantilla("charla_con", {"sug": " / ".join(s["label"] for s in sug)})
            if abierta:
                txt = pre + txt
        else:
            txt, i, n = self._plantilla("charla_sin")
            txt = pre + txt if abierta else txt
        info["fallback"] = ("pregunta" if abierta else "charla") + ": sin verbo de acción; sugerencias de baja confianza / herramientas parecidas" + (" / @buscar" if abierta else "")
        info["sugerencias"] = [s["label"] for s in sug]
        turno = Turno("fallback", txt, ["pregunta" if abierta else "charla"], info=info)
        self._marcar(turno, info)
        self.pend_si = sug or None
        self.alt = {"d": None, "pool": sug, "ptr": 0} if sug else None
        return turno

    # ------------------------------------------------------------ !porque (capa K)
    def explicar(self):
        """Explicacion del ultimo turno si lo respondio K; None si el ultimo turno fue de comandos (entonces explica la capa H)."""
        if not self.k_vigente or not self.ult:
            return None
        i = self.ult["info"]
        detalle = "Interpretación de la petición." if self.ult["tipo"] == "peticion" else "Capa K (conversación), no se ejecutó nada."
        L = [f"  Frase: {i.get('frase')!r}", f"  {detalle}"]
        if i.get("norm") is not None:
            L.append(f"  Normalizada: {i['norm']!r}" + ("  (con corrección de typos)" if i.get("corregida") else ""))
        for p in i.get("partes", []):
            L.append(f"  Intención detectada: {p['intent']}  <- patrón «{p['patron']}» (coincidió con {p['coincidio']!r})")
        if i.get("puntajes"):
            L.append("  Puntajes de las opciones: " + ", ".join(f"{opcion} ({valor})" for opcion, valor in i["puntajes"].items()))
        if i.get("fallback"):
            L.append(f"  Fallback: {i['fallback']}")
        if i.get("sugerencias"):
            L.append(f"  Sugerencias: {', '.join(i['sugerencias'])}")
        if i.get("seguimiento"):
            L.append(f"  Seguimiento: {i['seguimiento']}")
        if i.get("opciones"):
            L.append(f"  Opciones consideradas: {', '.join(i['opciones'])}")
        for k, v in (i.get("respuestas") or {}).items():
            L.append(f"  Respuesta ({k}): {v}; no repite la anterior")
        if i.get("reescribe"):
            L.append(f"  Se reencamina a la herramienta con la frase canónica {i['reescribe']!r}")
        L.append(f"  Contexto: hora {i.get('hora')}" + (f", nombre {i['nombre']}" if i.get("nombre") else ", sin nombre guardado"))
        return "\n".join(L)


def _restaurar(original, resto_norm):
    """Devuelve el resto de 'y ahora X' con su ortografia original (tildes, mayusculas) cuando se puede localizar en la frase."""
    m = re.match(r"^\s*[yY]\s+(?:(?:ahora|luego|despu[eé]s|tambi[eé]n|entonces)\s+)?(.+?)\s*$", original.strip())
    if m:
        return " ".join(m.group(1).split()).rstrip("?!.")
    return resto_norm
