"""
Prueba del lip sync de Niu: ¿VTube Studio oye su voz y mueve la boca?

Cómo funciona el lip sync (importante para entender qué se está midiendo):

    Niu reproduce su voz  →  Voicemeeter (strip VAIO)  →  bus B1
                                                          ↓
                              VTube Studio escucha B1, calcula el volumen
                              y mueve ParamMouthOpenY (la boca)

Niu NO puede mover la boca por la API: la API pública no permite escribir
parámetros Live2D, solo parámetros de tracking propios. Por eso este script
solo comprueba, no empuja nada.

Se hacen dos comprobaciones independientes:

  1. ¿VTS OYE?          -> lee VoiceVolume y VoiceSilence mientras suena un tono.
  2. ¿SE MUEVE LA BOCA? -> lee ParamMouthOpenY mientras Niu habla de verdad.

Así se distingue un problema de captura (VTS no oye) de un problema de mapeo
(VTS oye pero el modelo no tiene la boca conectada).

Uso:
    .venv\\Scripts\\python.exe probar_lipsync.py
"""

import asyncio
import json
import sys
import time

import numpy as np
import sounddevice as sd

from core.tts import _buscar_dispositivo_salida, sintetizar_y_reproducir_voz_async
from core.vts_client import vts_client

sys.stdout.reconfigure(encoding="utf-8")

FS = 48000
TRAMO = 0.8          # segundos de cada tramo del tono de prueba
CICLOS = 2           # pares fuerte/silencio
FRASE = "Uno, dos, tres, cuatro, cinco. La boca debería moverse con cada palabra."
PARAMETROS_VOZ = ["VoiceVolume", "VoiceSilence"]


async def pedir(message_type: str, data: dict | None = None) -> dict:
    """Envía una petición a la API de VTS y devuelve la respuesta ya decodificada."""
    payload = {
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": f"{message_type}_{time.time_ns() % 100000}",
        "messageType": message_type,
    }
    if data is not None:
        payload["data"] = data
    await vts_client.websocket.send(json.dumps(payload))
    return json.loads(await vts_client.websocket.recv())


async def leer_parametros(nombres: list[str]) -> dict[str, float]:
    """Lee varios parámetros de tracking (VoiceVolume, etc.) de una vez."""
    valores = {}
    for nombre in nombres:
        respuesta = await pedir("ParameterValueRequest", {"name": nombre})
        if respuesta.get("messageType") == "ParameterValueResponse":
            valores[nombre] = float(respuesta["data"]["value"])
    return valores


async def leer_live2d(nombres: list[str]) -> dict[str, float]:
    """Lee parámetros Live2D del modelo (la lista completa trae los valores)."""
    respuesta = await pedir("Live2DParameterListRequest")
    if respuesta.get("messageType") != "Live2DParameterListResponse":
        return {}
    return {p["name"]: float(p["value"])
            for p in respuesta["data"].get("parameters", [])
            if p["name"] in nombres}


def tono_de_prueba() -> np.ndarray:
    """Tono y silencio alternos: un volumen 'cuadrado' fácil de reconocer."""
    t = np.arange(int(FS * TRAMO)) / FS
    fuerte = 0.6 * np.sin(2 * np.pi * 220 * t)
    silencio = np.zeros_like(fuerte)
    return np.concatenate([fuerte, silencio] * CICLOS).astype(np.float32)


async def fase_1_oir() -> bool:
    """¿VTube Studio está recibiendo audio del bus B1?"""
    print("\n[1/2] ¿VTube Studio OYE el audio?")
    salida = _buscar_dispositivo_salida()
    if salida is None:
        print("      No encontré el dispositivo de salida de Niu.")
        return False

    audio = tono_de_prueba()
    canales = int(sd.query_devices(salida)["max_output_channels"]) or 1
    muestras = {n: [] for n in PARAMETROS_VOZ}

    print(f"      Reproduciendo {CICLOS} tonos en "
          f"[{salida}] {sd.query_devices(salida)['name']}")
    sd.play(np.column_stack([audio] * canales), FS, device=salida, blocking=False)
    inicio = time.perf_counter()
    while time.perf_counter() - inicio < TRAMO * 2 * CICLOS:
        for nombre, valor in (await leer_parametros(PARAMETROS_VOZ)).items():
            muestras[nombre].append(valor)
        await asyncio.sleep(0.05)
    sd.stop()

    volumen = np.array(muestras["VoiceVolume"] or [0.0])
    silencio = np.array(muestras["VoiceSilence"] or [0.0])
    print(f"      VoiceVolume  min={volumen.min():.3f} max={volumen.max():.3f}")
    print(f"      VoiceSilence min={silencio.min():.3f} max={silencio.max():.3f}")

    if volumen.max() - volumen.min() > 0.05:
        print("      ✅ VTS está oyendo el bus B1.")
        return True

    print("      ❌ VTS no está oyendo nada.")
    print("         Revisa en VTube Studio (Configuración > Lipsync):")
    print("           - 'Use microphone' activado")
    print("           - dispositivo = 'Voicemeeter Out B1'")
    print("           - si pone 'failed to initialize (timeout)', reinicia VTS:")
    print("             Unity no reconstruye bien la lista de dispositivos.")
    return False


async def fase_2_boca(oye: bool) -> None:
    """¿El parámetro de apertura de boca se mueve mientras Niu habla?

    Se ejecuta siempre, aunque la fase 1 haya fallado: esta fase reproduce una
    frase real de Niu, así que también sirve para comprobar de oído que el audio
    sale por los auriculares.
    """
    print("\n[2/2] Niu va a decir una frase. Escúchala.")
    print("      Sirve para dos cosas: confirmar que la OYES y medir la BOCA.")

    respuesta = await pedir("Live2DParameterListRequest")
    if respuesta.get("messageType") != "Live2DParameterListResponse":
        print("      No se pudo leer la lista de parámetros del modelo.")
        return

    datos = respuesta["data"]
    nombres = [p["name"] for p in datos.get("parameters", [])
               if "mouth" in p["name"].lower()]
    print(f"      Modelo: {datos.get('modelName')!r}")
    if not nombres:
        print("      El modelo no tiene parámetros de boca.")
        return

    tarea = asyncio.create_task(
        sintetizar_y_reproducir_voz_async(FRASE, "dia_por_dia/voz_temp.mp3"))

    muestras = {n: [] for n in nombres}
    while not tarea.done():
        for nombre, valor in (await leer_live2d(nombres)).items():
            muestras[nombre].append(valor)
        await asyncio.sleep(0.07)
    await tarea

    recorridos = {}
    for nombre, valores in muestras.items():
        if not valores:
            continue
        recorridos[nombre] = max(valores) - min(valores)
        print(f"      {nombre:18s} min={min(valores):6.3f} max={max(valores):6.3f} "
              f"recorrido={recorridos[nombre]:.3f}")

    apertura = recorridos.get("ParamMouthOpenY", 0.0)
    if apertura > 0.05:
        print("      ✅ La boca se abre y se cierra: el lip sync funciona.")
    elif not oye:
        print("      ❌ La boca no se mueve, pero es coherente: la fase 1 ya")
        print("         avisó de que VTS no está oyendo. Arregla la captura")
        print("         primero y vuelve a ejecutar esta prueba.")
    else:
        print("      ❌ La boca no se mueve, aunque VTS SÍ oye el audio.")
        print("         Entonces el problema es el mapeo: en VTube Studio,")
        print("         Configuración > Lipsync > botón de auto-configuración")
        print("         para conectar MouthOpen -> ParamMouthOpenY.")


async def main() -> None:
    print("=" * 70)
    print(" LIP SYNC DE NIU — PRUEBA EN DOS FASES")
    print("=" * 70)

    if not await vts_client.connect_and_auth():
        return

    try:
        oye = await fase_1_oir()
        await fase_2_boca(oye)
    finally:
        await vts_client.close()


if __name__ == "__main__":
    asyncio.run(main())
