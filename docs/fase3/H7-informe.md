# H7 — informe (Tareas 31, 32 y 33: publicable, D43-D45)

Rama `feature/h7`, worktree `/data/enjambre-explicador-h7` (`.venv` propio). `/data/enjambre-explicador` sigue en `main`.
Gasto: **0**. No he tocado el vault, `/data/github-abordaje`, el `cola/` real, el `.env` real (ni lo he leído: solo vi los nombres
de sus claves) ni `README.md` (lo reescribe `feature/readme`).

## Hecho

- **Tarea 31, D43** (`b963edd`): los siete `.claude/agents/<rol>.md` pasan de enlaces al vault a **ficheros reales**, comprobados
  idénticos byte a byte (`cmp`) con los del vault antes de sustituir. `enjambre/agentes.py` gana `ORDEN`, `aviso_copia(rol)`,
  `copiar_a(destino, dir_agentes=None)` (atómico; `FileNotFoundError` si el destino no existe; el aviso va justo tras el `---` que cierra
  el frontmatter) y la CLI `python -m enjambre.agentes --copiar-a <carpeta>`. El código no sabe dónde está el vault.
- **Tarea 32, D44** (`562be55`, `fix` posterior): `enjambre/config.py` (`RAIZ_REPO`, `RUTA_ENV`, `VARIABLES`, `cargar_env`, `valor`,
  `raiz_notas`, `raiz_copias`, `raiz_local`, `host`, `puerto`): entorno > `.env` > defecto genérico, **al llamar**, rutas relativas desde
  `RAIZ_REPO`, `~` expandido, `0.0.0.0`/`::` → `ValueError`. Salen del código `nota.RAIZ_NOTAS`, `fuente.RAIZ_COPIAS`, `raiz_local=/data` de
  `resolver` (desviación 7 de H6), `raiz_repos` y `--host`/`--puerto` de `pantalla.py`; `leer` resuelve `raiz_notas`/`raiz_copias` dentro.
  `aviso.py` lee Telegram con `config.cargar_env`. `tests/conftest.py` (autouse) redirige `config.RUTA_ENV`, borra las `ENJAMBRE_*` y pone
  `ENJAMBRE_NOTAS`/`ENJAMBRE_COPIAS` en `tmp_path`. `registro.py`: sin `logcentral_client`, `logging` con un `FileHandler` en
  `<log_dir>/enjambre.log` (sin handlers repetidos). `requirements.txt` sin LogCentral; `requirements-seb01.txt` (`-r requirements.txt` +
  `-e /data/logcentral/packages/client`).
- **Tarea 33, D45** (`7702fab`): `LICENSE` (MIT, `Copyright (c) 2026 Zell0ss`), `.env.example` (las cinco `ENJAMBRE_*` comentadas con su defecto y
  `TELEGRAM_*` vacías, con la nota de que sin ellas no se avisa), `.gitignore` con `notas/` y `copias/` (el «Añadido 2026-10-18» del plan), y
  `CLAUDE.md` con las reglas nuevas.
- Pruebas: **376 Python** (355 de antes + 21) y 19/19 JS. Las del anexo, tal cual salvo lo que el propio anexo manda cambiar
  (`test_pesar_fuente_url_no_toca_las_copias`: `setenv("ENJAMBRE_COPIAS", …)`).

### Comprobado a mano (sin gastar)

- **Clon limpio** (el punto 3 de la aceptación): `git clone` de la rama, `python3.12 -m venv .venv`, `pip install -r requirements.txt`, `pytest`:
  **376 pasan sin LogCentral y sin `.env`**, y no aparece `.env`, `notas/`, `copias/`, `cola/` ni `cerrojo.lock` en el clon. Este ejercicio encontró un
  fallo real, ya corregido (Desviación 2).
- Pantalla sin `--host`: `http://127.0.0.1:<puerto>`; con `ENJAMBRE_HOST=100.87.64.121`: esa IP; con `ENJAMBRE_PUERTO=8899`: 8899;
  `ENJAMBRE_HOST=0.0.0.0` → `ValueError ... todas las interfaces (D12)`. (Los dos primeros, vía entorno; el `.env` lo lee igual.)
- `python -m enjambre.leer <ruta local pequeña> --falso` con `ENJAMBRE_RAIZ_LOCAL=/tmp ENJAMBRE_NOTAS=<tmp>`: sale 0, deja `nota.md` en la
  salida y **no** crea la carpeta de notas.

## Gasto

0.

## Desviaciones

1. **`git check-ignore -q notas/x.md copias/x/a.py` no funciona**: `-q` solo admite una ruta (error 128). La prueba comprueba cada una por
   separado; lo comprobado es lo mismo.
2. **El respaldo de logging escribe JSON** (`timestamp`, `source`, `level`, `message`, `exception`), no texto: `test_logger_escribe_json_con_source`
   (de H1) lo exige y **falla en un clon sin LogCentral**. El contrato del anexo solo decía «`logging` con un `FileHandler`»; el prueba del clon
   limpio lo cazó. Prueba añadida.
3. **`ORDEN = ROLES`** (alias) en vez de repetir la tupla: son la misma lista y así no pueden divergir.
4. **`aviso.py` reexporta `cargar_env`** (`from enjambre.config import cargar_env`): `tests/test_aviso.py` (normativa de H2) lo importa de ahí.
5. **Texto genérico en el código y la página** (para que `test_sin_codigo_de_seb01` y la publicación no enseñen la máquina): el placeholder de
   la página pasa a «URL de GitHub o ruta local»; los `help` y docstrings dicen `ENJAMBRE_RAIZ_LOCAL`; «seb01» sale de comentarios de `enjambre/`.
6. **Un valor vacío cuenta como no puesto** en `config.valor` (así `TELEGRAM_BOT_TOKEN=` vacío del `.env.example` no «gana» al defecto), y
   `host()` rechaza también `[::]` (usa `ipaddress`); `puerto()` valida el rango.
7. `pantalla.py`: `--puerto` pasa a `None` por defecto y se resuelve con `config.puerto()` (si no, `ENJAMBRE_PUERTO` no tendría efecto).

## Para que el README cuente (lista pedida por el anexo)

**Variables** (en el entorno o en `.env`; ver `.env.example`): `ENJAMBRE_NOTAS` (defecto `<repo>/notas`), `ENJAMBRE_COPIAS` (`<repo>/copias`),
`ENJAMBRE_RAIZ_LOCAL` (`~`), `ENJAMBRE_HOST` (`127.0.0.1`; `0.0.0.0` y `::` se rechazan), `ENJAMBRE_PUERTO` (`8790`), `TELEGRAM_BOT_TOKEN` y
`TELEGRAM_CHAT_ID` (opcionales: sin ellas no se avisa). Entorno > `.env` > defecto; ruta relativa desde la raíz del repo.

**Comandos** (todos con `.venv/bin/python -m …`): `enjambre.leer <URL|ruta> [--tope-usd] [--falso] [--sin-aviso]` y `enjambre.leer --reanudar <salida>`;
`enjambre.peso <fuente>`; `enjambre.cola` (la noche) y `encolar`; `enjambre.pantalla [--host] [--puerto]`; `enjambre.agentes --copiar-a <carpeta>`;
instalación: `pip install -r requirements.txt` (y `requirements-seb01.txt` solo en seb01, para LogCentral); pruebas: `pytest` y
`node --test tests/js/*.mjs`. Python 3.12.

**Otros hechos publicables:** licencia MIT; los prompts están en `.claude/agents/` (son el original: se cambian por plan o por Josem); sin
LogCentral el log va a `logs/enjambre.log`; `notas/` y `copias/` están en `.gitignore`; la unidad systemd de `systemd/` es la de seb01, de ejemplo.

## Decisiones que necesito

Ninguna. Antes de fusionar (Josem), como dice el anexo: el `.env` de `/data/enjambre-explicador` **ya tiene** las `ENJAMBRE_*` (vi sus
nombres, no los valores; compruébalos tú, sobre todo `ENJAMBRE_NOTAS` y `ENJAMBRE_HOST`, porque sin ellas la noche dejaría las notas en
`<repo>/notas`). Fusiona: `git merge --ff-only feature/h7` desde `/data/enjambre-explicador` y `git worktree remove ../enjambre-explicador-h7`;
reinicia la pantalla (lee `.env` al arrancar). Después, el arquitecto debe lanzar `python -m enjambre.agentes --copiar-a <carpeta del
proyecto en el vault>` para que `01-…07-*.md` pasen a ser copias de lectura con su aviso (hoy son idénticas a los prompts del repo, pero sin aviso).
