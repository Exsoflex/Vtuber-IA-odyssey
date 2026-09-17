import asyncio
import edge_tts
import pygame
import os

# Voces recomendadas en español:
# 'es-MX-DaliaNeural' (Juvenil, expresiva)
# 'es-MX-CarlotaNeural' (Enérgica)

VOZ_SELECCIONADA = "es-MX-DaliaNeural"

async def sintetizar_y_hablar(texto):
    archivo_audio = "voz_niu.mp3"
    
    # 1. Generar audio con edge-tts
    comunicador = edge_tts.Communicate(texto, VOZ_SELECCIONADA)
    await comunicador.save(archivo_audio)
    
    # 2. Reproducir con pygame
    pygame.mixer.init()
    pygame.mixer.music.load(archivo_audio)
    pygame.mixer.music.play()
    
    # Esperar a que termine de hablar
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
        
    pygame.mixer.music.unload()
    pygame.mixer.quit()
    
    # 3. Limpieza opcional del archivo temporal
    if os.path.exists(archivo_audio):
        os.remove(archivo_audio)

# Prueba directa:
asyncio.run(sintetizar_y_hablar("¡Hola Rotceh! Por fin tengo una voz real para hablar contigo."))