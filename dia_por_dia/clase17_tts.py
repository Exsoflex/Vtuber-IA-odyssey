import asyncio
import edge_tts
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

VOZ_SELECCIONADA = "es-MX-DaliaNeural"

async def sintetizar_y_reproducir_voz_async(texto: str, archivo_salida: str = "dia_por_dia/voz_temp.wav") -> bool:
    """
    Sintetiza texto a audio usando Edge-TTS y lo reproduce por VB-CABLE.
    
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
        
        # 1. Limpiar emojis para la síntesis vocal (no los lee en voz alta)
        texto_para_tts = _limpiar_texto_para_tts(texto)
        
        if not texto_para_tts.strip():
            print("[WARN] [TTS] Texto vacío después de filtrar emojis")
            return False
        
        # 2. Generar audio con Edge-TTS
        comunicador = edge_tts.Communicate(
            text=texto_para_tts,
            voice=VOZ_NIU,
            rate=VELOCIDAD,
            pitch=TONO,
        )
        
        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)
        await comunicador.save(archivo_salida)
        
        print(f"[TTS Edge]: Audio generado y guardado ({os.path.getsize(archivo_salida)} bytes)")
        
        # 3. Reproducir por VB-CABLE
        await _reproducir_por_vb_cable(archivo_salida)
        
        print("[TTS Edge]: Reproducción completada")
        return True
        
    except Exception as e:
        print(f"[WARN] [TTS Edge] Falló: {type(e).__name__}: {e}")
        return False


async def _reproducir_por_vb_cable(ruta_wav: str):
    """Reproduce WAV por VB-CABLE usando sounddevice con device ID específico."""
    if not SOUNDDEVICE_AVAILABLE:
        print("[WARN] sounddevice no disponible, reproduciendo por defecto")
        import winsound
        winsound.PlaySound(ruta_wav, winsound.SND_FILENAME)
        return
    
    try:
        device_id = _buscar_dispositivo_vb_cable()
        if device_id is None:
            print("[WARN] VB-CABLE no encontrado, reproduciendo por dispositivo default")
            import winsound
            winsound.PlaySound(ruta_wav, winsound.SND_FILENAME)
            return
        
        # Leer archivo WAV
        import soundfile as sf
        data, fs = sf.read(ruta_wav)
        
        # Re-muestrear a 48000 Hz (requerido por VB-CABLE)
        if fs != TARGET_SAMPLE_RATE:
            print(f"[TTS] Re-muestreando de {fs} Hz a {TARGET_SAMPLE_RATE} Hz...")
            data = _remuestrear_audio(data, fs, TARGET_SAMPLE_RATE)
            fs = TARGET_SAMPLE_RATE
        
        def _play():
            sd.play(data, fs, device=device_id)
            sd.wait()
        
        print(f"[TTS] Reproduciendo por VB-CABLE (device_id={device_id}, sr={fs} Hz)...")
        await asyncio.to_thread(_play)
        print("[TTS] Reproducción completada")
        
    except Exception as e:
        print(f"[WARN] Error reproduciendo por VB-CABLE: {e}")
        import winsound
        winsound.PlaySound(ruta_wav, winsound.SND_FILENAME)


def _buscar_dispositivo_vb_cable() -> int | None:
    """Busca el dispositivo VB-CABLE Input (prefiere WASAPI/DirectSound sobre MME)."""
    if not SOUNDDEVICE_AVAILABLE:
        return None
    try:
        dispositivos = sd.query_devices()
        candidatos = []
        for i, dispositivo in enumerate(dispositivos):
            if "CABLE Input" in dispositivo['name'] and dispositivo['max_output_channels'] > 0:
                hostapi = sd.query_hostapis()[dispositivo['hostapi']]['name']
                prioridad = 0
                if 'WASAPI' in hostapi:
                    prioridad = 3
                elif 'DirectSound' in hostapi:
                    prioridad = 2
                elif 'MME' in hostapi:
                    prioridad = 1
                candidatos.append((prioridad, i, dispositivo['name'], hostapi))
        
        if candidatos:
            candidatos.sort(reverse=True)
            mejor = candidatos[0]
            print(f"[TTS] Dispositivo VB-CABLE: [{mejor[1]}] {mejor[2]} ({mejor[3]})")
            return mejor[1]
    except Exception as e:
        print(f"[WARN] Error buscando VB-CABLE: {e}")
    return None


def _remuestrear_audio(data, fs_origen: int, fs_objetivo: int):
    """Re-muestrea audio usando interpolación lineal (sin scipy)."""
    if fs_origen == TARGET_SAMPLE_RATE:
        return data
    
    duracion = len(data) / fs_origen
    nueva_longitud = int(duracion * TARGET_SAMPLE_RATE)
    
    if data.ndim == 1:
        indices_originales = np.arange(len(data))
        nuevos_indices = np.linspace(0, len(data) - 1, nueva_longitud)
        datos_resampleados = np.interp(nuevos_indices, indices_originales, data)
    else:
        indices_originales = np.arange(len(data))
        nuevos_indices = np.linspace(0, len(data) - 1, nueva_longitud)
        datos_resampleados = np.column_stack([
            np.interp(nuevos_indices, old_indices, data[:, ch])
            for ch in range(data.shape[1])
        ])
    
    return datos_resampleados


def sintetizar_y_reproducir_voz(texto: str):
    """
    Función de compatibilidad sincrónica.
    """
    def run_in_thread():
        asyncio.run(sintetizar_y_reproducir_voz_async(texto))
    
    t = threading.Thread(target=run_in_thread)
    t.start()
    t.join()