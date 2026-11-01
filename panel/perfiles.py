"""
Perfiles desde el punto de vista del panel.

`core/perfiles.py` sabe guardar y leer el archivo; aquí se conecta con la
configuración viva (`config.json`) y se prepara lo que necesita la interfaz:

- activar un perfil = validar sus ajustes, aplicarlos y marcarlo como activo;
- guardar ajustes = copiarlos también al perfil activo;
- al arrancar, el perfil activo manda sobre la copia de `config.json`.

Así el archivo de perfiles es la fuente de verdad del panel y `config.json`
sigue siendo la copia que leen la CLI y los módulos que no conocen perfiles.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core import config, perfiles as almacen
from core.personalidad import INSTRUCCION_POR_DEFECTO


def _reinicio(antes: config.Ajustes, despues: config.Ajustes) -> list[str]:
    return sorted(
        campo for campo in config.CAMPOS_FRIOS
        if getattr(antes, campo) != getattr(despues, campo)
    )


def _aplicar(perfil: almacen.Perfil) -> tuple[config.Ajustes, list[str], list[str]]:
    """Valida y activa los ajustes de un perfil sobre la configuración viva."""
    antes = config.ajustes()
    nuevos, avisos = config.normalizar(perfil.ajustes)
    config.guardar_ajustes(nuevos)
    config.fijar_ajustes(nuevos)
    return nuevos, avisos, _reinicio(antes, nuevos)


def estado(
    *,
    avisos: list[str] | None = None,
    requiere_reinicio: list[str] | None = None,
) -> dict[str, Any]:
    """Todo lo que la tarjeta de perfiles necesita en una sola respuesta."""
    lista, activo_id = almacen.listar()
    actual = next(perfil for perfil in lista if perfil.id == activo_id)
    return {
        "activo": actual.id,
        "nombre": actual.nombre,
        "perfiles": [{"id": p.id, "nombre": p.nombre} for p in lista],
        "instruccion": actual.instruccion,
        "defecto_instruccion": INSTRUCCION_POR_DEFECTO,
        "valores": asdict(config.ajustes()),
        "avisos": avisos or [],
        "requiere_reinicio": requiere_reinicio or [],
    }


def aplicar_activo() -> dict[str, Any]:
    """Al arrancar el panel: el perfil activo vuelve a mandar.

    Si `perfiles.json` todavía no existe, se crea con los ajustes que ya haya
    en `config.json`. Es la migración de un panel sin perfiles, sin pedirle
    nada al usuario.
    """
    lista, activo_id = almacen.listar()
    actual = next(perfil for perfil in lista if perfil.id == activo_id)

    antes = config.ajustes()
    nuevos, avisos = config.normalizar(actual.ajustes)
    if asdict(antes) != asdict(nuevos):
        config.guardar_ajustes(nuevos)
        config.fijar_ajustes(nuevos)

    # Persistir el perfil inicial aunque no haya cambios: así la instrucción
    # ya se puede editar y el archivo existe desde el primer arranque.
    if not almacen.RUTA_PERFILES.exists():
        almacen.fijar_activo(activo_id)

    return estado(avisos=avisos, requiere_reinicio=_reinicio(antes, nuevos))


def activar(perfil_id: str) -> dict[str, Any]:
    """Cambia de perfil: aplica sus ajustes y lo deja como activo."""
    perfil = almacen.obtener(perfil_id)
    # Primero se marca como activo: si escribir `config.json` fallara, al
    # volver a abrir el panel el perfil elegido se aplicaría igualmente.
    almacen.fijar_activo(perfil_id)
    _nuevos, avisos, reinicio = _aplicar(perfil)
    return estado(avisos=avisos, requiere_reinicio=reinicio)


def crear(nombre: str, *, duplicar: bool = False) -> dict[str, Any]:
    """Crea un perfil. Con `duplicar`, copia el activo; si no, parte de fábrica."""
    if duplicar:
        base = almacen.activo()
        perfil = almacen.crear(
            nombre,
            ajustes=base.ajustes,
            instruccion=base.instruccion,
        )
    else:
        perfil = almacen.crear(
            nombre,
            ajustes=asdict(config.por_defecto()),
            instruccion=INSTRUCCION_POR_DEFECTO,
        )

    resultado = activar(perfil.id)
    resultado["avisos"].insert(0, f"Perfil «{perfil.nombre}» creado y activado.")
    return resultado


def renombrar(perfil_id: str, nombre: str) -> dict[str, Any]:
    perfil = almacen.renombrar(perfil_id, nombre)
    resultado = estado()
    resultado["avisos"].append(f"Perfil renombrado a «{perfil.nombre}».")
    return resultado


def eliminar(perfil_id: str) -> dict[str, Any]:
    """Borra un perfil. Si era el activo, aplica el que queda."""
    borrado = almacen.obtener(perfil_id)
    nuevo_activo, era_activo = almacen.eliminar(perfil_id)

    resultado = activar(nuevo_activo) if era_activo else estado()
    if era_activo:
        resultado["avisos"].append(
            f"Perfil «{borrado.nombre}» eliminado; ahora está activo "
            f"«{resultado['nombre']}»."
        )
    else:
        resultado["avisos"].append(f"Perfil «{borrado.nombre}» eliminado.")
    return resultado


def guardar_instruccion(perfil_id: str, instruccion: str) -> dict[str, Any]:
    """Guarda el prompt del perfil. Se aplica en el turno siguiente."""
    almacen.guardar_instruccion(perfil_id, instruccion)
    resultado = estado()
    resultado["avisos"].append("Instrucción guardada. Se aplica en el siguiente turno.")
    return resultado
