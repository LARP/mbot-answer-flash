"""Ejecucion de comandos y dialogos de consola (confirmar, completar, corregir)."""
import re, shutil, subprocess

from .config import UMBRAL_PREGUNTAR, es_peligroso
from .lexico import clases_de
from .herramientas import es_herramienta
from .slots import _seguro
from .texto import STOP, sin_tildes

INTERNOS = set("""assoc break call cd chdir cls color copy date del dir echo endlocal erase exit for ftype goto if md mkdir mklink
move path pause popd prompt pushd rd rem ren rename rmdir set setlocal shift start time title type ver verify vol""".split())


def parece_comando(A, cmd):
    """True si `cmd` parece un comando de CMD y no una frase en espanol (muchas palabras de STOP/lexico y ningun
    ejecutable o comando interno conocido)."""
    w = cmd.split()
    if not w:
        return False
    p = w[0].strip('"').lower()
    if p.endswith(".exe"):
        p = p[:-4]
    conocido = (p in INTERNOS or bool(shutil.which(w[0].strip('"'))) or p in {n for n, _d in A.desc.get("ayuda", [])}
                or any(a[2][:-4] == p for a in A.desc.get("apps", []) if a[2])
                or any(c in cmd for c in "\\/:|&<>%") or re.search(r"\s[-/]\w", cmd) is not None)
    if conocido:
        return True
    prosa = sum(1 for x in w if (sin_tildes(x.lower()) in STOP) or clases_de(sin_tildes(x.lower())))
    return not (prosa >= 2 or (len(w) >= 3 and prosa >= 1))


def confirmar_literal(A, cmd):
    """Si el texto escrito no parece un comando, pide confirmacion explicita antes de usarlo."""
    if parece_comando(A, cmd):
        return True
    return input(f"  Eso parece una frase, no un comando. ¿Ejecutar literalmente '{cmd}'? (s/n) ").strip().lower() == "s"


class EjecRes:
    """Resultado de ejecutar un comando de cmd: ok, codigo de retorno (None si es `start`, que no espera), salida, proceso."""
    def __init__(self, ok, rc=None, salida="", proc=None, cancelado=False):
        self.ok, self.rc, self.salida, self.proc, self.cancelado = ok, rc, salida, proc, cancelado


def ejecutar_ex(cmd, imprimir=True):
    """Ejecuta `cmd` en cmd.exe y devuelve un EjecRes. Es el UNICO sitio donde se lanza un subproceso de usuario.
    Los comandos internos de herramientas (@hora...) nunca llegan al shell."""
    if es_herramienta(cmd):
        if imprimir:
            print("  Eso es una herramienta interna; no se ejecuta en cmd.")
        return EjecRes(False, salida="herramienta interna")
    if es_peligroso(cmd) and input(f"  ⚠ '{cmd}' puede ser destructivo. ¿Ejecutar? (s/n) ").lower() != "s":
        if imprimir:
            print("  Cancelado.")
        return EjecRes(False, cancelado=True)
    try:
        if cmd.lower().startswith("start "):
            return EjecRes(True, None, "", subprocess.Popen(cmd, shell=True))
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, encoding="cp850", errors="replace")
        salida = (r.stdout + r.stderr).rstrip()
        if imprimir:
            print(salida or "  (sin salida)")
        return EjecRes(r.returncode == 0, r.returncode, salida)
    except subprocess.TimeoutExpired:
        if imprimir:
            print("  Tiempo agotado.")
        return EjecRes(False, salida="tiempo agotado")


def ejecutar(cmd):
    """Compatibilidad: True si se ejecuto bien (sin registro ni verificacion; para eso `A.correr`)."""
    return ejecutar_ex(cmd).ok


def correr_cmd(A, cmd, frase="", d=None):
    """Ejecuta con validacion de rutas, detector de bucles, registro y verificacion en segundo plano. True si salio bien."""
    c = A.correr(cmd, frase, d=d, asincrono=True, runner=ejecutar_ex)
    if c.estado == "rechazado":
        print(f"  ✗ Rechazado antes de ejecutar: {c.detalle}")
    elif c.estado == "bloqueado":
        print(f"  ⏸ '{cmd}' fallo 3 veces seguidas; queda bloqueado {c.detalle:.0f} s. Revisa el comando o usa !historial.")
    return c.estado not in ("rechazado", "bloqueado", "cancelado", "fallo")


RE_NO = re.compile(r"^(?:no|mal|eso no era|no era eso|no es eso|incorrecto|eso no|error)[.!\s]*$", re.I)


SI_NO = {"s", "si", "sí", "y", "yes", "claro", "dale", "ok", "okey", "vale", "n", "no", "nop", "nel", "nah"}
SI = {"s", "si", "sí", "y", "yes", "claro", "dale", "ok", "okey", "vale"}


def preguntar_comando(A, frase):
    """El asistente no supo resolver una ORDEN: pide confirmacion para que la enseñen. Un 'sí'/'dale'/'no' NUNCA se ejecuta como comando."""
    r = input(f"  No sé hacer «{frase}». ¿Me enseñas el comando? (Enter para saltar) ").strip()
    if r.lower().strip("¡!.¿?") in SI_NO:
        if r.lower().strip("¡!.¿?") not in SI:
            print("  Vale, lo dejamos.")
            return
        r = input("  Escribe el comando CMD (Enter para saltar): ").strip()
        if r.lower().strip("¡!.¿?") in SI_NO:
            print("  Eso no es un comando; lo dejamos.")
            return
    if r and confirmar_literal(A, r) and correr_cmd(A, r, frase):
        A.aprender(frase, r)
        print("  ✓ Aprendido.")


def completar(A, d):
    """Decision con huecos sin rellenar (borrar un archivo -> falta la ruta): pregunta, nunca inventa."""
    cmd = d.cmd
    nombres = {"ruta": "ruta completa", "host": "direccion (ej. ejemplo.com)", "app": "nombre del proceso (ej. notepad)"}
    for nom in d.falta:
        v = input(f"  Entendí «{d.cmd}» pero falta {nombres.get(nom, nom)}: ").strip().strip('"')
        if not _seguro(v) and nom != "app":
            print("  Valor vacío o con caracteres no permitidos. Cancelado.")
            return
        if nom == "app":
            v = v[:-4] if v.lower().endswith(".exe") else v
        cmd = cmd.replace("{%s}" % nom, v)
    correr_cmd(A, cmd, d.texto, d)


def usar_ayuda(A, d):
    desc = next((c["extra"].get("E", "") for c in d.cands if c["cmd"] == d.cmd), "")
    print(f"  {desc}")
    args = input(f"  Escribe los argumentos de '{d.cmd}' (Enter = ver '{d.cmd} /?'): ").strip()
    correr_cmd(A, f"{d.cmd} {args}" if args else f"{d.cmd} /?", d.texto)


def corregir(A, ult):
    """Tras un 'no': penaliza y pregunta cual era el comando correcto."""
    ds = ult if isinstance(ult, list) else [ult]
    if len(ds) > 1:
        try:
            k = int(input(f"  ¿Qué paso estuvo mal? (1-{len(ds)}) ").strip()) - 1
            d = ds[k]
        except (ValueError, IndexError):
            print("  Sin cambios.")
            return
    else:
        d = ds[0]
    A.penalizar(d)
    alts = [c for c in d.cands if c["cmd"] != d.cmd and not c["ayuda"] and c["conf"] >= UMBRAL_PREGUNTAR][:3]
    for n, c in enumerate(alts, 1):
        print(f"   {n}) {c['cmd']}")
    resp = input("  Entendido, anoto que eso no era. ¿Cuál era el comando correcto? "
                 "(número, comando o Enter para cancelar) ").strip()
    if resp.isdigit() and 1 <= int(resp) <= len(alts):
        resp = alts[int(resp) - 1]["cmd"]
    if resp and confirmar_literal(A, resp):
        A.aprender(d.texto, resp)
        print("  ✓ Aprendido: la próxima vez usaré ese comando.")
