# Cambios

## Vuelta 1
- F1: la lista de modelos de `_COST_PER_TOKEN` ahora usa las claves exactas (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-8`).
- D1: explicada la estructura de FKs en `delete_channel()` (RESTRICT de `summaries` hacia `messages`, CASCADE para el resto) según la verificación; quitada la duda equivalente de "sin determinar".
- D2: los perfiles reales dejan de aparecer como hecho; se dice que no se sabe quién los crea y se supone el editor, marcado como no confirmado.
- Menor: explicado `funcion` frente a `name`; aclarado qué es `_MODELS_NO_TEMPERATURE` y que no se conoce su contenido; explicado por qué sale "Josem" fijo.
