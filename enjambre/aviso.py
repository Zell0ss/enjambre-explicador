"""
Aviso por Telegram (D32, D34): La borracha, el bot de mangataro, con su token y
su chat en un `.env` propio del enjambre (nunca el de mangataro).

`enviar` **nunca lanza**: si el aviso falla, va a LogCentral y no falla el run.
"""

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from enjambre.registro import obtener_log
from enjambre.tipos import Lectura

# parent = enjambre/, parent.parent = raíz del repo.
RUTA_ENV = Path(__file__).resolve().parent.parent / ".env"
_LIMITE = 4096  # máximo de un mensaje de Telegram


def cargar_env(ruta: Path = RUTA_ENV) -> dict[str, str]:
    """`CLAVE=valor` por línea; sin fichero, vacío. Ignora comentarios y comillas."""
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    env = {}
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        clave, sep, valor = linea.removeprefix("export ").partition("=")
        if not sep:
            continue
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        env[clave.strip()] = valor
    return env


def _post_http(url: str, datos: dict) -> int:
    peticion = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def enviar(texto: str, *, env: dict | None = None, post=None) -> bool:
    """Manda `texto` por Telegram. `post(url, datos) -> código HTTP`."""
    env = cargar_env() if env is None else env
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        _avisar("aviso: faltan TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID en el .env del enjambre, no se envía")
        return False
    try:
        codigo = (post or _post_http)(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat, "text": texto[:_LIMITE]},
        )
    except Exception as e:  # noqa: BLE001 -- el aviso jamás debe tumbar un run
        # El mensaje de la excepción podría llevar la URL, y la URL lleva el token.
        _avisar(f"aviso: el envío falló ({type(e).__name__}: {str(e).replace(token, '***')})")
        return False
    if codigo != 200:
        _avisar(f"aviso: Telegram contestó HTTP {codigo}")
        return False
    return True


def _avisar(mensaje: str) -> None:
    try:
        obtener_log().warning(mensaje)
    except Exception:  # noqa: BLE001 -- ni siquiera el log puede propagar
        pass


def texto_run(l: Lectura) -> str:
    cabecera = f"enjambre: {l.nombre}"
    if l.motivo == "sin_cambios":
        return f"{cabecera}: sin cambios desde la última lectura (commit {(l.commit or '?')[:7]}), no se ha gastado nada"
    coste = f"{l.coste_usd:.2f} $"
    if l.nota is not None:
        veredicto = "aprobado" if l.motivo == "aprobado" else f"sin aprobar tras {l.vueltas} vueltas"
        return f"{cabecera}: {veredicto} · {coste}\nNota: {l.nota}"
    return (
        f"{cabecera}: parado ({l.motivo}) · {coste}\n"
        "Se puede seguir con Continuar en la página; si estaba en la cola, la noche siguiente lo retoma."
    )


def texto_noche(resumen: dict) -> str:
    lineas = ["enjambre: resumen de la noche"]
    for l in resumen["lecturas"]:
        if l.motivo == "sin_cambios":
            lineas.append(f"· {l.nombre}: sin cambios")
        elif l.nota is not None:
            lineas.append(f"· {l.nombre}: {l.motivo}, {l.coste_usd:.2f} $")
        else:
            lineas.append(f"· {l.nombre}: parado ({l.motivo}), {l.coste_usd:.2f} $")
    for fuente, error in resumen["errores"]:
        lineas.append(f"✗ {fuente}: {error}")
    lineas.append(f"Gastado: {resumen['gastado_usd']:.2f} $")
    if resumen["parada"]:
        lineas.append(f"La noche paró: {resumen['parada']}")
    lineas.append(f"En la cola quedan {resumen['quedan']}")
    return "\n".join(lineas)
