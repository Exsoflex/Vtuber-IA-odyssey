"""
Tests de `core/config.py`: el objeto único de ajustes.

Por qué esto merece tests propios: este módulo decide qué valor usa Niu cuando
hay tres fuentes que pueden contradecirse (`config.json`, variables de entorno
y valores de fábrica). Un fallo aquí no lanza ninguna excepción: Niu
simplemente habla con otra voz, escucha en otro idioma o espera tres minutos a
que el usuario termine una frase. Es exactamente el tipo de error que no se ve
hasta que ya está en una conversación.

Lo que se comprueba:

1. Que los valores por defecto sean los documentados.
2. Que un valor absurdo se corrija **y avise**, en vez de romper el arranque.
3. Que la precedencia sea `config.json > entorno > defecto`.
4. Que guardar y cargar devuelva lo mismo, y que un JSON corrupto no impida
   arrancar.

Nada de esto toca el `config.json` real del proyecto: cada test usa un archivo
temporal, y el fixture `ajustes_limpios` devuelve el estado vivo como estaba.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json

import pytest

from core import config


@pytest.fixture(autouse=True)
def ajustes_limpios(monkeypatch):
    """Parte de un entorno vacío y devuelve el objeto vivo como estaba.

    Sin limpiar las variables, un `NIU_IDIOMA` puesto en la sesión de PowerShell
    haría fallar tests que esperan valores de fábrica. Y sin restaurar el
    objeto, un test contaminaría al siguiente.
    """
    for variable in config.VARIABLES_ENTORNO.values():
        monkeypatch.delenv(variable, raising=False)

    original = config.ajustes()
    try:
        yield
    finally:
        config.fijar_ajustes(original)


@pytest.fixture
def ruta(tmp_path):
    """Un `config.json` de mentira, para no tocar el del proyecto."""
    return tmp_path / "config.json"


# ─── Valores de fábrica ────────────────────────────────────────────────


def test_los_valores_por_defecto_son_los_documentados():
    ajustes = config.por_defecto()

    assert ajustes.idioma == "es"
    assert ajustes.motor_stt == "whisper"
    assert ajustes.modelo_whisper == "large-v3-turbo"
    assert ajustes.silencio_final == pytest.approx(0.9)
    # Voz y tono vacíos significan "la del perfil de idioma": si se clavaran
    # aquí, cambiar de idioma dejaría la voz del anterior.
    assert ajustes.voz == ""
    assert ajustes.tono == ""
    assert ajustes.salida == ""


def test_normalizar_sin_datos_equivale_a_los_valores_por_defecto():
    ajustes, avisos = config.normalizar({})

    assert ajustes == config.por_defecto()
    assert avisos == []


# ─── Validación: corregir y avisar, nunca romper ───────────────────────


def test_un_numero_ilegible_vuelve_al_valor_por_defecto():
    ajustes, avisos = config.normalizar({"silencio_final": "mucho"})

    assert ajustes.silencio_final == pytest.approx(0.9)
    assert any("silencio_final" in aviso for aviso in avisos)


@pytest.mark.parametrize(
    "campo, malo, bueno",
    [
        ("tono", "5", ""),               # sin unidad, Edge-TTS lo ignoraría
        ("tono", "muy grave", ""),
        ("velocidad", "lento", "+0%"),
        ("velocidad", "20", "+0%"),       # sin el símbolo de porcentaje
        ("motor_stt", "otro", "whisper"),
        ("idioma", "espanol", "es"),
    ],
)
def test_un_formato_invalido_se_corrige(campo, malo, bueno):
    """Un valor inválido corregido en silencio es peor que uno avisado."""
    ajustes, avisos = config.normalizar({campo: malo})

    assert getattr(ajustes, campo) == bueno
    assert avisos, f"{campo}={malo!r} debería haber generado un aviso"


@pytest.mark.parametrize(
    "campo, valor, esperado",
    [
        ("silencio_final", 99.0, 3.0),
        ("silencio_final", 0.0, 0.2),
        ("temperatura", -1.0, 0.0),
        ("temperatura", 3.5, 2.0),
        ("tts_intentos", 0, 1),
        ("tts_intentos", 500, 5),
    ],
)
def test_un_valor_fuera_de_rango_se_recorta(campo, valor, esperado):
    ajustes, avisos = config.normalizar({campo: valor})

    assert getattr(ajustes, campo) == pytest.approx(esperado)
    assert any(campo in aviso for aviso in avisos)


def test_una_clave_desconocida_se_ignora_sin_romper():
    """Un `config.json` de una versión futura no debe impedir arrancar."""
    ajustes, avisos = config.normalizar({"campo_que_no_existe": 42})

    assert ajustes == config.por_defecto()
    assert any("campo_que_no_existe" in aviso for aviso in avisos)


def test_tono_y_velocidad_validos_pasan_intactos():
    ajustes, avisos = config.normalizar({"tono": "-15Hz", "velocidad": "+12%"})

    assert ajustes.tono == "-15Hz"
    assert ajustes.velocidad == "+12%"
    assert avisos == []


# ─── Precedencia: config.json > entorno > defecto ──────────────────────


def test_lee_las_variables_de_entorno(monkeypatch, ruta):
    """El `.env` que ya existe tiene que seguir funcionando."""
    monkeypatch.setenv("NIU_IDIOMA", "en")
    monkeypatch.setenv("NIU_SILENCIO_FINAL", "1.4")
    monkeypatch.setenv("OLLAMA_MODEL", "otro-modelo:7b")

    ajustes = config.cargar_ajustes(ruta)

    assert ajustes.idioma == "en"
    assert ajustes.silencio_final == pytest.approx(1.4)
    assert ajustes.modelo_llm == "otro-modelo:7b"


def test_una_variable_vacia_no_pisa_el_valor_por_defecto(monkeypatch, ruta):
    monkeypatch.setenv("NIU_IDIOMA", "   ")

    assert config.cargar_ajustes(ruta).idioma == "es"


def test_el_json_gana_al_entorno(monkeypatch, ruta):
    """Lo que edita el panel manda: el entorno es solo la fuente de arranque."""
    monkeypatch.setenv("NIU_IDIOMA", "es")
    ruta.write_text(json.dumps({"idioma": "en"}), encoding="utf-8")

    assert config.cargar_ajustes(ruta).idioma == "en"


# ─── Persistencia ──────────────────────────────────────────────────────


def test_guardar_y_cargar_devuelve_lo_mismo(ruta):
    original = config.con_cambios(
        idioma="en",
        voz="en-US-AriaNeural",
        tono="+0Hz",
        velocidad="-8%",
        microfono="Micrófono con acentos",
        silencio_final=1.2,
        temperatura=0.6,
    )

    config.guardar_ajustes(original, ruta)
    recuperado = config.cargar_ajustes(ruta)

    assert recuperado == original
    # El archivo se lee a mano alguna vez: los acentos tienen que verse.
    assert "Micrófono" in ruta.read_text(encoding="utf-8")


def test_restablecer_vuelve_a_fabrica_en_memoria_y_en_disco(monkeypatch, ruta):
    monkeypatch.setattr(config, "RUTA_CONFIG", ruta)
    config.fijar_ajustes(config.con_cambios(idioma="en", silencio_final=2.0))

    nuevos = config.restablecer()

    assert nuevos == config.por_defecto()
    assert config.ajustes() == config.por_defecto()
    assert json.loads(ruta.read_text(encoding="utf-8"))["idioma"] == "es"


def test_un_json_corrupto_no_impide_arrancar(ruta):
    """Un editor a medias no debería costar una sesión de depuración."""
    ruta.write_text('{"idioma": "en",', encoding="utf-8")

    ajustes = config.cargar_ajustes(ruta)

    assert ajustes == config.por_defecto()


def test_un_json_que_no_es_un_objeto_se_ignora(ruta):
    ruta.write_text("[]", encoding="utf-8")

    assert config.cargar_ajustes(ruta) == config.por_defecto()


# ─── Cambios en caliente ───────────────────────────────────────────────


def test_con_cambios_no_muta_el_objeto_activo():
    """Nunca se cambia el objeto vivo a medias: se construye y se aplica."""
    antes = config.ajustes()

    nuevo = config.con_cambios(silencio_final=1.5)

    assert config.ajustes() is antes
    assert nuevo.silencio_final == pytest.approx(1.5)


def test_con_cambios_tambien_valida():
    nuevo = config.con_cambios(silencio_final=99.0)

    assert nuevo.silencio_final == pytest.approx(3.0)
