"""
Cliente de VTube Studio: conexión WebSocket, autenticación y envío de datos.

Qué hace y qué NO hace:

- Conecta con la API pública de VTS (`ws://localhost:8001`) y se autentica con
  un token persistente en `vts_token.txt` (el usuario solo autoriza una vez).
- Dispara hotkeys (expresiones, animaciones) con `trigger_expression`.

- NO empuja la boca del avatar. El lip sync lo hace VTube Studio por su cuenta:
  escucha un dispositivo de audio (aquí `Voicemeeter Out B1`) y mueve los
  parámetros de boca según el volumen. La API no permite escribir parámetros
  Live2D como `ParamMouthOpenY`; solo parámetros de tracking propios.
"""

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

    # ─── Conexión ──────────────────────────────────────────────────────────

    async def connect_and_auth(self, intentos: int = 5, espera: float = 2.0):
        """Conecta y autentica con VTube Studio, reintentando si hace falta.

        VTube Studio tarda unos segundos en levantar su API al arrancar. Si Niu
        se lanza a la vez que VTS, la primera conexión falla con
        `[WinError 1225] The remote computer refused the network connection`,
        que aquí no significa "VTS está cerrado" sino "todavía no hay nadie
        escuchando en el puerto 8001". Reintentar lo resuelve.

        Args:
            intentos: número total de intentos antes de rendirse.
            espera: segundos entre intentos.

        Returns:
            True si quedó conectado y autenticado.
        """
        ultimo_error: Exception | str | None = None

        for intento in range(1, intentos + 1):
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
                ultimo_error = e
                self.connected = False
                # Si el socket se abrió pero la autenticación falló, cerrarlo
                # antes del siguiente intento para no dejarlo colgando.
                if self.websocket is not None:
                    try:
                        await self.websocket.close()
                    except Exception:
                        pass
                    self.websocket = None
                if intento < intentos:
                    print(f"[VTS] Intento {intento}/{intentos} falló ({e}). "
                          f"Reintentando en {espera:.0f} s...")
                    await asyncio.sleep(espera)

        print(f"[ERROR] No se pudo conectar con VTube Studio tras {intentos} "
              f"intentos: {ultimo_error}")
        print("[VTS] Comprueba que VTube Studio está abierto y que en")
        print("      Configuración > API > 'Start API' está activo (puerto 8001).")
        return False

    async def authenticate(self):
        """Pide el token la primera vez y autentica la sesión actual."""
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
        """Reconecta si el socket se cayó. Devuelve False si no lo consigue."""
        if not self.connected or not self.websocket:
            print("[VTS] Conexión perdida, reconectando...")
            # En caliente (a mitad de conversación) no conviene esperar 10 s:
            # dos intentos rápidos y, si falla, se sigue sin VTS.
            return await self.connect_and_auth(intentos=2, espera=1.0)
        return True

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            self.websocket = None

    # ─── Datos hacia el modelo ─────────────────────────────────────────────

    async def send_parameter(self, parameter_name: str, value: float,
                             weight: float = 1.0):
        """Inyecta un valor en un parámetro de tracking.

        Ojo: solo funciona con parámetros de tracking (los que crea un plugin
        con `ParameterCreationRequest`). Los parámetros Live2D del modelo, como
        `ParamMouthOpenY`, NO se pueden escribir por la API: VTS responde con
        el error 453. La boca se mueve con el lip sync propio de VTS.
        """
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
            if response.get("messageType") == "APIError":
                print(f"[WARN] [VTS] {parameter_name}: "
                      f"{response.get('data', {}).get('message')}")
        except asyncio.TimeoutError:
            print(f"[WARN] [VTS] Timeout esperando respuesta para {parameter_name}")
        except Exception as e:
            print(f"[ERROR] [VTS Error enviando parámetro]: {e}")
            self.connected = False

    async def trigger_expression(self, expression_file: str):
        """Dispara un hotkey del modelo por su nombre o por su ID.

        `expression_file` es un nombre de hotkey de VTS, no un archivo: los
        nombres válidos son los que aparecen en la lista de hotkeys del modelo.
        """
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
            # Hay que leer la respuesta SIEMPRE. Si no se lee, queda en el
            # buffer y la siguiente petición recibe la respuesta anterior.
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=2)
            response = json.loads(response_raw)
            if response.get("messageType") == "APIError":
                print(f"[WARN] [VTS] Hotkey {expression_file!r}: "
                      f"{response.get('data', {}).get('message')}")
        except asyncio.TimeoutError:
            print(f"[WARN] [VTS] Timeout esperando respuesta del hotkey "
                  f"{expression_file!r}")
        except Exception as e:
            print(f"[ERROR] [VTS Error disparando expresión]: {e}")
            self.connected = False


vts_client = VTSClient()
