"""
Historial del chat de Niu: mensajes, archivo de sesión y exportación.

Por qué existe
--------------
El motor no sabe de burbujas ni de archivos: emite hechos (`respuesta_inicio`,
`fragmento`, `respuesta`...). Alguien tiene que convertirlos en mensajes con
principio y final, guardarlos y repartirlos entre las pestañas abiertas. Eso es
esta clase.

Decisiones que conviene entender
--------------------------------
1. **Un mensaje de Niu se abre al empezar y se cierra al terminar.** El motor
   entrega la respuesta a trozos; el chat crea el globo vacío en
   `respuesta_inicio`, le añade texto en cada `fragmento` y lo marca como
   completo en `respuesta`. Así el texto se ve al mismo ritmo que suena.

2. **Los turnos llevan número.** Si Niu se calla a mitad (`respuesta_cancelada`),
   el globo se cierra con lo que había y se marca como interrumpido. Sin número
   habría que adivinar a qué mensaje pertenece cada evento.

3. **El archivo se escribe al cerrar cada mensaje, no en cada fragmento.**
   Reescribir el JSON por cada palabra sería tirar disco en cada turno; y un
   fragmento suelto no aporta nada si el proceso muere, porque la sesión
   siguiente empieza de cero.

4. **El mensaje del usuario lo añade quien lo envía, no el motor.** El texto
   escrito en el panel ya lo conoce el panel y no se emite como
   `transcripcion`; si se emitiera, el mensaje saldría duplicado. Lo que sí
   viene del micrófono se traduce desde `transcripcion`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Las sesiones viven junto al proyecto, no en el directorio de instalación del
# paquete: son datos del usuario y no deben perderse al actualizar el código.
CARPETA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "sesiones"


def _segundos(valor: Any) -> str:
    """Formatea un tiempo del motor como «1,23 s» (una sola cifra decimal)."""
    try:
        return f"{float(valor):.2f} s"
    except (TypeError, ValueError):
        return "—"


def resumen_metricas(tiempos: dict[str, Any]) -> str:
    """Resume la latencia de un turno en una línea legible.

    El número que importa es «primer sonido»: la suma de lo que se tarda en
    transcribir, tener la primera frase, sintetizarla y prepararla. Es lo que
    decide si la conversación se siente fluida. El resto son datos de apoyo.
    """
    hasta_sonido = sum(
        float(tiempos.get(clave) or 0.0)
        for clave in ("stt", "texto", "sintesis", "preparacion")
    )
    partes = [f"1er sonido {hasta_sonido:.2f} s"]
    # El STT no existe cuando el mensaje se escribió en el chat: no se inventa
    # un 0,00 s que parezca una medida.
    if "stt" in tiempos:
        partes.append(f"STT {_segundos(tiempos.get('stt'))}")
    if "texto" in tiempos:
        partes.append(f"1ª frase {_segundos(tiempos.get('texto'))}")
    partes.append(f"voz {_segundos(tiempos.get('voz'))}")
    if tiempos.get("partes"):
        cuantas = int(tiempos["partes"])
        partes.append("1 parte" if cuantas == 1 else f"{cuantas} partes")
    return " · ".join(partes)


class Historial:
    """Lista de mensajes de la sesión actual, persistida en un JSON.

    Es síncrona a propósito: el motor llama a `procesar()` desde el mismo bucle
    de `asyncio` que el panel, así que no hay dos hilos tocando la lista. Los
    archivos son pequeños y se escriben una vez por mensaje.
    """

    def __init__(
        self,
        carpeta: Path | str | None = None,
        metadatos: dict[str, Any] | None = None,
    ) -> None:
        # Se resuelve aquí y no en la firma para que los tests puedan apuntar
        # a una carpeta temporal sin ensuciar el proyecto.
        self.carpeta = Path(carpeta) if carpeta is not None else CARPETA_POR_DEFECTO
        self.metadatos = dict(metadatos or {})
        self.mensajes: list[dict[str, Any]] = []
        self.inicio = datetime.now()
        self.ruta = self._ruta_nueva(self.inicio)

        self._siguiente_id = 1
        self._niu: dict[str, Any] | None = None   # respuesta de Niu en curso
        self._oyentes: list[asyncio.Queue] = []

    # ─── Sesión y archivo ──────────────────────────────────────────────

    def _ruta_nueva(self, momento: datetime) -> Path:
        """Nombre de archivo libre para una sesión que empieza ahora."""
        base = momento.strftime("%Y-%m-%d_%H-%M-%S")
        ruta = self.carpeta / f"{base}.json"
        numero = 2
        while ruta.exists():
            ruta = self.carpeta / f"{base}_{numero}.json"
            numero += 1
        return ruta

    def _nombre_archivo(self) -> str:
        return f"{self.carpeta.name}/{self.ruta.name}"

    def snapshot(self) -> dict[str, Any]:
        """Todo lo necesario para pintar el chat al abrir o recargar."""
        return {
            "tipo": "historial",
            "inicio": self.inicio.isoformat(timespec="seconds"),
            "archivo": self._nombre_archivo(),
            "mensajes": list(self.mensajes),
        }

    def _guardar(self) -> None:
        """Vuelca la sesión a disco. Sin mensajes no hay archivo todavía."""
        if not self.mensajes:
            return
        self.carpeta.mkdir(parents=True, exist_ok=True)
        datos = {
            "inicio": self.inicio.isoformat(timespec="seconds"),
            **self.metadatos,
            "mensajes": self.mensajes,
        }
        self.ruta.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def limpiar(self) -> None:
        """Vacía la vista y empieza una sesión nueva sin borrar la anterior."""
        self.mensajes = []
        self._siguiente_id = 1
        self._niu = None
        self.inicio = datetime.now()
        self.ruta = self._ruta_nueva(self.inicio)
        self._difundir(self.snapshot())

    # ─── Reparto a los navegadores ─────────────────────────────────────

    def suscribir(self) -> asyncio.Queue:
        """Abre una cola de eventos; el WebSocket la consume y la cierra."""
        cola: asyncio.Queue = asyncio.Queue()
        self._oyentes.append(cola)
        return cola

    def desuscribir(self, cola: asyncio.Queue) -> None:
        with contextlib.suppress(ValueError):
            self._oyentes.remove(cola)

    def _difundir(self, evento: dict[str, Any]) -> None:
        for cola in list(self._oyentes):
            cola.put_nowait(evento)

    def _publicar(self, mensaje: dict[str, Any]) -> None:
        """Manda el estado actual de un mensaje; el navegador lo reemplaza."""
        self._difundir({"tipo": "mensaje", "mensaje": dict(mensaje)})

    # ─── Mensajes ──────────────────────────────────────────────────────

    def _nuevo(self, papel: str, texto: str, **extra: Any) -> dict[str, Any]:
        mensaje = {
            "id": self._siguiente_id,
            "papel": papel,
            "texto": texto,
            "hora": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        self._siguiente_id += 1
        self.mensajes.append(mensaje)
        return mensaje

    def agregar_usuario(self, texto: str) -> dict[str, Any] | None:
        """Añade lo que dijo o escribió el usuario. Vacío no se muestra."""
        limpio = (texto or "").strip()
        if not limpio:
            return None
        mensaje = self._nuevo("usuario", limpio)
        self._publicar(mensaje)
        self._guardar()
        return mensaje

    def agregar_sistema(self, texto: str) -> dict[str, Any] | None:
        """Avisos del motor (errores, voz detenida...) como nota en el chat."""
        limpio = (texto or "").strip()
        if not limpio:
            return None
        mensaje = self._nuevo("sistema", limpio)
        self._publicar(mensaje)
        self._guardar()
        return mensaje

    def _abrir_respuesta(self, turno: int, texto_usuario: str) -> None:
        # Si el turno anterior quedó abierto por algún camino raro, se cierra
        # antes de empezar otro: nunca hay dos globos «en curso».
        self._cerrar_en_curso()

        self._niu = self._nuevo(
            "niu", "", turno=turno, parcial=True, texto_usuario=texto_usuario
        )
        self._publicar(self._niu)

    def _agregar_fragmento(self, texto: str) -> None:
        if self._niu is None or not texto:
            return
        self._niu["texto"] += texto
        self._publicar(self._niu)

    def _cerrar_respuesta(self, turno: int, texto: str) -> None:
        if self._niu is None or self._niu.get("turno") != turno:
            # El panel pudo perder el inicio del turno (por ejemplo, al
            # reconectar). Si hay texto, se muestra igualmente.
            if not (texto or "").strip():
                return
            self._niu = self._nuevo("niu", texto, turno=turno, parcial=False)

        mensaje = self._niu
        self._niu = None
        if (texto or "").strip():
            mensaje["texto"] = texto
        mensaje["parcial"] = False
        self._publicar(mensaje)
        self._guardar()

    def _cancelar_respuesta(self, turno: int) -> None:
        """Cierra el globo de un turno cortado a mitad."""
        if self._niu is None:
            return
        if self._niu.get("turno") != turno:
            return

        mensaje = self._niu
        self._niu = None
        if not mensaje["texto"].strip():
            # No llegó a decir nada: un globo vacío solo estorba.
            self.mensajes[:] = [m for m in self.mensajes if m is not mensaje]
            self._difundir({"tipo": "quitar", "id": mensaje["id"]})
            return

        mensaje["parcial"] = False
        mensaje["interrumpida"] = True
        self._publicar(mensaje)
        self._guardar()

    def _poner_metricas(self, turno: int, tiempos: dict[str, Any]) -> None:
        for mensaje in reversed(self.mensajes):
            if mensaje.get("turno") == turno and mensaje["papel"] == "niu":
                mensaje["metricas"] = dict(tiempos)
                self._publicar(mensaje)
                self._guardar()
                return

    def _cerrar_en_curso(self) -> None:
        """Cierra el globo abierto, si lo hay, conservando su texto."""
        if self._niu is None:
            return
        mensaje = self._niu
        self._niu = None
        if not mensaje["texto"].strip():
            self.mensajes[:] = [m for m in self.mensajes if m is not mensaje]
            self._difundir({"tipo": "quitar", "id": mensaje["id"]})
            return
        mensaje["parcial"] = False
        mensaje["interrumpida"] = True
        self._publicar(mensaje)
        self._guardar()

    # ─── Puente con el motor ───────────────────────────────────────────

    def procesar(self, tipo: str, datos: dict[str, Any]) -> None:
        """Traduce un evento de `MotorNiu` a un cambio en el chat.

        Se suscribe tal cual: `motor.suscribir(historial.procesar)`.
        """
        if tipo == "transcripcion":
            self.agregar_usuario(datos.get("texto", ""))
        elif tipo == "respuesta_inicio":
            self._abrir_respuesta(
                int(datos.get("turno") or 0), datos.get("texto_usuario", "")
            )
        elif tipo == "fragmento":
            self._agregar_fragmento(datos.get("texto", ""))
        elif tipo == "respuesta":
            self._cerrar_respuesta(
                int(datos.get("turno") or 0), datos.get("texto", "")
            )
        elif tipo == "respuesta_cancelada":
            self._cancelar_respuesta(int(datos.get("turno") or 0))
        elif tipo == "metricas":
            self._poner_metricas(
                int(datos.get("turno") or 0), datos.get("tiempos") or {}
            )
        elif tipo == "error":
            self.agregar_sistema(datos.get("mensaje", "Error"))
        elif tipo == "sistema":
            self.agregar_sistema(datos.get("mensaje", ""))
        # `estado`, `parte` y `perfil` no son mensajes: los usa la cabecera.

    # ─── Exportación ───────────────────────────────────────────────────

    def exportar_markdown(self) -> str:
        """Sesión completa en Markdown, lista para guardar o releer."""
        lineas = [
            f"# Sesión de Niu — {self.inicio:%d/%m/%Y %H:%M}",
            "",
        ]
        for clave in ("idioma", "voz"):
            if self.metadatos.get(clave):
                lineas.append(f"- **{clave.capitalize()}:** {self.metadatos[clave]}")
        lineas.append("")

        for mensaje in self.mensajes:
            hora = mensaje.get("hora", "")[11:16]
            papel = mensaje.get("papel")
            if papel == "usuario":
                lineas.append(f"### Tú · {hora}")
                lineas.append("")
                lineas.append(mensaje["texto"])
            elif papel == "niu":
                titulo = "Niu"
                if mensaje.get("interrumpida"):
                    titulo += " (interrumpida)"
                lineas.append(f"### {titulo} · {hora}")
                lineas.append("")
                lineas.append(mensaje["texto"])
                if mensaje.get("metricas"):
                    lineas.append("")
                    lineas.append(f"_{resumen_metricas(mensaje['metricas'])}_")
            else:
                lineas.append(f"> **Sistema:** {mensaje['texto']}")
            lineas.append("")

        return "\n".join(lineas).rstrip() + "\n"
