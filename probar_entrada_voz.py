"""
Prueba de extremo a extremo del oído de Niu.

Usa EXACTAMENTE el mismo camino que main.py:

    1. buscar_dispositivo()   -> encuentra el micrófono configurado
    2. grabar_hasta_silencio() -> captura y corta cuando te callas
    3. STTProvider.transcribir() -> el motor configurado (whisper o gemini)

Si esto entiende lo que dices, Niu también. Sirve para comprobar el oído sin
arrancar el cerebro, el TTS y VTube Studio.

Uso:
    .venv\\Scripts\\python.exe probar_entrada_voz.py

Di tres frases cortas. Se corta solo al detectar un segundo de silencio, así
que no hay que pulsar nada.
"""

import asyncio
import os
import sys
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from core.audio_devices import buscar_dispositivo
from core.stt import SAMPLE_RATE, crear_proveedor_stt, grabar_hasta_silencio

DISPOSITIVO_ENTRADA = os.getenv("NIU_MIC", "DGM20 USB Microphone")
IDIOMA = os.getenv("NIU_STT_IDIOMA", "").strip().lower() or None
TOMAS = 3


async def main() -> None:
    print("=" * 70)
    print(" OÍDO DE NIU — PRUEBA DE EXTREMO A EXTREMO")
    print("=" * 70)

    dispositivo = buscar_dispositivo(DISPOSITIVO_ENTRADA, salida=False)
    if dispositivo is None:
        print(f"No encontré '{DISPOSITIVO_ENTRADA}'. Revisa NIU_MIC en el .env.")
        return

    import sounddevice as sd

    info = sd.query_devices(dispositivo)
    print(f"Micrófono : [{dispositivo}] {info['name']}")
    print(f"Formato   : {info['max_input_channels']} canal/es "
          f"a {info['default_samplerate']:.0f} Hz")
    print(f"Idioma    : {IDIOMA or 'detección automática'}")

    stt = crear_proveedor_stt()
    print("\nCargando el modelo de voz...")
    await asyncio.to_thread(stt.preparar)
    print("Listo.\n")

    for toma in range(1, TOMAS + 1):
        print(f"--- Toma {toma}/{TOMAS}: habla ahora (corto al callarte) ---")
        inicio = time.perf_counter()
        audio = await asyncio.to_thread(grabar_hasta_silencio, dispositivo)
        captura_s = time.perf_counter() - inicio

        if audio is None:
            print("    No se detectó voz (8 s de espera). ¿Está el micro silenciado?")
            continue

        muestras = np.frombuffer(audio, dtype=np.int16)
        duracion = len(muestras) / SAMPLE_RATE
        if duracion < 0.3:
            print(f"    Captura demasiado corta ({duracion:.2f} s). Ignorada.")
            continue

        t0 = time.perf_counter()
        texto = await stt.transcribir(muestras, SAMPLE_RATE, IDIOMA)
        ms = (time.perf_counter() - t0) * 1000

        print(f"    capturado {duracion:.2f} s en {captura_s:.1f} s reales "
              f"| transcrito en {ms:.0f} ms")
        if texto:
            print(f"    ✅ {texto!r}")
        else:
            print("    ❌ no se entendió nada")

    print("\nFin. Si las tres tomas se transcribieron, el oído funciona.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrumpido.")
