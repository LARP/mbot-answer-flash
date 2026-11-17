# Cambios de XChatBot

- **2026-11-17 · Nuevo nombre: mbot-answer-flash.** El paquete `xchat/` pasa a `mbot_answer_flash/` (mismo código, solo cambian importaciones y el nombre con que se presenta: «Soy mbot-answer-flash»). Bench antes y después: 776/782, idéntico. Carpeta del proyecto, lanzador `asistente.py` y formato de datos sin cambios. Respaldo previo: `D:/App/xchatbot_respaldos/xchatbot_antes_renombrar_20261117.zip`.
- **2026-11-17 · Evaluación conversacional.** Se creó un banco reservado de 60 escenarios, se validó el puntuador y se registró el control y su ablación. [Resultados](resultados/2026-11-17_piloto_max.txt)
- **2026-11-17 · Aprendizaje por corrección.** Se instrumentaron tres casos sintéticos de desarrollo para medir corrección, paráfrasis, intrusión y restauración. [Resultados](resultados/2026-11-17_aprendizaje_max.txt)

Las salidas del 17 de noviembre se obtuvieron con el código del commit `f1234cf` y fusión `max`. [Banco completo](resultados/2026-11-17_bench_max.txt) · [Medición concurrente](resultados/2026-11-17_bench_max_concurrente.txt)
