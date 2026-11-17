"""Lanzador delgado del Asistente CMD v2 (la logica vive en el paquete `mbot_answer_flash/`).

`python asistente.py` abre la consola. Tambien reexporta la API publica que usan bench.py y otros scripts.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mbot_answer_flash.config import *                                    # noqa: F401,F403  (rutas, umbrales, PELIGROSO)
from mbot_answer_flash.texto import *                                     # noqa: F401,F403
from mbot_answer_flash.texto import _palabra                              # noqa: F401
from mbot_answer_flash.refuerzo import fac_beta, decaer                   # noqa: F401
from mbot_answer_flash.lexico import *                                    # noqa: F401,F403
from mbot_answer_flash.slots import resolver_carpetas, An, _seguro, CHARS_PELIGRO, FOLDER_ALIAS   # noqa: F401
from mbot_answer_flash.red import Red                                     # noqa: F401
from mbot_answer_flash.memoria import SEMILLA, guardar_json               # noqa: F401
from mbot_answer_flash.descubrimiento import descubrir                    # noqa: F401
from mbot_answer_flash.razonamiento import Decision                       # noqa: F401
from mbot_answer_flash.nucleo import Asistente                            # noqa: F401
from mbot_answer_flash.ejecucion import ejecutar, completar, corregir, preguntar_comando, usar_ayuda, RE_NO   # noqa: F401
from mbot_answer_flash.ejecucion import ejecutar_ex, correr_cmd, EjecRes   # noqa: F401
from mbot_answer_flash.consola import main                                # noqa: F401

if __name__ == "__main__":
    main()
