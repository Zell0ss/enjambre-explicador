# H2 — informe (la nota, el aviso y `enjambre.leer`)

Incluye los retoques R1 y R2 de la revisión de H1 (commit `0949061`, ya hecho antes de empezar H2).

## Hecho

- **Tarea 20** (`e82f2c0`): `Lectura` en `tipos.py`; `fuente`/`commit` al nivel superior de `run_inicio`
  (`orquestar(..., fuente=None, commit=None)`); `enjambre/nota.py` (`escribir`, `leer_frontmatter`,
  `NotaAjena`, `FINALES`, `RAIZ_NOTAS`). `tests/test_nota.py` normativa + 2 pruebas en `test_orquestar.py`.
- **Tarea 21** (`974eff6`): `enjambre/aviso.py` (`cargar_env`, `enviar`, `texto_run`, `texto_noche`).
  `tests/test_aviso.py` normativa + 1 prueba añadida (el token no llega al log).
- **Tarea 22** (`7dbb628`): `enjambre/leer.py` (`leer`, `ultimo_parado`, `main`; CLI `python -m enjambre.leer`).
  `tests/test_leer.py`: las 8 normativas + 6 añadidas (la que pide el plan para `main` con `--falso`,
  más coste de una continuación, fuente inválida → 2, sin fuente → 2, cerrojo ocupado → 3 y
  `--reanudar` de un run sin `fuente`).
- Pruebas: **239 Python** (201 de antes de H2 + 38) y 19/19 JS. No queda `cerrojo.lock` por las pruebas.

### Paso manual sin gastar (hecho)

`.venv/bin/python -m enjambre.leer https://github.com/henrik-thevibe/Claude-Fables --falso`, exit 0, 7 s.

- **Commit que leyó:** `6d0ce80575a92f8f6c8c2493c2bf20413e255622` (rama `main`). La copia de
  `/data/github-abordaje/Claude-Fables` quedó limpia en ese commit; el `articulo.md` suelto desapareció
  (comprobado antes, con `cmp`, que era idéntico al de `salidas/Claude-Fables/Claude-Fables-20261004-220410/`).
- Run falso: `salidas/Claude-Fables/Claude-Fables-20261014-2128/`; nota en su `nota.md` (frontmatter correcto,
  `generado_por: enjambre`). El coste 0,09 $ es el inventado del modo falso.
- **El vault no se tocó:** `Clippings/repo-articles/` sigue sin existir. Sí se creó el `cerrojo.lock` real
  en la raíz del repo (lo toma el run; está en `.gitignore`).

## Gasto

0. Ningún [API]. La red solo se usó en el paso manual (`git fetch` de un repo público).

## Desviaciones

1. **`escribir(..., fichero=None)`**: parámetro añadido (el plan no lo tenía) para que `--falso` escriba
   `<salida>/nota.md` con el mismo código y no un segundo camino de escritura. Sin él, `escribir` solo sabe
   `<nombre>.md`.
2. **`max_vueltas: int | None = 2` en `leer`** (el plan: `int = 2`). `None` hereda el del run parado al
   continuar (D24, igual que `orquestar --reanudar` hoy); en un run nuevo vale 2. Así `--reanudar` sin
   `--max-vueltas` no pisa lo que se fijó al lanzar.
3. **Coste en la nota ≠ coste de la lectura.** `Lectura.coste_usd` es lo de esta lectura (foco 4: se calcula
   como `run_fin.coste_total_usd` menos el `coste_previo_usd` del último `reanudado`). El `coste_usd` del
   frontmatter de la nota es el **total del run**: describe lo que costó el artículo. Lo dice la prueba
   `test_continuacion_cuenta_solo_lo_de_esta_lectura`. Si prefieres lo contrario, es un cambio de una línea.
4. **`--reanudar` con otro commit, o sin commit** (fuente local sin git): no se continúa, se lanza un run
   nuevo. El plan lo dice para "otro commit"; "sin commit" lo añado porque no hay con qué compararlo.
5. **`main` de `leer` no puede probarse con una fuente en `tmp_path` sin ayuda:** `resolver` usa `/data` por
   defecto. La prueba pedida sustituye `enjambre.leer.resolver` con `monkeypatch`. No hay opción de CLI
   para cambiar la raíz (no la quiero: sería una puerta más fuera de `/data`).
6. **`--falso` con `--reanudar`:** el modo sale del `params.falso` del run, no del flag (igual que
   `orquestar --reanudar`); un run sin `params.falso` da código 2.

## Decisiones que necesito

1. **`.env` para el aviso (D34), lo crea Josem.** Para probar el Telegram real en H3 hacen falta
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (los de La borracha, copiados a mano) en
   `/data/enjambre-explicador/.env`. Yo no lo creo ni lo leo.
2. **Nota que Josem sacó de `Clippings/` (I9: "no se vuelve a escribir").** Hoy, si la nota ya no está en
   `repo-articles/`, `saltar_si_igual` no salta (no hay nota con ese commit) y la cola relee, y gasta, el
   repo, y `escribir` la recrea. Para cumplir I9 a la letra haría falta un registro de "notas ya
   sacadas" que ni el plan ni la spec definen. No lo he inventado. Dime si es lo que se quiere y dónde vive.
