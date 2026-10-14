# H1 — informe (la fuente y el cerrojo)

## Hecho

- **Tarea 18** (`7630013`): `enjambre/fuente.py` (`Fuente`, `resolver`, `actualizar`, `FuenteInvalida`,
  `CopiaAjena`, `GitFallo`), `tests/gitutil.py`, `tests/test_fuente.py` (normativas, copiadas tal cual),
  `tests/test_fuente_seguridad.py` (añadidas, ver abajo) y `.gitignore` (`.env`, `cola/`, `cerrojo.lock`).
- **Tarea 19** (`f0edd6b`): `enjambre/cerrojo.py` (`tomar`, `ocupado`, `Ocupado`), `--cerrojo` en
  `orquestar.main` (todo el run, también `--reanudar`, dentro de `tomar`; ocupado → stderr
  `hay otro run en marcha` y código 3), `tests/test_cerrojo.py` (normativas) y `tests/conftest.py`.
- Plan commiteado aparte antes de empezar: `22bcdd7`.
- Pruebas: **199 Python** (155 de antes + 44 nuevas) y 19/19 JS. Las del plan: 30, todas verdes sin tocarlas.

### Foco de revisión 1-3: dónde mirar

1. **`git` nunca pide credenciales** — todo `git` pasa por `fuente._git` (`fuente.py`) y solo por ahí:
   `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=""`, `SSH_ASKPASS=""`, `GCM_INTERACTIVE=never`,
   `-c credential.helper=` (ningún helper), `stdin=DEVNULL`, timeout (por defecto 300 s). Al vencer el
   timeout se mata el **grupo de procesos** (`start_new_session` + `killpg`), no solo `git`, para no dejar
   colgado `git-remote-https`. Además `GIT_ALLOW_PROTOCOL=https:file` (nada de `ext::` ni `ssh`).
   Prueba: `test_git_va_sin_terminal_ni_credenciales`, `test_timeout_falla_sin_restos`.
2. **Sin inyección por la URL** — `Popen` con lista, nunca `shell=True`; `--` antes de URL y ruta en el
   `clone`. Nombre (y dueño) con lista blanca `[A-Za-z0-9_.-]`, ni `.` ni `..`, sin empezar por `-`.
   `netloc` exacto (`github.com`/`www.github.com`): `github.com@evil`, `github.com:444` o
   `evil/github.com/...` se rechazan. `actualizar` **revalida el nombre** porque `Fuente` se puede construir
   a mano. Pruebas: `test_nombre_a_mano_se_revalida`, `test_url_con_usuario_o_puerto_no_es_github`.
3. **`reset --hard`/`clean -fdx` solo dentro de `raiz_copias`** — antes de tocar nada,
   `ruta.resolve() == raiz_copias.resolve()/nombre` exacto (un symlink hacia fuera no pasa). La copia
   existente debe tener `.git` propio **y** `rev-parse --show-toplevel` igual a la propia ruta (si no,
   `git` actuaría sobre el repo de arriba), y `origin` igual a la URL. Una fuente local jamás llega a
   `reset`/`clean`: solo lee `rev-parse HEAD`. Pruebas: `test_symlink_hacia_fuera_no_se_toca`,
   `test_directorio_dentro_de_otro_repo_no_se_toca`, `test_fuente_local_no_se_modifica`.

### Pruebas añadidas (no normativas)

`tests/test_fuente_seguridad.py` (nombre a mano, URL con usuario/puerto, dueño en mayúsculas, symlink,
directorio dentro de otro repo, cambio de rama por defecto, argv/env de `git`, timeout) y `tests/conftest.py`
(ver Desviaciones 3).

## Gasto

0. Sin API ni red: los "remotos" son repos bare locales (`file://`). No se ha tocado el vault, `/data/github-abordaje` ni el cerrojo real.

## Desviaciones

1. **`fetch` por `origin HEAD`, sin `set-head --auto` ni `origin/HEAD`.** El plan dice `fetch --depth 1 origin`
   + `remote set-head origin --auto` + `reset --hard origin/HEAD`. Un clon `--depth 1` es de **una sola
   rama**: su refspec guardada solo trae la rama de entonces, así que si el remoto cambia su rama por
   defecto (master→main), ese fetch seguiría trayendo la vieja. Uso `fetch --depth 1 origin HEAD` +
   `reset --hard FETCH_HEAD` + `clean -fdx`: sigue siendo "la rama por defecto del remoto" (D27) y lo cubre
   `test_cambia_la_rama_por_defecto_del_remoto`. La rama local conserva su nombre antiguo; no importa, es
   una caché de solo lectura.
2. **El dueño de la URL se pasa a minúsculas** en la forma canónica (la spec §8.3 pide normalizar "mayúsculas
   del dueño"; GitHub no las distingue). El nombre del repo conserva sus mayúsculas (`Claude-Fables`).
3. **`tests/conftest.py` (nuevo).** Las pruebas existentes que llaman a `orquestar.main` sin `--cerrojo`
   ahora toman el cerrojo, y con el valor por defecto habrían creado `cerrojo.lock` en la raíz del repo
   (lo comprobé: se creaba). Un fixture autouse apunta `cerrojo.RUTA` a `tmp_path`. No cambia ninguna prueba
   existente.
4. **Un fallo del `_ejecutar` de siempre**: lo que antes era el cuerpo de `main` pasa a
   `_main_con_cerrojo(args)` (el nombre `_ejecutar` ya lo usa el guion). Mismo cuerpo, sin cambios.
   Consecuencia menor: con el cerrojo ocupado, un `--reanudar --repo` mal combinado devuelve 3 y no 2
   (el cerrojo se mira antes que la validación de argumentos).
5. `actualizar` de una fuente **local** con un `git` que falla (p. ej. dueño distinto, `safe.directory`)
   devuelve `commit=None` en vez de propagar `GitFallo`: es solo lectura y el plan permite `None`.

## Decisiones que necesito

Ninguna. (Para H2, la 1 y la 2 de Desviaciones son lo que conviene que confirme el arquitecto, no
bloquean nada.)
