"""
Panel de control de Niu: aplicación FastAPI servida en 127.0.0.1.

Por qué una web local y no una aplicación de escritorio: el navegador ya es el
renderizador, el CSS moderno sale gratis y el panel comparte el bucle de
`asyncio` con el motor. No hay IPC ni dos procesos que se puedan desincronizar.

Qué hace ahora: arrancar y parar el motor, callar la voz, mostrar el estado de
las piezas que pueden fallar (Ollama, VTube Studio, micrófono, TTS), mantener
el chat de la sesión y editar los ajustes de Niu. El chat llega por dos caminos
que no compiten:

- `POST /api/mensaje` para escribirle a Niu.
- `/ws` para que el servidor empuje los mensajes según se producen. Sin
  WebSocket habría que preguntar cada segundo y el texto de Niu llegaría a
  saltos, justo lo que el streaming evita.

El historial vive en `panel/chat.py`; aquí solo se conectan las piezas.

Una regla que se mantiene: la interfaz **no** copia lógica del motor. `MotorNiu`
sigue siendo el único que sabe conversar; aquí solo se le pide que arranque o
pare, se lee su estado y se le pasa texto.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config, tts
from core.audio_devices import buscar_dispositivo
from core.idiomas import tono_activo, voz_activa
from core.motor import MotorNiu
from core.perfiles import InstruccionInvalida, NombreInvalido, PerfilNoExiste, PerfilUnico
from core.vts_client import vts_client
from panel import perfiles as panel_perfiles
from panel.ajustes import (
    MotorOcupado,
    URL_OLLAMA,
    aplicar_ajustes,
    descripcion_ajustes,
    listar_dispositivos,
    listar_modelos,
    probar_voz,
    restaurar_ajustes,
)
from panel.chat import Historial

ESTATICOS = Path(__file__).resolve().parent / "static"


class MensajeEntrante(BaseModel):
    """Cuerpo de `POST /api/mensaje`: lo que el usuario escribe en el chat."""

    texto: str = ""


class PruebaVoz(BaseModel):
    """Valores para oír la voz **antes** de guardarlos. Todo opcional: lo que
    falta se toma de los ajustes guardados."""

    voz: str | None = None
    tono: str | None = None
    velocidad: str | None = None
    idioma: str | None = None


class NuevoPerfil(BaseModel):
    """`POST /api/perfiles`: nombre y si se copia el perfil activo."""

    nombre: str = ""
    duplicar: bool = False


class NombrePerfil(BaseModel):
    nombre: str = ""


class InstruccionPerfil(BaseModel):
    instruccion: str = ""


# ─── Comprobaciones de estado ──────────────────────────────────────────


async def _ollama_disponible(cliente: httpx.AsyncClient) -> bool:
    """¿Contesta Ollama? Es el fallo que deja a Niu muda pero viva."""
    try:
        respuesta = await cliente.get(URL_OLLAMA)
        return respuesta.status_code == 200
    except Exception:
        return False


def _microfono_disponible(nombre: str) -> bool:
    """Buscar un dispositivo abre el host de audio: se hace en un hilo."""
    try:
        return buscar_dispositivo(nombre, salida=False) is not None
    except Exception:
        return False


async def _chips(app: FastAPI) -> dict[str, Any]:
    motor: MotorNiu = app.state.motor
    ajustes = config.ajustes()
    return {
        "motor": motor.estado,
        "ollama": await _ollama_disponible(app.state.http),
        "vts": vts_client.connected,
        "microfono": await asyncio.to_thread(
            _microfono_disponible, ajustes.microfono
        ),
        "tts": tts.EDGE_TTS_AVAILABLE,
    }


# ─── Arranque en segundo plano ─────────────────────────────────────────


async def _arrancar_motor(app: FastAPI) -> None:
    """Arranca el motor y, si falla, deja el panel vivo y el motivo a la vista.

    El arranque carga modelos (segundos), así que no se hace dentro de la
    petición: el navegador vería la petición colgada y parecería roto.
    """
    app.state.ultimo_error = None
    try:
        await app.state.motor.iniciar()
    except Exception as e:
        app.state.ultimo_error = f"{type(e).__name__}: {e}"
        # Un motor a medio arrancar retiene el modelo o el socket de VTS.
        with contextlib.suppress(Exception):
            await app.state.motor.detener()


def _estado(motor: MotorNiu) -> dict[str, Any]:
    return {"estado": motor.estado, "en_marcha": motor.en_marcha}


# ─── Aplicación ────────────────────────────────────────────────────────


def crear_app() -> FastAPI:
    """Construye la app. Es una función para que los tests usen otra instancia."""

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        # El perfil activo manda antes de crear el motor: este captura idioma,
        # modelos y micrófono al arrancar. Si el archivo de perfiles estuviera
        # roto, se sigue con `config.json` en vez de dejar el panel sin abrir.
        try:
            panel_perfiles.aplicar_activo()
        except Exception as e:      # pragma: no cover - defensa de arranque
            print(f"[PERFILES] No se pudo aplicar el perfil activo: {e}")

        # permitir_texto: el panel puede escribirle a Niu aunque no haya
        # micrófono. El teclado sigue apagado porque `input()` no se puede
        # cancelar desde el botón Detener.
        app.state.motor = MotorNiu(permitir_teclado=False, permitir_texto=True)
        app.state.arranque = None
        app.state.ultimo_error = None
        app.state.http = httpx.AsyncClient(timeout=0.6)
        app.state.historial = Historial(metadatos={
            "idioma": config.ajustes().idioma,
            "voz": voz_activa(),
        })
        app.state.motor.suscribir(app.state.historial.procesar)
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                await app.state.motor.detener()
            await app.state.http.aclose()

    app = FastAPI(title="Niu", docs_url=None, redoc_url=None, lifespan=ciclo)

    app.mount("/estaticos", StaticFiles(directory=ESTATICOS), name="estaticos")

    @app.get("/", include_in_schema=False)
    async def raiz() -> FileResponse:
        return FileResponse(ESTATICOS / "index.html")

    @app.get("/api/estado")
    async def estado() -> dict[str, Any]:
        motor: MotorNiu = app.state.motor
        perfil = config.ajustes()
        return {
            **_estado(motor),
            "idioma": perfil.idioma,
            "voz": voz_activa(),
            "tono": tono_activo(),
            "error": app.state.ultimo_error,
            "chips": await _chips(app),
        }

    @app.post("/api/motor/iniciar")
    async def iniciar() -> dict[str, Any]:
        motor: MotorNiu = app.state.motor
        tarea = app.state.arranque
        if not motor.en_marcha and (tarea is None or tarea.done()):
            app.state.arranque = asyncio.create_task(_arrancar_motor(app))
            # Un turno de más para que la tarea empiece y el estado «iniciando»
            # ya sea visible en la respuesta, en vez de «apagado» un instante.
            await asyncio.sleep(0)
        return _estado(motor)

    @app.post("/api/motor/detener")
    async def detener() -> dict[str, Any]:
        app.state.ultimo_error = None
        await app.state.motor.detener()
        return _estado(app.state.motor)

    @app.post("/api/motor/detener-voz")
    async def detener_voz() -> dict[str, Any]:
        await app.state.motor.detener_voz()
        return _estado(app.state.motor)

    # ─── Chat ──────────────────────────────────────────────────────────

    @app.get("/api/sesion")
    async def sesion() -> dict[str, Any]:
        return app.state.historial.snapshot()

    @app.post("/api/sesion/limpiar")
    async def limpiar_sesion() -> dict[str, Any]:
        app.state.historial.limpiar()
        return app.state.historial.snapshot()

    @app.get("/api/sesion/exportar")
    async def exportar_sesion() -> Response:
        historial: Historial = app.state.historial
        return Response(
            content=historial.exportar_markdown(),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{historial.ruta.stem}.md"'
            },
        )

    @app.post("/api/mensaje")
    async def mensaje(entrada: MensajeEntrante) -> dict[str, Any]:
        """Acepta un mensaje escrito y lo deja en la cola del motor.

        La respuesta no espera a que Niu conteste: el motor avisará por
        WebSocket cuando empiece y cuando termine.
        """
        motor: MotorNiu = app.state.motor
        texto = entrada.texto.strip()
        if not texto:
            raise HTTPException(status_code=400, detail="El mensaje está vacío.")
        if not motor.en_marcha:
            raise HTTPException(status_code=409,
                                detail="El motor no está en marcha.")
        if not motor.enviar_texto(texto):
            raise HTTPException(status_code=409,
                                detail="No se pudo enviar el mensaje.")

        # El texto escrito no pasa por el micro ni por el STT, así que el motor
        # no lo emite como `transcripcion`: se añade aquí, justo después de
        # aceptarlo, para que aparezca en el chat sin esperar al turno.
        app.state.historial.agregar_usuario(texto)
        return {"aceptado": True}

    @app.websocket("/ws")
    async def chat(websocket: WebSocket) -> None:
        """Empuja el chat en vivo: historial al conectar y un evento por cambio."""
        await websocket.accept()
        historial: Historial = app.state.historial
        cola = historial.suscribir()
        try:
            await websocket.send_json(historial.snapshot())
            while True:
                await websocket.send_json(await cola.get())
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            # El navegador se cerró o recargó: nada que avisar.
            pass
        finally:
            historial.desuscribir(cola)

    # ─── Ajustes ───────────────────────────────────────────────────────

    @app.get("/api/ajustes")
    async def obtener_ajustes() -> dict[str, Any]:
        return descripcion_ajustes()

    @app.put("/api/ajustes")
    async def guardar_ajustes(cambios: dict[str, Any]) -> dict[str, Any]:
        """Valida, guarda en `config.json` y devuelve avisos y pendientes.

        No devuelve 422 ante un valor raro: se corrige con aviso, igual que
        hace `core/config.py` al arrancar. Rechazar dejaría la interfaz sin
        saber qué hacer con el resto del formulario.
        """
        if not cambios:
            raise HTTPException(status_code=400,
                                detail="No hay cambios que guardar.")
        return aplicar_ajustes(cambios)

    @app.post("/api/ajustes/restablecer")
    async def restablecer_ajustes() -> dict[str, Any]:
        return restaurar_ajustes()

    @app.post("/api/ajustes/probar-voz")
    async def probar_la_voz(prueba: PruebaVoz) -> dict[str, Any]:
        """Oye la voz con los valores del formulario, sin guardar nada."""
        try:
            return await probar_voz(
                app.state.motor,
                voz=prueba.voz or None,
                tono=prueba.tono or None,
                velocidad=prueba.velocidad or None,
                idioma=prueba.idioma or None,
            )
        except MotorOcupado as e:
            raise HTTPException(status_code=409, detail=str(e)) from None

    # ─── Perfiles ──────────────────────────────────────────────────────

    @app.get("/api/perfiles")
    async def obtener_perfiles() -> dict[str, Any]:
        return panel_perfiles.estado()

    @app.post("/api/perfiles")
    async def crear_perfil(entrada: NuevoPerfil) -> dict[str, Any]:
        try:
            return panel_perfiles.crear(entrada.nombre, duplicar=entrada.duplicar)
        except NombreInvalido as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.put("/api/perfiles/{perfil_id}")
    async def renombrar_perfil(perfil_id: str,
                               entrada: NombrePerfil) -> dict[str, Any]:
        try:
            return panel_perfiles.renombrar(perfil_id, entrada.nombre)
        except PerfilNoExiste as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except NombreInvalido as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.delete("/api/perfiles/{perfil_id}")
    async def borrar_perfil(perfil_id: str) -> dict[str, Any]:
        try:
            return panel_perfiles.eliminar(perfil_id)
        except PerfilNoExiste as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except PerfilUnico as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.post("/api/perfiles/{perfil_id}/activar")
    async def activar_perfil(perfil_id: str) -> dict[str, Any]:
        try:
            return panel_perfiles.activar(perfil_id)
        except PerfilNoExiste as e:
            raise HTTPException(status_code=404, detail=str(e)) from None

    @app.put("/api/perfiles/{perfil_id}/instruccion")
    async def guardar_instruccion(perfil_id: str,
                                  entrada: InstruccionPerfil) -> dict[str, Any]:
        try:
            return panel_perfiles.guardar_instruccion(perfil_id, entrada.instruccion)
        except PerfilNoExiste as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except InstruccionInvalida as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.get("/api/dispositivos")
    async def dispositivos() -> dict[str, Any]:
        return await listar_dispositivos()

    @app.get("/api/modelos")
    async def modelos_llm() -> dict[str, Any]:
        return await listar_modelos(app.state.http)

    return app
