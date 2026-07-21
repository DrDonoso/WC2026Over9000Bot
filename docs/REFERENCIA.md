# REFERENCIA TÉCNICA — WorldCup2026 Over9000 Bot

> **Propósito:** Cuando en ~2 años retomes este proyecto para el siguiente torneo, este documento te explica con detalle qué hacía cada comando, cada job en segundo plano, cada subsistema y cada variable de entorno.  
> Es el compañero técnico del `README.md`, que enlaza aquí para quien quiera profundizar.  
> Asume que has olvidado todos los detalles de implementación.

---

## Tabla de Contenidos

1. [Comandos de usuario](#1-comandos-de-usuario)
   - [/start](#11-start)
   - [/help](#12-help)
   - [/clasificacion](#13-clasificacion)
   - [/actual y /porra](#14-actual-y-porra)
   - [/general](#15-general)
   - [/evolucion](#16-evolucion)
   - [/estadisticas](#17-estadisticas)
   - [/listaaciertos](#18-listaaciertos)
   - [/listaaciertosactual](#19-listaaciertosactual)
   - [/endirecto](#110-endirecto)
   - [/hoy](#111-hoy)
   - [/ayer](#112-ayer)
   - [/siguiente](#113-siguiente)
   - [/elecciones](#114-elecciones)
   - [/mispredicciones](#115-mispredicciones)
   - [/participantes](#116-participantes)
   - [/tongo](#117-tongo)
2. [Comandos ocultos / admin](#2-comandos-ocultos--admin)
   - [/simulagol](#21-simulagol)
   - [/updatediario](#22-updatediario)
   - [/recalcular](#23-recalcular)
   - [/tongocheck](#24-tongocheck)
   - [/evilsanchez](#25-evilsanchez)
   - [/granfinal](#26-granfinal)
   - [/calcularperfiles](#27-calcularperfiles)
   - [/perfil](#28-perfil)
3. [Jobs / tareas en segundo plano](#3-jobs--tareas-en-segundo-plano)
   - [poll_goals_job](#31-poll_goals_job)
   - [poll_thread_goals_job](#32-poll_thread_goals_job)
   - [poll_kickoff_job](#33-poll_kickoff_job)
   - [poll_finished_matches_job](#34-poll_finished_matches_job)
   - [poll_goal_clips_job](#35-poll_goal_clips_job)
   - [poll_final_ceremony_job](#36-poll_final_ceremony_job)
   - [daily_update_job](#37-daily_update_job)
   - [rich_image_job](#38-rich_image_job)
   - [history_backfill_job](#39-history_backfill_job)
   - [profile_update_job](#310-profile_update_job)
   - [revive_inactive_job](#311-revive_inactive_job)
4. [Subsistemas — mapa de módulos](#4-subsistemas--mapa-de-módulos)
   - [api/](#41-api)
   - [porra/](#42-porra)
   - [reddit/](#43-reddit)
   - [espn/](#44-espn)
   - [tve.py](#45-tvepy)
   - [ai/](#46-ai)
   - [chat/](#47-chat)
   - [bot/](#48-bot)
   - [config.py](#49-configpy)
5. [Modelo de puntuación de la porra](#5-modelo-de-puntuación-de-la-porra)
6. [Ficheros de datos y formatos](#6-ficheros-de-datos-y-formatos)
7. [Catálogo completo de variables de entorno](#7-catálogo-completo-de-variables-de-entorno)
8. [Notas operativas / gotchas para el yo del futuro](#8-notas-operativas--gotchas-para-el-yo-del-futuro)

---

## 1. Comandos de usuario

Estos comandos se muestran en `/start` y `/help` y son accesibles para todos los miembros del grupo.  
Fuente de registro: `src/worldcup_bot/__main__.py` líneas ~2710-2743 (`handlers` list).  
Implementaciones: `src/worldcup_bot/bot/handlers.py`.

---

### 1.1 `/start`

**Nombre exacto:** `start` — sin aliases.

**Qué hace:**  
Muestra el mensaje de bienvenida estático con la lista de todos los comandos públicos. Es el primer punto de contacto para usuarios nuevos.

**Argumentos:** ninguno.

**Formato de salida:** texto plano (Markdown simple). Un bloque de texto con los comandos listados, sin parse_mode especial.

**Comportamiento interno:**  
Llama directamente a `update.message.reply_text(_HELP_COMMANDS)`. El texto `_HELP_COMMANDS` es una constante definida en `handlers.py`. No llama a ninguna API.

---

### 1.2 `/help`

**Nombre exacto:** `help` — sin aliases.

**Qué hace:**  
Muestra el mismo mensaje de bienvenida que `/start` más una sección adicional explicando el **sistema de puntuación** de la porra (grupos + eliminatorias).

**Argumentos:** ninguno.

**Formato de salida:** texto HTML (parse_mode="HTML"). La sección de puntuación está generada dinámicamente desde las constantes `GROUP_SCORING` y `KNOCKOUT_STAGES` de `data/stages.py`, lo que garantiza que la explicación siempre refleje los puntos reales configurados.

**Comportamiento interno:**  
`_points_help_text()` itera sobre `KNOCKOUT_STAGES` para construir la lista dinámica de puntos por ronda. El número de puntos por fase se lee en tiempo de ejecución, no está hardcodeado en el texto.

---

### 1.3 `/clasificacion`

**Nombre exacto:** `clasificacion` — sin aliases.

**Qué hace:**  
Muestra la tabla de posiciones de los grupos del torneo tal como las reporta football-data.org. Marca con emoji los equipos actualmente en partido en directo.

**Argumentos:**  
- Sin argumento: muestra todos los grupos (A–L).  
- Con una letra: `/clasificacion L` → solo el Grupo L.  
- Letras válidas: A–L (los 12 grupos del Mundial 2026). Si se pasa una letra no válida, responde con un mensaje de error.

**Formato de salida:** texto plano. Usa `format_standings()` del módulo `bot/formatters.py`.

**Comportamiento interno:**  
Llama a `client.get_standings()` y `client.get_live_matches()` (con caché TTL). Los equipos cuyos TLAs aparezcan en un partido en directo se marcan visualmente. El argumento de grupo se parsea buscando el primer token que sea una sola letra dentro del rango A–L.

---

### 1.4 `/actual` y `/porra`

**Nombres exactos:** `actual` (comando principal), `porra` (alias exacto — mismo handler).

**Qué hace:**  
Muestra la clasificación **provisional** de la porra con todos los puntos acumulados hasta el momento (incluyendo grupos no cerrados, resultados parciales, etc.). Lema: "a día de hoy".

**Argumentos:** ninguno.

**Formato de salida:**  
1. **Preferente:** imagen de podio renderizada (`bot/podium_image.py`) con los top-3 como foto, más texto como caption.  
2. **Fallback (álbum):** si el podio falla, intenta un álbum de fotos de los top-3 descargadas de `PHOTO_BASE_URL/{username}.jpg`.  
3. **Fallback final:** texto HTML puro.

**Comportamiento interno:**  
Llama a `engine.compute_general_ranking(predictions, client, official=False)`. El parámetro `official=False` incluye grupos en curso. Si `predictions.yml` no está cargado, responde con un mensaje de error amigable.

---

### 1.5 `/general`

**Nombre exacto:** `general` — sin aliases.

**Qué hace:**  
Muestra la clasificación **oficial** de la porra, contando únicamente los grupos ya cerrados y las rondas eliminatorias ya disputadas. Más conservadora que `/actual`.

**Argumentos:** ninguno.

**Formato de salida:** igual que `/actual` (podio → álbum → texto), más un pie de página que indica cuántos grupos de 12 están cerrados y un aviso si la clasificación es incompleta.

**Comportamiento interno:**  
Llama a `engine.compute_general_ranking(predictions, client, official=True)` y a `client.get_finished_groups()` para calcular el footer. Cuando todos los grupos están cerrados, el footer desaparece.

---

### 1.6 `/evolucion`

**Nombre exacto:** `evolucion` — sin aliases.

**Qué hace:**  
Envía un **gráfico de líneas / bump-chart** (imagen PNG) mostrando la evolución de la clasificación de la porra jornada a jornada desde el primer partido del torneo.

**Argumentos:** ninguno.

**Formato de salida:** foto con caption `"📈 Evolución de la porra"`.

**Comportamiento interno:**  
Carga el histórico desde `{STATE_DIR}/porra_history.json` (construido por `history_backfill_job`). Si el histórico está vacío (torneo no empezado), responde con un texto informativo. El gráfico se renderiza en `porra/chart.py` con `render_evolution_png()` y se guarda temporalmente en `{STATE_DIR}/evolucion.png` antes de enviarse.

---

### 1.7 `/estadisticas`

**Nombre exacto:** `estadisticas` — sin aliases.

**Qué hace:**  
Muestra un ranking de quién ha visto más clips de goles usando el botón **"Ver gol"** (la funcionalidad inline de visualización de vídeos).

**Argumentos:** ninguno.

**Formato de salida:** texto HTML con lista numerada: `1. <Nombre> — N`.

**Comportamiento interno:**  
Lee `{STATE_DIR}/vergol_stats.json` y llama a `_vs_leaderboard()`. Si nadie ha pulsado "Ver gol" todavía, responde con un mensaje indicando que no hay estadísticas.

---

### 1.8 `/listaaciertos`

**Nombre exacto:** `listaaciertos` — sin aliases.

**Qué hace:**  
Muestra el detalle de aciertos/fallos **oficial** de un participante: solo cuentan grupos cerrados y rondas eliminatorias disputadas.

**Argumentos:**  
- Sin argumento: muestra los aciertos del propio usuario (requiere tener @username en Telegram).  
- `@usuario` o nombre de display: muestra los aciertos de ese participante.  
  Ejemplo: `/listaaciertos @drdonoso` o `/listaaciertos DavidR`.

**Formato de salida:** texto HTML con el desglose por grupo (posiciones predichas vs reales, puntos) y por fase eliminatoria.

**Comportamiento interno:**  
Llama a `engine.compute_user_detail(username, predictions, client, official=True)`. La resolución de nombre sigue esta prioridad: (1) self si no hay argumento, (2) búsqueda directa por username, (3) búsqueda por `display_name`. Si el usuario no tiene @username en Telegram, muestra un error.

---

### 1.9 `/listaaciertosactual`

**Nombre exacto:** `listaaciertosactual` — sin aliases.

**Qué hace:**  
Igual que `/listaaciertos` pero en modo **provisional** — incluye resultados de grupos en curso.

**Argumentos:** Mismos que `/listaaciertos`.

**Formato de salida:** Mismo formato HTML que `/listaaciertos`.

**Comportamiento interno:**  
Misma lógica que `/listaaciertos` pero con `official=False` en `compute_user_detail`.

---

### 1.10 `/endirecto`

**Nombre exacto:** `endirecto` — sin aliases.

**Qué hace:**  
Muestra el estado en tiempo real de los partidos actualmente en directo. Si la IA está configurada y hay un hilo de Reddit para el partido, muestra un resumen enriquecido con: marcador, minuto, goles, tarjetas, alineación y cambios — con botones inline para revelar cada sección. También incluye el bloque "⚔️ ¿Con quién vas?" (qué miembros de la porra apoyan a cada equipo).

**Argumentos:** ninguno.

**Formato de salida:**  
- **Con IA:** texto con resumen del partido + teclado inline con botones: `⚽ Goles`, `🟨 Tarjetas`, `📋 Alineación`, `🔄 Cambios`. Hasta 4 partidos simultáneos.  
- **Sin IA o sin hilo Reddit:** texto simple con marcador y tiempo.

**Comportamiento interno:**  
Llama a `client.get_live_matches()`. Para cada partido (hasta 4), intenta encontrar el hilo de Reddit via `scanner.find_thread_permalink()` (primero caché `/new/`) o `scanner.find_match_thread()` (búsqueda). Con el cuerpo del hilo llama a `extract_match_events()` (AI) para extraer el resumen. El estado del mensaje enriquecido se guarda en `{STATE_DIR}/endirecto.json` con un token único para que los callbacks inline puedan recuperarlo. Los botones inline tienen tres patrones de callback: `ed|{token}|{code}` (secciones), `edgol|{token}|{idx}` (gol individual), `vergol:{token}` (clip de vídeo).

**Gotcha:** si se llama cuando no hay partidos en directo, responde "No hay partidos en directo en este momento."

---

### 1.11 `/hoy`

**Nombre exacto:** `hoy` — sin aliases.

**Qué hace:**  
Lista los partidos de **la jornada activa** (ventana de 09:00 a 09:00 del día siguiente, configurable con `FOOTBALL_DAY_START_HOUR`). Si todos los partidos de hoy ya han terminado, avanza automáticamente hasta el siguiente día con partidos pendientes (hasta +14 días). Añade el marcador `📺 La 1` o `📺 Teledeporte` cuando el partido se emite en RTVE (requiere `TVE_ENABLED=1`).

**Argumentos:** ninguno.

**Formato de salida:** texto plano. Cabecera con el rango horario, después una línea por partido.

**Comportamiento interno:**  
Itera `get_football_day_matches(timezone, offset, anchor_hour)` con offset 0..14 buscando el primer offset con al menos un partido no-FINISHED. Carga el calendario de RTVE desde `tve.py` para añadir la etiqueta de canal. Si el offset seleccionado es >0, cambia el header a "ya acabaron los de hoy, estos son los próximos".

---

### 1.12 `/ayer`

**Nombre exacto:** `ayer` — sin aliases.

**Qué hace:**  
Muestra los resultados de **la jornada anterior** (ventana 09:00–09:00 del día de ayer).

**Argumentos:** ninguno.

**Formato de salida:** texto plano con resultados. Cabecera con el rango horario.

**Comportamiento interno:**  
Llama a `get_football_day_matches(timezone, -1, anchor_hour)`. No añade etiquetas RTVE (ya pasaron los partidos).

---

### 1.13 `/siguiente`

**Nombre exacto:** `siguiente` — sin aliases.

**Qué hace:**  
Muestra el **próximo partido** programado (el primero con estado TIMED/SCHEDULED, convertido a hora local). Incluye etiqueta RTVE si aplica.

**Argumentos:** ninguno.

**Formato de salida:** texto plano de una línea: flags, equipos, fecha/hora local, opcionalmente el canal RTVE.

**Comportamiento interno:**  
Llama a `client.get_next_match(timezone)`. Convierte la fecha UTC del partido a la zona horaria configurada (`TIMEZONE`).

---

### 1.14 `/elecciones`

**Nombre exacto:** `elecciones` — sin aliases.

**Qué hace:**  
Muestra las predicciones de **todos los participantes** para una fase concreta, con un menú de fases inline. Permite ver quién eligió qué equipo en cada ronda. Cuando una fase se acerca (< 2 horas), muestra un "nudge" con quién aún no tiene predicciones para esa fase.

**Argumentos:** ninguno (la fase se selecciona mediante botones inline).

**Formato de salida:**  
- Modo `CHOICES_TYPE=text` (defecto): varios mensajes de texto HTML divididos si superan el límite de Telegram (3800 chars).  
- Modo `CHOICES_TYPE=image`: imagen PNG generada con tiles de banderas.  
El teclado inline ofrece una fila de botones por fase: Grupos, Dieciseisavos, Octavos, Cuartos, Semifinales, 3.º y 4.º, Final.

**Comportamiento interno:**  
El handler principal (`cmd_elecciones`) registra un callback (`cmd_elecciones_callback` con patrón `^elecciones\|`). Cada fase tiene un artefacto cacheado en `bot_data["elecciones_cache"]` (hasta 6 entradas, máx. `_MAX_ELECCIONES_CACHE`) invalidado por mtime del predictions.yml + hash del estado del cuadro eliminatorio (parings + ganadores de cada fase). Esto evita redibujar la imagen o reconstruir el texto en cada tap.

---

### 1.15 `/mispredicciones`

**Nombre exacto:** `mispredicciones` — sin aliases.

**Qué hace:**  
Muestra las predicciones del usuario que invoca el comando: grupos (con flags) y todas las rondas eliminatorias.

**Argumentos:** ninguno (solo funciona para el propio usuario; requiere @username en Telegram).

**Formato de salida:** texto Markdown. Sección "Grupos" con una línea por grupo, y sección "Eliminatorias" con una línea por fase.

**Comportamiento interno:**  
Lee directamente de `predictions.yml` sin llamar a la API. Los TLAs `**` se muestran tal cual (no se intentan resolver). Solo funciona si el caller tiene @username; si no, responde con `_MSG_NO_USERNAME`.

---

### 1.16 `/participantes`

**Nombre exacto:** `participantes` — sin aliases.

**Qué hace:**  
Lista todos los participantes registrados en `predictions.yml`, con su @username y display_name (si tienen).

**Argumentos:** ninguno.

**Formato de salida:** texto HTML. Una línea por participante: `• @username (Nombre)` o `• @username` si no hay display_name.

**Comportamiento interno:**  
Lee directamente de `predictions.yml`. Ordena alfabéticamente por username. No llama a la API.

---

### 1.17 `/tongo`

**Nombre exacto:** `tongo` — sin aliases.

**Qué hace:**  
Easter egg del grupo. Cuando alguien reclama que hay "tongo" en los resultados, el bot responde con una frase aleatoria del pool de frases cargado de `TongoUsers.yml`. Con probabilidad 1/3 responde "Sanchez ens roba" (frase especial hardcodeada). Puede enviar un GIF animado si hay GIFs en `tongo_gifs/`. Soporta reply-targeting: si `/tongo` se usa como respuesta a otro mensaje y una frase usa `{{reply_to_*}}`, el bot elige frases que mencionan al objetivo.

**Argumentos:** ninguno (pero puede usarse como respuesta a otro mensaje).

**Formato de salida:**  
- **GIF:** si hay archivos en `tongo_gifs/`, puede enviar un `.gif` o `.mp4` animado.  
- **Texto:** una frase del pool, renderizada con las variables de plantilla del invoker y del destinatario del reply.

**Comportamiento interno:**  
Carga `TongoUsers.yml` con hot-reload (caché por mtime). Construye un `TongoContext` con los datos del usuario (first_name, username, etc.) y del mensaje respondido. Elige una respuesta con `choose_tongo_response()`. Si el archivo no está disponible o tiene errores YAML, responde con un error y sugiere usar `/tongocheck`.

**Variables de plantilla disponibles:** `{{first_name}}`, `{{last_name}}`, `{{full_name}}`, `{{username}}`, `{{id}}`, `{{reply_to_first_name}}`, `{{reply_to_last_name}}`, `{{reply_to_full_name}}`, `{{reply_to_username}}`, `{{reply_to_id}}` — 10 variables en total.

**Overrides por usuario en TongoUsers.yml:** `sanchez_ratio`, `phrases_mode` (`append`/`replace`), `phrases` propias.

---

## 2. Comandos ocultos / admin

⚠️ **ADVERTENCIA CRÍTICA:** Estos comandos **NO están listados** en `/start` ni en `/help`. Sin embargo, **no hay ninguna autenticación de admin** — cualquier miembro del grupo que conozca el nombre puede invocarlos. Si en el futuro hay usuarios en el grupo que no sean de confianza, considera añadir una verificación de `user_id` o moverlos a un chat privado.

---

### 2.1 `/simulagol`

**Qué hace:**  
Dispara una **notificación de gol simulada** con un gol aleatorio extraído de un hilo de Reddit de un partido ya terminado del torneo. Si no encuentra ninguno, usa un gol de fallback hardcodeado (Gyökeres, Suecia 3-1 Túnez). Útil para probar la pipeline de notificaciones de gol y la búsqueda de clips de vídeo.

**Por qué está oculto:** comando de test; no tiene utilidad para usuarios normales.

**Comportamiento:** Crea una entrada en el clip-store con `status='searching'` para que `poll_goal_clips_job` busque el clip y añada el botón "Ver gol" una vez encontrado.

---

### 2.2 `/updatediario`

**Qué hace:**  
Dispara manualmente el **resumen diario de IA** (el mismo que `/daily_update_job` envía automáticamente cada día a la hora configurada). Envía el texto al chat actual (no al grupo, para poder probarlo). Requiere que `OPENAI_*` esté configurado.

**Por qué está oculto:** útil para testear el resumen antes de que se publique automáticamente.

---

### 2.3 `/recalcular`

**Qué hace:**  
Recalcula el histórico de puntuación de la porra **desde cero** (`force=True`), sobreescribiendo `porra_history.json`. Necesario si se cambian las reglas de puntuación o se corrige un bug de scoring, para que `/evolucion` refleje los puntos correctos.

**Por qué está oculto:** operación destructiva de caché; no tiene sentido exponer al usuario final.

---

### 2.4 `/tongocheck`

**Qué hace:**  
Valida `TongoUsers.yml` y reporta el resultado en Telegram: ✅ OK o ❌ con detalle del error. Útil para depurar errores de YAML sin tener que mirar los logs del servidor.

**Por qué está oculto:** utilidad de diagnóstico, no relevante para el grupo.

---

### 2.5 `/evilsanchez`

**Qué hace:**  
Dispara manualmente el job de evolución de la **imagen "rich"** (el mismo que `rich_image_job` ejecuta automáticamente cada día a `RICH_IMAGE_HOUR`). Hace la iteración completa: busca ganadores de ayer → genera imagen evolucionada → la envía al grupo. Requiere que la IA de imágenes esté configurada (`OPENAI_IMAGE_*`).

**Por qué está oculto:** fallback manual en caso de que el job automático no haya corrido.

---

### 2.6 `/granfinal`

**Qué hace:**  
Dispara manualmente la **ceremonia de la Final** del torneo:  
- Si el partido de la Final aún no ha terminado: envía la pieza pre-final (hype + clasificación snapshot + bloque ⚔️ cara a cara).  
- Si la Final ya está FINISHED: envía el anuncio del campeón + clasificación oficial final + imagen de podio.

**Por qué está oculto:** fallback manual en caso de que `poll_final_ceremony_job` no haya disparado la ceremonia automáticamente.

---

### 2.7 `/calcularperfiles`

**Qué hace:**  
Dispara manualmente el job de actualización de perfiles de usuario para la feature **picante** (el mismo que `profile_update_job` ejecuta a las 04:00). Lee los mensajes nuevos del timeline desde `last_run`, hace una llamada de IA y actualiza `picante_profiles.json`. Requiere `PICANTE_PROFILES_ENABLED=1`.

**Por qué está oculto:** utilidad de mantenimiento de la feature de perfiles.

---

### 2.8 `/perfil`

**Nombre exacto:** `perfil`.

**Qué hace:**  
Inspecciona el perfil auto-aprendido de un participante para la feature picante. Sin argumento, muestra un teclado inline con todos los perfiles disponibles. Con argumento `@usuario`, muestra directamente ese perfil: rasgos, equipo, motes, temas, tono, piques recientes y fecha de última actualización.

**Por qué está oculto:** utilidad de diagnóstico para la feature de perfiles.

---

## 3. Jobs / tareas en segundo plano

Los jobs se registran en `main()` dentro de `src/worldcup_bot/__main__.py`. Todos usan la cola de jobs de `python-telegram-bot` (`job_queue`).

---

### 3.1 `poll_goals_job`

**Cadencia:** cada `GOAL_POLL_INTERVAL_SECONDS` (defecto: **60 segundos**), primer disparo a los 10 s.

**Qué hace:**  
Detecta nuevos goles comparando el marcador de la API de football-data.org con el estado guardado (`live_scores.json`). Fuente **oficial** de la puntuación. Para cada partido relevante (IN_PLAY, PAUSED, o TIMED/SCHEDULED dentro de la ventana de 4h):

1. Lee el estado guardado (`scores[match_key]`).  
2. Llama a `reconcile()` para calcular deltas (goal/disallowed/catchup).  
3. **Dentro del `goal_lock`** (asyncio.Lock compartido con `poll_thread_goals_job`): reclama el marcador nuevo atómicamente.  
4. **Fuera del lock:** enriquece el gol (busca nombre del goleador + minuto vía Reddit + OpenAI) y envía la notificación al grupo.

**Dedup / VAR:**  
- Los goles anulados (score baja) generan un mensaje de "⚽ GOL ANULADO".  
- Si el bot arrancó con el partido ya en marcha (non-zero score al first-seed), intenta recuperar los goles perdidos desde el hilo de Reddit (`_attempt_goal_recovery`), o envía un catch-up neutral.  
- Evicción automática de partidos terminados hace > 4h (`MATCH_OVER_AGE`).  
- Evicción de partidos `POSTPONED`/`SUSPENDED` que quedaron en el estado.

**Estado persistido:** `{STATE_DIR}/live_scores.json`

---

### 3.2 `poll_thread_goals_job`

**Cadencia:** cada **25 segundos**, primer disparo a los 25 s.

**Qué hace:**  
Detecta goles **antes** que football-data.org consultando directamente los hilos de Reddit de los partidos en directo. Fuente **complementaria y early-detection**. Opera en todos los partidos ya sembrados en `live_scores` por `poll_goals_job`.

**Dedup compartido con `poll_goals_job`:**  
- Comparte el mismo `goal_lock` y el mismo estado `live_scores` (announced).  
- Cada fuente mantiene su propio `seen` en memoria (`seen_scores["api"]` y `seen_scores["thread"]`).  
- El primero en detectar un gol lo reclama dentro del lock; el otro ve `new_ann` ya actualizado y `reconcile()` devuelve delta vacío → no se duplica.

**VAR real (hilo propio):**  
- Si el hilo de Reddit baja su puntuación (VAR propio), genera un disallowed.  
- **Bug 3 fix:** el score del disallowed se clampea a `announced−1` por lado para evitar que un under-read momentáneo del hilo muestre un marcador incorrecto.

**Scorer backfill (Bug 2 fix):**  
En cada tick, independientemente de si hay nuevos goles, llama a `_backfill_scorer_in_clip_store()` para rellenar el nombre del goleador en entradas del clip-store que habían quedado sin él (por 429 o lag del hilo al momento del anuncio).

**Estado persistido:** `{STATE_DIR}/live_scores.json`

---

### 3.3 `poll_kickoff_job`

**Cadencia:** cada **30 segundos**, primer disparo a los 20 s.

**Qué hace:**  
Envía el mensaje 🟢 **"¡Empieza el partido!"** con la formación de la porra (⚔️ ¿Con quién va la porra?) exactamente una vez por partido, cuando el kickoff programado llega.

**Seed en primer run:** marca como anunciados todos los partidos cuyo kickoff ya pasó o que ya están IN_PLAY/PAUSED/FINISHED, para no spamear al arrancar.

**Grace window:** un partido no anunciado cuyo kickoff fue hace más de 30 min se marca silenciosamente sin enviar mensaje (protege contra arranques tardíos).

**Acción adicional importante:** siembra el marcador 0-0 en `live_scores` para ese partido, así `poll_goals_job` verá una transición 0→1 correcta en lugar de disparar el catch-up de "score non-zero al first-see".

**Estado persistido:** `{STATE_DIR}/kickoff_announced.json`

---

### 3.4 `poll_finished_matches_job`

**Cadencia:** cada `FINISHED_POLL_INTERVAL_SECONDS` (defecto: **120 segundos**), primer disparo a los 15 s.

**Qué hace:**  
Detecta partidos recién terminados y envía el **recap oficial**: estadísticas del partido (vía ESPN API) + comentario de porra (IA) + resultado final. También gestiona el caso especial del **final provisional** (partido bloqueado en IN_PLAY > 4h por el retraso del free tier de football-data).

**Dos tracks de dedup:**  
- `finished_announced` (persistido): solo para partidos con `status == "FINISHED"`. Protege el recap oficial.  
- `provisional_announced` (persistido, separado): para partidos bloqueados IN_PLAY > 4h. Envía un ⏳ recap provisional sin consumir el dedup oficial, de modo que el recap oficial sigue disparando cuando la API finalmente cambia a FINISHED.

**Incluye `_var_correction_watch`:** en ticks sin partidos nuevos, comprueba si algún partido FINISHED tiene score diferente al último conocido (post-partido VAR / corrección tardía). Si lo detecta, envía un mensaje especial.

**Estado persistido:** `{STATE_DIR}/finished_announced.json`, `{STATE_DIR}/provisional_announced.json`

---

### 3.5 `poll_goal_clips_job`

**Cadencia:** cada **45 segundos**, primer disparo a los 20 s.

**Qué hace:**  
Busca en Reddit clips de vídeo para los goles ya notificados (entradas con `status='searching'` en el clip-store). Cuando encuentra un clip:

1. Lo descarga con `MediaDownloader`.  
2. Lo comprime con ffmpeg si supera 50 MB (`compress_if_needed`).  
3. Lo mueve al volumen persistente: `{STATE_DIR}/clips/{token}.mp4`.  
4. Edita el mensaje de Telegram del gol para añadir el botón **"Ver gol"** (keyboard inline).

**Límites:** máximo `_MAX_CLIP_ATTEMPTS = 40` intentos (~30 min a 45 s). Si no encuentra clip en ese tiempo, marca la entrada como `timeout`. Para el keyboard: máximo `_MAX_KEYBOARD_ATTEMPTS = 5` reintentos de edición antes de rendirse (evita llamadas infinitas a la API de Telegram por mensajes borrados).

**Limpieza:** cada tick elimina entradas y archivos de clip de más de 7 días.

**Estado persistido:** `{STATE_DIR}/goal_clips.json`, archivos `.mp4` en `{STATE_DIR}/clips/`

---

### 3.6 `poll_final_ceremony_job`

**Cadencia:** cada **60 segundos**, primer disparo a los 20 s.

**Qué hace:**  
Gestiona la **ceremonia del partido de la Final** disparando automáticamente dos piezas exactamente una vez cada una:

- **A) Pre-final:** cuando el kickoff de la Final llega (o el partido está ya IN_PLAY/PAUSED/FINISHED). Envía: hype + clasificación snapshot + bloque cara a cara de la porra.  
- **B) Campeón + Podio:** cuando `final_match.status == "FINISHED"` y hay ganador. Envía: anuncio del campeón, clasificación final oficial, imagen del podio.

**Restart-safe:** el estado (`pre_final_sent`, `campeon_sent`) se persiste en `final_ceremony_state.json` después de cada pieza enviada. Si el job devuelve error antes de persistir, reintenta en el siguiente tick.

**Estado persistido:** `{STATE_DIR}/final_ceremony_state.json`

---

### 3.7 `daily_update_job`

**Cadencia:** **diaria**, a la hora `DAILY_UPDATE_HOUR:00` (defecto: 09:00) en la zona horaria `TIMEZONE`.

**Condición de activación:** requiere `OPENAI_API_KEY + OPENAI_BASE_URL + OPENAI_MODEL` configurados y `TELEGRAM_GROUP_ID` definido.

**Qué hace:**  
Genera un **resumen diario en español** con IA: resultados de ayer, partidos de hoy, movimientos en la clasificación de la porra y notas contextuales (conflictos geopolíticos, curiosidades históricas, etc.). Lo envía al grupo de Telegram con parse_mode="HTML". Casos especiales: "pausa" (ayer hay partidos, hoy no), "reanudación" (ayer no, hoy sí), `None` si no hay partidos en ninguno de los dos días (el job salta sin enviar nada).

**Implementación:** `ai/daily_update.py` → `generate_daily_update()`.

---

### 3.8 `rich_image_job`

**Cadencia:** **diaria**, a las `RICH_IMAGE_HOUR:00` (defecto: 00:00) en `TIMEZONE`.

**Condición de activación:** requiere configuración de imagen IA (`OPENAI_IMAGE_API_KEY / OPENAI_IMAGE_BASE_URL + OPENAI_IMAGE_MODEL`).

**Qué hace:**  
Hace evolucionar la imagen de "riqueza" de una persona (el dueño del bot, de ahí `rich_original.jpg`) un nivel más cada día, añadiendo lujo, opulencia y glamour progresivos. El resultado se envía al grupo como foto con caption generada por IA.

**Días especiales (2026):**  
- **7/20 (Rich Apex):** imagen especial que menciona al país campeón del día anterior como símbolo de conquista suprema.  
- **7/21 (Rich Death):** imagen de despedida, escribe en `rich_death.png` (sin tocar `rich_modified.png`), no incrementa nivel, no actualiza historial.  
- **7/8 (Micky Birthday):** patrón similar al Death, imagen de cumpleaños, cadena intacta.

**Estado persistido:** `data/rich/rich_modified.png` (cadena de evolución), `data/rich/rich_level.txt`, `data/rich/rich_history.json`, `data/rich/rich_captions.json`.

---

### 3.9 `history_backfill_job`

**Cadencia:** una vez al **arranque** (15 s después) + **diaria** a las 09:05 en `TIMEZONE`.

**Qué hace:**  
Construye o actualiza el histórico de puntuación de la porra jornada a jornada, guardándolo en `porra_history.json`. Este fichero es la fuente de datos de `/evolucion`. El job es best-effort: si falla, no afecta a ningún otro job. Nunca lanza excepciones hacia afuera.

**Estado persistido:** `{STATE_DIR}/porra_history.json`

---

### 3.10 `profile_update_job`

**Cadencia:** **diaria**, a las `PICANTE_PROFILES_UPDATE_HOUR:00` (defecto: 04:00) en `TIMEZONE`.

**Condición de activación:** requiere `PICANTE_PROFILES_ENABLED=1` + picante activo (requiere a su vez `CHAT_PICANTE_ENABLED=1` + IA configurada).

**Qué hace:**  
Actualiza los perfiles automáticos de cada participante de la porra a partir de los mensajes del grupo. Proceso incremental: solo procesa mensajes desde `last_run` para no repetir trabajo. Hace una única llamada de IA con la conversación completa atribuida, extrayendo rasgos, equipo favorito, motes, temas de conversación y piques recientes por usuario.

**Estado persistido:** `{STATE_DIR}/picante_profiles.json`, `{STATE_DIR}/picante_last_run.json`

---

### 3.11 `revive_inactive_job`

**Cadencia:** auto-reprogramable con jitter. Base: `REVIVE_CHECK_INTERVAL_SECONDS` (defecto: 14400 s = 4h) ± `REVIVE_JITTER_SECONDS` (defecto: 2700 s = 45 min). Nunca dispara dentro de la ventana silenciosa (`REVIVE_QUIET_START_HOUR`–`REVIVE_QUIET_END_HOUR`, defecto 23:00–06:00).

**Condición de activación:** requiere `CHAT_REVIVE_ENABLED=1` + IA configurada.

**Qué hace:**  
Detecta participantes de la porra que llevan más de `REVIVE_INACTIVE_DAYS` días sin escribir en el grupo y genera un @mention personalizado con IA (tono amigable, 1-2 frases en español/catalán) para que vuelvan al chat. Respeta un cooldown por usuario (`REVIVE_MENTION_COOLDOWN_DAYS`) para no acosar a nadie.

**Estado persistido:** en el `ChatState` (`{STATE_DIR}/chat_state.json`): `last_seen` y `last_mentioned` por usuario.

---

## 4. Subsistemas — mapa de módulos

### 4.1 `api/`

**Ficheros clave:** `client.py`, `models.py`, `cache.py`

**Responsabilidad:** cliente HTTP síncrono para football-data.org v4.

`FootballDataClient` expone:
- `get_all_matches()` → lista completa de partidos de la competición.  
- `get_live_matches()` → partidos en IN_PLAY/PAUSED.  
- `get_standings()` → tabla de grupos.  
- `get_finished_groups()` → grupos en estado FINISHED.  
- `get_football_day_matches(timezone, offset, anchor_hour)` → partidos de una "jornada futbolera" (ventana de 24h anclada a las 09:00).  
- `get_next_match(timezone)` → próximo partido.

**Caché TTL:** `TTLCache` (defecto 60 s) evita duplicar llamadas dentro del intervalo de poleo. El cliente long-lived se almacena en `bot_data["football_client"]` para reusar la conexión HTTP.

**winner/penalty handling:** el campo `match.winner` del modelo toma valores `"HOME_TEAM"`, `"AWAY_TEAM"` o `null`. El atributo `match.in_penalty_shootout` (derivado del `stage` o de los metadatos del partido) permite excluir penalties de la detección de goles.

**`match_is_schedule_live(match, now_utc)`:** función auxiliar que trata como "en directo" un partido cuyo kickoff ya pasó pero que sigue en estado TIMED/SCHEDULED en la API (compensación del ~1h de retraso del free tier).

---

### 4.2 `porra/`

**Ficheros:** `predictions.py`, `scoring.py`, `engine.py`, `camps.py`, `elecciones.py`, `history.py`, `chart.py`, `live.py`

**`predictions.py`:**  
Loader YAML con hot-reload por mtime. **Gotcha crítica:** si un participante tiene un error (TLA desconocido, grupos incorrectos, claves extra en knockout, etc.), ese participante se descarta completamente del dict resultante — no parcialmente, sino entero. El error se logea a nivel ERROR. Si no se corrige `predictions.yml`, esa persona no aparecerá en ninguna clasificación.

**`scoring.py`:**  
Lógica pura de scoring. Cero I/O.  
- `score_groups()`: puntúa grupo a grupo.  
- `score_knockout()`: puntúa eliminatorias. Soporta `decided_teams` para marcar "pending" en lugar de "fallo" equipos cuyo partido no ha terminado todavía.  
- `best_qualifying_thirds()`: calcula los 8 mejores terceros del Mundial 2026 (más grupos por competición).

**`camps.py`:**  
Calcula el bloque ⚔️ "¿Con quién vas?". Para rondas eliminatorias, divide a los participantes entre los que predijeron avanzar al equipo local, los que predijeron al visitante, y los indecisos. Solo aplica a rondas eliminatorias (no en fase de grupos).

**`elecciones.py`:**  
Genera el texto o imagen de `/elecciones` por fase. Puro, sin I/O.

---

### 4.3 `reddit/`

**Ficheros:** `scanner.py`, `parser.py`, `score_state.py`, `notifier.py`, `clip_finder.py`, `clip_store.py`, `downloader.py`, `video.py`, `vergol_stats.py`, etc.

**`scanner.py` (`RedditMatchScanner`):**  
Scrapa el subreddit `r/soccer` buscando el match thread de un partido por nombre de equipo. Usa caché de TTL para evitar llamadas repetidas. Fallback: búsqueda via la API JSON pública de Reddit (`/search.json`).

**`parser.py`:**  
Parsea el cuerpo del hilo de Reddit para extraer eventos de gol (`GoalEvent`): minuto, goleador, equipo, marcador resultante.

**`score_state.py` — `reconcile()`:**  
Función central para el sistema dual de detección de goles. Dados `source_seen` (lo que esta fuente ya procesó), `announced` (lo que ya se anunció al grupo) y el marcador actual, calcula qué deltas hay que anunciar: `goal`, `disallowed` o `catchup`. El estado `announced` es compartido entre API y Reddit; `seen` es por fuente.

**`clip_finder.py`:**  
Busca en el hilo de Reddit un clip de vídeo del gol específico (por minuto y goleador).

**`downloader.py` / `video.py`:**  
Descarga el clip y lo comprime con ffmpeg si es mayor de 50 MB (`VideoTooLargeError` si supera el límite incluso comprimido).

---

### 4.4 `espn/`

**Ficheros:** `client.py`, `formatter.py`

**Responsabilidad:** cliente HTTP para la API pública (no oficial) de ESPN, para obtener estadísticas de partido (posesión, disparos, tarjetas, etc.) que se muestran en el recap de partido terminado.

**Configuración:** `ESPN_LEAGUE_SLUG` (defecto: `"fifa.world"`).

---

### 4.5 `tve.py`

**Responsabilidad:** consulta la API pública de RTVE para saber qué partidos del Mundial se emiten en La 1 o Teledeporte, y devuelve la etiqueta de canal correspondiente.

**API:** `https://www.rtve.es/api/schedule/{slug}.json` (pública, sin auth). Canales: `tv1` (La 1), `dep` (Teledeporte).

**Identificación de partidos:** filtra por `idPrograma == 1030562` (el programa del Mundial 2026 en RTVE) y excluye ítems de "resumen" o repetición.

**Activación:** controlada por `TVE_ENABLED` (defecto: `True`). Aparece en `/hoy` y `/siguiente`.

---

### 4.6 `ai/`

**Ficheros:** `client.py`, `daily_update.py`, `rich_image.py`, `commentators.py`, `goal_extractor.py`, `match_events.py`, `snapshot.py`

**`client.py` (`AIClient`):**  
Wrapper async sobre `openai.AsyncOpenAI`. Usado por todos los módulos de IA. La función global `ai_enabled(settings)` verifica que los tres vars (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`) estén todos definidos.

**`daily_update.py`:**  
Genera el resumen diario. Prompt en español, respuesta JSON que luego se renderiza como HTML. Casos especiales: "normal", "pausa", "reanudacion".

**`rich_image.py` (`run_rich_iteration`):**  
Pipeline de evolución de imagen: carga `rich_original.jpg` + `rich_modified.png` (si existe), llama al modelo de imagen con `RICH_EDIT_PROMPT`, guarda el resultado. Días especiales: `is_rich_apex()` (7/20), `is_rich_death()` (7/21), Micky birthday (7/10). La función de imagen usa claves separadas (`OPENAI_IMAGE_API_KEY` / `OPENAI_IMAGE_BASE_URL` / `OPENAI_IMAGE_MODEL`) que hacen fallback a las claves generales si no están definidas.

**`commentators.py`:**  
Genera comentarios de la porra para el recap de partido terminado. Elige aleatoriamente entre varios "comentaristas" con personalidades distintas.

**`goal_extractor.py`:**  
Extrae el nombre del goleador y el minuto desde el texto del hilo de Reddit via IA.

**`match_events.py`:**  
Extrae eventos completos de partido (goles, tarjetas, alineaciones, cambios, minuto) desde el texto del hilo de Reddit via IA. Usado por `/endirecto`.

**Notas de moderación:** los prompts están diseñados para output en español, sin contenido inapropiado. Las llamadas de IA son best-effort: si fallan, el bot envía el mensaje sin la parte de IA.

---

### 4.7 `chat/`

**Ficheros:** `listener.py`, `buffer.py`, `picante.py`, `revive.py`, `profiles.py`, `profile_updater.py`, `state.py`, `timeline_store.py`

**⚠️ PRIVACIDAD:** Estas features requieren que el bot tenga acceso a los mensajes del grupo (Privacy Mode desactivado en @BotFather). Sin esto, el bot solo recibe mensajes que empiezan por `/` y las features de chat no funcionan.

**`listener.py` (`on_group_text`):**  
MessageHandler registrado únicamente cuando al menos `picante` o `revive` están activos (cero overhead si ambos están desactivados). Filtra mensajes del propio bot, comandos, media con caption y mensajes demasiado cortos (< 5 chars). Registra mensajes en `RingBuffer`, actualiza `last_seen`, guarda en timeline si `PICANTE_STORE_TEXT=1`, y dispara `maybe_reply()` si picante está activo.

**`buffer.py` (`RingBuffer`):**  
Buffer circular en memoria de los últimos `CHAT_BUFFER_SIZE` mensajes (defecto: 30). Usado como contexto para las respuestas de picante.

**`picante.py` (`maybe_reply`):**  
Con probabilidad `PICANTE_PROBABILITY` (defecto: 0.20), respeta cooldown `PICANTE_COOLDOWN_SECONDS` y límite diario `PICANTE_MAX_PER_DAY`, genera una respuesta IA breve al hilo de conversación del grupo. Solo dispara si el buffer tiene al menos `PICANTE_MIN_BUFFER` mensajes. Temperatura: `PICANTE_TEMPERATURE` (defecto: 0.9).

**`revive.py`:**  
Auto-programable via `schedule_next_revive()`. Candidatos: participantes de la porra inactivos > `REVIVE_INACTIVE_DAYS` y no mencionados en los últimos `REVIVE_MENTION_COOLDOWN_DAYS`. Respeta horas silenciosas.

**`profiles.py` / `profile_updater.py`:**  
Modelo de perfil de usuario (rasgos, equipo, motes, temas, tono, piques recientes). Actualización incremental via IA con conversación atribuida completa. Requiere `PICANTE_PROFILES_ENABLED=1`.

**`timeline_store.py`:**  
Almacena mensajes del grupo en formato JSONL (`picante_timeline.jsonl`) para el job de actualización de perfiles. Solo activo si `PICANTE_STORE_TEXT=1`.

---

### 4.8 `bot/`

**Ficheros:** `handlers.py`, `formatters.py`, `final_ceremony.py`, `podium_image.py`, `endirecto_store.py`

**`handlers.py`:** implementaciones de todos los comandos. Separa limpiamente la capa Telegram de la lógica de negocio (importa de `porra/`, `api/`, `ai/`).

**`formatters.py`:** funciones de formateo de texto para resultados, clasificaciones, goles. Puras, sin I/O.

**`final_ceremony.py`:** constantes de copy para la ceremonia final (editables sin tocar lógica), y helpers de estado.

**`podium_image.py`:** renderiza la imagen de podio con PIL/Pillow usando fotos de los participantes descargadas de `PHOTO_BASE_URL`.

**`endirecto_store.py`:** persiste y carga el snapshot de `/endirecto` en `endirecto.json` (necesario para que los callbacks inline funcionen tras reinicio del bot).

---

### 4.9 `config.py`

**Responsabilidad:** carga todas las variables de entorno, valida las obligatorias (`TELEGRAM_BOT_TOKEN`, `FOOTBALL_DATA_API_KEY`, `TELEGRAM_GROUP_ID`) y construye el objeto `Settings`. Expone también funciones de feature-flag: `ai_enabled()`, `picante_enabled()`, `revive_enabled()`, `picante_profiles_enabled()`, `image_ai_enabled()`.

---

## 5. Modelo de puntuación de la porra

### Fase de grupos

Cada participante predice los **3 primeros** de cada grupo (12 grupos, A–L).

| Situación | Puntos |
|-----------|--------|
| Equipo en posiciones 1 o 2 (cualquier orden dentro del top-2) | **1.0** |
| Posición exacta == 3 **y** el equipo es de los 8 mejores terceros que clasifican | **1.0** |
| Equipo clasifica pero no en la posición predicha (boundary: el equipo estaba en top-2 en la pred pero cayó a 3.º clasificado, o al revés) | **0.5** |
| El equipo predice 3.º pero NO es de los mejores terceros (eliminado) | **0.0** |
| Fallo completo (equipo no clasifica) | **0.0** |
| `**` (wildcard, no-pick) | **0.0** (nunca error) |

**Mejores terceros:** El Mundial 2026 tiene 12 grupos con 4 equipos cada uno → 12 terceros. Solo los 8 mejores (por puntos, diferencia de goles, goles a favor) clasifican al Round of 32. `best_qualifying_thirds()` en `scoring.py` los calcula con los desempates de la FIFA. Mientras el torneo está en curso y no todos los grupos han cerrado, todos los terceros conocidos se tratan como clasificados (provisionally).

### Fase eliminatoria

Por cada equipo que el participante predice que **avanzará** de una ronda:

| Ronda | Puntos por acierto |
|-------|-------------------|
| Dieciseisavos de Final (`LAST_32`) | **1** |
| Octavos de Final (`LAST_16`) | **2** |
| Cuartos de Final (`QUARTER_FINALS`) | **3** |
| Semifinales (`SEMI_FINALS`) | **5** |
| 3.º y 4.º Puesto (`THIRD_PLACE`) | **5** |
| Final (`FINAL`) | **8** |

**Nota sobre THIRD_PLACE:** el scoring de `THIRD_PLACE` sí está configurado en `KNOCKOUT_STAGES` (5 puntos), pero **solo puntúa si el participante acertó qué equipo ganó el partido del tercer puesto**. La lógica es idéntica a cualquier otra ronda eliminatoria — se trata como un partido más, no como un stage especial.

**Penalty shootouts:** el ganador tras penaltis cuenta como ganador normal (`match.winner` refleja el resultado final incluyendo penaltis). Los kicks individuales de los penaltis se excluyen de la detección de goles (`match.in_penalty_shootout`).

**Modo `decided_teams`:** cuando `official=False` (provisional), los picks de rondas cuyo primer partido no ha terminado aún se marcan como "⏳ pending" en lugar de "fallo". Esto evita mostrar una derrota prematura para equipos cuyo partido simplemente no se ha jugado todavía.

**`base_score`:** campo opcional en `predictions.yml` para ajuste manual de puntos (default: 0). Útil para compensar errores de registro o puntuación de torneos previos.

---

## 6. Ficheros de datos y formatos

### 6.1 `data/predictions.yml`

**Propósito:** predicciones de todos los participantes.  
**Formato:** YAML con clave raíz `participants:` → dict keyed por @username en minúsculas.  
**Estado:** **git-ignorado** (runtime). El archivo comprometido es `predictions.example.yml`.  
**Plantilla comprometida:** `data/predictions.template.yml`  
**Hot-reload:** sí, por mtime en cada invocación de `pred_loader.load()`.

Estructura por participante:
```yaml
username:
  display_name: "Nombre Mostrado"     # opcional
  base_score: 0                       # ajuste manual de puntos
  groups:
    A: ["TLA1", "TLA2", "TLA3"]       # 3 TLAs por grupo, en orden [1º, 2º, 3º]
    # ... grupos B–L
  knockout:
    round_of_32:    # 16 equipos
    round_of_16:    # 8 equipos
    quarter_finals: # 4 equipos
    semi_finals:    # 2 equipos
    final:          # 1 equipo (el campeón)
```

**Wildcard `**`:** se puede usar en lugar de cualquier TLA. Siempre puntúa 0, nunca da error de validación.

---

### 6.2 `data/TongoUsers.yml`

**Propósito:** configuración del comando `/tongo`: pool de frases y overrides por usuario.  
**Estado:** **git-ignorado** (runtime).  
**Plantilla comprometida:** `data/TongoUsers.template.yml`  
**Hot-reload:** sí, por mtime en cada invocación de `/tongo`.

Estructura:
```yaml
phrases:           # Pool global de frases
  - "Frase de ejemplo."

users:             # Overrides por usuario (username en minúsculas, sin @)
  username:
    sanchez_ratio: 0.33    # Prob. de "Sanchez ens roba" (defecto: 1/3)
    phrases_mode: append   # "append" (añade al global) o "replace" (sustituye)
    phrases:
      - "Frase personalizada, {{first_name}}"
```

**Variables de plantilla:** 10 variables disponibles: `{{first_name}}`, `{{last_name}}`, `{{full_name}}`, `{{username}}`, `{{id}}` (del invocador), más `{{reply_to_first_name}}`, `{{reply_to_last_name}}`, `{{reply_to_full_name}}`, `{{reply_to_username}}`, `{{reply_to_id}}` (del mensaje respondido).

**Reply-targeting:** si `/tongo` se usa como respuesta y la frase elegida usa `{{reply_to_*}}`, el bot entra en modo reply-targeting y solo elige frases que contienen esas variables.

---

### 6.3 `data/tongo_gifs/`

**Propósito:** GIFs y vídeos cortos (`.gif`, `.mp4`) que el bot puede enviar como respuesta a `/tongo`.  
**Estado:** el directorio está en git (con `.gitkeep`), pero los archivos `.gif`/`.mp4` son **git-ignorados**.  
**Hot-reload:** sí, `list_tongo_gifs()` lee el directorio en cada invocación de `/tongo`.  
**Deployment:** copiar los archivos al directorio en el servidor (o volumen montado). No requiere reinicio.

---

### 6.4 Ficheros de estado JSON (runtime, `STATE_DIR`)

Todos están en el volumen persistente `{STATE_DIR}` (defecto: `/app/state` en contenedor). Son **git-ignorados** y se crean/regeneran automáticamente. No commitear nunca.

| Fichero | Qué guarda | Quién lo usa |
|---------|-----------|-------------|
| `live_scores.json` | Marcadores "anunciados" de partidos en directo | `poll_goals_job`, `poll_thread_goals_job` |
| `kickoff_announced.json` | IDs de partidos cuyo kickoff ya fue notificado | `poll_kickoff_job` |
| `finished_announced.json` | IDs de partidos con recap oficial enviado | `poll_finished_matches_job` |
| `provisional_announced.json` | IDs de partidos con recap provisional enviado | `poll_finished_matches_job` |
| `final_ceremony_state.json` | `{pre_final_sent, campeon_sent}` | `poll_final_ceremony_job`, `/granfinal` |
| `goal_clips.json` | Entradas del clip-store (token → metadata + path + status) | `poll_goal_clips_job`, `cmd_ver_gol_callback` |
| `porra_history.json` | Histórico de puntuación por jornada | `history_backfill_job`, `/evolucion`, `/recalcular` |
| `vergol_stats.json` | Contadores de clicks en "Ver gol" por usuario | `/estadisticas`, `cmd_ver_gol_callback` |
| `endirecto.json` | Snapshots de `/endirecto` (para callbacks inline) | `cmd_en_directo`, callbacks |
| `chat_state.json` | `last_seen` + `last_mentioned` por usuario | `revive_inactive_job` |
| `picante_profiles.json` | Perfiles AI por usuario | `profile_update_job`, `/perfil`, `/calcularperfiles` |
| `picante_last_run.json` | Timestamp de última ejecución del profile_update | `profile_update_job`, `/calcularperfiles` |
| `picante_timeline.jsonl` | Mensajes del grupo con atribución (JSONL) | `profile_update_job` |
| `clips/*.mp4` | Clips de vídeo de goles descargados | `poll_goal_clips_job`, `cmd_ver_gol_callback` |
| `evolucion.png` | Gráfico de evolución generado (sobreescrito cada vez) | `/evolucion` |

---

### 6.5 `data/rich/` (imagen "rich")

**`rich_original.jpg`:** foto base de la persona (el dueño del bot). **Git-ignorado**. Copiar al servidor manualmente.  
**`rich_modified.png`:** resultado de la última iteración de evolución. Runtime.  
**`rich_level.txt`:** número entero del nivel actual de riqueza. Runtime.  
**`rich_history.json`:** historial de captions de cada iteración. Runtime.  
**`rich_death.png`:** imagen especial del día de la "muerte" (7/21). No sobreescribe `rich_modified.png`.

---

## 7. Catálogo completo de variables de entorno

Fuente autoritativa: `src/worldcup_bot/config.py` → `load_settings()`.

### Obligatorias (el bot no arranca sin ellas)

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Token del bot de Telegram (@BotFather) |
| `FOOTBALL_DATA_API_KEY` | — | Clave API de football-data.org |
| `TELEGRAM_GROUP_ID` | — | ID del grupo de Telegram donde enviar notificaciones |

### Torneo y datos

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `PREDICTIONS_PATH` | `data/predictions.yml` | Ruta al fichero de predicciones |
| `COMPETITION_CODE` | `WC` | Código de competición en football-data.org (WC = World Cup) |
| `TIMEZONE` | `Europe/Madrid` | Zona horaria para mostrar horas y programar jobs |
| `FOOTBALL_CACHE_TTL` | `60` | TTL en segundos de la caché del cliente de football-data |
| `FOOTBALL_DAY_START_HOUR` | `9` | Hora de inicio de la "jornada futbolera" (09:00 → 09:00 del día siguiente) |
| `ESPN_LEAGUE_SLUG` | `fifa.world` | Slug de la liga en ESPN para estadísticas de partido |
| `BELOVED_TEAMS` | `PAN,UZB,CUW` | TLAs de equipos "queridos" (separados por comas); usados en prompts AI |
| `TVE_ENABLED` | `1` | Activa las etiquetas 📺 de RTVE en /hoy y /siguiente |

### Polling y estado

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `GOAL_POLL_INTERVAL_SECONDS` | `60` | Intervalo del job de detección de goles por API |
| `FINISHED_POLL_INTERVAL_SECONDS` | `120` | Intervalo del job de partidos terminados |
| `STATE_DIR` | `/app/state` | Directorio para todos los ficheros de estado JSON y clips |
| `FINAL_CORRECTION_WINDOW_MINUTES` | `30` | Ventana post-partido para vigilar correcciones de VAR tardías |

### Fotos y UI

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `PHOTO_BASE_URL` | `http://victorsaez.cat` | URL base para las fotos de participantes (`{base}/{username}.jpg`) |
| `CHOICES_TYPE` | `text` | Formato de /elecciones: `"text"` (texto) o `"image"` (imagen PNG) |

### Tongo

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `TONGO_GIFS_DIR` | `""` (usa `data/tongo_gifs/`) | Directorio con GIFs para /tongo |
| `TONGO_USERS_PATH` | `""` (usa `data/TongoUsers.yml`) | Ruta al fichero de configuración de /tongo |

### IA — chat y daily update

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `OPENAI_API_KEY` | `""` | Clave API de OpenAI (o compatible) para IA de chat |
| `OPENAI_BASE_URL` | `""` | Base URL del endpoint OpenAI (permite usar proxies/LLMs alternativos) |
| `OPENAI_MODEL` | `""` | Modelo de chat AI (e.g. `gpt-4o`, `gpt-5.5`) |
| `DAILY_UPDATE_HOUR` | `9` | Hora de publicación del resumen diario AI (00–23) |

### IA — imágenes (rich)

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `OPENAI_IMAGE_MODEL` | `gpt-image-2` | Modelo de generación de imágenes |
| `OPENAI_IMAGE_API_KEY` | `""` | Clave API específica para imágenes (fallback: `OPENAI_API_KEY`) |
| `OPENAI_IMAGE_BASE_URL` | `""` | Base URL específica para imágenes (fallback: `OPENAI_BASE_URL`) |
| `RICH_IMAGE_HOUR` | `0` | Hora del job de evolución de imagen (00:00 por defecto) |

### Reddit

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `REDDIT_USER_AGENT` | Chrome UA | User-Agent para las peticiones a Reddit (no auth) |

### Chat — picante

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `CHAT_PICANTE_ENABLED` | `0` | Activa las respuestas AI espontáneas en el grupo (requiere IA) |
| `CHAT_BUFFER_SIZE` | `30` | Tamaño del buffer circular de mensajes recientes |
| `PICANTE_PROBABILITY` | `0.20` | Probabilidad de responder a cada mensaje del grupo |
| `PICANTE_COOLDOWN_SECONDS` | `300` | Tiempo mínimo entre respuestas picantes (5 min) |
| `PICANTE_MAX_PER_DAY` | `30` | Máximo de respuestas picante por día |
| `PICANTE_MIN_BUFFER` | `5` | Mínimo de mensajes en buffer antes de responder |
| `PICANTE_TEMPERATURE` | `0.9` | Temperatura del modelo para picante |

### Chat — revive

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `CHAT_REVIVE_ENABLED` | `0` | Activa las menciones a usuarios inactivos (requiere IA) |
| `REVIVE_CHECK_INTERVAL_SECONDS` | `14400` | Intervalo base del job de revive (4 horas) |
| `REVIVE_INACTIVE_DAYS` | `3` | Días de inactividad para considerar a alguien "inactivo" |
| `REVIVE_MENTION_COOLDOWN_DAYS` | `2` | Días mínimos entre menciones al mismo usuario |
| `REVIVE_TEMPERATURE` | `0.8` | Temperatura del modelo para mensajes de revive |
| `REVIVE_QUIET_START_HOUR` | `23` | Hora de inicio del periodo silencioso (no se menciona a nadie) |
| `REVIVE_QUIET_END_HOUR` | `6` | Hora de fin del periodo silencioso |
| `REVIVE_JITTER_SECONDS` | `2700` | Jitter aleatorio ±45 min sobre el intervalo base |

### Chat — perfiles (picante avanzado)

| Variable | Defecto | Descripción |
|----------|---------|-------------|
| `PICANTE_PROFILES_ENABLED` | `0` | Activa los perfiles AI por usuario (requiere picante activo) |
| `PICANTE_STORE_TEXT` | `1` | Guarda mensajes en timeline JSONL para perfiles |
| `PICANTE_PROFILE_MODEL` | `gpt-5.4-nano` | Modelo AI para actualizar perfiles (puede ser uno más barato) |
| `PICANTE_PROFILES_WINDOW_DAYS` | `2` | Días de mensajes considerados para la actualización de perfiles |
| `PICANTE_PROFILES_OTHERS_CAP` | `3` | Máximo de otros usuarios incluidos en el contexto por perfil |
| `PICANTE_PROFILES_PIQUES_CAP` | `5` | Máximo de piques recientes a guardar por usuario |
| `PICANTE_PROFILES_UPDATE_HOUR` | `4` | Hora del job de actualización de perfiles (04:00 por defecto) |

---

## 8. Notas operativas / gotchas para el yo del futuro

### 8.1 La "jornada futbolera" empieza a las 09:00

El sistema de jornadas usa una ventana de 24h anclada a `FOOTBALL_DAY_START_HOUR` (defecto: 09:00). Un partido jugado a las 00:00 del martes pertenece a la jornada del lunes (09:00 lunes → 09:00 martes). Esto afecta a `/hoy`, `/ayer`, al job de daily update y a la detección de ganadores de ayer para la imagen rich. **Configura `FOOTBALL_DAY_START_HOUR` antes del torneo** si los partidos empiezan después de medianoche en tu zona horaria.

### 8.2 Códigos TLA: deben coincidir EXACTAMENTE con football-data.org

Los TLAs en `predictions.yml` deben coincidir byte a byte con los que usa football-data.org. Ejemplos de errores comunes:

| Incorrecto | Correcto |
|-----------|---------|
| `SAU` | `KSA` (Arabia Saudí) |
| `URU` | `URY` (Uruguay) |

Un TLA incorrecto se loguea como ERROR y el usuario entero se descarta del `predictions.yml`. Ver la lista de TLAs reales en el comentario del `predictions.example.yml` o consultando directamente la API.

### 8.3 Privacy Mode de Telegram es obligatorio para las features de chat

Las features `CHAT_PICANTE_ENABLED` y `CHAT_REVIVE_ENABLED` requieren que el bot reciba **todos los mensajes del grupo**, no solo los que empiezan por `/`. Para esto:

1. Ir a @BotFather → Bot Settings → Group Privacy → **Disable**.  
2. Expulsar y volver a añadir el bot al grupo para que el cambio surta efecto.

Sin este paso, `on_group_text` nunca se dispara y el bot no construye el buffer de mensajes.

### 8.4 SSL truststore (entornos corporativos)

El bot usa `truststore.inject_into_ssl()` al arrancar para inyectar el CA bundle del sistema operativo. Esto resuelve errores SSL en entornos con inspección TLS / CA corporativa. Si el entorno no tiene `truststore` instalado, la excepción se swallowea silenciosamente y el bot continúa con el store por defecto de Python. La carpeta `certs/` está git-ignorada y se usa opcionalmente para un bundle custom.

### 8.5 Hot-reload sin reiniciar el bot

Los siguientes ficheros se recargan automáticamente en la siguiente invocación, sin necesidad de reiniciar el contenedor:

- `data/predictions.yml` — recargado en cada llamada a `pred_loader.load()` si el mtime cambió.
- `data/TongoUsers.yml` — recargado en cada `/tongo` si el mtime cambió.
- `data/tongo_gifs/` — el listado de GIFs se lee en cada `/tongo`.

Para los ficheros de estado JSON en `STATE_DIR`, el bot los carga en `bot_data` al arranque y los persiste en disco tras cada cambio — no se recargan desde disco en cada tick (salvo en el primer tick tras arranque).

### 8.6 Imagen Docker y CI/CD

La imagen se publica en Docker Hub automáticamente. El workflow de GitHub Actions `Build and Deploy Docker Image` se dispara en cada push a `main`. Cuando hagas un merge, espera a que CI complete antes de hacer `docker pull` en el servidor.

### 8.7 El free tier de football-data.org tiene ~1h de retraso

Los partidos pueden quedarse en estado `TIMED` o `SCHEDULED` hasta ~1 hora después de su kickoff real. El bot compensa esto con `match_is_schedule_live()` (considera como "en directo" cualquier partido cuyo kickoff ya pasó según el calendario, hasta 4h) y con `poll_thread_goals_job` (detecta goles desde Reddit sin esperar a la API). Sin embargo, algunos datos (alineaciones, estadísticas) solo llegan via ESPN cuando el partido está `FINISHED`.

### 8.8 Los comandos ocultos no tienen autenticación

Cualquiera que esté en el grupo puede ejecutar `/simulagol`, `/updatediario`, `/recalcular`, etc. si conoce el nombre. Para el próximo torneo, considera añadir una verificación de `update.effective_user.id in ADMIN_IDS` antes de cada comando de admin.

### 8.9 THIRD_PLACE no puntúa como "tercer clasificado del torneo"

El partido del 3.º y 4.º puesto puntúa como cualquier otra ronda eliminatoria: si predijiste que ese equipo ganaría el partido (`third_place: [TLA]`), sumas 5 puntos. No hay puntuación especial por "acabar tercero del torneo". Si en el próximo torneo no hay partido de 3.º puesto (e.g., la Eurocopa no lo tiene), simplemente elimina `THIRD_PLACE` de `KNOCKOUT_STAGES` en `data/stages.py`.

### 8.10 El archivo `predictions.yml` es el núcleo — valida antes de arrancar

Antes de lanzar el bot para un nuevo torneo, comprueba que todos los TLAs son válidos con el validador interno: arranca el bot y busca líneas `ERROR` en los logs de la carga de predictions. Cada usuario con un TLA incorrecto se descarta silenciosamente — no aparecerá en las clasificaciones, y no recibirás ningún aviso en Telegram sobre ello.

---

*Documento generado el 2026-07-21 por Kanté (Backend Developer). Fuentes: `src/worldcup_bot/config.py` (variables de entorno), `src/worldcup_bot/__main__.py` líneas ~2710-2743 (registro de comandos) y `main()` (registro de jobs), `src/worldcup_bot/bot/handlers.py` (implementaciones). Ver también `README.md` para guía de despliegue y configuración inicial.*
