import asyncio
import edge_tts
import pygame
import os

# Inicializamos el motor de audio UNA SOLA VEZ
pygame.mixer.init()

VOCES_CANDIDATAS = [
    {
        "id_num": "1",
        "nombre": "Dalia con Pitch Anime (Aguda y enérgica)",
        "voice": "es-MX-DaliaNeural",
        "pitch": "+20Hz",
        "rate": "+10%",
    },
    {
        "id_num": "2",
        "nombre": "Larissa Juvenil (Suave y dulce)",
        "voice": "es-MX-LarissaNeural",
        "pitch": "+12Hz",
        "rate": "+5%",
    },
    {
        "id_num": "3",
        "nombre": "Beatriz Cálida (Expresiva y natural)",
        "voice": "es-MX-BeatrizNeural",
        "pitch": "+8Hz",
        "rate": "+2%",
    },
    {
        "id_num": "4",
        "nombre": "Paloma Neutra (Estilo streamer casual)",
        "voice": "es-US-PalomaNeural",
        "pitch": "+15Hz",
        "rate": "+8%",
    },
]

async def reproducir_voz(config_voz, texto):
    # Nombre único por opción para evitar bloqueos de archivo
    archivo = f"temp_voz_{config_voz['id_num']}.mp3"
    
    print(f"\n[Sintetizando...] {config_voz['nombre']}")
    
    comunicador = edge_tts.Communicate(
        texto,
        voice=config_voz["voice"],
        pitch=config_voz["pitch"],
        rate=config_voz["rate"]
    )
    await comunicador.save(archivo)
    
    # Reproducir
    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()
    
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
        
    pygame.mixer.music.unload()

async def main():
    frase_defecto = "¡Hola Rotceh! Oye, deja de mirar el código un segundo y dime... ¿esta voz te gusta para mí o suena muy rara?"
    
    print("=" * 55)
    print("       🎙️ AUDICIÓN DE VOCES PARA NIU 🎙️")
    print("=" * 55)
    
    while True:
        print("\nElige una voz para escuchar:")
        for v in VOCES_CANDIDATAS:
            print(f" {v['id_num']}. {v['nombre']}")
        print(" 5. Probar una frase personalizada")
        print(" 6. Salir")
        
        opcion = input("\nSelecciona una opción (1-6): ").strip()
        
        if opcion in ["1", "2", "3", "4"]:
            seleccion = next(v for v in VOCES_CANDIDATAS if v["id_num"] == opcion)
            await reproducir_voz(seleccion, frase_defecto)
            
        elif opcion == "5":
            frase_personalizada = input("\nEscribe lo que quieres que diga Niu: ")
            print("¿Con qué voz?")
            for v in VOCES_CANDIDATAS:
                print(f" {v['id_num']}. {v['nombre']}")
            sub_opcion = input("Elige (1-4): ").strip()
            
            if sub_opcion in ["1", "2", "3", "4"]:
                seleccion = next(v for v in VOCES_CANDIDATAS if v["id_num"] == sub_opcion)
                await reproducir_voz(seleccion, frase_personalizada)
            else:
                print("Opción inválida.")
                
        elif opcion == "6":
            print("\n¡Cerrando cabina de audio!")
            break
        else:
            print("Opción no válida, intenta de nuevo.")

    # Limpieza final
    pygame.mixer.quit()
    for v in VOCES_CANDIDATAS:
        archivo = f"temp_voz_{v['id_num']}.mp3"
        if os.path.exists(archivo):
            try:
                os.remove(archivo)
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())