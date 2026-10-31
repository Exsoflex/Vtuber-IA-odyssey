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
import panel.chat as panel_chat


class MotorFalso:
    """Motor mínimo: registra lo que le piden y cambia de estado."""

    def __init__(self) -> None:
        self.estado = "apagado"
        self.en_marcha = False
        self.inicios = 0
        self.detenciones = 0
        self.voces_calladas = 0
        self.textos: list[str] = []

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

    def enviar_texto(self, texto: str) -> bool:
        if not self.en_marcha or not texto.strip():
            return False
        self.textos.append(texto.strip())
        return True


class MotorQueFalla(MotorFalso):
    async def iniciar(self) -> None:
        raise RuntimeError("Ollama no contesta")


@contextmanager
def _panel(monkeypatch, motor, carpeta):
    """App real con el motor indicado y los chips sin red.

    `carpeta` es temporal: una prueba que hable no debe escribir sesiones en el
    proyecto.
    """
    async def ollama_si(_cliente):
        return True

    monkeypatch.setattr(panel_app, "_ollama_disponible", ollama_si)
    monkeypatch.setattr(panel_app, "_microfono_disponible", lambda nombre: True)
    monkeypatch.setattr(panel_app.vts_client, "connected", True)
    monkeypatch.setattr(panel_chat, "CARPETA_POR_DEFECTO", carpeta)

    app = panel_app.crear_app()
    with TestClient(app) as c:
        # Después de entrar: el lifespan acaba de crear el motor real.
        app.state.motor = motor
        yield c, motor


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    with _panel(monkeypatch, MotorFalso(), tmp_path) as par:
        yield par


@pytest.fixture
def cliente_que_falla(monkeypatch, tmp_path):
    with _panel(monkeypatch, MotorQueFalla(), tmp_path) as par:
        yield par


# ─── La página ─────────────────────────────────────────────────────────


def test_la_raiz_sirve_la_interfaz(cliente):
    c, _ = cliente

    respuesta = c.get("/")

    assert respuesta.status_code == 200
    assert "Niu" in respuesta.text
    assert "btn-iniciar" in respuesta.text
    assert "chat-entrada" in respuesta.text


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


# ─── Chat ──────────────────────────────────────────────────────────────


def test_la_sesion_empieza_vacia_y_apunta_a_un_archivo(cliente):
    c, _ = cliente

    datos = c.get("/api/sesion").json()

    assert datos["tipo"] == "historial"
    assert datos["mensajes"] == []
    assert datos["archivo"].endswith(".json")


def test_un_mensaje_escrito_llega_al_motor_y_al_chat(cliente):
    c, motor = cliente
    c.post("/api/motor/iniciar")

    respuesta = c.post("/api/mensaje", json={"texto": "  hola  "})

    assert respuesta.status_code == 200
    assert motor.textos == ["hola"]
    mensajes = c.get("/api/sesion").json()["mensajes"]
    assert mensajes[-1]["papel"] == "usuario"
    assert mensajes[-1]["texto"] == "hola"


def test_no_se_puede_escribir_con_el_motor_apagado(cliente):
    c, motor = cliente

    respuesta = c.post("/api/mensaje", json={"texto": "hola"})

    assert respuesta.status_code == 409
    assert "no está en marcha" in respuesta.json()["detail"]
    assert motor.textos == []
    assert c.get("/api/sesion").json()["mensajes"] == []


def test_un_mensaje_vacio_se_rechaza(cliente):
    c, motor = cliente
    c.post("/api/motor/iniciar")

    respuesta = c.post("/api/mensaje", json={"texto": "   "})

    assert respuesta.status_code == 400
    assert motor.textos == []


def test_el_websocket_manda_el_historial_y_los_mensajes_nuevos(cliente):
    c, _ = cliente
    c.post("/api/motor/iniciar")

    with c.websocket_connect("/ws") as ws:
        saludo = ws.receive_json()
        assert saludo["tipo"] == "historial"
        assert saludo["mensajes"] == []

        c.post("/api/mensaje", json={"texto": "hola"})

        evento = ws.receive_json()
        assert evento["tipo"] == "mensaje"
        assert evento["mensaje"]["papel"] == "usuario"
        assert evento["mensaje"]["texto"] == "hola"


def test_exportar_descarga_la_sesion_en_markdown(cliente):
    c, _ = cliente
    c.post("/api/motor/iniciar")
    c.post("/api/mensaje", json={"texto": "hola"})

    respuesta = c.get("/api/sesion/exportar")

    assert respuesta.status_code == 200
    assert "text/markdown" in respuesta.headers["content-type"]
    assert "attachment" in respuesta.headers["content-disposition"]
    assert "hola" in respuesta.text


def test_limpiar_vacia_el_chat_y_empieza_otra_sesion(cliente, tmp_path):
    c, _ = cliente
    c.post("/api/motor/iniciar")
    c.post("/api/mensaje", json={"texto": "hola"})
    archivo_anterior = c.get("/api/sesion").json()["archivo"]

    datos = c.post("/api/sesion/limpiar").json()

    assert datos["mensajes"] == []
    assert datos["archivo"] != archivo_anterior
    assert (tmp_path / archivo_anterior.split("/")[-1]).exists()
