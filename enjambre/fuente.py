"""
La fuente de una lectura (fase 3, D26 y D27): una URL pública de GitHub o una
ruta local bajo `/data`.

`resolver` normaliza y valida (pura: ni `git` ni red). `actualizar` deja la
copia local al día y devuelve `(ruta, commit)`. **Este es el único módulo que
llama a `git`.**

Dos riesgos gobiernan casi todo el código:

- La URL acaba en el argv de `git` y el nombre del repo en una ruta de disco
  sobre la que se hace `reset --hard` y `clean -fdx`. Por eso: lista de
  argumentos (nunca `shell=True`), `--` antes de URL y ruta, nombre validado
  con una lista blanca, y comprobación de que la ruta resuelta cuelga
  directamente de `raiz_copias` antes de tocar nada.
- Un repo privado o inexistente hace que `git` pregunte usuario y contraseña
  por terminal, y una noche entera se queda colgada. Todo `git` va sin
  terminal, sin helpers de credenciales, sin stdin y con timeout.
"""

import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

RAIZ_COPIAS = Path("/data/github-abordaje")

# Lista blanca, no lista negra: `.`/`..` y lo que empiece por `-` se rechazan
# aparte (un nombre así sería una ruta o una opción de git, no un repo).
_NOMBRE = re.compile(r"[A-Za-z0-9_.-]+")
_HOSTS = {"github.com", "www.github.com"}


class FuenteInvalida(ValueError): ...


class CopiaAjena(RuntimeError):
    """El directorio existe y no es una copia de esta URL."""


class GitFallo(RuntimeError):
    """Clonar o actualizar falló (privado, inexistente, red, timeout)."""


@dataclass(frozen=True)
class Fuente:
    texto: str  # forma canónica: "https://github.com/<dueño>/<repo>" o ruta absoluta resuelta
    nombre: str  # <repo>, o el nombre del directorio local
    url: str | None  # = texto si es de GitHub; None si es local


def _nombre_valido(nombre: str) -> bool:
    return bool(_NOMBRE.fullmatch(nombre)) and nombre not in (".", "..") and not nombre.startswith("-")


def _resolver_url(texto: str) -> Fuente:
    partes = urlsplit(texto)
    # `netloc` exacto: sin usuario@, sin :puerto. Un `https://github.com@evil/...`
    # tiene host `evil`, y aquí ni siquiera llegaría a coincidir con `_HOSTS`.
    if partes.scheme not in ("http", "https") or partes.netloc.lower() not in _HOSTS:
        raise FuenteInvalida(f"no es una URL de github.com ni una ruta absoluta: {texto!r}")
    trozos = [t for t in partes.path.split("/") if t]
    if len(trozos) < 2:
        raise FuenteInvalida(f"falta el dueño o el repo en la URL: {texto!r}")
    dueno, repo = trozos[0], trozos[1]
    repo = repo.removesuffix(".git")
    if not _nombre_valido(dueno) or not _nombre_valido(repo):
        raise FuenteInvalida(f"dueño o repo con caracteres no válidos: {texto!r}")
    # GitHub no distingue mayúsculas en el dueño: se normaliza para que dos
    # escrituras de la misma URL no se vean como orígenes distintos (D27).
    canon = f"https://github.com/{dueno.lower()}/{repo}"
    return Fuente(texto=canon, nombre=repo, url=canon)


def resolver(
    texto: str, *, raiz_local: Path = Path("/data"), raiz_copias: Path = RAIZ_COPIAS
) -> Fuente:
    texto = texto.strip()
    if not texto:
        raise FuenteInvalida("fuente vacía")
    if "://" in texto or texto.startswith("git@"):
        return _resolver_url(texto)
    if not texto.startswith("/"):
        raise FuenteInvalida(f"no es una URL de github.com ni una ruta absoluta: {texto!r}")

    ruta = Path(texto).resolve()
    if not ruta.is_dir():
        raise FuenteInvalida(f"no existe el directorio {texto!r}")
    copias = raiz_copias.resolve()
    if ruta == copias or ruta.is_relative_to(copias):
        raise FuenteInvalida(
            f"{texto!r} es una copia del enjambre: dale la URL de GitHub, no la ruta de la copia"
        )
    # Estrictamente dentro: la propia raíz (`/data`) no es un proyecto.
    if ruta == raiz_local.resolve() or not ruta.is_relative_to(raiz_local.resolve()):
        raise FuenteInvalida(f"{texto!r} no está bajo {raiz_local}")
    return Fuente(texto=str(ruta), nombre=ruta.name, url=None)


def _entorno() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        SSH_ASKPASS="",
        GCM_INTERACTIVE="never",
        # El clon de una URL de GitHub solo habla https; `file` es para las
        # pruebas, con repos bare locales. Nada de `ext::` ni `ssh`.
        GIT_ALLOW_PROTOCOL="https:file",
    )
    return env


def _git(args: list[str], cwd: Path | None, timeout_s: float) -> str:
    # `credential.helper=` vacío: ningún helper (de sistema o de usuario) puede
    # abrir un diálogo ni servir una credencial ajena.
    argv = ["git", "-c", "credential.helper=", *args]
    try:
        # Sesión propia para poder matar también a `git-remote-https` si hay
        # timeout: matar solo a `git` dejaría al hijo colgado.
        p = subprocess.Popen(
            argv,
            cwd=cwd,
            env=_entorno(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        raise GitFallo(f"no se pudo ejecutar git: {e}") from e
    try:
        salida, error = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:  # acabó justo ahora
            pass
        p.communicate()
        raise GitFallo(f"git {args[0]} tardó más de {timeout_s:g}s") from None
    if p.returncode != 0:
        ultima = next((l for l in reversed(error.splitlines()) if l.strip()), "sin mensaje")
        pista = ""
        if any(s in error for s in ("terminal prompts disabled", "could not read Username", "not found")):
            pista = " (¿repo privado o inexistente?)"
        raise GitFallo(f"git {args[0]} falló ({p.returncode}): {ultima.strip()}{pista}")
    return salida.strip()


def _canonico(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git")


def _commit(ruta: Path, timeout_s: float) -> str:
    return _git(["rev-parse", "HEAD"], ruta, timeout_s)


def actualizar(
    f: Fuente,
    *,
    raiz_copias: Path = RAIZ_COPIAS,
    remoto: str | None = None,
    timeout_s: float = 300,
) -> tuple[Path, str | None]:
    """Deja la copia al día y devuelve `(ruta, commit)`.

    Una fuente local no se toca: solo se lee su commit (`None` si no es un
    repo git). `remoto` sustituye a `f.url` como URL de clonado (pruebas).
    """
    if f.url is None:
        ruta = Path(f.texto)
        if not (ruta / ".git").exists():
            return ruta, None
        try:
            return ruta, _commit(ruta, timeout_s)
        except GitFallo:
            return ruta, None

    # `Fuente` es un dataclass público: se puede construir a mano, así que el
    # nombre se vuelve a validar aquí, donde pesa, y no solo en `resolver`.
    if not _nombre_valido(f.nombre):
        raise FuenteInvalida(f"nombre de repo no válido: {f.nombre!r}")
    origen = remoto or f.url
    copias = raiz_copias.resolve()
    ruta = raiz_copias / f.nombre
    # Todo lo destructivo (reset, clean, rmtree) cuelga de esta comprobación:
    # la ruta resuelta tiene que ser exactamente <raiz_copias>/<nombre>. Si
    # `ruta` fuese un symlink hacia otro sitio, no pasa.
    if ruta.resolve() != copias / f.nombre:
        raise CopiaAjena(f"{ruta} no cuelga directamente de {copias}")

    if not ruta.exists():
        copias.mkdir(parents=True, exist_ok=True)
        try:
            _git(["clone", "--depth", "1", "--", origen, str(ruta)], None, timeout_s)
        except GitFallo:
            # `git clone` limpia lo suyo si falla, pero no si lo matamos por
            # timeout. Aquí sabemos que el directorio no existía antes.
            shutil.rmtree(ruta, ignore_errors=True)
            raise
        return ruta, _commit(ruta, timeout_s)

    # Existe: tiene que ser un repo propio (no un directorio dentro de otro
    # repo, donde `git` actuaría sobre el de arriba) y de esta misma URL.
    if not (ruta / ".git").exists():
        raise CopiaAjena(f"{ruta} existe y no es un repo git")
    try:
        raiz_repo = Path(_git(["rev-parse", "--show-toplevel"], ruta, timeout_s)).resolve()
        origin = _git(["remote", "get-url", "origin"], ruta, timeout_s)
    except GitFallo as e:
        raise CopiaAjena(f"{ruta} existe y no se puede leer su origin: {e}") from e
    if raiz_repo != ruta.resolve():
        raise CopiaAjena(f"{ruta} no es la raíz de su repo git")
    if _canonico(origin) != _canonico(origen):
        raise CopiaAjena(f"{ruta} es una copia de {origin}, no de {origen}")

    # `fetch origin HEAD` (rama por defecto del remoto, D27) y no `origin
    # <rama>`: el clon `--depth 1` es de una sola rama, y si el remoto cambia
    # su rama por defecto, un fetch por la refspec guardada seguiría trayendo
    # la antigua.
    _git(["fetch", "--depth", "1", "origin", "HEAD"], ruta, timeout_s)
    _git(["reset", "--hard", "FETCH_HEAD"], ruta, timeout_s)
    _git(["clean", "-fdx"], ruta, timeout_s)
    return ruta, _commit(ruta, timeout_s)
