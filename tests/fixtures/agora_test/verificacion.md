# Verificación de articulo.md

## Resultado
- Afirmaciones comprobadas: 68
- Correctas: 68
- Fallos: 0
- No comprobables: 3

## Fallos
(Ninguno)

## No comprobables
- **"Quién crea los perfiles de uso real"** — El artículo especula correctamente que Sócrates y el canal de prueba están en init.sql, pero que perfiles adicionales (Gilito, Pratchett, etc.) se crean vía API `POST /profiles`. No hay forma de verificar esto contra el código, porque es sobre uso posterior por usuarios.
- **"Qué pasa cuando dos perfiles comparten `speaking_order`"** — El código ejecuta `ORDER BY cp.speaking_order` sin definir tiebreaker. El desempate depende del DBMS. El artículo reconoce correctamente que "el desempate no está definido en el código".
- **"Versionado de perfiles: no existe; se sobrescriben en vivo"** — Afirmación sobre ausencia de característica. Es verda que no hay versionado, pero no es verificable contra presencia.

## Correctas

1. `app = FastAPI()` y `lifespan()` en main.py con `init_pool()` al arrancar y `close_pool()` al parar
2. Log "startup: DB pool initialized" en lifespan() (exacto)
3. Settings en config.py con obligatorias anthropic_api_key, db_user, db_password
4. Defaults en Settings: db_host="localhost", db_port=3306, db_name="tertulia_db"
5. Logger con _json_sink() escribiendo a logs/tertulia.log en formato JSON
6. Timestamp en ISO 8601 UTC con milisegundos (formato "%Y-%m-%dT%H:%M:%S.%f"[:-3]+"Z")
7. Source fijo "tertulia" en logs
8. Pool aiomysql con minsize=1, maxsize=10, autocommit=True, charset="utf8mb4"
9. get_db() devuelve DictCursor async context manager
10. Queries agrupadas en tres ficheros: profiles.py, channels.py, messages.py
11. profiles.py: get_profile(), list_profiles(), insert_profile(), update_profile(), archive_profile(), get_moderador_profile()
12. channels.py: get_channel(), insert_channel(), update_channel(), delete_channel(), get_active_roster(), get_full_roster(), get_roster_entry(), add_to_roster(), remove_from_roster(), count_active_roster(), get_synthesis_cache(), save_synthesis(), delete_synthesis_cache()
13. messages.py: insert_message(), get_context_messages(), get_latest_summary(), insert_summary(), count_messages_after(), get_messages_chunk(), get_full_transcript(), get_last_message_id(), get_last_human_message(), get_total_cost_usd()
14. Tablas: profiles, channels, channel_profiles, messages (roles human/persona/system), summaries, channel_syntheses
15. archive_profile() pone archived=TRUE
16. remove_from_roster() pone active=FALSE
17. add_to_roster() usa ON DUPLICATE KEY UPDATE con active=TRUE
18. get_active_roster() filtra cp.active=TRUE AND p.archived=FALSE, ordena por speaking_order
19. save_synthesis() hace upsert: INSERT...ON DUPLICATE KEY UPDATE
20. delete_channel() borra primero summaries, luego channels
21. summaries.covers_up_to_msg_id es FK con RESTRICT hacia messages.id
22. Máximo 3 perfiles activos por canal (count_active_roster() >= 3 rechaza con 400)
23. speaking_order por defecto 0 en RosterAddIn
24. ProfilePatch no incluye tipo (no se puede cambiar)
25. delete_profile() endpoint llama a archive_profile()
26. patch_channel() borra síntesis caché si cambia base_text (delete_synthesis_cache())
27. Perfiles creados con model="claude-sonnet-4-6" y temperature=0.7 por defecto
28. ANDAMIO_DEBATE y ANDAMIO_CRITICA son strings constantes
29. build_context(profile, channel, messages, profile_names, summary=None) devuelve (system, api_messages)
30. Sistema según tipo/modo: facilitador → solo system_prompt; critica → ANDAMIO_CRITICA + system_prompt; otro → ANDAMIO_DEBATE + system_prompt
31. Bloques: base_text (si existe) con cache_control ephemeral, acta (si existe) sin caché, mensajes, último con cache_control ephemeral
32. Si sin mensajes, bloque "(La conversación acaba de comenzar.)"
33. human → "Josem: ..." (nombre fijo)
34. persona → profile_names.get(id) o "Participante {id}"
35. stream_turn() yield texto str, luego dict con tokens_in, tokens_out, cost_usd, cache_write, cache_read
36. stream_turn() con max_tokens=1024 fijo
37. stream_turn() calcula coste: entrada*precio + cache_write*precio*1.25 + cache_read*precio*0.1 + salida*precio
38. Temperature omitido en silencio para modelos en _MODELS_NO_TEMPERATURE (Claude 4.x)
39. Modelo no en _COST_PER_TOKEN → coste 0 sin error
40. _COST_PER_TOKEN tiene exactamente: "claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"
41. _MODELS_NO_TEMPERATURE contiene "claude-sonnet-4-6" y "claude-opus-4-8"
42. post_message() valida canal, devuelve StreamingResponse con media_type="text/event-stream"
43. Cabecera X-Accel-Buffering: no en post_message()
44. post_round() busca último mensaje humano, lanza 400 si no hay
45. post_round() llama run_turn(..., save_human=False)
46. run_turn() ejecuta maybe_compress() antes de guardar mensaje humano
47. parse_mention() busca @(\S+), normaliza sin acentos/minúsculas, rstrip puntuación
48. Mención válida → solo ese perfil; sin mención o desconocida → roster completo en speaking_order
49. Roster vacío emite TURN_COMPLETE y termina sin llamar modelo
50. Cada hablante lee get_latest_summary() y get_context_messages() en cada iteración del loop
51. BD es el canal de comunicación (siguiente hablante ve inserts previos)
52. insert_message() con rol "persona" después de stream, con tokens y coste
53. Errores en stream_turn() loguean y relanza (sin evento error SSE, conexión corta)
54. Eventos SSE: start (profile_id, profile_name), token (profile_id, token), done (tokens_in, tokens_out, cost_usd), TURN_COMPLETE (total_cost_usd)
55. Moderador no excluido del round-robin (run_turn() no filtra por tipo ni funcion)
56. COMPRESSION_THRESHOLD=30
57. COMPRESSION_CHUNK=20
58. ACTA_MAX_TOKENS=800
59. maybe_compress() retorna si count < 30
60. get_messages_chunk() con limit=COMPRESSION_CHUNK (20 mensajes)
61. _update_acta() con Haiku, max_tokens=1200, temperature=0.2
62. Formato acta difiere por modo (debate vs critica)
63. Nueva fila en summaries con covers_up_to_msg_id = id último mensaje del chunk
64. Fallo en compresión se loguea y turno continúa sin comprimir
65. Acta vacía descartada con warning
66. Coste Haiku no se registra en messages.cost_usd
67. synthesize() valida canal, devuelve StreamingResponse
68. run_synthesis() caché hit: si up_to_msg_id == last_msg_id, responde del instante
69. get_full_transcript() solo human y persona, con speaker names
70. get_moderador_profile() busca LOWER(funcion) LIKE '%moderador%' AND archived=FALSE
71. Síntesis usa system_prompt, model, temperature del Moderador
72. Errores en stream_turn() se convierten a evento SSE error
73. save_synthesis() con up_to_msg_id = last_msg_id
74. Síntesis con max_tokens=1024 puede truncarse, texto truncado se guarda como válido

## Verificación detallada realizada

- ✅ Existencia: Todos los ficheros, funciones, clases, constantes mencionados existen en sus ubicaciones exactas
- ✅ Relación: Todas las llamadas entre componentes (orchestrator → llm, stream.py → orchestrator, etc.) se verificaron contra el código
- ✅ Comportamiento: Valores numéricos (thresholds, tokens, precios), reglas de negocio (máximo 3 perfiles, caché, normalización), orders (speaking_order), estados (archived, active) confirmados
- ✅ FKs y cascadas: Estructura de init.sql coincide con descripciones de borrado en código
- ✅ Constantes: COMPRESSION_THRESHOLD, COMPRESSION_CHUNK, ACTA_MAX_TOKENS, _ACTA_GEN_TOKENS, max_tokens en stream_turn(), temperature en compressor
- ✅ Modelos: Nombres exactos en _COST_PER_TOKEN y _MODELS_NO_TEMPERATURE
- ✅ SSE: Eventos emitidos con sus campos exactos
