"""
Entrada de voz de Niu: captura y detección de silencio.

Nota de arquitectura: este módulo NO transcribe. Solo entrega audio.
Quién transcribe lo decide `crear_proveedor_stt()`, que devuelve un
STTProvider (core/stt_whisper.py o core/stt_gemini.py). Es el mismo patrón
que ya usa el cerebro con LLMProvider.

Usa sounddevice para capturar el micrófono (sin PyAudio, que no tiene wheel para
Python 3.14). Incluye un detector de silencio simple: espera a que empiece el
habla, graba mientras hablas y corta tras un segundo de silencio.
"""

import os

import numpy as np
import sounddevice as sd
import speech_recognition as sr

from core.idiomas import IDIOMA
from core.stt_provider import STTProvider, remuestrear

SAMPLE_RATE = 16000      # Hz, formato que esperan los motores de STT
BLOQUE = 0.1             # segundos por bloque analizado
UMBRAL_MINIMO = 200.0    # RMS mínimo para considerar que hay voz

# Cuánto silencio hay que oír para dar la frase por terminada.
#
# Esto es tiempo muerto puro: hasta que no transcurre, Niu no sabe que has
# acabado de hablar. 1,0 s era muy conservador: se notaba como un segundo de
# nada antes de que la transcripción siquiera empezara.
#
# Ojo con bajarlo demasiado. Medido a 0,6 s: en frases largas con una pausa
# natural en medio (respirar, buscar la palabra), el corte llega antes de
# tiempo y la frase se parte en dos. Las pausas al hablar duran más de lo que
# uno cree.
#
# 0,9 s es el equilibrio: se ahorra una décima respecto al original y aguanta
# respiraciones. Si aún te corta, súbelo sin tocar código:
#     $env:NIU_SILENCIO_FINAL = "1.1"
SILENCIO_FINAL = float(os.getenv("NIU_SILENCIO_FINAL", "0.9"))

FRASES_SALIDA = {"salir", "adiós", "adios", "terminar", "hasta luego"}


def _rms(bloque: np.ndarray) -> float:
    return float(np.sqrt(np.mean(bloque.astype(np.float64) ** 2)))


def _a_mono(bloque: np.ndarray, canal: int) -> np.ndarray:
    """Saca un canal de un bloque que puede venir en mono o en estéreo."""
    b = np.asarray(bloque)
    if b.ndim == 1:
        return b
    return b[:, canal]


def _canal_mas_fuerte(bloques: list[np.ndarray]) -> int:
    """
    Elige el canal con más señal.

    Algunos micrófonos USB entregan 2 canales donde uno va vacío o con otro
    contenido (por ejemplo, un bucle de monitoreo). Comparar el nivel de cada
    canal durante el silencio ambiente es la forma barata de elegir bien.
    """
    primero = np.asarray(bloques[0])
    if primero.ndim == 1 or primero.shape[1] == 1:
        return 0
    niveles = np.mean(
        [np.sqrt(np.mean(np.asarray(b, dtype=np.float64) ** 2, axis=0))
         for b in bloques],
        axis=0,
    )
    return int(np.argmax(niveles))


def _remuestrear_int16(datos: np.ndarray, fs_origen: int, fs_destino: int) -> np.ndarray:
    """Convierte la frecuencia de muestreo con filtro antialiasing (ver stt_provider)."""
    return remuestrear(datos, fs_origen, fs_destino)


def grabar_hasta_silencio(
    dispositivo: int | None = None,
    timeout_inicio: float = 8.0,
    silencio_final: float = SILENCIO_FINAL,
    duracion_maxima: float = 15.0,
) -> bytes | None:
    """
    Graba desde el micrófono hasta detectar silencio.

    Dos detalles importantes del camino de captura:

    1. WASAPI no permite abrir el dispositivo a una frecuencia distinta de la
       del mezclador de Windows, así que grabamos a la del dispositivo y luego
       remuestreamos a 16 kHz.

    2. NO se pide `channels=1` a un dispositivo estéreo. Cuando PortAudio tiene
       que convertir 2 canales a 1 en WASAPI, el audio sale deformado: el tono
       fundamental se dispara (error de octava), se pierden los agudos y ningún
       motor de STT reconoce la voz. Medido en este equipo con el DGM20:
       a 1 canal, Whisper no transcribía; a 2 canales, transcribía a la primera.
       Por eso se abre con los canales nativos y el canal se elige en Python.

    Returns:
        Bytes PCM 16-bit mono a 16 kHz, o None si no se detectó voz a tiempo.
    """
    info = (sd.query_devices(kind="input") if dispositivo is None
            else sd.query_devices(dispositivo))
    fs_dispositivo = int(info["default_samplerate"])
    canales = max(1, min(2, int(info["max_input_channels"])))

    tam_bloque = int(fs_dispositivo * BLOQUE)
    bloques_espera = int(timeout_inicio / BLOQUE)
    bloques_silencio = int(silencio_final / BLOQUE)
    bloques_maximos = int(duracion_maxima / BLOQUE)

    with sd.InputStream(
        samplerate=fs_dispositivo,
        channels=canales,
        dtype="int16",
        blocksize=tam_bloque,
        device=dispositivo,
    ) as stream:
        ambiente = [np.asarray(stream.read(tam_bloque)[0]) for _ in range(10)]
        canal = _canal_mas_fuerte(ambiente)
        ruido = float(np.median([_rms(_a_mono(m, canal)) for m in ambiente]))
        umbral = max(UMBRAL_MINIMO, ruido * 2.0 + 50.0)

        # 1. Esperar a que empiece el habla
        inicio = None
        for _ in range(bloques_espera):
            bloque, _ = stream.read(tam_bloque)
            if _rms(_a_mono(bloque, canal)) > umbral:
                inicio = _a_mono(bloque, canal).copy()
                break

        if inicio is None:
            return None

        # 2. Acumular hasta silencio sostenido
        partes = [inicio]
        silencio_acumulado = 0
        for _ in range(bloques_maximos):
            bloque, _ = stream.read(tam_bloque)
            mono = _a_mono(bloque, canal)
            partes.append(mono.copy())
            if _rms(mono) > umbral:
                silencio_acumulado = 0
            else:
                silencio_acumulado += 1
                if silencio_acumulado >= bloques_silencio:
                    break

    audio_completo = np.concatenate(partes).flatten()
    audio_completo = _remuestrear_int16(audio_completo, fs_dispositivo, SAMPLE_RATE)
    return audio_completo.tobytes()


def reconocer(audio_pcm: bytes, idioma: str = "es-MX") -> str | None:
    """
    Transcripción con Google Web Speech (heredado).

    Se conserva solo para las herramientas de diagnóstico, que son síncronas.
    El motor de Niu es el STTProvider que devuelve `crear_proveedor_stt()`.
    Esta API es la que fallaba con voz real de micrófono: devolvía vacío.
    """
    reconocedor = sr.Recognizer()
    audio = sr.AudioData(audio_pcm, SAMPLE_RATE, 2)
    try:
        return reconocedor.recognize_google(audio, language=idioma)
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print(f"[STT] Servicio de voz no disponible: {e}")
        return None


def idioma_stt() -> str | None:
    """Idioma que se le pide al reconocedor de voz, o None para automático.

    Por defecto **sigue al perfil** (`NIU_IDIOMA`). Si Niu va a contestar en
    inglés, el oído tiene que esperar inglés: dejarlo en automático era el
    fallo, porque con una frase corta y un prompt en español Whisper "oía"
    español aunque se le hablara en inglés. Niu respondía entonces a una
    transcripción que no era lo que se había dicho.

    `NIU_STT_IDIOMA` fuerza otro idioma, o `auto` para volver a la detección
    automática (útil si de verdad alternas idiomas en la misma sesión, a
    sabiendas de que el prompt del perfil sigue sesgando la detección).
    """
    pedido = os.getenv("NIU_STT_IDIOMA", "").strip().lower()
    if pedido == "auto":
        return None
    return pedido or IDIOMA.codigo


def crear_proveedor_stt() -> STTProvider:
    """
    Crea el motor de reconocimiento configurado en el .env.

    NIU_STT = whisper | gemini
        whisper : local, sin internet ni cuotas (necesita buen audio de entrada)
        gemini  : nube, muy robusto con audio difícil (necesita GOOGLE_API_KEY)

    NIU_STT_IDIOMA = es | en | auto (por defecto, el idioma del perfil)
    """
    motor = os.getenv("NIU_STT", "whisper").strip().lower()
    idioma = idioma_stt()

    if motor == "gemini":
        from core.stt_gemini import GeminiSTT

        proveedor = GeminiSTT()
    elif motor == "whisper":
        from core.stt_whisper import WhisperSTT

        # El idioma se pasa al constructor para que el prompt del decoder y el
        # calentamiento usen el mismo idioma que la transcripción.
        proveedor = WhisperSTT(idioma=idioma)
    else:
        raise ValueError(
            f"NIU_STT='{motor}' no es válido. Usa 'whisper' o 'gemini'."
        )

    print(f"[STT] Motor: {proveedor.nombre} | idioma: {idioma or 'detección automática'}")
    return proveedor
