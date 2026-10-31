"""
Lip sync controlado por Niu: la boca la mueve ella, no el micrófono de VTS.

Por qué existe
--------------
El lip sync integrado de VTube Studio escucha un dispositivo de audio y mueve
la boca según el volumen. En este equipo eso es frágil: Unity (el motor de VTS)
cachea la lista de dispositivos al arrancar y, si Voicemeeter se reinicia
mientras tanto, pierde el bus `Voicemeeter Out B1` y no lo recupera hasta
reiniciar VTS. Comprobado en sus logs con `Failed to initialize microphone
(timeout)` y `Activating microphone: ""`.

Además, ese camino tiene un fallo conceptual: VTS oye lo mismo que suena en los
auriculares, así que cualquier sonido del sistema (música, un vídeo, Discord)
mueve la boca de Niu.

Cómo funciona este módulo
-------------------------
    1. Niu acaba de sintetizar su voz, así que ya tiene la forma de onda.
    2. De esa onda se calcula la envolvente de volumen: un valor 0..1 cada
       1/FPS segundos (~40 por segundo).
    3. Se reproduce el audio y, en paralelo, se envía cada valor a VTS justo
       cuando le toca sonar.
    4. VTS recibe el valor en un parámetro de tracking y el modelo lo convierte
       en `ParamMouthOpenY`.

Qué parámetro se usa
--------------------
Hay dos candidatos, y no se elige por configuración sino midiendo:

- `NiuMouthOpen`: parámetro propio, creado por Niu vía API. Es el bueno, porque
  nada más lo escribe. Requiere que el usuario lo asigne una vez a `Mouth Open`
  en la configuración de parámetros del modelo.
- `VoiceVolumePlusMouthOpen`: el que VTS usa de serie para su propio lip sync,
  ya mapeado a `ParamMouthOpenY` en prácticamente todos los modelos. Funciona
  sin tocar nada, pero VTS también lo escribe desde su micrófono, así que los
  dos pueden competir.

`resolver_parametro()` prueba primero el propio: inyecta 0 y 1 y mira si la
boca del modelo se mueve. Si no se mueve, cae al de VTS. Así funciona hoy sin
configuración y mejora sola en cuanto exista el mapeo.
"""

import asyncio
import ctypes
import sys
import time
from typing import AsyncIterator

import numpy as np

from core import tts
from core.frases import frases_de_async
from core.vts_client import vts_client

# Nombre del parámetro de tracking. VTS exige alfanumérico y 4-32 caracteres.
PARAMETRO_BOCA = "NiuMouthOpen"
EXPLICACION_BOCA = ("Apertura de boca calculada por Niu a partir de su propio "
                    "audio TTS. Mapear a ParamMouthOpenY.")

# Parámetro de serie de VTube Studio, ya mapeado a la boca en casi todos los
# modelos. Se usa como respaldo mientras no exista el mapeo propio.
PARAMETRO_RESPALDO = "VoiceVolumePlusMouthOpen"

# Parámetro Live2D del modelo que se lee para comprobar que la boca se mueve.
PARAMETRO_LIVE2D = "ParamMouthOpenY"

# ─── Ajustes de la envolvente ──────────────────────────────────────────
#
# FPS: cuántos valores por segundo se envían a VTS.
#
# Cada petición tarda ~16,7 ms, porque VTS no contesta al recibir sino en su
# siguiente frame de render (1/60 s). Con 40 Hz el presupuesto por frame es
# 25 ms, así que hay margen. Medido en este equipo: 375/375 frames enviados en
# 9,37 s para un audio de 9,38 s (0,1 % de error).
#
# 25 ms entre cambios de boca es de sobra: el ojo deja de notar el escalonado
# por encima de ~50 ms.
FPS = 40

# Si un envío se atasca y vamos más de esto por detrás, en vez de seguir
# mandando valores viejos (la boca contaría la frase con retraso) se salta al
# frame que corresponde al audio que está sonando ahora.
SALTO_MAXIMO = 2.5 / FPS

# Margen que se resta a cada espera. Incluso con el temporizador en 1 ms,
# `asyncio.sleep` se despierta ~1 ms tarde de media; restar 2 ms hace que el
# envío salga un poco antes en vez de un poco después, y así el pequeño error
# no se acumula a lo largo de la frase.
MARGEN_SLEEP = 0.002

# Ventana de volumen: todo lo que esté por debajo de SUELO_DB se considera
# silencio (boca cerrada) y todo lo que supere TECHO_DB se considera boca
# abierta del todo. Se trabaja en dB y no en amplitud lineal porque el oído
# (y el aspecto de una boca) responden de forma logarítmica: en lineal, una
# frase normal apenas movía la boca.
#
# Estos valores salen de medir una frase real de Edge-TTS (24000 Hz → 48000 Hz)
# frame a frame: mediana −28 dBFS, p95 −15 dBFS, mínimo −240 dBFS en silencio.
# Con −45/−16 solo un 8 % de los frames llega al máximo y un 53 % queda en
# rango medio. Con un techo más bajo (−18) saturaba el 19 % y la boca parecía
# pegada al tope todo el rato.
SUELO_DB = -45.0
TECHO_DB = -16.0

# Suavizado asimétrico: la boca abre rápido y cierra más despacio, como una
# boca real. 1.0 = copia el objetivo al instante (nervioso), 0.0 = no se mueve.
ATAQUE = 0.65
LIBERACION = 0.30

# Retardo entre "lanzo el audio" y "el primer sample sale por el altavoz".
# sounddevice y la cola de DirectSound añaden unos milisegundos. Ajustable si
# al mirarte ves la boca adelantada o atrasada respecto a la voz.
RETARDO_SALIDA = 0.0

# Caché del parámetro elegido para este proceso (None = todavía sin resolver).
_parametro_activo: str | None = None


class _TemporizadorPreciso:
    """Pide a Windows temporizadores de 1 ms mientras dura la animación.

    Por defecto, Windows despierta a los procesos en múltiplos de 15,6 ms. Con
    eso, pedir `asyncio.sleep(0.0166)` tarda en realidad 31,2 ms: el doble.
    Medido en este equipo:

        pedido    real    error
         5,0 ms   15,6    +10,6
        16,6 ms   31,2    +14,6
        23,3 ms   31,2     +7,9

    En un bucle que envía 40 valores por segundo ese error se acumula y la boca
    termina contando la frase con retraso. Con `timeBeginPeriod(1)` el error
    baja a ~1 ms (es la misma llamada que usan juegos y programas de audio).

    Se activa solo durante la animación y se desactiva al terminar, porque
    mantenerla siempre sube el consumo del sistema.
    """

    def __init__(self):
        self._activo = False

    def __enter__(self):
        if sys.platform == "win32":
            self._activo = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        return self

    def __exit__(self, *_):
        if self._activo:
            ctypes.windll.winmm.timeEndPeriod(1)
        return False


def envolvente(
    muestras,
    fs: int,
    fps: int = FPS,
    suelo_db: float = SUELO_DB,
    techo_db: float = TECHO_DB,
    ataque: float = ATAQUE,
    liberacion: float = LIBERACION,
) -> list[float]:
    """Convierte una onda de audio en la curva de apertura de boca.

    Es una función pura: no toca red, ni audio, ni VTS. Entra un array de
    muestras y sale una lista de valores entre 0.0 y 1.0. Se puede probar con
    un tono generado a mano.

    Pasos:

    1. Trocea la señal en ventanas de `1/fps` segundos.
    2. Calcula el RMS de cada ventana (su volumen eficaz).
    3. Pasa el RMS a dBFS y lo normaliza entre `suelo_db` y `techo_db`.
    4. Suaviza con ataque rápido y liberación lenta.

    Args:
        muestras: señal mono, float32 en el rango -1.0 a 1.0.
        fs: frecuencia de muestreo de la señal.
        fps: valores por segundo a generar.

    Returns:
        Lista de flotantes en [0.0, 1.0]. Vacía si el audio es más corto que
        una ventana.
    """
    datos = np.asarray(muestras, dtype=np.float32)
    if datos.ndim > 1:
        datos = datos.mean(axis=1)

    tam = max(1, int(fs / fps))
    n_ventanas = len(datos) // tam
    if n_ventanas == 0:
        return []

    trozos = datos[: n_ventanas * tam].reshape(n_ventanas, tam).astype(np.float64)
    rms = np.sqrt(np.mean(trozos ** 2, axis=1))

    # 1e-12 en vez de 0 para que log10 no explote con el silencio digital.
    db = 20.0 * np.log10(np.maximum(rms, 1e-12))
    objetivo = np.clip((db - suelo_db) / (techo_db - suelo_db), 0.0, 1.0)

    valores: list[float] = []
    actual = 0.0
    for valor in objetivo:
        factor = ataque if valor > actual else liberacion
        actual += (valor - actual) * factor
        valores.append(round(float(actual), 4))
    return valores


# ─── Elección del parámetro ────────────────────────────────────────────


async def leer_apertura() -> float | None:
    """Lee `ParamMouthOpenY` del modelo cargado en VTS.

    Los parámetros Live2D no se pueden consultar con `ParameterValueRequest`,
    pero `Live2DParameterListRequest` devuelve la lista completa con sus
    valores actuales.
    """
    respuesta = await vts_client.peticion("Live2DParameterListRequest")
    if not respuesta or respuesta.get("messageType") != "Live2DParameterListResponse":
        return None
    if not respuesta["data"].get("modelLoaded"):
        return None
    for parametro in respuesta["data"].get("parameters", []):
        if parametro["name"] == PARAMETRO_LIVE2D:
            return float(parametro["value"])
    return None


async def _mueve_la_boca(nombre: str) -> bool:
    """¿El modelo reacciona a `nombre` moviendo la boca?

    No se le pregunta al archivo de configuración: se prueba de verdad. Se
    inyecta 0, se mide; se inyecta 1, se mide. Si la boca no se abre, ese
    parámetro no está mapeado.

    Se espera 120 ms entre inyección y medida para que VTS procese el cambio.
    """
    await vts_client.inyectar_parametro(nombre, 0.0)
    await asyncio.sleep(0.12)
    cerrado = await leer_apertura()

    if not await vts_client.inyectar_parametro(nombre, 1.0):
        return False
    await asyncio.sleep(0.12)
    abierto = await leer_apertura()

    await vts_client.inyectar_parametro(nombre, 0.0)

    if cerrado is None or abierto is None:
        return False
    return (abierto - cerrado) > 0.3


async def resolver_parametro() -> str | None:
    """Decide qué parámetro mueve la boca. Se ejecuta una vez por proceso.

    Returns:
        El nombre del parámetro a inyectar, o None si no hay forma de mover la
        boca (sin VTS, sin modelo, o modelo sin mapeo de boca).
    """
    global _parametro_activo
    if _parametro_activo is not None:
        return _parametro_activo
    if not vts_client.connected:
        return None

    if await leer_apertura() is None:
        print("[LIPSYNC] VTS no tiene ningún modelo cargado")
        return None

    creado = await vts_client.crear_parametro_tracking(
        PARAMETRO_BOCA, EXPLICACION_BOCA, minimo=0.0, maximo=1.0, defecto=0.0)
    if not creado:
        print(f"[WARN] [LIPSYNC] No se pudo crear {PARAMETRO_BOCA}")

    if creado and await _mueve_la_boca(PARAMETRO_BOCA):
        _parametro_activo = PARAMETRO_BOCA
        print(f"[LIPSYNC] Boca controlada por {PARAMETRO_BOCA} (parámetro propio)")
        return _parametro_activo

    if await _mueve_la_boca(PARAMETRO_RESPALDO):
        _parametro_activo = PARAMETRO_RESPALDO
        print(f"[LIPSYNC] {PARAMETRO_BOCA} todavía no está mapeado en el modelo; "
              f"uso {PARAMETRO_RESPALDO}")
        print("[LIPSYNC] Para usar el parámetro propio: en VTube Studio, "
              "configuración de parámetros del modelo")
        print(f"[LIPSYNC]   → entrada 'Mouth Open' → cámbiala a {PARAMETRO_BOCA}")
        return _parametro_activo

    print("[LIPSYNC] El modelo no mueve la boca con ninguno de los dos "
          "parámetros. Revisa el mapeo 'Mouth Open' en VTube Studio.")
    return None


# ─── Animación ─────────────────────────────────────────────────────────


async def animar_boca(boca: list[float], parametro: str | None = None,
                      fps: int = FPS) -> int:
    """Envía la curva de boca a VTS sincronizada con el reloj de reproducción.

    No duerme "25 ms entre envíos": calcula el instante absoluto de cada frame
    (`inicio + i/fps`). Así, si una petición se retrasa, la siguiente no acumula
    el retraso; se recupera sola.

    Returns:
        Número de valores enviados correctamente.
    """
    if not boca:
        return 0

    nombre = parametro or _parametro_activo
    if nombre is None:
        return 0

    inicio = time.perf_counter()
    enviados = 0
    saltados = 0
    atraso_maximo = 0.0

    with _TemporizadorPreciso():
        i = 0
        while i < len(boca):
            objetivo = inicio + i / fps + RETARDO_SALIDA
            espera = objetivo - time.perf_counter()

            if espera > MARGEN_SLEEP:
                await asyncio.sleep(espera - MARGEN_SLEEP)
            elif espera > 0:
                await asyncio.sleep(0)   # ceder el turno sin dormir

            atraso = time.perf_counter() - objetivo
            if atraso > 0:
                atraso_maximo = max(atraso_maximo, atraso)
                if atraso > SALTO_MAXIMO:
                    # Vamos tarde. Seguir enviando boca[i] sería narrar la frase
                    # con retraso; saltamos al frame que corresponde al audio.
                    actual = int((time.perf_counter() - inicio - RETARDO_SALIDA) * fps)
                    if actual > i:
                        saltados += actual - i
                        i = min(actual, len(boca) - 1)

            if await vts_client.inyectar_parametro(nombre, boca[i]):
                enviados += 1
            i += 1

    # Cerrar la boca al terminar; si no, se queda abierta hasta que VTS
    # considere el parámetro "perdido" (1 s sin datos).
    await vts_client.inyectar_parametro(nombre, 0.0)

    if enviados < len(boca) * 0.9:
        print(f"[WARN] [LIPSYNC] Solo se enviaron {enviados}/{len(boca)} frames")
    elif saltados > len(boca) * 0.15:
        print(f"[WARN] [LIPSYNC] {saltados}/{len(boca)} frames saltados por atraso "
              f"({atraso_maximo * 1000:.0f} ms máx)")

    return enviados


async def sintetizar_y_preparar(
    texto: str,
    archivo_audio: str = "core/voz_temp.mp3",
    voz: str = tts.VOZ_NIU,
    medidas: dict[str, float] | None = None,
) -> tts.AudioPreparado | None:
    """Convierte texto en audio listo para sonar (y ya medido, para la boca).

    Son los dos primeros pasos de siempre, separados para poder encadenarlos:
    el streaming sintetiza una parte mientras otra está sonando.

    El audio se deja cargado en memoria, así que el archivo temporal puede
    reutilizarse sin peligro: para cuando se vuelve a escribir en él, su
    contenido ya está copiado en el array.

    Args:
        texto: lo que Niu va a decir.
        archivo_audio: archivo temporal donde guardar el audio.
        voz: voz de Edge-TTS.
        medidas: si se pasa, se anotan `sintesis` y `preparacion`.

    Returns:
        El audio preparado, o None si el texto no tenía nada que decir (por
        ejemplo, un trozo que solo contenía emojis).
    """
    inicio = time.perf_counter()
    if not await tts.sintetizar_voz_async(texto, archivo_audio, voz):
        return None
    if medidas is not None:
        medidas["sintesis"] = time.perf_counter() - inicio

    inicio = time.perf_counter()
    audio = tts.preparar_audio(archivo_audio)
    if medidas is not None and audio is not None:
        medidas["preparacion"] = time.perf_counter() - inicio
    return audio


async def decir(audio: tts.AudioPreparado, etiqueta: str = "") -> int:
    """Reproduce un audio preparado y mueve la boca a la vez.

    Orden de las operaciones, que importa:

    1. Calcular la envolvente **antes** de reproducir: durante la reproducción
       el bucle solo envía números ya calculados, sin gastar CPU en DSP.
    2. Lanzar la reproducción en un hilo aparte.
    3. Inyectar la envolvente en VTS mientras suena.

    Si VTS no está disponible, reproduce igual: el audio nunca depende del
    avatar.

    Args:
        audio: audio ya preparado (ver `sintetizar_y_preparar`).
        etiqueta: texto para distinguir esta parte en los mensajes.

    Returns:
        Número de valores de boca enviados (0 si no había a quién enviarlos).
    """
    boca = envolvente(audio.mono, audio.fs)
    parametro = await resolver_parametro()

    reproduccion = asyncio.create_task(asyncio.to_thread(tts.reproducir_audio, audio))
    enviados = 0

    try:
        if parametro is None:
            print("[LIPSYNC] Sin control de boca: solo audio")
        else:
            inicio_envio = time.perf_counter()
            enviados = await animar_boca(boca, parametro)
            duracion_envio = time.perf_counter() - inicio_envio
            print(f"[LIPSYNC]{etiqueta} Boca animada {enviados}/{len(boca)} frames "
                  f"en {duracion_envio:.2f} s (audio {audio.duracion:.2f} s)")
    except Exception as e:
        print(f"[WARN] [LIPSYNC] {type(e).__name__}: {e}")
    finally:
        # Siempre hay que esperar a que termine el audio. Si la boca se rompió
        # a media frase, o terminó antes, dejar la reproducción en marcha haría
        # que dos partes sonaran encima de la otra.
        await asyncio.gather(reproduccion, return_exceptions=True)

    return enviados


async def hablar_con_lipsync(
    texto: str,
    archivo_audio: str = "core/voz_temp.mp3",
    voz: str = tts.VOZ_NIU,
    medidas: dict[str, float] | None = None,
) -> bool:
    """Dice una frase entera de una vez, sin streaming.

    Es el camino simple: esperar el texto completo, sintetizarlo y hablar. Se
    conserva porque aísla problemas (si con esto se oye y con el streaming no,
    el fallo está en la tubería por partes) y porque es lo que usan las pruebas
    de audio sin avatar.

    Returns:
        True si se generó y reprodujo el audio.
    """
    audio = await sintetizar_y_preparar(texto, archivo_audio, voz, medidas)
    if audio is None:
        return False
    if medidas is not None:
        medidas["voz"] = audio.duracion

    await decir(audio)
    return True


async def hablar_por_partes(
    fragmentos: AsyncIterator[str],
    archivo_audio: str = "core/voz_temp.mp3",
    voz: str = tts.VOZ_NIU,
    medidas: dict[str, float] | None = None,
) -> str:
    """Habla mientras el texto todavía se está escribiendo.

    Antes esto era una fila de tres pasos: esperar el texto completo
    (3,8 s), sintetizarlo entero (0,6 s) y hablar. Ahora son tres etapas que se
    solapan:

        cerebro (streaming) → síntesis → reproducción + boca

    Mientras una parte suena, la siguiente ya se está sintetizando. El tiempo
    hasta la primera palabra deja de depender de la respuesta completa y pasa a
    depender de la primera frase: medido en este equipo, la primera frase está
    lista a los 0,6 s y su audio cuesta otros 0,6 s.

    Las tres etapas corren como tareas separadas y se comunican por colas, así
    que ninguna espera a otra para avanzar:

    - `generar_texto` consume el stream del cerebro y va sacando frases enteras
      (ver `core/frases.py`).
    - `sintetizar` coge frases y las convierte en audio.
    - `reproducir` coge audios y los dice, en orden, moviendo la boca.

    Args:
        fragmentos: lo que produce el cerebro, trozo a trozo.
        archivo_audio: archivo temporal donde guardar cada parte.
        voz: voz de Edge-TTS.
        medidas: si se pasa, se anotan `texto` (espera hasta la primera frase),
            `sintesis` y `preparacion` (de esa primera parte), `voz` (duración
            total de lo dicho), `partes` y `generando` (lo que tardó el cerebro).

    Returns:
        El texto completo que se dijo, para poder revisarlo después (por
        ejemplo, para decidir la expresión del avatar).
    """
    if medidas is None:
        medidas = {}

    inicio = time.perf_counter()
    cola_texto: asyncio.Queue[str | None] = asyncio.Queue()
    cola_audio: asyncio.Queue[tts.AudioPreparado | None] = asyncio.Queue()
    dicho: list[str] = []

    async def generar_texto() -> None:
        try:
            async for frase in frases_de_async(fragmentos):
                dicho.append(frase)
                medidas.setdefault("texto", time.perf_counter() - inicio)
                await cola_texto.put(frase)
        finally:
            medidas["generando"] = time.perf_counter() - inicio
            await cola_texto.put(None)      # fin del texto: cerrar la tubería

    async def sintetizar() -> None:
        primera = True
        try:
            while (frase := await cola_texto.get()) is not None:
                # Solo se mide la primera parte: es la que decide cuánto tarda
                # Niu en decir la primera palabra.
                audio = await sintetizar_y_preparar(
                    frase, archivo_audio, voz, medidas if primera else None
                )
                primera = False
                if audio is None:
                    continue        # trozo sin nada que decir (solo emojis)
                await cola_audio.put(audio)
        finally:
            await cola_audio.put(None)

    async def reproducir() -> None:
        partes = 0
        duracion = 0.0
        while (audio := await cola_audio.get()) is not None:
            partes += 1
            duracion += audio.duracion
            await decir(audio, etiqueta=f" parte {partes}:")
        medidas["partes"] = partes
        medidas["voz"] = duracion

    try:
        await asyncio.gather(generar_texto(), sintetizar(), reproducir())
    except Exception as e:
        print(f"[WARN] [LIPSYNC] Tubería interrumpida: {type(e).__name__}: {e}")

    return " ".join(dicho)
