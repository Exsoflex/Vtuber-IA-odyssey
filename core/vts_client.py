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
        # Usar parámetro de tracking, NO parámetro Live2D
        # MouthOpen es parámetro Live2D (no inyectable)
        # VoiceVolumePlusMouthOpen es parámetro de tracking (inyectable)
        self._mouth_param_name = "VoiceVolumePlusMouthOpen"

    async def connect_and_auth(self):
        """Conecta y autentica con VTube Studio, mantiene la conexión abierta."""
        try:
            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=10_000_000,
            )
            print(f"[VTS] Conectado a VTube Studio en {self.uri}")
            await self.authenticate()
            self.connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Error de conexion con VTube Studio: {e}")
            self.connected = False
            return False

    async def authenticate(self):
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
                await asyncio.sleep(3)
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

    async def _ensure_connected(self):
        if not self.connected or not self.websocket:
            print("[VTS] Conexión perdida, reconectando...")
            return await self.connect_and_auth()
        return True

    async def connect_and_auth(self):
        try:
            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=10_000_000,
            )
            print(f"[VTS] Conectado a VTube Studio en {self.uri}")
            await self.authenticate()
            self.connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Error de conexion con VTube Studio: {e}")
            self.connected = False
            return False

    async def authenticate(self):
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
                await asyncio.sleep(3)
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

    async def _ensure_connected(self):
        if not self.connected or not self.websocket:
            print("[VTS] Conexión perdida, reconectando...")
            return await self.connect_and_auth()
        return True

    async def send_parameter(self, parameter_name: str, value: float, weight: float = 1.0):
        """Envía un valor de parámetro a VTube Studio."""
        if not await self._ensure_connected():
            return
        
        value = max(0.0, min(1.0, value))
        
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"ParamInject_{parameter_name}",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "parameterValues": [
                    {
                        "name": parameter_name,
                        "value": value,
                        "weight": weight
                    }
                ]
            }
        }
        try:
            await self.websocket.send(json.dumps(payload))
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=2)
            response = json.loads(response_raw)
            print(f"[VTS] Param response: {json.dumps(response)}")
        except asyncio.TimeoutError:
            print(f"[WARN] [VTS] Timeout esperando respuesta para {parameter_name}")
        except Exception as e:
            print(f"[ERROR] [VTS Error enviando parámetro]: {e}")
            self.connected = False

    async def send_mouth_open(self, value: float, weight: float = 1.0):
        """Envía valor de apertura de boca usando parámetro de tracking (VoiceVolumePlusMouthOpen)."""
        await self.send_parameter("VoiceVolumePlusMouthOpen", value, weight)

    async def trigger_expression(self, expression_file: str):
        if not await self._ensure_connected():
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
            self.connected = False

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def connect_and_auth(self):
        try:
            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=10_000_000,
            )
            print(f"[VTS] Conectado a VTube Studio en {self.uri}")
            await self.authenticate()
            self.connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Error de conexion con VTube Studio: {e}")
            self.connected = False
            return False

    async def authenticate(self):
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
                await asyncio.sleep(3)
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

    async def _ensure_connected(self):
        if not self.connected or not self.websocket:
            print("[VTS] Conexión perdida, reconectando...")
            return await self.connect_and_auth()
        return True

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def send_parameter(self, parameter_name: str, value: float, weight: float = 1.0):
        """Envía un valor de parámetro a VTube Studio (formato CORRECTO)."""
        if not await self._ensure_connected():
            return
        
        value = max(0.0, min(1.0, value))
        
        # Formato CORRECTO: parameterValues array
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"ParamInject_{parameter_name}",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "parameterValues": [
                    {
                        "name": parameter_name,
                        "value": value,
                        "weight": weight
                    }
                ]
            }
        }
        try:
            await self.websocket.send(json.dumps(payload))
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=2)
            response = json.loads(response_raw)
            print(f"[VTS] Param response: {json.dumps(response)}")
        except asyncio.TimeoutError:
            print(f"[WARN] [VTS] Timeout esperando respuesta para {parameter_name}")
        except Exception as e:
            print(f"[ERROR] [VTS Error enviando parámetro]: {e}")
            self.connected = False

    async def send_mouth_open(self, value: float, weight: float = 1.0):
        """Envía valor de apertura de boca usando VoiceVolume (parámetro de tracking más básico)."""
        await self.send_parameter("VoiceVolume", value, weight)

    async def trigger_expression(self, expression_file: str):
        if not await self._ensure_connected():
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
            self.connected = False

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def connect_and_auth(self):
        try:
            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=10_000_000,
            )
            print(f"[VTS] Conectado a VTube Studio en {self.uri}")
            await self.authenticate()
            self.connected = True
            return True
        except Exception as e:
            print(f"[ERROR] Error de conexion con VTube Studio: {e}")
            self.connected = False
            return False

    async def authenticate(self):
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
                await asyncio.sleep(3)
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

    async def _ensure_connected(self):
        if not self.connected or not self.websocket:
            print("[VTS] Conexión perdida, reconectando...")
            return await self.connect_and_auth()
        return True

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False

vts_client = VTSClient()

async def conectar_y_autenticar():
    return await vts_client.connect_and_auth()