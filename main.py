import sys
import io
import os
import asyncio
import wave
import struct
import winsound
import speech_recognition as sr
from core.brain import procesar_mensaje_niu
from core.tts import sintetizar_y_reproducir_voz_async
from core.vts_client import vts_client

# Forzar codificación UTF-8 en la consola de Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def escuchar_microfono():
    """Captura voz desde el micrófono local y la convierte a texto (STT es-MX)."""
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n--- [SISTEMA AUDITIVO]: Niu te esta escuchando... ---")
        r.adjust_for_ambient_noise(source, duration=1)
        audio = r.listen(source)
        try:
            texto = r.recognize_google(audio, language="es-MX")
            return texto
        except sr.UnknownValueError:
            return "ERROR_AUDIO_NO_COMPRENDIDO"
        except sr.RequestError:
            return "ERROR_SERVICIO_VOZ"

def analizar_amplitud_audio(ruta_wav: str, chunk_size: int = 1024):
    """
    Analiza un archivo WAV y genera una lista de valores de amplitud normalizada (0.0 - 1.0)
    para sincronización labial (lip-sync).
    """
    try:
        with wave.open(ruta_wav, 'rb') as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            sample_width = wav_file.getsampwidth()
            n_channels = wav_file.getnchannels()
            
            fmt = f"<{len(frames) // sample_width}h" if sample_width == 2 else f"<{len(frames)}b"
            samples = struct.unpack(fmt, frames)
            
            if n_channels == 2:
                samples = [(samples[i] + samples[i+1]) / 2 for i in range(0, len(samples), 2)]
            
            amplitudes = []
            for i in range(0, len(samples), chunk_size):
                chunk = samples[i:i+chunk_size]
                if chunk:
                    rms = (sum(x*x for x in chunk) / len(chunk)) ** 0.5
                    normalized = min(rms / 32767.0, 1.0)
                    amplitudes.append(normalized)
            
            return amplitudes
    except Exception as e:
        print(f"[WARN] [LipSync] Error analizando audio: {e}")
        return []

async def sincronizar_labios(ruta_wav: str):
    """
    Reproduce el audio y envía valores de amplitud a VTube Studio para MouthOpen en tiempo real.
    """
    if not vts_client.connected:
        return
        
    amplitudes = analizar_amplitud_audio(ruta_wav)
    if not amplitudes:
        return
    
    delay_per_chunk = 0.0426  # ~42ms
    
    print("[LipSync] Iniciando sincronizacion labial...")
    for amp in amplitudes:
        smoothed_amp = min(amp * 1.5, 1.0)
        await vts_client.send_parameter("MouthOpen", smoothed_amp)
        await asyncio.sleep(delay_per_chunk)
    
    await vts_client.send_parameter("MouthOpen", 0.0)
    print("[LipSync] Sincronizacion completada.")

async def hablar_con_niu(texto_usuario: str):
    """
    Flujo completo: Cerebro -> TTS -> LipSync + Audio -> Expresiones
    """
    respuesta_niu = procesar_mensaje_niu("Rotceh", texto_usuario)
    print(f"\nNiu: {respuesta_niu}")
    
    archivo_audio = "core/voz_temp.wav"
    os.makedirs("core", exist_ok=True)
    
    await sintetizar_y_reproducir_voz_async(respuesta_niu, archivo_audio)
    
    import threading
    audio_thread = threading.Thread(target=lambda: winsound.PlaySound(archivo_audio, winsound.SND_FILENAME))
    audio_thread.start()
    
    await sincronizar_labios(archivo_audio)
    
    audio_thread.join()
    
    if any(palabra in respuesta_niu.lower() for palabra in ["feliz", "alegre", "contenta", ":)", ":-)"]):
        await vts_client.trigger_expression("MyAnimation_Trigger_Happy")
    elif any(palabra in respuesta_niu.lower() for palabra in ["sorpresa", "sorprendida", "wow", "!!"]):
        await vts_client.trigger_expression("MyAnimation_Trigger_Surprised")
    elif any(palabra in respuesta_niu.lower() for palabra in ["triste", "tristeza", "llorar", ":("]):
        await vts_client.trigger_expression("MyAnimation_Trigger_Sad")
    elif any(palabra in respuesta_niu.lower() for palabra in ["enojada", "enojo", "enojado", ">:("]):
        await vts_client.trigger_expression("MyAnimation_Trigger_Angry")

async def main():
    print("//////////////////////////////////////////////////////")
    print("[INFO] Iniciando Niu Autonomous Engine (Motor v2.5)")
    print("////////////////////////////////////////////////______\n")

    print("[VTS] Intentando conectar con VTube Studio...")
    try:
        await vts_client.connect_and_auth()
    except Exception as e:
        print(f"[WARN] [Aviso VTS]: No se pudo conectar ({e}). Continuando en modo solo consola.")

    while True:
        print("\n---------------------------------------------------")
        opcion = input("Como deseas interactuar con Niu?\n 1 - Hablar por Voz (Microfono)\n 2 - Escribir por Texto\n 4 - Salir\nElige una opcion: ").strip()

        if opcion == "1":
            mi_voz = escuchar_microfono()
            if mi_voz.startswith("ERROR_"):
                print("Niu: Uy, no te entendi bien... ¿me lo repites?")
                continue
            
            print(f"Tu (Voz): {mi_voz}")
            await hablar_con_niu(mi_voz)

        elif opcion == "2":
            txt = input("Tu (Texto): ").strip()
            if not txt:
                continue
            await hablar_con_niu(txt)

        elif opcion == "4":
            print("\n[INFO] Cerrando motor de Niu. Hasta luego, Rotceh-kun!")
            await vts_client.close()
            break
        else:
            print("[ERROR] Opcion no valida. Selecciona 1, 2 o 4.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Programa interrumpido. Adios!")