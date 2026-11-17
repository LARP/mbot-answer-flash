# mbot-answer-flash

Asistente local en español, **sin modelo de lenguaje**, que traduce frases a comandos de Windows y a herramientas internas. Razona con reglas, con una memoria que crece con el uso y con las notas y documentos que tú le indiques. Todo corre en tu PC, sin red ni claves, y usa solo la biblioteca estándar de Python.

Forma parte del ecosistema de Mbot (Marley Bot). Está pensado como motor de respuestas rápidas que no gasta LLM, pero **hoy funciona por sí solo, en consola**: la integración con Mbot todavía no está hecha (ver [Estado](#estado)).

## Qué hace

- **Entiende órdenes en lenguaje natural**: «abre la carpeta Música», «abre el bloc de notas y luego la calculadora», «cierra chrome».
- **Aprende de ti**: si no sabe una orden, le enseñas el comando y lo recuerda. Si se equivoca y le dices «no», baja la confianza de esa respuesta y reaprende.
- **Explica sus decisiones**: `!porque` muestra qué capas intervinieron y por qué eligió ese comando.
- **Pregunta antes de actuar** cuando no está seguro, y pide confirmación siempre que el comando es delicado. Las coincidencias dudosas solo preguntan, nunca ejecutan.
- **Busca en tus notas y documentos** (`.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.pdf`, texto) con un índice local, y responde preguntas sobre un documento: resumen, entidades (fechas, montos, correos, teléfonos, RUT, DNI, URLs) y columnas de tablas.
- **Conversa lo básico**: saludos, agradecimientos, «qué puedes hacer», seguimientos de los últimos turnos («otra vez», «y ahora X»).
- **Herramientas internas** que no pasan por el shell: hora, fecha, calculadora segura, espacio en disco, portapapeles, archivos, notas e información del sistema.

## Requisitos y uso

Windows y Python 3.12. No hay dependencias que instalar.

```bash
git clone https://github.com/LARP/mbot-answer-flash.git
cd mbot-answer-flash
python asistente.py
```

Escribe una frase y pulsa Intro. Las líneas que empiezan por `!` son comandos del propio asistente.

| Comando | Para qué sirve |
|---|---|
| `!lista` | Muestra lo que ha aprendido |
| `!aprender frase => comando` | Le enseñas un comando |
| `!olvidar N` | Borra una entrada aprendida |
| `!porque` | Explica la última decisión |
| `!descubrir` | Vuelve a leer accesos directos y aplicaciones de Windows |
| `!herramientas`, `!herramienta on\|off X` | Lista, activa o desactiva herramientas |
| `!historial` | Últimas ejecuciones |
| `!indexar <carpeta>`, `!reindexar`, `!fuentes`, `!desindexar <carpeta>` | Gestiona el índice de notas y documentos |
| `!buscar X` | Busca en el índice |
| `!yo` | Muestra lo que sabe de ti |
| `!salir` | Termina |

## Cómo razona

Cada frase se consulta en varias capas, que se fusionan en un puntaje de confianza:

| Capa | Idea |
|---|---|
| A. Exacta | La frase coincide con una ya aprendida |
| B. Huecos | Extrae rutas, URLs, números, carpetas y aplicaciones y los pone en la plantilla del comando |
| C. Similitud | Parecido ponderado por IDF, tolerante a erratas |
| D. Red de conceptos | Grafo de palabras y comandos que se construye solo |
| E. Windows | Accesos directos, App Paths y la salida de `help` de cmd (esta última solo pregunta) |
| F. Planes | «abre X y luego Y» en varios pasos con una sola confirmación |
| G. Refuerzo | Aciertos y fallos con memoria que se desvanece con el tiempo |
| H. Explicación | Cadena de razonamiento para `!porque` |
| K. Conversación | Charla básica y seguimientos |
| S. Semántica | Léxico de acciones y objetos para entender frases nuevas |

Con confianza alta ejecuta, en una zona intermedia pregunta y por debajo te pide que le enseñes. Los detalles están al inicio de [`mbot_answer_flash/__init__.py`](mbot_answer_flash/__init__.py).

## Seguridad

- Los comandos de borrado, formato, apagado y similares exigen confirmación.
- Las rutas se validan antes de proponer el comando; las no válidas se rechazan.
- Los lectores de documentos protegen contra ZIP bombs y contra XML con `DOCTYPE` o `ENTITY`.
- La calculadora usa una lista blanca de operaciones, no `eval`.
- Los plugins de usuario (carpeta `plugins/`) se ejecutan **sin sandbox**: instala solo código en el que confíes.

## Pruebas

```bash
python bench.py
```

El banco cubre reconocimiento, preferencias personales, seguridad, correcciones, conocimiento, documentos y conversación. Resultado actual: **776/782**. Las salidas de las evaluaciones de noviembre de 2026 están en [`resultados/`](resultados/).

## Datos

La memoria vive junto al código y **no se sube a git**: `memoria_v2.json`, `personal.json`, `notas.json`, `descubrimiento.json`, `ejecuciones.json`, `herramientas.json` y los `*.db`. Borrarlos deja el asistente como recién instalado.

## Estructura

```
asistente.py          lanzador de la consola
bench.py              banco de pruebas
evaluar_piloto.py     evaluación conversacional
mbot_answer_flash/    paquete con la lógica (capas, memoria, herramientas, documentos, conversación)
plugins/              plugins de usuario (ejemplo_dado.py)
docs/                 análisis de integración con Mbot
resultados/           salidas de las evaluaciones
CAMBIOS.md            historial de cambios
```

## Estado

- Antes se llamaba **xchat**. El paquete `xchat/` pasó a `mbot_answer_flash/` el 2026-11-17 sin cambiar su comportamiento.
- La integración como motor sin LLM de Mbot está analizada en [`docs/INTEGRACION_WIN_DIRECTOR.md`](docs/INTEGRACION_WIN_DIRECTOR.md) y aún no se ha empezado. Cuando se haga, solo **propondrá** comandos y será Mbot quien los ejecute, siempre con confirmación.
- Límites conocidos: es un sistema de reglas y no entiende cualquier frase; fuera de lo que ha aprendido o de sus herramientas, pregunta o pide que le enseñes. Funciona solo en Windows.
- Licencia: todavía sin definir.
