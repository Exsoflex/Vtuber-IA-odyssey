"""
Tests del panel: que la web exista y que los botones pidan lo correcto.

Por qué esto merece tests: un panel roto no lanza una excepción en la consola,
simplemente muestra «Apagado» para siempre o deja el botón de parar sin efecto.
Lo que se comprueba aquí es el contrato entre navegador y motor: qué recibe
`/api/estado` y qué método del motor llama cada botón.

No se abre un puerto ni se arranca uvicorn: `TestClient` ejecuta la app en
memoria. Tampoco se llama a Ollama ni al micrófono: los chips se sustituyen por
dobles para que el test no dependa de qué esté abierto en la máquina.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import panel.app as panel_app


class MotorFalso:
    """Motor mínimo: registra lo que le piden y cambia de estado."""

    def __init__(self) -> None:
        self.estado = "apagado"
        self.en_marcha = False
        self.inicios = 0
        self.detenciones = 0
        self.voces_calladas = 0

    async def iniciar(self) -> None:
        self.inicios += 1
        self.estado = "escuchando"
        self.en_marcha = True

    async def detener(self) -> None:
        self.detenciones += 1
        self.estado = "apagado"
        self.en_marcha = False

    async def detener_voz(self) -> None:
        self.voces_calladas += 1


class MotorQueFalla(MotorFalso):
    async def iniciar(self) -> None:
        raise RuntimeError("Ollama no contesta")


@contextmanager
def _panel(monkeypatch, motor):
    """App real con el motor indicado y los chips sin red."""
    async def ollama_si(_cliente):
        return True

    monkeypatch.setattr(panel_app, "_ollama_disponible", ollama_si)
    monkeypatch.setattr(panel_app, "_microfono_disponible", lambda nombre: True)
    monkeypatch.setattr(panel_app.vts_client, "connected", True)

    app = panel_app.crear_app()
    with TestClient(app) as c:
        # Después de entrar: el lifespan acaba de crear el motor real.
        app.state.motor = motor
        yield c, motor


@pytest.fixture
def cliente(monkeypatch):
    with _panel(monkeypatch, MotorFalso()) as par:
        yield par


@pytest.fixture
def cliente_que_falla(monkeypatch):
    with _panel(monkeypatch, MotorQueFalla()) as par:
        yield par


# ─── La página ─────────────────────────────────────────────────────────


def test_la_raiz_sirve_la_interfaz(cliente):
    c, _ = cliente

    respuesta = c.get("/")

    assert respuesta.status_code == 200
    assert "Niu" in respuesta.text
    assert "btn-iniciar" in respuesta.text


def test_los_estaticos_se_sirven(cliente):
    c, _ = cliente

    assert c.get("/estaticos/estilo.css").status_code == 200
    assert c.get("/estaticos/app.js").status_code == 200


# ─── Estado ────────────────────────────────────────────────────────────


def test_el_estado_incluye_chips_y_voz_activa(cliente):
    c, _ = cliente

    datos = c.get("/api/estado").json()

    assert datos["estado"] == "apagado"
    assert datos["en_marcha"] is False
    assert set(datos["chips"]) == {"motor", "ollama", "vts", "microfono", "tts"}
    assert datos["chips"]["ollama"] is True
    assert datos["chips"]["vts"] is True
    assert datos["chips"]["microfono"] is True
    assert datos["idioma"] and datos["voz"] and datos["tono"]


# ─── Botones ───────────────────────────────────────────────────────────


def test_iniciar_arranca_el_motor(cliente):
    c, motor = cliente

    datos = c.post("/api/motor/iniciar").json()

    assert motor.inicios == 1
    assert datos["estado"] == "escuchando"
    assert datos["en_marcha"] is True


def test_iniciar_dos_veces_no_arranca_dos_veces(cliente):
    c, motor = cliente

    c.post("/api/motor/iniciar")
    c.post("/api/motor/iniciar")

    assert motor.inicios == 1


def test_detener_para_el_motor(cliente):
    c, motor = cliente
    c.post("/api/motor/iniciar")

    datos = c.post("/api/motor/detener").json()

    assert motor.detenciones >= 1
    assert datos["estado"] == "apagado"


def test_detener_voz_no_apaga_el_motor(cliente):
    c, motor = cliente
    c.post("/api/motor/iniciar")

    datos = c.post("/api/motor/detener-voz").json()

    assert motor.voces_calladas == 1
    assert datos["estado"] == "escuchando"


def test_si_el_arranque_falla_el_panel_sigue_vivo_y_explica(cliente_que_falla):
    c, motor = cliente_que_falla

    c.post("/api/motor/iniciar")
    datos = c.get("/api/estado").json()

    assert datos["estado"] == "apagado"
    assert "Ollama no contesta" in datos["error"]
    # Un arranque a medias retiene modelos y el socket de VTS: hay que cerrarlo.
    assert motor.detenciones >= 1
