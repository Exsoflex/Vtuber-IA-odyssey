"""
Módulo de Síntesis Vocal (TTS) para Niu Autonomous Engine.

Usa Edge-TTS para voz natural y emotiva en español. Filtra emojis para la
síntesis vocal pero los conserva para subtítulos.

Está dividido en tres pasos independientes:

    sintetizar_voz_async()  -> genera el archivo de audio
    preparar_audio()        -> lo carga, lo remuestrea y lo adapta al endpoint
    reproducir_audio()      -> lo manda al dispositivo (bloqueante)

Están separados porque el lip sync necesita el audio **antes** de que suene:
con `AudioPreparado.mono` se calcula la envolvente de la boca y después se
reproduce e inyecta a la vez. Si todo estuviera en una sola función no habría
forma de saber qué va a sonar hasta que ya ha sonado.
"""

import asyncio
import os
import re
from dataclasses import dataclass

import numpy as np
from dotenv import load_dotenv

from core import config
from core.audio_devices import buscar_dispositivo, buscar_salida_por_defecto
from core.idiomas import tono_activo, voz_activa

load_dotenv()

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    print("[WARN] edge-tts no instalado. Instala con: pip install edge-tts")

try:
    import sounddevice as sd
    import soundfile as sf

    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    sd = None
    sf = None
    SOUNDDEVICE_AVAILABLE = False
    print("[WARN] sounddevice o soundfile no instalado. "
          "Instala con: pip install sounddevice soundfile")

# ─── Configuración de voz ──────────────────────────────────────────────
# Nada de esto es una constante de importación: la voz, el tono, el ritmo y el
# dispositivo se leen de `core/config.py` en el momento de usarlos. Así el panel
# puede cambiarlos y la siguiente frase ya sale distinta, sin reiniciar Python.
TARGET_SAMPLE_RATE = 48000  # Hz; se remuestrea aquí para no depender del endpoint

# Salida de voz.
#
# Por defecto (sin `salida` en los ajustes) Niu suena donde suena Windows: se
# coge el dispositivo de salida predeterminado del sistema y se busca ese mismo
# dispositivo en el mejor backend disponible. Así no queda clavado al hardware
# de este equipo: si el usuario cambia de auriculares, Niu se muda con él.
#
# Historia: antes la voz iba a "Voicemeeter Input" para que VTube Studio la
# escuchara por el cable virtual y moviera la boca. Ese camino se abandonó (ver
# core/lipsync.py): ahora la boca la mueve Niu a partir de su propia onda, así
# que el audio puede ir directo a los auriculares. Un salto menos, menos
# latencia y una pieza menos que puede romperse.

# Tope de tiempo por síntesis, y cuántas veces se reintenta.
#
# Edge-TTS es un servicio externo, no una función local: a veces tarda, y a
# veces deja de contestar sin cerrar la conexión. Sin tope, eso cuelga la
# conversación entera para siempre; medido en este equipo, un turno se quedó
# esperando más de 5 minutos dentro de `comunicador.save()`.
#
# Perder una frase es molesto; quedarse mudo del todo es peor. Con un tope, el
# turno sigue: la parte que falló se salta y el resto se dice igual. Los valores
# viven en `Ajustes` (`tts_timeout`, `tts_intentos`) y se leen por llamada.


@dataclass
class AudioPreparado:
    """Audio listo para sonar y para medir.

    Attributes:
        mono: señal a 48 kHz, un canal. Es la referencia para el lip sync.
        salida: la misma señal, ya con el número de canales del endpoint.
        fs: frecuencia de muestreo de ambas.
        device_id: índice del dispositivo de salida (None si no se encontró).
    """

    mono: np.ndarray
    salida: np.ndarray
    fs: int
    device_id: int | None

    @property
    def duracion(self) -> float:
        """Duración en segundos."""
        return len(self.mono) / self.fs


# ─── Recorte del silencio de los extremos ──────────────────────────────
#
# Edge-TTS rellena cada frase con silencio: medido en este equipo, ~0,18 s al
# principio y ~0,85 s al final. En una respuesta entera no se nota, porque el
# relleno solo está en los bordes. Al hablar por partes, cada trozo arrastra su
# propio relleno y las fronteras se llenan de aire: con 3 partes son ~2 s de
# pausa, y "¡Hola!" pasaba de 1,87 s a solo 0,40 s de voz real.
#
# Se recorta, pero NO hasta cero: un poco de silencio al final de una frase es
# lo que hace que el habla suene natural y no atropellada. Estos márgenes son
# los que suenan bien, no los que más ahorran.
MARGEN_INICIO = 0.05         # s de silencio que se conservan antes de la voz
MARGEN_FINAL = 0.15          # s de silencio que se conservan después
VENTANA_SILENCIO = 0.025     # s por bloque analizado (el mismo criterio que la boca)
UMBRAL_SILENCIO = 0.02       # 2 % del pico: por debajo, es silencio


def recortar_silencio(mono: np.ndarray, fs: int) -> np.ndarray:
    """Quita el silencio de los extremos, conservando un margen audible.

    Es una función pura (entra un array, sale otro), así que se puede probar sin
    red ni audio real.

    Args:
        mono: muestras float32 en [-1, 1].
        fs: frecuencia de muestreo.

    Returns:
        El mismo audio, recortado. Si todo es silencio, se devuelve igual: no
        hay nada que recortar y devolver un array vacío rompería la reproducción.
    """
    bloque = max(1, int(fs * VENTANA_SILENCIO))
    n = len(mono) // bloque
    if n == 0:
        return mono

    trozos = mono[: n * bloque].reshape(n, bloque)
    rms = np.sqrt((trozos.astype(np.float64) ** 2).mean(axis=1))

    # Umbral relativo al pico, no absoluto: el volumen de Edge-TTS puede variar.
    umbral = max(float(rms.max()) * UMBRAL_SILENCIO, 1e-6)
    activos = np.flatnonzero(rms > umbral)
    if len(activos) == 0:
        return mono

    inicio = max(0, int((activos[0] * VENTANA_SILENCIO - MARGEN_INICIO) * fs))
    fin = min(len(mono),
              int(((activos[-1] + 1) * VENTANA_SILENCIO + MARGEN_FINAL) * fs))
    return mono[inicio:fin]


def _limpiar_texto_para_tts(texto: str) -> str:
    """
    Elimina emojis y caracteres especiales para la síntesis vocal.
    Los emojis se mantienen para subtítulos en pantalla.
    """
    # Rangos Unicode de emojis
    patron_emojis = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Emoticones
        "\U0001F300-\U0001F5FF"  # Símbolos y pictogramas
        "\U0001F680-\U0001F6FF"  # Transporte y símbolos
        "\U0001F1E0-\U0001F1FF"  # Banderas (países)
        "\U00002700-\U000027BF"  # Símbolos diversos
        "\U000024C2-\U0001F251"  # Caracteres encerrados
        "\U0001F900-\U0001F9FF"  # Símbolos suplementarios
        "\U0001FA70-\U0001FAFF"  # Símbolos y pictogramas extendidos
        "\U0001F000-\U0001F02F"  # Juegos de dados
        "]+",
        flags=re.UNICODE,
    )
    texto_limpio = patron_emojis.sub("", texto)
    # Limpiar espacios múltiples
    texto_limpio = re.sub(r"\s+", " ", texto_limpio).strip()
    return texto_limpio


# ─── Paso 1: generar ───────────────────────────────────────────────────


async def sintetizar_voz_async(
    texto: str,
    archivo_salida: str = "core/voz_temp.mp3",
    voz: str | None = None,
) -> bool:
    """Sintetiza texto a audio con Edge-TTS y lo guarda en disco.

    Args:
        texto: Texto a sintetizar (puede contener emojis).
        archivo_salida: Ruta del archivo de audio temporal.
        voz: Nombre de la voz de Edge-TTS. None = la de los ajustes activos
            (que a su vez puede ser la del perfil de idioma).

    Returns:
        True si el archivo se generó y no está vacío.
    """
    ajustes = config.ajustes()
    voz = voz or voz_activa()
    velocidad = ajustes.velocidad
    tono = tono_activo()

    try:
        print("🎙️ [TTS Edge]: Niu está preparando su voz...")

        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError("edge-tts no instalado. Instala con: pip install edge-tts")

        # Limpiar emojis para la síntesis vocal (se conservan para subtítulos)
        texto_para_tts = _limpiar_texto_para_tts(texto)
        if not texto_para_tts.strip():
            # Normal en streaming: el corte por frases deja trozos que solo
            # tenían emojis. No es un fallo, no hay nada que decir.
            print("[TTS] Trozo sin texto (solo emojis): se salta")
            return False

        comunicador = edge_tts.Communicate(
            text=texto_para_tts,
            voice=voz,
            rate=velocidad,
            pitch=tono,
        )

        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)

        # Se crea un comunicador nuevo en cada intento: `save()` consume el
        # comunicador, así que reutilizarlo tras un fallo no funcionaría.
        for intento in range(1, ajustes.tts_intentos + 1):
            if intento > 1:
                comunicador = edge_tts.Communicate(
                    text=texto_para_tts, voice=voz, rate=velocidad, pitch=tono
                )
            try:
                await asyncio.wait_for(comunicador.save(archivo_salida),
                                       timeout=ajustes.tts_timeout)
                break
            except asyncio.TimeoutError:
                print(f"[WARN] [TTS Edge] Sin respuesta en "
                      f"{ajustes.tts_timeout:.1f} s "
                      f"(intento {intento}/{ajustes.tts_intentos})")
                if intento == ajustes.tts_intentos:
                    print("[WARN] [TTS Edge] Se salta esta frase")
                    return False

        print(f"[TTS Edge]: Audio generado y guardado "
              f"({os.path.getsize(archivo_salida)} bytes)")
        return True

    except Exception as e:
        print(f"[WARN] [TTS Edge] Falló: {type(e).__name__}: {e}")
        return False


# ─── Paso 2: preparar ──────────────────────────────────────────────────


def preparar_audio(ruta_audio: str) -> AudioPreparado | None:
    """Carga el audio y lo deja en el formato que espera el endpoint.

    Hace tres cosas:

    1. Lee el archivo como float32 (rango -1.0 a 1.0, que es lo que usa
       sounddevice; los enteros de 16 bits no valen directamente).
    2. Remuestrea a 48 kHz, una frecuencia que casi todos los endpoints
       aceptan (los virtuales de Windows trabajan a 48 kHz de forma nativa).
    3. Coloca la voz en los canales que espera el endpoint. El endpoint puede
       declarar más canales de los que existen de verdad (el de DirectSound
       dice 8, formato 7.1), pero la voz es mono: va en los dos primeros y el
       resto en silencio.
    4. Recorta el silencio de los extremos (`recortar_silencio`).

    Returns:
        `AudioPreparado` o None si no se pudo leer.
    """
    if not SOUNDDEVICE_AVAILABLE:
        print("[WARN] sounddevice no disponible: no se puede preparar el audio")
        return None

    try:
        data, fs = sf.read(ruta_audio, dtype="float32")
    except Exception as e:
        print(f"[WARN] [TTS] No se pudo leer {ruta_audio}: {type(e).__name__}: {e}")
        return None

    if data.ndim > 1:
        mono = data.mean(axis=1)   # la boca se mide sobre la mezcla, no sobre un canal
    else:
        mono = data

    if fs != TARGET_SAMPLE_RATE:
        print(f"[TTS] Re-muestreando de {fs} Hz a {TARGET_SAMPLE_RATE} Hz...")
        mono = _remuestrear_audio(mono, fs, TARGET_SAMPLE_RATE)
        fs = TARGET_SAMPLE_RATE

    # Recorte del relleno de Edge-TTS. Importa sobre todo hablando por partes:
    # cada trozo trae su propio silencio y sin recortarlo las fronteras suman
    # pausas de casi un segundo.
    duracion_antes = len(mono) / fs
    mono = recortar_silencio(mono, fs)
    recortado = duracion_antes - len(mono) / fs
    if recortado >= 0.2:
        print(f"[TTS] Recorte de silencio: {recortado:.2f} s "
              f"({duracion_antes:.2f} s → {len(mono) / fs:.2f} s)")

    device_id = _buscar_dispositivo_salida()
    canales = 1
    if device_id is not None:
        canales = int(sd.query_devices(device_id)["max_output_channels"]) or 1

    if canales < 2:
        salida = mono[:, None].astype(np.float32)
    else:
        # Duplicar la voz en los 8 canales haría que el sistema la mezcle varias
        # veces al bajar a estéreo; mejor callar los que no van a sonar.
        silencio = np.zeros_like(mono)
        salida = np.column_stack([mono, mono, *[silencio] * (canales - 2)]).astype(np.float32)

    return AudioPreparado(mono=mono.astype(np.float32), salida=salida,
                          fs=fs, device_id=device_id)


# ─── Paso 3: reproducir ────────────────────────────────────────────────


def reproducir_audio(audio: AudioPreparado) -> None:
    """Reproduce el audio por el dispositivo de salida. Bloqueante.

    Es bloqueante a propósito: quien la llama decide si la manda a un hilo
    (`asyncio.to_thread`) para poder hacer otra cosa mientras suena.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return

    if audio.device_id is None:
        print("[WARN] No encontré dispositivo de salida, usando el que Windows "
              "tenga por defecto")
        sd.play(audio.salida[:, 0], audio.fs)
    else:
        nombre = sd.query_devices(audio.device_id)["name"]
        print(f"[TTS] Reproduciendo en [{audio.device_id}] {nombre} "
              f"({audio.fs} Hz)...")
        sd.play(audio.salida, audio.fs, device=audio.device_id)

    sd.wait()
    print("[TTS] Reproducción completada")


# ─── Atajo para pruebas de audio (sin avatar) ──────────────────────────


async def sintetizar_y_reproducir_voz_async(
    texto: str,
    archivo_salida: str = "core/voz_temp.mp3",
    voz: str | None = None,
) -> bool:
    """Genera y reproduce una frase, sin lip sync.

    Sirve para aislar problemas: si con esto se oye y con `hablar_con_lipsync`
    no, el fallo está en el lip sync y no en el audio.
    """
    if not await sintetizar_voz_async(texto, archivo_salida, voz):
        return False

    if not SOUNDDEVICE_AVAILABLE:
        import winsound
        winsound.PlaySound(archivo_salida, winsound.SND_FILENAME)
        return True

    audio = preparar_audio(archivo_salida)
    if audio is None:
        return False

    await asyncio.to_thread(reproducir_audio, audio)
    return True


def _buscar_dispositivo_salida() -> int | None:
    """Busca el dispositivo de salida de audio.

    Sin `salida` en los ajustes devuelve el que Windows tenga por defecto; con
    ella, el primero cuyo nombre contenga ese texto. Se lee por llamada, así
    que cambiarla desde el panel afecta a la siguiente frase.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return None
    nombre = config.ajustes().salida
    if not nombre:
        return buscar_salida_por_defecto()
    return buscar_dispositivo(nombre, salida=True)


def _remuestrear_audio(data, fs_origen: int, fs_objetivo: int):
    """
    Re-muestrea audio usando interpolación lineal (sin scipy).
    """
    if fs_origen == fs_objetivo:
        return data

    duracion = len(data) / fs_origen
    nueva_longitud = int(duracion * fs_objetivo)

    indices_originales = np.arange(len(data))
    nuevos_indices = np.linspace(0, len(data) - 1, nueva_longitud)

    if data.ndim == 1:
        return np.interp(nuevos_indices, indices_originales, data)

    return np.column_stack([
        np.interp(nuevos_indices, indices_originales, data[:, canal])
        for canal in range(data.shape[1])
    ])
