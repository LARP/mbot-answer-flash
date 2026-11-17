"""Clase Asistente: ensambla los mixins."""
import os

from .acciones import AccionesMixin
from .capas import CapasMixin
from .config import BASE, DESC_PATH, MEM_PATH
from .conversacion import Conversacion
from . import tools_locales  # noqa: F401  (registra las herramientas locales)
from . import documentos  # noqa: F401  (registra @leer @seccion @preguntar_doc @entidades @tabla y los lectores docx/xlsx/pptx/odt/ods/pdf)
from .herramientas import PLUGINS_DIR
from .descubrimiento import DescubrimientoMixin
from .explicacion import ExplicacionMixin
from .memoria import MemoriaMixin
from .personal import PERSONAL_PATH, Personal, PreferenciasMixin
from .planes import PlanesMixin
from .razonamiento import RazonamientoMixin
from .slots import AnalisisMixin, resolver_carpetas


class Asistente(MemoriaMixin, DescubrimientoMixin, AnalisisMixin, RazonamientoMixin, CapasMixin,
                ExplicacionMixin, PlanesMixin, PreferenciasMixin, AccionesMixin):
    def __init__(self, ruta=MEM_PATH, ruta_desc=DESC_PATH, auto_descubrir=True, silencioso=True,
                 reloj=None, ruta_personal=None, herramientas=True, plugins=PLUGINS_DIR):
        self.ruta, self.ruta_desc = ruta, ruta_desc
        if ruta_personal is None:           # memoria_v2.json -> personal.json; una memoria temporal -> <nombre>.personal.json
            ruta_personal = PERSONAL_PATH if ruta == MEM_PATH else os.path.splitext(ruta)[0] + ".personal.json"
        self.personal = Personal(ruta_personal, reloj)
        self.personal.tareas_fn = lambda: self.tareas
        self.carpetas = resolver_carpetas()
        def junto(sufijo, nombre):      # memoria real -> archivos de BASE; memoria temporal -> <nombre>.<sufijo>.json (aislados)
            return os.path.join(BASE, nombre) if ruta == MEM_PATH else os.path.splitext(ruta)[0] + "." + sufijo + ".json"
        ruta_k = os.path.join(BASE, "conocimiento.db") if ruta == MEM_PATH else os.path.splitext(ruta)[0] + ".conocimiento.db"
        self._init_acciones(junto("herramientas", "herramientas.json"), junto("ejecuciones", "ejecuciones.json"),
                            junto("notas", "notas.json"), herramientas, plugins, ruta_k)
        self._cache_an = {}
        self.ultima = None
        self.conv = Conversacion(self)           # capa K (conversacion); el reloj es el de `personal` (inyectable con A.conv.reloj)
        self._cargar_desc(auto_descubrir, silencioso)
        self._indexar_apps()
        self._cargar(ruta)
        self._indexar()
