# H1 — revisión (la fuente y el cerrojo)

Revisado contra el código (`7630013`, `f0edd6b`) y la spec (§8, D26, D27, D31), no contra el informe.

## 1. Comprobado

- 199 pruebas de Python y 19 de JS, todas verdes (ejecutadas por el arquitecto).
- `tests/test_fuente.py` y `tests/test_cerrojo.py` son **idénticos** a los del plan (`diff` vacío).
- No queda `cerrojo.lock` en la raíz del repo después de las pruebas.
- Foco 1 (credenciales): todo `git` pasa por `_git`, sin terminal ni helper, con `stdin=DEVNULL`,
  timeout y `killpg`. `GIT_ALLOW_PROTOCOL=https:file` no lo pedía el plan, pero suma. Bien.
- Foco 2 (inyección): argv en lista, `--` en el `clone`, lista blanca para dueño y nombre, `netloc`
  exacto y nombre revalidado en `actualizar`. Bien.
- Foco 3 (destrucción acotada): la ruta resuelta tiene que ser exactamente `<raiz_copias>/<nombre>`,
  con `.git` propio, `show-toplevel` igual a la ruta y `origin` igual a la URL. Una fuente local nunca
  llega a `reset` ni a `clean`. Bien.

## 2. Desviaciones del informe

| # | Veredicto | Atribución |
|---|---|---|
| 1. `fetch origin HEAD` + `reset FETCH_HEAD` | **Aceptada; es mejor que el plan.** Con un clon `--depth 1` de una sola rama, `set-head --auto` + `origin/HEAD` no habría seguido un cambio de rama por defecto. Cumple la intención de D27, "la rama por defecto del remoto" | hueco del plan (arquitecto) |
| 2. Dueño en minúsculas | Aceptada, con el retoque R1 | — |
| 3. `conftest.py` autouse | Aceptada, con el retoque R2 | — |
| 4. `_main_con_cerrojo`; 3 antes que 2 | Aceptada | — |
| 5. Local con `git` roto → `commit=None` | Aceptada | — |

## 3. Hallazgos

**R1. Una copia con el dueño en mayúsculas en su `origin` se ve como ajena para siempre.**
`resolver` pasa el dueño a minúsculas (desviación 2), pero `_canonico` compara el `origin` sin
pasarlo. Comprobado: `_canonico("https://github.com/Zell0ss/mangataro.git") ==
_canonico(resolver("https://github.com/Zell0ss/mangataro").url)` da `False`. Cualquier copia
clonada a mano, o por un `git` que guardó la URL tal cual, con un dueño con mayúsculas da
`CopiaAjena` en cada actualización y la petición acaba en `fallidas/`. Hoy Claude-Fables no lo
sufre, porque su dueño ya está en minúsculas. GitHub tampoco distingue mayúsculas en el nombre del
repo, así que la comparación de `origin` debe ser insensible a mayúsculas en dueño y repo. La forma
canónica y el nombre del directorio siguen conservando las mayúsculas del repo.
*Prueba de regresión:* copia con `origin` = `file://.../Remoto.git`, `actualizar` con
`remoto="file://.../remoto.git"` → actualiza, no `CopiaAjena`.
**Atribución:** implementación (programador). La desviación 2 cambió un lado de la comparación y no el otro.

**R2. `tomar()` y `ocupado()` fijan `RUTA` al importarse, así que el `conftest` solo protege a medias.**
`def tomar(ruta: Path = RUTA)` guarda el valor por defecto al definir la función. El
`monkeypatch.setattr(cerrojo, "RUTA", ...)` del `conftest` no le afecta (comprobado:
`inspect.signature(cerrojo.tomar)` sigue apuntando a `/data/enjambre-explicador/cerrojo.lock`).
Hoy no muerde, porque `orquestar.main` pasa la ruta explícita y lee `cerrojo.RUTA` en cada llamada.
Pero en H2-H4, `leer`, `cola` y `pantalla` llamarán al cerrojo, y una llamada sin argumento
tocaría el real desde las pruebas. Cambia la firma a `ruta: Path | None = None` y resuelve
`ruta or RUTA` dentro.
*Prueba de regresión:* con el `conftest` activo, `with cerrojo.tomar(): assert not Path(<RUTA real>).exists()`,
o `ocupado()` sin argumento crea el fichero en `tmp_path`.
**Atribución:** plan (arquitecto). La firma `tomar(ruta: Path = RUTA)` la dictaba el plan.

## 4. Para H2

- El `articulo.md` suelto de `/data/github-abordaje/Claude-Fables` es idéntico al de
  `salidas/Claude-Fables/Claude-Fables-20261004-220410/articulo.md`: el paso manual de la Tarea 22
  puede borrarlo sin perder nada.
- El contrato del vault ya tiene la excepción de `Clippings/` (Josem lo copió).

## 5. Veredicto

**Aprobado con retoques.** Haz R1 y R2 con su prueba de regresión, en un commit (o dos), y sigue
con **H2 (Tareas 20, 21 y 22)** sin esperar otra revisión de H1: los retoques los miro en la de H2.

- Gasto autorizado en H2: **0**. El paso manual de la Tarea 22 es `--falso`.
- El `.env` lo crea Josem cuando lo pidas en el informe de H2. No lo crees tú.
- Para al acabar H2: `docs/fase3/H2-informe.md`.
