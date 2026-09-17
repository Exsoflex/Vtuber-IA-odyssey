import asyncio
import websockets

async def conectar_vtube_studio():
    # Dirección IP local y puerto por defecto de VTube Studio API
    uri = "ws://localhost:8001"
    
    print(f"--- [SINTONIZANDO]: Intentando conectar con VTube Studio en {uri}... ---")
    
    try:
        # Abrimos el canal de comunicación persistente (WebSocket)
        async with websockets.connect(uri) as websocket:
            print("✨ ¡Conexión establecida con éxito con VTube Studio! ✨")
            print("Canal abierto y listo para enviar comandos de Niu.")
            
            # Mantenemos la conexión abierta unos segundos para probar
            await asyncio.sleep(2)
            
    except ConnectionRefusedError:
        print("❌ [ERROR]: No se pudo conectar. ¿Tienes abierto VTube Studio y el servidor WebSocket activado en el puerto 8001?")
    except Exception as e:
        print(f"❌ [ERROR INESPERADO]: {e}")

if __name__ == "__main__":
    # Arrancamos el motor asíncrono desde el script principal
    
    asyncio.run(conectar_vtube_studio())
