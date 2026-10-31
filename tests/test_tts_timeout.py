"""
Tests del tope de tiempo de Edge-TTS.

Por qué esto merece un test: el 18 de este mes un turno se quedó colgado más de
cinco minutos dentro de `comunicador.save()`, sin error, sin excepción y sin
nada que mirar. Edge-TTS es un servicio externo: puede tardar, y puede dejar de
contestar sin cerrar la conexión. Sin tope, eso congela la conversación entera.

El fallo es imposible de provocar a voluntad (habría que esperar a que el
servicio se caiga justo ahora), así que se simula: se sustituye
`edge_tts.Communicate` por un doble que se cuelga cuando se le pide.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import asyncio

import pytest

from core import config, tts


class ComunicadorFalso:
    """Doble de `edge_tts.Communicate` que obedece al atributo de clase `modo`.

    - "normal":        escribe el archivo y termina.
    - "siempre_cuelga": no termina nunca (simula el servicio que no contesta).
    - "cuelga_la_primera": se cuelga solo en la primera llamada.
    """

    modo = "normal"
    llamadas = 0

    def __init__(self, *args, **kwargs) -> None:
        ComunicadorFalso.llamadas += 1
        self._numero = ComunicadorFalso.llamadas

    async def save(self, ruta: str) -> None:
        if ComunicadorFalso.modo == "siempre_cuelga":
            await asyncio.sleep(3600)
        if ComunicadorFalso.modo == "cuelga_la_primera" and self._numero == 1:
            await asyncio.sleep(3600)
        with open(ruta, "wb") as archivo:
            archivo.write(b"\xff\xfb\x90\x00" * 100)


@pytest.fixture
def tts_rapido(monkeypatch):
    """Deja el tope en décimas de segundo y cambia el comunicador por el doble."""
    import edge_tts

    original = config.ajustes()
    monkeypatch.setattr(edge_tts, "Communicate", ComunicadorFalso)
    # El tope y los reintentos ya no son constantes del módulo: son ajustes.
    # Se cambian por el mismo camino que usará el panel.
    config.fijar_ajustes(config.con_cambios(tts_timeout=0.2, tts_intentos=2))
    ComunicadorFalso.llamadas = 0
    ComunicadorFalso.modo = "normal"
    try:
        yield ComunicadorFalso
    finally:
        config.fijar_ajustes(original)


@pytest.mark.asyncio
async def test_sintetiza_a_la_primera(tts_rapido, tmp_path):
    salida = tmp_path / "voz.mp3"
    assert await tts.sintetizar_voz_async("Hola.", str(salida)) is True
    assert tts_rapido.llamadas == 1
    assert salida.exists()


@pytest.mark.asyncio
async def test_se_rinde_si_nunca_contesta(tts_rapido, tmp_path):
    """Lo importante: devuelve False en vez de esperar para siempre."""
    tts_rapido.modo = "siempre_cuelga"
    salida = tmp_path / "voz.mp3"

    resultado = await asyncio.wait_for(
        tts.sintetizar_voz_async("Hola.", str(salida)),
        timeout=5,          # si el tope no funcionara, este test se colgaría
    )
    assert resultado is False
    assert tts_rapido.llamadas == 2       # lo intentó INTENTOS_TTS veces


@pytest.mark.asyncio
async def test_reintenta_y_se_recupera(tts_rapido, tmp_path):
    """Un cuelgue puntual no debe costar la frase."""
    tts_rapido.modo = "cuelga_la_primera"
    salida = tmp_path / "voz.mp3"

    resultado = await asyncio.wait_for(
        tts.sintetizar_voz_async("Hola.", str(salida)),
        timeout=5,
    )
    assert resultado is True
    assert tts_rapido.llamadas == 2
    assert salida.exists()


@pytest.mark.asyncio
async def test_texto_sin_nada_que_decir_no_llama_al_servicio(tts_rapido, tmp_path):
    """Un trozo que solo tenía emojis no debe gastar una petición de red."""
    salida = tmp_path / "voz.mp3"
    assert await tts.sintetizar_voz_async("🚀✨😜", str(salida)) is False
    assert tts_rapido.llamadas == 0
