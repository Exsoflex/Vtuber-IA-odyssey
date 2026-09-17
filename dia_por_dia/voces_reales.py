import asyncio
import edge_tts
import pygame
import os

pygame.mixer.init()

async def obtener_voces_espanol():
    # Consulta en tiempo real el catálogo oficial de Microsoft
    todas_las_voces = await edge_tts.list_voices()
    # Filtramos solo las de habla hispana femeninas (ideales para Niu)
    voces_es = [
        v for v in todas_las_voces 
        if v["Locale"].startswith("es-") and v["Gender"] == "Female"
    ]
    return voces_es

async def reproducir(short_name, pitch="+15Hz", rate="+8%"):
    archivo = "temp_preview.mp3"
    frase = "¡Hola Rotceh! Soy Niu. ¿Cómo sientes esta entonación para mi canal?"
    
    comunicador = edge_tts.Communicate(
        frase, 
        voice=short_name, 
        pitch=pitch, 
        rate=rate
    )
    await comunicador.save(archivo)
    
    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.music.unload()
    
    if os.path.exists(archivo):
        try:
            os.remove(archivo)
        except:
            pass

async def main():
    print("Consultando catálogo en vivo de Microsoft...")
    voces = await obtener_voces_espanol()
    
    print("\n" + "=" * 60)
    print("      🎙️ CATÁLOGO OFICIAL DE VOCES FEMENINAS (ESPAÑOL) 🎙️")
    print("=" * 60)
    
    for i, v in enumerate(voces, start=1):
        # Muestra el número, el identificador y el país
        print(f" {i:2d}. [{v['Locale']}] {v['ShortName']}")
        
    print(f" {len(voces)+1:2d}. Salir")
    print("=" * 60)
    
    while True:
        opcion = input(f"\nElige una voz para escuchar (1-{len(voces)+1}): ").strip()
        
        if not opcion.isdigit():
            print("Por favor, ingresa un número válido.")
            continue
            
        num = int(opcion)
        if 1 <= num <= len(voces):
            voz_elegida = voces[num - 1]
            print(f"\n[Reproduciendo]: {voz_elegida['ShortName']} (con Pitch Anime +15Hz)...")
            try:
                await reproducir(voz_elegida["ShortName"])
            except Exception as e:
                print(f"Error al reproducir: {e}")
        elif num == len(voces) + 1:
            print("\n¡Catálogo cerrado!")
            break
        else:
            print("Número fuera de rango.")

    pygame.mixer.quit()

if __name__ == "__main__":
    asyncio.run(main())