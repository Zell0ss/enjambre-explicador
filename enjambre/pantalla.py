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
import json
import mimetypes
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Rutas de §5.1 del diseño. Los grupos de repo/run son `[^/]+` (un solo
# segmento); `<ruta...>` de /api/fichero es `.+` (puede llevar más barras:
# es una ruta de fichero dentro del run, no un nombre suelto).
_RUTA_FICHERO = re.compile(r"^/api/fichero/([^/]+)/([^/]+)/(.+)$")
_RUTA_EVENTOS = re.compile(r"^/api/eventos/([^/]+)/([^/]+)\.jsonl$")
_RUTA_DIRECTO = re.compile(r"^/api/directo/([^/]+)/([^/]+)$")
_RUTA_STATIC = re.compile(r"^/static/(.+)$")
# Nombres simples para /static: sin barras, así que por construcción ya
# bloquea "../secreto.txt" (contiene "/"). No bloquea ".." a solas (son solo
# puntos, caracter permitido) -- de eso se encarga _resuelve_dentro debajo.
_NOMBRE_STATIC = re.compile(r"^[A-Za-z0-9._-]+$")


def _resuelve_dentro(base: Path, ruta_relativa: str) -> Path | None:
    """Junta `ruta_relativa` (ya decodificada por el llamador) con `base` y
    resuelve el resultado contra el disco real. Si se escapa de `base`
    (cualquier `..`, incluido uno que solo aparece tras decodificar un
    `%2F`, o un symlink dentro de `base` que apunte fuera) devuelve `None`:
    es el único punto de autorización de las rutas con entrada de usuario."""
    base_r = base.resolve()
    candidato = base_r
    for segmento in ruta_relativa.split("/"):
        if segmento in ("", "."):
            continue
        candidato = candidato / segmento
    candidato = candidato.resolve()
    if candidato == base_r or candidato.is_relative_to(base_r):
        return candidato
    return None


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
                            inicio = json.loads(primera).get("t")
                        except json.JSONDecodeError:
                            inicio = None
                    for linea in f:
                        linea = linea.strip()
                        if not linea:
                            continue
                        try:
                            evento = json.loads(linea)
                        except json.JSONDecodeError:
                            continue  # línea corrupta: se ignora, no tumba /api/runs
                        if evento.get("tipo") == "run_fin":
                            motivo = evento.get("motivo")
            except OSError:
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
        sondea cada 0,5 s. Solo se emite una línea cuando está completa
        (terminada en `\\n`); el resto a medio escribir se guarda hasta la
        siguiente lectura (Foco de revisión #3: 8 lectores escribiendo a la
        vez no debe producir un `data:` con JSON roto). Cierra la conexión
        en cuanto envía un evento `run_fin`."""
        run_dir = _resuelve_dentro(self.server.salidas, f"{repo}/{run}")  # type: ignore[attr-defined]
        if run_dir is None or not run_dir.is_dir():
            self.send_error(404)
            return
        eventos_path = run_dir / "eventos.jsonl"
        if not eventos_path.is_file():
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        resto = ""
        with eventos_path.open("r", encoding="utf-8") as f:
            while True:
                trozo = f.read()
                if not trozo:
                    time.sleep(0.5)
                    continue
                resto += trozo
                *completas, resto = resto.split("\n")
                for linea in completas:
                    if not linea.strip():
                        continue
                    self.wfile.write(f"data: {linea}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    try:
                        tipo = json.loads(linea).get("tipo")
                    except json.JSONDecodeError:
                        tipo = None
                    if tipo == "run_fin":
                        return


def crear_servidor(host: str, puerto: int, salidas: Path, estaticos: Path) -> ThreadingHTTPServer:
    """Crea el servidor sin arrancarlo (el llamador decide hilo/`serve_forever`,
    como hace `tests/test_pantalla.py` y `main` de abajo)."""

    class _Servidor(ThreadingHTTPServer):
        # D12: cada conexión (incluidas las SSE, que se quedan abiertas
        # sondeando) en su propio hilo daemon, para que no impidan salir.
        daemon_threads = True
        allow_reuse_address = True

    servidor = _Servidor((host, puerto), _ManejadorPantalla)
    servidor.salidas = salidas  # type: ignore[attr-defined]
    servidor.estaticos = estaticos  # type: ignore[attr-defined]
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
