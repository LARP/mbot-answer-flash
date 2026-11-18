"""Capa E: descubrimiento de apps de Windows (lnk, App Paths) y de la salida de `help`."""
import json, os, re, subprocess, time
from time import perf_counter

from .config import DESC_PATH
from .memoria import guardar_json
from .slots import FOLDER_ALIAS
from .texto import SIN, STOP, sin_tildes

APP_RUIDO = {"google", "microsoft", "windows", "adobe", "mozilla", "the"}
APP_MALOS = re.compile(r"desinstal|uninstall|readme|licen|manual|ayuda|help|sitio web|website|acerca|release notes", re.I)
APP_GENERICOS = {"ayuda", "herramientas", "accesorios", "sistema", "panel", "configuracion", "ejecutar", "inicio",
                 "opciones", "mantenimiento", "administracion", "centro", "tienda", "juegos", "mapas", "camara",
                 "correo", "calendario", "reloj", "clima", "noticias", "personas", "cine", "fotos", "grabadora"}


def _lnk_destino(ruta):
    """Lee el exe destino de un .lnk (parser minimo, sin COM). None si no se puede."""
    try:
        with open(ruta, "rb") as fh:
            d = fh.read(65536)
        if len(d) < 0x4C or d[:4] != b"L\0\0\0":
            return None
        flags = int.from_bytes(d[0x14:0x18], "little")
        off = 0x4C
        if flags & 1:
            off += 2 + int.from_bytes(d[off:off + 2], "little")
        if not flags & 2:
            return None
        li = off
        hdr = int.from_bytes(d[li + 4:li + 8], "little")
        lf = int.from_bytes(d[li + 8:li + 12], "little")
        if not lf & 1:
            return None
        if hdr >= 0x24:
            uo = int.from_bytes(d[li + 28:li + 32], "little")
            if uo:
                fin = d.find(b"\0\0", li + uo)
                fin += fin % 2 if (fin - (li + uo)) % 2 else 0
                return d[li + uo:fin].decode("utf-16-le", "ignore")
        bo = int.from_bytes(d[li + 16:li + 20], "little")
        fin = d.index(b"\0", li + bo)
        return d[li + bo:fin].decode("mbcs", "replace")
    except Exception:
        return None


def descubrir(ruta_cache=DESC_PATH, con_help=True):
    """Escanea Windows (lnk del Menu Inicio, App Paths, `help`) y guarda la cache. Devuelve el dict."""
    t0 = perf_counter()
    apps, vistos = [], set()
    bases = [os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
             os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs")]
    for b in bases:
        for raiz, _d, fs in os.walk(b):
            for f in fs:
                if f.lower().endswith(".lnk"):
                    p = os.path.join(raiz, f)
                    dest = _lnk_destino(p)
                    exe = os.path.basename(dest).lower() if dest and dest.lower().endswith(".exe") else ""
                    apps.append([f[:-4], f'start "" "{p}"', exe, "lnk"])
                    if exe:
                        vistos.add(exe)
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    k = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths", 0,
                                       winreg.KEY_READ | flag)
                except OSError:
                    continue
                with k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            n = winreg.EnumKey(k, i)
                        except OSError:
                            break
                        if not n.lower().endswith(".exe") or n.lower() in vistos:
                            continue
                        try:
                            with winreg.OpenKey(k, n) as sk:
                                ruta = winreg.QueryValueEx(sk, "")[0]
                        except OSError:
                            ruta = ""
                        ruta = os.path.expandvars((ruta or "").strip('"'))
                        vistos.add(n.lower())
                        apps.append([n[:-4], f'start "" "{ruta or n}"', n.lower(), "reg"])
    except ImportError:
        pass
    ayuda = []
    try:
        if not con_help:
            raise OSError("sin help")
        r = subprocess.run(["cmd", "/c", "help"], capture_output=True, timeout=10)
        txt = r.stdout.decode("oem", "replace")
        for ln in txt.splitlines():
            m = re.match(r"^([A-Z][A-Z0-9]+)\s{2,}(\S.*)$", ln)
            if m:
                ayuda.append([m.group(1).lower(), m.group(2).strip()])
            elif ayuda and ln.startswith("  ") and ln.strip():
                ayuda[-1][1] += " " + ln.strip()
    except Exception:
        pass
    datos = {"ver": 1, "ts": time.time(), "dur": round(perf_counter() - t0, 3), "apps": apps, "ayuda": ayuda}
    guardar_json(ruta_cache, datos)
    return datos


class DescubrimientoMixin:
    def _cargar_desc(self, auto, silencioso):
        d = None
        if os.path.exists(self.ruta_desc):
            try:
                with open(self.ruta_desc, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                d = None
        if d is None and auto:
            if not silencioso:
                print("  Descubriendo aplicaciones y comandos de Windows (solo la primera vez)...")
            d = descubrir(self.ruta_desc, getattr(self, "con_help", True))
            if not silencioso:
                print(f"  Listo en {d['dur']:.2f}s: {len(d['apps'])} apps, {len(d['ayuda'])} comandos de help.")
        self.desc = d or {"apps": [], "ayuda": [], "dur": 0}

    def redescubrir(self):
        self.desc = descubrir(self.ruta_desc, getattr(self, "con_help", True))
        self._cache_an.clear()
        self._indexar()
        return self.desc

    def _indexar_apps(self):
        self.app_keys, self.app_single = {}, []
        for k, (nombre, cmd, exe, _src) in enumerate(self.desc.get("apps", [])):
            if APP_MALOS.search(nombre):
                continue
            ws = [w for w in re.findall(r"[a-z0-9]+", sin_tildes(nombre.lower())) if w not in ("x86", "x64")]
            claves = set()
            if ws:
                claves.add(" ".join(ws))
                while len(ws) > 1 and ws[0] in APP_RUIDO:
                    ws = ws[1:]
                    claves.add(" ".join(ws))
            if exe:
                claves.add(exe[:-4].lower())
            for c in claves:
                if " " not in c and (len(c) < 3 or c in STOP or c in SIN or c in APP_GENERICOS or c in FOLDER_ALIAS
                                     or c.isdigit()):
                    continue
                prev = self.app_keys.get(c)
                if prev is None or (self.desc["apps"][prev][3] != "lnk" and _src == "lnk"):
                    self.app_keys[c] = k
        self.app_single = [c for c in self.app_keys if " " not in c and len(c) >= 6]
        self._appfix = {}
