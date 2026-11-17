"""Bloque 4: lectura de documentos (DOCX, XLSX, PPTX, ODT/ODS, PDF) sin dependencias y sin LLM.

Ideas de los repos docpack y document-intelligence-mcp (lectura por formato, troceo por titulos, resumen extractivo, preguntas sobre el
documento, tablas); implementacion propia con zipfile + xml.etree + zlib.

Lectores (registrados en conocimiento.LECTORES: `!indexar` los incluye; devuelven un `str` con `.tipo` = clasificacion del documento):
  DOCX  word/document.xml; titulos por w:pStyle resolviendo styles.xml (outlineLvl, basedOn, nombres "heading N"/"Titulo N"), tablas w:tbl,
        metadatos de docProps/core.xml.
  XLSX  xl/sharedStrings.xml + hojas (t="s", inlineStr, numeros); nombres desde workbook.xml + rels; la cabecera salta las filas de titulo
        de una sola celda.
  PPTX  diapositivas en el orden de presentation.xml (+ rels), texto a:t.
  ODT/ODS  content.xml (text:h con outline-level, tablas, celdas repetidas acotadas), meta.xml.
  PDF   "mejor esfuerzo": objetos y streams (FlateDecode/ASCII85/ASCIIHex), arbol /Pages para el orden, operadores Tj TJ ' " Td Tm T*,
        /Info. Sin texto legible (escaneado, CID, cifrado) avisa claramente. Si pypdf esta instalado se usa opcionalmente.

Seguridad: ZIP bombs (tope de entradas, de tamano descomprimido total y por miembro, lectura por bloques con cuenta real), XML sin
entidades (se rechaza todo DOCTYPE/ENTITY antes de parsear), celdas/filas repetidas acotadas, streams PDF con tope de salida. Los errores
salen como DocError con un mensaje legible. Las rutas se resuelven con la validacion existente y solo en LECTURA.

Herramientas: @leer @seccion @preguntar_doc @entidades @tabla (al final del modulo).
"""
import base64, difflib, io, math, os, posixpath, re, time, zipfile, zlib
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from .conocimiento import LECTORES, RELLENO, RE_TITULO, RE_TOK, _casa, dividir_frases, raiz, registrar_lector
from .herramientas import Resultado, herramienta, validar_ruta
from .texto import STOP, sin_tildes

MAX_ENTRADAS = 2000                       # entradas de un zip
MAX_DESCOMP_TOTAL = 64 * 1024 * 1024      # bytes descomprimidos de todo el zip
MAX_MIEMBRO = 32 * 1024 * 1024            # bytes descomprimidos de un miembro
MAX_TEXTO = 3_000_000                     # caracteres de texto indexable por documento
MAX_FILAS = 100_000
MAX_CELDAS = 1_000_000
MAX_REPETIR = 64                          # celdas/filas repetidas de ODS
MAX_LEER = 50 * 1024 * 1024               # tamano maximo de un archivo para @leer
MAX_STREAM_PDF = 16 * 1024 * 1024
EXT_DOC = (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods", ".pdf")
PYPDF = False
try:
    import importlib.util as _iu
    PYPDF = _iu.find_spec("pypdf") is not None        # opcional: nunca se exige
except Exception:
    PYPDF = False


class DocError(Exception):
    """Documento ilegible, danado o rechazado por seguridad (mensaje legible para el usuario)."""


# ---------------------------------------------------------------- modelo
@dataclass
class Seccion:
    titulo: str
    nivel: int = 1
    partes: list = field(default_factory=list)

    @property
    def texto(self):
        return "\n".join(self.partes)

    def palabras(self):
        return len(self.texto.split())


@dataclass
class Tabla:
    nombre: str
    cabecera: list
    filas: list


@dataclass
class Doc:
    formato: str
    nombre: str = ""
    meta: dict = field(default_factory=dict)
    secciones: list = field(default_factory=list)
    tablas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    ruta: str = ""
    tamano: int = 0
    tipo: str = "otro"

    def texto(self):
        out = []
        for s in self.secciones:
            if s.titulo:
                out.append(s.titulo)
            if s.texto:
                out.append(s.texto)
        return "\n".join(out)

    def a_texto_indexable(self):
        """Texto con titulos '#' para que el troceo de conocimiento corte por secciones (diapositiva, hoja, pagina, titulo)."""
        partes = []
        m = [f"{k}: {self.meta[c]}" for k, c in (("Titulo", "titulo"), ("Autor", "autor"), ("Asunto", "asunto")) if self.meta.get(c)]
        if m:
            partes.append(". ".join(m) + ".")
        for s in self.secciones:
            if s.titulo:
                partes.append("#" * min(max(s.nivel, 1), 6) + " " + s.titulo.replace("\n", " "))
            if s.texto:
                partes.append(s.texto)
        return "\n\n".join(partes)[:MAX_TEXTO]


class TextoDoc(str):
    """Texto de un documento para el indice; `tipo` lo guarda conocimiento en doctipo (filtro `tipo:factura`)."""
    tipo = None
    avisos = ()


# ---------------------------------------------------------------- zip y xml seguros
class _Zip:
    def __init__(self, datos):
        try:
            self.z = zipfile.ZipFile(io.BytesIO(datos))
        except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError) as e:
            raise DocError("no es un archivo ZIP/Office valido (o esta danado)") from e
        infos = self.z.infolist()
        if len(infos) > MAX_ENTRADAS:
            raise DocError(f"zip con demasiadas entradas ({len(infos)} > {MAX_ENTRADAS}): rechazado")
        tot = sum(i.file_size for i in infos)
        if tot > MAX_DESCOMP_TOTAL:
            raise DocError(f"zip bomb: {tot // 2 ** 20} MB descomprimidos superan el tope de {MAX_DESCOMP_TOTAL // 2 ** 20} MB de tamano descomprimido")
        self.nombres = {i.filename: i for i in infos}
        self.restante = MAX_DESCOMP_TOTAL

    def existe(self, n):
        return n in self.nombres

    def leer(self, nombre, tope=MAX_MIEMBRO):
        """bytes del miembro o None si no existe. La cuenta de bytes es la REAL (no la que declara la cabecera)."""
        info = self.nombres.get(nombre)
        if info is None:
            return None
        if info.file_size > tope:
            raise DocError(f"{nombre}: {info.file_size // 2 ** 20} MB descomprimidos superan el tope de tamano descomprimido ({tope // 2 ** 20} MB)")
        total, partes = 0, []
        try:
            with self.z.open(info) as f:
                while True:
                    b = f.read(65536)
                    if not b:
                        break
                    total += len(b)
                    self.restante -= len(b)
                    if total > tope or self.restante < 0:
                        raise DocError(f"{nombre}: supera el tope de tamano descomprimido")
                    partes.append(b)
        except DocError:
            raise
        except (RuntimeError, zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError) as e:
            raise DocError(f"no se puede leer {nombre} ({type(e).__name__}: cifrado o danado)") from e
        return b"".join(partes)

    def cerrar(self):
        self.z.close()


_RE_PELIGRO_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.I)


def _xml(datos, nombre=""):
    """Parsea XML rechazando TODO DOCTYPE/ENTITY (sin entidades externas ni expansion) y UTF-16/NUL (que esconderian la marca)."""
    if datos is None:
        raise DocError(f"falta {nombre}")
    if b"\x00" in datos[:64] or datos[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise DocError(f"{nombre}: XML en UTF-16/32 no soportado")
    if _RE_PELIGRO_XML.search(datos):
        raise DocError(f"{nombre}: XML con DOCTYPE/ENTITY rechazado (posible ataque de entidades)")
    try:
        return ET.fromstring(datos)
    except ET.ParseError as e:
        raise DocError(f"XML invalido en {nombre}: {e}") from e


def _t(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _ns(uri):
    return "{" + uri + "}"


W = _ns("http://schemas.openxmlformats.org/wordprocessingml/2006/main")
SS = _ns("http://schemas.openxmlformats.org/spreadsheetml/2006/main")
R_ID = _ns("http://schemas.openxmlformats.org/officeDocument/2006/relationships") + "id"
A = _ns("http://schemas.openxmlformats.org/drawingml/2006/main")
P = _ns("http://schemas.openxmlformats.org/presentationml/2006/main")
TEXT = _ns("urn:oasis:names:tc:opendocument:xmlns:text:1.0")
TABLE = _ns("urn:oasis:names:tc:opendocument:xmlns:table:1.0")
OFFICE = _ns("urn:oasis:names:tc:opendocument:xmlns:office:1.0")


def _rels(z, ruta):
    d = z.leer(ruta)
    if d is None:
        return {}
    return {e.get("Id"): e.get("Target") for e in _xml(d, ruta) if _t(e) == "Relationship"}


def _ruta_rel(base_dir, target):
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(base_dir, target))


def _meta_core(z):
    d = z.leer("docProps/core.xml")
    if d is None:
        return {}
    out = {}
    for e in _xml(d, "core.xml"):
        k = {"title": "titulo", "creator": "autor", "created": "fecha", "subject": "asunto", "lastModifiedBy": "modificado_por"}.get(_t(e))
        if k and (e.text or "").strip():
            out[k] = e.text.strip()
    return out


# ---------------------------------------------------------------- DOCX
_RE_HEAD = re.compile(r"^(?:heading|titulo|ttulo|encabezado)(\d)$")


def _estilos_docx(z):
    d = z.leer("word/styles.xml")
    if d is None:
        return {}
    est = {}
    for st in _xml(d, "styles.xml").iter(W + "style"):
        sid = st.get(W + "styleId")
        nm = st.find(W + "name")
        bs = st.find(W + "basedOn")
        lvl = None
        ppr = st.find(W + "pPr")
        if ppr is not None and ppr.find(W + "outlineLvl") is not None:
            try:
                lvl = int(ppr.find(W + "outlineLvl").get(W + "val"))
            except (TypeError, ValueError):
                lvl = None
        est[sid] = (nm.get(W + "val") if nm is not None else "", bs.get(W + "val") if bs is not None else None, lvl)
    return est


def _nivel_estilo(est, sid, prof=0):
    """Nivel de titulo (1..9) de un estilo: outlineLvl, nombre 'heading N' / 'Titulo N' / 'Title', o el del estilo base. None = texto normal."""
    if sid is None or prof > 10:
        return None
    nombre, base, lvl = est.get(sid, ("", None, None))
    if lvl is not None:
        return lvl + 1 if lvl < 9 else None
    for c in (nombre, sid):
        k = re.sub(r"[\s_-]+", "", sin_tildes(c or "").lower())
        m = _RE_HEAD.match(k)
        if m:
            return max(1, min(int(m.group(1)), 9))
        if k in ("title", "titulo", "ttulo"):
            return 1
    return _nivel_estilo(est, base, prof + 1) if base else None


def _texto_parrafo(p):
    out = []
    for el in p.iter():
        t = _t(el)
        if t == "t":
            out.append(el.text or "")
        elif t == "tab":
            out.append("\t")
        elif t in ("br", "cr"):
            out.append("\n")
        elif t == "noBreakHyphen":
            out.append("-")
    return "".join(out)


def _bloques_docx(el, prof=0):
    for ch in el:
        t = _t(ch)
        if t in ("p", "tbl"):
            yield t, ch
        elif t in ("sdt", "sdtContent", "ins", "smartTag", "customXml", "moveTo") and prof < 12:
            yield from _bloques_docx(ch, prof + 1)


def _filas_tabla_docx(tbl):
    filas = []
    for tr in tbl.findall(W + "tr"):
        fila = []
        for tc in tr.findall(W + "tc"):
            fila.append(" ".join(x for x in (_texto_parrafo(p).strip() for p in tc.iter(W + "p")) if x))
        if any(fila):
            filas.append(fila)
        if len(filas) >= MAX_FILAS:
            break
    return filas


def leer_docx(datos, nombre=""):
    z = _Zip(datos)
    d = z.leer("word/document.xml")
    if d is None:
        raise DocError("no es un DOCX valido: falta word/document.xml")
    est = _estilos_docx(z)
    root = _xml(d, "document.xml")
    body = root.find(W + "body")
    if body is None:
        raise DocError("DOCX sin cuerpo (word/body)")
    doc = Doc("DOCX", nombre, _meta_core(z))
    cur = Seccion("", 0)
    secs = [cur]
    ntab = 0
    for kind, el in _bloques_docx(body):
        if kind == "p":
            txt = _texto_parrafo(el).strip()
            if not txt:
                continue
            ppr = el.find(W + "pPr")
            sid = ppr.find(W + "pStyle").get(W + "val") if ppr is not None and ppr.find(W + "pStyle") is not None else None
            lvl = _nivel_estilo(est, sid)
            if sid and not est:                                   # sin styles.xml: "Heading1" por el id
                m = _RE_HEAD.match(re.sub(r"[\s_-]+", "", sin_tildes(sid).lower()))
                lvl = int(m.group(1)) if m else lvl
            if ppr is not None and ppr.find(W + "outlineLvl") is not None:
                try:
                    o = int(ppr.find(W + "outlineLvl").get(W + "val"))
                    lvl = o + 1 if o < 9 else None
                except (TypeError, ValueError):
                    pass
            if lvl and len(txt) <= 200:
                cur = Seccion(txt.replace("\n", " "), lvl)
                secs.append(cur)
            else:
                cur.partes.append(txt)
        else:
            filas = _filas_tabla_docx(el)
            if filas:
                ntab += 1
                doc.tablas.append(Tabla(f"Tabla {ntab}" + (f" ({cur.titulo})" if cur.titulo else ""), filas[0], filas[1:]))
                cur.partes.extend(" | ".join(f) for f in filas)
    z.cerrar()
    doc.secciones = [s for s in secs if s.titulo or s.partes]
    return doc


# ---------------------------------------------------------------- XLSX
def _col_idx(ref):
    n = 0
    for c in ref:
        if "A" <= c <= "Z":
            n = n * 26 + ord(c) - 64
        else:
            break
    return min(max(n - 1, 0), 16383)


def _shared_strings(z):
    d = z.leer("xl/sharedStrings.xml")
    if d is None:
        return []
    out = []
    for si in _xml(d, "sharedStrings.xml").iter(SS + "si"):
        partes = []
        for ch in si:
            t = _t(ch)
            if t == "t":
                partes.append(ch.text or "")
            elif t == "r":
                partes.extend((x.text or "") for x in ch if _t(x) == "t")
        out.append("".join(partes))
        if len(out) >= MAX_CELDAS:
            break
    return out


def _hojas_xlsx(z):
    d = z.leer("xl/workbook.xml")
    if d is not None:
        rels = _rels(z, "xl/_rels/workbook.xml.rels")
        hojas = []
        for sh in _xml(d, "workbook.xml").iter(SS + "sheet"):
            tgt = rels.get(sh.get(R_ID))
            if tgt:
                ruta = _ruta_rel("xl", tgt)
                if z.existe(ruta):
                    hojas.append((sh.get("name") or f"Hoja {len(hojas) + 1}", ruta))
        if hojas:
            return hojas
    sueltas = sorted((n for n in z.nombres if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    return [(f"Hoja {i}", n) for i, n in enumerate(sueltas, 1)]


def _num(txt):
    try:
        v = float(txt)
    except (TypeError, ValueError):
        return txt
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def _filas_hoja(datos, ss, nombre):
    root = _xml(datos, nombre)
    sd = root.find(SS + "sheetData")
    filas, celdas = [], 0
    if sd is None:
        return filas
    for row in sd.iter(SS + "row"):
        vals, sig = {}, 0
        for c in row.findall(SS + "c"):
            ref = c.get("r")
            col = _col_idx(ref) if ref else sig
            sig = col + 1
            t = c.get("t")
            v = c.find(SS + "v")
            if t == "s":
                try:
                    val = ss[int(v.text)] if v is not None else None
                except (ValueError, IndexError, TypeError):
                    val = None
            elif t == "inlineStr":
                is_ = c.find(SS + "is")
                val = "".join((x.text or "") for x in is_.iter(SS + "t")) if is_ is not None else None
            elif t == "str":
                val = v.text if v is not None else None
            elif t == "b":
                val = "VERDADERO" if v is not None and v.text == "1" else "FALSO"
            elif t == "e":
                val = None
            else:
                val = _num(v.text) if v is not None and v.text is not None else None
            if val not in (None, ""):
                vals[col] = val
            celdas += 1
        if vals:
            ancho = min(max(vals) + 1, 200)
            filas.append([vals.get(i) for i in range(ancho)])
        if len(filas) >= MAX_FILAS or celdas >= MAX_CELDAS:
            break
    return filas


def _fmt_celda(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v).strip()


def _cabecera(filas):
    """Indice de la fila de cabecera: la primera con >= 2 celdas y mayoria de texto (salta las filas de titulo de una sola celda)."""
    if not filas:
        return None
    if max(sum(1 for x in f if x not in (None, "")) for f in filas) <= 1:
        return 0
    for i, f in enumerate(filas[:30]):
        ne = [x for x in f if x not in (None, "")]
        if len(ne) >= 2 and sum(1 for x in ne if isinstance(x, str) and parsear_numero(x) is None) * 2 >= len(ne):
            return i
    for i, f in enumerate(filas[:30]):
        if sum(1 for x in f if x not in (None, "")) >= 2:
            return i
    return 0


def _tabla_de_filas(nombre, filas):
    h = _cabecera(filas)
    if h is None:
        return None
    cab = [(_fmt_celda(x) or f"Col {j + 1}") for j, x in enumerate(filas[h])]
    cuerpo = [list(f) + [None] * (len(cab) - len(f)) for f in filas[h + 1:]]
    cuerpo = [f for f in cuerpo if any(x not in (None, "") for x in f)]
    return Tabla(nombre, cab, cuerpo)


def _seccion_tabla(titulo, tabla, previas):
    s = Seccion(titulo, 1, list(previas))
    for f in tabla.filas[:5000]:
        s.partes.append(" | ".join(f"{c}: {_fmt_celda(v)}" for c, v in zip(tabla.cabecera, f) if v not in (None, "")))
    if len(tabla.filas) > 5000:
        s.partes.append(f"(... {len(tabla.filas) - 5000} filas mas)")
    return s


def leer_xlsx(datos, nombre=""):
    z = _Zip(datos)
    doc = Doc("XLSX", nombre, _meta_core(z))
    ss = _shared_strings(z)
    hojas = _hojas_xlsx(z)
    if not hojas:
        raise DocError("el libro no contiene hojas legibles")
    for hn, ruta in hojas:
        filas = _filas_hoja(z.leer(ruta), ss, ruta)
        t = _tabla_de_filas(hn, filas)
        if t is None:
            doc.secciones.append(Seccion(f"Hoja: {hn}", 1, ["(hoja vacia)"]))
            continue
        h = _cabecera(filas)
        previas = [" ".join(_fmt_celda(x) for x in f if x not in (None, "")) for f in filas[:h]]
        doc.tablas.append(t)
        doc.secciones.append(_seccion_tabla(f"Hoja: {hn}", t, previas))
    z.cerrar()
    return doc


# ---------------------------------------------------------------- PPTX
def leer_pptx(datos, nombre=""):
    z = _Zip(datos)
    doc = Doc("PPTX", nombre, _meta_core(z))
    rutas = []
    d = z.leer("ppt/presentation.xml")
    if d is not None:
        rels = _rels(z, "ppt/_rels/presentation.xml.rels")
        for e in _xml(d, "presentation.xml").iter(P + "sldId"):
            tgt = rels.get(e.get(R_ID))
            if tgt and z.existe(_ruta_rel("ppt", tgt)):
                rutas.append(_ruta_rel("ppt", tgt))
    if not rutas:
        rutas = sorted((n for n in z.nombres if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    if not rutas:
        raise DocError("la presentacion no contiene diapositivas legibles")
    for i, ruta in enumerate(rutas, 1):
        root = _xml(z.leer(ruta), ruta)
        titulo, cuerpo = "", []
        for sp in root.iter(P + "sp"):
            tx = sp.find(P + "txBody")
            if tx is None:
                continue
            ph = next(iter(sp.iter(P + "ph")), None)
            es_titulo = ph is not None and ph.get("type") in ("title", "ctrTitle")
            lineas = [("".join((x.text or "") for x in p.iter(A + "t"))).strip() for p in tx.findall(A + "p")]
            lineas = [x for x in lineas if x]
            if es_titulo and not titulo:
                titulo = " ".join(lineas)
            else:
                cuerpo.extend(lineas)
        for tbl in root.iter(A + "tbl"):
            filas = []
            for tr in tbl.findall(A + "tr"):
                filas.append([(" ".join(("".join((x.text or "") for x in p.iter(A + "t"))) for p in tc.iter(A + "p"))).strip() for tc in tr.findall(A + "tc")])
            filas = [f for f in filas if any(f)]
            if filas:
                doc.tablas.append(Tabla(f"Diapositiva {i}", filas[0], filas[1:]))
                cuerpo.extend(" | ".join(f) for f in filas)
        doc.secciones.append(Seccion(f"Diapositiva {i}" + (f": {titulo}" if titulo else ""), 1, cuerpo))
    z.cerrar()
    return doc


# ---------------------------------------------------------------- ODT / ODS
def _odf_texto(el, out, prof=0):
    out.append(el.text or "")
    for ch in el:
        t = _t(ch)
        if t == "s":
            try:
                out.append(" " * min(int(ch.get(TEXT + "c") or 1), 100))
            except ValueError:
                out.append(" ")
        elif t == "tab":
            out.append("\t")
        elif t == "line-break":
            out.append("\n")
        elif prof < 30:
            _odf_texto(ch, out, prof + 1)
        out.append(ch.tail or "")


def _odf_str(el):
    out = []
    _odf_texto(el, out)
    return "".join(out)


def _odf_celda(c):
    vt = c.get(OFFICE + "value-type")
    if vt in ("float", "percentage", "currency"):
        return _num(c.get(OFFICE + "value"))
    if vt == "date":
        return c.get(OFFICE + "date-value")
    if vt == "boolean":
        return "VERDADERO" if c.get(OFFICE + "boolean-value") == "true" else "FALSO"
    txt = "\n".join(_odf_str(p) for p in c.findall(TEXT + "p")).strip()
    return txt or None


def _filas_odf(tabla):
    filas = []
    for tr in tabla.iter(TABLE + "table-row"):
        celdas = []
        for c in tr:
            if _t(c) not in ("table-cell", "covered-table-cell"):
                continue
            try:
                rep = max(1, int(c.get(TABLE + "number-columns-repeated") or 1))
            except ValueError:
                rep = 1
            v = _odf_celda(c) if _t(c) == "table-cell" else None
            celdas.extend([v] * min(rep, MAX_REPETIR if v is not None else 16))
            if len(celdas) > 1000:
                break
        while celdas and celdas[-1] in (None, ""):
            celdas.pop()
        if celdas:
            try:
                rr = max(1, int(tr.get(TABLE + "number-rows-repeated") or 1))
            except ValueError:
                rr = 1
            filas.extend([celdas] * min(rr, MAX_REPETIR))
        if len(filas) >= MAX_FILAS:
            break
    return filas


def leer_odf(datos, nombre="", ext=".odt"):
    z = _Zip(datos)
    d = z.leer("content.xml")
    if d is None:
        raise DocError("no es un documento ODF valido: falta content.xml")
    root = _xml(d, "content.xml")
    meta = {}
    dm = z.leer("meta.xml")
    if dm is not None:
        for e in _xml(dm, "meta.xml").iter():
            k = {"title": "titulo", "creator": "autor", "initial-creator": "autor", "creation-date": "fecha", "subject": "asunto"}.get(_t(e))
            if k and (e.text or "").strip() and k not in meta:
                meta[k] = e.text.strip()
    doc = Doc("ODS" if ext == ".ods" else "ODT", nombre, meta)
    body = root.find(OFFICE + "body")
    if body is None:
        raise DocError("ODF sin cuerpo")
    if ext == ".ods":
        for tb in body.iter(TABLE + "table"):
            hn = tb.get(TABLE + "name") or f"Hoja {len(doc.tablas) + 1}"
            filas = _filas_odf(tb)
            t = _tabla_de_filas(hn, filas)
            if t is None:
                doc.secciones.append(Seccion(f"Hoja: {hn}", 1, ["(hoja vacia)"]))
                continue
            h = _cabecera(filas)
            doc.tablas.append(t)
            doc.secciones.append(_seccion_tabla(f"Hoja: {hn}", t, [" ".join(_fmt_celda(x) for x in f if x not in (None, "")) for f in filas[:h]]))
        z.cerrar()
        if not doc.secciones:
            raise DocError("la hoja de calculo no contiene tablas legibles")
        return doc
    txt = body.find(OFFICE + "text")
    cur = Seccion("", 0)
    secs = [cur]
    ntab = 0

    def recorrer(el, prof=0):
        nonlocal cur, ntab
        for ch in el:
            t = _t(ch)
            if t == "h":
                titulo = _odf_str(ch).strip()
                if titulo:
                    try:
                        lvl = int(ch.get(TEXT + "outline-level") or 1)
                    except ValueError:
                        lvl = 1
                    cur = Seccion(titulo.replace("\n", " "), max(1, min(lvl, 9)))
                    secs.append(cur)
            elif t == "p":
                s = _odf_str(ch).strip()
                if s:
                    cur.partes.append(s)
            elif t == "list":
                for p in ch.iter(TEXT + "p"):
                    s = _odf_str(p).strip()
                    if s:
                        cur.partes.append("- " + s)
            elif t == "table":
                filas = [[str(x) if x is not None else "" for x in f] for f in _filas_odf(ch)]
                if filas:
                    ntab += 1
                    doc.tablas.append(Tabla(ch.get(TABLE + "name") or f"Tabla {ntab}", filas[0], filas[1:]))
                    cur.partes.extend(" | ".join(f) for f in filas)
            elif prof < 12:
                recorrer(ch, prof + 1)
    recorrer(txt if txt is not None else body)
    z.cerrar()
    doc.secciones = [s for s in secs if s.titulo or s.partes]
    return doc


# ---------------------------------------------------------------- PDF (mejor esfuerzo)
_RE_OBJ = re.compile(rb"(?<![\d.])(\d{1,7})\s+(\d{1,5})\s+obj\b")
_RE_FILTRO = re.compile(rb"/Filter\s*(\[[^\]]*\]|/\w+)")
_RE_LEN = re.compile(rb"/Length\s+(\d+)(?!\s+\d+\s+R)")


def _decodificar_stream(dic, raw, presupuesto):
    """bytes del stream decodificado, o None si es una imagen / filtro no soportado / corrupto. presupuesto = [bytes restantes]."""
    m = _RE_FILTRO.search(dic)
    filtros = re.findall(rb"/(\w+)", m.group(1)) if m else []
    data = raw
    for f in filtros:
        if f in (b"FlateDecode", b"Fl"):
            d = zlib.decompressobj()
            try:
                data = d.decompress(data, MAX_STREAM_PDF)
            except zlib.error:
                try:
                    d = zlib.decompressobj(-15)
                    data = d.decompress(data[2:], MAX_STREAM_PDF)
                except zlib.error:
                    return None
            if d.unconsumed_tail:
                raise DocError("PDF con un stream que supera el tope de tamano descomprimido")
        elif f in (b"ASCII85Decode", b"A85"):
            try:
                data = base64.a85decode(data.strip(), adobe=data.strip().startswith(b"<~"))
            except (ValueError, TypeError):
                return None
        elif f in (b"ASCIIHexDecode", b"AHx"):
            try:
                data = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0]).decode() + "0" * (len(re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])) % 2))
            except ValueError:
                return None
        else:
            return None                                   # DCT/JPX/CCITT (imagenes), LZW, etc.
    presupuesto[0] -= len(data)
    if presupuesto[0] < 0:
        raise DocError("PDF con tamano descomprimido total excesivo (posible bomba)")
    return data


def _objetos_pdf(datos):
    """{num: (dict_bytes, stream_decodificado|None, es_imagen)} (incluye objetos dentro de ObjStm)."""
    objs, pos, n, presupuesto = {}, 0, len(datos), [MAX_DESCOMP_TOTAL]
    pend_objstm = []
    while n > pos and len(objs) < 200_000:
        m = _RE_OBJ.search(datos, pos)
        if not m:
            break
        num, ini = int(m.group(1)), m.end()
        e = datos.find(b"endobj", ini)
        k = datos.find(b"stream", ini)
        if k != -1 and (e == -1 or k < e):
            dic = datos[ini:k]
            a = k + 6
            if datos[a:a + 2] == b"\r\n":
                a += 2
            elif datos[a:a + 1] in (b"\n", b"\r"):
                a += 1
            ml = _RE_LEN.search(dic)
            fin = None
            if ml:
                cand = a + int(ml.group(1))
                if datos[cand:cand + 20].lstrip(b"\r\n \t").startswith(b"endstream"):
                    fin = cand
            if fin is None:
                j = datos.find(b"endstream", a)
                fin = j if j != -1 else n
                if datos[fin - 2:fin] == b"\r\n":
                    fin -= 2
                elif datos[fin - 1:fin] in (b"\n", b"\r"):
                    fin -= 1
            raw = datos[a:fin]
            img = bool(re.search(rb"/Subtype\s*/Image", dic))
            st = None if img else _decodificar_stream(dic, raw, presupuesto)
            objs[num] = (dic, st, img)
            if re.search(rb"/Type\s*/ObjStm", dic) and st is not None:
                pend_objstm.append((dic, st))
            pos = fin
        else:
            objs[num] = (datos[ini:e if e != -1 else n], None, False)
            pos = e if e != -1 else n
    for dic, st in pend_objstm:                                       # PDF 1.5: objetos dentro de un ObjStm
        try:
            cnt = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            nums = [int(x) for x in re.findall(rb"\d+", st[:first])[:2 * cnt]]
            pares = list(zip(nums[0::2], nums[1::2]))
            for i, (onum, off) in enumerate(pares):
                fin = pares[i + 1][1] if i + 1 < len(pares) else len(st) - first
                objs.setdefault(onum, (st[first + off:first + fin], None, False))
        except (AttributeError, ValueError, IndexError):
            pass
    return objs


def _pdf_literal(b):
    """Cadena literal PDF (sin los parentesis externos) -> bytes (escapes y octales)."""
    out, i, n = bytearray(), 0, len(b)
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while i < n:
        c = b[i]
        if c == 92 and i + 1 < n:
            d = b[i + 1]
            if d in esc:
                out.append(esc[d])
                i += 2
            elif 48 <= d <= 55:
                j, v = i + 1, 0
                while j < n and j < i + 4 and 48 <= b[j] <= 55:
                    v = v * 8 + b[j] - 48
                    j += 1
                out.append(v & 255)
                i = j
            elif d in (10, 13):
                i += 2 + (1 if d == 13 and i + 2 < n and b[i + 2] == 10 else 0)
            else:
                out.append(d)
                i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


def _tokens_pdf(b):
    """Tokens de un content stream: ('s', bytes) cadenas, ('n', float), ('[',), (']',), ('op', bytes), ('name', bytes)."""
    i, n = 0, len(b)
    ws = b" \t\r\n\x00\x0c"
    delim = b"()<>[]{}/%"
    while i < n:
        c = b[i]
        if c in ws:
            i += 1
        elif c == 0x25:                                              # % comentario
            while i < n and b[i] not in b"\r\n":
                i += 1
        elif c == 0x28:                                              # ( cadena literal con parentesis balanceados
            nivel, j = 1, i + 1
            while j < n and nivel:
                d = b[j]
                if d == 92:
                    j += 2
                    continue
                nivel += (d == 0x28) - (d == 0x29)
                j += 1
            yield ("s", _pdf_literal(b[i + 1:j - 1]))
            i = j
        elif c == 0x3C:
            if b[i + 1:i + 2] == b"<":
                i += 2
            else:
                j = b.find(b">", i)
                j = n if j == -1 else j
                h = re.sub(rb"[^0-9A-Fa-f]", b"", b[i + 1:j])
                if len(h) % 2:
                    h += b"0"
                yield ("s", bytes.fromhex(h.decode()))
                i = j + 1
        elif c == 0x3E:
            i += 1
        elif c == 0x5B:
            yield ("[",)
            i += 1
        elif c == 0x5D:
            yield ("]",)
            i += 1
        elif c == 0x2F:
            j = i + 1
            while j < n and b[j] not in ws and b[j] not in delim:
                j += 1
            yield ("name", b[i + 1:j])
            i = j
        elif c in b"{}":
            i += 1
        else:
            j = i
            while j < n and b[j] not in ws and b[j] not in delim:
                j += 1
            w = b[i:j]
            if re.fullmatch(rb"[+-]?(?:\d+\.?\d*|\.\d+)", w):
                yield ("n", float(w))
            else:
                if w == b"BI":                                       # imagen en linea: se salta hasta EI
                    k = re.compile(rb"\sEI(?=\s|$)").search(b, j)
                    j = k.end() if k else n
                else:
                    yield ("op", w)
            i = max(j, i + 1)


def _decod_cadena(bs, cid):
    if bs[:2] == b"\xfe\xff":
        return bs[2:].decode("utf-16-be", "replace")
    if cid:
        return ""
    if len(bs) >= 2 and len(bs) % 2 == 0 and bs[0::2].count(0) * 2 >= len(bs):         # <00480065...>: UTF-16BE sin BOM
        return bs.decode("utf-16-be", "replace")
    return bs.decode("cp1252", "replace")


def _texto_stream(data, fuentes_cid):
    """Texto de un content stream (Tj TJ ' " Td TD Tm T*). Devuelve (texto, n_operadores_de_texto)."""
    out, pila, arr, y_ult, fuente, nops = [], [], None, None, None, 0

    def nl():
        if out and not out[-1].endswith("\n"):
            out.append("\n")

    def sp():
        if out and not out[-1].endswith((" ", "\n")):
            out.append(" ")
    for tk in _tokens_pdf(data):
        k = tk[0]
        if k == "[":
            arr = []
        elif k == "]":
            if arr is not None:
                pila.append(("arr", arr))
            arr = None
        elif k in ("s", "n", "name"):
            (arr if arr is not None else pila).append(tk)
        else:
            op = tk[1]
            cid = fuente in fuentes_cid
            if op in (b"Tj", b"'", b'"'):
                if op != b"Tj":
                    nl()
                s = next((x[1] for x in reversed(pila) if x[0] == "s"), None)
                if s is not None:
                    out.append(_decod_cadena(s, cid))
                nops += 1
            elif op == b"TJ":
                a = next((x[1] for x in reversed(pila) if x[0] == "arr"), [])
                for x in a:
                    if x[0] == "s":
                        out.append(_decod_cadena(x[1], cid))
                    elif x[0] == "n" and x[1] < -200:
                        sp()
                nops += 1
            elif op in (b"Td", b"TD"):
                nums = [x[1] for x in pila if x[0] == "n"][-2:]
                if len(nums) == 2:
                    if abs(nums[1]) > 0:
                        nl()
                    elif nums[0] > 0:
                        sp()
            elif op == b"Tm":
                nums = [x[1] for x in pila if x[0] == "n"][-6:]
                if len(nums) == 6:
                    if y_ult is not None and abs(nums[5] - y_ult) > 1:
                        nl()
                    elif y_ult is not None:
                        sp()
                    y_ult = nums[5]
            elif op == b"T*":
                nl()
            elif op == b"Tf":
                nm = [x[1] for x in pila if x[0] == "name"]
                fuente = nm[-1] if nm else None
            elif op == b"ET":
                nl()
            pila = []
    return "".join(out), nops


def _legible(txt):
    t = [c for c in txt if not c.isspace()]
    if not t:
        return False
    ctrl = sum(1 for c in t if ord(c) < 32 or c == "�")
    letras = sum(1 for c in t if c.isalpha())
    return ctrl * 20 <= len(t) and letras / len(t) >= 0.55 and re.search(r"[^\W\d_]{3,}", txt) is not None


def _fecha_pdf(s):
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?", s or "")
    return "-".join(x for x in m.groups() if x) if m else (s or "")


def _meta_pdf(objs, datos):
    m = list(re.finditer(rb"/Info\s+(\d+)\s+\d+\s+R", datos))
    if not m or int(m[-1].group(1)) not in objs:
        return {}
    dic = objs[int(m[-1].group(1))][0]
    meta = {}
    for clave, k in ((b"Title", "titulo"), (b"Author", "autor"), (b"Subject", "asunto"), (b"Creator", "creador"), (b"CreationDate", "fecha")):
        mm = re.search(rb"/" + clave + rb"\s*(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>)", dic)
        if mm:
            v = mm.group(1)
            bs = _pdf_literal(v[1:-1]) if v[:1] == b"(" else bytes.fromhex(re.sub(rb"\s", b"", v[1:-1]).decode() + ("0" if len(re.sub(rb"\s", b"", v[1:-1])) % 2 else ""))
            s = (bs[2:].decode("utf-16-be", "replace") if bs[:2] == b"\xfe\xff" else bs.decode("cp1252", "replace")).strip()
            if s:
                meta[k] = _fecha_pdf(s) if k == "fecha" else s
    return meta


def _orden_paginas(objs):
    """Numeros de objeto de las paginas en el orden del arbol /Pages (o por numero de objeto si el arbol no se puede leer)."""
    orden, vistos = [], set()

    def rec(num, prof):
        if prof > 40 or num in vistos or len(orden) > 5000 or num not in objs:
            return
        vistos.add(num)
        dic = objs[num][0]
        if re.search(rb"/Type\s*/Pages\b", dic) or (b"/Kids" in dic and not re.search(rb"/Type\s*/Page\b", dic)):
            mk = re.search(rb"/Kids\s*\[(.*?)\]", dic, re.S)
            for r in re.findall(rb"(\d+)\s+\d+\s+R", mk.group(1)) if mk else []:
                rec(int(r), prof + 1)
        else:
            orden.append(num)
    for num, (dic, _s, _i) in objs.items():
        if re.search(rb"/Type\s*/Catalog\b", dic):
            mp = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", dic)
            if mp:
                rec(int(mp.group(1)), 0)
            break
    if not orden:
        orden = sorted(n for n, (dic, _s, _i) in objs.items() if re.search(rb"/Type\s*/Page\b", dic))
    return orden


def _pdf_con_pypdf(datos):
    import pypdf                                                      # opcional
    r = pypdf.PdfReader(io.BytesIO(datos))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            return None
    paginas = [(p.extract_text() or "") for p in list(r.pages)[:2000]]
    meta = {}
    try:
        md = r.metadata or {}
        for k, c in (("/Title", "titulo"), ("/Author", "autor"), ("/Subject", "asunto")):
            if md.get(k):
                meta[c] = str(md.get(k))
    except Exception:
        pass
    return paginas, meta


def leer_pdf(datos, nombre="", usar_pypdf=True):
    doc = Doc("PDF", nombre)
    if not datos.lstrip()[:5] == b"%PDF-" and b"%PDF-" not in datos[:1024]:
        raise DocError("no es un PDF valido (falta la cabecera %PDF-)")
    if re.search(rb"/Encrypt\s*(?:\d+\s+\d+\s+R|<<)", datos):
        doc.avisos.append("PDF cifrado (/Encrypt): no se puede extraer el texto sin la contrasena")
        doc.meta = {}
        return doc
    if usar_pypdf and PYPDF:
        try:
            r = _pdf_con_pypdf(datos)
            if r and _legible(" ".join(r[0])):
                doc.meta = r[1]
                doc.secciones = [Seccion(f"Pagina {i}".replace("Pagina", "Página"), 1, [t.strip()]) for i, t in enumerate(r[0], 1) if t.strip()]
                doc.avisos.append("texto extraido con pypdf")
                return doc
        except Exception:
            pass                                                      # sin pypdf o fallo: se sigue con el lector propio
    objs = _objetos_pdf(datos)
    doc.meta = _meta_pdf(objs, datos)
    cid = set()
    for num, (dic, _s, _i) in objs.items():                           # fuentes Type0/Identity (2 bytes por glifo): sus cadenas no son texto
        if re.search(rb"/Subtype\s*/Type0\b|/Encoding\s*/Identity-[HV]", dic):
            cid.add(num)
    paginas = _orden_paginas(objs)
    textos, nops, hay_img = [], 0, any(img for _d, _s, img in objs.values()) or b"/Subtype/Image" in datos

    def contenidos(dic):
        m = re.search(rb"/Contents\s*(\[(.*?)\]|(\d+)\s+\d+\s+R)", dic, re.S)
        if not m:
            return []
        return [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(2) if m.group(2) is not None else m.group(0))]
    nombres_cid = set()
    for num in paginas:
        dic = objs[num][0]
        mf = re.search(rb"/Font\s*<<(.*?)>>", dic, re.S)
        if mf:
            for nm, ref in re.findall(rb"/(\w+)\s+(\d+)\s+\d+\s+R", mf.group(1)):
                if int(ref) in cid:
                    nombres_cid.add(nm)
        partes = []
        for c in contenidos(dic):
            st = objs.get(c, (b"", None, False))[1]
            if st:
                t, k = _texto_stream(st, nombres_cid)
                partes.append(t)
                nops += k
        textos.append("\n".join(partes))
    if not paginas:                                                   # sin arbol de paginas: todos los streams con texto, en orden de objeto
        for num in sorted(objs):
            st = objs[num][1]
            if st and b"BT" in st:
                t, k = _texto_stream(st, nombres_cid)
                textos.append(t)
                nops += k
    textos = [re.sub(r"[ \t]+", " ", re.sub(r"[ \t]*\n[ \t]*", "\n", t)).strip() for t in textos]
    if not _legible(" ".join(textos)):
        doc.avisos.append("El PDF no tiene texto legible: probablemente esta escaneado (solo imagenes) o usa fuentes CID/codificacion propia "
                          "(hace falta OCR, o instalar pypdf)" + (" [solo se encontraron imagenes]" if hay_img and not nops else ""))
        return doc
    doc.secciones = [Seccion(f"Página {i}", 1, [t]) for i, t in enumerate(textos, 1) if t]
    return doc


# ---------------------------------------------------------------- despacho y lectores del indice
def leer_bytes(datos, ext, nombre="", usar_pypdf=True):
    """bytes + extension -> Doc. Lanza DocError con un mensaje legible (nunca otra excepcion por culpa del archivo)."""
    ext = ext.lower() if ext.startswith(".") else "." + ext.lower()
    try:
        if ext in (".docx", ".docm", ".dotx"):
            doc = leer_docx(datos, nombre)
        elif ext in (".xlsx", ".xlsm"):
            doc = leer_xlsx(datos, nombre)
        elif ext == ".pptx":
            doc = leer_pptx(datos, nombre)
        elif ext in (".odt", ".ods"):
            doc = leer_odf(datos, nombre, ext)
        elif ext == ".pdf":
            doc = leer_pdf(datos, nombre, usar_pypdf)
        else:
            raise DocError(f"formato no soportado ({ext}); admito: " + " ".join(EXT_DOC))
    except DocError:
        raise
    except RecursionError as e:
        raise DocError("documento con anidacion excesiva") from e
    except (ET.ParseError, KeyError, ValueError, IndexError, AttributeError, TypeError, zipfile.BadZipFile, OSError, MemoryError) as e:
        raise DocError(f"documento danado o con estructura inesperada ({type(e).__name__})") from e
    doc.tamano = len(datos)
    doc.tipo = clasificar(doc.texto()[:30000], doc.nombre + " " + doc.meta.get("titulo", ""))
    return doc


def _lector(ext):
    def f(datos):
        doc = leer_bytes(datos, ext, "")
        t = TextoDoc(doc.a_texto_indexable())
        t.tipo, t.avisos = doc.tipo, tuple(doc.avisos)
        return t
    f.__name__ = "leer" + ext.replace(".", "_")
    return f


for _e in (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods", ".pdf"):
    registrar_lector(_e, _lector(_e))


# ---------------------------------------------------------------- numeros es-CL / es-ES / en-US
_RE_MONEDA = re.compile(r"(?i)\b(?:usd|clp|eur|cop|mxn|ars|pen|us\$)\b|[$€£%\s ]")


def parsear_numero(s, es=True):
    """'1.234,56' (es) y '1,234.56' (en) -> 1234.56; '(1.500)' -> -1500; '$ 2.000' -> 2000; None si no es un numero.
    Con un solo separador y exactamente 3 digitos detras ('1.234') es ambiguo: es=True lo toma como miles ('.') o decimal (','),
    es=False al reves (convencion en-US)."""
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return s
    t = str(s).strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = _RE_MONEDA.sub("", t)
    if t.endswith("-"):
        neg, t = True, t[:-1]
    if t[:1] in "+-":
        neg ^= t[0] == "-"
        t = t[1:]
    if not re.fullmatch(r"[\d.,']+", t) or not any(c.isdigit() for c in t) or not t[0].isdigit():
        return None
    t = t.replace("'", "")
    pd, pc = t.count("."), t.count(",")
    dec = None
    if pd and pc:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
    elif pd + pc == 1:
        sep = "." if pd else ","
        izq, der = t.split(sep)
        miles = len(der) == 3 and 1 <= len(izq) <= 3 and izq != "0"
        if miles:
            dec = None if ((sep == ".") == es) else sep
        else:
            dec = sep
    if dec:
        i = t.rfind(dec)
        ent, frac = t[:i].replace(".", "").replace(",", ""), t[i + 1:]
        if frac and not frac.isdigit():
            return None
        v = float(f"{ent or '0'}.{frac or '0'}")
    else:
        v = float(t.replace(".", "").replace(",", ""))
    v = -v if neg else v
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def _es_locale(valores):
    """True si la columna usa coma decimal (es-CL/es-ES), False si usa punto decimal (en-US). Por defecto es."""
    es = en = 0
    for v in valores:
        if not isinstance(v, str):
            continue
        t = _RE_MONEDA.sub("", v)
        if not re.fullmatch(r"[\d.,]+", t):
            continue
        pd, pc = t.count("."), t.count(",")
        if pd and pc:
            if t.rfind(",") > t.rfind("."):
                es += 1
            else:
                en += 1
        elif pd + pc == 1:
            sep = "." if pd else ","
            if len(t.split(sep)[1]) != 3:
                if sep == ",":
                    es += 1
                else:
                    en += 1
        elif pd > 1:
            es += 1
        elif pc > 1:
            en += 1
    return es >= en


def fmt_num(v):
    """Numero en formato es-CL: 3.735,06 / 1.270.000."""
    if isinstance(v, float) and not v.is_integer():
        s = f"{v:,.2f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(round(v)):,}".replace(",", ".")


def _norm_col(s):
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes(str(s).lower())).strip()


def _buscar_columna(cabecera, q):
    nq = _norm_col(q)
    mejor = (0.0, None)
    for i, h in enumerate(cabecera):
        nh = _norm_col(h)
        if not nh or not nq:
            continue
        if nh == nq:
            sc = 1.0
        elif len(nq) >= 3 and (nq in nh or nh in nq):
            sc = 0.9
        elif raiz(nq.replace(" ", "")) == raiz(nh.replace(" ", "")) and len(nq) >= 4:
            sc = 0.88
        else:
            sc = difflib.SequenceMatcher(None, nq, nh).ratio()
            sc = sc if sc >= 0.7 else 0.0
        if sc > mejor[0]:
            mejor = (sc, i)
    return mejor


def operar_columna(doc, columna, op="suma", hoja=None):
    """Suma / promedio / min / max / conteo de una columna (nombre difuso) de las tablas de `doc` (o de una Tabla).
    -> {valor, n, omitidos, columna, tabla, operacion} o {error}."""
    tablas = doc.tablas if isinstance(doc, Doc) else [doc]
    if hoja:
        th = [t for t in tablas if _norm_col(hoja) in _norm_col(t.nombre)]
        tablas = th or tablas
    best = None
    for t in tablas:
        sc, i = _buscar_columna(t.cabecera, columna)
        if i is not None and (best is None or sc > best[0]):
            best = (sc, i, t)
    if best is None:
        todas = [h for t in tablas for h in t.cabecera][:12]
        return {"error": f"No encuentro la columna «{columna}». Columnas disponibles: " + (", ".join(todas) if todas else "(el documento no tiene tablas)")}
    _sc, i, t = best
    crudos = [f[i] for f in t.filas if i < len(f) and f[i] not in (None, "")]
    es = _es_locale(crudos)
    nums, omit = [], 0
    for v in crudos:
        n = parsear_numero(v, es)
        if n is None:
            omit += 1
        else:
            nums.append(n)
    op = {"suma": "suma", "sumar": "suma", "total": "suma", "promedio": "promedio", "media": "promedio", "min": "min", "minimo": "min", "max": "max",
          "maximo": "max", "conteo": "conteo", "cuenta": "conteo", "cantidad": "conteo"}.get(sin_tildes(str(op).lower()), "suma")
    if op == "conteo":
        valor = len(crudos)
    elif not nums:
        return {"error": f"La columna «{t.cabecera[i]}» no tiene valores numericos ({omit} celdas de texto)."}
    elif op == "suma":
        valor = sum(nums)
    elif op == "promedio":
        valor = sum(nums) / len(nums)
    elif op == "min":
        valor = min(nums)
    else:
        valor = max(nums)
    if isinstance(valor, float):
        valor = round(valor, 10)
        valor = int(valor) if valor.is_integer() else valor
    return {"valor": valor, "n": len(nums), "omitidos": omit, "columna": t.cabecera[i], "tabla": t.nombre, "operacion": op}


# ---------------------------------------------------------------- clasificacion y estadisticas
_CLAS = {
    "factura": [(r"\bfacturas?\b", 3), (r"\bboletas?\b", 2), (r"\biva\b", 2), (r"\bsubtotal\b", 2), (r"total a pagar", 3), (r"\bfolio\b", 1),
                (r"\bmonto neto\b", 2), (r"\bvencimiento\b", 1), (r"\bcliente\b", 1)],
    "contrato": [(r"\bcontratos?\b", 3), (r"\bclausulas?\b", 2), (r"\barrendador\b|\barrendatario\b", 2), (r"\bvigencia\b", 1), (r"\blas partes\b", 1),
                 (r"\bfirman?\b|\bfirmado\b", 1), (r"\brescision\b|\bterminacion anticipada\b", 2), (r"\bobligaciones\b", 1)],
    "cv": [(r"curriculum|\bcv\b", 3), (r"experiencia laboral", 3), (r"formacion academica|educacion", 2), (r"\bhabilidades\b|\bcompetencias\b", 2),
           (r"\breferencias\b", 1), (r"\bidiomas\b", 1), (r"perfil profesional", 2)],
    "informe": [(r"\binformes?\b", 3), (r"resumen ejecutivo", 3), (r"\bconclusion(?:es)?\b", 2), (r"\brecomendaci(?:on|ones)\b", 2), (r"\bmetodologia\b", 2),
                (r"\bintroduccion\b", 1), (r"\bresultados\b", 1), (r"\banalisis\b", 1)],
    "receta": [(r"\brecetas?\b", 3), (r"\bingredientes\b", 3), (r"\bpreparacion\b", 2), (r"\bhornea\w*|\bhornear\b", 2), (r"\bporciones\b|\braciones\b", 2),
               (r"\bcoccion\b|\bhervir\b|\bhierve\b", 1), (r"\bamasar\b", 1)],
    "acta": [(r"\bactas?\b", 3), (r"\basistentes\b", 3), (r"\bacuerdos?\b", 2), (r"orden del dia", 3), (r"se levanta la sesion", 3), (r"\bsiendo las\b", 2),
             (r"\bsesion\b", 1)],
}
_CLAS_RX = {k: [(re.compile(p), w) for p, w in v] for k, v in _CLAS.items()}


def clasificar(texto, nombre=""):
    """Tipo de documento por palabras clave: factura | contrato | cv | informe | receta | acta | otro."""
    t = sin_tildes(texto[:30000].lower())
    n = sin_tildes(nombre.lower())
    mejor, pts = "otro", 0.0
    for k, rxs in _CLAS_RX.items():
        sc = 0.0
        for rx, w in rxs:
            sc += w * min(len(rx.findall(t)), 3) + (w if rx.search(n) else 0)
        if sc > pts:
            mejor, pts = k, sc
    return mejor if pts >= 3 else "otro"


_STOP_ES_EXTRA = set("""fue fueron era eran ha han he hemos son ser esta estan estaba estar este estos estas ese esos esas aquel aquella
muy mas menos tambien tanto cuando donde como pero sino porque aunque sobre entre hasta desde durante segun hacia ante bajo tras cada
otro otra otros otras todo toda todos todas algun alguna algunos algunas ningun ninguna mismo misma nuestro nuestra vuestro sus
suyo ella ellos ellas nosotros usted ustedes hay hubo habia sera seria podria puede pueden deben debe tiene tienen tuvo""".split())
_STOP_EN = set("""the of and to in is are was were be been being that this these those it its for on with as by at from or an a not but have has had
will would can could should may might do does did we you they he she them our your their which who what when where how than then so if
into over under about after before between during through""".split())
_STOP_ES = set(STOP) | _STOP_ES_EXTRA | set("de la el en y a los las un una por con para del al se que no es lo su sus".split())


def estadisticas(texto):
    """{palabras, minutos (200 ppm), top [(termino, n)], idioma 'es'|'en'|'indeterminado'}."""
    ws = RE_TOK.findall(sin_tildes(texto.lower()))
    cnt = {}
    for w in ws:
        if len(w) >= 4 and w not in _STOP_ES and w not in _STOP_EN and w not in RELLENO and not w.isdigit():
            cnt[w] = cnt.get(w, 0) + 1
    top = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[:8]
    es = sum(1 for w in ws if w in _STOP_ES)
    en = sum(1 for w in ws if w in _STOP_EN)
    idioma = "es" if es > en * 1.3 else "en" if en > es * 1.3 else "indeterminado"
    return {"palabras": len(texto.split()), "minutos": max(1, math.ceil(len(texto.split()) / 200)), "top": top, "idioma": idioma}


# ---------------------------------------------------------------- resumen extractivo (sin LLM)
_STOP_RES = _STOP_ES | _STOP_EN | set(RELLENO)


def _terminos(frase):
    return [raiz(w) for w in RE_TOK.findall(sin_tildes(frase.lower())) if len(w) >= 3 and w not in _STOP_RES and not w.isdigit()]


def _frases_candidatas(texto):
    out = []
    for i, f in enumerate(dividir_frases(texto)):
        n = len(f.split())
        if 5 <= n <= 70 and " | " not in f and re.search(r"[^\W\d_]{3,}", f):
            out.append((i, f))
    return out


def resumir(texto, n=4, metodo="tfidf"):
    """Las `n` frases mas importantes en su orden original. 'tfidf': puntua cada frase por frecuencia de terminos (tf del documento x idf
    sobre las frases) normalizada por su longitud, mas un bonus de posicion (las primeras valen mas). 'textrank': PageRank sobre el grafo
    de similitud por solapamiento de terminos. Sin LLM."""
    cand = _frases_candidatas(texto)
    if not cand:
        return []
    if len(cand) <= n:
        return [f for _i, f in cand]
    toks = [_terminos(f) for _i, f in cand]
    N = len(cand)
    if metodo == "textrank":
        conj = [set(t) for t in toks]
        sim = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(i + 1, N):
                if conj[i] and conj[j]:
                    com = len(conj[i] & conj[j])
                    if com:
                        sim[i][j] = sim[j][i] = com / (math.log(len(conj[i]) + 1) + math.log(len(conj[j]) + 1) + 1e-9)
        sal = [sum(r) or 1.0 for r in sim]
        pr = [1.0 / N] * N
        for _ in range(30):
            pr = [0.15 / N + 0.85 * sum(sim[j][i] / sal[j] * pr[j] for j in range(N) if sim[j][i]) for i in range(N)]
        puntos = pr
    else:
        tf, df = {}, {}
        for t in toks:
            for w in t:
                tf[w] = tf.get(w, 0) + 1
            for w in set(t):
                df[w] = df.get(w, 0) + 1
        puntos = []
        for k, t in enumerate(toks):
            u = set(t)
            s = sum((1 + math.log(tf[w])) * math.log(1 + N / df[w]) for w in u)
            s /= math.sqrt(len(u) + 1)
            puntos.append(s * (1 + 0.3 * (1 - k / N)))
    elegidas = sorted(sorted(range(N), key=lambda k: -puntos[k])[:n])
    return [cand[k][1] for k in elegidas]


# ---------------------------------------------------------------- preguntas sobre un documento (BM25 en memoria)
def _chunks_doc(doc, mx=90):
    """[(titulo_seccion, texto)] de <= mx palabras (por lineas; las lineas largas por frases)."""
    out = []
    for s in doc.secciones:
        for linea in s.partes:
            for sub in linea.split("\n"):
                if not sub.strip():
                    continue
                if len(sub.split()) <= mx:
                    out.append((s.titulo, sub))
                else:
                    cur, nw = [], 0
                    for fr in re.split(r"(?<=[.!?])\s+", sub):
                        w = len(fr.split())
                        if cur and nw + w > mx:
                            out.append((s.titulo, " ".join(cur)))
                            cur, nw = [], 0
                        cur.append(fr)
                        nw += w
                    if cur:
                        out.append((s.titulo, " ".join(cur)))
    return out


def responder_doc(doc, pregunta, k=3):
    """Las 1-k frases del documento que mejor responden a `pregunta`: BM25 sobre los trozos (en memoria) y, dentro de los mejores,
    las frases con mas terminos de la pregunta. -> [(titulo_de_seccion, frase, puntaje)] (vacio si el tema no aparece)."""
    from .conocimiento import PREGUNTA_PAL, parsear_consulta
    c = parsear_consulta(pregunta)
    terminos = [t for t in c.terminos if t not in PREGUNTA_PAL]
    chunks = _chunks_doc(doc)
    if not terminos or not chunks:
        return []
    toks = [RE_TOK.findall(sin_tildes(t.lower())) for _s, t in chunks]
    N = len(chunks)
    avgdl = sum(len(t) for t in toks) / N or 1.0
    tfs = [[_casa(t, tk) for t in terminos] for tk in toks]
    idf = []
    for j in range(len(terminos)):
        n = sum(1 for tf in tfs if tf[j])
        idf.append(math.log(1 + (N - n + 0.5) / (n + 0.5)))
    punt = []
    for i, tk in enumerate(toks):
        K = 1.2 * (0.25 + 0.75 * len(tk) / avgdl)
        punt.append(sum(idf[j] * tf * 2.2 / (tf + K) for j, tf in enumerate(tfs[i]) if tf))
    top = [i for i in sorted(range(N), key=lambda i: -punt[i])[:4] if punt[i] > 0]
    cands = []
    for i in top:
        for fr in dividir_frases(chunks[i][1]) or [chunks[i][1]]:
            ft = RE_TOK.findall(sin_tildes(fr.lower()))
            hits = [_casa(t, ft) for t in terminos]
            dist = sum(1 for h in hits if h)
            if dist:
                cands.append((dist, punt[i], chunks[i][0], fr))
    if not cands:
        return []
    cands.sort(key=lambda x: (-x[0], -x[1]))
    if cands[0][0] * 2 < len(terminos):
        return []
    out, vistos = [], set()
    for dist, p, sec, fr in cands:
        if fr in vistos or dist < cands[0][0] - (1 if len(terminos) > 2 else 0) and out:
            continue
        vistos.add(fr)
        out.append((sec, fr, round(dist + p / 100, 3)))
        if len(out) >= k:
            break
    return out


# ---------------------------------------------------------------- entidades por regex
_MESES = "enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre".split()
_RX = {
    "emails": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "urls": re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.I),
    "ruts": re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{3}){2}|\d{7,8})-([\dkK])(?![\w])"),
    "fecha_txt": re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")(?:\s+(?:de|del)\s+(\d{4}))?\b", re.I),
    "fecha_num": re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?![\d/])"),
    "fecha_iso": re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    "dnis": re.compile(r"(?<![\w.])(\d{8})([A-Za-z])(?![\w])"),
    "tel": re.compile(r"(?<![\w.,+])(?:\+\d{1,3}[ -]?)?(?:\(?\d{1,4}\)?[ -])?\d{3,4}[ -]?\d{3,4}(?![\w])"),
}
_NUM = r"\d{1,3}(?:[., ']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MON = r"(?:US\$|USD|CLP|EUR|COP|MXN|ARS|PEN|\$|€|£)"
_RX["monto_pre"] = re.compile(r"(?<![\w$])" + _MON + r"\s?(" + _NUM + r")")
_RX["monto_suf"] = re.compile(r"(?<![\d.,])(" + _NUM + r")\s?(?:USD|CLP|EUR|COP|MXN|ARS|PEN|pesos|d[oó]lares|euros|€|\$)(?!\w)", re.I)
_LETRA_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"


def valida_rut(cuerpo, dv):
    s, f = 0, 2
    for c in reversed(re.sub(r"\D", "", cuerpo)):
        s += int(c) * f
        f = 2 if f == 7 else f + 1
    r = 11 - s % 11
    return str({11: 0, 10: "K"}.get(r, r)) == dv.upper()


def entidades(texto):
    """Fechas, montos, emails, telefonos, RUT chileno (con digito verificador), DNI y URLs por regex.
    -> {tipo: [(texto, extra)]}; extra: fecha ISO / monto normalizado / True|False (RUT, DNI validos)."""
    t = texto[:2_000_000]
    res = {k: [] for k in ("fechas", "montos", "emails", "telefonos", "ruts", "dnis", "urls")}
    vistos = {k: set() for k in res}
    masc = [t]

    def tomar(rx, clave, fn, quitar=True):
        s = masc[0]
        for m in rx.finditer(s):
            if len(res[clave]) >= 500:
                break
            r = fn(m)
            if r is None:
                continue
            if r[0] not in vistos[clave]:
                vistos[clave].add(r[0])
                res[clave].append(r)
        if quitar:
            masc[0] = rx.sub(lambda m: " " * len(m.group(0)), s)
    tomar(_RX["emails"], "emails", lambda m: (m.group(0).rstrip(".-"), None))

    def url(m):
        u = m.group(0).rstrip(".,;:!?)")
        return (u, None)
    tomar(_RX["urls"], "urls", url)

    def rut(m):
        return (m.group(0), valida_rut(m.group(1), m.group(2)))
    tomar(_RX["ruts"], "ruts", rut)

    def ftxt(m):
        return (m.group(0), None)

    def fnum(m):
        d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return None
        return (m.group(0), f"{a if a > 99 else 2000 + a:04d}-{mo:02d}-{d:02d}")

    def fiso(m):
        a, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (m.group(0), m.group(0)) if 1 <= mo <= 12 and 1 <= d <= 31 else None
    tomar(_RX["fecha_txt"], "fechas", ftxt)
    tomar(_RX["fecha_num"], "fechas", fnum)
    tomar(_RX["fecha_iso"], "fechas", fiso)

    def dni(m):
        n, letra = int(m.group(1)), m.group(2).upper()
        return (m.group(0), _LETRA_DNI[n % 23] == letra)
    tomar(_RX["dnis"], "dnis", dni)

    def monto(m):
        v = parsear_numero(m.group(1), _es_locale([m.group(1)]))
        return (m.group(0).strip(), v) if v is not None else None
    tomar(_RX["monto_pre"], "montos", monto)
    tomar(_RX["monto_suf"], "montos", monto)

    def tel(m):
        d = re.sub(r"\D", "", m.group(0))
        return (m.group(0).strip(), None) if 7 <= len(d) <= 13 and len(set(d)) > 2 else None
    tomar(_RX["tel"], "telefonos", tel)
    return res


# ---------------------------------------------------------------- sesion: documento reciente, cache y traza para !porque
class SesionDocs:
    def __init__(self):
        self.ultimo = None                  # ruta del ultimo documento leido ("muestrame la seccion 3", "promedio de Ventas")
        self.cache = OrderedDict()          # (ruta, mtime_ns, tamano) -> Doc  (LRU de 6)
        self.traza = []                     # que documento/seccion uso la ultima herramienta (!porque)
        self.pendientes = []                # candidatos de una desambiguacion


def _sesion(ctx):
    if getattr(ctx, "docs", None) is None:
        ctx.docs = SesionDocs()
    return ctx.docs


_DET = r"(?:el|la|los|las|mi|mis|este|esta|ese|esa|un|una)"
_SUST = (r"(?:documento|informe|contrato|factura|presupuesto|cv|curriculum|acta|reporte|planilla|presentacion|pdf|word|excel|receta|"
         r"hoja\s+de\s+calculo|diapositivas)")
_EXT = r"(?:docx|docm|xlsx|xlsm|pptx|odt|ods|pdf)"
_RX_ARCH_Q = re.compile(r"[\"“«']([^\"”»']+\." + _EXT + r")[\"”»']", re.I)
_RX_ARCH_UNIDAD = re.compile(r"[A-Za-z]:[\\/][^\"<>|?*\r\n]*?\." + _EXT + r"(?![\w])", re.I)
_RX_ARCH = re.compile(r"(?:[\w.\-()áéíóúñÁÉÍÓÚÑ]+[\\/])*[\w.\-()áéíóúñÁÉÍÓÚÑ]+\." + _EXT + r"(?![\w])", re.I)
_RX_NOMBRE = re.compile(r"\b" + _DET + r"\s+(?:(?:documento|archivo|fichero)\s+)?(" + _SUST + r")\b", re.I)


def _ref_doc(orig, plano):
    """(referencia, (ini, fin)) del documento nombrado en la frase (ruta, nombre de archivo o sustantivo 'el informe') o None."""
    for rx in (_RX_ARCH_Q, _RX_ARCH_UNIDAD, _RX_ARCH):
        m = rx.search(orig)
        if m:
            g = 1 if rx is _RX_ARCH_Q else 0
            return m.group(g).strip(), (m.start(), m.end())
    m = _RX_NOMBRE.search(plano)
    if m:
        return orig[m.start(1):m.end(1)], (m.start(), m.end())
    return None


def _ex_ruta(an, ctx, orig, plano):
    r = _ref_doc(orig, plano)
    return {"ruta": r[0]} if r else {}


_PRE = r"^(?:(?:por\s+favor|porfa|oye|hola|ok|vale)\s+)*"
def _gate(*claves):
    """condicion barata (substrings en la frase plana) para que decidir() no corra las regex de cada herramienta de documentos en cada frase."""
    return lambda ctx, plano: any(k in plano for k in claves)


_V_LEER = (r"(?:lee|leer|leeme|lea|resume|resumeme|resumir|resumen\s+de(?:l)?|haz(?:me)?\s+un\s+resumen\s+de(?:l)?|dame\s+un\s+resumen\s+de(?:l)?|"
           r"abre\s+y\s+(?:lee|leeme|resume|resumeme)|de\s+que\s+(?:trata|habla)|extrae\s+el\s+texto\s+de(?:l)?)")


def _resolver_candidatos(ctx, ref):
    """Documentos que casan con `ref`. -> (lista de rutas, mensaje_error). Solo lectura: validar_ruta (realpath) y extension de documento."""
    ses = _sesion(ctx)
    ref = (ref or "").strip().strip("\"'“”«»").strip()
    if not ref:
        if ses.ultimo and os.path.isfile(ses.ultimo):
            return [ses.ultimo], ""
        return [], "¿Que documento? Dime la ruta o el nombre (ej. 'lee informe.docx')."
    ref = re.sub(r"^(?:" + _DET + r"\s+)?(?:(?:documento|archivo|fichero)\s+)?", "", ref, flags=re.I).strip() or ref
    ext = os.path.splitext(ref)[1].lower()
    carpetas = [c for c in dict.fromkeys(list(getattr(ctx, "carpetas", {}).values()) + [getattr(ctx, "home", os.path.expanduser("~"))]) if c and os.path.isdir(c)]
    if ext:
        if ext not in EXT_DOC:
            return [], f"Formato no soportado ({ext}); admito: " + " ".join(EXT_DOC)
        refw = ref.replace("/", "\\")
        directos = []
        if re.match(r"^(?:[A-Za-z]:\\|\\\\|~|%)", refw) or os.path.isabs(ref):
            directos.append(os.path.expandvars(os.path.expanduser(ref)))
        else:
            partes = refw.split("\\")
            alias = {"descargas": "descargas", "downloads": "descargas", "documentos": "documentos", "documents": "documentos", "escritorio": "escritorio",
                     "desktop": "escritorio", "imagenes": "imagenes", "pictures": "imagenes", "musica": "musica", "music": "musica", "videos": "videos"}
            k = alias.get(sin_tildes(partes[0].lower()))
            if len(partes) > 1 and k and getattr(ctx, "carpetas", {}).get(k):
                directos.append(os.path.join(ctx.carpetas[k], *partes[1:]))
            directos += [os.path.join(c, *partes) for c in carpetas]
        hallados = []
        for p in directos:
            if os.path.isfile(p):
                hallados.append(os.path.realpath(p))
        base = os.path.basename(refw).lower()
        if not hallados and "\\" not in refw:
            K = getattr(ctx, "conocimiento", None)
            if K is not None:
                hallados += [os.path.realpath(r_) for r_, _m in K.archivos_indexados([ext]) if os.path.basename(r_).lower() == base]
        vistos, uniq = set(), []
        for h in hallados:
            if os.path.normcase(h) not in vistos:
                vistos.add(os.path.normcase(h))
                uniq.append(h)
        if not uniq:
            return [], f"No encuentro el documento «{ref}» (prueba con la ruta completa o indexa su carpeta con !indexar)."
        return uniq, ""
    # nombre sin extension ("el informe"): difuso sobre los documentos indexados, los recientes y el primer nivel de las carpetas conocidas
    pool = {}
    K = getattr(ctx, "conocimiento", None)
    if K is not None:
        for r_, m in K.archivos_indexados(EXT_DOC):
            pool[os.path.normcase(os.path.realpath(r_))] = (r_, m)
    for r_ in [k[0] for k in ses.cache]:
        pool.setdefault(os.path.normcase(r_), (r_, os.path.getmtime(r_) if os.path.exists(r_) else 0))
    for c in carpetas:
        try:
            with os.scandir(c) as it:
                for e in it:
                    if e.is_file() and os.path.splitext(e.name)[1].lower() in EXT_DOC:
                        pool.setdefault(os.path.normcase(os.path.realpath(e.path)), (e.path, e.stat().st_mtime))
        except OSError:
            pass
    rt = [w for w in RE_TOK.findall(sin_tildes(ref.lower())) if w not in STOP and w not in ("documento", "archivo", "fichero")]
    if not rt:
        return [], "¿Que documento? Dime la ruta o el nombre."
    puntos = []
    for _k, (ruta, m) in pool.items():
        nt = RE_TOK.findall(sin_tildes(os.path.splitext(os.path.basename(ruta))[0].lower()))
        hit = 0
        for w in rt:
            r = raiz(w)
            if any(x == w or (len(r) >= 4 and x.startswith(r)) or (len(w) >= 5 and difflib.SequenceMatcher(None, w, x).ratio() >= 0.85) for x in nt):
                hit += 1
        sc = hit / len(rt)
        if sc >= 0.99 or (sc >= 0.66 and len(rt) >= 3):
            puntos.append((sc, m, ruta))
    if not puntos:
        return [], f"No encuentro ningun documento que se llame «{ref}» (indexa su carpeta con !indexar o dame la ruta)."
    mejor = max(p[0] for p in puntos)
    cand = sorted((p for p in puntos if p[0] >= mejor - 1e-9), key=lambda p: (-p[1], p[2]))
    return [os.path.realpath(p[2]) for p in cand], ""


def _cargar(ctx, ref):
    """-> (Doc, None) | (None, Resultado de error / pregunta de desambiguacion)."""
    ses = _sesion(ctx)
    cand, err = _resolver_candidatos(ctx, ref)
    if err:
        return None, Resultado(False, err)
    if len(cand) > 1:
        ses.pendientes = cand[:6]
        L = [f"Hay {len(cand)} documentos que coinciden con «{ref}»; dime cual quieres (con su nombre completo):"]
        L += [f"  {i}. {os.path.basename(c)}  ({os.path.dirname(c)})" for i, c in enumerate(cand[:6], 1)]
        return None, Resultado(False, "\n".join(L), {"ambiguo": cand[:6]})
    ruta = cand[0]
    ok, real, motivo = validar_ruta(ruta, requiere_existir=True, escritura=False)      # solo lectura
    if not ok:
        return None, Resultado(False, f"Ruta rechazada: {motivo}")
    ext = os.path.splitext(real)[1].lower()
    if ext not in EXT_DOC or not os.path.isfile(real):
        return None, Resultado(False, f"No es un documento que sepa leer ({ext or 'sin extension'}); admito: " + " ".join(EXT_DOC))
    st = os.stat(real)
    if st.st_size > MAX_LEER:
        return None, Resultado(False, f"El archivo pesa {st.st_size // 2 ** 20} MB (tope {MAX_LEER // 2 ** 20} MB).")
    clave = (real, st.st_mtime_ns, st.st_size)
    doc = ses.cache.get(clave)
    if doc is None:
        try:
            with open(real, "rb") as f:
                datos = f.read(MAX_LEER + 1)
            doc = leer_bytes(datos, ext, os.path.basename(real))
        except DocError as e:
            return None, Resultado(False, f"No puedo leer {os.path.basename(real)}: {e}")
        except OSError as e:
            return None, Resultado(False, f"No puedo abrir {os.path.basename(real)}: {e.strerror or type(e).__name__}")
        doc.ruta = real
        ses.cache[clave] = doc
        while len(ses.cache) > 6:
            ses.cache.popitem(last=False)
    else:
        ses.cache.move_to_end(clave)
    ses.ultimo = real
    return doc, None


def _kb(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


# ---------------------------------------------------------------- herramientas
@herramienta("leer", slots={"ruta": "texto?"}, extraer=_ex_ruta, peso_senal=0.97, condicion=_gate("lee", "resum", "trata", "habla", "extrae"),
             disparadores=(_PRE + _V_LEER + r"\b.*\." + _EXT + r"(?![\w])", _PRE + _V_LEER + r"\s+(?:" + _DET + r"\s+)(?:(?:documento|archivo|fichero)\s+)?" + _SUST + r"\b"),
             descripcion="lee un documento (docx xlsx pptx odt ods pdf): metadatos, indice de secciones, tipo, estadisticas y resumen extractivo: 'lee el informe.docx', "
                         "'abre y resume Descargas\\presupuesto.xlsx'")
def leer(ctx, ruta=None):
    doc, err = _cargar(ctx, ruta)
    if err:
        return err
    ses = _sesion(ctx)
    txt = doc.texto()
    est = estadisticas(txt)
    L = [f"{doc.nombre} ({doc.formato}, {_kb(doc.tamano)}) - tipo: {doc.tipo}"]
    m = [f"{k}: {doc.meta[c]}" for k, c in (("Titulo", "titulo"), ("Autor", "autor"), ("Fecha", "fecha"), ("Asunto", "asunto")) if doc.meta.get(c)]
    if m:
        L.append("  " + " | ".join(m))
    L.append(f"  {est['palabras']} palabras - ~{est['minutos']} min de lectura - idioma: {est['idioma']}"
             + (" - temas: " + ", ".join(t for t, _n in est['top'][:6]) if est["top"] else ""))
    for a in doc.avisos:
        L.append("  Aviso: " + a)
    if doc.secciones:
        L.append(f"  Secciones ({len(doc.secciones)}):")
        for i, s in enumerate(doc.secciones[:40], 1):
            L.append(f"   {i}. {'  ' * (s.nivel - 1 if 0 < s.nivel < 4 else 0)}{s.titulo or '(sin titulo)'}  ({s.palabras()} palabras)")
        if len(doc.secciones) > 40:
            L.append(f"   ... y {len(doc.secciones) - 40} mas")
    if doc.formato in ("XLSX", "ODS"):
        for t in doc.tablas[:10]:
            L.append(f"  {t.nombre}: {len(t.filas)} filas; columnas: " + ", ".join(t.cabecera[:12]))
    else:
        res = resumir(txt, 4)
        if res:
            L.append("  Resumen:")
            L += [f"   - {x}" for x in res]
    ses.traza = [{"documento": doc.nombre, "ruta": doc.ruta, "secciones": [s.titulo for s in doc.secciones[:3]], "metodo": "lectura + resumen extractivo (TF-IDF por frases)"}]
    return Resultado(True, "\n".join(L), {"ruta": doc.ruta, "tipo": doc.tipo, "secciones": [s.titulo for s in doc.secciones], "palabras": est["palabras"]})


@herramienta("seccion", slots={"ruta": "texto?", "n": "n"}, extraer=_ex_ruta, peso_senal=0.97, condicion=_gate("seccion", "diapositiva", "hoja", "pagina", "capitulo"),
             disparadores=(re.compile(_PRE + r"(?:muestra\w*|ensena\w*|dame|dime|lee\w*|abre|ver|mira)\s+(?:me\s+)?(?:" + _DET + r"\s+)?"
                                      r"(?:seccion|diapositiva|hoja|pagina|capitulo)\s+(?P<n>\d{1,4})\b"),),
             descripcion="muestra la seccion N (titulo, diapositiva, hoja o pagina) de un documento: 'muestrame la seccion 3', 'la seccion 2 del informe.docx'")
def seccion(ctx, n, ruta=None):
    doc, err = _cargar(ctx, ruta)
    if err:
        return err
    n = int(n)
    if not 1 <= n <= len(doc.secciones):
        return Resultado(False, f"{doc.nombre} tiene {len(doc.secciones)} seccion(es); no existe la seccion {n}.")
    s = doc.secciones[n - 1]
    cuerpo = s.texto
    cortado = len(cuerpo) > 4000
    _sesion(ctx).traza = [{"documento": doc.nombre, "ruta": doc.ruta, "secciones": [s.titulo], "metodo": f"seccion {n} por numero"}]
    return Resultado(True, f"{doc.nombre} - seccion {n} de {len(doc.secciones)}: {s.titulo or '(sin titulo)'} ({s.palabras()} palabras)\n"
                     + cuerpo[:4000] + ("\n[... recortado]" if cortado else ""), {"n": n, "titulo": s.titulo, "texto": cuerpo})


_V_PREG = r"(?:que\s+(?:dice\w*|menciona\w*|cuenta|habla|trata|hay|se\s+dice)|segun)"
_RX_PREG = re.compile(_PRE + _V_PREG + r"\s+(?:" + _DET + r"\s+)?(?:(?:documento|archivo|fichero)\s+)?"
                      r"(?P<ruta>\S*\." + _EXT + r"|" + _SUST + r")\s+(?:sobre|acerca\s+de|respecto\s+a|de|del|en\s+cuanto\s+a)\s+(?P<pregunta>.+)$")


@herramienta("preguntar_doc", slots={"ruta": "texto?", "pregunta": "texto"}, peso_senal=0.97, condicion=_gate("dice", "dicen", "decia", "menciona", "cuenta", "habla", "trata", "hay", "segun"), disparadores=(_RX_PREG,),
             descripcion="busca en UN documento lo que dice sobre un tema (BM25 en memoria): '¿que dice el informe sobre el presupuesto?'")
def preguntar_doc(ctx, pregunta, ruta=None):
    doc, err = _cargar(ctx, ruta)
    if err:
        return err
    pregunta = re.sub(r"^(?:el|la|los|las|mi|mis|su|sus)\s+", "", pregunta.strip().strip("?¿!¡ ."), flags=re.I)
    hs = responder_doc(doc, pregunta)
    _sesion(ctx).traza = [{"documento": doc.nombre, "ruta": doc.ruta, "secciones": list(dict.fromkeys(h[0] for h in hs)), "metodo": "BM25 en memoria sobre los trozos del documento"}]
    if not hs:
        return Resultado(True, f"No encuentro nada sobre «{pregunta}» en {doc.nombre}.", {"frases": []})
    L = [f"Sobre «{pregunta}» en {doc.nombre}:"]
    L += [f"  {i}. [{h[0] or 'sin titulo'}] {h[1]}" for i, h in enumerate(hs, 1)]
    return Resultado(True, "\n".join(L), {"frases": [{"seccion": h[0], "frase": h[1], "puntaje": h[2]} for h in hs]})


_TIPOS_ENT = {"fecha": "fechas", "fechas": "fechas", "monto": "montos", "montos": "montos", "importe": "montos", "importes": "montos",
              "email": "emails", "emails": "emails", "correo": "emails", "correos": "emails", "telefono": "telefonos", "telefonos": "telefonos",
              "rut": "ruts", "ruts": "ruts", "dni": "dnis", "dnis": "dnis", "url": "urls", "urls": "urls", "enlace": "urls", "enlaces": "urls",
              "link": "urls", "links": "urls"}
_ENT_RX = r"(?P<tipo>fechas?|montos?|importes?|emails?|correos?|telefonos?|ruts?|dnis?|urls?|enlaces|enlace|links?)"
_DOC_RX = r"(?:" + _DET + r"\s+)?(?:(?:documento|archivo|fichero)\s+)?(?:\S*\." + _EXT + r"|" + _SUST + r")"
_RX_ENT = (re.compile(_PRE + r"(?:que|cuales|cuantas|cuantos)\s+" + _ENT_RX + r"\s+(?:aparec\w+|hay|salen?|figuran?|menciona\w*|contiene\w*|tiene\w*|se\s+mencionan?)\s+"
                      r"(?:en|dentro\s+de)\s+" + _DOC_RX),
           re.compile(_PRE + r"(?:extrae\w*|saca\w*|lista\w*|dame|muestra\w*|dime|busca\w*)\s+(?:todos\s+)?(?:" + _DET + r"\s+)?" + _ENT_RX +
                      r"\s+(?:de|del|de\s+la|en|dentro\s+de)\s+" + _DOC_RX))


@herramienta("entidades", slots={"ruta": "texto?", "tipo": ("texto", "todas")}, extraer=_ex_ruta, peso_senal=0.97,
             condicion=_gate("fecha", "monto", "importe", "email", "correo", "telefono", "rut", "dni", "url", "enlace", "link"), disparadores=_RX_ENT,
             descripcion="extrae fechas, montos, emails, telefonos, RUT (valida el digito verificador), DNI y URLs de un documento: '¿que fechas aparecen en el contrato?'")
def entidades_(ctx, ruta=None, tipo="todas"):
    doc, err = _cargar(ctx, ruta)
    if err:
        return err
    ent = entidades(doc.texto())
    k = _TIPOS_ENT.get(sin_tildes(str(tipo).lower()))
    claves = [k] if k else list(ent)
    nombres = {"fechas": "Fechas", "montos": "Montos", "emails": "Emails", "telefonos": "Telefonos", "ruts": "RUT", "dnis": "DNI", "urls": "URLs"}
    L, hay = [f"Entidades en {doc.nombre}:"], False
    for c in claves:
        items = ent[c]
        if not items:
            continue
        hay = True

        def fmt(it):
            if c in ("ruts", "dnis"):
                return f"{it[0]} ({'valido' if it[1] else 'digito verificador invalido'})"
            if c == "montos":
                return f"{it[0]} (= {fmt_num(it[1])})"
            return it[0]
        L.append(f"  {nombres[c]} ({len(items)}): " + "; ".join(fmt(i) for i in items[:25]) + (" ..." if len(items) > 25 else ""))
    if not hay:
        L = [f"No encontre {nombres[k].lower() if k else 'entidades'} en {doc.nombre}."]
    _sesion(ctx).traza = [{"documento": doc.nombre, "ruta": doc.ruta, "secciones": [], "metodo": "regex de " + (nombres[k] if k else "todas las entidades")}]
    return Resultado(True, "\n".join(L), {c: [list(i) for i in ent[c]] for c in claves})


_OPS = (("promedio", "promedio"), ("media", "promedio"), ("minimo", "min"), ("menor", "min"), ("maximo", "max"), ("mayor", "max"), ("suma", "suma"),
        ("sumar", "suma"), ("total", "suma"), ("conteo", "conteo"), ("cuantos", "conteo"), ("cuantas", "conteo"), ("cantidad de", "conteo"))
_OPW = r"(?:suma\w*|total|promedio|media|maximo|minimo|mayor|menor|conteo|cuantos|cuantas|cantidad\s+de)"
_RX_TAB_COL = re.compile(_PRE + r".*\b" + _OPW + r"\b.*\bcolumna\b")
_RX_TAB_EXT = re.compile(_PRE + r"(?:cuanto\s+(?:suma\w*|es\s+(?:el\s+)?total)|(?:el|la)\s+" + _OPW + r"|" + _OPW + r").*\.(?:xlsx|xlsm|ods|docx|odt)(?![\w])")
_RX_TAB_REC = re.compile(_PRE + r"(?:(?:el|la)\s+)?(?:promedio|media|suma|total|maximo|minimo)\s+(?:de|del)\s+(?:la\s+)?(?:columna\s+)?(?P<c>[^.]+?)$")


def _col_de_frase(orig, plano):
    """(operacion, columna) de 'cuanto suma la columna Monto en gastos.xlsx' / 'promedio de Ventas'."""
    r = _ref_doc(orig, plano)
    sin = orig
    spl = plano
    if r:
        i, j = r[1]
        pre = plano[:i].rstrip()
        m = re.search(r"\s(?:en|de|del|dentro\s+de)(?:\s+(?:el|la|los|las|mi)){0,2}(?:\s+(?:archivo|documento|hoja|planilla|excel|libro))?$", pre)
        corte = m.start() if m else i
        sin, spl = orig[:corte] + " " + orig[j:], plano[:corte] + " " + plano[j:]
    op = next((v for k, v in _OPS if re.search(r"\b" + k + r"\w*\b", spl)), "suma")
    m = re.search(r"\bcolumna\s+(?:llamada\s+|de\s+)?[\"“']?(.+?)[\"”']?\s*[?¿!.]*\s*$", spl)
    if m:
        return op, sin[m.start(1):m.end(1)].strip()
    m = re.search(r"\b" + _OPW + r"\s+(?:de|del)\s+(?:la\s+)?(?:todos\s+los\s+)?(.+?)\s*[?¿!.]*\s*$", spl)
    if m:
        return op, sin[m.start(1):m.end(1)].strip()
    return op, ""


def _ex_tabla(an, ctx, orig, plano):
    op, col = _col_de_frase(orig, plano)
    out = {"operacion": op}
    if col:
        out["columna"] = col
    out.update(_ex_ruta(an, ctx, orig, plano))
    return out


_GATE_TAB = ("suma", "total", "promedio", "media", "maximo", "minimo", "mayor", "menor", "conteo", "cuantos", "cuantas", "cantidad")


def _cond_tabla(ctx, plano):
    if not any(k in plano for k in _GATE_TAB):
        return False
    if _RX_TAB_COL.search(plano) or _RX_TAB_EXT.search(plano):
        return True
    m = _RX_TAB_REC.search(plano)                       # "promedio de Ventas": solo si esa columna existe en el documento reciente
    ses = getattr(ctx, "docs", None)
    if not m or ses is None or not ses.ultimo:
        return False
    doc = next((d for k, d in ses.cache.items() if k[0] == ses.ultimo), None)
    return bool(doc and doc.tablas and any(_buscar_columna(t.cabecera, m.group("c"))[0] >= 0.8 for t in doc.tablas))


@herramienta("tabla", slots={"ruta": "texto?", "columna": "texto", "operacion": ("texto", "suma")}, extraer=_ex_tabla, peso_senal=0.97, condicion=_cond_tabla,
             disparadores=(_RX_TAB_COL, _RX_TAB_EXT, _RX_TAB_REC),
             descripcion="suma, promedio, minimo, maximo o conteo de una columna (nombre difuso, numeros es-CL/es-ES/en-US): '¿cuanto suma la columna Monto en gastos.xlsx?', "
                         "'promedio de Ventas'")
def tabla(ctx, columna, operacion="suma", ruta=None):
    doc, err = _cargar(ctx, ruta)
    if err:
        return err
    r = operar_columna(doc, columna, operacion)
    if r.get("error"):
        return Resultado(False, r["error"])
    nom = {"suma": "Suma", "promedio": "Promedio", "min": "Minimo", "max": "Maximo", "conteo": "Conteo"}[r["operacion"]]
    extra = f" ({r['omitidos']} celdas no numericas omitidas)" if r["omitidos"] else ""
    _sesion(ctx).traza = [{"documento": doc.nombre, "ruta": doc.ruta, "secciones": [r["tabla"]], "metodo": f"{r['operacion']} de la columna {r['columna']}"}]
    return Resultado(True, f"{nom} de «{r['columna']}» en {doc.nombre} ({r['tabla']}): {fmt_num(r['valor'])}  [{r['n']} valores]{extra}", r)
