"""
Módulo del Cerebro de Niu.

Gestiona memoria y personalidad, y delega la generación de texto en cualquier
implementación de LLMProvider. El cerebro no sabe si detrás hay Ollama o Gemini.
"""

from core import config, perfiles
from core.idiomas import Idioma, idioma_activo
from core.llm_provider import LLMConfig, LLMProvider, Messages
from core.ollama_adapter import OllamaAdapter
from core.personalidad import INSTRUCCION_POR_DEFECTO

# Nombre conservado para el código y los tests que ya lo importaban. El texto
# de fábrica vive en `core/personalidad.py`; cada perfil puede sustituirlo.
SISTEMA_INSTRUCCION_NIU = INSTRUCCION_POR_DEFECTO


class NiuBrain:
    """
    Cerebro de Niu: memoria, personalidad y llamada al proveedor LLM.
    """

    def __init__(self, provider: LLMProvider | None = None, ventana: int = 20,
                 idioma: Idioma | None = None):
        """
        Args:
            provider: Implementación de LLMProvider. Por defecto usa Ollama local.
            ventana: Número máximo de mensajes guardados en memoria.
            idioma: Perfil de idioma (ver `core/idiomas.py`). Por defecto, el
                elegido con `NIU_IDIOMA`.
        """
        self.provider = provider or OllamaAdapter(
            model=config.ajustes().modelo_llm,
        )
        self.ventana = ventana
        self.idioma = idioma or idioma_activo()
        self.mi_historial: Messages = []

    def _instruccion(self) -> str:
        """Personalidad del perfil activo + reglas del idioma.

        La personalidad se lee en cada turno, no al construir el cerebro: así
        editarla en el panel surte efecto sin reiniciar el motor. El perfil de
        idioma no la reescribe, le añade el bloque que fija en qué idioma y con
        qué registro expresarla.
        """
        return f"{perfiles.instruccion_activa()}\n{self.idioma.reglas}"

    def _normalizar_entrada(self, mensaje_contenido) -> str:
        """
        Convierte la entrada a texto plano.

        Nota: el soporte de imágenes requiere un modelo multimodal. qwen2.5 no lo
        es, así que de momento solo se usa la parte textual.
        """
        if isinstance(mensaje_contenido, str):
            return mensaje_contenido
        print("[BRAIN] Entrada multimodal: se ignoran las imágenes con este modelo.")
        return str(mensaje_contenido[0])

    def _aplicar_ventana_deslizante(self):
        """Mantiene el historial dentro del límite (ventana deslizante)."""
        while len(self.mi_historial) >= self.ventana:
            self.mi_historial.pop(0)
            print("--- [SISTEMA COGNITIVO]: Niu está optimizando su memoria...")

    async def procesar_mensaje(self, usuario: str, mensaje_contenido) -> str:
        texto = self._normalizar_entrada(mensaje_contenido)

        self._aplicar_ventana_deslizante()
        self.mi_historial.append({"role": "user", "content": f"[{usuario}]: {texto}"})

        try:
            respuesta = await self.provider.generate(
                messages=self.mi_historial,
                system_instruction=self._instruccion(),
                config=LLMConfig(temperature=config.ajustes().temperatura),
            )
            respuesta_texto = respuesta.text.strip()
        except Exception as e:
            print(f"[ERROR] [Cerebro de Niu]: {e}")
            return "Uy... se me cruzaron los cables. ¿Puedes repetirlo?"

        if not respuesta_texto:
            return "Mmm... me quedé en blanco. ¿Otra vez?"

        self.mi_historial.append({"role": "assistant", "content": respuesta_texto})
        return respuesta_texto

    async def procesar_mensaje_streaming(self, usuario: str, mensaje_contenido):
        texto = self._normalizar_entrada(mensaje_contenido)

        self._aplicar_ventana_deslizante()
        self.mi_historial.append({"role": "user", "content": f"[{usuario}]: {texto}"})

        texto_completo = ""
        try:
            async for fragmento in self.provider.generate_stream(
                messages=self.mi_historial,
                system_instruction=self._instruccion(),
                config=LLMConfig(temperature=config.ajustes().temperatura),
            ):
                texto_completo += fragmento
                yield fragmento
        except Exception as e:
            print(f"[ERROR] [Cerebro de Niu]: {e}")
            yield "Uy... se me cruzaron los cables."

        if texto_completo:
            self.mi_historial.append({"role": "assistant", "content": texto_completo})
