"""
Tests de `panel/ajustes.py`: el formulario que escribe `config.json`.

Por qué merece tests propios: aquí se juntan tres cosas que pueden fallar sin
hacer ruido.

1. **Persistencia**: un cambio que solo vive en memoria parece funcionar hasta
   que se reinicia el panel. Hay que comprobar que el archivo se escriba.
2. **Validación con aviso**: el panel no rechaza un valor raro, lo corrige y
   devuelve el motivo. Si el aviso se pierde, la interfaz miente.
3. **Cambios calientes y fríos**: `tono` se aplica en la frase siguiente, pero
   `idioma` o `microfono` se capturan al arrancar el motor. La respuesta tiene
   que decir cuáles quedan pendientes para no dejar al usuario esperando un
   cambio que no ocurrirá.

Ningún test toca el `config.json` real: el fixture `entorno` redirige
`config.RUTA_CONFIG` a un directorio temporal y devuelve el objeto vivo como
estaba.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from core import config, perfiles, tts
from panel import ajustes as panel_ajustes


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    """Ajustes de fábrica, sin `.env`, con config y perfiles temporales."""
    for variable in config.VARIABLES_ENTORNO.values():
        monkeypatch.delenv(variable, raising=False)

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(perfiles, "RUTA_PERFILES", tmp_path / "perfiles.json")
    original = config.ajustes()
    config.fijar_ajustes(config.por_defecto())
    try:
        yield tmp_path
    finally:
        config.fijar_ajustes(original)


class MotorFalso:
    def __init__(self, estado: str = "escuchando") -> None:
        self.estado = estado


# ─── Esquema ───────────────────────────────────────────────────────────


def test_el_esquema_trae_valores_esquema_y_secciones():
    datos = panel_ajustes.descripcion_ajustes()

    assert datos["valores"] == asdict(config.por_defecto())
    assert datos["defecto"] == asdict(config.por_defecto())
    assert set(datos["secciones"]) == {"voz", "audio", "modelos",
                                       "conversacion", "avanzado"}

    nombres = {campo["campo"] for campo in datos["campos"]}
    assert nomina_completa(nombres)
    for campo in datos["campos"]:
        assert campo["seccion"] in datos["secciones"]
        assert campo["etiqueta"]
        assert campo["tipo"] in {"seleccion", "texto", "hz", "porcentaje", "numero"}


def nomina_completa(nombres: set[str]) -> bool:
    """Los 13 ajustes editables, incluidos los tres avanzados."""
    esperados = set(asdict(config.por_defecto()))
    return nombres == esperados


def test_los_campos_que_requieren_reinicio_estan_marcados_frios():
    por_nombre = {campo["campo"]: campo
                  for campo in panel_ajustes.descripcion_ajustes()["campos"]}

    for campo in panel_ajustes.REQUIEREN_REINICIO:
        assert por_nombre[campo]["en_caliente"] is False
        assert "reiniciar" in por_nombre[campo]["nota"].lower()

    # El tono no reinicia nada: es el ejemplo de ajuste caliente.
    assert por_nombre["tono"]["en_caliente"] is True


def test_los_rangos_de_la_interfaz_caben_dentro_de_los_del_config():
    """Si la UI ofreciera menos, no podría mostrar un valor guardado a mano."""
    campos = {campo["campo"]: campo
              for campo in panel_ajustes.descripcion_ajustes()["campos"]}

    for nombre, (minimo, maximo) in config._RANGOS.items():
        campo = campos[nombre]
        assert campo["minimo"] <= minimo
        assert campo["maximo"] >= maximo


# ─── Guardar ───────────────────────────────────────────────────────────


def test_un_cambio_caliente_se_aplica_y_se_guarda(entorno):
    resultado = panel_ajustes.aplicar_ajustes({"tono": "-10Hz"})

    assert resultado["valores"]["tono"] == "-10Hz"
    assert resultado["requiere_reinicio"] == []
    assert resultado["avisos"] == []
    assert config.ajustes().tono == "-10Hz"

    guardado = (entorno / "config.json").read_text(encoding="utf-8")
    assert "-10Hz" in guardado


def test_un_cambio_frio_avisa_de_que_hace_falta_reiniciar():
    resultado = panel_ajustes.aplicar_ajustes({"idioma": "en",
                                               "microfono": "Otra cosa"})

    assert resultado["requiere_reinicio"] == ["idioma", "microfono"]


def test_un_valor_absurdo_se_corrige_con_aviso_y_no_deja_el_estado_a_medias():
    resultado = panel_ajustes.aplicar_ajustes({"silencio_final": 99})

    assert resultado["valores"]["silencio_final"] == config._RANGOS["silencio_final"][1]
    assert any("silencio_final" in aviso for aviso in resultado["avisos"])
    assert config.ajustes().silencio_final == 3.0


def test_guardar_un_campo_no_pisa_los_demas(entorno):
    config.fijar_ajustes(config.con_cambios(voz="en-US-AriaNeural"))

    panel_ajustes.aplicar_ajustes({"velocidad": "-8%"})

    actual = config.ajustes()
    assert actual.voz == "en-US-AriaNeural"
    assert actual.velocidad == "-8%"


def test_restaurar_vuelve_a_fabrica_en_memoria_y_en_disco(entorno):
    panel_ajustes.aplicar_ajustes({"tono": "+20Hz", "idioma": "en"})

    resultado = panel_ajustes.restaurar_ajustes()

    assert resultado["valores"] == asdict(config.por_defecto())
    assert resultado["requiere_reinicio"] == ["idioma"]
    assert config.ajustes() == config.por_defecto()

    guardado = (entorno / "config.json").read_text(encoding="utf-8")
    assert "+20Hz" not in guardado


# ─── Probar voz ────────────────────────────────────────────────────────


def _preparar_tts_falso(monkeypatch, generado=True):
    """Sustituye Edge-TTS y la reproducción; devuelve lo que se le pidió."""
    llamadas = {}

    async def sintetizar(texto, archivo, voz=None, tono=None, velocidad=None):
        llamadas["texto"] = texto
        llamadas["voz"] = voz
        llamadas["tono"] = tono
        llamadas["velocidad"] = velocidad
        return generado

    monkeypatch.setattr(tts, "sintetizar_voz_async", sintetizar)
    monkeypatch.setattr(tts, "preparar_audio",
                        lambda _ruta: SimpleNamespace(duracion=1.5))
    monkeypatch.setattr(tts, "detener_reproduccion", lambda: llamadas.update(detenida=True))
    monkeypatch.setattr(tts, "reproducir_audio",
                        lambda _audio: llamadas.update(reproducido=True))
    return llamadas


async def test_probar_voz_usa_los_valores_sin_guardarlos(monkeypatch):
    llamadas = _preparar_tts_falso(monkeypatch)

    resultado = await panel_ajustes.probar_voz(
        MotorFalso(), voz="en-US-AriaNeural", tono="-5Hz", velocidad="+10%",
        idioma="en",
    )

    assert resultado["ok"] is True
    assert resultado["duracion"] == 1.5
    assert llamadas["voz"] == "en-US-AriaNeural"
    assert llamadas["tono"] == "-5Hz"
    assert llamadas["velocidad"] == "+10%"
    # La frase de prueba sigue al idioma del formulario, no al guardado.
    assert llamadas["texto"].startswith("Hi, I'm Niu")
    assert llamadas["reproducido"] is True
    # Nada de esto se guardó: probar es solo oír.
    assert config.ajustes() == config.por_defecto()


async def test_probar_voz_con_otro_idioma_usa_el_perfil_de_ese_idioma(monkeypatch):
    """«Voz vacía» con idioma inglés debe sonar en inglés, no en el guardado."""
    llamadas = _preparar_tts_falso(monkeypatch)

    resultado = await panel_ajustes.probar_voz(MotorFalso(), idioma="en")

    assert llamadas["voz"] == "en-US-AriaNeural"
    assert resultado["voz"] == "en-US-AriaNeural"
    assert llamadas["texto"].startswith("Hi, I'm Niu")


async def test_probar_voz_sin_audio_no_finge_que_sono(monkeypatch):
    _preparar_tts_falso(monkeypatch, generado=False)

    resultado = await panel_ajustes.probar_voz(MotorFalso(), tono="+5Hz")

    assert resultado["ok"] is False
    assert "audio" in resultado["detalle"]


async def test_no_se_prueba_la_voz_mientras_niu_habla():
    with pytest.raises(panel_ajustes.MotorOcupado):
        await panel_ajustes.probar_voz(MotorFalso(estado="hablando"))

    with pytest.raises(panel_ajustes.MotorOcupado):
        await panel_ajustes.probar_voz(MotorFalso(estado="pensando"))


# ─── Listas del sistema ────────────────────────────────────────────────


async def test_los_dispositivos_se_listan_por_nombre_y_host(monkeypatch):
    salida = [
        {"name": "DGM20 USB Microphone", "hostapi": 0,
         "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Altavoces", "hostapi": 1,
         "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setattr(panel_ajustes.sd, "query_devices", lambda: salida)
    monkeypatch.setattr(panel_ajustes.sd, "query_hostapis",
                        lambda: [{"name": "MME"}, {"name": "DirectSound"}])

    datos = await panel_ajustes.listar_dispositivos()

    assert [d["nombre"] for d in datos["entrada"]] == ["DGM20 USB Microphone"]
    assert [d["nombre"] for d in datos["salida"]] == ["Altavoces"]
    assert datos["entrada"][0]["host_api"] == "MME"
    assert datos["salida"][0]["host_api"] == "DirectSound"


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._datos


class _Cliente:
    async def get(self, url, timeout=None):
        assert url == panel_ajustes.URL_OLLAMA
        return _Respuesta({"models": [{"name": "qwen2.5:7b"},
                                      {"name": "llama3:8b"}]})


async def test_los_modelos_de_ollama_son_solo_los_nombres():
    datos = await panel_ajustes.listar_modelos(_Cliente())

    assert datos["llm"] == ["qwen2.5:7b", "llama3:8b"]
    assert "error" not in datos


async def test_si_ollama_no_contesta_la_lista_viene_con_el_motivo():
    class _Caido:
        async def get(self, url, timeout=None):
            raise ConnectionError("sin respuesta")

    datos = await panel_ajustes.listar_modelos(_Caido())

    assert datos["llm"] == []
    assert "ConnectionError" in datos["error"]
