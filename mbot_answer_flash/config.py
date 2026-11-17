"""Rutas, umbrales y constantes globales."""
import os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM_PATH = os.path.join(BASE, "memoria_v2.json")
MEM_V1 = os.path.join(BASE, "memoria.json")
DESC_PATH = os.path.join(BASE, "descubrimiento.json")
MAX_FRASES = 15
UMBRAL_EJECUTAR = 0.60
UMBRAL_PREGUNTAR = 0.30
PESO_CAPA = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.85, "E": 1.0, "S": 1.0, "P": 1.0}
S_BASE = 0.9               # tope de una coincidencia de marco; las inferencias distribucionales bajan de 0.6
TOPE_AYUDA = 0.50          # las descripciones de `help` nunca llegan a ejecutar
SEMIVIDA_REFUERZO = 30 * 86400
SEMIVIDA_RED = 180 * 86400

PELIGROSO = re.compile(r"\b(del|erase|rd|rmdir|format|shutdown|diskpart|bcdedit|cipher|takeown|icacls|taskkill|reg\s+delete)\b", re.I)
# un comando que SOLO abre una URL (sin metacaracteres de shell: espacio, & | < > ^ ") no es destructivo aunque la busqueda diga "del" o "format"
RE_START_URL = re.compile(r'''^start "" "https?://[A-Za-z0-9._~:/?#\[\]@!$()*+,;=%'-]+"$''')


def es_peligroso(cmd):
    return False if RE_START_URL.match(cmd) else bool(PELIGROSO.search(cmd))


FUSION = "max"             # "max": puntaje = max(peso*capa) + 0.1*segundo (actual) | "rrf": orden por Reciprocal Rank Fusion (experimento, bloque 3)
RRF_K = 60
