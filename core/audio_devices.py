"""
Utilidades para localizar dispositivos de audio por nombre.

sounddevice expone el mismo dispositivo físico varias veces (MME, DirectSound,
WASAPI, WDM-KS). Elegimos el backend según el caso:

- Entrada: WASAPI, el más moderno y con menor latencia.
- Salida: DirectSound, porque WASAPI falla al abrir el stream desde un hilo
  secundario (el que usa asyncio.to_thread) con "Unanticipated host error".
"""

import sounddevice as sd

PRIORIDAD_ENTRADA = {
    "Windows WASAPI": 3,
    "Windows DirectSound": 2,
    "MME": 1,
    "Windows WDM-KS": 0,
}

PRIORIDAD_SALIDA = {
    "Windows DirectSound": 3,
    "MME": 2,
    "Windows WASAPI": 1,
    "Windows WDM-KS": 0,
}


def buscar_dispositivo(fragmento: str, salida: bool = False) -> int | None:
    """
    Devuelve el índice del mejor dispositivo cuyo nombre contenga `fragmento`.

    Args:
        fragmento: Parte del nombre a buscar (ej. "Voicemeeter Out B1").
        salida: True para buscar dispositivos de reproducción, False para entrada.

    Returns:
        Índice del dispositivo o None si no existe.
    """
    clave_canales = "max_output_channels" if salida else "max_input_channels"
    prioridades = PRIORIDAD_SALIDA if salida else PRIORIDAD_ENTRADA
    hostapis = sd.query_hostapis()

    candidatos = []
    for indice, dispositivo in enumerate(sd.query_devices()):
        if fragmento.lower() not in dispositivo["name"].lower():
            continue
        if dispositivo[clave_canales] <= 0:
            continue
        hostapi = hostapis[dispositivo["hostapi"]]["name"]
        candidatos.append((prioridades.get(hostapi, 0), indice, dispositivo["name"], hostapi))

    if not candidatos:
        return None

    candidatos.sort(reverse=True)
    prioridad, indice, nombre, hostapi = candidatos[0]
    print(f"[AUDIO] Dispositivo: [{indice}] {nombre} ({hostapi})")
    return indice
