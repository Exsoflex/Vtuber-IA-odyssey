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
import time

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
        self.hotkeys: list[dict] | None = None
        self.hotkeys_disparados: list[str] = []
        self.hotkey_falla = False

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

    async def _listar_hotkeys(self) -> list[dict]:
        return self.hotkeys

    async def _disparar_hotkey(self, nombre: str) -> bool:
        self.hotkeys_disparados.append(nombre)
        return not self.hotkey_falla

    async def _hablar(self, texto: str, tiempos: dict[str, float],
                      turno: int = 0) -> None:
        """Turno instantáneo: sin Edge-TTS ni audio, pero con el stream real."""
        self.hablado.append(texto)
        self._cambiar_estado(HABLANDO)
        async for _ in self._fragmentos(texto, turno):
            pass
        await asyncio.sleep(0)      # deja hueco a una cancelación
        self._emitir("respuesta", texto="hola", turno=turno)
        self._emitir("metricas", tiempos=dict(tiempos), turno=turno)


class MotorQueHablaSinParar(MotorDePrueba):
    """Se queda hablando hasta que alguien lo cancela."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.empezo = asyncio.Event()

    async def _hablar(self, texto: str, tiempos: dict[str, float],
                      turno: int = 0) -> None:
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


async def esperar_hasta(condicion, timeout: float = 2.0) -> None:
    """Espera a que se cumpla una condición sin dormir un tiempo fijo."""
    limite = time.monotonic() + timeout
    while not condicion():
        assert time.monotonic() < limite, "la condición no se cumplió a tiempo"
        await asyncio.sleep(0.01)


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


# ─── Entrada de texto (chat del panel) ────────────────────────────────


async def test_sin_microfono_el_texto_del_panel_arranca_el_motor():
    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)
    await motor.iniciar()

    assert motor.en_marcha
    assert motor.enviar_texto("hola") is True

    await esperar_hasta(lambda: motor.brain.mensajes == ["hola"])
    assert motor.hablado == ["hola"]

    await motor.detener()


async def test_enviar_texto_con_el_motor_apagado_no_hace_nada():
    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)

    assert motor.enviar_texto("hola") is False


async def test_el_texto_vacio_no_se_acepta():
    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)
    await motor.iniciar()

    assert motor.enviar_texto("   ") is False
    assert motor.enviar_texto("") is False

    await motor.detener()


async def test_un_motor_sin_entrada_de_texto_lo_rechaza(monkeypatch):
    entrada(monkeypatch, ["salir"])
    motor = MotorDePrueba()      # teclado sí, texto no

    assert motor.enviar_texto("hola") is False


async def test_el_texto_del_chat_no_cierra_la_sesion():
    """«adiós» escrito en el panel es una frase, no la orden de apagar."""
    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)
    await motor.iniciar()

    assert motor.enviar_texto("adios") is True
    await esperar_hasta(lambda: motor.hablado == ["adios"])

    assert motor.en_marcha
    await motor.detener()


async def test_los_eventos_del_turno_llevan_numero():
    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)
    eventos = recolectar(motor)
    await motor.iniciar()

    motor.enviar_texto("uno")
    await esperar_hasta(lambda: motor.hablado == ["uno"])
    motor.enviar_texto("dos")
    await esperar_hasta(lambda: motor.hablado == ["uno", "dos"])
    await esperar_hasta(
        lambda: sum(1 for tipo, _ in eventos if tipo == "respuesta") == 2
    )

    await motor.detener()

    turnos = {
        tipo: [datos.get("turno") for t, datos in eventos if t == tipo]
        for tipo in ("respuesta_inicio", "fragmento", "respuesta", "metricas")
    }
    assert turnos["respuesta_inicio"] == [1, 2]
    assert set(turnos["fragmento"]) == {1, 2}
    assert turnos["respuesta"] == [1, 2]
    assert turnos["metricas"] == [1, 2]


async def test_un_turno_sin_audio_avisa_en_el_chat(monkeypatch):
    """Edge-TTS falla a veces (es un servicio en la nube): que no sea en silencio."""
    async def sin_audio(fragmentos, archivo, medidas=None, al_hablar=None):
        async for _ in fragmentos:
            pass
        return "hola"       # texto sí, pero ninguna parte de audio

    monkeypatch.setattr("core.motor.hablar_por_partes", sin_audio)
    # El doble de pruebas sustituye `_hablar` entero; aquí hace falta el real,
    # que es el que decide avisar cuando no sonó nada.
    monkeypatch.setattr(MotorDePrueba, "_hablar", MotorNiu._hablar)

    motor = MotorDePrueba(permitir_teclado=False, permitir_texto=True)
    eventos = recolectar(motor)
    await motor.iniciar()

    motor.enviar_texto("hola")
    await esperar_hasta(
        lambda: any(tipo == "respuesta" for tipo, _ in eventos)
    )

    await motor.detener()

    assert any("no tiene audio" in datos["mensaje"]
               for tipo, datos in eventos if tipo == "sistema")


async def test_cancelar_una_respuesta_avisa_del_turno(monkeypatch):
    entrada(monkeypatch, ["hola", "salir"])
    motor = MotorQueHablaSinParar()
    eventos = recolectar(motor)

    await motor.iniciar()
    await asyncio.wait_for(motor.empezo.wait(), timeout=2)

    await motor.detener_voz()

    canceladas = [datos for tipo, datos in eventos
                  if tipo == "respuesta_cancelada"]
    assert canceladas == [{"turno": 1}]

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


# ─── Expresiones y hotkeys ─────────────────────────────────────────────


async def test_el_tono_de_la_respuesta_elige_el_hotkey():
    """Cada emoción pide su hotkey por su nombre exacto."""
    casos = [
        ("¡Qué bien, estoy feliz!", "MouthSmile"),
        ("¡Vaya, qué sorpresa!", "MouthOpen"),
        ("Me siento triste :(", "MouthFrown"),
        ("¡Me da mucho enojo! >:(", "MouthAngry"),
    ]

    for respuesta, esperado in casos:
        motor = MotorDePrueba()
        await motor._expresar(respuesta)
        assert motor.hotkeys_disparados == [esperado], respuesta


async def test_una_respuesta_neutra_no_pide_expresion():
    motor = MotorDePrueba()

    await motor._expresar("La temperatura de hoy es de 22 grados.")

    assert motor.hotkeys_disparados == []


async def test_al_arrancar_avisa_de_los_hotkeys_que_faltan():
    """El hotkey es un contrato: si falta, hay que decirlo, no fallar en silencio."""
    motor = MotorDePrueba()
    motor.hotkeys = [{"name": "MouthSmile", "type": "ToggleExpression"}]
    eventos = recolectar(motor)

    await motor.iniciar()
    await motor.detener()

    avisos = [d["mensaje"] for t, d in eventos
              if t == "sistema" and "hotkeys" in d["mensaje"]]
    assert len(avisos) == 1
    # Los que faltan son los tres; el que sí tiene aparece como «lo que hay».
    faltan = avisos[0].split(". ")[0]
    assert "MouthOpen" in faltan
    assert "MouthFrown" in faltan
    assert "MouthAngry" in faltan
    assert "MouthSmile" not in faltan
    assert "El modelo tiene: MouthSmile" in avisos[0]


async def test_si_el_modelo_tiene_todos_los_hotkeys_no_avisa():
    motor = MotorDePrueba()
    motor.hotkeys = [{"name": n, "type": "ToggleExpression"}
                     for n in ("MouthSmile", "MouthOpen",
                               "MouthFrown", "MouthAngry")]
    eventos = recolectar(motor)

    await motor.iniciar()
    await motor.detener()

    assert not any("hotkeys" in d["mensaje"]
                   for t, d in eventos if t == "sistema")


async def test_un_modelo_sin_ningun_hotkey_tambien_se_avisa():
    """Lista vacía es un dato, no un «no se pudo comprobar»: hay que avisar."""
    motor = MotorDePrueba()
    motor.hotkeys = []
    eventos = recolectar(motor)

    await motor.iniciar()
    await motor.detener()

    avisos = [d["mensaje"] for t, d in eventos
              if t == "sistema" and "hotkeys" in d["mensaje"]]
    assert len(avisos) == 1
    assert "ningún hotkey" in avisos[0]


async def test_sin_modelo_cargado_no_se_avisa_de_nada():
    """`None` es «no hay modelo», y eso no es un fallo del modelo."""
    motor = MotorDePrueba()
    motor.hotkeys = None
    eventos = recolectar(motor)

    await motor.iniciar()
    await motor.detener()

    assert not any("hotkeys" in d["mensaje"]
                   for t, d in eventos if t == "sistema")


async def test_un_hotkey_que_falla_se_avisa_una_sola_vez():
    """Un aviso por hotkey: si no, el chat se llena de lo mismo."""
    motor = MotorDePrueba()
    motor.hotkey_falla = True
    eventos = recolectar(motor)

    await motor._expresar("estoy feliz")
    await motor._expresar("qué bien, alegre")

    avisos = [d["mensaje"] for t, d in eventos
              if t == "sistema" and "MouthSmile" in d["mensaje"]]
    assert len(avisos) == 1
