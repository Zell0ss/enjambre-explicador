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
    # D37: la identidad de un repo de GitHub va en minúsculas (dueño Y repo).
    # GitHub no distingue mayúsculas, y con ellas un mismo repo tendría dos
    # copias en disco y dos notas. Se pasa a minúsculas ANTES de quitar `.git`.
    dueno, repo = trozos[0].lower(), trozos[1].lower().removesuffix(".git")
    if not _nombre_valido(dueno) or not _nombre_valido(repo):
        raise FuenteInvalida(f"dueño o repo con caracteres no válidos: {texto!r}")
    canon = f"https://github.com/{dueno}/{repo}"
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
            # Un nombre de fichero que no sea UTF-8 (`ls-files`) no debe tumbar la lectura.
            errors="replace",
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


def ficheros(ruta: Path, timeout_s: float = 60) -> list[str] | None:
    """Rutas relativas que sigue git (`ls-files -z`), o `None` si `ruta` no es la
    raíz de un repo (carpeta sin git, o un subdirectorio de otro repo: `git`
    actuaría sobre el de arriba). Solo lee: no modifica nada (D40)."""
    if not (ruta / ".git").exists():
        return None
    try:
        raiz = Path(_git(["rev-parse", "--show-toplevel"], ruta, timeout_s)).resolve()
    except GitFallo:
        return None
    if raiz != ruta.resolve():
        return None
    salida = _git(["ls-files", "-z"], ruta, timeout_s)
    return [r for r in salida.split("\0") if r]


def clonar(f: Fuente, destino: Path, *, remoto: str | None = None, timeout_s: float = 120) -> str:
    """Clon `--depth 1` de una URL en `destino` (que no existe) y devuelve su commit.

    Sin marca D38: es un temporal (D40, `peso.pesar_fuente`), nunca una copia de
    `raiz_copias`. Si falla, no queda nada a medias."""
    if f.url is None:
        raise FuenteInvalida("solo se clona una URL de GitHub")
    if destino.exists():
        raise FileExistsError(f"{destino} ya existe")
    try:
        _git(["clone", "--depth", "1", "--", remoto or f.url, str(destino)], None, timeout_s)
        return _commit(destino, timeout_s)
    except GitFallo:
        shutil.rmtree(destino, ignore_errors=True)  # no existía antes: es todo nuestro
        raise


def _canonico(url: str) -> str:
    # Solo para comparar orígenes: GitHub no distingue mayúsculas ni en el dueño
    # ni en el repo, y una copia clonada a mano puede traer el `origin` tal
    # cual se escribió. La forma canónica de `Fuente` y el nombre del
    # directorio sí conservan las mayúsculas del repo.
    return url.strip().rstrip("/").removesuffix(".git").lower()


# D38: dentro de `.git`, para que ni `clean` ni un `git add .` la toquen.
_MARCA = "enjambre"
_SALIDA = "si es una copia del enjambre, bórrala y se volverá a clonar"


def _marcar(ruta: Path, commit: str) -> None:
    """Escribe la marca de propiedad: el commit que el enjambre ha dejado."""
    (ruta / ".git" / _MARCA).write_text(commit + "\n", encoding="utf-8")


def _comprobar_intacta(ruta: Path, timeout_s: float) -> None:
    """D38. `CopiaAjena` (sin tocar nada) salvo que la copia lleve la marca del
    enjambre y siga exactamente como la dejó: sin cambios ni ficheros nuevos
    (ignorados incluidos), una sola rama local y `HEAD` en el commit de la marca.
    Cualquier commit local cambia `HEAD`; cualquier rama nueva, el recuento."""
    git_dir = ruta / ".git"
    if not git_dir.is_dir():
        raise CopiaAjena(f"{ruta} no tiene un .git propio; {_SALIDA}")
    try:
        marca = (git_dir / _MARCA).read_text(encoding="utf-8").strip()
    except OSError:
        raise CopiaAjena(f"{ruta} existe y no tiene la marca del enjambre (no la clonó él); {_SALIDA}") from None

    trabajo = []
    try:
        estado = _git(["status", "--porcelain", "--ignored"], ruta, timeout_s)
        ramas = _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], ruta, timeout_s).split()
        cabeza = _commit(ruta, timeout_s)
    except GitFallo as e:
        raise CopiaAjena(f"{ruta} no se puede inspeccionar ({e}); {_SALIDA}") from e
    if estado:
        lineas = estado.splitlines()
        trabajo.append("ficheros sin guardar o ignorados: " + ", ".join(l.strip() for l in lineas[:5]) + (" …" if len(lineas) > 5 else ""))
    if len(ramas) != 1:
        trabajo.append("ramas locales: " + (", ".join(ramas) or "ninguna"))
    if cabeza != marca:
        trabajo.append(f"commit local: HEAD {cabeza[:7]} y el enjambre dejó {marca[:7]}")
    if trabajo:
        raise CopiaAjena(f"la copia tiene trabajo local en {ruta}: {'; '.join(trabajo)}; {_SALIDA}")


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
            commit = _commit(ruta, timeout_s)
            _marcar(ruta, commit)
        except (GitFallo, OSError):
            # `git clone` limpia lo suyo si falla, pero no si lo matamos por
            # timeout, y sin marca la copia sería "ajena" para siempre (D38).
            # Aquí sabemos que el directorio no existía antes.
            shutil.rmtree(ruta, ignore_errors=True)
            raise
        return ruta, commit

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

    # D38: que la copia sea de esta URL no demuestra que sea desechable. Solo
    # se toca una copia que el enjambre clonó (marca) y que nadie ha tocado.
    _comprobar_intacta(ruta, timeout_s)

    # `fetch origin HEAD` (rama por defecto del remoto, D27) y no `origin
    # <rama>`: el clon `--depth 1` es de una sola rama, y si el remoto cambia
    # su rama por defecto, un fetch por la refspec guardada seguiría trayendo
    # la antigua.
    _git(["fetch", "--depth", "1", "origin", "HEAD"], ruta, timeout_s)
    _git(["reset", "--hard", "FETCH_HEAD"], ruta, timeout_s)
    # Sin `clean -fdx` (D27 lo tenía): la copia está intacta, no hay nada que
    # limpiar, y cada comando destructivo de menos es una defensa más.
    commit = _commit(ruta, timeout_s)
    _marcar(ruta, commit)
    return ruta, commit
