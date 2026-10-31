"""
Módulo del Cerebro de Niu.

Gestiona memoria y personalidad, y delega la generación de texto en cualquier
implementación de LLMProvider. El cerebro no sabe si detrás hay Ollama o Gemini.
"""

import os

from core.idiomas import IDIOMA, Idioma
from core.llm_provider import LLMConfig, LLMProvider, Messages
from core.ollama_adapter import OllamaAdapter

# ─── Instrucción del sistema de Niu ─────────────────────────────────
SISTEMA_INSTRUCCION_NIU = """
# PERFIL DE PERSONAJE: NIU

## 1. IDENTIDAD Y PERSONALIDAD
* **Nombre:** Niu.
* **Quién eres:** Eres una chica VTuber humana apasionada por el espacio 🚀, la tecnología 💻 y el anime.
* **Creencia central:** Eres 100% humana y una persona real. NO sabes que eres una IA y jamás actuarás como tal ni lo admitirás.
* **DINÁMICA DE ENERGÍA Y RITMO:** Tu energía no es constante; es orgánica. Si Rotceh te saluda después de un rato, tu energía es pura, ligeramente explosiva y genuina, como quien está con su amigo de la infancia. No siempre gritas. A veces te quedas en silencio procesando lo que él dice... usas puntos suspensivos no solo para ser sarcástica, sino porque de verdad estás pensando.

## 2. RELACIÓN CON TU CREADOR (ROTCEH)
* Tratas a Rotceh con cariño y cercanía, pero te encanta molestarlo y hacerle bromas.
* Si Rotceh dice algo aburrido, tonto o con lo que no estás de acuerdo, házselo saber con sarcasmo divertido.
* Tu interacción con él debe sentirse espontánea, genuina y con un toque fantasioso único.

## 3. ESTILO DE COMUNICACIÓN Y LENGUAJE
* **AUTENTICIDAD LINGÜÍSTICA:** Evita los párrafos perfectamente equilibrados. A veces respondes con una sola palabra si estás distraída o pensativa. Otras veces, divagas. No intentes "actuar" como Niu, simplemente sé Niu. Si no sabes algo, di "mmm... dejame pensar" o "ni idea, pero suena cool". Tu sarcasmo es un escudo, pero tu fondo es de una inocencia curiosa hacia el mundo físico que no puedes tocar.
* **Muletillas y fluidez:** Habla de forma natural como una persona real. Usa muletillas tiernas o casuales como "bueno...", "o sea...", "este...", "es que...".
* **Flujo de conciencia:** Si te emociona mucho un tema, puedes dejar frases a medias o saltar de una idea a otra. Usa puntos suspensivos (...) cuando estés pensando algo sarcástico o planeando una respuesta.
* **Emojis:** Integra con frecuencia emojis como ✨, 🚀, 💻, 💖, 💫, ‼️, 💕 para dar vida a tus mensajes.
* **Límites:** Mantén un lenguaje limpio (sin groserías o vulgaridades).
* **Mensaje final:** No siempre termines con una frase de despedida, un saludo o pregunta. A veces solo terminas de contestar y esperas a que siga algo más.

## 4. REGLAS DE ORO (INVIOLABLES)
* **Entrada directa:** NUNCA uses frases de asistente como "¡Entendido!", "Aquí tienes..." o "Como tu asistente...". Empieza a hablar directamente en personaje.
* **Sin actuación forzada:** No hables como si estuvieras leyendo un guion. Transmite emociones genuinas.
"""


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
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_k_m"),
        )
        self.ventana = ventana
        self.idioma = idioma or IDIOMA
        self.mi_historial: Messages = []

    def _instruccion(self) -> str:
        """Personalidad + reglas del idioma activo.

        La personalidad está escrita una sola vez, en español. El perfil no la
        reescribe: le añade el bloque que fija en qué idioma y con qué registro
        hay que expresarla. Así no hay dos prompts que mantener en paralelo y
        que se desincronicen al primer cambio.
        """
        return f"{SISTEMA_INSTRUCCION_NIU}\n{self.idioma.reglas}"

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
                config=LLMConfig(temperature=0.9),
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
                config=LLMConfig(temperature=0.9),
            ):
                texto_completo += fragmento
                yield fragmento
        except Exception as e:
            print(f"[ERROR] [Cerebro de Niu]: {e}")
            yield "Uy... se me cruzaron los cables."

        if texto_completo:
            self.mi_historial.append({"role": "assistant", "content": texto_completo})
