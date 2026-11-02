"""
Cliente de VTube Studio: conexión WebSocket, autenticación y envío de datos.

Qué hace:

- Conecta con la API pública de VTS (`ws://localhost:8001`) y se autentica con
  un token persistente en `vts_token.txt` (el usuario solo autoriza una vez).
- Crea parámetros de tracking propios ("custom parameters") con
  `ParameterCreationRequest`.
- Inyecta valores en esos parámetros con `InjectParameterDataRequest`.
- Dispara hotkeys (expresiones, animaciones) con `trigger_expression`.

Qué NO hace:

- NO puede escribir parámetros Live2D como `ParamMouthOpenY`: VTS responde con
  el error 453. Solo acepta parámetros de tracking (los que crea un plugin).

Sobre la concurrencia:

    Un WebSocket no etiqueta las respuestas. Si dos corrutinas mandan una
    petición cada una, la primera puede recibir la respuesta de la segunda.
    Por eso TODAS las peticiones pasan por `peticion()`, que las serializa con
    un `asyncio.Lock`.
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
        self._lock = asyncio.Lock()
        self._id = 0

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
                    "pluginDeveloper": "Rotceh",
                },
            }
            await self.websocket.send(json.dumps(token_payload))
            response = json.loads(await self.websocket.recv())

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
                "authenticationToken": token,
            },
        }

        print("[VTS] Autenticando sesion...")
        await self.websocket.send(json.dumps(auth_payload))
        auth_response = json.loads(await self.websocket.recv())

        if auth_response.get("data", {}).get("authenticated", False):
            print("[VTS] Autenticacion con VTube Studio exitosa!")
        else:
            print(f"[ERROR] [VTS Error de Autenticacion]: {auth_response}")

    async def _ensure_connected(self) -> bool:
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

    # ─── Transporte ────────────────────────────────────────────────────────

    async def peticion(self, message_type: str, data: dict | None = None,
                       timeout: float = 2.0) -> dict | None:
        """Envía una petición y devuelve la respuesta decodificada.

        Es el único punto por el que salen mensajes, y está serializado con un
        lock: mientras una corrutina espera su respuesta, ninguna otra puede
        adelantarse y quedarse con ella.

        Returns:
            El dict de respuesta, o None si no hay conexión o hubo un error de
            red. Los `APIError` (petición mal formada, parámetro inexistente...)
            sí se devuelven: son respuestas válidas de VTS.
        """
        async with self._lock:
            if not await self._ensure_connected():
                return None

            self._id += 1
            payload = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": f"Niu_{self._id}",
                "messageType": message_type,
            }
            if data is not None:
                payload["data"] = data

            try:
                await self.websocket.send(json.dumps(payload))
                respuesta = json.loads(
                    await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                )
            except asyncio.TimeoutError:
                print(f"[WARN] [VTS] Timeout en {message_type}")
                return None
            except Exception as e:
                print(f"[ERROR] [VTS] {message_type}: {type(e).__name__}: {e}")
                self.connected = False
                return None

        if respuesta.get("messageType") == "APIError":
            print(f"[WARN] [VTS] {message_type}: "
                  f"{respuesta.get('data', {}).get('message')}")
        return respuesta

    # ─── Parámetros de tracking ────────────────────────────────────────────

    async def crear_parametro_tracking(self, nombre: str,
                                       explicacion: str = "",
                                       minimo: float = 0.0,
                                       maximo: float = 1.0,
                                       defecto: float = 0.0) -> bool:
        """Crea un parámetro de tracking propio (idempotente).

        VTS exige que el nombre sea alfanumérico (sin espacios) y de 4 a 32
        caracteres. Si el parámetro ya existe y lo creó este mismo plugin, la
        petición vuelve a tener éxito y solo actualiza min/max/defecto: se puede
        llamar en cada arranque sin miedo.

        Después de crearlo, el usuario tiene que asignarlo a un parámetro Live2D
        en VTS (Configuración del modelo). Eso se hace una vez y queda guardado
        en el modelo.
        """
        if not nombre.isalnum() or not 4 <= len(nombre) <= 32:
            print(f"[ERROR] [VTS] Nombre de parámetro inválido: {nombre!r} "
                  f"(alfanumérico, 4-32 caracteres)")
            return False

        respuesta = await self.peticion("ParameterCreationRequest", {
            "parameterName": nombre,
            "explanation": explicacion,
            "min": minimo,
            "max": maximo,
            "defaultValue": defecto,
        })
        return bool(respuesta
                    and respuesta.get("messageType") == "ParameterCreationResponse")

    async def inyectar_parametro(self, nombre: str, valor: float,
                                 peso: float | None = None) -> bool:
        """Envía un valor a un parámetro de tracking.

        VTS considera el parámetro "perdido" si no recibe un valor al menos una
        vez por segundo; al perderse vuelve a su valor por defecto.

        Args:
            nombre: parámetro de tracking (por ejemplo `NiuMouthOpen`).
            valor: valor a enviar (entre -1e6 y 1e6).
            peso: 0-1 para mezclar con el tracking de la cara. None = control
                total (peso 1).
        """
        datos: dict = {
            "faceFound": True,
            "mode": "set",
            "parameterValues": [{"id": nombre, "value": float(valor)}],
        }
        if peso is not None:
            datos["parameterValues"][0]["weight"] = float(peso)

        respuesta = await self.peticion("InjectParameterDataRequest", datos)
        return bool(respuesta
                    and respuesta.get("messageType") == "InjectParameterDataResponse")

    async def leer_parametro(self, nombre: str) -> float | None:
        """Lee el valor actual de un parámetro de tracking.

        No sirve para parámetros Live2D (`ParamMouthOpenY`): para esos hay que
        usar `Live2DParameterListRequest`.
        """
        respuesta = await self.peticion("ParameterValueRequest", {"name": nombre})
        if not respuesta or respuesta.get("messageType") != "ParameterValueResponse":
            return None
        return float(respuesta["data"].get("value", 0.0))

    # ─── Compatibilidad ────────────────────────────────────────────────────

    async def send_parameter(self, parameter_name: str, value: float,
                             weight: float = 1.0) -> bool:
        """Alias de `inyectar_parametro` con peso obligatorio."""
        return await self.inyectar_parametro(parameter_name, value, peso=weight)

    async def trigger_expression(self, expression_file: str) -> bool:
        """Dispara un hotkey del modelo por su nombre o por su ID.

        `expression_file` es un nombre de hotkey de VTS, no un archivo: los
        nombres válidos son los que aparecen en la lista de hotkeys del modelo.
        VTS acepta el nombre sin distinguir mayúsculas, o el ID único.

        Returns:
            True si VTS confirmó la ejecución (`HotkeyTriggerResponse`).
            False si no hay modelo, el hotkey no existe o hubo un error de red.
        """
        respuesta = await self.peticion("HotkeyTriggerRequest",
                                        {"hotkeyID": expression_file})
        if not respuesta:
            return False
        if respuesta.get("messageType") == "APIError":
            print(f"[WARN] [VTS] Hotkey {expression_file!r}: "
                  f"{respuesta.get('data', {}).get('message')}")
            return False
        return respuesta.get("messageType") == "HotkeyTriggerResponse"

    async def listar_hotkeys(self) -> list[dict]:
        """Devuelve los hotkeys del modelo cargado en VTube Studio.

        Sirve para saber qué nombres se pueden usar: si un hotkey no está en
        esta lista, dispararlo devuelve un error aunque el mensaje se envíe
        bien.

        Returns:
            Lista de dicts con `name`, `type`, `file` y `hotkeyID`. Vacía si no
            hay ningún modelo cargado.
        """
        respuesta = await self.peticion("HotkeysInCurrentModelRequest")
        if not respuesta or respuesta.get("messageType") != \
                "HotkeysInCurrentModelResponse":
            return []
        return list(respuesta.get("data", {}).get("availableHotkeys", []))


vts_client = VTSClient()
