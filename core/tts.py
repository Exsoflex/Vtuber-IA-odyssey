"""
Módulo de Síntesis Vocal (TTS) para Niu Autonomous Engine.
Utiliza Edge-TTS para voz natural y emotiva en español.
Filtra emojis para la síntesis vocal pero los conserva para subtítulos.
Reproduce el audio en el dispositivo virtual de Voicemeeter para que VTube
Studio lo capture vía Lip Sync.
"""

import asyncio
import io
import os
import re
import wave
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
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("[WARN] sounddevice o soundfile no instalado. Instala con: pip install sounddevice soundfile numpy")

# ─── Configuración de voz ──────────────────────────────────────────────
VOZ_NIU = "es-MX-DaliaNeural"  # Voz natural en español de Edge-TTS
VELOCIDAD = "+0%"               # Velocidad normal
TONO = "+0Hz"                   # Edge-TTS usa Hz para el tono, no porcentaje

TARGET_SAMPLE_RATE = 48000  # Hz, frecuencia del mezclador de Voicemeeter

# Salida de voz: por aquí escucha VTube Studio para el lip sync.
DISPOSITIVO_SALIDA = os.getenv("NIU_SALIDA", "Voicemeeter In 1")


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


async def sintetizar_y_reproducir_voz_async(
    texto: str,
    archivo_salida: str = "core/voz_temp.mp3",
    voz: str = VOZ_NIU,
) -> bool:
    """
    Sintetiza texto a audio usando Edge-TTS y lo reproduce en el dispositivo
    virtual de salida.

    Args:
        texto: Texto a sintetizar (puede contener emojis).
        archivo_salida: Ruta del archivo WAV temporal.
        voz: Nombre de la voz de Edge-TTS a utilizar.

    Returns:
        True si la síntesis y reproducción tuvo éxito.
    """
    try:
        print("🎙️ [TTS Edge]: Niu está preparando su voz...")

        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError("edge-tts no instalado. Instala con: pip install edge-tts")

        # 1. Limpiar emojis para la síntesis vocal (se conservan para subtítulos)
        texto_para_tts = _limpiar_texto_para_tts(texto)

        if not texto_para_tts.strip():
            print("[WARN] [TTS] Texto vacío después de filtrar emojis")
            return False

        # 2. Generar audio con Edge-TTS
        comunicador = edge_tts.Communicate(
            text=texto_para_tts,
            voice=voz,
            rate=VELOCIDAD,
            pitch=TONO,
        )

        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)
        await comunicador.save(archivo_salida)

        print(f"[TTS Edge]: Audio generado y guardado ({os.path.getsize(archivo_salida)} bytes)")

        # 3. Reproducir en el dispositivo virtual
        await _reproducir_en_dispositivo(archivo_salida)

        print("[TTS Edge]: Reproducción completada")
        return True

    except Exception as e:
        print(f"[WARN] [TTS Edge] Falló: {type(e).__name__}: {e}")
        return False


async def _reproducir_en_dispositivo(ruta_audio: str):
    """Reproduce el audio en el dispositivo virtual que usa VTube Studio."""
    if not SOUNDDEVICE_AVAILABLE:
        print("[WARN] sounddevice no disponible, no se puede reproducir audio")
        return

    try:
        # Buscar el dispositivo virtual de salida
        device_id = _buscar_dispositivo_salida()
        if device_id is None:
            print("[WARN] Dispositivo virtual no encontrado, reproduciendo por default")
            import winsound
            winsound.PlaySound(ruta_audio, winsound.SND_FILENAME)
            return

        # Leer archivo WAV
        import soundfile as sf
        data, fs = sf.read(ruta_audio)

        # Re-muestrear a 48000 Hz (requerido en el dispositivo virtual)
        if fs != TARGET_SAMPLE_RATE:
            print(f"[TTS] Re-muestreando de {fs} Hz a {TARGET_SAMPLE_RATE} Hz...")
            data = _remuestrear_audio(data, fs, TARGET_SAMPLE_RATE)
            fs = TARGET_SAMPLE_RATE

        # WASAPI exige que el número de canales coincida con el del dispositivo
        canales = sd.query_devices(device_id)["max_output_channels"]
        if data.ndim == 1 and canales >= 2:
            data = np.column_stack([data, data])

        def _play():
            sd.play(data, fs, device=device_id)
            sd.wait()

        print(f"[TTS] Reproduciendo en {DISPOSITIVO_SALIDA} (device_id={device_id}, sr={fs} Hz)...")
        await asyncio.to_thread(_play)
        print("[TTS] Reproducción completada")

    except Exception as e:
        print(f"[WARN] Error reproduciendo el audio: {e}")
        import winsound
        winsound.PlaySound(ruta_audio, winsound.SND_FILENAME)


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