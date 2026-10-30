"""
Módulo de Síntesis Vocal (TTS) para Niu Autonomous Engine.

Usa Edge-TTS para voz natural y emotiva en español. Filtra emojis para la
síntesis vocal pero los conserva para subtítulos.

Está dividido en tres pasos independientes:

    sintetizar_voz_async()  -> genera el archivo de audio
    preparar_audio()        -> lo carga, lo remuestrea y lo adapta al endpoint
    reproducir_audio()      -> lo manda al dispositivo (bloqueante)

Están separados porque el lip sync necesita el audio **antes** de que suene:
con `AudioPreparado.mono` se calcula la envolvente de la boca y después se
reproduce e inyecta a la vez. Si todo estuviera en una sola función no habría
forma de saber qué va a sonar hasta que ya ha sonado.
"""

import asyncio
import os
import re
from dataclasses import dataclass

import numpy as np
from dotenv import load_dotenv

from core.audio_devices import buscar_dispositivo

load_dotenv()

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    print("[WARN] edge-tts no instalado. Instala con: pip install edge-tts")

try:
    import sounddevice as sd
    import soundfile as sf

    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    sd = None
    sf = None
    SOUNDDEVICE_AVAILABLE = False
    print("[WARN] sounddevice o soundfile no instalado. "
          "Instala con: pip install sounddevice soundfile")

# ─── Configuración de voz ──────────────────────────────────────────────
VOZ_NIU = "es-MX-DaliaNeural"  # Voz natural en español de Edge-TTS
VELOCIDAD = "+0%"              # Velocidad normal
TONO = "+0Hz"                  # Edge-TTS usa Hz para el tono, no porcentaje

TARGET_SAMPLE_RATE = 48000  # Hz, frecuencia del mezclador de Voicemeeter

# Salida de voz: por aquí escucha VTube Studio para el lip sync.
#
# OJO con el nombre. En este driver (Voicemeeter "8 points") existen dos
# familias de endpoints que se parecen:
#   "Voicemeeter Input"                 -> Strip 3 (Virtual VAIO)  <-- el bueno
#   "Voicemeeter In 1" ... "In 5"       -> puntos de entrada hardware
#
# Comprobado midiendo el bus B1 mientras se reproducía un tono:
#   "Voicemeeter In 1" -> -240 dBFS (silencio digital, no llega a ningún lado)
#   "Voicemeeter Input" ->  -12 dBFS (llega a VAIO -> A1 + B1)
#
# Con "Voicemeeter In 1" Niu "reproducía" sin error y no sonaba nada.
DISPOSITIVO_SALIDA = os.getenv("NIU_SALIDA", "Voicemeeter Input")


@dataclass
class AudioPreparado:
    """Audio listo para sonar y para medir.

    Attributes:
        mono: señal a 48 kHz, un canal. Es la referencia para el lip sync.
        salida: la misma señal, ya con el número de canales del endpoint.
        fs: frecuencia de muestreo de ambas.
        device_id: índice del dispositivo de salida (None si no se encontró).
    """

    mono: np.ndarray
    salida: np.ndarray
    fs: int
    device_id: int | None

    @property
    def duracion(self) -> float:
        """Duración en segundos."""
        return len(self.mono) / self.fs


def _limpiar_texto_para_tts(texto: str) -> str:
    """
    Elimina emojis y caracteres especiales para la síntesis vocal.
    Los emojis se mantienen para subtítulos en pantalla.
    """
    # Rangos Unicode de emojis
    patron_emojis = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Emoticones
        "\U0001F300-\U0001F5FF"  # Símbolos y pictogramas
        "\U0001F680-\U0001F6FF"  # Transporte y símbolos
        "\U0001F1E0-\U0001F1FF"  # Banderas (países)
        "\U00002700-\U000027BF"  # Símbolos diversos
        "\U000024C2-\U0001F251"  # Caracteres encerrados
        "\U0001F900-\U0001F9FF"  # Símbolos suplementarios
        "\U0001FA70-\U0001FAFF"  # Símbolos y pictogramas extendidos
        "\U0001F000-\U0001F02F"  # Juegos de dados
        "]+",
        flags=re.UNICODE,
    )
    texto_limpio = patron_emojis.sub("", texto)
    # Limpiar espacios múltiples
    texto_limpio = re.sub(r"\s+", " ", texto_limpio).strip()
    return texto_limpio


# ─── Paso 1: generar ───────────────────────────────────────────────────


async def sintetizar_voz_async(
    texto: str,
    archivo_salida: str = "core/voz_temp.mp3",
    voz: str = VOZ_NIU,
) -> bool:
    """Sintetiza texto a audio con Edge-TTS y lo guarda en disco.

    Args:
        texto: Texto a sintetizar (puede contener emojis).
        archivo_salida: Ruta del archivo de audio temporal.
        voz: Nombre de la voz de Edge-TTS a utilizar.

    Returns:
        True si el archivo se generó y no está vacío.
    """
    try:
        print("🎙️ [TTS Edge]: Niu está preparando su voz...")

        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError("edge-tts no instalado. Instala con: pip install edge-tts")

        # Limpiar emojis para la síntesis vocal (se conservan para subtítulos)
        texto_para_tts = _limpiar_texto_para_tts(texto)
        if not texto_para_tts.strip():
            print("[WARN] [TTS] Texto vacío después de filtrar emojis")
            return False

        comunicador = edge_tts.Communicate(
            text=texto_para_tts,
            voice=voz,
            rate=VELOCIDAD,
            pitch=TONO,
        )

        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)
        await comunicador.save(archivo_salida)

        print(f"[TTS Edge]: Audio generado y guardado "
              f"({os.path.getsize(archivo_salida)} bytes)")
        return True

    except Exception as e:
        print(f"[WARN] [TTS Edge] Falló: {type(e).__name__}: {e}")
        return False


# ─── Paso 2: preparar ──────────────────────────────────────────────────


def preparar_audio(ruta_audio: str) -> AudioPreparado | None:
    """Carga el audio y lo deja en el formato que espera el endpoint.

    Hace tres cosas:

    1. Lee el archivo como float32 (rango -1.0 a 1.0, que es lo que usa
       sounddevice; los enteros de 16 bits no valen directamente).
    2. Remuestrea a 48 kHz, la frecuencia del mezclador de Voicemeeter.
    3. Rellena con silencio hasta el número de canales del endpoint. El
       endpoint de Voicemeeter expone 8 canales y hay que entregarle
       exactamente ese número; los sobrantes van en silencio y Voicemeeter usa
       los dos primeros.

    Returns:
        `AudioPreparado` o None si no se pudo leer.
    """
    if not SOUNDDEVICE_AVAILABLE:
        print("[WARN] sounddevice no disponible: no se puede preparar el audio")
        return None

    try:
        data, fs = sf.read(ruta_audio, dtype="float32")
    except Exception as e:
        print(f"[WARN] [TTS] No se pudo leer {ruta_audio}: {type(e).__name__}: {e}")
        return None

    if data.ndim > 1:
        mono = data.mean(axis=1)   # la boca se mide sobre la mezcla, no sobre un canal
    else:
        mono = data

    if fs != TARGET_SAMPLE_RATE:
        print(f"[TTS] Re-muestreando de {fs} Hz a {TARGET_SAMPLE_RATE} Hz...")
        mono = _remuestrear_audio(mono, fs, TARGET_SAMPLE_RATE)
        fs = TARGET_SAMPLE_RATE

    device_id = _buscar_dispositivo_salida()
    canales = 1
    if device_id is not None:
        canales = int(sd.query_devices(device_id)["max_output_channels"]) or 1

    salida = np.repeat(mono[:, None], canales, axis=1).astype(np.float32)

    return AudioPreparado(mono=mono.astype(np.float32), salida=salida,
                          fs=fs, device_id=device_id)


# ─── Paso 3: reproducir ────────────────────────────────────────────────


def reproducir_audio(audio: AudioPreparado) -> None:
    """Reproduce el audio por el dispositivo de salida. Bloqueante.

    Es bloqueante a propósito: quien la llama decide si la manda a un hilo
    (`asyncio.to_thread`) para poder hacer otra cosa mientras suena.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return

    if audio.device_id is None:
        print(f"[WARN] No encontré '{DISPOSITIVO_SALIDA}', usando el dispositivo "
              f"por defecto")
        sd.play(audio.salida[:, 0], audio.fs)
    else:
        print(f"[TTS] Reproduciendo en {DISPOSITIVO_SALIDA} "
              f"(device_id={audio.device_id}, sr={audio.fs} Hz)...")
        sd.play(audio.salida, audio.fs, device=audio.device_id)

    sd.wait()
    print("[TTS] Reproducción completada")


# ─── Atajo para pruebas de audio (sin avatar) ──────────────────────────


async def sintetizar_y_reproducir_voz_async(
    texto: str,
    archivo_salida: str = "core/voz_temp.mp3",
    voz: str = VOZ_NIU,
) -> bool:
    """Genera y reproduce una frase, sin lip sync.

    Sirve para aislar problemas: si con esto se oye y con `hablar_con_lipsync`
    no, el fallo está en el lip sync y no en el audio.
    """
    if not await sintetizar_voz_async(texto, archivo_salida, voz):
        return False

    if not SOUNDDEVICE_AVAILABLE:
        import winsound
        winsound.PlaySound(archivo_salida, winsound.SND_FILENAME)
        return True

    audio = preparar_audio(archivo_salida)
    if audio is None:
        return False

    await asyncio.to_thread(reproducir_audio, audio)
    return True


def _buscar_dispositivo_salida() -> int | None:
    """Busca el dispositivo virtual de salida de audio."""
    if not SOUNDDEVICE_AVAILABLE:
        return None
    return buscar_dispositivo(DISPOSITIVO_SALIDA, salida=True)


def _remuestrear_audio(data, fs_origen: int, fs_objetivo: int):
    """
    Re-muestrea audio usando interpolación lineal (sin scipy).
    """
    if fs_origen == fs_objetivo:
        return data

    duracion = len(data) / fs_origen
    nueva_longitud = int(duracion * fs_objetivo)

    indices_originales = np.arange(len(data))
    nuevos_indices = np.linspace(0, len(data) - 1, nueva_longitud)

    if data.ndim == 1:
        return np.interp(nuevos_indices, indices_originales, data)

    return np.column_stack([
        np.interp(nuevos_indices, indices_originales, data[:, canal])
        for canal in range(data.shape[1])
    ])
