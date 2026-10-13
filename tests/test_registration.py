"""registration: auditoría y registro final con SirIL mockeado.

El doble reproduce lo que SirIL hace de verdad (link renombra por índice y
sus enlaces conservan el archivo original; register deja las filas R en el .seq;
seqapplyreg crea los r_*; calibrate crea la salida pp_), para poder probar
el mapeo sesión↔frame y los comandos sin el binario. La validación con
SirIL real vive fuera de pytest.
"""
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from stacks import registration
from stacks.global_pool import GlobalPool
from stacks.registration import audit_pool, auditoria_guardada, register_pool
from stacks.siril_runner import SirilError, SirilResult


@pytest.mark.parametrize("defecto", ["falta", "nombre", "duplicado"])
def test_mapeo_rechaza_indices_invalidos(tmp_path, defecto):
    """El mapeo exige índices consecutivos y una referencia por entrada."""
    pool = _pool(tmp_path)
    destino = tmp_path / "indices"
    destino.mkdir()
    for i, ref in enumerate(pool.entries, 1):
        os.link(ref.ruta, destino / f"registro_{i:05d}.fit")
    ultimo = destino / "registro_00005.fit"
    if defecto == "falta":
        ultimo.unlink()
    elif defecto == "nombre":
        ultimo.rename(destino / "registro_incorrecto.fit")
    else:
        ultimo.unlink()
        os.link(pool.entries[0].ruta, ultimo)
    with pytest.raises(SirilError):
        registration._mapear(destino, "registro_", pool.entries)


def test_registro_limpia_restos_antes_de_invocar_siril(tmp_path, siril_falso, monkeypatch):
    """Una corrida nueva no consume secuencias ni salidas de la anterior."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    destino = tmp_path / "working" / "registrados" / "x"
    destino.mkdir(parents=True)
    restos = [destino / "r_viejo.fit", destino / "viejo.seq"]
    for p in restos:
        p.write_bytes(b"anterior")
    register_pool(_pool(tmp_path), "x")
    assert all(not p.exists() for p in restos)


@pytest.mark.parametrize("paso", ["calibrate", "seqapplyreg"])
def test_salidas_mal_nombradas_no_se_admiten(tmp_path, siril_falso, monkeypatch, paso):
    """Un fichero inesperado no sustituye una salida indexada de SirIL."""
    def ejecutar(comandos, *, cwd=None, **kwargs):
        """Simula un OK con una salida cuyo índice no pertenece a la secuencia."""
        resultado = siril_falso(comandos, cwd=cwd, **kwargs)
        if any(c.startswith(paso) for c in comandos):
            prefijo = "pp_d_" if paso == "calibrate" else "r_registro_"
            (cwd / f"{prefijo}00001.fit").rename(cwd / f"{prefijo}99999.fit")
        return resultado

    monkeypatch.setattr(registration, "ejecutar_script", ejecutar)
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    with pytest.raises(SirilError):
        register_pool(_pool_cfa(tmp_path), "x", debayer=paso == "calibrate")


def _light(path: Path, *, bayer: bool = False) -> Path:
    """Light calibrado de mentira (FITS mínimo); ``bayer`` = CFA crudo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cabecera = fits.Header({"BAYERPAT": "RGGB"}) if bayer else None
    fits.writeto(path, np.full((2, 2), 1, dtype=np.uint16),
                 header=cabecera, overwrite=True)
    return path


class _SirilFalso:
    """Doble de ``ejecutar_script``: simula link/register/seqapplyreg/calibrate."""

    def __init__(self):
        self.llamadas: list[dict] = []

    def __call__(self, comandos, *, cwd=None, **kwargs):
        self.llamadas.append({"comandos": list(comandos), "cwd": cwd})
        for comando in comandos:
            res = self._ejecutar(comando, cwd)
            if res is not None:  # un comando puede cortar la corrida (fallo)
                return res
        return SirilResult(ok=True, comandos=list(comandos))

    def _ejecutar(self, comando: str, cwd: Path) -> SirilResult | None:
        partes = comando.split()
        orden, resto = partes[0], partes[1:]
        if orden == "link":
            prefijo = resto[0]
            fuentes = sorted(
                p for p in cwd.iterdir()
                if p.suffix == ".fit" and not p.name.startswith(f"{prefijo}_")
            )
            for i, fuente in enumerate(fuentes, start=1):
                os.link(fuente, cwd / f"{prefijo}_{i:05d}.fit")
            (cwd / f"{prefijo}_.seq").write_text(
                f"S '{prefijo}_' 1 0 0 0 0 6 0 0 0\n"
            )
        elif orden == "register":
            prefijo = resto[0].rstrip("_")
            with (cwd / f"{prefijo}_.seq").open("a") as fh:
                for _ in sorted(cwd.glob(f"{prefijo}_*.fit")):
                    fh.write("R0 5.0 5.0 0.98 0 690.0 27 H 1 0 0 0 1 0 0 0 1\n")
        elif orden == "seqapplyreg":
            prefijo = resto[0].rstrip("_")
            for enlace in sorted(cwd.glob(f"{prefijo}_*.fit")):
                shutil.copyfile(enlace, cwd / f"r_{enlace.name}")
        elif orden == "calibrate":
            # Como SirIL real (vía ``calibrate … -debayer``): la salida es
            # pp_ + el nombre de la entrada (d_00001.fit → pp_d_00001.fit).
            prefijo = resto[0].rstrip("_")
            for fuente in sorted(cwd.glob(f"{prefijo}_*.fit")):
                shutil.copyfile(fuente, cwd / f"pp_{fuente.name}")
        return None


class _SirilIdentidad(_SirilFalso):
    """Como el doble normal, pero seqapplyreg aborta como SirIL real sin dither."""

    def _ejecutar(self, comando: str, cwd: Path) -> SirilResult | None:
        if comando.startswith("seqapplyreg"):
            return SirilResult(
                ok=False,
                comandos=[comando],
                lineas=[
                    (
                        "Existing registration data is a set of identity matrices, "
                        "no transformation would be applied, aborting"
                    )
                ],
                motivo="SirIL terminó con código 1.",
            )
        return super()._ejecutar(comando, cwd)


@pytest.fixture
def siril_falso(monkeypatch) -> _SirilFalso:
    """Sustituye la corrida de SirIL por el doble de esta prueba."""
    falso = _SirilFalso()
    monkeypatch.setattr(registration, "ejecutar_script", falso)
    return falso


def _pool(tmp_path: Path) -> GlobalPool:
    """Pool de dos sesiones cuyos ficheros CHOCAN de nombre entre sí."""
    raiz = tmp_path / "calibrados"
    pool = GlobalPool(root=raiz)
    for sesion, n in (("noche1", 2), ("noche2", 3)):
        carpeta = raiz / sesion / "light"
        for i in range(1, n + 1):
            _light(carpeta / f"pp_light_{i:05d}.fit")
        pool.add_session(sesion, carpeta)
    return pool


def test_mapea_frames_a_su_sesion(tmp_path, siril_falso, monkeypatch):
    """Cada índice de la secuencia vuelve a su sesión (aunque los nombres chocan)."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    registro = register_pool(_pool(tmp_path), "apilado1")

    assert registro.seq == "registro_"
    assert registro.transformadas is True
    assert [ref.sesion for ref in registro.frames] == [
        "noche1", "noche1", "noche2", "noche2", "noche2",
    ]
    assert [ref.ruta.name for ref in registro.frames] == [
        "pp_light_00001.fit", "pp_light_00002.fit",
        "pp_light_00001.fit", "pp_light_00002.fit", "pp_light_00003.fit",
    ]
    assert registro.ruta_seq.exists()


def test_registro_sin_privilegios_symlink(tmp_path, siril_falso, monkeypatch):
    """Los hardlinks conservan identidad de frames sin requerir permisos de symlink."""
    def negar(*args, **kwargs):
        """Simula Windows sin privilegio para crear enlaces simbólicos."""
        raise PermissionError("symlink no permitido")

    monkeypatch.setattr(Path, "symlink_to", negar)
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    pool = _pool(tmp_path)
    registro = register_pool(pool, "sin_privilegios")
    assert [ref.ruta for ref in registro.frames] == [ref.ruta for ref in pool.entries]


def test_auditoria_guardada_reutiliza_solo_pool_identico(tmp_path, siril_falso, monkeypatch):
    """El .seq previo no se atribuye a lights distintos ni modificados."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    pool = _pool(tmp_path)
    registro = audit_pool(pool)
    previo = auditoria_guardada(pool)
    assert previo is not None
    assert previo.frames == registro.frames
    assert len(siril_falso.llamadas) == 2
    pool.entries[0].ruta.touch()
    assert auditoria_guardada(pool) is None


def test_registra_con_referencia_automatica(tmp_path, siril_falso, monkeypatch):
    """-2pass (SirIL elige la referencia) y seqapplyreg (aplica las transformadas)."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    register_pool(_pool(tmp_path), "apilado1")

    plan = [c for llamada in siril_falso.llamadas for c in llamada["comandos"]]
    assert plan == ["link registro", "register registro_ -2pass", "seqapplyreg registro_"]


def test_drizzle_va_en_seqapplyreg_con_escala_x2(tmp_path, siril_falso, monkeypatch):
    """Drizzle en la aplicación, con su escala x2 (validado con SirIL real)."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    register_pool(_pool(tmp_path), "d", drizzle=True, pixfrac=0.8, kernel="lanczos2")

    aplicar = [
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("seqapplyreg")
    ]
    assert aplicar == [
        "seqapplyreg registro_ -drizzle -pixfrac=0.8 -kernel=lanczos2 -scale=2"
    ]


def test_encuadre_escala_y_flat_se_usan_en_registro(tmp_path, siril_falso, monkeypatch):
    """Las elecciones de la referencia viajan hasta seqapplyreg, con ruta segura."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    flat = tmp_path / "flat maestro.fit"
    flat.touch()
    register_pool(_pool(tmp_path), "d", drizzle=True, scale=1.4,
                  framing="min", pixfrac=0.7, kernel="point", flat=flat)
    comandos = [c for llamada in siril_falso.llamadas
                for c in llamada["comandos"] if c.startswith("seqapplyreg")]
    assert len(comandos) == 1
    assert "-framing=min -drizzle -pixfrac=0.7 -kernel=point -scale=1.4" in comandos[0]
    assert f'"-flat={flat.as_posix()}"' in comandos[0]


def test_flat_invalido_no_limpia_registro_previo(tmp_path, monkeypatch):
    """Una configuración inválida no borra salidas existentes en working."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    carpeta = tmp_path / "working" / "registrados" / "d"
    carpeta.mkdir(parents=True)
    marca = carpeta / "anterior.fit"
    marca.touch()
    with pytest.raises(ValueError, match="flat"):
        register_pool(_pool(tmp_path), "d", drizzle=True,
                      flat=tmp_path / "inexistente.fit")
    assert marca.exists()


def test_pool_vacio_no_registra(tmp_path):
    """Sin frames no se invoca a SirIL."""
    with pytest.raises(SirilError, match="vacío"):
        register_pool(GlobalPool(root=tmp_path), "x")


def test_fallo_de_siril_propaga(tmp_path, monkeypatch):
    """Si SirIL falla, no se finge registro."""

    def _falla(comandos, *, cwd=None, **kwargs):
        return SirilResult(ok=False, comandos=list(comandos), motivo="fallo simulado")

    monkeypatch.setattr(registration, "ejecutar_script", _falla)
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    with pytest.raises(SirilError, match="secuencia"):
        register_pool(_pool(tmp_path), "x")


def test_no_toca_los_originales(tmp_path, siril_falso, monkeypatch):
    """Ni copias ni escrituras fuera de la carpeta de registro (cero copias)."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    pool = _pool(tmp_path)
    antes = {ref.ruta: ref.ruta.stat().st_mtime_ns for ref in pool.entries}

    register_pool(pool, "apilado1")

    assert {ref.ruta: ref.ruta.stat().st_mtime_ns for ref in pool.entries} == antes
    trabajo = tmp_path / "working" / "registrados" / "apilado1"
    # La entrada vive de enlaces al original (nuestro código); la salida r_*
    # es la transformación que SirIL escribe por su cuenta.
    assert all(p.is_symlink() or p.stat().st_nlink >= 2 for p in trabajo.glob("registro_*.fit"))
    assert len(list(trabajo.glob("r_*.fit"))) == 5


def test_frames_idénticos_no_son_fallo(tmp_path, monkeypatch):
    """SirIL se niega con transformadas de identidad: se apila la entrada."""
    avisos = []
    monkeypatch.setattr(registration, "ejecutar_script", _SirilIdentidad())
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")

    registro = register_pool(_pool(tmp_path), "apilado1", log_cb=avisos.append)

    assert registro.transformadas is False
    assert registro.ruta_seq.exists()  # las métricas siguen siendo válidas
    assert not list(registro.dir.glob("r_*.fit"))
    assert any("identidad" in aviso for aviso in avisos)


def test_drizzle_exige_transformadas_reales(tmp_path, monkeypatch):
    """Con drizzle pedido, la identidad no sirve: no hay salida que generar."""
    monkeypatch.setattr(registration, "ejecutar_script", _SirilIdentidad())
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    with pytest.raises(SirilError, match="drizzle"):
        register_pool(_pool(tmp_path), "d", drizzle=True)


# ------------------------------------------------------------------ auditoría
def test_auditoria_registra_sin_aplicar_nada(tmp_path, siril_falso, monkeypatch):
    """La auditoría solo hace ``-2pass``: sin seqapplyreg, sin r_, sin drizzle."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")

    registro = audit_pool(_pool(tmp_path))

    plan = [c for llamada in siril_falso.llamadas for c in llamada["comandos"]]
    assert plan == ["link registro", "register registro_ -2pass"]
    assert registro.transformadas is False  # no hay r_*: nada se aplicó
    assert registro.ruta_seq.exists()       # las métricas sí están
    assert not list(registro.dir.glob("r_*.fit"))
    assert [ref.sesion for ref in registro.frames] == [
        "noche1", "noche1", "noche2", "noche2", "noche2",
    ]


def test_auditoria_pool_vacio_no_invoca_siril(tmp_path):
    """Sin frames no se invoca a SirIL."""
    with pytest.raises(SirilError, match="vacío"):
        audit_pool(GlobalPool(root=tmp_path))


# -------------------------------------------------------------- aceptados
def test_registro_final_solo_enlaza_los_aceptados(tmp_path, siril_falso, monkeypatch):
    """El registro final trabaja SOLO con los frames marcados en la auditoría."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    pool = _pool(tmp_path)
    elegidos = [pool.entries[1], pool.entries[3]]

    registro = register_pool(pool, "apilado", aceptados=elegidos)

    assert [ref.ruta.name for ref in registro.frames] == [
        pool.entries[1].ruta.name, pool.entries[3].ruta.name,
    ]
    assert [ref.sesion for ref in registro.frames] == ["noche1", "noche2"]
    enlaces = sorted(registro.dir.glob("registro_*.fit"))
    assert len(enlaces) == 2  # solo los dos aceptados llegaron a SirIL


def test_registro_final_sin_aceptados_no_registra(tmp_path):
    """Una lista vacía de aceptados es un error claro, no un SirIL vacío."""
    pool = _pool(tmp_path)
    with pytest.raises(SirilError, match="aceptados"):
        register_pool(pool, "x", aceptados=[])


# ------------------------------------------------------------------ debayer
def _pool_cfa(tmp_path: Path) -> GlobalPool:
    """Pool mixto: el primero es CFA crudo (BAYERPAT), el segundo ya está."""
    raiz = tmp_path / "calibrados"
    pool = GlobalPool(root=raiz)
    carpeta = raiz / "noche1" / "light"
    _light(carpeta / "pp_light_00001.fit", bayer=True)
    _light(carpeta / "pp_light_00002.fit")
    pool.add_session("noche1", carpeta)
    return pool


def test_debayer_rebayeriza_solo_los_cfa(tmp_path, siril_falso, monkeypatch):
    """``debayer=True``: los CFA pasan por ``calibrate -debayer``; el resto, no.

    El orden se conserva y el registro continúa sobre la salida nueva
    (SirIL 1.4.4 no tiene comando ``debayer`` en la CLI).
    """
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    pool = _pool_cfa(tmp_path)
    antes = {ref.ruta: ref.ruta.stat().st_mtime_ns for ref in pool.entries}

    registro = register_pool(pool, "apilado", debayer=True)

    # El subpaso de rebayerizado ocurre en su propia subcarpeta…
    rebayer = next(
        llamada for llamada in siril_falso.llamadas
        if llamada["comandos"] and llamada["comandos"][0] == "link d"
    )
    assert rebayer["comandos"] == ["link d", "calibrate d_ -debayer"]
    assert rebayer["cwd"].name == "debayer"
    # …y solo el frame CFA tiene salida nueva; el otro entra tal cual.
    assert registro.frames[0].ruta.name == "pp_d_00001.fit"
    assert registro.frames[1].ruta.name == "pp_light_00002.fit"
    assert [ref.sesion for ref in registro.frames] == ["noche1", "noche1"]
    # Cero copias: los originales del pool intactos.
    assert {ref.ruta: ref.ruta.stat().st_mtime_ns for ref in pool.entries} == antes


def test_debayer_sin_cfa_no_hace_nada(tmp_path, siril_falso, monkeypatch):
    """Sin frames CFA, ``debayer=True`` no gasta una corrida de SirIL."""
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")

    registro = register_pool(_pool(tmp_path), "apilado", debayer=True)

    plan = [c for llamada in siril_falso.llamadas for c in llamada["comandos"]]
    assert "calibrate d_ -debayer" not in plan
    assert [ref.ruta.name for ref in registro.frames][0] == "pp_light_00001.fit"


def test_debayer_falla_si_siril_falla(tmp_path, siril_falso, monkeypatch):
    """Si el rebayerizado falla, no se sigue como si nada hubiera pasado."""
    def _falla_debayer(comandos, *, cwd=None, **kwargs):
        if any(c.startswith("calibrate") for c in comandos):
            return SirilResult(ok=False, comandos=list(comandos),
                               motivo="debayer roto")
        return siril_falso(comandos, cwd=cwd, **kwargs)

    monkeypatch.setattr(registration, "ejecutar_script", _falla_debayer)
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    with pytest.raises(SirilError, match="debayer"):
        register_pool(_pool_cfa(tmp_path), "d", debayer=True)


def test_debayer_falla_si_faltan_salidas(tmp_path, siril_falso, monkeypatch):
    """SirIL dice OK pero no sale un fichero por frame: se falla claro."""
    def _sin_salidas(comandos, *, cwd=None, **kwargs):
        if any(c.startswith("calibrate") for c in comandos):
            return SirilResult(ok=True, comandos=list(comandos))  # no escribe
        return siril_falso(comandos, cwd=cwd, **kwargs)

    monkeypatch.setattr(registration, "ejecutar_script", _sin_salidas)
    monkeypatch.setattr(registration, "WORKING_FOLDER", tmp_path / "working")
    with pytest.raises(SirilError, match="ficheros de"):
        register_pool(_pool_cfa(tmp_path), "d", debayer=True)
