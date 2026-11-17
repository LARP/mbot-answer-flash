"""
Paquete mbot_answer_flash (antes asistente.py monolitico). Asistente CMD v2: razonamiento basico SIN LLM (solo libreria estandar de Python).

Capas (se consultan en orden y se fusionan, ver `Asistente.decidir`):
  A  exacta/plantilla  frase normalizada == frase aprendida -> 1.0 (plantilla: 0.97).
  B  slots             extrae {ruta} {url} {host} {n} {texto} {carpeta} {app}; las tareas con hueco
                       (`taskkill /im {app}.exe`) se comparan con la frase ya "slotificada".
                       Induccion: dos frases que solo difieren en un slot, con comandos que difieren
                       en ese mismo valor, se fusionan en UNA tarea con hueco.
  C  IDF + typos       similitud Jaccard ponderada por IDF (la de la v1) para tareas sin hueco.
  D  red de conceptos  grafo palabra-palabra y palabra-comando que se construye solo; la activacion
                       se propaga 3 saltos con decaimiento y normalizacion por abanico (fan effect).
  E  Windows           accesos .lnk, App Paths y salida de `help` de cmd (cache en descubrimiento.json,
                       refresco con !descubrir). Las entradas de `help` SOLO preguntan, nunca ejecutan.
  F  planificacion     "abre X y luego Y" -> plan de varios pasos con UNA confirmacion.
  G  refuerzo          contadores aciertos/fallos (Beta) con semivida; "no"/"mal" penaliza y reaprende.
  H  explicabilidad    !porque muestra la cadena de razonamiento de la ultima decision.
  S  semantica         lexico de clases (ABRIR, BORRAR, DIBUJAR... / ARCHIVO, MUSICA, EQUIPO...) con raiz ligera;
                       cada frase = marco (ACCION, OBJETO, slots). Las tareas guardan marcos (semilla o aprendidos:
                       ensenar "quiero dibujar un gato" -> mspaint ensena (DIBUJAR,*) -> mspaint). Sitios web conocidos.
                       Similitud distribucional (coseno de segundo orden sobre la red D) para palabras desconocidas:
                       solo preguntan, nunca ejecutan. Los comandos peligrosos devuelven accion "confirmar".

Fusion: puntaje = max(peso_capa * s_capa) + 0.1 * segundo_mejor_puntaje_de_capa (tope 1.0),
multiplicado por el factor Beta de la tarea y por 0.2 si la frase fue vetada para esa tarea.

Bloque 2 (acciones confiables): herramientas.py (registro @herramienta, comandos internos "@hora" que se ejecutan en Python,
validacion de rutas con realpath, plugins en plugins/), tools_locales.py (hora, fecha, calculadora ast, disco, portapapeles,
archivos, notas, sistema), verificacion.py (tasklist/exists/returncode, inyectable), registro.py (ejecuciones.json, detector de
bucles), acciones.py (correr con validacion+verificacion+refuerzo G, planes-borrador con TTL de 2 min).
Comandos: !herramientas  !herramienta on|off X  !historial

Bloque 3 (conocimiento): conocimiento.py = indice SQLite FTS5 (conocimiento.db) de notas, hechos personales, tareas aprendidas y carpetas que
el usuario agrega; parser determinista de consulta ("frase", -excluir, ext:, en:, tiempo), ranking RRF (bm25 + titulo + recencia) y la herramienta
@buscar (reglas de desambiguacion en tools_locales.py). decidir() valida los comandos de archivos ANTES de pedir confirmacion (accion "rechazar").
Las rutas sin comillas con espacios se resuelven probando prefijos que existan (slots._extender_ruta). config.FUSION="max"|"rrf" (experimento).
Comandos: !indexar <carpeta>  !reindexar  !fuentes  !desindexar <carpeta>  !buscar X

Bloque 4 (documentos): documentos.py = lectores docx/xlsx/pptx/odt/ods/pdf con zipfile + xml.etree + zlib (registrados en conocimiento.LECTORES, asi
`!indexar` los incluye; troceo por titulos/diapositiva/hoja/pagina; proteccion contra ZIP bombs y XML con DOCTYPE/ENTITY), resumen extractivo
(TF-IDF por frases + posicion, o TextRank), preguntas sobre UN documento (BM25 en memoria), entidades por regex (fechas, montos, emails,
telefonos, RUT con digito verificador, DNI, URLs), operaciones sobre columnas (numeros es-CL/es-ES/en-US), clasificacion (`tipo:factura` en
@buscar) y estadisticas. Herramientas @leer @seccion @preguntar_doc @entidades @tabla. !porque dice que documento y seccion se usaron.
Preguntas abiertas: si decidir() termina en "ensenar" y la frase es una pregunta (qué/cuál/cuánto/dónde/cómo/cuándo/quién o '?'), la consola llama
a `Asistente.responder_pregunta(d)`, que consulta el indice FUERA de decidir() (una consulta FTS5 cuesta 1-10 ms y decidir() debe seguir < 3 ms)
y, si el mejor trozo tiene buen BM25 normalizado, contesta con la accion "responder" (nunca ejecuta nada). Un "ensenar" ya no arrastra un
comando de baja confianza (< 0.3): d.cmd queda en None y el candidato descartado va en d.descartado.

Bloque 5 (conversacion, capa K): conversacion.py = charla basica sin LLM, consultada DESPUES de decidir() y ANTES de pedir que enseñen un comando
(consola.procesar_linea): intenciones (saludo con hora y nombre, despedida, gracias, como estas, quien eres, "que puedes hacer" generado del registro
real, si/no sueltos, elogio, queja, risa, disculpa, "no se que hacer"), seguimientos con memoria de 5 turnos ("otra vez", "y ahora X", "la otra",
"¿por qué?"), y fallback inteligente (charla con sugerencias / orden desconocida con "¿Me enseñas el comando?" / "No entendí"). !porque explica tambien la capa K.

Comandos: !lista  !aprender frase => comando  !olvidar N  !descubrir  !porque  !salir
(la memoria v2 vive en memoria_v2.json; memoria.json de la v1 solo se lee para migrar).

Modulos: config, texto, refuerzo, lexico, slots, red, memoria, descubrimiento, capas, razonamiento,
explicacion, planes, personal, nucleo (Asistente), ejecucion, consola.
"""
