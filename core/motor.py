"""
Motor de Niu: el bucle de conversación como una tarea con estados y eventos.

Por qué existe
--------------
Hasta ahora el bucle vivía dentro de `main.py`, mezclado con `print`. Eso
funciona para una consola, pero un panel necesita lo mismo de otra forma: no
quiere imprimir el texto de Niu, quiere **recibirlo** para pintarlo; no quiere
que el proceso muera con el bucle, quiere poder arrancarlo y pararlo.

Si el panel copiara el bucle, acabarían existiendo dos conversaciones distintas
que se separan con cada cambio. Por eso el bucle se extrae aquí y `main.py`
queda como un cliente de consola que se suscribe a los eventos.

Qué significa «detener» aquí
----------------------------
Hay dos paradas y no son la misma:

- `detener()`: apaga el motor. Cancela el bucle, corta la voz en curso y cierra
  VTube Studio y el proveedor del LLM. Después hay que llamar a `iniciar()`.
- `detener_voz()`: corta solo lo que Niu está diciendo. El motor sigue vivo y
  vuelve a escuchar. Sirve para callarla sin cerrar la sesión.

Cómo se comunica
----------------
`suscribir(oyente)` recibe una función `(tipo, datos)` y devuelve cómo
desuscribirla. Los eventos son:

    estado            {estado}                       apagado | iniciando |
                                                     escuchando | pensando | hablando
    perfil            {nombre, codigo, voz, tono}     qué idioma y voz van a usarse
    sistema           {mensaje}                       aviso para el usuario
    error             {mensaje}                       algo falló
    transcripcion     {texto, ms}                     lo que se entendió del micrófono
    respuesta_inicio  {texto_usuario, turno}          empieza un turno de Niu
    fragmento         {texto, turno}                  trozo de respuesta según llega
    parte             {numero, duracion, turno}       cada trozo de audio que suena
    respuesta         {texto, turno}                  respuesta completa del turno
    respuesta_cancelada {turno}                       el turno se cortó a medias
    metricas          {tiempos, turno}                latencias del turno

`turno` es un número que empieza en 1 y sube con cada turno. Existe para que el
panel pueda emparejar fragmentos, audio y métricas sin adivinar por orden: si
una respuesta se cancela, sus eventos se descartan por número y no se mezclan
con los del turno siguiente.

La transcripción solo se emite para lo que viene del micrófono. El texto que el
panel escribe en el chat ya lo conoce el panel: volver a emitirlo duplicaría el
mensaje del usuario.

También hay entrada de texto (`enviar_texto()`). Sirve para el chat del panel:
si no hay micrófono, o si el usuario prefiere escribir, el motor responde
igual. Esa entrada no usa las palabras de salida («salir», «adiós»): en un chat
son frases normales y cerrar el motor desde ahí sería una sorpresa.

Un oyente que lanza una excepción no puede tumbar la conversación: se avisa y
se sigue. El panel es un consumidor, no un requisito para que Niu hable.

Por qué `iniciar()` espera a estar listo
----------------------------------------
Cargar el modelo del LLM y el de Whisper tarda segundos la primera vez. Si esa
carga ocurriera dentro del bucle, el panel no sabría cuándo está listo y el
usuario hablaría al vacío. `iniciar()` termina cuando Niu ya puede escuchar;
solo entonces arranca la tarea del bucle.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import AsyncIterator, Callable

import numpy as np

from core import config, tts
from core.audio_devices import buscar_dispositivo
from core.brain import NiuBrain
from core.idiomas import idioma_activo, tono_activo, voz_activa
from core.lipsync import hablar_por_partes
from core.stt import (
    FRASES_SALIDA,
    SAMPLE_RATE,
    crear_proveedor_stt,
    grabar_hasta_silencio,
    idioma_stt,
)
from core.vts_client import vts_client

# Estados. Son cadenas y no un enum para que viajen tal cual por un WebSocket
# sin conversión, y para que un `print` de depuración diga algo legible.
APAGADO = "apagado"
INICIANDO = "iniciando"
ESCUCHANDO = "escuchando"
PENSANDO = "pensando"
HABLANDO = "hablando"

# Hotkeys que el motor puede pedir. Son los nombres que el modelo debe tener
# en VTube Studio para que Niu pueda cambiar de expresión.
#
# Son un contrato entre el avatar y el código: si en el modelo el hotkey se
# llama de otra forma, VTS responde con un error y la expresión no cambia. Por
# eso el motor avisa de los que falten en vez de fallar en silencio.
EXPRESIONES_NIU = ("MouthSmile", "MouthOpen", "MouthFrown", "MouthAngry")

Oyente = Callable[[str, dict], None]


class _FinDeConversacion(Exception):
    """Se lanza al cerrar la entrada (EOF o Ctrl+C): fin normal, no error."""


class MotorNiu:
    """Arranca, para y opera la conversación de Niu.

    Los métodos `_crear_*`, `_buscar_mic` y `_conectar_vts` existen para que los
    tests puedan sustituir red, GPU y micrófono por dobles. No son API pública.
    """

    def __init__(
        self,
        *,
        permitir_teclado: bool = True,
        permitir_texto: bool = False,
        archivo_audio: str = "dia_por_dia/voz_temp.mp3",
    ) -> None:
        """
        Args:
            permitir_teclado: si no hay micrófono, leer del teclado. La consola
                lo quiere; el panel no, porque `input()` bloquea un hilo y no
                se puede cancelar cuando el usuario pulsa «Detener».
            permitir_texto: aceptar mensajes escritos con `enviar_texto()`. El
                panel lo activa; la consola ya tiene el teclado.
            archivo_audio: archivo temporal donde Edge-TTS deja cada parte.
        """
        self.permitir_teclado = permitir_teclado
        self.permitir_texto = permitir_texto
        self.archivo_audio = os.path.abspath(archivo_audio)

        self._estado = APAGADO
        self._oyentes: list[Oyente] = []
        self._tarea: asyncio.Task | None = None
        self._tarea_voz: asyncio.Task | None = None
        self._parando = False
        self._recursos_abiertos = False

        self._turno = 0
        # Los mensajes escritos esperan aquí a que el bucle pueda atenderlos.
        # Una cola y no una variable: si llegan dos seguidos, no se pierde
        # ninguno.
        self._cola_texto: asyncio.Queue[str] = asyncio.Queue()
        # Se activa para que una grabación en curso termine ya.
        self._cancelar_mic = threading.Event()

        self._brain: NiuBrain | None = None
        self._stt = None
        self._mic: int | None = None
        self._nombre_mic = ""
        # Hotkeys que ya se han avisado: el aviso se da una vez, no cada turno.
        self._expresiones_avisadas: set[str] = set()

    # ─── Observación ───────────────────────────────────────────────────

    @property
    def estado(self) -> str:
        """Estado actual del motor (`apagado`, `escuchando`, ...)."""
        return self._estado

    @property
    def en_marcha(self) -> bool:
        """True si el bucle está corriendo (aunque esté hablando)."""
        return self._tarea is not None and not self._tarea.done()

    def suscribir(self, oyente: Oyente) -> Callable[[], None]:
        """Añade un oyente de eventos y devuelve cómo quitarlo.

        Se usa una lista y no un `set` porque el orden importa poco pero el
        `set` obligaría a que las funciones fueran *hashable*, y un método de
        una clase que define `__eq__` deja de serlo.
        """
        self._oyentes.append(oyente)

        def desuscribir() -> None:
            with contextlib.suppress(ValueError):
                self._oyentes.remove(oyente)

        return desuscribir

    def _emitir(self, tipo: str, **datos) -> None:
        """Reparte un evento a todos los oyentes, sin dejar que uno tumbe todo."""
        for oyente in list(self._oyentes):
            try:
                oyente(tipo, datos)
            except Exception as e:     # un panel roto no debe callar a Niu
                print(f"[WARN] [MOTOR] Oyente falló con {tipo!r}: "
                      f"{type(e).__name__}: {e}")

    def _cambiar_estado(self, nuevo: str) -> None:
        """Cambia el estado y avisa, solo si de verdad cambió."""
        if nuevo == self._estado:
            return
        self._estado = nuevo
        self._emitir("estado", estado=nuevo)

    # ─── Entrada de texto (chat del panel) ─────────────────────────────

    def enviar_texto(self, texto: str) -> bool:
        """Encola un mensaje escrito y despierta al oído si está grabando.

        Returns:
            True si se aceptó. False si el motor está apagado, el texto está
            vacío o este motor no admite texto.
        """
        limpio = texto.strip()
        if not limpio or not self.permitir_texto or not self.en_marcha:
            return False

        self._cola_texto.put_nowait(limpio)
        # Si el bucle está esperando al micrófono, esta señal corta la
        # grabación: ya hay algo mejor que escuchar.
        self._cancelar_mic.set()
        return True

    def _tomar_texto(self) -> str | None:
        """Saca un mensaje pendiente sin esperar. None si no hay ninguno."""
        try:
            return self._cola_texto.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _vaciar_texto(self) -> None:
        """Tira los mensajes pendientes (al apagar o reiniciar)."""
        while self._tomar_texto() is not None:
            pass

    # ─── Ciclo de vida ─────────────────────────────────────────────────

    async def iniciar(self) -> None:
        """Prepara cerebro, oído y avatar, y deja el bucle corriendo.

        Es idempotente: si ya está en marcha, no hace nada. Si no hay
        micrófono ni ninguna entrada de texto permitida, deja el motor apagado
        y emite un `error` en vez de arrancar un bucle que no puede oír nada.
        """
        if self.en_marcha:
            return

        self._parando = False
        self._cambiar_estado(INICIANDO)
        self._vaciar_texto()

        self._brain = self._crear_brain()
        self._recursos_abiertos = True

        perfil = idioma_activo()
        self._emitir(
            "perfil",
            nombre=perfil.nombre,
            codigo=perfil.codigo,
            voz=voz_activa(),
            tono=tono_activo(),
        )

        preparar = getattr(self._brain.provider, "preparar", None)
        if preparar is not None:
            self._emitir("sistema", mensaje="Cargando el modelo de lenguaje "
                                            "(la primera vez tarda)...")
            await preparar()

        try:
            await self._conectar_vts()
        except Exception as e:
            self._emitir("sistema", mensaje=f"VTS no disponible "
                                            f"({type(e).__name__}: {e}). "
                                            f"Sigo sin avatar.")
        else:
            await self._comprobar_hotkeys()

        await self._abrir_oido()

    async def _comprobar_hotkeys(self) -> None:
        """Avisa de los hotkeys de expresión que el modelo no tiene.

        Los hotkeys son un contrato entre el motor y el avatar: el motor pide
        `MouthSmile`, `MouthOpen`, `MouthFrown` y `MouthAngry` por su nombre.
        Si el modelo se llama de otra forma, VTS devuelve un error y Niu se
        queda con la cara neutra sin decir por qué.

        Comprobarlo al arrancar convierte un fallo invisible en una lista de
        tareas concreta.
        """
        try:
            hotkeys = await self._listar_hotkeys()
        except Exception:
            return
        if not hotkeys:
            return

        nombres = {str(h.get("name", "")).strip().lower() for h in hotkeys}
        faltan = [e for e in EXPRESIONES_NIU if e.lower() not in nombres]
        if faltan:
            self._emitir(
                "sistema",
                mensaje=f"El modelo no tiene los hotkeys de expresión: "
                        f"{', '.join(faltan)}. Un hotkey no es un parámetro: "
                        f"se crea en VTube Studio → pestaña Hotkeys, con "
                        f"esos nombres exactos.",
            )

    async def _abrir_oido(self) -> None:
        """Localiza micrófono y STT. Si no hay, decide entre texto y parar."""
        self._nombre_mic = config.ajustes().microfono
        self._mic = self._buscar_mic(self._nombre_mic)

        if self._mic is None:
            self._emitir("sistema", mensaje=f"No encontré "
                                            f"'{self._nombre_mic}'. Revisa el "
                                            f"nombre en los ajustes.")
            if not self._hay_entrada_de_texto():
                self._emitir("error", mensaje="Sin micrófono ni entrada de "
                                              "texto: no hay forma de hablar.")
                await self._cerrar_recursos()
                self._cambiar_estado(APAGADO)
                return
            self._emitir("sistema", mensaje=self._mensaje_sin_mic())
        else:
            self._emitir("sistema", mensaje=f"Escuchando en {self._nombre_mic}. "
                                            f"Di 'salir' para terminar.")

        self._stt = None
        if self._mic is not None:
            try:
                self._stt = self._crear_stt()
            except Exception as e:
                self._emitir("sistema", mensaje=f"STT no disponible "
                                                f"({type(e).__name__}: {e}).")
                self._mic = None
                if not self._hay_entrada_de_texto():
                    self._emitir("error", mensaje="Sin STT ni entrada de "
                                                  "texto: no hay forma de hablar.")
                    await self._cerrar_recursos()
                    self._cambiar_estado(APAGADO)
                    return
                self._emitir("sistema", mensaje=self._mensaje_sin_mic())

        if self._stt is not None and hasattr(self._stt, "preparar"):
            self._emitir("sistema", mensaje="Cargando el modelo de voz "
                                            "(la primera vez tarda)...")
            await asyncio.to_thread(self._stt.preparar)

        self._emitir("sistema", mensaje="🎙️ Niu está lista.")
        self._tarea = asyncio.create_task(self._bucle(), name="niu-bucle")

    def _hay_entrada_de_texto(self) -> bool:
        """¿Queda alguna forma de recibir texto si el micrófono falla?"""
        return self.permitir_teclado or self.permitir_texto

    def _mensaje_sin_mic(self) -> str:
        """Qué se le dice al usuario cuando el micrófono no está disponible."""
        if self.permitir_texto:
            return "Sin micrófono. Escribe en el chat."
        return "Sin micrófono. Usando teclado."

    async def esperar(self) -> None:
        """Espera a que el bucle termine solo (por «salir» o por error).

        La consola la usa para no salirse: quien cierra es el usuario, no el
        script.
        """
        tarea = self._tarea
        if tarea is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await tarea

    async def detener(self) -> None:
        """Apaga el motor entero: bucle, voz, VTS y proveedor del LLM."""
        self._parando = True
        await self.detener_voz()

        # Si el bucle está grabando, la señal cierra la grabación ya en vez de
        # dejar un hilo esperando hasta 8 s después de apagar.
        self._cancelar_mic.set()
        self._vaciar_texto()

        tarea = self._tarea
        if tarea is not None:
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea
            self._tarea = None

        await self._cerrar_recursos()
        self._cambiar_estado(APAGADO)

    async def detener_voz(self) -> None:
        """Calla a Niu sin apagar el motor; después vuelve a escuchar.

        Hacen falta las dos cosas: cancelar la tarea (para que no siga
        sintetizando frases nuevas) y `sd.stop()` (porque el audio ya está
        sonando en un hilo bloqueado en `sd.wait()`).
        """
        tts.detener_reproduccion()

        tarea = self._tarea_voz
        if tarea is None or tarea.done():
            return
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea

    async def _cerrar_recursos(self) -> None:
        """Cierra VTS y el proveedor una sola vez, aunque se llame dos veces."""
        if not self._recursos_abiertos:
            return
        self._recursos_abiertos = False

        with contextlib.suppress(Exception):
            await self._cerrar_vts()

        if self._brain is not None:
            cerrar = getattr(self._brain.provider, "close", None)
            if cerrar is not None:
                with contextlib.suppress(Exception):
                    await cerrar()

    # ─── El bucle ──────────────────────────────────────────────────────

    async def _bucle(self) -> None:
        """Escucha, responde y repite hasta que el usuario se va."""
        try:
            while True:
                texto, tiempos, origen = await self._escuchar()
                if texto is None:
                    continue

                limpio = texto.strip()
                if not limpio:
                    continue
                # «salir» cierra la consola. En el chat no: ahí es una frase
                # normal y la sesión se cierra con el botón Detener.
                if origen != "texto" and limpio.lower() in FRASES_SALIDA:
                    self._emitir("sistema", mensaje="👋 ¡Hasta luego!")
                    break

                await self._responder(limpio, tiempos)
        except _FinDeConversacion:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._emitir("error", mensaje=f"{type(e).__name__}: {e}")
        finally:
            await self._cerrar_recursos()
            self._cambiar_estado(APAGADO)

    async def _escuchar(self) -> tuple[str | None, dict[str, float], str]:
        """Consigue una frase del usuario: texto del panel, micrófono o teclado.

        Returns:
            `(texto, tiempos, origen)`. `texto` es None si no hubo nada que
            contestar (silencio, transcripción vacía). `origen` es `"texto"`,
            `"voz"` o `"teclado"`: el bucle lo necesita para no confundir un
            «adiós» escrito en el chat con la orden de cerrar la consola.

        Raises:
            _FinDeConversacion: si se cerró la entrada.
        """
        self._cambiar_estado(ESCUCHANDO)
        tiempos: dict[str, float] = {}

        # 1. Lo que ya está escrito manda: no tiene sentido abrir el micro
        #    cuando hay un mensaje esperando respuesta.
        texto = self._tomar_texto()
        if texto is not None:
            return texto, tiempos, "texto"

        try:
            if self._mic is None:
                if self.permitir_teclado:
                    tecleado = await asyncio.to_thread(input, "Escribe tu mensaje: ")
                    return tecleado, tiempos, "teclado"
                # Sin micrófono ni teclado: el panel es la única entrada.
                return await self._cola_texto.get(), tiempos, "texto"

            self._cancelar_mic = threading.Event()
            audio = await asyncio.to_thread(
                grabar_hasta_silencio, self._mic, cancelar=self._cancelar_mic
            )

            # 2. Si el texto llegó mientras grababa, gana el texto: es una
            #    intención explícita y no depende de lo que se colara por el
            #    micrófono (la propia voz de Niu, por ejemplo).
            texto = self._tomar_texto()
            if texto is not None:
                return texto, tiempos, "texto"

            if audio is None:
                return None, tiempos, "voz"

            # grabar_hasta_silencio entrega bytes PCM 16-bit a 16 kHz; el
            # proveedor espera un array de numpy.
            muestras = np.frombuffer(audio, dtype=np.int16)
            inicio = time.perf_counter()
            texto = await self._stt.transcribir(muestras, SAMPLE_RATE, idioma_stt())
            tiempos["stt"] = time.perf_counter() - inicio
            ms = tiempos["stt"] * 1000

            if not texto:
                self._emitir("sistema", mensaje=f"No entendí ({ms:.0f} ms). "
                                                f"Intenta otra vez.")
                return None, tiempos, "voz"

            self._emitir("transcripcion", texto=texto, ms=ms)
            return texto, tiempos, "voz"
        except (EOFError, KeyboardInterrupt):
            self._emitir("sistema", mensaje="Entrada finalizada. Saliendo...")
            raise _FinDeConversacion from None

    async def _responder(self, texto: str, tiempos: dict[str, float]) -> None:
        """Dice un turno completo, dejándose cancelar sin romper el bucle."""
        self._turno += 1
        turno = self._turno
        self._cambiar_estado(PENSANDO)
        self._emitir("respuesta_inicio", texto_usuario=texto, turno=turno)

        # La voz va en su propia tarea para poder cancelarla sola desde
        # `detener_voz()` sin tocar el bucle.
        tarea = asyncio.create_task(
            self._hablar(texto, tiempos, turno), name="niu-voz"
        )
        self._tarea_voz = tarea
        try:
            await tarea
        except asyncio.CancelledError:
            # El turno se cortó: el panel necesita saberlo para cerrar el globo
            # de Niu, tanto si se pulsó «Detener voz» como «Detener».
            self._emitir("respuesta_cancelada", turno=turno)
            if self._parando:
                raise
            # Cancelación pedida por `detener_voz`: es normal, se sigue.
            self._emitir("sistema", mensaje="Voz detenida.")
            self._cambiar_estado(ESCUCHANDO)
        finally:
            if self._tarea_voz is tarea:
                self._tarea_voz = None

    async def _hablar(self, texto_usuario: str, tiempos: dict[str, float],
                      turno: int = 0) -> None:
        """Flujo cerebro en streaming → frases → TTS con lip sync."""
        os.makedirs(os.path.dirname(self.archivo_audio), exist_ok=True)

        def al_hablar(numero: int, duracion: float) -> None:
            # La primera parte es el dato honesto de «ya está sonando».
            if numero == 1:
                self._cambiar_estado(HABLANDO)
            self._emitir("parte", numero=numero, duracion=duracion, turno=turno)

        respuesta = await hablar_por_partes(
            self._fragmentos(texto_usuario, turno),
            self.archivo_audio,
            medidas=tiempos,
            al_hablar=al_hablar,
        )

        if not respuesta.strip():
            self._emitir("error", mensaje="Niu no llegó a decir nada.")
            self._emitir("respuesta_cancelada", turno=turno)
            return

        # Si el servicio de voz falló para todas las frases (Edge-TTS es un
        # servicio en la nube y falla a veces), el turno acaba «mudo»: el texto
        # está pero no suena nada. Sin este aviso, parece que Niu se quedó sin
        # voz para siempre.
        if not tiempos.get("partes"):
            self._emitir("sistema",
                         mensaje="⚠️ Esta respuesta no tiene audio: el servicio "
                                 "de voz falló. El texto está en el chat.")

        self._emitir("respuesta", texto=respuesta, turno=turno)
        self._emitir("metricas", tiempos=dict(tiempos), turno=turno)
        await self._expresar(respuesta)

    async def _fragmentos(self, texto_usuario: str, turno: int = 0) -> AsyncIterator[str]:
        """Deja pasar los trozos del cerebro, avisando de cada uno.

        Avisar aquí y no al final es lo que permite que el panel pinte el texto
        al mismo ritmo que suena.
        """
        assert self._brain is not None
        async for fragmento in self._brain.procesar_mensaje_streaming(
            "Rotceh", texto_usuario
        ):
            self._emitir("fragmento", texto=fragmento, turno=turno)
            yield fragmento

    async def _expresar(self, respuesta: str) -> None:
        """Pide la expresión del avatar según lo que acaba de decir.

        Es cosmético: si VTS no está conectado, se avisa y se sigue. La
        conversación no depende de que el avatar sonría.

        Los hotkeys son un contrato con el modelo: si el avatar no los tiene,
        VTS responde con un error. Aquí se avisa una sola vez por hotkey, para
        que el problema se vea sin llenar el chat de avisos.
        """
        expresion = self._expresion_para(respuesta)
        if expresion is None:
            return

        try:
            ok = await self._disparar_hotkey(expresion)
        except Exception as e:
            self._emitir("sistema", mensaje=f"No se pudo cambiar la expresión "
                                            f"({type(e).__name__}).")
            return

        if not ok and expresion not in self._expresiones_avisadas:
            self._expresiones_avisadas.add(expresion)
            self._emitir(
                "sistema",
                mensaje=f"El modelo no tiene el hotkey «{expresion}». "
                        f"Un hotkey no es un parámetro: se crea en VTube "
                        f"Studio → pestaña Hotkeys, con ese nombre exacto.",
            )

    def _expresion_para(self, respuesta: str) -> str | None:
        """Elige el hotkey de expresión según el tono de lo que dice Niu.

        El orden importa: el emoticon de enfado `>:(` contiene al de tristeza
        `:(` como subcadena. Si se comprobara la tristeza primero, el enfado
        nunca llegaría a su rama.

        Returns:
            El nombre del hotkey, o None si la respuesta no sugiere ninguna
            expresión.
        """
        respuesta_lower = respuesta.lower()
        if any(p in respuesta_lower for p in ["feliz", "alegre", "contenta", ":)", ":-)"]):
            return "MouthSmile"
        if any(p in respuesta_lower for p in ["sorpresa", "sorprendida", "wow", "‼️"]):
            return "MouthOpen"
        if any(p in respuesta_lower for p in ["enojada", "enojo", "enojado", ">:("]):
            return "MouthAngry"
        if any(p in respuesta_lower for p in ["triste", "tristeza", "llorar", ":("]):
            return "MouthFrown"
        return None

    # ─── Puntos que los tests sustituyen ───────────────────────────────

    def _crear_brain(self) -> NiuBrain:
        return NiuBrain()

    def _crear_stt(self):
        return crear_proveedor_stt()

    def _buscar_mic(self, nombre: str) -> int | None:
        return buscar_dispositivo(nombre, salida=False)

    async def _listar_hotkeys(self) -> list[dict]:
        """Hotkeys del modelo cargado. Los tests sustituyen este punto."""
        return await vts_client.listar_hotkeys()

    async def _disparar_hotkey(self, nombre: str) -> bool:
        """Dispara un hotkey. Los tests sustituyen este punto."""
        return await vts_client.trigger_expression(nombre)

    async def _conectar_vts(self) -> None:
        await vts_client.connect_and_auth()

    async def _cerrar_vts(self) -> None:
        await vts_client.close()
