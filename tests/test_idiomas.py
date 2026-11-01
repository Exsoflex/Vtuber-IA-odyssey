"""
Tests de los perfiles de idioma.

Dos cosas se pueden romper aquí sin que salte ningún error:

1. Que la voz no sea del idioma del perfil. Una voz española leyendo inglés no
   falla: suena mal, y eso no se detecta hasta que alguien lo escucha.
2. Que las reglas de idioma no lleguen al modelo. Si el cerebro se olvida de
   añadirlas al prompt, Niu sigue contestando en el idioma que le apetezca y
   todo parece funcionar.

Los tests comprueban las dos, sin red y sin modelo.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import pytest

from core import perfiles
from core.brain import SISTEMA_INSTRUCCION_NIU, NiuBrain
from core.idiomas import ESPANOL, IDIOMAS, INGLES, elegir_idioma


@pytest.fixture(autouse=True)
def personalidad_de_fabrica(monkeypatch):
    """Estos tests comprueban el idioma, no la instrucción guardada.

    Sin esto, editar la personalidad desde el panel haría que la suite
    dependiera del `perfiles.json` de la máquina.
    """
    monkeypatch.setattr(perfiles, "instruccion_activa",
                        lambda: SISTEMA_INSTRUCCION_NIU)


class ProveedorFalso:
    """Guarda la instrucción que recibe, en vez de llamar a un modelo."""

    def __init__(self) -> None:
        self.instrucciones: list[str | None] = []

    async def generate(self, messages, system_instruction, config):
        from core.llm_provider import LLMResponse

        self.instrucciones.append(system_instruction)
        return LLMResponse(text="ok")

    async def generate_stream(self, messages, system_instruction, config):
        self.instrucciones.append(system_instruction)
        yield "ok"


# ─── Coherencia de la tabla ────────────────────────────────────────────


def test_hay_espanol_e_ingles():
    assert set(IDIOMAS) >= {"es", "en"}


@pytest.mark.parametrize("codigo", sorted(IDIOMAS))
def test_la_voz_es_del_mismo_idioma(codigo):
    """El nombre de la voz de Edge-TTS empieza por el código del idioma."""
    perfil = IDIOMAS[codigo]
    assert perfil.voz.lower().startswith(f"{codigo}-"), (
        f"{perfil.nombre}: la voz {perfil.voz!r} no es de idioma {codigo!r}"
    )


@pytest.mark.parametrize("codigo", sorted(IDIOMAS))
def test_cada_perfil_tiene_reglas(codigo):
    """Sin reglas, el perfil solo cambiaría la voz y no el idioma del texto."""
    assert len(IDIOMAS[codigo].reglas.strip()) > 40


def test_el_ingles_prohibe_traducir_muletillas():
    """La regla que evita que Niu suene a traducción literal."""
    assert "NEVER translate" in INGLES.reglas
    assert "like..." in INGLES.reglas


# ─── Elección del perfil ───────────────────────────────────────────────


def test_elige_por_codigo():
    assert elegir_idioma("en") is INGLES


def test_no_le_importan_las_mayusculas_ni_los_espacios():
    assert elegir_idioma("  EN ") is INGLES


def test_un_codigo_desconocido_no_rompe_el_arranque():
    """Una errata en NIU_IDIOMA no debe dejar a Niu muda."""
    assert elegir_idioma("fr") is ESPANOL


# ─── Lo que de verdad importa: que llegue al modelo ────────────────────


@pytest.mark.parametrize("perfil", [ESPANOL, INGLES], ids=["es", "en"])
async def test_el_cerebro_envia_las_reglas_del_idioma(perfil):
    proveedor = ProveedorFalso()
    cerebro = NiuBrain(provider=proveedor, idioma=perfil)

    await cerebro.procesar_mensaje("Rotceh", "hola")

    assert proveedor.instrucciones, "no se llamó al proveedor"
    instruccion = proveedor.instrucciones[0]
    assert perfil.reglas.strip() in instruccion


async def test_el_perfil_anade_reglas_sin_borrar_la_personalidad():
    """La personalidad se escribe una vez; el idioma es un añadido."""
    proveedor = ProveedorFalso()
    cerebro = NiuBrain(provider=proveedor, idioma=INGLES)

    await cerebro.procesar_mensaje("Rotceh", "hi")

    instruccion = proveedor.instrucciones[0]
    assert SISTEMA_INSTRUCCION_NIU in instruccion
    assert INGLES.reglas in instruccion
    assert len(instruccion) > len(SISTEMA_INSTRUCCION_NIU)


async def test_el_streaming_tambien_lleva_las_reglas():
    """El camino que usa main.py es el de streaming; hay que probar ese."""
    proveedor = ProveedorFalso()
    cerebro = NiuBrain(provider=proveedor, idioma=INGLES)

    async for _ in cerebro.procesar_mensaje_streaming("Rotceh", "hi"):
        pass

    assert INGLES.reglas.strip() in proveedor.instrucciones[0]


async def test_editar_la_instruccion_surte_efecto_en_el_turno_siguiente(monkeypatch):
    """El motor se crea una vez; la personalidad se lee en cada turno.

    Si la instrucción se capturara al construir `NiuBrain`, editarla en el
    panel no haría nada hasta reiniciar, y eso se ve como un fallo silencioso.
    """
    actual = {"texto": "Personalidad A"}
    monkeypatch.setattr(perfiles, "instruccion_activa", lambda: actual["texto"])

    proveedor = ProveedorFalso()
    cerebro = NiuBrain(provider=proveedor, idioma=ESPANOL)

    await cerebro.procesar_mensaje("Rotceh", "hola")
    actual["texto"] = "Personalidad B"
    await cerebro.procesar_mensaje("Rotceh", "otra vez")

    primera, segunda = proveedor.instrucciones
    assert primera.startswith("Personalidad A")
    assert segunda.startswith("Personalidad B")
