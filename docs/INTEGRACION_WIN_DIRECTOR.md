# mbot-answer-flash como plugin de WIN_DIRECTOR: análisis (2026-11-17)

Estudio hecho solo leyendo el código: no se ejecutó nada en ninguno de los dos proyectos y no se tocó WIN_DIRECTOR.
Respaldo previo de xchatbot: `D:\App\xchatbot_respaldos\xchatbot_20261117-1450.zip` (205 archivos).

## 1. Cómo funcionan hoy los plugins de WIN_DIRECTOR

- **Contrato.** El dataclass `Plugin` (`plugin_host.py:98`) tiene `id`, `name`, `instructions`, `handlers`, `validate` y los ganchos `prepare/begin/shortcut/end/on_help`. Es un contrato de **acciones del modo Computadora**, no del chat general.
- **Manifiesto.** Es `plugins/<id>/plugin.json` y lo valida `plugin_registro.validar_manifiesto`. Ejemplos: `plugins/pc_control/` y `plugins/unity/`.
- **Carga.** `plugin_host.load()` carga solo lo que está en `plugins_enabled` de `config.json`. El cargador **solo admite `tipo: integrado`** (`plugin_registro.py:318`). Los plugins locales (un proceso aparte por MCP) están diseñados (lotes 2-3), pero todavía no existen.
- **Sin modelo hoy.** `Plugin.shortcut` es el único punto que no usa modelo, y solo existe dentro del modo Computadora.
- **Chat.** `handle_chat` (`server.py:3520`) → `run_chat` → `_agent_loop` (`server.py:3728`) **siempre llama al modelo**. No hay gancho para resolver algo antes.
- **Herramientas MCP de plugins.** Solo se ofrecen con el motor claude sin bypass (`backends.mcp_plugins_activos`, `backends.py:249`).
- **Datos.** Van en `DATA_DIR\plugins\datos\<id>\` según el diseño (§9.2.2).
- **Reglas del diseño.** Tocar `server.py`, `web/index.html` o el instalador requiere tu autorización. Primero se trabaja en una copia, con respaldo y un commit por cambio, y no deben cambiar ni `tests/snapshot_protocolo_151.json` ni `ok.plugins`.

## 2. Tres formas de encajar mbot-answer-flash

| Opción | Qué es | A favor | En contra |
|---|---|---|---|
| **a. Motor sin LLM** | Un `mbot_answer_flash_backend.py` que se declara en `config.json` como otro backend de CLI, como claude o codex: recibe el prompt por stdin y responde por stdout (`backends._run_oneshot`, `backends.py:505`) | No toca `server.py`. Si responde con un bloque powershell, el host aplica `necesita_confirmacion` (`server.py:2357`) + `confirm_action`, es decir, toda la seguridad existente para Android y el túnel | El prompt trae todo el historial y el system prompt (hay que extraer el último mensaje). No recibe el id de la conversación. Arranca un proceso en cada turno |
| **b. Herramientas MCP** | mbot-answer-flash expone herramientas `mbot_answer_flash_*` | Reutiliza el registro de herramientas | No ahorra LLM: solo funciona si claude ya está corriendo. Requiere los plugins locales (lote 2, esfuerzo L) |
| **c. Filtro previo** | Un gancho `route(texto)` antes de `_agent_loop` que resuelve lo simple sin gastar LLM y deriva el resto al modelo | Es la opción que más ahorra LLM y la más rápida | Hay que tocar `server.py`, lo que requiere tu autorización |

**Recomendación:** empezar por **a**, que se puede hacer sin tocar `server.py` y reutiliza la seguridad, y validar con uso real. Si funciona, proponer **c** con un gancho genérico pequeño en `server.py`, como cambio aparte.

## 3. Qué duplica mbot-answer-flash y qué debería usar del host

| mbot-answer-flash | WIN_DIRECTOR | Decisión propuesta |
|---|---|---|
| `PELIGROSO`, `validar_comando`, confirmación por `input()` | `cmdrisk.py`, `confirm_action`, `aprobaciones.py` | Usar los del host; lo de mbot-answer-flash queda solo como rechazo previo |
| `ejecucion.py` (subprocess, cmd) | `tracked_powershell` / `run_powershell` | Delegar: mbot-answer-flash **propone** y el host ejecuta |
| `personal.json`, `notas.json` | `memoria.py` (SQLite FTS5) | Preferencias y notas en la memoria del host; el aprendizaje de comandos queda en mbot-answer-flash |
| Recordatorios propios | `scheduler.py` | Usar el scheduler del host |
| `conocimiento.db` | `memoria.py` | Por decidir: mantener separado o unificar |
| Control de mouse y teclado | `plugins/pc_control` | mbot-answer-flash no lo replica |

## 4. Lo que hace falta (S pequeño, M medio, L grande)

1. **API de turnos (M/L).** Quitar los ~69 `input()` y `print` de `consola.py`, `ejecucion.py` y `herramientas.py`. La entrada pasa a ser `turno(frase, estado) → {respuesta, propuesta_de_comando, pendiente}`, y las confirmaciones pendientes se guardan como estado serializable, no como diálogos bloqueantes. Es la base de todo lo demás y sirve también para la consola actual.
2. **Ejecución por el host (M).** `ejecucion.py` deja de usar subprocess y devuelve el comando. Hay que decidir entre traducir CMD a PowerShell o envolverlo en `cmd /c "..."` dentro del bloque powershell.
3. **Datos (S/M).** Hoy `mbot_answer_flash/config.py` usa la carpeta del código. Debe leer `MBOT_ANSWER_FLASH_DATA_DIR`, que apunte a `DATA_DIR\plugins\datos\mbot-answer-flash\`, y migrar la memoria actual una sola vez.
4. **Concurrencia (M).** Usar una instancia por conversación o un lock, escrituras JSON atómicas (ya existen en parte) y SQLite en modo WAL con `timeout`.
5. **Empaquetado (M).** Para la opción a: `mbot_answer_flash_backend.py` más una entrada en `config.json` y en los valores por defecto de `core.py`. Para la opción c (más adelante): `plugins/mbot_answer_flash/plugin.json` integrado, con herramientas `mbot_answer_flash_*`.
6. **Memoria y recordatorios (M).** Pasar las notas y preferencias a `memoria.py` y los recordatorios a `scheduler.py`. Una tarea desatendida nunca confirma por `input`.
7. **Pruebas (M).** Crear `tests/test_mbot_answer_flash_bench.py`, que corra `bench.py` con mundo simulado y un umbral (hoy 776/782, con 0 falsos positivos en el bench principal). Agregar una prueba del motor con CLI falsa (como `tests/fake_codex.py`) y la confirmación vía aprobaciones.
8. **Seguridad remota (M/L).** Android y el túnel envían frases que terminan en comandos en el PC. Reglas:
   - Nunca ejecutar sin confirmar cuando la orden viene de un cliente remoto o de un invitado (`motivo_confirmacion`, `server.py:2343`).
   - Respetar `history_tainted` y `cmdrisk.proteger`.
   - Los comandos "delicados" de mbot-answer-flash siempre pasan por `confirm_action`.

## 5. Decisiones pendientes (tuyas)

1. **¿Opción a o c?** Es decir, ¿un motor alternativo sin tocar `server.py` o ahorrar LLM tocándolo con tu autorización?
2. **¿Cuándo puede ejecutar mbot-answer-flash sin confirmación?** ¿Nunca dentro de WIN_DIRECTOR, o solo cuando el dueño escribe desde el PC con confianza alta?
3. **¿CMD o PowerShell?** ¿Traducir los comandos o aceptar `cmd /c`?
4. **¿Qué memoria manda?** ¿La memoria y los recordatorios de mbot-answer-flash pasan al host, o se mantienen separados?
5. **¿Integrado ahora o local después?** ¿Integrarlo ya como plugin integrado o esperar a los plugins locales (lote 2)?

## Notas de verificación

Un agente hizo el estudio y yo comprobé en el código las afirmaciones clave: el rechazo de `tipo: local` en `plugin_registro.py:318`, `Plugin.shortcut`, `_run_oneshot`, `handle_chat`, `_agent_loop` y `necesita_confirmacion`.

Corregí estos errores del informe original:
- WIN_DIRECTOR **sí** es un repositorio git en la raíz.
- Corrección posterior (2026-11-17): el bench de mbot-answer-flash da 776/782 (medido antes y después del renombrado); el 742/748 de este análisis era un dato erróneo.
- mbot-answer-flash no "ejecutó 6 comandos erróneos": hay 0 falsos positivos en el bench principal y 1 en el holdout («pinta la pared» → Paint).
