"""
Tests del corte de texto en frases.

`extraer_frases()` decide cuándo lo que ha escrito el cerebro ya es "una frase
que se puede decir". Un error aquí no da ningún mensaje de error: solo hace que
Niu lea cosas raras (un decimal partido en dos, un emoji cortado, una pausa
donde no toca) o que tarde más de lo necesario en empezar a hablar.

Es una función pura, así que se puede probar con textos partidos a mano, sin
modelo, sin red y sin audio.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import pytest

from core.frases import MAXIMO_POR_TROZO, extraer_frases, frases_de


# ─── La regla básica: signo final + espacio ────────────────────────────


def test_frase_cerrada_con_espacio():
    frases, resto = extraer_frases("Hola Niu. ¿Qué tal?")
    assert frases == ["Hola Niu."]
    assert resto == "¿Qué tal?"


def test_signo_sin_espacio_no_cierra():
    """Un punto al final del buffer aún puede ser un decimal o un '...'."""
    frases, resto = extraer_frases("Son 3.")
    assert frases == []
    assert resto == "Son 3."


def test_varias_frases_de_golpe():
    frases, resto = extraer_frases("¡Hola! ¿Todo bien? Me alegro. ")
    assert frases == ["¡Hola!", "¿Todo bien?", "Me alegro."]
    assert resto == ""


def test_interrogacion_y_exclamacion():
    frases, _ = extraer_frases("¿En serio? ¡Qué fuerte! ")
    assert frases == ["¿En serio?", "¡Qué fuerte!"]


def test_puntos_suspensivos_completos():
    """Son una pausa, no un final: Niu los usa a mitad de frase."""
    frases, resto = extraer_frases("Bueno... no sé")
    assert frases == []
    assert resto == "Bueno... no sé"


def test_varias_dudas_no_se_trocean():
    """El caso real que motivó la regla: 'bueno... o sea... este...'."""
    frases, resto = extraer_frases("bueno... o sea... este... pues no sé.")
    assert frases == []
    frases, _ = extraer_frases(resto + " Al final iré. ")
    assert frases == ["bueno... o sea... este... pues no sé.", "Al final iré."]


def test_puntos_suspensivos_seguidos_de_espacio():
    frases, resto = extraer_frases("Bueno... ya veremos.")
    assert frases == []
    frases, resto = extraer_frases("Bueno... ya veremos. Y luego")
    assert frases == ["Bueno... ya veremos."]
    assert resto == "Y luego"


def test_caracter_de_puntos_suspensivos():
    frases, _ = extraer_frases("Pues… no lo sé. ")
    assert frases == ["Pues… no lo sé."]


# ─── Los casos que rompen: números, enlaces y emojis ───────────────────


def test_decimal_no_se_parte():
    frases, resto = extraer_frases("Hacen 3.5 grados hoy. ")
    assert frases == ["Hacen 3.5 grados hoy."]
    assert resto == ""


def test_decimal_llegando_en_dos_fragmentos():
    """El caso real: el primer fragmento acaba justo en el punto."""
    frases, resto = extraer_frases("Hacen 3.")
    assert frases == []
    frases, _ = extraer_frases(resto + "5 grados hoy. ")
    assert frases == ["Hacen 3.5 grados hoy."]


def test_enlace_web_no_se_parte():
    frases, _ = extraer_frases("Está en niu.dev y funciona. ")
    assert frases == ["Está en niu.dev y funciona."]


def test_emojis_no_se_parten():
    """Un emoji se queda entero en un trozo; cómo se reparta da igual.

    Da igual porque el emoji desaparece antes del TTS: `_limpiar_texto_para_tts`
    lo quita. Lo único que importa es que no se corte por la mitad, porque
    entonces sí llegaría roto al sintetizador.
    """
    frases, resto = extraer_frases("¡Qué guay! 🚀✨ ")
    assert " ".join(frases + [resto]).split() == ["¡Qué", "guay!", "🚀✨"]


def test_emoji_compuesto_no_se_parte():
    """Una familia son varios puntos de código unidos; el corte cae en espacios."""
    familia = "👩‍👩‍👧"
    frases, _ = extraer_frases(f"Mi familia {familia} es genial! ")
    assert frases == [f"Mi familia {familia} es genial!"]


# ─── Texto largo sin puntuación ────────────────────────────────────────


def test_texto_largo_sin_puntos_corta_por_coma():
    texto = "bueno " * 20 + ", " + "sigo hablando " * 20
    frases, resto = extraer_frases(texto)
    assert len(frases) >= 1
    assert all(len(f) <= MAXIMO_POR_TROZO + 2 for f in frases)
    assert resto


def test_texto_largo_sin_comas_corta_por_espacio():
    texto = "palabra " * 60
    frases, resto = extraer_frases(texto)
    assert len(frases) >= 1
    assert all(not f.startswith(" ") and not f.endswith(" ") for f in frases)


def test_palabra_larguisima_no_se_corta():
    """Si no hay ni un espacio, no hay dónde cortar: se espera."""
    texto = "a" * (MAXIMO_POR_TROZO * 2)
    frases, resto = extraer_frases(texto)
    assert frases == []
    assert resto == texto


def test_texto_largo_todavia_no_corta():
    frases, resto = extraer_frases("palabra " * 3)
    assert frases == []
    assert resto == "palabra " * 3


# ─── Propiedades que deben cumplirse siempre ───────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        "Hola. Adiós. ",
        "¿Qué? ¡No! ",
        "Son 3.5 y 4.2 grados. ",
        "Bueno... ya veremos. Y luego añadió algo más, con una coma, y siguió. ",
        "😜 " * 5,
        "palabra " * 50,
    ],
)
def test_nunca_se_pierde_texto(texto):
    """Todo lo que entra está en las frases o en el resto, en el mismo orden."""
    frases, resto = extraer_frases(texto)
    reconstruido = (" ".join(frases) + " " + resto).split()
    assert reconstruido == texto.split()


def test_fragmentos_uno_a_uno_reconstruyen_el_texto():
    """El caso real: el cerebro envía el texto en trozos pequeños."""
    original = "¡Hola Rotceh! ¿Cómo estás hoy? Espero que muy bien. 🚀"
    trozos = list(original)          # lo más hostil posible: carácter a carácter
    frases = list(frases_de(iter(trozos)))
    assert " ".join(frases) == " ".join(original.split())
