"""
Tests de que el oído escuche en el mismo idioma en que Niu habla.

El fallo que cubren: con el STT en detección automática y un `initial_prompt`
en español, Whisper "oía" español aunque se le hablara en inglés. La
transcripción salía en español y Niu respondía a algo que no se había dicho.
Nada de eso lanza una excepción: simplemente la conversación se vuelve absurda.

Por eso hay dos capas que comprobar:

1. `idioma_stt()`: el idioma que se le pide al motor, que por defecto debe
   seguir al perfil.
2. El prompt del decoder: tiene que estar en ese mismo idioma. Un `language=en`
   con un prompt en español sigue sesgando la decodificación al español.

Desde la fase 0 del panel, el idioma activo ya no es una constante de
importación: vive en `core/config.py`. Cada test que lo cambia lo hace a través
de `config.fijar_ajustes()` y el fixture `ajustes_limpios` deja el estado como
estaba, para que un test no contamine al siguiente.

Sin red, sin modelo y sin micrófono.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import re

import pytest

from core import config
from core.idiomas import ESPANOL, IDIOMAS, INGLES
from core.stt import idioma_stt
from core.stt_whisper import WhisperSTT

PERFILES = [ESPANOL, INGLES]


@pytest.fixture(autouse=True)
def ajustes_limpios(monkeypatch):
    """Parte de un estado conocido y lo devuelve intacto al terminar.

    Sin esto, un test que pone `idioma="en"` dejaría a los siguientes leyendo
    el perfil inglés y el fallo aparecería en un test que no tiene nada que ver.
    """
    monkeypatch.delenv("NIU_STT_PROMPT", raising=False)
    monkeypatch.delenv("NIU_STT_IDIOMA", raising=False)
    original = config.ajustes()
    config.fijar_ajustes(config.por_defecto())
    try:
        yield
    finally:
        config.fijar_ajustes(original)


# ─── Qué idioma se le pide al motor ────────────────────────────────────


def test_por_defecto_sigue_al_perfil():
    """Con `idioma="en"` en los ajustes, el oído espera inglés sin más."""
    config.fijar_ajustes(config.con_cambios(idioma="en"))
    assert idioma_stt() == "en"


def test_el_idioma_del_perfil_activo_es_el_que_se_pide():
    assert idioma_stt() == config.ajustes().idioma


def test_se_puede_forzar_otro_idioma(monkeypatch):
    monkeypatch.setenv("NIU_STT_IDIOMA", "  ES ")
    assert idioma_stt() == "es"


def test_auto_vuelve_a_la_deteccion_automatica(monkeypatch):
    """La salida de emergencia para quien alterna idiomas de verdad."""
    monkeypatch.setenv("NIU_STT_IDIOMA", "auto")
    assert idioma_stt() is None


# ─── El prompt del decoder, que es la mitad del problema ───────────────


@pytest.mark.parametrize("codigo", sorted(IDIOMAS))
def test_el_prompt_esta_en_el_idioma_del_perfil(codigo):
    """Sin esto, `language=en` con prompt español sigue "oyendo" español."""
    perfil = IDIOMAS[codigo]
    assert WhisperSTT(idioma=codigo).prompt == perfil.prompt_stt.strip()


def test_el_prompt_ingles_no_esta_en_espanol():
    prompt = WhisperSTT(idioma="en").prompt
    assert "English" in prompt
    assert "español" not in prompt.lower()


def test_el_prompt_en_espanol_mantiene_el_vocabulario_de_casa():
    prompt = WhisperSTT(idioma="es").prompt
    assert "Niu" in prompt
    assert "español" in prompt.lower()


def test_sin_idioma_usa_el_prompt_del_perfil_activo():
    """En automático el oído hereda el perfil: Niu va a contestar en ese idioma."""
    config.fijar_ajustes(config.con_cambios(idioma="en"))
    assert WhisperSTT().prompt == INGLES.prompt_stt.strip()


def test_un_idioma_desconocido_no_se_sesga_con_otro():
    """Si se fuerza 'fr' y no hay perfil, mejor sin pista que con una española."""
    assert WhisperSTT(idioma="fr").prompt is None


def test_la_variable_de_entorno_puede_sobrescribir_el_prompt(monkeypatch):
    monkeypatch.setenv("NIU_STT_PROMPT", "contexto a medida de Héctor")
    assert WhisperSTT(idioma="en").prompt == "contexto a medida de Héctor"


def test_un_prompt_vacio_desactiva_el_contexto(monkeypatch):
    monkeypatch.setenv("NIU_STT_PROMPT", "")
    assert WhisperSTT(idioma="en").prompt is None


# ─── El tono, que también es dato del perfil ───────────────────────────


@pytest.mark.parametrize("perfil", PERFILES, ids=[p.codigo for p in PERFILES])
def test_el_tono_tiene_formato_de_edge_tts(perfil):
    """Edge-TTS espera hercios con signo ('-15Hz'); otra cosa no es válida."""
    assert re.fullmatch(r"[+-]\d+Hz", perfil.tono), perfil.tono
