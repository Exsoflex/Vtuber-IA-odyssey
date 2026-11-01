"""
Tests de `core/perfiles.py`: la biblioteca de configuraciones de Niu.

Lo que puede romperse aquí sin lanzar un error visible:

1. Que un perfil se guarde solo en memoria y desaparezca al reiniciar.
2. Que dos perfiles compartan id y uno pise al otro.
3. Que borrar el activo deje el panel apuntando a un perfil que ya no existe.
4. Que un `perfiles.json` corrupto impida arrancar en vez de caer en fábrica.

Ningún test toca los archivos reales: el fixture redirige `config.json` y
`perfiles.json` a un directorio temporal.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json
from dataclasses import asdict

import pytest

from core import config, perfiles
from core.personalidad import INSTRUCCION_POR_DEFECTO


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
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


# ─── Primer arranque ───────────────────────────────────────────────────


def test_sin_archivo_hay_un_perfil_de_fabrica():
    lista, activo = perfiles.listar()

    assert activo == "niu"
    assert len(lista) == 1
    assert lista[0].nombre == "Niu"
    assert lista[0].instruccion == INSTRUCCION_POR_DEFECTO
    assert lista[0].ajustes == asdict(config.por_defecto())


def test_un_archivo_corrupto_no_impide_arrancar(entorno):
    (entorno / "perfiles.json").write_text("{ esto no es json", encoding="utf-8")

    lista, activo = perfiles.listar()

    assert activo == "niu"
    assert len(lista) == 1


# ─── Crear ─────────────────────────────────────────────────────────────


def test_crear_guarda_y_no_repite_ids(entorno):
    primero = perfiles.crear("Niu Espacial")
    segundo = perfiles.crear("Niu Espacial")

    assert primero.id == "niu-espacial"
    assert segundo.id == "niu-espacial-2"

    guardado = json.loads((entorno / "perfiles.json").read_text(encoding="utf-8"))
    assert guardado["version"] == 1
    assert len(guardado["perfiles"]) == 3      # el de fábrica + los dos nuevos


def test_el_id_quita_acentos_y_signos():
    perfil = perfiles.crear("Ñandú ¡Nú!")

    assert perfil.id == "nandu-nu"


def test_un_nombre_vacio_se_rechaza():
    with pytest.raises(perfiles.NombreInvalido):
        perfiles.crear("   ")


def test_la_instruccion_vacia_cae_en_la_de_fabrica():
    perfil = perfiles.crear("Sin texto", instruccion="")

    assert perfil.instruccion == INSTRUCCION_POR_DEFECTO


# ─── Activar y sincronizar ─────────────────────────────────────────────


def test_fijar_activo_persiste(entorno):
    perfil = perfiles.crear("Inglés")
    perfiles.fijar_activo(perfil.id)

    lista, activo = perfiles.listar()
    assert activo == perfil.id
    assert {p.id for p in lista} == {"niu", perfil.id}


def test_sincronizar_ajustes_los_copia_al_perfil_activo(entorno):
    perfil = perfiles.crear("Inglés")
    perfiles.fijar_activo(perfil.id)

    datos = asdict(config.por_defecto())
    datos.update({"idioma": "en", "voz": "en-US-AriaNeural"})
    nuevos, _avisos = config.normalizar(datos)
    perfiles.sincronizar_ajustes(nuevos)

    guardado = perfiles.obtener(perfil.id)
    assert guardado.ajustes["idioma"] == "en"
    assert guardado.ajustes["voz"] == "en-US-AriaNeural"


# ─── Instrucción ───────────────────────────────────────────────────────


def test_guardar_instruccion_se_lee_al_activar_el_perfil():
    perfil = perfiles.crear("Seco")

    perfiles.guardar_instruccion(perfil.id, "Habla en frases de tres palabras.")
    perfiles.fijar_activo(perfil.id)

    assert perfiles.instruccion_activa() == "Habla en frases de tres palabras."


def test_una_instruccion_vacia_se_rechaza():
    perfil = perfiles.crear("Seco")

    with pytest.raises(perfiles.InstruccionInvalida):
        perfiles.guardar_instruccion(perfil.id, "   ")


# ─── Borrar ────────────────────────────────────────────────────────────


def test_no_se_puede_borrar_el_ultimo_perfil():
    with pytest.raises(perfiles.PerfilUnico):
        perfiles.eliminar("niu")


def test_borrar_el_activo_devuelve_otro():
    segundo = perfiles.crear("Temporal")
    perfiles.fijar_activo(segundo.id)

    nuevo_activo, era_activo = perfiles.eliminar(segundo.id)

    assert era_activo is True
    assert nuevo_activo == "niu"
    assert perfiles.activo().id == "niu"


def test_borrar_un_perfil_inactivo_no_cambia_el_activo():
    segundo = perfiles.crear("Temporal")

    nuevo_activo, era_activo = perfiles.eliminar(segundo.id)

    assert era_activo is False
    assert nuevo_activo == "niu"
