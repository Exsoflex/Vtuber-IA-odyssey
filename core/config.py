"""
Ajustes de Niu: un solo objeto, validado y persistido.

Por qué existe este módulo
--------------------------
Antes, cada valor se leía con `os.getenv` en el momento de importar el módulo:

    core/idiomas.py   VOZ      = os.getenv("NIU_VOZ") ...
    core/tts.py       TONO     = os.getenv("NIU_TONO") ...
    core/stt.py       SILENCIO = float(os.getenv("NIU_SILENCIO_FINAL")) ...

Eso funciona para una CLI que se lanza una vez, pero hace imposible un panel:
si la interfaz escribe una variable, Python ya la leyó y no vuelve a mirar.
Recargar el módulo tampoco sirve, porque hay estado vivo que no se puede
recargar (modelos en la GPU, el socket de VTube Studio, hilos de audio).

Así que la configuración pasa a ser **un dato**: `Ajustes`. Se lee cuando se
necesita (`ajustes()`), no cuando se importa. Cambiar un valor es cambiar el
objeto; persistirlo es escribir `config.json`.

Precedencia
-----------
    config.json  >  variables de entorno  >  valores por defecto

El JSON gana porque es lo que edita el panel. Las variables de entorno siguen
funcionando para no romper los scripts que ya existen, y son la única fuente
en el primer arranque (cuando todavía no hay `config.json`).

Los secretos NO viven aquí: `GOOGLE_API_KEY`, el token de VTube Studio y demás
se quedan en `.env`, que no se versiona ni se expone en la interfaz.

Por qué la carga es perezosa
----------------------------
`core/idiomas.py` importa este módulo para saber qué idioma está activo. Si
`config` importara `idiomas` al cargarse, el import sería circular y, peor, la
llamada a `ajustes()` desde la validación volvería a entrar en `ajustes()`
mientras todavía está cargando. Por eso `ajustes()` construye el objeto la
primera vez que alguien lo pide, y la validación no importa otros módulos.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

# El `.env` se carga aquí, no en cada punto de entrada. Si lo hiciera solo
# `main.py`, el panel (que importa `core.config` directamente) leería unas
# variables y la consola otras. `load_dotenv` no pisa lo que ya está en el
# entorno, así que una variable puesta en la sesión de PowerShell sigue
# mandando sobre el archivo.
load_dotenv()

# El archivo vive en la raíz del proyecto, no en el directorio desde el que se
# lance Python: si dependiera del cwd, abrir el panel desde otra carpeta
# crearía un config.json distinto y los ajustes "desaparecerían".
RUTA_CONFIG = Path(
    os.getenv("NIU_CONFIG") or Path(__file__).resolve().parent.parent / "config.json"
)

# Formato de los valores que viajan a Edge-TTS. Se validan porque un "+5" sin
# unidad no da error: simplemente Edge-TTS ignora el tono y nadie entiende por
# qué el slider no hace nada.
_RE_TONO = re.compile(r"^[+-]\d{1,3}Hz$")
_RE_VELOCIDAD = re.compile(r"^[+-]\d{1,2}%$")
_RE_IDIOMA = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")

MOTORES_STT = ("whisper", "gemini")


@dataclass(frozen=True)
class Ajustes:
    """Todo lo que se puede cambiar sin tocar código.

    Los valores vacíos significan "lo que diga el perfil de idioma": así, al
    cambiar de español a inglés, la voz y el tono cambian solos si no se han
    forzado a mano. Un `voz=""` no es un error, es "no me fijes la voz".

    Attributes:
        idioma: perfil activo (`es`, `en`). Cambia voz, reglas y oído.
        voz: voz de Edge-TTS. Vacío = la del perfil.
        tono: tono de Edge-TTS (`+0Hz`, `-25Hz`). Vacío = el del perfil.
        velocidad: ritmo de habla (`+0%`, `-8%`).
        microfono: nombre (parcial) del dispositivo de entrada.
        salida: nombre (parcial) del dispositivo de salida. Vacío = el del
            sistema.
        modelo_llm: modelo de Ollama.
        motor_stt: `whisper` (local) o `gemini` (nube).
        modelo_whisper: tamaño del modelo de Whisper.
        silencio_final: segundos de silencio que cierran un turno.
        tts_timeout: segundos antes de rendirse con una frase.
        tts_intentos: reintentos de Edge-TTS.
        temperatura: creatividad del LLM (0 = repetitivo, 2 = caótico).
    """

    idioma: str = "es"
    voz: str = ""
    tono: str = ""
    velocidad: str = "+0%"
    microfono: str = "DGM20 USB Microphone"
    salida: str = ""
    modelo_llm: str = "qwen2.5:7b-instruct-q4_k_m"
    motor_stt: str = "whisper"
    modelo_whisper: str = "large-v3-turbo"
    silencio_final: float = 0.9
    tts_timeout: float = 15.0
    tts_intentos: int = 2
    temperatura: float = 0.9


# Variables de entorno que todavía se aceptan, para no romper el `.env` que ya
# existe. Nombre del campo -> variable.
VARIABLES_ENTORNO: dict[str, str] = {
    "idioma": "NIU_IDIOMA",
    "voz": "NIU_VOZ",
    "tono": "NIU_TONO",
    "velocidad": "NIU_VELOCIDAD",
    "microfono": "NIU_MIC",
    "salida": "NIU_SALIDA",
    "modelo_llm": "OLLAMA_MODEL",
    "motor_stt": "NIU_STT",
    "modelo_whisper": "NIU_WHISPER_MODELO",
    "silencio_final": "NIU_SILENCIO_FINAL",
    "tts_timeout": "NIU_TTS_TIMEOUT",
    "tts_intentos": "NIU_TTS_INTENTOS",
    "temperatura": "NIU_TEMPERATURA",
}

# Rangos sensatos. No son límites técnicos: son los que evitan que un dedo
# resbalado en un slider deje a Niu muda o esperando tres minutos.
_RANGOS = {
    "silencio_final": (0.2, 3.0),
    "tts_timeout": (1.0, 120.0),
    "tts_intentos": (1, 5),
    "temperatura": (0.0, 2.0),
}


def por_defecto() -> Ajustes:
    """Los valores de fábrica, sin mirar entorno ni disco."""
    return Ajustes()


def _leer_entorno() -> dict[str, object]:
    """Valores presentes en el entorno, con su tipo ya convertido.

    Una variable mal escrita no debe impedir arrancar: se ignora y se avisa
    al normalizar, igual que un slider fuera de rango.
    """
    datos: dict[str, object] = {}
    for campo, variable in VARIABLES_ENTORNO.items():
        crudo = os.getenv(variable)
        if crudo is None or not crudo.strip():
            continue
        datos[campo] = crudo.strip()
    return datos


def normalizar(datos: dict[str, object]) -> tuple[Ajustes, list[str]]:
    """Convierte un diccionario suelto en `Ajustes` válidos.

    Es una función pura: no toca disco ni entorno. Devuelve también los avisos,
    porque un valor corregido en silencio es peor que uno rechazado: el panel
    tiene que poder decir «esto no valía, lo he puesto en 0,9 s».

    Args:
        datos: claves iguales a los campos de `Ajustes`. Las desconocidas se
            ignoran: un `config.json` viejo no debe romper una versión nueva.

    Returns:
        `(ajustes, avisos)`.
    """
    base = asdict(Ajustes())
    avisos: list[str] = []

    for campo, valor in datos.items():
        if campo not in base:
            avisos.append(f"ajuste desconocido ignorado: {campo!r}")
            continue
        base[campo] = valor

    # Tipos y formatos.
    for campo in ("silencio_final", "tts_timeout", "temperatura"):
        try:
            base[campo] = float(base[campo])
        except (TypeError, ValueError):
            avisos.append(f"{campo}: {base[campo]!r} no es un número; se usa el valor por defecto")
            base[campo] = getattr(Ajustes(), campo)

    try:
        base["tts_intentos"] = int(float(base["tts_intentos"]))
    except (TypeError, ValueError):
        avisos.append("tts_intentos: no es un número; se usa 2")
        base["tts_intentos"] = 2

    for campo in ("idioma", "voz", "tono", "velocidad", "microfono", "salida",
                  "modelo_llm", "motor_stt", "modelo_whisper"):
        base[campo] = str(base[campo]).strip()

    base["idioma"] = base["idioma"].lower()
    if not _RE_IDIOMA.match(base["idioma"]):
        avisos.append(f"idioma: {base['idioma']!r} no parece un código de idioma; se usa 'es'")
        base["idioma"] = "es"

    if base["tono"] and not _RE_TONO.match(base["tono"]):
        avisos.append(f"tono: {base['tono']!r} no tiene el formato de Edge-TTS (+0Hz); se usa el del perfil")
        base["tono"] = ""

    if not _RE_VELOCIDAD.match(base["velocidad"]):
        avisos.append(f"velocidad: {base['velocidad']!r} no tiene el formato de Edge-TTS (+0%); se usa '+0%'")
        base["velocidad"] = "+0%"

    if base["motor_stt"] not in MOTORES_STT:
        avisos.append(f"motor_stt: {base['motor_stt']!r} no existe; se usa 'whisper'")
        base["motor_stt"] = "whisper"

    # Rangos.
    for campo, (minimo, maximo) in _RANGOS.items():
        valor = base[campo]
        if valor < minimo or valor > maximo:
            avisos.append(f"{campo}: {valor} está fuera de [{minimo}, {maximo}]; se ajusta")
            base[campo] = min(max(valor, minimo), maximo)

    return Ajustes(**base), avisos


def cargar_ajustes(ruta: Path | None = None) -> Ajustes:
    """Lee entorno y `config.json`, en ese orden, y valida el resultado.

    Un `config.json` corrupto no deja a Niu sin arrancar: se avisa y se usan
    los valores del entorno y los de fábrica. Un editor de texto a medias no
    debería costar una sesión de depuración.
    """
    ruta = ruta or RUTA_CONFIG
    datos = _leer_entorno()

    if ruta.exists():
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(contenido, dict):
                datos.update(contenido)
            else:
                print(f"[CONFIG] {ruta.name} no contiene un objeto JSON; se ignora")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[CONFIG] No se pudo leer {ruta.name}: {e}. Se usan valores por defecto")

    ajustes, avisos = normalizar(datos)
    for aviso in avisos:
        print(f"[CONFIG] {aviso}")
    return ajustes


def guardar_ajustes(ajustes: Ajustes, ruta: Path | None = None) -> None:
    """Escribe los ajustes en disco de forma atómica.

    Se escribe a un temporal y se renombra: si el proceso muere a mitad, el
    `config.json` anterior sigue intacto en vez de quedar truncado.
    """
    ruta = ruta or RUTA_CONFIG
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(
        json.dumps(asdict(ajustes), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporal, ruta)


# ─── Instancia viva ────────────────────────────────────────────────────
#
# El panel y la CLI comparten este objeto. No es una constante de import: se
# construye la primera vez que alguien pregunta, para que `core/idiomas.py`
# pueda importar este módulo sin que se muerda la cola.

_ajustes: Ajustes | None = None


def ajustes() -> Ajustes:
    """Los ajustes activos. Se cargan la primera vez y luego se reutilizan."""
    global _ajustes
    if _ajustes is None:
        _ajustes = cargar_ajustes()
    return _ajustes


def fijar_ajustes(nuevos: Ajustes) -> None:
    """Cambia los ajustes en memoria (sin tocar disco).

    Lo usa el panel después de guardar, y los tests para partir de un estado
    conocido sin escribir archivos.
    """
    global _ajustes
    _ajustes = nuevos


def restablecer() -> Ajustes:
    """Vuelve a los valores de fábrica, en memoria y en disco."""
    nuevos = por_defecto()
    guardar_ajustes(nuevos)
    fijar_ajustes(nuevos)
    return nuevos


def con_cambios(**cambios: object) -> Ajustes:
    """Copia los ajustes activos con algunos campos cambiados y validados.

    Es el camino que usará el panel: nunca se muta el objeto en caliente, se
    construye uno nuevo y se aplica. Así un valor inválido no deja el estado a
    medio cambiar.
    """
    datos = asdict(ajustes())
    datos.update(cambios)
    nuevos, avisos = normalizar(datos)
    for aviso in avisos:
        print(f"[CONFIG] {aviso}")
    return nuevos
