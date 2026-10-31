"""
Perfiles de idioma: en qué idioma habla Niu y con qué voz.

Por qué esto NO es un `Protocol` como `LLMProvider`
---------------------------------------------------
`LLMProvider` es una interfaz porque Ollama y Gemini **hacen cosas distintas**:
uno habla HTTP con JSON, el otro usa un SDK con autenticación propia, y sus
streams ni siquiera tienen la misma forma. Ahí hay comportamiento que varía, y
una interfaz es lo que permite que el cerebro no se entere.

Un idioma no cambia el comportamiento: es **el mismo código con otros datos**.
La voz es un string, el idioma es un string y las reglas de estilo son texto.
Convertirlo en clases (`EspanolProvider`, `InglesProvider`) daría dos clases que
solo devuelven valores distintos: abstracción de mentira, con más sitios donde
equivocarse.

Así que esto es una **tabla**: un `dataclass` congelado por idioma. Añadir
francés es añadir una entrada, no una clase ni tocar el cerebro.

Qué cambia de un idioma a otro, y por qué no basta con traducir
--------------------------------------------------------------
El perfil no lleva solo la voz. Lleva también las **reglas de estilo**, porque
el prompt de personalidad está escrito en español y con muletillas españolas
("bueno...", "o sea...", "este..."). Si solo se le pidiera "responde en
inglés", el modelo traduciría esas muletillas y Niu sonaría a española hablando
inglés: *"well... I mean... this..."*. Eso no es una persona hablando inglés,
es una traducción.

Por eso cada perfil trae sus propias muletillas y una regla explícita de no
traducir literalmente.

Uso
---
Se elige con una variable de entorno, sin tocar código:

    $env:NIU_IDIOMA = "en"

Y la voz concreta se puede forzar aparte, por si quieres probar otra:

    $env:NIU_VOZ = "en-US-AvaNeural"
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Idioma:
    """Todo lo que cambia de un idioma a otro.

    Attributes:
        codigo: código ISO para los motores de voz (`es`, `en`).
        voz: nombre exacto de la voz de Edge-TTS. Tiene que ser de ese idioma:
            una voz española leyendo inglés suena a español leyendo inglés.
        nombre: cómo se llama el idioma al hablarle al modelo ("inglés").
        reglas: bloque de prompt que fija el idioma y el registro.
    """

    codigo: str
    voz: str
    nombre: str
    reglas: str


ESPANOL = Idioma(
    codigo="es",
    # Voz natural de Edge-TTS en español. Dalia es mexicana y conversacional.
    voz="es-MX-DaliaNeural",
    nombre="español",
    reglas="""
## IDIOMA (REGLA DE ORO)
* Responde SIEMPRE en español natural, aunque Rotceh te hable en otro idioma.
* Muletillas: "bueno...", "o sea...", "este...", "es que...".
* Mantén los emojis con la misma frecuencia que en tus respuestas normales.
* Límites: lenguaje limpio, sin groserías.
""",
)

INGLES = Idioma(
    codigo="en",
    # Emma: "Cheerful, Clear, Conversational". Es la que mejor encaja con el
    # registro de Niu entre las voces inglesas de Edge-TTS. Cambiable con
    # NIU_VOZ; las alternativas están en muestras_voces/.
    voz="en-US-EmmaNeural",
    nombre="inglés",
    reglas="""
## LANGUAGE (GOLDEN RULE)
* ALWAYS answer in English, even if Rotceh speaks to you in Spanish or any
  other language.
* Your character description above is written in Spanish. Do NOT change who
  you are: express the same personality in English.
* Sound like a native American VTuber, not like a translation. Use contractions
  ("I'm", "we're", "gonna", "kinda", "what's") and short sentences.
* Natural English fillers: "like...", "honestly...", "you know...", "I mean...",
  "okay so...", "wait...".
* NEVER translate Spanish fillers literally. Do not say "well... I mean...
  this..." or "it's that...". If you catch yourself translating, rephrase the
  whole sentence as an English speaker would say it.
* If you don't know a word, stay in English: say "I don't know the word, but..."
  instead of switching languages.
* Keep using emojis (✨, 🚀, 💻, 💖, 💫, ‼️, 💕) as often as you normally do.
* Limits: clean language, no profanity.
""",
)

IDIOMAS: dict[str, Idioma] = {
    "es": ESPANOL,
    "en": INGLES,
}


def elegir_idioma(codigo: str | None = None) -> Idioma:
    """Devuelve el perfil de `codigo`, o español si no existe.

    Es una función aparte de la constante para poder probarla: cambiar
    `NIU_IDIOMA` y reimportar el módulo en un test es frágil, mientras que
    llamar a esta función con "en" o con "fr" es trivial.

    Un código desconocido cae en español en vez de romper el arranque: un
    error de tecleo en una variable de entorno no debe dejar a Niu muda.
    """
    return IDIOMAS.get((codigo or CODIGO_IDIOMA).strip().lower(), ESPANOL)


# Idioma activo. `es` mantiene el comportamiento que ya conoces; para contenido
# en inglés, NIU_IDIOMA=en.
CODIGO_IDIOMA = os.getenv("NIU_IDIOMA", "es").strip().lower()
IDIOMA = elegir_idioma(CODIGO_IDIOMA)

# Voz efectiva: la del perfil, salvo que se fuerce con NIU_VOZ.
VOZ = os.getenv("NIU_VOZ", "").strip() or IDIOMA.voz
