"""
Corta un texto que está llegando a trozos en frases que ya se pueden decir.

Por qué existe
--------------
Con el cerebro en streaming, el texto llega palabra a palabra. Para hablar sin
esperar a que termine, hace falta decidir en qué momento lo que hay en el buffer
es "una frase entera".

El problema no es trivial: el corte no se puede hacer mirando solo el final del
buffer, porque un fragmento puede terminar justo en mitad de un signo. Ejemplos
reales que llegan partidos:

    "3." + "5 grados"        -> no es una frase, es un número decimal
    "Hola" + "." + " ¿qué tal?"  -> el punto solo cierra frase si le sigue un espacio

Por eso la regla es: **corta cuando el signo final va seguido de un espacio**.
Mientras no haya espacio después, el signo podría seguir creciendo ("..." son
tres puntos que llegan uno a uno) o formar parte de algo más largo.

De paso, esa regla resuelve los dos casos que más rompen estos cortes:

- Emojis: nunca son signos de puntuación, así que no se parten por la mitad.
  Un emoji compuesto (familia, bandera) son varios puntos de código unidos por
  caracteres invisibles; como el corte cae siempre en un espacio, la secuencia
  llega intacta a Edge-TTS.
- Decimales y direcciones web: "3.5" o "niu.dev" no se cortan, porque el punto
  va seguido de una letra y no de un espacio.

Limitación conocida: una abreviatura con punto y espacio ("Sr. García") sí se
corta. En el habla de este personaje no aparece, y en el peor caso el TTS dice
las dos partes seguidas, con una pausa de más.

Si el texto se alarga sin ningún signo (alguien hablando sin parar), se corta
por la última coma dentro del límite. Eso evita que una frase interminable
retrase el primer sonido hasta el final.
"""

from typing import AsyncIterator, Iterator

# Signos que cierran frase. Los guiones de diálogo y las comillas no cuentan.
#
# OJO: los puntos suspensivos NO están aquí a propósito. En el habla de Niu
# aparecen constantemente a mitad de frase ("bueno... o sea... este..."). Si
# cerraran frase, cada duda se convertiría en un trozo de audio con su propia
# petición a Edge-TTS y su propia pausa: el habla sonaría troceada justo donde
# debería sonar natural.
SIGNOS_FINALES = ".!?"

# Pausas dentro de una frase. Sirven de último recurso cuando el texto es largo
# y no ha aparecido ningún signo final.
PAUSAS_DEBILES = ",;:—"

# Cuántos caracteres puede tener un trozo como máximo antes de cortarlo por las
# malas. 140 caracteres son unos 6-7 segundos de voz: si el cerebro tarda en
# llegar al primer punto, no queremos esperar medio minuto.
MAXIMO_POR_TROZO = 140


def _es_puntos_suspensivos(texto: str, i: int) -> bool:
    """¿El carácter en `i` forma parte de unos puntos suspensivos?

    Cubre las dos formas: el carácter único "…" y la secuencia de puntos "...",
    que llega de una en una por el streaming.
    """
    if texto[i] == "…":
        return True
    return texto[i] == "." and i > 0 and texto[i - 1] in ".…"


def _punto_de_corte(texto: str) -> int | None:
    """Índice donde termina la primera frase cerrada de `texto`, o None.

    El índice apunta al signo incluido, de modo que `texto[:corte]` es la frase.
    """
    for i, caracter in enumerate(texto):
        if caracter not in SIGNOS_FINALES:
            continue
        if _es_puntos_suspensivos(texto, i):
            continue
        siguiente = texto[i + 1] if i + 1 < len(texto) else None
        if siguiente is not None and siguiente.isspace():
            return i + 1
    return None


def _punto_de_corte_largo(texto: str, maximo: int) -> int | None:
    """Corta un texto sin puntuación por la mejor pausa antes de `maximo`."""
    ventana = texto[:maximo]

    posiciones = [ventana.rfind(pausa) for pausa in PAUSAS_DEBILES]
    corte = max(posiciones) if posiciones else -1

    # Una coma en la posición 5 daría un trozo de 6 caracteres: peor que
    # esperar. Si la única pausa está muy al principio, se prefiere un espacio.
    if corte < maximo * 0.4:
        corte = ventana.rfind(" ")

    if corte <= 0:
        return None      # una sola palabra larguísima: no hay dónde cortar
    return corte + 1


def extraer_frases(
    buffer: str, maximo: int = MAXIMO_POR_TROZO
) -> tuple[list[str], str]:
    """Separa de `buffer` lo que ya se puede decir y lo que aún no.

    Es una función pura: no recuerda nada entre llamadas. Quien la usa conserva
    el resto y se lo vuelve a pasar junta con el siguiente fragmento de texto.
    Así se puede probar con frases partidas a mano, sin depender de un modelo.

    Args:
        buffer: todo el texto acumulado que aún no se ha dicho.
        maximo: caracteres máximos antes de cortar por la última pausa.

    Returns:
        `(frases, resto)`. `frases` puede estar vacía y `resto` puede estar
        vacío, pero nunca se pierde texto: `"".join(frases) + resto` contiene
        exactamente los caracteres de `buffer`, salvo espacios sobrantes.
    """
    frases: list[str] = []
    resto = buffer

    while True:
        corte = _punto_de_corte(resto)
        if corte is None:
            break
        frase = resto[:corte].strip()
        if frase:
            frases.append(frase)
        resto = resto[corte:].lstrip()

    # Texto largo sin ningún signo: se corta por pausa para no quedarse mudo.
    while len(resto) > maximo:
        corte = _punto_de_corte_largo(resto, maximo)
        if corte is None:
            break
        frase = resto[:corte].strip()
        if frase:
            frases.append(frase)
        resto = resto[corte:].lstrip()

    return frases, resto


def frases_de(
    fragmentos: Iterator[str], maximo: int = MAXIMO_POR_TROZO
) -> Iterator[str]:
    """Convierte un chorro de fragmentos en un chorro de frases."""
    buffer = ""
    for fragmento in fragmentos:
        buffer += fragmento
        frases, buffer = extraer_frases(buffer, maximo)
        yield from frases
    if buffer.strip():
        yield buffer.strip()


async def frases_de_async(
    fragmentos: AsyncIterator[str], maximo: int = MAXIMO_POR_TROZO
) -> AsyncIterator[str]:
    """Igual que `frases_de`, para el generador asíncrono del cerebro."""
    buffer = ""
    async for fragmento in fragmentos:
        buffer += fragmento
        frases, buffer = extraer_frases(buffer, maximo)
        for frase in frases:
            yield frase
    if buffer.strip():
        yield buffer.strip()
