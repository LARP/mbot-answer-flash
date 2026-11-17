"""Lanzador delgado del Asistente CMD v2 (la logica vive en el paquete `xchat/`).

`python asistente.py` abre la consola. Tambien reexporta la API publica que usan bench.py y otros scripts.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xchat.config import *                                    # noqa: F401,F403  (rutas, umbrales, PELIGROSO)
from xchat.texto import *                                     # noqa: F401,F403
from xchat.texto import _palabra                              # noqa: F401
from xchat.refuerzo import fac_beta, decaer                   # noqa: F401
from xchat.lexico import *                                    # noqa: F401,F403
from xchat.slots import resolver_carpetas, An, _seguro, CHARS_PELIGRO, FOLDER_ALIAS   # noqa: F401
from xchat.red import Red                                     # noqa: F401
from xchat.memoria import SEMILLA, guardar_json               # noqa: F401
from xchat.descubrimiento import descubrir                    # noqa: F401
from xchat.razonamiento import Decision                       # noqa: F401
from xchat.nucleo import Asistente                            # noqa: F401
from xchat.ejecucion import ejecutar, completar, corregir, preguntar_comando, usar_ayuda, RE_NO   # noqa: F401
from xchat.ejecucion import ejecutar_ex, correr_cmd, EjecRes   # noqa: F401
from xchat.consola import main                                # noqa: F401

if __name__ == "__main__":
    main()
