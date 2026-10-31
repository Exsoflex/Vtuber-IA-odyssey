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

El perfil también decide qué **escucha** Niu, no solo qué dice
--------------------------------------------------------------
El idioma no vive en un solo sitio. Si el perfil solo eligiera la voz y las
reglas del modelo, quedaría el otro extremo de la tubería: el reconocimiento de
voz. Whisper, sin que nadie le diga nada, decide por su cuenta en qué idioma
está oyendo. Con una frase corta y un `initial_prompt` en español, tiende a
"oír" español aunque le estés hablando en inglés: transcribe «¿could usted
decir algo en inglés?» y a partir de ahí todo va mal, porque Niu responde a una
transcripción que no es lo que se dijo.

Por eso cada perfil lleva también `prompt_stt`: el texto que sesga el
decodificador hacia ese idioma y hacia el vocabulario de la casa («Niu»).
Hablar y oír tienen que apuntar al mismo idioma.

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
        tono: tono de Edge-TTS en hercios (`+0Hz`, `-15Hz`). Bajar el tono
            oscurece la voz; subirlo la vuelve más infantil.
        nombre: cómo se llama el idioma al hablarle al modelo ("inglés").
        reglas: bloque de prompt que fija el idioma y el registro.
        prompt_stt: contexto para el reconocedor de voz. Sesga el idioma y el
            vocabulario (nombre «Niu») hacia este perfil.
    """

    codigo: str
    voz: str
    tono: str
    nombre: str
    reglas: str
    prompt_stt: str


ESPANOL = Idioma(
    codigo="es",
    # Voz natural de Edge-TTS en español. Dalia es mexicana y conversacional.
    voz="es-MX-DaliaNeural",
    tono="+0Hz",
    nombre="español",
    reglas="""
## IDIOMA (REGLA DE ORO)
* Responde SIEMPRE en español natural, aunque Rotceh te hable en otro idioma.
* Muletillas: "bueno...", "o sea...", "este...", "es que...".
* Mantén los emojis con la misma frecuencia que en tus respuestas normales.
* Límites: lenguaje limpio, sin groserías.
""",
    # Este texto no se transcribe: es una pista. Whisper elige las palabras por
    # contexto y, sin él, "Niu" (nombre que no existe en español) se convierte
    # en "New", "ni" o "un".
    prompt_stt=(
        "Conversación hablada en español con Niu, una asistente virtual. "
        "El usuario se dirige a ella por su nombre: Niu. "
        "Frases habituales: hola Niu, ¿cómo estás?, ¿qué hora es?, "
        "¿qué día es hoy?, ¿me escuchas?, pon música, abre el navegador."
    ),
)

INGLES = Idioma(
    codigo="en",
    # Aria: "Positive, Confident". Elegida por Héctor de oído entre Emma, Ava,
    # Ana y cuatro variantes de tono. Se queda en el tono normal: bajarle los
    # hercios no aportaba y Ava, la alternativa cálida, resultaba demasiado
    # madura para el personaje.
    voz="en-US-AriaNeural",
    tono="+0Hz",
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
    # En inglés el prompt es lo que más pesa: sin él, el decoder parte del
    # idioma que más ha visto (español) y transcribe sonidos ingleses con
    # ortografía española. Con él, espera inglés y además reconoce «Niu».
    prompt_stt=(
        "Spoken conversation in English with Niu, a virtual assistant. "
        "The user calls her by name: Niu. "
        "Common phrases: hi Niu, how are you?, what time is it?, "
        "what day is it today?, can you hear me?, play music, open the browser."
    ),
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
