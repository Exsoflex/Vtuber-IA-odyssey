"""
Tests del cliente de VTube Studio: disparo de hotkeys y lista de hotkeys.

Por qué esto merece tests: el nombre del mensaje que dispara un hotkey es
exactamente el tipo de dato que nadie mira. El código usaba
`TriggerHotkeyRequest` y la API de VTS espera `HotkeyTriggerRequest`: el
mensaje salía bien formado, VTS lo recibía, lo rechazaba con un `APIError` y
el error se perdía en un warning de consola. Las expresiones de Niu no
funcionaban y no había ningún síntoma visible.

Estos tests comprueban el mensaje exacto que sale por el WebSocket, sin
necesitar VTube Studio: un WebSocket falso que guarda lo enviado y devuelve
lo que se le pida.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json

from core.vts_client import VTSClient


class WebSocketFalso:
    """WebSocket que guarda lo enviado y devuelve respuestas preparadas."""

    def __init__(self, respuestas: list[dict]) -> None:
        self.pendientes = list(respuestas)
        self.enviados: list[dict] = []

    async def send(self, texto: str) -> None:
        self.enviados.append(json.loads(texto))

    async def recv(self) -> str:
        return json.dumps(self.pendientes.pop(0))

    async def close(self) -> None:
        pass


def cliente_con(respuestas: list[dict]) -> tuple[VTSClient, WebSocketFalso]:
    """Devuelve un cliente ya conectado, con su WebSocket falso."""
    c = VTSClient()
    c.websocket = WebSocketFalso(respuestas)
    c.connected = True
    return c, c.websocket


# ─── Disparo de hotkeys ───────────────────────────────────────────────


async def test_dispara_un_hotkey_con_el_nombre_correcto_del_mensaje():
    """El mensaje tiene que llamarse `HotkeyTriggerRequest`, sin más.

    Este es el test que habría pillado el bug: el nombre del mensaje es un
    dato, no una convención, y VTS responde `APIError` si no coincide.
    """
    cliente, ws = cliente_con([
        {"messageType": "HotkeyTriggerResponse",
         "data": {"hotkeyID": "abc123"}},
    ])

    ok = await cliente.trigger_expression("MouthSmile")

    assert ok is True
    enviado = ws.enviados[0]
    assert enviado["messageType"] == "HotkeyTriggerRequest"
    assert enviado["data"]["hotkeyID"] == "MouthSmile"


async def test_el_nombre_del_hotkey_llega_sin_espacios_extra():
    """VTS compara el nombre sin distinguir mayúsculas, pero no lo recorta."""
    cliente, ws = cliente_con([
        {"messageType": "HotkeyTriggerResponse", "data": {}},
    ])

    await cliente.trigger_expression("MouthOpen")

    assert ws.enviados[0]["data"]["hotkeyID"] == "MouthOpen"


async def test_un_hotkey_inexistente_devuelve_false_y_no_revienta():
    """VTS responde con `APIError`; eso es un fallo controlado, no una caída."""
    cliente, _ = cliente_con([
        {"messageType": "APIError",
         "data": {"errorID": 8, "message": "Hotkey not found"}},
    ])

    ok = await cliente.trigger_expression("NoExiste")

    assert ok is False


async def test_sin_conexion_no_dispara_nada():
    """Sin WebSocket no se puede ni intentar."""
    cliente = VTSClient()
    cliente.connected = False
    cliente.websocket = None

    ok = await cliente.trigger_expression("MouthSmile")

    assert ok is False


# ─── Lista de hotkeys ──────────────────────────────────────────────────


async def test_lista_los_hotkeys_del_modelo_cargado():
    cliente, ws = cliente_con([
        {"messageType": "HotkeysInCurrentModelResponse",
         "data": {"modelLoaded": True,
                  "availableHotkeys": [
                      {"name": "MouthSmile", "type": "ToggleExpression",
                       "file": "smile.exp3.json", "hotkeyID": "id1"},
                      {"name": "MouthOpen", "type": "ToggleExpression",
                       "file": "open.exp3.json", "hotkeyID": "id2"},
                  ]}},
    ])

    hotkeys = await cliente.listar_hotkeys()

    assert ws.enviados[0]["messageType"] == "HotkeysInCurrentModelRequest"
    assert [h["name"] for h in hotkeys] == ["MouthSmile", "MouthOpen"]


async def test_sin_modelo_cargado_la_lista_vacia():
    cliente, _ = cliente_con([
        {"messageType": "HotkeysInCurrentModelResponse",
         "data": {"modelLoaded": False, "availableHotkeys": []}},
    ])

    assert await cliente.listar_hotkeys() == []


async def test_una_respuesta_inesperada_no_rompe_la_lista():
    cliente, _ = cliente_con([
        {"messageType": "APIError", "data": {"message": "no model loaded"}},
    ])

    assert await cliente.listar_hotkeys() == []
