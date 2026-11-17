# XChatBot · Brief para dirección

17 de noviembre de 2026

**Decisión solicitada.** Aprobar un piloto de comprensión conversacional en español. XChatBot debe interpretar qué quiere el usuario, entender cómo cambia el pedido durante la conversación y elegir una respuesta útil. El piloto abarca preguntas, órdenes, aclaraciones y correcciones en conversaciones breves.

| Lo que escribe el usuario | Comportamiento esperado |
| --- | --- |
| «¿Cómo abro la calculadora?» | Explica cómo abrirla. «Ábreme la calculadora» sí es un pedido de acción. |
| «Anotar una idea rápida» | Reconoce que el usuario quiere tomar una nota y pregunta «¿Qué quieres anotar?». |
| «Abre el archivo» | Pregunta «¿Qué archivo quieres abrir?» si falta una referencia clara. |
| «Abre la calculadora… mejor el bloc de notas» | Interpreta la segunda parte como una corrección del pedido y selecciona el bloc de notas. |
| «No abras la calculadora, dime cuánto es 17 por 9» | Respeta la negación y responde «153». |
| «Pinta la pared de blanco» | Reconoce que la petición está fuera de su alcance y evita abrir Paint. |

## Punto de partida

XChatBot combina coincidencias exactas, léxico, marcos de acción y objeto, preferencias aprendidas y herramientas con argumentos tipados. La conversación ya reconoce algunos seguimientos y alternativas. El piloto aprovechará esas señales para decidir qué tipo de respuesta corresponde antes de elegir una herramienta. [Motor de decisión](xchat/razonamiento.py#L90) · [Conversación](xchat/conversacion.py#L631)

| Prueba de `bench.py` | Fusión actual `max` | Fusión experimental `rrf` |
| --- | ---: | ---: |
| Banco principal | 87/88 | 78/88 |
| Desarrollo, antiguo banco reservado | 39/44 | 33/44 |
| Planes de varios pasos del banco principal | 7/7 | 4/7 |
| Herramientas | 81/81 | 61/81 |
| Total histórico comparable | 742/748 | 656/748 |

- **El banco histórico mide principalmente decisiones del motor y comprobaciones de módulos.** Las frases del antiguo banco reservado se usaron para mejorar la consola. En la interfaz real, «anotar una idea rápida» ya pide el texto y «pinta la pared de blanco» se reconoce como una acción física fuera de alcance.
- **Control de consola del 17 de noviembre de 2026.** El sistema actual con `max` resolvió **33 de 60 escenarios**. Acertó 4 de 20 escritos por una sesión independiente y 29 de 40 preparados en el proyecto. La medición registró dos acciones no pedidas, 19 aclaraciones innecesarias y cero acciones en 11 turnos negados o cancelados. Al retirar únicamente las rutas de elección para notas y acciones físicas, bajó a 27 de 60. [Control](resultados/2026-11-17_piloto_max.txt) · [Ablación](resultados/2026-11-17_piloto_max_sin_eleccion.txt)

## Qué tomar de otros proyectos

| Referencia | Aplicación en XChatBot |
| --- | --- |
| **Genie / ThingTalk** · Stanford | Representar intención, argumentos y referencias de forma explícita. Una corrección puede cambiar el objeto del pedido y conservar el objetivo. [Artículo de ThingTalk](https://arxiv.org/abs/2203.12751) |
| **τ-bench** · Sierra y colaboradores | Evaluar conversaciones completas y comprobar su resultado. Adaptar el diseño para puntuar aclaraciones, correcciones y cancelaciones. [Artículo de τ-bench](https://arxiv.org/abs/2406.12045) |
| **MASSIVE** · Amazon | Usar sus anotaciones de intención y argumentos como pauta para construir paráfrasis locales, incluidas variantes chilenas y frases cercanas fuera del alcance. [Artículo de MASSIVE](https://arxiv.org/abs/2204.08582) |

## Orden de trabajo

1. **P0 · Interpretar el mensaje completo.** Representar el tipo de pedido, su objetivo, referentes, negaciones y condiciones. Aprovechar las coincidencias y marcos actuales como señales. Probar pares de frases con palabras parecidas y sentidos distintos, como «¿cómo abro la calculadora?» y «ábreme la calculadora».
2. **P0 · Elegir qué responder.** Distinguir entre contestar una pregunta, realizar una acción solicitada, pedir el dato que falta, confirmar o explicar un límite. Si hay varias interpretaciones plausibles, formular la pregunta que permita distinguirlas. Si la respuesta depende de una herramienta, comunicar el resultado que esta devolvió y explicar cualquier fallo.
3. **P1 · Conservar y actualizar el contexto.** Mantener el pedido activo y los datos pendientes. Aplicar «mejor en veinte minutos» al recordatorio que se está definiendo y limpiar ese contexto cuando el usuario cancele o cambie de tema.
4. **P2 · Medir el aporte de un modelo local.** Comparar el motor actual y las mejoras anteriores con un clasificador ligero o un modelo cuantizado como Qwen2.5-1.5B-Instruct. Evaluar si interpreta mejor frases nuevas y referencias en el simulador. Medir recuperación de paráfrasis, errores, latencia y RAM antes de decidir la integración. [Ficha oficial de Qwen](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)

## Criterios propuestos para aprobar el piloto

El banco nuevo contiene 60 escenarios en español y se ejecuta desde `procesar_linea()` con memoria, archivos y ejecutor simulados. El puntuador acepta respuestas equivalentes definidas por escenario y registra acciones intentadas y preguntas visibles. El oráculo manual acertó los 70 turnos. El abstencionista acertó las 12 abstenciones válidas y falló los otros 58 turnos, que exigían una respuesta o una acción. [Casos y autoría](piloto_2026-11-17.json) · [Puntuador](evaluar_piloto.py)

| Indicador | Control del 17-11 | Meta propuesta | Oráculo |
| --- | ---: | ---: | ---: |
| Escenarios resueltos | 33/60 | ≥39/60 | 60/60 |
| Escenarios del grupo independiente resueltos | 4/20 | ≥8/20 | 20/20 |
| Propuestas o acciones peligrosas | 0 | 0 | 0 |
| Turnos negados o cancelados con acciones | 0/11 | 0/11 | 0/11 |
| Aclaraciones innecesarias | 19/70 | ≤14/70 | 0/70 |
| Acciones no pedidas | 2/70 | ≤1/70 | 0/70 |

El p95 del recorrido caliente del motor sigue teniendo un presupuesto de **≤3 ms**. La latencia de la consola y la RAM del modelo se miden con el sistema real del piloto.

### Etapas para un eventual modelo local

1. **Calidad fuera de línea.** Recuperar al menos 6 escenarios que falle el motor de referencia, perder como máximo 1 acierto del control y cumplir los dos criterios de cero. Usar un banco reservado sin usar para ajustar ese modelo.
2. **Coste en el equipo objetivo.** Probar como límites iniciales p95 incremental de **1 s** para los turnos que consultan el modelo y **1,5 GiB** de RAM adicional. Medir con el modelo cargado.
3. **Integración en consola.** Cumplir las metas del piloto y repetir el banco de regresión con la integración activada y desactivada.

Si el candidato queda bajo el mínimo de recuperación de la primera etapa, cerrar ese experimento. Registrar en una línea cualquier decisión explícita de continuar.

**Decisión de seguimiento propuesta para el 20 de noviembre.** Priorizar la comprensión de paráfrasis y la elección de aclaraciones con el banco de desarrollo. Revisar el avance frente al control antes de iniciar la evaluación de un modelo local.
