"""
Motor principal de Niu Autonomous Engine.
Orquesta cerebro (LLM), voz (TTS) y VTube Studio.
Entrada continua por voz o teclado.
"""

import asyncio
import os
import sys
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from core.audio_devices import buscar_dispositivo
from core.brain import NiuBrain
from core.stt import (
    FRASES_SALIDA,
    SAMPLE_RATE,
    crear_proveedor_stt,
    grabar_hasta_silencio,
)
from core.lipsync import hablar_con_lipsync
from core.vts_client import vts_client

# ─── UTF-8 y salida sin buffering en consola Windows ───────────────────────
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Micrófono físico de Héctor. Importante: NO usar "Voicemeeter Out B1", porque
# ese bus lleva la voz de Niu y el audio del sistema (Niu se oiría a sí misma).
# Si prefieres pasar tu voz por Voicemeeter, enruta HARDWARE IN 1 a B2 y pon
# NIU_MIC="Voicemeeter Out B2" en el .env.
DISPOSITIVO_ENTRADA = os.getenv("NIU_MIC", "DGM20 USB Microphone")

# "" o "auto" = que el motor detecte el idioma (sirve para español e inglés).
IDIOMA_STT = os.getenv("NIU_STT_IDIOMA", "").strip().lower() or None


async def hablar_con_niu(texto_usuario: str, brain: NiuBrain):
    """Flujo completo: Cerebro -> texto -> TTS con lip sync -> audio."""
    respuesta_niu = await brain.procesar_mensaje("Rotceh", texto_usuario)
    print(f"\nNiu: {respuesta_niu}")

    archivo_audio = os.path.abspath("dia_por_dia/voz_temp.mp3")
    os.makedirs(os.path.dirname(archivo_audio), exist_ok=True)

    # Sintetiza, reproduce y mueve la boca. La boca la calcula Niu a partir de
    # su propio audio: no depende del micrófono de VTube Studio.
    exito_tts = await hablar_con_lipsync(respuesta_niu, archivo_audio)
    if not exito_tts:
        print("❌ [Error] No se pudo generar el audio de Niu")
        return

    respuesta_lower = respuesta_niu.lower()
    if any(p in respuesta_lower for p in ["feliz", "alegre", "contenta", ":)", ":-)"]):
        await vts_client.trigger_expression("MouthSmile")
    elif any(p in respuesta_lower for p in ["sorpresa", "sorprendida", "wow", "‼️"]):
        await vts_client.trigger_expression("MouthOpen")
    elif any(p in respuesta_lower for p in ["triste", "tristeza", "llorar", ":("]):
        await vts_client.trigger_expression("MouthFrown")
    elif any(p in respuesta_lower for p in ["enojada", "enojo", "enojado", ">:("]):
        await vts_client.trigger_expression("MouthAngry")


async def bucle_conversacion(brain: NiuBrain, dispositivo_mic: int | None, stt):
    """Bucle de conversación continua."""
    if dispositivo_mic is None:
        print("[AVISO] Sin micrófono. Usando teclado.")
    else:
        print(f"[MIC] Escuchando en {DISPOSITIVO_ENTRADA}. Di 'salir' para terminar.")

    while True:
        try:
            if dispositivo_mic is None:
                texto = await asyncio.to_thread(input, "Escribe tu mensaje: ")
            else:
                audio = await asyncio.to_thread(grabar_hasta_silencio, dispositivo_mic)
                if audio is None:
                    continue
                # grabar_hasta_silencio entrega bytes PCM 16-bit a 16 kHz;
                # el proveedor espera un array de numpy.
                muestras = np.frombuffer(audio, dtype=np.int16)
                inicio = time.perf_counter()
                texto = await stt.transcribir(muestras, SAMPLE_RATE, IDIOMA_STT)
                ms = (time.perf_counter() - inicio) * 1000
                if not texto:
                    print(f"[STT] No entendí ({ms:.0f} ms). Intenta otra vez.")
                    continue
                print(f"\n👤 Tú: {texto}   ({ms:.0f} ms)")
        except (EOFError, KeyboardInterrupt):
            print("\n[SISTEMA] Entrada finalizada. Saliendo...")
            break

        if not texto.strip():
            continue
        if texto.strip().lower() in FRASES_SALIDA:
            print("👋 ¡Hasta luego!")
            break

        await hablar_con_niu(texto, brain)


async def main():
    """Punto de entrada principal de Niu Autonomous Engine."""
    print("//////////////////////////////////////////////////////")
    print("[INFO] Iniciando Niu Autonomous Engine (Motor v2.5)")
    print("////////////////////////////////////////////////______\n")

    # 1. Cerebro: Ollama local por defecto
    brain = NiuBrain()

    # 2. Conectar VTube Studio (opcional)
    print("[VTS] Intentando conectar con VTube Studio...")
    try:
        await vts_client.connect_and_auth()
    except Exception as e:
        print(f"[WARN] [Aviso VTS]: No se pudo conectar ({e}). Continuando en modo solo consola.")

    # 3. Localizar el micrófono
    dispositivo_mic = buscar_dispositivo(DISPOSITIVO_ENTRADA, salida=False)
    if dispositivo_mic is None:
        print(f"[WARN] No encontré '{DISPOSITIVO_ENTRADA}'. Revisa Voicemeeter.")

    # 4. Motor de reconocimiento de voz (independiente del proveedor)
    stt = None
    if dispositivo_mic is not None:
        try:
            stt = crear_proveedor_stt()
        except Exception as e:
            print(f"[WARN] STT no disponible ({type(e).__name__}: {e}). Usando teclado.")
            dispositivo_mic = None

    if stt is not None and hasattr(stt, "preparar"):
        print("[STT] Cargando el modelo de voz (la primera vez tarda)...")
        await asyncio.to_thread(stt.preparar)

    print("\n🎙️ Niu está lista.\n")
    try:
        await bucle_conversacion(brain, dispositivo_mic, stt)
    finally:
        await vts_client.close()
        cerrar = getattr(brain.provider, "close", None)
        if cerrar:
            await cerrar()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Programa interrumpido. ¡Adiós!")
