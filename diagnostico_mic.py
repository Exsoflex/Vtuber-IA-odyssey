"""
Diagnóstico del micrófono de Niu.

Separa dos capas que hasta ahora iban juntas:

    1. CAPTURA:  ¿el micrófono entrega voz con un espectro normal?
    2. STT:      ¿el motor de reconocimiento entiende ese audio?

Uso:
    .venv\\Scripts\\python.exe diagnostico_mic.py
    .venv\\Scripts\\python.exe diagnostico_mic.py "Realtek"

El segundo argumento (opcional) es un fragmento del nombre del dispositivo.
Sirve para comparar el DGM20 con el micrófono interno del portátil.

Qué mide:
    - RMS por tramos de 0.5 s mientras hablas,
    - reparto de energía por bandas (clave: cuánta energía hay en 300-1000 Hz,
      que es donde vive la inteligibilidad),
    - reconocimiento con Google STT y con Whisper local,
    - cuánto recorta el detector de voz real de Niu.

No forma parte del motor: es una herramienta de depuración.
"""

import os
import sys
import time

import numpy as np
import soundfile as sf

from core.audio_devices import buscar_dispositivo
from core.stt import SAMPLE_RATE, _remuestrear_int16, grabar_hasta_silencio, reconocer

DURACION = 6.0
NOMBRE_MIC = sys.argv[1] if len(sys.argv) > 1 else os.getenv("NIU_MIC", "DGM20 USB Microphone")
ARCHIVO = "diagnostico_mic.wav"


def rms(datos: np.ndarray) -> float:
    return float(np.sqrt(np.mean(datos.astype(np.float64) ** 2)))


def bandas(datos: np.ndarray, fs: int = SAMPLE_RATE) -> dict[str, float]:
    """
    Porcentaje de energía por banda, en un tramo con voz.

    Una voz normal tiene la mayor parte de su energía entre 300 y 3000 Hz.
    Si casi todo está por debajo de 300 Hz, hay rumble tapando la voz.
    """
    esp = np.abs(np.fft.rfft(datos.astype(np.float64) * np.hanning(len(datos)))) ** 2
    freqs = np.fft.rfftfreq(len(datos), 1 / fs)
    total = esp.sum() or 1.0
    return {
        f"{lo}-{hi} Hz": 100 * esp[(freqs >= lo) & (freqs < hi)].sum() / total
        for lo, hi in [(0, 100), (100, 300), (300, 1000), (1000, 3000), (3000, 8000)]
    }


def tramo_con_voz(datos: np.ndarray, fs: int) -> np.ndarray:
    """Devuelve el tercio más energético del audio (aproxima el tramo hablado)."""
    ventana = int(fs * 0.5)
    trozos = [(rms(datos[i:i + ventana]), i) for i in range(0, len(datos) - ventana, ventana)]
    if not trozos:
        return datos
    _, inicio = max(trozos)
    return datos[inicio:inicio + 3 * ventana]


def describir(nombre: str, pcm: bytes) -> None:
    datos = np.frombuffer(pcm, dtype=np.int16)
    print(
        f"  {nombre}: {len(datos) / SAMPLE_RATE:5.2f} s | RMS={rms(datos):8.1f} "
        f"| pico={int(np.max(np.abs(datos))) if len(datos) else 0:6d}"
    )


def grabar_ventana_fija(dispositivo: int, duracion: float) -> bytes:
    import sounddevice as sd

    fs = int(sd.query_devices(dispositivo)["default_samplerate"])
    canales = max(1, min(2, int(sd.query_devices(dispositivo)["max_input_channels"])))
    print(f"\n[CAPTURA] {duracion:.0f} s a {fs} Hz ({canales} canal/es, igual que Niu)")
    for segundos in range(3, 0, -1):
        print(f"  ... {segundos}")
        time.sleep(1)
    print("  ¡HABLA AHORA!")

    with sd.InputStream(
        device=dispositivo, samplerate=fs, channels=canales, dtype="int16",
        blocksize=int(fs * 0.1),
    ) as stream:
        bloques = [stream.read(int(fs * 0.1))[0].copy() for _ in range(int(duracion / 0.1))]

    # Pedir 1 canal a un dispositivo estéreo deforma el audio en WASAPI.
    # Se captura con los canales nativos y se elige el que tiene señal.
    datos = np.concatenate(bloques)
    if datos.ndim > 1:
        datos = datos[:, int(np.argmax(np.std(datos.astype(np.float64), axis=0)))]
    mono = datos.flatten()
    print("\n  Nivel por tramos de 0.5 s (RMS):")
    tramo = int(fs * 0.5)
    for i in range(0, len(mono), tramo):
        print(f"    t={i / fs:4.1f}s  rms={rms(mono[i:i + tramo]):8.1f}")

    print(f"  Pico global: {int(np.max(np.abs(mono)))} de 32767")
    return _remuestrear_int16(mono, fs, SAMPLE_RATE).tobytes()


def main() -> None:
    print("=" * 60)
    print(" DIAGNÓSTICO DE MICRÓFONO — NIU")
    print("=" * 60)

    dispositivo = buscar_dispositivo(NOMBRE_MIC, salida=False)
    if dispositivo is None:
        print(f"No encontré ningún dispositivo que contenga '{NOMBRE_MIC}'.")
        return

    input("\nPulsa ENTER y prepárate para decir una frase corta...")
    pcm = grabar_ventana_fija(dispositivo, DURACION)
    datos = np.frombuffer(pcm, dtype=np.int16)

    print("\n[1] Espectro del tramo con voz")
    reparto = bandas(tramo_con_voz(datos, SAMPLE_RATE))
    for banda, pct in reparto.items():
        print(f"    {banda:14s} {pct:5.1f}% {'#' * int(pct / 2)}")

    bajo = reparto["0-100 Hz"] + reparto["100-300 Hz"]
    habla = reparto["300-1000 Hz"] + reparto["1000-3000 Hz"]
    print(f"\n    Energía < 300 Hz: {bajo:5.1f}%   |   energía 300-3000 Hz: {habla:5.1f}%")
    if bajo > 60 or habla < 20:
        print("    ⚠️  MUCHO RUMBLE: la voz está enterrada en frecuencias graves.")
        print("       Revisa: perilla de ganancia del micrófono, distancia (15-20 cm),")
        print("       mejoras de audio de Windows y nivel de entrada.")
    else:
        print("    ✅ Reparto espectral normal para voz.")

    sf.write(ARCHIVO, datos, SAMPLE_RATE)
    print(f"\n[2] Guardado en '{ARCHIVO}' — escúchalo.")

    print("\n[3] Google STT")
    print(f"    -> {reconocer(pcm, 'es-MX')!r}")

    print("\n[4] Whisper local (si está instalado)")
    try:
        import asyncio

        from faster_whisper import WhisperModel

        audio = datos.astype(np.float32) / 32768
        audio = audio * (0.9 / (np.max(np.abs(audio)) or 1.0))
        modelo = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)
        inicio = time.perf_counter()
        segmentos, info = modelo.transcribe(
            audio, language="es", beam_size=5, vad_filter=False,
            condition_on_previous_text=False,
        )
        texto = " ".join(s.text.strip() for s in segmentos)
        print(f"    -> {texto!r} ({time.perf_counter() - inicio:.1f} s)")
    except ImportError:
        print("    (faster-whisper no instalado)")

    print("\n[5] Qué recorta el detector de voz de Niu")
    pcm_vad = grabar_hasta_silencio(dispositivo)
    if pcm_vad is None:
        print("    El detector NO detectó voz (umbral demasiado alto o micrófono mudo).")
    else:
        describir("capturado por el VAD", pcm_vad)
        print(f"    Google -> {reconocer(pcm_vad, 'es-MX')!r}")


if __name__ == "__main__":
    main()
