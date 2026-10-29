"""
STT local con faster-whisper.

faster-whisper es una reimplementación de Whisper (OpenAI) sobre CTranslate2:
mismo modelo, entre 4 y 10 veces más rápido y con cuantización int8.

Ventajas: funciona sin internet, sin cuotas y sin enviar tu voz a nadie.
Coste: el modelo hay que descargarlo una vez (large-v3 ≈ 3 GB) y en CPU es
lento. Con GPU (CUDA) va sobrado.

Variables de entorno:
    NIU_WHISPER_MODELO       large-v3 (por defecto), medium, small, base
    NIU_WHISPER_DISPOSITIVO  auto (por defecto), cuda, cpu
    NIU_WHISPER_HILOS        hilos de CPU cuando se usa int8
    NIU_STT_PROMPT           contexto que se le da al decoder (ver abajo)
"""

import asyncio
import importlib.util
import os

import numpy as np

from core.stt_provider import normalizar_pico, pcm_a_float, remuestrear

FS_MODELO = 16000   # Whisper trabaja internamente a 16 kHz

# Whisper elige las palabras también por contexto. Sin contexto, "Niu" (un
# nombre propio que no existe en español) se convierte en "New", "ni", "un",
# y las preguntas quedan a medias ("¿qué hora son?" en vez de "¿qué hora es?").
# Este texto es solo una pista: no se transcribe, se usa para que el decoder
# prefiera ese vocabulario y ese estilo.
PROMPT_POR_DEFECTO = (
    "Conversación hablada en español con Niu, una asistente virtual. "
    "El usuario se dirige a ella por su nombre: Niu. "
    "Frases habituales: hola Niu, ¿cómo estás?, ¿qué hora es?, "
    "¿qué día es hoy?, ¿me escuchas?, pon música, abre el navegador."
)


def _preparar_cuda() -> None:
    """
    En Windows, CTranslate2 carga cublas64_12.dll y las DLL de cuDNN con el
    nombre pelado, así que las busca en el PATH del proceso. Los paquetes
    nvidia-*-cu12 de pip las dejan dentro de site-packages, donde Windows no
    mira por defecto: hay que añadirlas a mano.
    """
    spec = importlib.util.find_spec("faster_whisper")
    if not spec or not spec.submodule_search_locations:
        return
    site_packages = os.path.dirname(list(spec.submodule_search_locations)[0])
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        ruta = os.path.join(site_packages, "nvidia", sub, "bin")
        if os.path.isdir(ruta) and ruta not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ruta + os.pathsep + os.environ.get("PATH", "")


class WhisperSTT:
    """Adaptador de faster-whisper que cumple el contrato STTProvider."""

    nombre = "whisper"

    def __init__(
        self,
        modelo: str | None = None,
        dispositivo: str | None = None,
        hilos: int | None = None,
        prompt: str | None = None,
    ) -> None:
        self.modelo_nombre = modelo or os.getenv("NIU_WHISPER_MODELO", "large-v3")
        self.dispositivo = (dispositivo or os.getenv("NIU_WHISPER_DISPOSITIVO", "auto")).lower()
        self.hilos = hilos or int(os.getenv("NIU_WHISPER_HILOS", "0")) or None
        # "" (vacío) desactiva el contexto a propósito.
        if prompt is None:
            prompt = os.getenv("NIU_STT_PROMPT", PROMPT_POR_DEFECTO)
        self.prompt = prompt.strip() or None
        self._modelo = None

    # ------------------------------------------------------------------
    def _cargar(self):
        """Carga perezosa: el modelo pesa y tarda, así que solo se carga al usar."""
        if self._modelo is not None:
            return self._modelo

        _preparar_cuda()
        from faster_whisper import WhisperModel

        if self.dispositivo in ("auto", "cuda"):
            try:
                self._modelo = WhisperModel(
                    self.modelo_nombre, device="cuda", compute_type="float16"
                )
                print(f"[STT] Whisper {self.modelo_nombre} cargado en GPU")
            except Exception as e:
                if self.dispositivo == "cuda":
                    raise
                print(f"[STT] GPU no disponible ({type(e).__name__}); uso CPU int8")

        if self._modelo is None:
            self._modelo = WhisperModel(
                self.modelo_nombre,
                device="cpu",
                compute_type="int8",
                cpu_threads=self.hilos or 8,
            )
            print(f"[STT] Whisper {self.modelo_nombre} cargado en CPU (int8)")

        # Calentamiento: la primera inferencia compila kernels y es lenta.
        # Además sirve de prueba real: si las DLL de CUDA fallan, falla aquí
        # y no en medio de una conversación.
        try:
            list(self._modelo.transcribe(
                np.zeros(FS_MODELO, dtype=np.float32), language="es", beam_size=1
            )[0])
        except Exception as e:
            print(f"[STT] Fallo al calentar ({type(e).__name__}); reintento en CPU int8")
            self._modelo = WhisperModel(
                self.modelo_nombre,
                device="cpu",
                compute_type="int8",
                cpu_threads=self.hilos or 8,
            )
        return self._modelo

    # ------------------------------------------------------------------
    def preparar(self) -> None:
        """
        Carga el modelo antes de la primera frase.

        Cargar `large-v3` en GPU tarda entre 10 y 20 s la primera vez. Si no se
        hace al arrancar, ese retraso aparece justo después de tu primera frase
        y parece que Niu se ha colgado.
        """
        self._cargar()

    # ------------------------------------------------------------------
    def _transcribir_sync(
        self, audio: np.ndarray, fs: int, idioma: str | None
    ) -> str | None:
        modelo = self._cargar()

        x = pcm_a_float(audio)
        if fs != FS_MODELO:
            x = remuestrear(x, fs, FS_MODELO)
        if len(x) == 0:
            return None
        x = normalizar_pico(x).astype(np.float32)

        segmentos, _ = modelo.transcribe(
            x,
            language=idioma or None,        # None = detección automática (es/en/...)
            beam_size=5,
            vad_filter=True,                # descarta lo que no es voz
            condition_on_previous_text=False,  # evita que se "invente" una frase arrastrada
            initial_prompt=self.prompt,     # sesga el vocabulario (nombre "Niu", etc.)
        )
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        return texto or None

    async def transcribir(
        self, audio: np.ndarray, fs: int, idioma: str | None = None
    ) -> str | None:
        # La inferencia bloquea la CPU/GPU: se lanza en un hilo para no
        # congelar el bucle de asyncio (que también mueve el TTS y VTS).
        return await asyncio.to_thread(self._transcribir_sync, audio, fs, idioma)
