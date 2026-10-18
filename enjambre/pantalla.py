"""
Servidor de la pantalla (D12): `ThreadingHTTPServer` de solo stdlib que sirve
la página estática y las salidas de un run, en directo (SSE) o en repetición
(fichero entero), sin publicar nada fuera de `salidas/` ni de `estaticos/`.

Foco de revisión #5 del plan de fase 2: el riesgo real de esta tarea es el
path traversal (`/api/fichero/.../../../../etc/passwd`, `%2e%2e`, `%2E%2E%2F`).
Toda ruta que viene de la URL se decodifica entera (`urllib.parse.unquote`)
ANTES de cortarla en componentes con una regex -- así un `%2F` decodifica a
`/` y puede introducir un `..` que la regex de la ruta no vio venir, pero que
`_resuelve_dentro` sí resuelve y rechaza -- y se resuelve (`Path.resolve()`)
comparándola contra el directorio permitido (`salidas` o `estaticos`) antes
de leer nada. Si la ruta resuelta no cae estrictamente dentro, 404 -- nunca
403 ni una excepción sin capturar que tumbe el hilo (`do_GET` nunca deja
escapar una excepción no prevista: ver `_despacha`).
"""

import argparse
import datetime
import json
import mimetypes
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# D6: este módulo no importa `enjambre.orquestar` ni el SDK (el run es un
# subproceso aparte, D21). `cola` solo importa `leer` dentro de una función,
# que la pantalla nunca llama; `tests/test_pantalla.py` lo comprueba.
from enjambre import cerrojo as cerrojo_mod
from enjambre import config
from enjambre import cola as cola_mod
from enjambre import peso as peso_mod
from enjambre.fuente import Fuente, FuenteInvalida, GitFallo, resolver

# Raíz de ESTE repo (enjambre-explicador), no la del repo que se vaya a
# analizar -- el subproceso de un run lanzado desde la página (anexo
# 2026-10-04, Tarea 15, D21) se arranca con este directorio como `cwd` para
# que `python -m enjambre.orquestar` se encuentre sea cual sea el repo de
# destino. Mismo patrón que ya usaba `_crear_analizador` para los defaults
# de `--salidas`/`--estaticos`.
_RAIZ_ENJAMBRE = Path(__file__).resolve().parent.parent

# Ver el comentario de `_ManejadorPantalla._parar` (carrera entre
# `subprocess.Popen` y `send_signal(SIGINT)` si el proceso recién lanzado
# aún no ha instalado su manejador de señales).
_MARGEN_ARRANQUE_S = 0.2

# Una URL tarda en clonarse (hasta los 300 s de `fuente.actualizar`) y el run
# no existe hasta entonces: el directo espera mientras el proceso siga vivo,
# con este tope por si se cuelga (D33).
_ESPERA_DIRECTO_MAX_S = 900

# Rutas de §5.1 del diseño. Los grupos de repo/run son `[^/]+` (un solo
# segmento); `<ruta...>` de /api/fichero es `.+` (puede llevar más barras:
# es una ruta de fichero dentro del run, no un nombre suelto).
_RUTA_FICHERO = re.compile(r"^/api/fichero/([^/]+)/([^/]+)/(.+)$")
_RUTA_EVENTOS = re.compile(r"^/api/eventos/([^/]+)/([^/]+)\.jsonl$")
_RUTA_DIRECTO = re.compile(r"^/api/directo/([^/]+)/([^/]+)$")
_RUTA_STATIC = re.compile(r"^/static/(.+)$")
# Lista blanca de caracteres para /static -- NO es la barrera de seguridad
# (esa es siempre `_resuelve_dentro`, que resuelve y comprueba
# `is_relative_to` igual que para /api/fichero; un ".." aquí dentro se deja
# pasar el carácter y luego se resuelve y se rechaza igual que siempre).
# Esto es solo para rechazar pronto basura evidente (bytes raros, espacios).
# Permite "/" desde que `pantalla/sprites/` trajo subcarpetas por rol
# (D14, arte real sustituyendo los sprites procedurales) -- antes solo
# servía ficheros sueltos en la raíz de `pantalla/`.
_NOMBRE_STATIC = re.compile(r"^[A-Za-z0-9._/-]+$")


def _resuelve_dentro(base: Path, ruta_relativa: str) -> Path | None:
    """Junta `ruta_relativa` (ya decodificada por el llamador) con `base` y
    resuelve el resultado contra el disco real. Si se escapa de `base`
    (cualquier `..`, incluido uno que solo aparece tras decodificar un
    `%2F`, o un symlink dentro de `base` que apunte fuera) devuelve `None`:
    es el único punto de autorización de las rutas con entrada de usuario."""
    try:
        base_r = base.resolve()
        candidato = base_r
        for segmento in ruta_relativa.split("/"):
            if segmento in ("", "."):
                continue
            candidato = candidato / segmento
        candidato = candidato.resolve()
    except ValueError:
        # Byte nulo u otro valor que Path/os.fspath rechaza (hallazgo Minor
        # de la revisión de seguridad del commit df61f0d): no autorizado,
        # igual que un traversal -- nunca una excepción sin capturar.
        return None
    if candidato == base_r or candidato.is_relative_to(base_r):
        return candidato
    return None


def _valida_lanzar(cuerpo: dict, raiz_repos: Path) -> tuple[Fuente, float, int, bool] | str:
    """Valida el cuerpo de `POST /api/lanzar` (D21, D33). Devuelve `(fuente,
    tope_usd, max_vueltas, falso)` ya validados y listos para pasar a
    `comando`, o un string con el motivo del rechazo (400) -- nunca lanza:
    toda entrada de red es sospechosa por defecto, mismo criterio que
    `_resuelve_dentro` para las rutas de `/api/fichero`.

    `repo` puede ser una URL pública de GitHub o una ruta bajo `raiz_repos`
    (D26): lo decide `fuente.resolver`, que es el único que sabe qué es una
    fuente válida, y devuelve la forma canónica.

    `isinstance(x, bool)` antes que `isinstance(x, (int, float))` en
    `tope_usd`/`max_vueltas` porque `bool` es subclase de `int` en Python --
    sin ese orden, `{"tope_usd": true}` colaría como `tope_usd=1`."""
    repo = cuerpo.get("repo")
    if not isinstance(repo, str) or not repo:
        return "repo debe ser una URL de GitHub o una ruta no vacía"
    try:
        fuente = resolver(repo, raiz_local=raiz_repos)
    except FuenteInvalida as e:
        return str(e)
    except (OSError, RuntimeError, ValueError):
        return "repo no es una ruta válida"

    tope_usd = cuerpo.get("tope_usd")
    if isinstance(tope_usd, bool) or not isinstance(tope_usd, (int, float)) or not (0 < tope_usd <= 10):
        return "tope_usd debe ser un número mayor que 0 y como mucho 10"

    max_vueltas = cuerpo.get("max_vueltas")
    if isinstance(max_vueltas, bool) or not isinstance(max_vueltas, int) or not (0 <= max_vueltas <= 3):
        return "max_vueltas debe ser un entero entre 0 y 3"

    falso = cuerpo.get("falso")
    if not isinstance(falso, bool):
        return "falso debe ser un booleano"

    return fuente, float(tope_usd), max_vueltas, falso


def _valida_reanudar_campos(cuerpo: dict) -> tuple[str, str, float, int] | str:
    """Valida los campos de `POST /api/reanudar` (D24, anexo 2026-10-04 (3))
    que no necesitan tocar el disco: `repo`/`run` son el NOMBRE corto de
    cada uno bajo `salidas/` (a diferencia de `/api/lanzar`, cuyo `repo` es
    una ruta de verdad bajo `raiz_repos` -- aquí ya existe el run, así que
    basta con el mismo par que usa `/api/runs`). `tope_usd`/`max_vueltas`
    con los mismos límites que `_valida_lanzar`. Devuelve `(repo, run,
    tope_usd, max_vueltas)` o un string con el motivo (400) -- los demás
    códigos (404/409) dependen del disco y los decide `_reanudar`."""
    repo = cuerpo.get("repo")
    if not isinstance(repo, str) or not repo:
        return "repo debe ser un nombre no vacío"
    run = cuerpo.get("run")
    if not isinstance(run, str) or not run:
        return "run debe ser un nombre no vacío"

    tope_usd = cuerpo.get("tope_usd")
    if isinstance(tope_usd, bool) or not isinstance(tope_usd, (int, float)) or not (0 < tope_usd <= 10):
        return "tope_usd debe ser un número mayor que 0 y como mucho 10"

    max_vueltas = cuerpo.get("max_vueltas")
    if isinstance(max_vueltas, bool) or not isinstance(max_vueltas, int) or not (0 <= max_vueltas <= 3):
        return "max_vueltas debe ser un entero entre 0 y 3"

    return repo, run, float(tope_usd), max_vueltas


def _listar_runs(salidas: Path) -> list[dict]:
    """`/api/runs`: un run es `salidas/<repo>/<run>/eventos.jsonl`. `inicio`
    es el `t` del primer evento (normalmente `run_inicio`); `motivo` es el
    de la línea `run_fin` si ya la hay, o `None` si el run sigue en marcha."""
    runs = []
    if not salidas.is_dir():
        return runs
    for repo_dir in salidas.iterdir():
        if not repo_dir.is_dir():
            continue
        for run_dir in repo_dir.iterdir():
            if not run_dir.is_dir():
                continue
            eventos_path = run_dir / "eventos.jsonl"
            if not eventos_path.is_file():
                continue
            inicio = None
            motivo = None
            try:
                with eventos_path.open("r", encoding="utf-8") as f:
                    primera = f.readline().strip()
                    if primera:
                        try:
                            primer_evento = json.loads(primera)
                        except json.JSONDecodeError:
                            primer_evento = None
                        # Important 3 (revisión df61f0d): la primera línea
                        # puede ser JSON válido y no ser un objeto (p.ej.
                        # "[1]") -- sin este isinstance, `.get("t")` lanza
                        # AttributeError y tumba /api/runs entero.
                        if isinstance(primer_evento, dict):
                            inicio = primer_evento.get("t")
                    for linea in f:
                        linea = linea.strip()
                        if not linea:
                            continue
                        try:
                            evento = json.loads(linea)
                        except json.JSONDecodeError:
                            continue  # línea corrupta: se ignora, no tumba /api/runs
                        if isinstance(evento, dict) and evento.get("tipo") == "run_fin":
                            motivo = evento.get("motivo")
            except (OSError, ValueError):
                # ValueError cubre UnicodeDecodeError (bytes UTF-8 inválidos
                # en el fichero): ese run concreto no sale en la lista, pero
                # /api/runs sigue respondiendo 200 con el resto (Important 3).
                continue
            runs.append(
                {
                    "repo": repo_dir.name,
                    "run": run_dir.name,
                    "inicio": inicio,
                    "motivo": motivo,
                }
            )
    runs.sort(key=lambda r: r["inicio"] or "", reverse=True)
    return runs


def _ultima_linea(log: Path | None) -> str:
    """Última línea no vacía del log de un run lanzado desde la página: es donde
    `enjambre.leer` deja su error (`GitFallo: ...`) cuando sale con código 2."""
    if log is None:
        return ""
    try:
        with log.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            cola = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return next((l.strip() for l in reversed(cola.splitlines()) if l.strip()), "")


class _ManejadorPantalla(BaseHTTPRequestHandler):
    """`self.server` es la subclase de `ThreadingHTTPServer` que crea
    `crear_servidor`, con `.salidas` y `.estaticos` ya puestos."""

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (firma heredada)
        pass  # silencia el access log de BaseHTTPRequestHandler en stderr.

    def do_GET(self) -> None:  # noqa: N802 (nombre fijado por BaseHTTPRequestHandler)
        try:
            self._despacha()
        except (BrokenPipeError, ConnectionResetError):
            # Cliente cerrado a medio envío (sobre todo en /api/directo):
            # "termina sin traza" (spec §5.1) -- nunca una excepción que
            # tumbe el hilo de ThreadingHTTPServer.
            pass

    def do_POST(self) -> None:  # noqa: N802 (nombre fijado por BaseHTTPRequestHandler)
        try:
            self._despacha_post()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _despacha_post(self) -> None:
        """`POST /api/lanzar` y `POST /api/parar` (anexo 2026-10-04, Tarea
        15, D21). Anti-CSRF antes de leer ni validar nada: `Content-Type:
        application/json` + cabecera `X-Enjambre: 1` -- una web ajena
        abierta en el navegador de Josem no puede mandar esa combinación sin
        un preflight CORS, y este servidor no responde CORS, así que el
        preflight falla antes de que el navegador llegue a mandar el POST
        de verdad."""
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta not in ("/api/lanzar", "/api/parar", "/api/reanudar", "/api/encolar", "/api/pesar", "/api/retirar"):
            self.send_error(404)
            return

        tipo_contenido = self.headers.get("Content-Type", "").split(";")[0].strip()
        if tipo_contenido != "application/json" or self.headers.get("X-Enjambre") != "1":
            self._responde_json(403, {"error": "faltan cabeceras anti-CSRF"})
            return

        if ruta == "/api/lanzar":
            self._lanzar()
        elif ruta == "/api/parar":
            self._parar()
        elif ruta == "/api/encolar":
            self._encolar()
        elif ruta == "/api/pesar":
            self._pesar()
        elif ruta == "/api/retirar":
            self._retirar()
        else:
            self._reanudar()

    def _responde_json(self, status: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _lanzar(self) -> None:
        longitud = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(longitud) if longitud > 0 else b""
        try:
            cuerpo = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            self._responde_json(400, {"error": "cuerpo no es JSON válido"})
            return
        if not isinstance(cuerpo, dict):
            self._responde_json(400, {"error": "cuerpo debe ser un objeto JSON"})
            return

        validado = _valida_lanzar(cuerpo, self.server.raiz_repos)  # type: ignore[attr-defined]
        if isinstance(validado, str):
            self._responde_json(400, {"error": validado})
            return
        fuente, tope_usd, max_vueltas, falso = validado

        with self.server.lock:  # type: ignore[attr-defined]
            proc = self.server.proc  # type: ignore[attr-defined]
            if proc is not None and proc.poll() is None:
                self._responde_json(409, {"error": "ya hay un run en marcha"})
                return
            # D31: un run a la vez en la MÁQUINA, no solo en este proceso: la
            # cola de la noche o una terminal pueden tener el cerrojo.
            if cerrojo_mod.ocupado(self.server.cerrojo):  # type: ignore[attr-defined]
                self._responde_json(409, {"error": "hay otro run en marcha (¿la cola?)"})
                return

            # Con segundos (no solo %Y%m%d-%H%M como el nombre por defecto
            # de `orquestar()`) para no chocar si Josem lanza dos veces
            # seguidas dentro del mismo minuto.
            run = f"{fuente.nombre}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
            args = [
                fuente.texto,
                "--salidas",
                str(self.server.salidas),  # type: ignore[attr-defined]
                "--tope-usd",
                str(tope_usd),
                "--max-vueltas",
                str(max_vueltas),
                "--run",
                run,
                # El mismo fichero que el servidor mira con `ocupado`: si el
                # hijo tomara otro (por defecto), D31 no cubriría nada.
                "--cerrojo",
                str(self.server.cerrojo),  # type: ignore[attr-defined]
            ]
            if falso:
                args.append("--falso")
            argv = self.server.comando(args)  # type: ignore[attr-defined]

            dir_logs = self.server.dir_logs  # type: ignore[attr-defined]
            dir_logs.mkdir(parents=True, exist_ok=True)
            log = dir_logs / f"{run}.log"
            with open(log, "wb") as log_fh:
                # start_new_session=True: el run sobrevive a un reinicio de
                # la pantalla (que entonces lo "olvida" -- /api/lanzador
                # volverá a decir en_marcha=false; aceptado en el POC, el
                # plan lo dice explícitamente). cwd=_RAIZ_ENJAMBRE, NUNCA el
                # `repo_path` del usuario: este proceso solo sabe lanzar
                # "python -m enjambre.orquestar" desde su propia raíz.
                proc = subprocess.Popen(
                    argv,
                    cwd=_RAIZ_ENJAMBRE,
                    start_new_session=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                )
            self.server.proc = proc  # type: ignore[attr-defined]
            self.server.proc_lanzado_en = time.monotonic()  # type: ignore[attr-defined]
            self.server.proc_repo = fuente.nombre  # type: ignore[attr-defined]
            self.server.proc_run = run  # type: ignore[attr-defined]
            self.server.proc_log = log  # type: ignore[attr-defined]

        self._responde_json(202, {"repo": fuente.nombre, "run": run})

    def _reanudar(self) -> None:
        """`POST /api/reanudar` (D24, anexo 2026-10-04 (3)): mismo patrón de
        validación en capas que `_lanzar` -- formato (400) antes de tocar
        disco, existencia (404) antes de leer, estado del run (409) antes de
        mirar si ya hay un proceso en marcha (409, misma ranura que
        `_lanzar`). El modo (`--falso` o real) lo decide el propio run
        (`params.falso`), nunca quien llama a este endpoint."""
        longitud = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(longitud) if longitud > 0 else b""
        try:
            cuerpo = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            self._responde_json(400, {"error": "cuerpo no es JSON válido"})
            return
        if not isinstance(cuerpo, dict):
            self._responde_json(400, {"error": "cuerpo debe ser un objeto JSON"})
            return

        validado = _valida_reanudar_campos(cuerpo)
        if isinstance(validado, str):
            self._responde_json(400, {"error": validado})
            return
        repo, run, tope_usd, max_vueltas = validado

        salida = _resuelve_dentro(self.server.salidas, f"{repo}/{run}")  # type: ignore[attr-defined]
        if salida is None or not (salida / "eventos.jsonl").is_file():
            self._responde_json(404, {"error": "ese run no existe"})
            return

        try:
            lineas = [l for l in (salida / "eventos.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            eventos_previos = [json.loads(l) for l in lineas]
        except (OSError, ValueError, json.JSONDecodeError):
            self._responde_json(409, {"error": "no se pudo leer el eventos.jsonl de ese run"})
            return
        if not eventos_previos or eventos_previos[-1].get("tipo") != "run_fin":
            self._responde_json(409, {"error": "ese run no termina en run_fin"})
            return
        if eventos_previos[-1].get("motivo") == "aprobado":
            self._responde_json(409, {"error": "ese run ya está aprobado"})
            return
        run_inicio = next((e for e in eventos_previos if e.get("tipo") == "run_inicio"), None)
        params_previos = (run_inicio or {}).get("params") or {}
        if "falso" not in params_previos:
            self._responde_json(409, {"error": "ese run es anterior a D24 (sin params.falso)"})
            return

        with self.server.lock:  # type: ignore[attr-defined]
            proc = self.server.proc  # type: ignore[attr-defined]
            if proc is not None and proc.poll() is None:
                self._responde_json(409, {"error": "ya hay un run en marcha"})
                return
            if cerrojo_mod.ocupado(self.server.cerrojo):  # type: ignore[attr-defined]
                self._responde_json(409, {"error": "hay otro run en marcha (¿la cola?)"})
                return

            args = [
                "--reanudar",
                str(salida),
                "--tope-usd",
                str(tope_usd),
                "--max-vueltas",
                str(max_vueltas),
                "--cerrojo",
                str(self.server.cerrojo),  # type: ignore[attr-defined]
            ]
            if params_previos["falso"]:
                args.append("--falso")
            argv = self.server.comando(args)  # type: ignore[attr-defined]

            dir_logs = self.server.dir_logs  # type: ignore[attr-defined]
            dir_logs.mkdir(parents=True, exist_ok=True)
            # "ab" (no "wb" como `_lanzar`): este run ya tenía un log de su
            # primer tramo -- se añade, no se pisa.
            log = dir_logs / f"{run}.log"
            with open(log, "ab") as log_fh:
                proc = subprocess.Popen(
                    argv,
                    cwd=_RAIZ_ENJAMBRE,
                    start_new_session=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                )
            self.server.proc = proc  # type: ignore[attr-defined]
            self.server.proc_lanzado_en = time.monotonic()  # type: ignore[attr-defined]
            self.server.proc_repo = repo  # type: ignore[attr-defined]
            self.server.proc_run = run  # type: ignore[attr-defined]
            self.server.proc_log = log  # type: ignore[attr-defined]

        self._responde_json(202, {"repo": repo, "run": run})

    def _encolar(self) -> None:
        """`POST /api/encolar` (D29, D33): pone una fuente en la cola de la
        noche. Misma validación que `/api/lanzar` (`fuente.resolver`, sin `git`
        ni red). 201 si es nueva, 200 si ya estaba pendiente, 400 si no vale."""
        longitud = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(longitud) if longitud > 0 else b""
        try:
            cuerpo = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            self._responde_json(400, {"error": "cuerpo no es JSON válido"})
            return
        repo = cuerpo.get("repo") if isinstance(cuerpo, dict) else None
        if not isinstance(repo, str) or not repo:
            self._responde_json(400, {"error": "repo debe ser una URL de GitHub o una ruta no vacía"})
            return
        try:
            ruta, nuevo = cola_mod.encolar(
                repo, raiz_cola=self.server.raiz_cola, raiz_local=self.server.raiz_repos  # type: ignore[attr-defined]
            )
        except FuenteInvalida as e:
            self._responde_json(400, {"error": str(e)})
            return
        except (OSError, RuntimeError, ValueError):
            self._responde_json(400, {"error": "repo no es una ruta válida"})
            return
        peticion = json.loads(ruta.read_text(encoding="utf-8"))
        self._responde_json(201 if nuevo else 200, {"fuente": peticion["fuente"], "nombre": peticion["nombre"], "nuevo": nuevo})

    def _pesar(self) -> None:
        """`POST /api/pesar` (D40): cuánto pesa una fuente y cuánto costaría leerla, antes
        de gastar. Misma validación de fuente que `/api/encolar`. No toma el cerrojo ni
        lanza subprocesos: una URL se clona en un temporal que se borra (nunca en
        `RAIZ_COPIAS`), sin gastar tokens."""
        longitud = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(longitud) if longitud > 0 else b""
        try:
            cuerpo = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            self._responde_json(400, {"error": "cuerpo no es JSON válido"})
            return
        if not isinstance(cuerpo, dict):
            self._responde_json(400, {"error": "cuerpo debe ser un objeto JSON"})
            return
        repo = cuerpo.get("repo")
        if not isinstance(repo, str) or not repo:
            self._responde_json(400, {"error": "repo debe ser una URL de GitHub o una ruta no vacía"})
            return
        tope_usd = cuerpo.get("tope_usd", 5)
        if isinstance(tope_usd, bool) or not isinstance(tope_usd, (int, float)) or not (0 < tope_usd <= 10):
            self._responde_json(400, {"error": "tope_usd debe ser un número mayor que 0 y como mucho 10"})
            return
        try:
            fuente = resolver(repo, raiz_local=self.server.raiz_repos)  # type: ignore[attr-defined]
        except FuenteInvalida as e:
            self._responde_json(400, {"error": str(e)})
            return
        except (OSError, RuntimeError, ValueError):
            self._responde_json(400, {"error": "repo no es una ruta válida"})
            return
        try:
            p = self.server.pesar(fuente)  # type: ignore[attr-defined]
        except (GitFallo, OSError) as e:
            self._responde_json(502, {"error": str(e)})
            return
        e = peso_mod.estimar(p, float(tope_usd))
        dato = peso_mod.como_dict(p, e)
        self._responde_json(200, {
            "texto": peso_mod.texto(p, e),
            "peso": {k: dato[k] for k in ("ficheros", "bytes", "ficheros_codigo", "bytes_codigo", "tokens")},
            "estimacion": {k: dato[k] for k in ("banda", "usd_min", "usd_max", "tope_usd", "alerta")},
        })

    def _retirar(self) -> None:
        """`POST /api/retirar {"id"}` (D42): saca una petición de la cola a `retiradas/`
        (no se borra nada). 200 si estaba, 404 si no, 400 si el id no tiene la forma de
        un nombre de la cola."""
        longitud = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(longitud) if longitud > 0 else b""
        try:
            cuerpo = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            self._responde_json(400, {"error": "cuerpo no es JSON válido"})
            return
        id_ = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        try:
            retirada = cola_mod.retirar(id_, raiz_cola=self.server.raiz_cola)  # type: ignore[attr-defined]
        except ValueError as e:
            self._responde_json(400, {"error": str(e)})
            return
        if not retirada:
            self._responde_json(404, {"error": "esa petición no está en la cola"})
            return
        self._responde_json(200, {"retirada": True})

    def _servir_cola(self) -> None:
        raiz = self.server.raiz_cola  # type: ignore[attr-defined]
        self._responde_json(200, {"pendientes": cola_mod.pendientes(raiz), "fallidas": cola_mod.fallidas(raiz)})

    def _parar(self) -> None:
        with self.server.lock:  # type: ignore[attr-defined]
            proc = self.server.proc  # type: ignore[attr-defined]
            if proc is None or proc.poll() is not None:
                self._responde_json(409, {"error": "no hay ningún run en marcha"})
                return
            # Margen de arranque: mandar SIGINT a un proceso recién lanzado
            # (`python -m enjambre.orquestar`, o el de mentira de las
            # pruebas) puede llegar ANTES de que ese proceso haya terminado
            # de arrancar el intérprete y de instalar su propio manejador de
            # señales -- en ese caso el SIGINT lo mata con el manejador por
            # defecto de Python (sale con el proceso terminado, sin más) en
            # vez de dejar que escriba su `run_fin: interrumpido`. Medido
            # empíricamente en este disco: un `python -c "..."` necesita
            # ~30ms hasta registrar `signal.signal(...)` (10/10 aciertos a
            # partir de 30ms, 4/10 a los 20ms, 0/10 sin espera) -- 0.2s deja
            # margen de sobra para eso y para el --falso real (importa algo
            # más). Nunca se espera de más: si el proceso ya lleva más de
            # `_MARGEN_ARRANQUE_S` corriendo (el caso normal: Josem para un
            # run que lleva un rato en marcha), `restante` sale <= 0 y no se
            # duerme nada.
            transcurrido = time.monotonic() - self.server.proc_lanzado_en  # type: ignore[attr-defined]
            restante = _MARGEN_ARRANQUE_S - transcurrido
            if restante > 0:
                time.sleep(restante)
            # El orquestador ya convierte esto en un `run_fin` con
            # `motivo: interrumpido` (verificado contra una ejecución real,
            # no solo asumido -- ver CancelledError/except en orquestar.py)
            # antes de que el proceso termine de verdad.
            proc.send_signal(signal.SIGINT)
        self._responde_json(202, {})

    def _servir_lanzador(self) -> None:
        proc = self.server.proc  # type: ignore[attr-defined]
        en_marcha = proc is not None and proc.poll() is None
        cuerpo = {
            "en_marcha": en_marcha,
            "repo": self.server.proc_repo if en_marcha else None,  # type: ignore[attr-defined]
            "run": self.server.proc_run if en_marcha else None,  # type: ignore[attr-defined]
        }
        if proc is not None and not en_marcha:
            repo, run = self.server.proc_repo, self.server.proc_run  # type: ignore[attr-defined]
            run_dir = _resuelve_dentro(self.server.salidas, f"{repo}/{run}")  # type: ignore[attr-defined]
            sin_run = run_dir is None or not (run_dir / "eventos.jsonl").is_file()
            # D33: el proceso murió antes de crear el run (repo privado o
            # inexistente, copia ajena, cerrojo ocupado...): sin esto la página
            # esperaría un directo que nunca llega. D36: y también si el run
            # existe pero el proceso salió con un código que no es de run
            # normal (0 aprobado, 1 parado, 130 interrumpido): p. ej. 2 =
            # "el repo ha cambiado" al continuar, que no deja ni un evento.
            if sin_run or proc.returncode not in (0, 1, 130):
                cuerpo.update(
                    repo=repo,
                    run=run,
                    codigo=proc.returncode,
                    error=_ultima_linea(self.server.proc_log),  # type: ignore[attr-defined]
                )
        self._responde_json(200, cuerpo)

    def _despacha(self) -> None:
        ruta = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)

        if ruta == "/":
            self._servir_simple(self.server.estaticos / "index.html")  # type: ignore[attr-defined]
            return

        m = _RUTA_STATIC.match(ruta)
        if m:
            nombre = m.group(1)
            candidato = (
                _resuelve_dentro(self.server.estaticos, nombre)  # type: ignore[attr-defined]
                if _NOMBRE_STATIC.match(nombre)
                else None
            )
            if candidato is None:
                self.send_error(404)
                return
            self._servir_simple(candidato)
            return

        if ruta == "/api/runs":
            self._servir_runs()
            return

        if ruta == "/api/lanzador":
            self._servir_lanzador()
            return

        if ruta == "/api/cola":
            self._servir_cola()
            return

        m = _RUTA_EVENTOS.match(ruta)
        if m:
            self._servir_eventos(*m.groups())
            return

        m = _RUTA_DIRECTO.match(ruta)
        if m:
            self._servir_directo(*m.groups())
            return

        m = _RUTA_FICHERO.match(ruta)
        if m:
            self._servir_fichero_salida(*m.groups())
            return

        self.send_error(404)

    def _servir_simple(self, ruta: Path) -> None:
        """`/` y `/static/<f>`: la ruta ya viene autorizada por el llamador."""
        if not ruta.is_file():
            self.send_error(404)
            return
        datos = ruta.read_bytes()
        tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _servir_runs(self) -> None:
        cuerpo = json.dumps(_listar_runs(self.server.salidas)).encode("utf-8")  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _servir_eventos(self, repo: str, run: str) -> None:
        # La URL termina en "<run>.jsonl" pero el fichero real en disco es
        # siempre "eventos.jsonl" dentro del directorio del run (ver Eventos).
        candidato = _resuelve_dentro(self.server.salidas, f"{repo}/{run}/eventos.jsonl")  # type: ignore[attr-defined]
        if candidato is None or not candidato.is_file():
            self.send_error(404)
            return
        datos = candidato.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _servir_fichero_salida(self, repo: str, run: str, ruta: str) -> None:
        candidato = _resuelve_dentro(self.server.salidas, f"{repo}/{run}/{ruta}")  # type: ignore[attr-defined]
        if candidato is None or not candidato.is_file():
            self.send_error(404)
            return
        datos = candidato.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _servir_directo(self, repo: str, run: str) -> None:
        """SSE: emite las líneas ya existentes de `eventos.jsonl` y luego
        sondea cada 0,5 s. Se lee en BINARIO y se corta por `b"\\n"`
        (Important 2, revisión df61f0d): un carácter UTF-8 multibyte puede
        quedar partido entre dos escrituras de un lector concurrente (Foco
        de revisión #3); decodificar solo tras encontrar el `\\n` evita que
        ese corte tumbe el stream con un `UnicodeDecodeError` a medio leer
        un fichero en modo texto. El resto sin `\\n` (que puede ser tanto
        una línea JSON a medias como un carácter multibyte a medias) se
        guarda hasta la siguiente lectura. Cierra la conexión en cuanto
        envía un evento `run_fin`.

        Important 1 (revisión df61f0d): si no hay datos nuevos, cada
        `_SONDEOS_KEEPALIVE` sondeos (sin esperar a que el fichero cambie)
        se escribe un comentario SSE (`: \\n\\n`) solo para que un `write`/
        `flush` sobre un socket ya cerrado por el cliente falle y lo
        detecte -- si no, un cliente desconectado sobre un run sin
        `run_fin` deja el hilo de sondeo vivo para siempre.

        Anexo 2026-10-04 (D21, Tarea 15): si el run se acaba de lanzar desde
        la página, el navegador puede llegar aquí nada más recibir el 202 de
        `POST /api/lanzar` -- antes de que el subproceso recién arrancado
        haya creado siquiera el directorio o escrito la primera línea. Se
        sondea hasta 30s (ni el directorio ni el fichero tienen por qué
        existir todavía) en vez de dar 404 al primer intento, para no perder
        esa carrera contra el propio subproceso que acabamos de lanzar.

        Retoque del anexo 2026-10-04 (2), Tarea 16: esa espera de 30s SOLO
        tiene sentido para el run que este servidor acaba de lanzar -- para
        cualquier otro (repo, run) que de verdad no existe -- una URL mal
        tecleada, un run antiguo borrado, un intento de sondeo a ciegas --
        no hay ningún subproceso en camino que vaya a crear el fichero, así
        que esperar 30s solo retrasaría un 404 que ya se sabe seguro desde
        el principio. Comparar contra `proc_repo`/`proc_run` (el último
        lanzado, puesto por `_lanzar`) decide cuál es cuál."""
        es_el_ultimo_lanzado = (
            repo == self.server.proc_repo and run == self.server.proc_run  # type: ignore[attr-defined]
        )
        limite = time.monotonic() + (_ESPERA_DIRECTO_MAX_S if es_el_ultimo_lanzado else 0)
        eventos_path = None
        while True:
            # D33: con una URL, el run no existe hasta que acaba el clon. Se
            # espera mientras el proceso siga vivo; si ya acabó sin crear el
            # run (repo privado, copia ajena, cerrojo), no hay nada que esperar
            # -- el motivo lo cuenta `/api/lanzador`. `terminado` se lee ANTES
            # de mirar el disco: si el proceso crea el fichero y sale entre
            # las dos cosas, no se pierde.
            proc = self.server.proc  # type: ignore[attr-defined]
            terminado = es_el_ultimo_lanzado and (proc is None or proc.poll() is not None)
            run_dir = _resuelve_dentro(self.server.salidas, f"{repo}/{run}")  # type: ignore[attr-defined]
            if run_dir is not None and run_dir.is_dir():
                candidato = run_dir / "eventos.jsonl"
                if candidato.is_file():
                    eventos_path = candidato
                    break
            if not es_el_ultimo_lanzado or terminado or time.monotonic() >= limite:
                self.send_error(404)
                return
            time.sleep(0.3)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        _SONDEOS_KEEPALIVE = 2  # ~1 s de inactividad (sondeo cada 0,5 s)
        sondeos_sin_datos = 0
        resto = b""
        with eventos_path.open("rb") as f:
            while True:
                trozo = f.read()
                if not trozo:
                    sondeos_sin_datos += 1
                    if sondeos_sin_datos >= _SONDEOS_KEEPALIVE:
                        sondeos_sin_datos = 0
                        try:
                            self.wfile.write(b": \n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            return  # cliente desconectado: cierra sin traza
                    time.sleep(0.5)
                    continue

                sondeos_sin_datos = 0
                resto += trozo
                *completas, resto = resto.split(b"\n")
                for linea_bytes in completas:
                    if not linea_bytes.strip():
                        continue
                    try:
                        linea = linea_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        continue  # línea realmente corrupta (no solo partida): se descarta
                    try:
                        self.wfile.write(f"data: {linea}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return  # cliente desconectado: cierra sin traza
                    try:
                        evento = json.loads(linea)
                        tipo = evento.get("tipo") if isinstance(evento, dict) else None
                    except json.JSONDecodeError:
                        tipo = None
                    if tipo == "run_fin":
                        # D24 (anexo 2026-10-04 (3)): si hay un proceso en
                        # marcha para este MISMO (repo, run) -- una
                        # continuación lanzada por `/api/reanudar` mientras
                        # este directo seguía abierto -- no se cierra: el
                        # mismo `eventos.jsonl` va a seguir creciendo (un
                        # `reanudado` y lo que venga después) y cerrar aquí
                        # dejaría al navegador sin verlo. Para cualquier otro
                        # caso (el run de verdad ha terminado, o el proceso
                        # en marcha es de OTRO run), cierra igual que antes.
                        proc = self.server.proc  # type: ignore[attr-defined]
                        sigue_en_marcha = (
                            proc is not None
                            and proc.poll() is None
                            and repo == self.server.proc_repo  # type: ignore[attr-defined]
                            and run == self.server.proc_run  # type: ignore[attr-defined]
                        )
                        if not sigue_en_marcha:
                            return


def crear_servidor(
    host: str,
    puerto: int,
    salidas: Path,
    estaticos: Path,
    *,
    raiz_repos: Path | None = None,
    comando: Callable[[list[str]], list[str]] | None = None,
    dir_logs: Path = _RAIZ_ENJAMBRE / "logs" / "lanzamientos",
    raiz_cola: Path | None = None,
    cerrojo: Path | None = None,
    pesar: Callable[[Fuente], peso_mod.Peso] | None = None,
) -> ThreadingHTTPServer:
    """Crea el servidor sin arrancarlo (el llamador decide hilo/`serve_forever`,
    como hace `tests/test_pantalla.py` y `main` de abajo).

    `raiz_repos`/`comando`/`dir_logs` son del anexo 2026-10-04 (Tarea 15,
    D21, "lanzar el run desde la página"): `raiz_repos` acota qué repos se
    pueden lanzar (`_valida_lanzar`); `comando` decide el argv real del
    subproceso (por defecto `[sys.executable, "-m", "enjambre.orquestar",
    *args]` -- las pruebas lo sustituyen por un proceso de mentira que no
    importa nada de `enjambre` ni gasta un token, ver `tests/test_pantalla.py`);
    `dir_logs` es dónde cae el stdout+stderr combinado de cada run lanzado
    así (un fichero por run, `<run>.log`).

    Fase 3 (D31, D33): `comando` por defecto lanza `enjambre.leer`, que
    acepta una URL o una ruta; `raiz_cola` es el directorio de la cola de la
    noche y `cerrojo` el fichero del cerrojo de máquina. Los dos son `None` y
    se resuelven aquí, no en la firma: un valor por defecto en la firma se
    fija al importar y las pruebas no podrían redirigirlo."""

    class _Servidor(ThreadingHTTPServer):
        # D12: cada conexión (incluidas las SSE, que se quedan abiertas
        # sondeando) en su propio hilo daemon, para que no impidan salir.
        daemon_threads = True
        allow_reuse_address = True

    servidor = _Servidor((host, puerto), _ManejadorPantalla)
    servidor.salidas = salidas  # type: ignore[attr-defined]
    servidor.estaticos = estaticos  # type: ignore[attr-defined]
    servidor.raiz_repos = raiz_repos or config.raiz_local()  # type: ignore[attr-defined]  # D44: se lee al llamar
    servidor.comando = comando or (lambda args: [sys.executable, "-m", "enjambre.leer", *args])  # type: ignore[attr-defined]
    servidor.raiz_cola = raiz_cola or cola_mod.RAIZ_COLA  # type: ignore[attr-defined]
    servidor.cerrojo = cerrojo or cerrojo_mod.RUTA  # type: ignore[attr-defined]
    servidor.pesar = pesar or peso_mod.pesar_fuente  # type: ignore[attr-defined]  # D40: inyectable en pruebas
    servidor.dir_logs = dir_logs  # type: ignore[attr-defined]
    # Un run a la vez (D21): `lock` protege el check-y-arranca de
    # `_lanzar`/`_parar` contra dos POST concurrentes; `proc`/`proc_repo`/
    # `proc_run` son el único estado que este servidor guarda sobre el
    # subproceso -- nunca importa `enjambre.orquestar` para saber más.
    servidor.lock = threading.Lock()  # type: ignore[attr-defined]
    servidor.proc = None  # type: ignore[attr-defined]
    servidor.proc_lanzado_en = None  # type: ignore[attr-defined]
    servidor.proc_repo = None  # type: ignore[attr-defined]
    servidor.proc_run = None  # type: ignore[attr-defined]
    servidor.proc_log = None  # type: ignore[attr-defined]
    return servidor


def _crear_analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(prog="python -m enjambre.pantalla")
    # Mismo patrón que enjambre.orquestar._crear_analizador: absoluto y
    # relativo a este fichero, no al cwd desde donde se invoque.
    raiz = Path(__file__).resolve().parent.parent
    # D44: sin --host sale de `config.host()` (ENJAMBRE_HOST o 127.0.0.1); nunca 0.0.0.0 (D12).
    analizador.add_argument("--host", default=None)
    analizador.add_argument("--puerto", type=int, default=None)
    analizador.add_argument("--salidas", type=Path, default=raiz / "salidas")
    analizador.add_argument("--estaticos", type=Path, default=raiz / "pantalla")
    return analizador


def main(argv: list[str] | None = None) -> int:
    """`python -m enjambre.pantalla [--host] [--puerto] [--salidas] [--estaticos]`."""
    args = _crear_analizador().parse_args(argv)
    host = args.host or config.host()
    puerto = config.puerto() if args.puerto is None else args.puerto
    servidor = crear_servidor(host, puerto, args.salidas, args.estaticos)
    print(f"pantalla escuchando en http://{host}:{servidor.server_address[1]}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.shutdown()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
