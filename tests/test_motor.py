"""
Tests del motor: estados, eventos, parada y «detener solo la voz».

Por qué esto merece tests: el motor es lo que el panel va a arrancar y parar.
Los fallos aquí no son excepciones visibles, son comportamientos raros:
un botón que deja el bucle vivo, una voz que sigue sonando después de pulsar
«detener», un estado que nunca vuelve a «escuchando» y deja la interfaz
congelada. Ninguno se detecta mirando la consola.

Todo se prueba con dobles: cerebro falso, sin micrófono, sin VTS y sin red.
La entrada de teclado se sustituye con `monkeypatch` sobre `builtins.input`,
que es lo que `_escuchar` lee en un hilo.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import asyncio

import pytest

from core.motor import (
    APAGADO,
    ESCUCHANDO,
    HABLANDO,
    PENSANDO,
    MotorNiu,
)


class ProveedorFalso:
    """Proveedor LLM mínimo: solo lo que el motor consulta."""

    def __init__(self) -> None:
        self.preparado = False
        self.cerrado = False

    async def preparar(self) -> None:
        self.preparado = True

    async def close(self) -> None:
        self.cerrado = True


class CerebroFalso:
    def __init__(self) -> None:
        self.provider = ProveedorFalso()
        self.mensajes: list[str] = []

    async def procesar_mensaje_streaming(self, usuario: str, texto: str):
        self.mensajes.append(texto)
        yield "hola"


class MotorDePrueba(MotorNiu):
    """Motor sin micrófono, sin STT, sin VTS y con un cerebro que no piensa."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**{"permitir_teclado": True, **kwargs})
        self.brain = CerebroFalso()
        self.hablado: list[str] = []
        self.vts_conectado = False

    def _crear_brain(self) -> CerebroFalso:
        return self.brain

    def _buscar_mic(self, nombre: str) -> None:
        return None

    def _crear_stt(self):
        return None

    async def _conectar_vts(self) -> None:
        self.vts_conectado = True

    async def _cerrar_vts(self) -> None:
        self.vts_conectado = False

    async def _hablar(self, texto: str, tiempos: dict[str, float]) -> None:
        """Turno instantáneo: sin Edge-TTS ni audio, pero con el stream real."""
        self.hablado.append(texto)
        self._cambiar_estado(HABLANDO)
        async for _ in self._fragmentos(texto):
            pass
        await asyncio.sleep(0)      # deja hueco a una cancelación
        self._emitir("respuesta", texto="hola")
        self._emitir("metricas", tiempos=dict(tiempos))


class MotorQueHablaSinParar(MotorDePrueba):
    """Se queda hablando hasta que alguien lo cancela."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.empezo = asyncio.Event()

    async def _hablar(self, texto: str, tiempos: dict[str, float]) -> None:
        self.hablado.append(texto)
        self._cambiar_estado(HABLANDO)
        self.empezo.set()
        await asyncio.sleep(3600)


class MotorQueSoloEscucha(MotorDePrueba):
    """Bucle que nunca recibe nada: sirve para probar paradas."""

    async def _escuchar(self):
        await asyncio.Event().wait()


def entrada(monkeypatch, respuestas: list[str]) -> None:
    """Sustituye el teclado por una lista de respuestas."""
    pendientes = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda *a: next(pendientes))


def recolectar(motor: MotorNiu) -> list[tuple[str, dict]]:
    eventos: list[tuple[str, dict]] = []
    motor.suscribir(lambda tipo, datos: eventos.append((tipo, datos)))
    return eventos


def estados(eventos: list[tuple[str, dict]]) -> list[str]:
    return [datos["estado"] for tipo, datos in eventos if tipo == "estado"]


# ─── Arranque y parada ────────────────────────────────────────────────


async def test_iniciar_avisa_del_perfil_y_termina_en_apagado(monkeypatch):
    entrada(monkeypatch, ["salir"])
    motor = MotorDePrueba()
    eventos = recolectar(motor)

    await motor.iniciar()
    assert motor.en_marcha
    await motor.esperar()
    await motor.detener()

    tipos = [tipo for tipo, _ in eventos]
    assert "perfil" in tipos
    assert estados(eventos)[0] == "iniciando"
    assert ESCUCHANDO in estados(eventos)
    assert motor.estado == APAGADO
    # El turno de «salir» no debe llegar al cerebro.
    assert motor.hablado == []


async def test_un_turno_pasa_por_pensando_y_hablando(monkeypatch):
    entrada(monkeypatch, ["hola", "salir"])
    motor = MotorDePrueba()
    eventos = recolectar(motor)

    await motor.iniciar()
    await motor.esperar()
    await motor.detener()

    assert motor.hablado == ["hola"]
    assert motor.brain.mensajes == ["hola"]
    tipos = [tipo for tipo, _ in eventos]
    for esperado in ("respuesta_inicio", "fragmento", "respuesta", "metricas"):
        assert esperado in tipos

    recorrido = estados(eventos)
    assert PENSANDO in recorrido
    assert HABLANDO in recorrido
    assert recorrido.index(PENSANDO) < recorrido.index(HABLANDO)


async def test_iniciar_dos_veces_no_crea_dos_bucles():
    motor = MotorQueSoloEscucha()
    await motor.iniciar()
    tarea = motor._tarea

    await motor.iniciar()

    assert motor._tarea is tarea
    await motor.detener()


async def test_detener_cancela_el_bucle_y_cierra_el_proveedor():
    motor = MotorQueSoloEscucha()
    await motor.iniciar()

    await motor.detener()

    assert not motor.en_marcha
    assert motor.estado == APAGADO
    assert motor.brain.provider.cerrado is True
    assert motor.vts_conectado is False


async def test_detener_un_motor_que_nunca_arranco_no_falla():
    motor = MotorDePrueba()

    await motor.detener()

    assert motor.estado == APAGADO


async def test_sin_microfono_ni_teclado_no_arranca_y_avisa(monkeypatch):
    motor = MotorDePrueba(permitir_teclado=False)
    eventos = recolectar(motor)

    await motor.iniciar()

    assert not motor.en_marcha
    assert motor.estado == APAGADO
    assert any(tipo == "error" for tipo, _ in eventos)
    assert motor.brain.provider.cerrado is True


# ─── «Detener voz» no es «detener motor» ──────────────────────────────


async def test_detener_voz_corta_el_turno_y_sigue_escuchando(monkeypatch):
    entrada(monkeypatch, ["hola", "salir"])
    motor = MotorQueHablaSinParar()
    eventos = recolectar(motor)

    await motor.iniciar()
    await asyncio.wait_for(motor.empezo.wait(), timeout=2)
    assert motor.estado == HABLANDO

    await motor.detener_voz()

    assert any(tipo == "sistema" and "Voz detenida" in datos["mensaje"]
               for tipo, datos in eventos)
    # Callar la voz no cierra nada: el avatar y el motor siguen vivos.
    assert motor.en_marcha
    assert motor.vts_conectado is True

    # Y el bucle siguió: leyó «salir» y terminó solo, no lo mató nadie.
    await asyncio.wait_for(motor.esperar(), timeout=2)
    assert motor.estado == APAGADO

    await motor.detener()


async def test_detener_voz_sin_voz_en_curso_no_hace_nada():
    motor = MotorQueSoloEscucha()
    await motor.iniciar()

    await motor.detener_voz()

    assert motor.en_marcha
    await motor.detener()


# ─── Eventos ──────────────────────────────────────────────────────────


def test_el_estado_no_se_emite_si_no_cambia():
    motor = MotorDePrueba()
    eventos = recolectar(motor)

    motor._cambiar_estado(APAGADO)      # ya estaba: no debe avisar
    motor._cambiar_estado(ESCUCHANDO)
    motor._cambiar_estado(ESCUCHANDO)

    assert estados(eventos) == [ESCUCHANDO]


def test_un_oyente_roto_no_impide_que_los_demas_reciban():
    motor = MotorDePrueba()
    recibidos: list[str] = []

    def roto(tipo: str, datos: dict) -> None:
        raise RuntimeError("panel roto")

    motor.suscribir(roto)
    motor.suscribir(lambda tipo, datos: recibidos.append(tipo))

    motor._emitir("sistema", mensaje="hola")

    assert recibidos == ["sistema"]


def test_desuscribir_deja_de_recibir():
    motor = MotorDePrueba()
    recibidos: list[str] = []
    quitar = motor.suscribir(lambda tipo, datos: recibidos.append(tipo))

    motor._emitir("sistema", mensaje="uno")
    quitar()
    motor._emitir("sistema", mensaje="dos")

    assert recibidos == ["sistema"]
