import os
import asyncio
import edge_tts
import winsound
from dotenv import load_dotenv

load_dotenv()

VOZ_NIU = "es-MX-DaliaNeural"
PITCH_ANIME = "+18Hz"
RATE_ANIME = "+10%"

async def sintetizar_y_reproducir_voz_async(texto: str, archivo_salida: str = "core/voz_temp.wav"):
    """
    Sintetiza la voz utilizando Edge-TTS guardando directamente en WAV.
    NO reproduce el audio (eso lo maneja main.py para lip-sync).
    """
    try:
        print("[TTS Edge]: Niu esta preparando su voz...")
        
        comunicador = edge_tts.Communicate(
            text=texto,
            voice=VOZ_NIU,
            pitch=PITCH_ANIME,
            rate=RATE_ANIME
        )
        
        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)
        await comunicador.save(archivo_salida)

        print("[TTS Edge]: Audio generado y guardado.")

    except Exception as e:
        print(f"[ERROR] [Error en Modulo TTS Edge]: {e}")
        if os.path.exists(archivo_salida):
            try:
                os.remove(archivo_salida)
            except:
                pass

def sintetizar_y_reproducir_voz(texto: str):
    """
    Función de compatibilidad sincrónica llamada desde main.py.
    Ejecuta el sintetizador asíncrono en un hilo independiente para evitar bloqueos del bucle.
    """
    import threading
    def run_in_thread():
        asyncio.run(sintetizar_y_reproducir_voz_async(texto))
    
    t = threading.Thread(target=run_in_thread)
    t.start()
    t.join()