"""
STT en la nube con Gemini.

¿Por qué este adaptador existe? Porque Gemini es un modelo multimodal muy
grande y transcribe audio que los modelos pequeños rechazan: voz con aire,
susurros, ruido de fondo, micrófonos de portátil. Es lo que permitió
comprobar que la voz de Héctor SÍ es inteligible cuando Whisper no la
entendía.

Coste: requiere internet, envía la voz a Google y el plan gratuito de
`gemini-3.5-transcribe` tiene un límite de 3 peticiones por minuto.

Variables de entorno:
    GOOGLE_API_KEY            (obligatoria)
    NIU_GEMINI_STT_MODELO     gemini-3.5-transcribe (por defecto)
    NIU_GEMINI_STT_RESPALDO   modelo al que reintentar si hay 429 / 404
"""

import asyncio
import io
import os

import numpy as np
import soundfile as sf

from core.stt_provider import pcm_a_float, remuestrear

FS_ENVIO = 16000   # suficiente para voz y mantiene la petición pequeña


class GeminiSTT:
    """Adaptador de Gemini que cumple el contrato STTProvider."""

    nombre = "gemini"

    def __init__(self, modelo: str | None = None, api_key: str | None = None) -> None:
        self.modelo = modelo or os.getenv("NIU_GEMINI_STT_MODELO", "gemini-3.5-transcribe")
        self.respaldo = os.getenv("NIU_GEMINI_STT_RESPALDO", "gemini-3.7-flash")
        clave = api_key or os.getenv("GOOGLE_API_KEY")
        if not clave:
            raise ValueError(
                "Falta GOOGLE_API_KEY en el .env (necesaria para NIU_STT=gemini)."
            )

        from google import genai

        self._cliente = genai.Client(api_key=clave)

    # ------------------------------------------------------------------
    def preparar(self) -> None:
        """No hay nada que precargar: el cliente ya se creó en el constructor."""
        return None

    # ------------------------------------------------------------------
    def _a_wav(self, audio: np.ndarray, fs: int) -> bytes:
        """Convierte PCM int16 a un WAV en memoria (Gemini lo acepta tal cual)."""
        x = audio if audio.dtype == np.int16 else pcm_a_float(audio)
        if fs != FS_ENVIO:
            x = remuestrear(x, fs, FS_ENVIO)
        buffer = io.BytesIO()
        sf.write(buffer, x, FS_ENVIO, format="WAV", subtype="PCM_16")
        return buffer.getvalue()

    def _texto_de_respuesta(self, respuesta) -> str | None:
        """
        El modelo de transcripción no devuelve el texto en `.text`: lo pone en
        `part.audio_transcription.text`. Se contemplan las dos formas.
        """
        for candidato in respuesta.candidates or []:
            if candidato.content is None:
                continue
            for parte in candidato.content.parts or []:
                if getattr(parte, "audio_transcription", None):
                    texto = parte.audio_transcription.text
                    if texto:
                        return texto.strip()
                if getattr(parte, "text", None):
                    return parte.text.strip()
        return None

    def _llamar(self, modelo: str, wav: bytes, indicacion: str) -> str | None:
        from google.genai import types

        respuesta = self._cliente.models.generate_content(
            model=modelo,
            contents=[
                types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                indicacion,
            ],
        )
        return self._texto_de_respuesta(respuesta)

    def _transcribir_sync(
        self, audio: np.ndarray, fs: int, idioma: str | None
    ) -> str | None:
        if len(audio) == 0:
            return None
        wav = self._a_wav(audio, fs)
        # El contexto ayuda por el mismo motivo que el initial_prompt de
        # Whisper: "Niu" es un nombre que el modelo no espera y lo sustituye
        # por "New", "ni" o "un".
        contexto = (
            " Es una conversación con Niu, una asistente virtual: el usuario "
            "la llama por su nombre, «Niu»."
        )
        if idioma:
            indicacion = (
                f"Transcribe exactamente lo que se dice, en {idioma}.{contexto} "
                "No inventes ni completes frases. Si no hay voz, responde vacío."
            )
        else:
            indicacion = (
                "Transcribe exactamente lo que se dice, en el idioma original."
                f"{contexto} No inventes ni completes frases. "
                "Si no hay voz, responde vacío."
            )

        try:
            return self._llamar(self.modelo, wav, indicacion)
        except Exception as e:
            # 429 = límite por minuto del plan gratuito; 404 = modelo retirado.
            mensaje = str(e)
            if "429" in mensaje or "RESOURCE_EXHAUSTED" in mensaje or "404" in mensaje:
                print(f"[STT] {self.modelo} no disponible; reintento con {self.respaldo}")
                try:
                    return self._llamar(self.respaldo, wav, indicacion)
                except Exception as e2:
                    print(f"[STT] Gemini falló también con respaldo: {type(e2).__name__}")
                    return None
            print(f"[STT] Error de Gemini: {type(e).__name__}: {mensaje[:160]}")
            return None

    async def transcribir(
        self, audio: np.ndarray, fs: int, idioma: str | None = None
    ) -> str | None:
        return await asyncio.to_thread(self._transcribir_sync, audio, fs, idioma)
