"""
Interfaz común de los motores de reconocimiento de voz (STT).

Es el mismo patrón que ya usamos con LLMProvider:

    core/stt.py            -> captura micrófono y detecta silencio (VAD)
    core/stt_provider.py   -> el contrato que cumple cualquier motor
    core/stt_whisper.py    -> adaptador local (faster-whisper)
    core/stt_gemini.py     -> adaptador en la nube (Gemini)

`core/stt.py` no sabe quién transcribe; solo entrega audio. Así se puede
cambiar de motor sin tocar la captura ni main.py.

Aquí también viven dos utilidades de audio que comparten los adaptadores,
para no duplicarlas: convertir PCM a float y remuestrear con antialiasing.
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class STTProvider(Protocol):
    """Contrato de un motor de reconocimiento de voz."""

    nombre: str

    async def transcribir(
        self,
        audio: np.ndarray,
        fs: int,
        idioma: str | None = None,
    ) -> str | None:
        """
        Transcribe un bloque de audio.

        Args:
            audio: PCM mono int16, forma (n,).
            fs: frecuencia de muestreo de `audio` (Hz).
            idioma: "es", "en", o None para detectar el idioma automáticamente.

        Returns:
            El texto reconocido, o None si no se entendió nada.
        """
        ...


def pcm_a_float(audio: np.ndarray) -> np.ndarray:
    """PCM int16 -> float32 en [-1, 1], que es lo que esperan los modelos."""
    if audio.dtype == np.float32:
        return audio
    if audio.dtype == np.int16:
        return audio.astype(np.float32) / 32768.0
    return audio.astype(np.float32)


def remuestrear(audio: np.ndarray, fs_origen: int, fs_destino: int) -> np.ndarray:
    """
    Cambia la frecuencia de muestreo sin aliasing, usando la FFT.

    Interpolar linealmente (lo que hacía antes el proyecto) no filtra las
    frecuencias que no caben en la nueva tasa: todo lo que hay por encima de
    fs_destino/2 se pliega dentro de la banda audible y añade ruido.

    Aquí nos quedamos solo con las frecuencias que caben: eso ES el filtro
    antialiasing, y es lo que hace un conversor de calidad.
    """
    if fs_origen == fs_destino:
        return audio
    x = audio.astype(np.float64)
    n_salida = int(round(len(x) * fs_destino / fs_origen))
    if n_salida < 1:
        return np.zeros(0, dtype=audio.dtype)

    espectro = np.fft.rfft(x)
    nuevo = np.zeros(n_salida // 2 + 1, dtype=complex)
    copiar = min(len(espectro), len(nuevo))
    nuevo[:copiar] = espectro[:copiar]
    y = np.fft.irfft(nuevo * (n_salida / len(x)), n=n_salida)

    if np.issubdtype(audio.dtype, np.integer):
        return np.clip(y, -32768, 32767).astype(audio.dtype)
    return y.astype(audio.dtype, copy=False)


def normalizar_pico(audio: np.ndarray, objetivo: float = 0.95) -> np.ndarray:
    """Escala el audio para que su pico quede en `objetivo` (evita silencios)."""
    pico = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if pico < 1e-6:
        return audio
    return audio * (objetivo / pico)
