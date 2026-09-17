import asyncio
import json
import os
import websockets

TOKEN_FILE = "vts_token.txt"

async def autenticar_vts(websocket):
    """
    Gestiona el flujo correcto de autenticación con VTube Studio API:
    1. Si no hay token guardado, solicita un Token a VTS (AuthenticationTokenRequest) 
       lo que abrirá una ventana de confirmación en VTS.
    2. Usa el token para autenticar la sesión (AuthenticationRequest).
    """
    token = ""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token = f.read().strip()

    # Si no tenemos token, debemos pedir uno primero
    if not token:
        print("🔑 [VTS]: No hay token guardado. Solicitando token de autenticación...")
        token_payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "GetTokenReq_01",
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": "NiuAutonomousEngine",
                "pluginDeveloper": "Rotceh"
            }
        }
        await websocket.send(json.dumps(token_payload))
        response_raw = await websocket.recv()
        response = json.loads(response_raw)
        
        if "data" in response and "authenticationToken" in response["data"]:
            token = response["data"]["authenticationToken"]
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(token)
            print("⚠️ [VTS]: ¡Por favor, acepta la solicitud de conexión en la ventana de VTube Studio!")
        else:
            print(f"❌ [VTS Error al pedir token]: {response}")
            return

    # Ahora realizamos la autenticación oficial con el token
    auth_payload = {
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": "AuthReq_01",
        "messageType": "AuthenticationRequest",
        "data": {
            "pluginName": "NiuAutonomousEngine",
            "pluginDeveloper": "Rotceh",
            "authenticationToken": token
        }
    }

    print("🔌 [VTS]: Autenticando sesión con VTube Studio...")
    await websocket.send(json.dumps(auth_payload))
    
    auth_response_raw = await websocket.recv()
    auth_response = json.loads(auth_response_raw)

    if auth_response.get("data", {}).get("authenticated", False):
        print("✨ ¡Autenticación con VTube Studio 100% exitosa! Niu tiene control de su avatar.")
    else:
        print(f"❌ [VTS Error de Autenticación]: {auth_response}")

async def conectar_y_autenticar():
    uri = "ws://localhost:8001"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"🔗 Conectado a VTube Studio en {uri}")
            await autenticar_vts(websocket)
            await asyncio.sleep(1)
    except Exception as e:
        print(f"❌ Error de conexión con VTube Studio: {e}")

if __name__ == "__main__":
    asyncio.run(conectar_y_autenticar())
