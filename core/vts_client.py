import asyncio
import json
import os
import websockets

TOKEN_FILE = "vts_token.txt"

class VTSClient:
    def __init__(self):
        self.websocket = None
        self.connected = False
        self.uri = "ws://localhost:8001"

    async def connect_and_auth(self):
        """Conecta y autentica con VTube Studio, mantiene la conexión abierta."""
        try:
            self.websocket = await websockets.connect(self.uri)
            print(f"[VTS] Conectado a VTube Studio en {self.uri}")
            await self.authenticate()
            self.connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Error de conexion con VTube Studio: {e}")
            self.connected = False
            return False

    async def authenticate(self):
        """Gestiona el flujo de autenticación."""
        token = ""
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token = f.read().strip()

        if not token:
            print("[VTS] Solicitando token de autenticación...")
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
            await self.websocket.send(json.dumps(token_payload))
            response_raw = await self.websocket.recv()
            response = json.loads(response_raw)
            
            if "data" in response and "authenticationToken" in response["data"]:
                token = response["data"]["authenticationToken"]
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(token)
                print("[VTS] Por favor, acepta la solicitud en la ventana de VTube Studio!")
                await asyncio.sleep(2)
            else:
                print(f"[ERROR] [VTS Error al pedir token]: {response}")
                return

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

        print("[VTS] Autenticando sesion...")
        await self.websocket.send(json.dumps(auth_payload))
        auth_response_raw = await self.websocket.recv()
        auth_response = json.loads(auth_response_raw)

        if auth_response.get("data", {}).get("authenticated", False):
            print("[VTS] Autenticacion con VTube Studio exitosa!")
        else:
            print(f"[ERROR] [VTS Error de Autenticacion]: {auth_response}")

    async def send_parameter(self, parameter_name: str, value: float, weight: float = 1.0):
        """Envía un valor de parámetro a VTube Studio (ej. MouthOpen, EyeOpen, etc.)."""
        if not self.connected or not self.websocket:
            return
        
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"ParamInject_{parameter_name}",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "parameterName": parameter_name,
                "value": value,
                "weight": weight
            }
        }
        try:
            await self.websocket.send(json.dumps(payload))
        except Exception as e:
            print(f"[ERROR] [VTS Error enviando parámetro]: {e}")

    async def trigger_expression(self, expression_file: str):
        """Dispara una expresión/hotkey en VTube Studio."""
        if not self.connected or not self.websocket:
            return
            
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"Expression_{expression_file}",
            "messageType": "TriggerHotkeyRequest",
            "data": {
                "hotkeyID": expression_file
            }
        }
        try:
            await self.websocket.send(json.dumps(payload))
        except Exception as e:
            print(f"[ERROR] [VTS Error disparando expresión]: {e}")

    async def close(self):
        """Cierra la conexión."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False

# Instancia global para uso en main.py
vts_client = VTSClient()

async def conectar_y_autenticar():
    """Función de compatibilidad para main.py - conecta y autentica."""
    return await vts_client.connect_and_auth()