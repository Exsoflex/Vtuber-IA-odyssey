"""
Utilidades para localizar dispositivos de audio por nombre.

sounddevice expone el mismo dispositivo físico varias veces (MME, DirectSound,
WASAPI, WDM-KS). Elegimos el backend según el caso:

- Entrada: WASAPI, el más moderno y con menor latencia.
- Salida: DirectSound, porque WASAPI falla al abrir el stream desde un hilo
  secundario (el que usa asyncio.to_thread) con "Unanticipated host error".

Nota de Windows: el nombre de un dispositivo en MME se corta a 31 caracteres
("Auriculares (DGM20 USB Micropho"), pero sigue sirviendo para buscarlo, porque
la búsqueda es por subcadena y el nombre completo de los otros backends lo
contiene.
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


def buscar_salida_por_defecto() -> int | None:
    """Devuelve el dispositivo de salida de Windows, por el mejor backend.

    PortAudio marca como predeterminado el primer endpoint que encuentra, y en
    Windows casi siempre es el de MME: el más antiguo y el de peor latencia.
    En vez de usarlo tal cual, se toma el *nombre* del predeterminado y se
    busca ese mismo nombre en los demás backends, donde `PRIORIDAD_SALIDA`
    decide.

    Así Niu suena donde suena el sistema (si el usuario cambia de auriculares,
    Niu se muda con él) sin quedar clavado a un nombre de dispositivo concreto.

    Returns:
        Índice del dispositivo, o None si no hay salida predeterminada.
    """
    indice = sd.default.device[1]
    if indice is None or indice < 0:
        return None

    nombre = sd.query_devices(indice)["name"]
    encontrado = buscar_dispositivo(nombre, salida=True)
    if encontrado is None:
        print(f"[AUDIO] '{nombre}' solo existe en un backend; uso [{indice}] "
              f"tal cual")
        return indice
    return encontrado
