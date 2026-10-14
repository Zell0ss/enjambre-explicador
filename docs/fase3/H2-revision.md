# H2 — revisión (la nota, el aviso y `enjambre.leer`)

Revisado contra el código (`0949061`, `e82f2c0`, `974eff6`, `7dbb628`) y la spec (§8, D24, D28,
D30-D32, D34), no contra el informe.

## 1. Comprobado

- 239 pruebas de Python y 19 de JS, todas verdes (ejecutadas por el arquitecto).
- Las pruebas normativas de `test_nota.py`, `test_aviso.py` y `test_leer.py` coinciden con las del plan.
- **R1 y R2 de H1, cerrados.** `tomar`/`ocupado` resuelven `ruta or RUTA` al llamarse, y `origin` se
  compara sin distinguir mayúsculas. Los dos tienen su prueba.
- El vault no se ha tocado: `Clippings/repo-articles/` no existe.
- Foco 4 (coste de una continuación): `Lectura.coste_usd = run_fin.coste_total_usd − coste_previo_usd`
  del último `reanudado`. Correcto, y con prueba.
- `aviso.enviar` no lanza nunca y tapa el token en el mensaje de error. `escribir` rechaza nombres
  con ruta. La escritura atómica deja el temporal oculto y lo borra si falla.

## 2. Desviaciones del informe

| # | Veredicto |
|---|---|
| 1. `escribir(..., fichero=None)` | Aceptada: un solo camino de escritura |
| 2. `max_vueltas: int \| None` | Aceptada: es D24 |
| 3. La nota lleva el coste del run entero | **Aceptada**: la nota describe lo que costó el artículo; `Lectura`, lo de esta lectura |
| 4. Sin commit → run nuevo | Aceptada |
| 5. `monkeypatch` de `resolver` en la prueba de `main` | Aceptada: no abrir otra puerta fuera de `/data` es correcto |
| 6. `--falso` con `--reanudar` | Aceptada: es D24 |

## 3. Hallazgos

**R3. Una nota ajena se descubre después de gastar.** `leer` lanza `orquestar` y solo al final
llama a `escribir`, que es donde salta `NotaAjena`. Dos casos lo provocan: otra fuente con el mismo
nombre (`github.com/a/utils` y `github.com/b/utils`) o una nota humana `utils.md` en `repo-articles/`.
En los dos, el run se paga entero y el artículo no llega al vault. En la cola es peor: la excepción
suma un intento y el repo se vuelve a leer, y a pagar, las dos noches siguientes antes de acabar en
`fallidas/`. Hasta 3 × 5 $ por un choque de nombres que se sabía desde el principio.
**Arreglo:** comprobar el destino **antes** de `actualizar` u `orquestar`. Una función
`nota.comprobar(raiz, nombre, fuente)` que lanza `NotaAjena` con la misma regla que `escribir`,
llamada en `leer` salvo con `falso`. `escribir` sigue comprobando también, por si alguien crea la
nota a mano durante el run.
*Prueba de regresión:* con `notas/proyecto.md` humana, `leer(...)` lanza `NotaAjena`, el
`lanzar` falso **no se llama** y no se crea `salidas/proyecto/`.
**Atribución:** plan (arquitecto). El plan ordenaba "4. nota" sin pedir que se comprobara antes.

## 4. Decisiones que pedía el informe

1. **`.env` (D34):** es de Josem. Se lo pide el arquitecto en su ventana. Tú no lo creas ni lo lees.
2. **Nota que Josem ha sacado de `Clippings/`:** la decide Josem (ver §6). **No hagas nada sobre
   este punto hasta que llegue la decisión en una revisión o en un mensaje de Josem.**

## 5. Veredicto

**Aprobado con un retoque.** Haz R3 con su prueba de regresión. Después sigue con **H3, solo la
Tarea 23** (`enjambre/cola.py` con las pruebas normativas del plan). Para antes de la Tarea 24 y
espera la decisión del §6: cambia una regla de la cola.

- Gasto autorizado: **0**.
- Si el §6 se resuelve antes de que acabes la Tarea 23, te llega como anexo de esta revisión (§6).

## 6. Pendiente de Josem: qué hace la cola con un repo ya leído

Propuesta del arquitecto (D35, pendiente de aprobación). El salto "sin cambios" de la cola
(`saltar_si_igual`) se decide con **`salidas/`**: el último run acabado (`aprobado` o
`tope_vueltas`) de esa fuente con ese commit. No se decide con la nota. Así, una nota que Josem ha
sacado de `Clippings/` no hace que se relea y se pague otra vez el mismo commit. Y si Josem quiere
releerlo igualmente, tiene "Lanzar ahora", que nunca salta.

**Resolución (2026-10-14): Josem aprueba. D35 vigente** (D30 queda revisada por D35). Lo que pide:

1. `leer(..., saltar_si_igual=True)` mira `salidas/`, no la nota: busca el run más reciente de esa
   `fuente` cuya última línea sea un `run_fin` con motivo en `FINALES`. Si su `run_inicio.commit` es el
   commit de ahora, devuelve `motivo="sin_cambios"` sin lanzar nada. `nota` queda como la ruta
   `raiz_notas/<nombre>.md` si existe, o `None`. `texto_run`/`texto_noche` ya lo cubren.
2. La comprobación previa de R3 sigue igual: es otra cosa (nombre ocupado), no el salto.
3. *Pruebas de regresión:* (a) run aprobado, se borra la nota y `leer(saltar_si_igual=True)` da
   `sin_cambios` sin crear otro run; (b) run aprobado y después otro parado del mismo commit:
   `sin_cambios`, porque cuenta el último *acabado*. La continuación de lo parado la decide la cola
   con `ultimo_parado`, que va antes. (c) Commit nuevo: no salta.
   La prueba normativa `test_saltar_si_la_nota_ya_tiene_ese_commit` sigue pasando tal cual.

Con esto puedes hacer la Tarea 24 y cerrar H3. El `.env` ya existe (lo creó Josem). **La prueba
[API] de H3 sigue necesitando el "sí" de Josem en tu ventana.**
