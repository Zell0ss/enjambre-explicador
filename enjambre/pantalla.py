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


def _valida_lanzar(cuerpo: dict, raiz_repos: Path) -> tuple[Path, float, int, bool] | str:
    """Valida el cuerpo de `POST /api/lanzar` (anexo 2026-10-04, Tarea 15,
    D21). Devuelve `(repo, tope_usd, max_vueltas, falso)` ya validados y
    listos para pasar a `comando`, o un string con el motivo del rechazo
    (400) -- nunca lanza: toda entrada de red es sospechosa por defecto,
    mismo criterio que `_resuelve_dentro` para las rutas de `/api/fichero`.

    `isinstance(x, bool)` antes que `isinstance(x, (int, float))` en
    `tope_usd`/`max_vueltas` porque `bool` es subclase de `int` en Python --
    sin ese orden, `{"tope_usd": true}` colaría como `tope_usd=1`."""
    repo = cuerpo.get("repo")
    if not isinstance(repo, str) or not repo:
        return "repo debe ser una ruta no vacía"
    try:
        repo_path = Path(repo).resolve()
    except (OSError, ValueError):
        return "repo no es una ruta válida"
    raiz_r = raiz_repos.resolve()
    if not (repo_path == raiz_r or repo_path.is_relative_to(raiz_r)):
        return f"repo debe estar bajo {raiz_r}"
    if not repo_path.is_dir():
        return "repo no es un directorio existente"

    tope_usd = cuerpo.get("tope_usd")
    if isinstance(tope_usd, bool) or not isinstance(tope_usd, (int, float)) or not (0 < tope_usd <= 10):
        return "tope_usd debe ser un número mayor que 0 y como mucho 10"

    max_vueltas = cuerpo.get("max_vueltas")
    if isinstance(max_vueltas, bool) or not isinstance(max_vueltas, int) or not (0 <= max_vueltas <= 3):
        return "max_vueltas debe ser un entero entre 0 y 3"

    falso = cuerpo.get("falso")
    if not isinstance(falso, bool):
        return "falso debe ser un booleano"

    return repo_path, float(tope_usd), max_vueltas, falso


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
        if ruta not in ("/api/lanzar", "/api/parar"):
            self.send_error(404)
            return

        tipo_contenido = self.headers.get("Content-Type", "").split(";")[0].strip()
        if tipo_contenido != "application/json" or self.headers.get("X-Enjambre") != "1":
            self._responde_json(403, {"error": "faltan cabeceras anti-CSRF"})
            return

        if ruta == "/api/lanzar":
            self._lanzar()
        else:
            self._parar()

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
        repo_path, tope_usd, max_vueltas, falso = validado

        with self.server.lock:  # type: ignore[attr-defined]
            proc = self.server.proc  # type: ignore[attr-defined]
            if proc is not None and proc.poll() is None:
                self._responde_json(409, {"error": "ya hay un run en marcha"})
                return

            # Con segundos (no solo %Y%m%d-%H%M como el nombre por defecto
            # de `orquestar()`) para no chocar si Josem lanza dos veces
            # seguidas dentro del mismo minuto.
            run = f"{repo_path.name}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
            args = [
                "--repo",
                str(repo_path),
                "--salidas",
                str(self.server.salidas),  # type: ignore[attr-defined]
                "--tope-usd",
                str(tope_usd),
                "--max-vueltas",
                str(max_vueltas),
                "--run",
                run,
            ]
            if falso:
                args.append("--falso")
            argv = self.server.comando(args)  # type: ignore[attr-defined]

            dir_logs = self.server.dir_logs  # type: ignore[attr-defined]
            dir_logs.mkdir(parents=True, exist_ok=True)
            with open(dir_logs / f"{run}.log", "wb") as log_fh:
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
            self.server.proc_repo = repo_path.name  # type: ignore[attr-defined]
            self.server.proc_run = run  # type: ignore[attr-defined]

        self._responde_json(202, {"repo": repo_path.name, "run": run})

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
        self._responde_json(
            200,
            {
                "en_marcha": en_marcha,
                "repo": self.server.proc_repo if en_marcha else None,  # type: ignore[attr-defined]
                "run": self.server.proc_run if en_marcha else None,  # type: ignore[attr-defined]
            },
        )

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
        esa carrera contra el propio subproceso que acabamos de lanzar."""
        plazo = time.monotonic() + 30
        eventos_path = None
        while True:
            run_dir = _resuelve_dentro(self.server.salidas, f"{repo}/{run}")  # type: ignore[attr-defined]
            if run_dir is not None and run_dir.is_dir():
                candidato = run_dir / "eventos.jsonl"
                if candidato.is_file():
                    eventos_path = candidato
                    break
            if time.monotonic() >= plazo:
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
                        return


def crear_servidor(
    host: str,
    puerto: int,
    salidas: Path,
    estaticos: Path,
    *,
    raiz_repos: Path = Path("/data"),
    comando: Callable[[list[str]], list[str]] | None = None,
    dir_logs: Path = _RAIZ_ENJAMBRE / "logs" / "lanzamientos",
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
    así (un fichero por run, `<run>.log`)."""

    class _Servidor(ThreadingHTTPServer):
        # D12: cada conexión (incluidas las SSE, que se quedan abiertas
        # sondeando) en su propio hilo daemon, para que no impidan salir.
        daemon_threads = True
        allow_reuse_address = True

    servidor = _Servidor((host, puerto), _ManejadorPantalla)
    servidor.salidas = salidas  # type: ignore[attr-defined]
    servidor.estaticos = estaticos  # type: ignore[attr-defined]
    servidor.raiz_repos = raiz_repos  # type: ignore[attr-defined]
    servidor.comando = comando or (lambda args: [sys.executable, "-m", "enjambre.orquestar", *args])  # type: ignore[attr-defined]
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
    return servidor


def _crear_analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(prog="python -m enjambre.pantalla")
    # Mismo patrón que enjambre.orquestar._crear_analizador: absoluto y
    # relativo a este fichero, no al cwd desde donde se invoque.
    raiz = Path(__file__).resolve().parent.parent
    analizador.add_argument("--host", default="100.87.64.121")  # nunca 0.0.0.0 (D12)
    analizador.add_argument("--puerto", type=int, default=8790)
    analizador.add_argument("--salidas", type=Path, default=raiz / "salidas")
    analizador.add_argument("--estaticos", type=Path, default=raiz / "pantalla")
    return analizador


def main(argv: list[str] | None = None) -> int:
    """`python -m enjambre.pantalla [--host] [--puerto] [--salidas] [--estaticos]`."""
    args = _crear_analizador().parse_args(argv)
    servidor = crear_servidor(args.host, args.puerto, args.salidas, args.estaticos)
    print(f"pantalla escuchando en http://{args.host}:{servidor.server_address[1]}")
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
