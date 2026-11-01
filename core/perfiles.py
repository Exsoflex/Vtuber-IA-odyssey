"""
Perfiles de Niu: cada uno con sus ajustes y su instrucción de sistema.

Por qué JSON y no una base de datos
-----------------------------------
El panel es local, de un solo usuario y con un puñado de perfiles. SQLite
obligaría a un esquema, una capa de consultas y migraciones para guardar lo
mismo: una lista corta de objetos. El JSON ya se escribe de forma atómica en
`core/config.py` y se puede abrir con cualquier editor cuando algo salga mal.

Qué guarda un perfil
--------------------
- `ajustes`: una copia completa de `Ajustes` (voz, modelos, temperatura...).
  Guardar el objeto entero evita la pregunta "¿y este campo de dónde sale?".
- `instruccion`: el prompt de personalidad de ese perfil. Si está vacío, se usa
  el de fábrica (`core/personalidad.py`).

Quién manda
-----------
El perfil activo es la fuente de verdad del panel: al abrir el panel se aplica
sobre `config.json`, y al guardar ajustes se copian también al perfil activo.
`config.json` sigue existiendo porque la CLI y los módulos ya lo leen; es la
copia viva, no un segundo lugar donde configurar.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from core import config
from core.personalidad import INSTRUCCION_POR_DEFECTO

RUTA_PERFILES = Path(
    os.getenv("NIU_PERFILES") or Path(__file__).resolve().parent.parent / "perfiles.json"
)

VERSION = 1
MAX_NOMBRE = 40
MAX_INSTRUCCION = 20_000


class PerfilNoExiste(Exception):
    """El id pedido no está en `perfiles.json`."""


class PerfilUnico(Exception):
    """No se puede borrar el último perfil: Niu se quedaría sin configuración."""


class NombreInvalido(Exception):
    """Un perfil necesita un nombre que se pueda leer y mostrar."""


class InstruccionInvalida(Exception):
    """La instrucción no puede quedar vacía tras guardarla."""


@dataclass(frozen=True)
class Perfil:
    """Un conjunto de ajustes + personalidad con nombre propio."""

    id: str
    nombre: str
    instruccion: str
    ajustes: dict[str, Any]


# ─── Nombres e identificadores ─────────────────────────────────────────


def _limpiar_nombre(nombre: str) -> str:
    limpio = " ".join(str(nombre or "").split())
    if not limpio:
        raise NombreInvalido("El perfil necesita un nombre.")
    return limpio[:MAX_NOMBRE]


def _slug(nombre: str, usados: set[str]) -> str:
    """`Niu Espacial` -> `niu-espacial`, sin acentos y sin repetir."""
    normalizado = unicodedata.normalize("NFKD", nombre)
    ascii_ = normalizado.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "perfil"

    candidato = base
    numero = 2
    while candidato in usados:
        candidato = f"{base}-{numero}"
        numero += 1
    return candidato


# ─── Lectura y escritura ───────────────────────────────────────────────


def _perfil_por_defecto(usados: set[str] | None = None) -> Perfil:
    usados = usados or set()
    return Perfil(
        id=_slug("Niu", usados),
        nombre="Niu",
        instruccion=INSTRUCCION_POR_DEFECTO,
        ajustes=asdict(config.ajustes()),
    )


def _normalizar_perfil(datos: Any, usados: set[str]) -> Perfil | None:
    if not isinstance(datos, dict):
        return None

    try:
        nombre = _limpiar_nombre(datos.get("nombre") or "Perfil")
    except NombreInvalido:
        nombre = "Perfil"
    id_bruto = str(datos.get("id") or nombre).strip()
    perfil_id = _slug(id_bruto, usados)
    usados.add(perfil_id)

    instruccion = str(datos.get("instruccion") or "").strip()
    if not instruccion:
        instruccion = INSTRUCCION_POR_DEFECTO
    instruccion = instruccion[:MAX_INSTRUCCION]

    ajustes_crudos = datos.get("ajustes")
    if not isinstance(ajustes_crudos, dict):
        ajustes_crudos = {}
    ajustes, _avisos = config.normalizar(ajustes_crudos)

    return Perfil(
        id=perfil_id,
        nombre=nombre,
        instruccion=instruccion,
        ajustes=asdict(ajustes),
    )


def _normalizar_registro(datos: Any) -> tuple[list[Perfil], str]:
    """Convierte lo que haya en disco en algo usable, sin lanzar excepciones."""
    if not isinstance(datos, dict):
        datos = {}

    brutos = datos.get("perfiles")
    if not isinstance(brutos, list):
        brutos = []

    usados: set[str] = set()
    perfiles: list[Perfil] = []
    for bruto in brutos:
        perfil = _normalizar_perfil(bruto, usados)
        if perfil is not None:
            perfiles.append(perfil)

    if not perfiles:
        return [_perfil_por_defecto()], "niu"

    activo = str(datos.get("activo") or "").strip()
    if activo not in {perfil.id for perfil in perfiles}:
        activo = perfiles[0].id
    return perfiles, activo


def cargar() -> tuple[list[Perfil], str]:
    """Devuelve los perfiles y el id activo. Nunca falla por un archivo roto."""
    if not RUTA_PERFILES.exists():
        return [_perfil_por_defecto()], "niu"

    try:
        contenido = json.loads(RUTA_PERFILES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[PERFILES] No se pudo leer {RUTA_PERFILES.name}: {e}")
        return [_perfil_por_defecto()], "niu"

    return _normalizar_registro(contenido)


def _escribir(perfiles: list[Perfil], activo: str) -> None:
    """Escritura atómica: si el proceso muere, el archivo anterior sobrevive."""
    RUTA_PERFILES.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "version": VERSION,
        "activo": activo,
        "perfiles": [asdict(perfil) for perfil in perfiles],
    }
    temporal = RUTA_PERFILES.with_suffix(RUTA_PERFILES.suffix + ".tmp")
    temporal.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporal, RUTA_PERFILES)


def _buscar(perfiles: list[Perfil], perfil_id: str) -> Perfil:
    for perfil in perfiles:
        if perfil.id == perfil_id:
            return perfil
    raise PerfilNoExiste(f"No existe el perfil {perfil_id!r}.")


# ─── Operaciones ───────────────────────────────────────────────────────


def listar() -> tuple[list[Perfil], str]:
    """Perfiles guardados y cuál está activo."""
    return cargar()


def obtener(perfil_id: str) -> Perfil:
    perfiles, _activo = cargar()
    return _buscar(perfiles, perfil_id)


def activo() -> Perfil:
    perfiles, activo_id = cargar()
    return _buscar(perfiles, activo_id)


def crear(
    nombre: str,
    *,
    ajustes: dict[str, Any] | None = None,
    instruccion: str | None = None,
) -> Perfil:
    """Añade un perfil y lo devuelve, sin activarlo.

    El panel decide si activarlo: crear y activar son dos operaciones distintas
    y mezclarlas haría que un error al guardar dejara la interfaz a medias.
    """
    nombre = _limpiar_nombre(nombre)
    perfiles, activo_id = cargar()

    usados = {perfil.id for perfil in perfiles}
    perfil_id = _slug(nombre, usados)

    texto = (instruccion or "").strip() or INSTRUCCION_POR_DEFECTO
    datos_ajustes = ajustes or asdict(config.ajustes())
    normalizados, _avisos = config.normalizar(datos_ajustes)

    perfil = Perfil(
        id=perfil_id,
        nombre=nombre,
        instruccion=texto[:MAX_INSTRUCCION],
        ajustes=asdict(normalizados),
    )
    perfiles.append(perfil)
    _escribir(perfiles, activo_id)
    return perfil


def renombrar(perfil_id: str, nombre: str) -> Perfil:
    nombre = _limpiar_nombre(nombre)
    perfiles, activo_id = cargar()
    perfil = _buscar(perfiles, perfil_id)
    renombrado = replace(perfil, nombre=nombre)

    actualizados = [renombrado if p.id == perfil_id else p for p in perfiles]
    _escribir(actualizados, activo_id)
    return renombrado


def guardar_instruccion(perfil_id: str, instruccion: str) -> Perfil:
    perfiles, activo_id = cargar()
    perfil = _buscar(perfiles, perfil_id)

    texto = str(instruccion or "").strip()
    if not texto:
        raise InstruccionInvalida(
            "La instrucción no puede quedar vacía; usa el texto de fábrica si quieres volver."
        )

    actualizado = replace(perfil, instruccion=texto[:MAX_INSTRUCCION])
    _escribir([actualizado if p.id == perfil_id else p for p in perfiles], activo_id)
    return actualizado


def fijar_activo(perfil_id: str) -> Perfil:
    perfiles, _activo_id = cargar()
    perfil = _buscar(perfiles, perfil_id)
    _escribir(perfiles, perfil_id)
    return perfil


def eliminar(perfil_id: str) -> tuple[str, bool]:
    """Borra un perfil. Devuelve `(nuevo_activo, hay_que_aplicarlo)`.

    No se permite quedarse sin ninguno: el panel necesita un perfil para
    mostrar y el motor para arrancar con algo coherente.
    """
    perfiles, activo_id = cargar()
    if len(perfiles) <= 1:
        raise PerfilUnico("No puedes borrar el último perfil.")

    _buscar(perfiles, perfil_id)
    restantes = [perfil for perfil in perfiles if perfil.id != perfil_id]
    nuevo_activo = activo_id
    if activo_id == perfil_id:
        nuevo_activo = restantes[0].id

    _escribir(restantes, nuevo_activo)
    return nuevo_activo, activo_id == perfil_id


def sincronizar_ajustes(ajustes: Any) -> None:
    """Copia los ajustes recién guardados al perfil activo.

    Se llama desde `panel/ajustes.py` después de escribir `config.json`. Si aún
    no hay `perfiles.json`, `cargar()` construye el perfil inicial con los
    ajustes que ya están en memoria, así que no se pierde nada.
    """
    perfiles, activo_id = cargar()
    perfil = _buscar(perfiles, activo_id)
    actualizado = replace(perfil, ajustes=asdict(ajustes))
    _escribir([actualizado if p.id == activo_id else p for p in perfiles], activo_id)


def instruccion_activa() -> str:
    """Prompt del perfil activo, o el de fábrica si algo falta."""
    return activo().instruccion or INSTRUCCION_POR_DEFECTO
