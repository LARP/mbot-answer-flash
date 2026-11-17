"""Capa S: lexico de clases, sitios conocidos, marcos accion x objeto."""
import re

from .config import S_BASE
from .texto import STOP, sin_tildes

# ---------------------------------------------------------------- lexico semantico (S)
# clase -> miembros (sin tildes). Las formas conjugadas caen en la clase por raiz ligera (ver raiz_lex).
ACCIONES = {
    "ABRIR": "abrir abre abri abras abra abro abrio abreme abrime ejecutar ejecuta ejecuto inicia iniciar lanza lanzar "
             "arranca arrancar corre pon pone poner ponme poneme activa activar enciende encender prende prender open launch run",
    "CERRAR": "cerrar cierra cierre cierro cierres close mata matar matame mate kill termina terminar finaliza finalizar "
              "detener deten detiene fuerza forzar",
    "BORRAR": "borrar borra borro borres borre borrame eliminar elimina elimine eliminame suprimir suprime suprimo "
              "quitar quita quitame remover remueve remove delete erase",
    "COPIAR": "copiar copia copie copio duplicar duplica clonar clona respaldar respalda copy",
    "MOVER": "mover mueve muevo mueva trasladar traslada mudar muda cortar corta move",
    "CREAR": "crear crea creo cree crees generar genera armar arma make",
    "BUSCAR": "buscar busca busco busque encontrar encuentra localizar localiza hallar halla search find",
    "VER": "ver ve veo mira mirar muestra mostrar muestrame mostrame ensenar ensena ensename listar lista listame "
           "revisar revisa revisame consultar consulta dime checar checa chequear chequea verificar verifica display",
    "APAGAR": "apagar apaga apague apago apagame apagues shutdown poweroff",
    "REINICIAR": "reiniciar reinicia reinicie reinicio reinicias reboot restart resetear resetea",
    "BLOQUEAR": "bloquear bloquea bloquee bloqueo lock",
    "DIBUJAR": "dibujar dibuja dibujo dibujos dibujame dibujando pintar pinta pinto pintura pintame ilustrar ilustra "
               "ilustracion disenar disena diseno bosquejar bosqueja garabatear garabato paint mspaint",
    "REPRODUCIR": "escuchar escucha escucho escuches escuchame oir oigo oye oyes oiga reproducir reproduce reproduzco "
                  "reproduzca reproduces sonar suena sonando poner pon pone ponme poneme ponga tocar toca play",
    "ESCRIBIR": "escribir escribe escribo escribi redactar redacta redacto anotar anota anoto apuntar apunta tipear "
                "tipea teclear teclea notas nota",
    "CALCULAR": "calcular calcula calculo calculas calculadora calculator calc sumar suma sumo restar resta restas "
                "multiplicar multiplica dividir divide operacion operaciones porcentaje",
    "NAVEGAR": "navegar navega navego navegador browser internet buscador surfear visitar visita visito entrar entra ir",
    "CONFIGURAR": "configurar configura configuro configuracion configuraciones ajustes ajusta ajustar opciones "
                  "preferencias personalizar settings",
    "RED": "ip red redes wifi conexion conectividad dns router lan network",
    "MEDIR": "ping pinguear pingea latencia tracert traza",
    "LIMPIAR": "limpiar limpia limpio limpie vaciar vacia depurar",
}
OBJETOS = {
    "ARCHIVO": "archivo archivos fichero ficheros documento documentos doc file files",
    "CARPETA": "carpeta carpetas directorio directorios folder folders dir",
    "PROCESO": "proceso procesos programa programas aplicacion aplicaciones app apps process",
    "EQUIPO": "equipo equipos computador computadora computadoras computadores ordenador ordenadores pc pcs laptop "
              "portatil notebook maquina compu windows",
    "MUSICA": "musica cancion canciones audio melodia album playlist mp3 radio podcast rola rolas",
    "VIDEO": "video videos pelicula peliculas peli pelis film serie series clip",
    "IMAGEN": "imagen imagenes foto fotos fotografia fotografias picture pic",
    "SITIO": "sitio sitios pagina paginas web website url link enlace portal",
    "TEXTO": "texto textos bloc notepad editor carta",
    "DISCO": "disco discos unidad unidades usb pendrive",
    "PANTALLA": "pantalla consola terminal",
    # herramientas internas (bloque 2)
    "HORA": "hora horas reloj",
    "FECHA": "fecha dia dias hoy calendario",
    "ESPACIO": "espacio espacios libre libres disponible disponibles queda quedan",
    "PORTAPAPELES": "portapapeles clipboard",
    "TAMANO": "tamano tamanos peso pesa pesan ocupa ocupan",
}
GENERICAS = {"ABRIR", "VER"}
COMPAT_ABRIR = {"REPRODUCIR", "DIBUJAR", "ESCRIBIR", "CALCULAR", "NAVEGAR", "CONFIGURAR"}
IGN = set("sobre entre hasta desde hacia muy tambien todo toda todos todas cada pero si ni ya ahi aqui aca va van "
          "tengo tienes hay mi tu bien".split())
APP_EXE = {"calculadora": "calc", "bloc": "notepad", "paint": "mspaint", "explorador": "explorer", "notas": "notepad"}
SITIOS = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com", "whatsapp web": "https://web.whatsapp.com",
    "whatsapp": "https://web.whatsapp.com", "github": "https://github.com", "wikipedia": "https://es.wikipedia.org",
    "chatgpt": "https://chatgpt.com", "netflix": "https://www.netflix.com", "twitter": "https://twitter.com",
    "instagram": "https://www.instagram.com", "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com", "amazon": "https://www.amazon.com", "mercadolibre": "https://www.mercadolibre.com",
    "mercado libre": "https://www.mercadolibre.com", "twitch": "https://www.twitch.tv", "tiktok": "https://www.tiktok.com",
    "pinterest": "https://www.pinterest.com", "telegram": "https://web.telegram.org", "outlook": "https://outlook.live.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
    "google translate": "https://translate.google.com", "traductor": "https://translate.google.com",
    "disney plus": "https://www.disneyplus.com", "prime video": "https://www.primevideo.com",
    "stackoverflow": "https://stackoverflow.com", "bing": "https://www.bing.com", "yahoo": "https://www.yahoo.com",
    "claude": "https://claude.ai",
}
_SUF = sorted("ando iendo amos emos imos aron ieron aban aran eran aras eras ado ido ion ar er ir as es an en os a e o s".split(),
              key=len, reverse=True)
_ENCL = ("me", "te", "se", "lo", "la", "le", "nos", "les", "los", "las")


def raiz_lex(w):
    """Raiz ligera para el lexico: quita una desinencia verbal/plural comun (deja >= 3 letras)."""
    for s in _SUF:
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)]
    return w


LEX_EX, LEX_ST = {}, {}
for _tabla in (ACCIONES, OBJETOS):
    for _k, _m in _tabla.items():
        for _w in _m.split():
            if _k not in LEX_EX.setdefault(_w, ()):
                LEX_EX[_w] = LEX_EX[_w] + (_k,)
            if len(_w) >= 4 and len(raiz_lex(_w)) >= 3:
                _r = raiz_lex(_w)
                if _k not in LEX_ST.get(_r, ()):
                    LEX_ST[_r] = LEX_ST.get(_r, ()) + (_k,)
_CL_CACHE = {}


def clases_de(w):
    """Palabra (sin tildes, minusculas) -> tupla de clases del lexico, o None."""
    if w in _CL_CACHE:
        return _CL_CACHE[w]
    r = LEX_EX.get(w)
    if r is None and len(w) >= 4:
        r = LEX_ST.get(raiz_lex(w))
    if r is None:
        for e in _ENCL:                                  # dibujame, ponme, borrarlo
            if w.endswith(e) and len(w) - len(e) >= 3:
                b = w[:-len(e)]
                r = LEX_EX.get(b) or (LEX_ST.get(raiz_lex(b)) if len(b) >= 4 else None)
                if r is None and b[-1:] in "aei":
                    r = LEX_EX.get(b + "r") or LEX_ST.get(raiz_lex(b + "r"))
                if r:
                    break
    _CL_CACHE[w] = r
    return r


class Marco:
    """(ACCION, OBJETO, slots) de una frase. acts/objs en orden de aparicion; resid = palabras sin clase."""
    __slots__ = ("acts", "objs", "resid", "cont", "sitio", "prim", "obj", "via", "nslots", "inf")

    def __init__(self):
        self.acts, self.objs, self.resid, self.cont, self.via = [], [], [], [], []
        self.sitio, self.prim, self.obj, self.nslots, self.inf = None, None, None, 0, []


def marco_de(slot_text, slots):
    m = Marco()
    words = re.findall(r"\{[a-z_]+\d*\}|[a-z0-9]+", sin_tildes(slot_text.lower()))
    i = 0
    carp = []
    while i < len(words):
        w = words[i]
        if w.startswith("{"):
            carp.append(w)
            i += 1
            continue
        hit = None
        for n in (3, 2, 1):
            k = " ".join(words[i:i + n])
            if len(words[i:i + n]) == n and k in SITIOS:
                hit = (k, n)
                break
        if hit:
            m.sitio = (hit[0], SITIOS[hit[0]])
            i += hit[1]
            continue
        i += 1
        if w in STOP or w in IGN:
            continue
        cl = clases_de(w)
        m.cont.append((w, cl))
        if cl is None:
            m.resid.append(w)
            continue
        for k in cl:
            lst = m.acts if k in ACCIONES else m.objs
            if k not in lst:
                lst.append(k)
            m.via.append((w, k))
    explic = False
    for mk in carp:
        s = slots.get(mk)
        if not s:
            continue
        t = s["tipo"]
        if t == "carpeta":
            if "CARPETA" not in m.objs:
                cl = clases_de(s["alts"][0]) if s["alts"] else None
                ob = [k for k in (cl or ()) if k in OBJETOS] or ["CARPETA"]
                for k in ob:
                    if k not in m.objs:
                        m.objs.append(k)
                        m.via.append((s["lit"].lower(), k))
                explic = True
        elif t == "ruta" and not ({"ARCHIVO", "CARPETA"} & set(m.objs)):
            m.objs.append("ARCHIVO")
        elif t in ("url", "host") and "SITIO" not in m.objs:
            m.objs.append("SITIO")
        if not (t == "carpeta" and explic):
            m.nslots += 1
    esp = [a for a in m.acts if a not in GENERICAS]
    m.prim = esp[0] if esp else (m.acts[0] if m.acts else None)
    m.obj = m.objs[0] if m.objs else None
    return m


def puntuar_marco(m, a_t, o_t, prim=None, acts=None, resid=None):
    """Que tan bien casa el marco (a_t, o_t) de una tarea con el de la frase. 0 = no casa."""
    prim = m.prim if prim is None else prim
    acts = m.acts if acts is None else acts
    resid = m.resid if resid is None else resid
    abrir = False
    if a_t == prim:
        fa = 1.0
    elif a_t in acts:
        fa = 0.9
    elif "ABRIR" in acts and a_t in COMPAT_ABRIR:
        fa, abrir = 0.65, True
    else:
        return 0.0
    n = len(resid)
    if o_t is None:                                      # comodin aprendido: (DIBUJAR, *)
        if abrir and n:
            return 0.0
        fo = 0.6 if m.objs else (0.85 if n == 0 else 0.75 if n == 1 else 0.6)
    elif o_t in m.objs:
        fo = 1.0
    elif m.objs or prim in GENERICAS or prim is None:
        return 0.0
    else:
        fo = 0.75 if n == 0 else 0.3
    return S_BASE * fa * fo
