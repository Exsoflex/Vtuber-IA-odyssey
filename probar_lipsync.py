"""
Prueba del lip sync de Niu: ¿se mueve la boca con su voz?

Cómo funciona ahora el lip sync (esto es lo que se está midiendo):

    Niu sintetiza su voz  →  calcula la envolvente (0..1 a 40 Hz)
                                    ↓
                        inyecta en VTS (NiuMouthOpen, o su respaldo)
                                    ↓
                        modelo:  entrada  →  ParamMouthOpenY

Ya NO depende del micrófono de VTube Studio: Niu conoce su propio audio.

Dos fases, cada una aislando un eslabón:

    1. ¿Hay un parámetro que mueva la boca?  Se crea NiuMouthOpen y se prueba
       de verdad: se inyecta 0 y 1 y se mira si ParamMouthOpenY cambia.
    2. ¿Se mueve mientras habla?             Se dice una frase real y se
       muestrea ParamMouthOpenY durante toda la reproducción.

La fase 1 no mira archivos de configuración: mide el resultado. Es más fiable
que suponer, porque VTS puede tener mapeos que el archivo no refleja.

Uso:
    .venv\\Scripts\\python.exe probar_lipsync.py
"""

import asyncio
import sys

import numpy as np

from core.lipsync import (
    FPS,
    PARAMETRO_BOCA,
    PARAMETRO_LIVE2D,
    envolvente,
    hablar_con_lipsync,
    leer_apertura,
    resolver_parametro,
)
from core.vts_client import vts_client

sys.stdout.reconfigure(encoding="utf-8")

FRASE = "Uno, dos, tres, cuatro, cinco. La boca debería moverse con cada palabra."


# ─── Fase 0: la función pura, sin red ni audio ─────────────────────────


def probar_envolvente() -> bool:
    """Comprueba `envolvente()` con un tono fabricado, sin tocar VTS.

    Si esta parte falla, no tiene sentido mirar el avatar: el problema estaría
    en el cálculo, no en la comunicación.
    """
    print("[0/2] Función de envolvente (audio sintético)")
    fs = 48000
    # 1 segundo de tono y 1 segundo de silencio
    t = np.arange(fs) / fs
    onda = np.concatenate([0.6 * np.sin(2 * np.pi * 220 * t), np.zeros(fs)])
    boca = envolvente(onda.astype(np.float32), fs)

    mitad = len(boca) // 2
    con_tono = np.array(boca[:mitad])
    # Del silencio se ignoran los primeros 0.4 s: la boca se cierra despacio
    # a propósito (liberación), y medir el primer frame daría 0.7.
    cola = np.array(boca[mitad + 16:])

    print(f"      {len(boca)} frames para 2.0 s a {FPS} Hz")
    print(f"      con tono          min={con_tono.min():.3f} max={con_tono.max():.3f}")
    print(f"      silencio (cola)   min={cola.min():.3f} max={cola.max():.3f}")

    ok = con_tono.max() > 0.9 and cola.max() < 0.02
    print("      ✅ abre con el tono y cierra en silencio" if ok
          else "      ❌ valores fuera de lo esperado")
    return ok


# ─── Fase 1: hay un parámetro que mueve la boca ────────────────────────


async def fase_1_parametro() -> bool:
    """Resuelve qué parámetro mueve la boca y lo verifica."""
    print("\n[1/2] Parámetro que mueve la boca")

    antes = await leer_apertura()
    if antes is None:
        print("      ❌ VTS no tiene ningún modelo cargado")
        return False
    print(f"      {PARAMETRO_LIVE2D} antes de tocar nada: {antes:.3f}")

    activo = await resolver_parametro()
    if activo is None:
        return False

    if activo != PARAMETRO_BOCA:
        print(f"      ⚠️ se usará el respaldo {activo!r}: la boca se moverá igual,")
        print("         pero VTS también escribe ese parámetro desde su micrófono.")
        print("         Para el camino limpio, mapea una vez en VTube Studio:")
        print(f"           configuración de parámetros del modelo → 'Mouth Open'")
        print(f"           → cambia la entrada a {PARAMETRO_BOCA} → guarda")

    despues = await leer_apertura()
    print(f"      {PARAMETRO_LIVE2D} después del sondeo: {despues}")
    return True


# ─── Fase 2: la boca se mueve mientras Niu habla ───────────────────────


async def muestrear_boca(muestras: dict[str, list[float]]) -> None:
    """Lee la boca del modelo a 8 Hz mientras dura la frase."""
    respuesta = await vts_client.peticion("Live2DParameterListRequest")
    if not respuesta or respuesta.get("messageType") != "Live2DParameterListResponse":
        return
    for parametro in respuesta["data"].get("parameters", []):
        if "mouth" in parametro["name"].lower():
            muestras.setdefault(parametro["name"], []).append(
                float(parametro["value"]))


async def fase_2_movimiento() -> None:
    """Dice una frase real y mide si la boca se mueve."""
    print("\n[2/2] Niu va a decir una frase. Escúchala.")
    print("      Sirve para dos cosas: confirmar que la OYES y medir la BOCA.")

    muestras: dict[str, list[float]] = {}
    tarea = asyncio.create_task(
        hablar_con_lipsync(FRASE, "dia_por_dia/voz_temp.mp3"))

    # 8 Hz: suficiente para ver el movimiento y no competir con los 40 Hz de
    # la inyección (todas las peticiones van serializadas por un lock).
    while not tarea.done():
        await muestrear_boca(muestras)
        await asyncio.sleep(0.125)
    await tarea

    if not muestras:
        print("      ❌ no se pudo leer ningún parámetro de boca")
        return

    print()
    recorridos = {}
    for nombre, valores in sorted(muestras.items()):
        datos = np.array(valores)
        recorridos[nombre] = float(datos.max() - datos.min())
        # Cruces por el punto medio: "cuántas veces se abrió/cerró", no solo
        # "cuánto se movió en total". Una boca que se abre una vez y se queda
        # así da recorrido alto pero 0 cruces.
        medio = (datos.max() + datos.min()) / 2
        cruces = int(np.sum(np.diff(datos > medio) != 0))
        print(f"      {nombre:18s} min={datos.min():6.3f} max={datos.max():6.3f} "
              f"recorrido={recorridos[nombre]:.3f} cruces={cruces:2d} "
              f"muestras={len(datos)}")

    apertura = recorridos.get(PARAMETRO_LIVE2D, 0.0)
    print()
    if apertura > 0.05:
        print("      ✅ La boca se abre y se cierra: el lip sync funciona.")
        print("         Si al mirarla va desfasada, ajusta RETARDO_SALIDA en")
        print("         core/lipsync.py (positivo = retrasar la boca).")
    else:
        print("      ❌ La boca no se mueve aunque el parámetro se inyecta.")
        print("         Revisa en VTube Studio que exista un mapeo a")
        print(f"         {PARAMETRO_LIVE2D} y que su entrada sea")
        print(f"         {PARAMETRO_BOCA} o VoiceVolumePlusMouthOpen.")


async def main() -> None:
    print("=" * 70)
    print(" LIP SYNC DE NIU — PRUEBA EN DOS FASES")
    print("=" * 70)

    probar_envolvente()

    if not await vts_client.connect_and_auth():
        return

    try:
        if not await fase_1_parametro():
            print("\nSin parámetro no hay nada que probar. Aborta.")
            return
        await fase_2_movimiento()
    finally:
        await vts_client.close()


if __name__ == "__main__":
    asyncio.run(main())
