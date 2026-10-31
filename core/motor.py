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
    transcripcion     {texto, ms}                     lo que se entendió del usuario
    respuesta_inicio  {texto_usuario}                 empieza un turno de Niu
    fragmento         {texto}                         trozo de respuesta según llega
    parte             {numero, duracion}              cada trozo de audio que suena
    respuesta         {texto}                         respuesta completa del turno
    metricas          {tiempos}                       latencias del turno

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
        archivo_audio: str = "dia_por_dia/voz_temp.mp3",
    ) -> None:
        """
        Args:
            permitir_teclado: si no hay micrófono, leer del teclado. La consola
                lo quiere; el panel no, porque `input()` bloquea un hilo y no
                se puede cancelar cuando el usuario pulsa «Detener».
            archivo_audio: archivo temporal donde Edge-TTS deja cada parte.
        """
        self.permitir_teclado = permitir_teclado
        self.archivo_audio = os.path.abspath(archivo_audio)

        self._estado = APAGADO
        self._oyentes: list[Oyente] = []
        self._tarea: asyncio.Task | None = None
        self._tarea_voz: asyncio.Task | None = None
        self._parando = False
        self._recursos_abiertos = False

        self._brain: NiuBrain | None = None
        self._stt = None
        self._mic: int | None = None
        self._nombre_mic = ""

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

    # ─── Ciclo de vida ─────────────────────────────────────────────────

    async def iniciar(self) -> None:
        """Prepara cerebro, oído y avatar, y deja el bucle corriendo.

        Es idempotente: si ya está en marcha, no hace nada. Si no hay ni
        micrófono ni teclado permitido, deja el motor apagado y emite un
        `error` en vez de arrancar un bucle que no puede oír nada.
        """
        if self.en_marcha:
            return

        self._parando = False
        self._cambiar_estado(INICIANDO)

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

        await self._abrir_oido()

    async def _abrir_oido(self) -> None:
        """Localiza micrófono y STT. Si no hay, decide entre teclado y parar."""
        self._nombre_mic = config.ajustes().microfono
        self._mic = self._buscar_mic(self._nombre_mic)

        if self._mic is None:
            self._emitir("sistema", mensaje=f"No encontré "
                                            f"'{self._nombre_mic}'. Revisa el "
                                            f"nombre en los ajustes.")
            if not self.permitir_teclado:
                self._emitir("error", mensaje="Sin micrófono y sin teclado: "
                                              "no hay forma de escuchar.")
                await self._cerrar_recursos()
                self._cambiar_estado(APAGADO)
                return
            self._emitir("sistema", mensaje="Sin micrófono. Usando teclado.")
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
                if not self.permitir_teclado:
                    self._emitir("error", mensaje="Sin STT y sin teclado: "
                                                  "no hay forma de escuchar.")
                    await self._cerrar_recursos()
                    self._cambiar_estado(APAGADO)
                    return
                self._emitir("sistema", mensaje="Usando teclado.")

        if self._stt is not None and hasattr(self._stt, "preparar"):
            self._emitir("sistema", mensaje="Cargando el modelo de voz "
                                            "(la primera vez tarda)...")
            await asyncio.to_thread(self._stt.preparar)

        self._emitir("sistema", mensaje="🎙️ Niu está lista.")
        self._tarea = asyncio.create_task(self._bucle(), name="niu-bucle")

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
                texto, tiempos = await self._escuchar()
                if texto is None:
                    continue

                limpio = texto.strip()
                if not limpio:
                    continue
                if limpio.lower() in FRASES_SALIDA:
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

    async def _escuchar(self) -> tuple[str | None, dict[str, float]]:
        """Consigue una frase del usuario: micrófono o teclado.

        Returns:
            `(texto, tiempos)`. `texto` es None si no hubo nada que contestar
            (silencio, transcripción vacía); los tiempos llevan lo que costó el
            STT.

        Raises:
            _FinDeConversacion: si se cerró la entrada.
        """
        self._cambiar_estado(ESCUCHANDO)
        tiempos: dict[str, float] = {}

        try:
            if self._mic is None:
                return await asyncio.to_thread(input, "Escribe tu mensaje: "), tiempos

            audio = await asyncio.to_thread(grabar_hasta_silencio, self._mic)
            if audio is None:
                return None, tiempos

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
                return None, tiempos

            self._emitir("transcripcion", texto=texto, ms=ms)
            return texto, tiempos
        except (EOFError, KeyboardInterrupt):
            self._emitir("sistema", mensaje="Entrada finalizada. Saliendo...")
            raise _FinDeConversacion from None

    async def _responder(self, texto: str, tiempos: dict[str, float]) -> None:
        """Dice un turno completo, dejándose cancelar sin romper el bucle."""
        self._cambiar_estado(PENSANDO)
        self._emitir("respuesta_inicio", texto_usuario=texto)

        # La voz va en su propia tarea para poder cancelarla sola desde
        # `detener_voz()` sin tocar el bucle.
        tarea = asyncio.create_task(self._hablar(texto, tiempos), name="niu-voz")
        self._tarea_voz = tarea
        try:
            await tarea
        except asyncio.CancelledError:
            if self._parando:
                raise
            # Cancelación pedida por `detener_voz`: es normal, se sigue.
            self._emitir("sistema", mensaje="Voz detenida.")
            self._cambiar_estado(ESCUCHANDO)
        finally:
            if self._tarea_voz is tarea:
                self._tarea_voz = None

    async def _hablar(self, texto_usuario: str, tiempos: dict[str, float]) -> None:
        """Flujo cerebro en streaming → frases → TTS con lip sync."""
        os.makedirs(os.path.dirname(self.archivo_audio), exist_ok=True)

        def al_hablar(numero: int, duracion: float) -> None:
            # La primera parte es el dato honesto de «ya está sonando».
            if numero == 1:
                self._cambiar_estado(HABLANDO)
            self._emitir("parte", numero=numero, duracion=duracion)

        respuesta = await hablar_por_partes(
            self._fragmentos(texto_usuario),
            self.archivo_audio,
            medidas=tiempos,
            al_hablar=al_hablar,
        )

        if not respuesta.strip():
            self._emitir("error", mensaje="Niu no llegó a decir nada.")
            return

        self._emitir("respuesta", texto=respuesta)
        self._emitir("metricas", tiempos=dict(tiempos))
        await self._expresar(respuesta)

    async def _fragmentos(self, texto_usuario: str) -> AsyncIterator[str]:
        """Deja pasar los trozos del cerebro, avisando de cada uno.

        Avisar aquí y no al final es lo que permite que el panel pinte el texto
        al mismo ritmo que suena.
        """
        assert self._brain is not None
        async for fragmento in self._brain.procesar_mensaje_streaming(
            "Rotceh", texto_usuario
        ):
            self._emitir("fragmento", texto=fragmento)
            yield fragmento

    async def _expresar(self, respuesta: str) -> None:
        """Pide la expresión del avatar según lo que acaba de decir.

        Es cosmético: si VTS no está conectado, se avisa y se sigue. La
        conversación no depende de que el avatar sonría.
        """
        respuesta_lower = respuesta.lower()
        if any(p in respuesta_lower for p in ["feliz", "alegre", "contenta", ":)", ":-)"]):
            expresion = "MouthSmile"
        elif any(p in respuesta_lower for p in ["sorpresa", "sorprendida", "wow", "‼️"]):
            expresion = "MouthOpen"
        elif any(p in respuesta_lower for p in ["triste", "tristeza", "llorar", ":("]):
            expresion = "MouthFrown"
        elif any(p in respuesta_lower for p in ["enojada", "enojo", "enojado", ">:("]):
            expresion = "MouthAngry"
        else:
            return

        try:
            await vts_client.trigger_expression(expresion)
        except Exception as e:
            self._emitir("sistema", mensaje=f"No se pudo cambiar la expresión "
                                            f"({type(e).__name__}).")

    # ─── Puntos que los tests sustituyen ───────────────────────────────

    def _crear_brain(self) -> NiuBrain:
        return NiuBrain()

    def _crear_stt(self):
        return crear_proveedor_stt()

    def _buscar_mic(self, nombre: str) -> int | None:
        return buscar_dispositivo(nombre, salida=False)

    async def _conectar_vts(self) -> None:
        await vts_client.connect_and_auth()

    async def _cerrar_vts(self) -> None:
        await vts_client.close()
