"""Plugin de ejemplo: la herramienta @dado ("tira un dado", "lanza un dado de 20 caras").

Como escribir un plugin
-----------------------
1. Crea un archivo .py en esta carpeta (plugins/). Los archivos que empiezan por "_" se ignoran.
2. Importa el decorador y registra una funcion:

       from xchat.herramientas import herramienta, Resultado

       @herramienta(
           "dado",                                  # nombre: se invoca como comando interno @dado
           verbos=("tira", "lanza", "tirar", "lanzar"),   # clases del lexico (ABRIR, BUSCAR...) o palabras sueltas
           objetos=("dado",),                       # idem para el objeto de la frase
           slots={"caras": ("n", 6)},               # {nombre: tipo}; (tipo, defecto) = opcional con valor por defecto;
                                                    # "carpeta"/"ruta"/"n"/"texto"/"patron"/"expresion"/"unidad"; "texto?" = opcional
           relleno=("caras",),                      # palabras sueltas que la herramienta tolera (si no, "dado de 20 caras" no se elige)
           peligro=False,                           # True -> siempre pide confirmacion
           requiere=(),                             # ("bin:programa", "mod:modulo", "os:win") -> estado 'necesita configuracion'
           descripcion="tira un dado",
       )
       def dado(ctx, caras):                        # ctx: reloj, runner, disk_usage... (inyectables); slots como argumentos
           ...
           return Resultado(True, "Salio 4", {"valor": 4})   # o simplemente un str

3. Arranca el asistente (o `!herramientas` para ver que cargo). Con `!herramienta off dado` se desactiva (se guarda).

OJO: un plugin es codigo Python con tus mismos permisos; solo copia aqui plugins que hayas leido. Si falla al importar,
el asistente lo ignora y `!herramientas` muestra el error.
"""
import random

from xchat.herramientas import Resultado, herramienta


@herramienta("dado", verbos=("tira", "lanza", "tirar", "lanzar"), objetos=("dado",), slots={"caras": ("n", 6)},
             relleno=("caras", "cara", "lados"),           # palabras que el plugin entiende: "tira un dado de 20 caras"
             descripcion="tira un dado (plugin de ejemplo): 'tira un dado'")
def dado(ctx, caras=6):
    v = random.randint(1, max(2, int(caras)))
    return Resultado(True, f"Salio {v} (dado de {caras} caras).", {"valor": v})
