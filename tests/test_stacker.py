"""stacks/stacker: traducción de opciones al CLI de SirIL y orquestación.

El doble simula SirIL fiel (link renumera; stack/rgbcomp escriben el -out=):
aquí se prueba la traducción de opciones, el apilado por canal y los
fallos; la validación con el binario real vive fuera de pytest.
"""
import shlex
from pathlib import Path

import pytest

from stacks import stacker
from stacks.global_pool import LightRef
from stacks.registration import Registro
from stacks.siril_runner import SirilError, SirilResult
from stacks.stacker import StackOptions, apilar_pool


def test_filtros_normalizados_homonimos_no_comparten_salidas(tmp_path, siril_falso, apilados):
    """Nombres normalizados iguales siguen siendo canales independientes."""
    registro = _registro(tmp_path, ["Ha+", "Ha-", "ha", None, "sin_filtro"])
    salidas = apilar_pool(registro, "prueba", opciones=StackOptions())
    assert len(salidas) == 5
    assert len({p.name.casefold() for p in salidas}) == 5
    assert all(p.is_file() for p in salidas)


class _SirilFalso:
    """Doble de ejecutar_script: link renumera; stack/rgbcomp crean su -out=."""

    def __init__(self, crea_salida: bool = True):
        self.crea_salida = crea_salida
        self.llamadas: list[dict] = []

    def __call__(self, comandos, *, cwd=None, **kwargs):
        self.llamadas.append({"comandos": list(comandos), "cwd": cwd})
        for comando in comandos:
            partes = shlex.split(comando)
            if partes[0] == "link":
                self._link(partes[1], cwd)
            elif partes[0] in ("stack", "rgbcomp") and self.crea_salida:
                out = next(p for p in partes if p.startswith("-out="))
                destino = Path(out.split("=", 1)[1])
                # SirIL escribe -out= relativo al cwd del guion (rgbcomp)
                (destino if destino.is_absolute() else Path(cwd) / destino).write_bytes(b"")
        return SirilResult(ok=True, comandos=list(comandos))

    def _link(self, base: str, cwd: Path) -> None:
        fuentes = sorted(p for p in cwd.iterdir() if p.suffix == ".fit")
        for i, fuente in enumerate(fuentes, start=1):
            (cwd / f"{base}_{i:05d}.fit").symlink_to(fuente.resolve())
        (cwd / f"{base}_.seq").write_text(f"S '{base}_' 1 0 0 0 0 6 0 0 0\n")


@pytest.fixture
def siril_falso(monkeypatch) -> _SirilFalso:
    """Sustituye la corrida de SirIL por el doble de esta prueba."""
    falso = _SirilFalso()
    monkeypatch.setattr(stacker, "ejecutar_script", falso)
    return falso


def _registro(tmp_path: Path, filtros: list) -> Registro:
    """Registro de mentira: un light por filtro y sus r_* de nombre."""
    dir_reg = tmp_path / "registrados" / "x"
    dir_reg.mkdir(parents=True)
    frames = [
        # ruta a la calibrada: la compone el canal (aquí no se lee)
        LightRef(ruta=Path(f"/cal/{i:04d}.fit"), sesion="s",
                 filtro=filtro, exposicion_s=60.0)
        for i, filtro in enumerate(filtros, start=1)
    ]
    for i in range(1, len(frames) + 1):
        (dir_reg / f"r_registro_{i:05d}.fit").touch()
    return Registro(dir=dir_reg, seq="registro_", frames=frames)


@pytest.fixture
def apilados(tmp_path, monkeypatch) -> Path:
    """WORKING_FOLDER redirigido a la carpeta temporal."""
    raiz = tmp_path / "working"
    monkeypatch.setattr(stacker, "WORKING_FOLDER", raiz)
    return raiz


# ------------------------------------------------------------------ opciones
def test_args_de_mean_completo():
    """La traducción sigue la gramática real de `stack` (help de 1.4.4)."""
    opciones = StackOptions(
        integration="mean", rejection="sigma", sigma_low=2.5, sigma_high=4.0,
        weighting="wfwhm", norm="mul", fastnorm=True,
    )
    assert opciones.to_siril_args() == [
        "mean", "sigma", "2.5", "4.0", "-norm=mul", "-fastnorm", "-weight=wfwhm", "-32b",
    ]


def test_args_de_med_no_lleva_rechazo():
    """`med` no admite tipo de rechazo ni sigma: SirIL lo rechazaría."""
    assert StackOptions(integration="med", norm="nonorm").to_siril_args() == [
        "med", "-nonorm", "-32b",
    ]


def test_args_de_sum_y_none():
    """`sum` es la integración mínima; rechazo none va sin sigmas."""
    assert StackOptions(integration="sum", bit32=False).to_siril_args() == ["sum"]
    assert StackOptions(rejection="none").to_siril_args() == ["mean", "none", "-32b"]


def test_args_con_extra_args():
    """Lo no expuesto (maximize, feather…) pasa sin traducir por el final."""
    assert StackOptions(integration="sum", extra_args=["-maximize"]).to_siril_args() == [
        "sum", "-32b", "-maximize",
    ]


def test_opciones_visibles_de_rechazo_y_salida_llegan_a_siril():
    """Mapas fusionados/separados y guardado no son casillas decorativas."""
    base = dict(rejmaps=True, output_norm=True, rgb_equal=True)
    assert StackOptions(**base).to_siril_args() == [
        "mean", "winsorized", "3.0", "3.0", "-rejmap", "-32b",
        "-output_norm", "-rgb_equal",
    ]
    assert "-rejmaps" in StackOptions(**base, merge_rejmaps=False).to_siril_args()
    with pytest.raises(ValueError, match="mapas"):
        StackOptions(integration="med", rejmaps=True).to_siril_args()
    with pytest.raises(ValueError, match="output_norm"):
        StackOptions(integration="sum", output_norm=True).to_siril_args()


def test_opciones_imposibles_se_rechazan():
    """Mejor un ValueError pronto que un «invalid arguments» de SirIL."""
    with pytest.raises(ValueError, match="Integración"):
        StackOptions(integration="winsorized_mean").to_siril_args()
    with pytest.raises(ValueError, match="Rechazo"):
        StackOptions(rejection="pedro").to_siril_args()
    with pytest.raises(ValueError, match="weight"):
        StackOptions(integration="sum", weighting="noise").to_siril_args()
    with pytest.raises(ValueError, match="norm"):
        StackOptions(integration="sum", norm="add").to_siril_args()


# ------------------------------------------------------------------ apilado
def test_apila_la_secuencia_registrada_entera(tmp_path, siril_falso, apilados):
    """Sin filtros (OSC o mono plano) se apila la secuencia r_ directa."""
    registro = _registro(tmp_path, [None, None, None])

    salidas = apilar_pool(registro, "mi_pila")

    assert [p.name for p in salidas] == ["mi_pila.fit"]
    assert salidas[0] == apilados / "apilados" / "mi_pila" / "mi_pila.fit"
    assert salidas[0].exists()
    assert len(siril_falso.llamadas) == 1  # una sola corrida, sin staging
    plan = siril_falso.llamadas[0]
    assert plan["comandos"][0].startswith("stack r_registro_ mean winsorized 3.0 3.0")
    assert "-32b" in plan["comandos"][0] and "-out=" in plan["comandos"][0]
    assert plan["cwd"] == registro.dir  # apila donde vive la secuencia


def test_transformadas_de_identidad_apilan_la_entrada(tmp_path, siril_falso, apilados):
    """Registro sin transformadas (identidad): se apila la secuencia de entrada."""
    registro = _registro(tmp_path, [None])
    registro.transformadas = False

    apilar_pool(registro, "p")

    assert siril_falso.llamadas[0]["comandos"][0].startswith("stack registro_ ")


def test_registro_sin_un_r_falla_en_siril_no_en_python(tmp_path, siril_falso, apilados):
    """Si al registro final le faltó un r_*, no se manda SirIL ese fichero.

    Regresión: el apilado directo (secuencia entera) se iba por ``stack``
    con un frame inexistente. Ahora cae a la ruta de secuencia propia, que
    filtra los que hay y los cuenta con aviso.
    """
    avisos = []
    registro = _registro(tmp_path, [None, None])
    (registro.dir / "r_registro_00002.fit").unlink()  # descartado al aplicar

    salidas = apilar_pool(registro, "p", log_cb=avisos.append)

    assert [p.name for p in salidas] == ["p.fit"]
    staged = registro.dir / "secuencias" / "sin_filtro"
    assert sorted(p.name for p in staged.glob("r_registro_*.fit")) == [
        "r_registro_00001.fit",
    ]
    assert any("no tienen transformadas" in a for a in avisos)


def test_aceptados_todos_es_apilado_directo(tmp_path, siril_falso, apilados):
    """La lista completa de aceptados no cambia nada: secuencia entera."""
    registro = _registro(tmp_path, [None, None, None])

    salidas = apilar_pool(registro, "p", aceptados=[1, 2, 3])

    assert [p.name for p in salidas] == ["p.fit"]
    assert len(siril_falso.llamadas) == 1  # sin secuencia de enlaces


def test_aceptados_recortados_se_estagean(tmp_path, siril_falso, apilados):
    """Descartar un frame apila una secuencia propia solo con los aceptados."""
    avisos = []
    registro = _registro(tmp_path, [None, None, None])

    salidas = apilar_pool(
        registro, "p", aceptados=[1, 3],
        opciones=StackOptions(weighting="wfwhm"), log_cb=avisos.append,
    )

    # nombre del apilado (no el de grupo) y solo los aceptados estageados
    assert [p.name for p in salidas] == ["p.fit"]
    staged = registro.dir / "secuencias" / "sin_filtro"
    assert sorted(p.name for p in staged.glob("r_registro_*.fit")) == [
        "r_registro_00001.fit",
        "r_registro_00003.fit",
    ]
    assert any("no viajan con ellas" in a for a in avisos)  # sin filas R: sin wfwhm


def test_aceptados_por_canal_intersecta(tmp_path, siril_falso, apilados):
    """Con canales, aceptados recorta cada grupo sin romper rgbcomp."""
    registro = _registro(tmp_path, ["R", "G", "B", "R", "G", "B"])

    salidas = apilar_pool(registro, "mi_rgb", aceptados=[1, 2, 3, 4])

    assert [p.name for p in salidas] == ["R.fit", "G.fit", "B.fit", "mi_rgb_rgb.fit"]


def test_aceptados_sin_un_canal_no_compone(tmp_path, siril_falso, apilados):
    """Si la auditoría vació un canal, no hay RGB que componer."""
    avisos = []
    registro = _registro(tmp_path, ["R", "G", "B"])

    salidas = apilar_pool(registro, "x", aceptados=[1, 2], log_cb=avisos.append)

    assert [p.name for p in salidas] == ["R.fit", "G.fit"]
    assert any("sin composición automática" in a for a in avisos)


def test_aceptados_vacios_falla_claro(tmp_path, siril_falso, apilados):
    """Descartarlo todo no produce una pila fantasma."""
    registro = _registro(tmp_path, [None, None])

    with pytest.raises(SirilError, match="ningún frame"):
        apilar_pool(registro, "x", aceptados=[])


def test_mono_con_filtros_apila_por_canal_y_compone_rgb(tmp_path, siril_falso, apilados):
    """R/G/B: una pila por canal y rgbcomp con el orden inequívoco."""
    registro = _registro(tmp_path, ["R", "G", "B", "R", "G", "B"])

    salidas = apilar_pool(registro, "mi_rgb")

    assert [p.name for p in salidas] == ["R.fit", "G.fit", "B.fit", "mi_rgb_rgb.fit"]
    plan = [c for l in siril_falso.llamadas for c in l["comandos"]]
    stacks = [c for c in plan if c.startswith("stack")]
    assert len(stacks) == 3 and all("canal" in c for c in stacks)
    composicion = next(c for c in plan if c.startswith("rgbcomp"))
    assert composicion.startswith("rgbcomp R.fit G.fit B.fit -out=mi_rgb_rgb.fit")


def test_tres_canales_que_no_son_rgb_no_se_componen(tmp_path, siril_falso, apilados):
    """Ha/OIII/SII: el orden de composición lo decide el usuario, no nosotros."""
    avisos = []
    registro = _registro(tmp_path, ["Ha", "OIII", "SII"])

    salidas = apilar_pool(registro, "sho", log_cb=avisos.append)

    assert [p.name for p in salidas] == ["Ha.fit", "OIII.fit", "SII.fit"]
    assert any("decide el usuario" in aviso for aviso in avisos)
    assert not any("rgbcomp" in c for l in siril_falso.llamadas for c in l["comandos"])


def test_dos_canales_sin_composicion(tmp_path, siril_falso, apilados):
    """SirIL compone RGB/LRGB: con 2 canales solo salen las pilas."""
    avisos = []
    registro = _registro(tmp_path, ["Ha", "OIII"])

    salidas = apilar_pool(registro, "hoo", log_cb=avisos.append)

    assert [p.name for p in salidas] == ["Ha.fit", "OIII.fit"]
    assert any("sin composición automática" in aviso for aviso in avisos)


def test_canal_por_enlaces_sin_copias(tmp_path, siril_falso, apilados):
    """La secuencia de canal vive de enlaces a los r_ registrados."""
    registro = _registro(tmp_path, ["R", "G", "B"])

    apilar_pool(registro, "mi_rgb")

    canal = registro.dir / "secuencias" / "R"
    assert all(p.is_symlink() for p in canal.glob("*.fit"))
    assert canal.joinpath("canal_.seq").exists()


def test_frames_del_canal_sin_registrar_se_avisa(tmp_path, siril_falso, apilados):
    """Los r_ que SirIL no generó (frames descartados) se saltan con aviso."""
    avisos = []
    registro = _registro(tmp_path, ["R", "G", "B", "R"])
    (registro.dir / "r_registro_00001.fit").unlink()  # un R no registró

    salidas = apilar_pool(registro, "mi_rgb", log_cb=avisos.append)

    assert [p.name for p in salidas] == ["R.fit", "G.fit", "B.fit", "mi_rgb_rgb.fit"]
    assert any("no tienen transformadas registradas" in a for a in avisos)
    canal = registro.dir / "secuencias" / "R"
    assert not list(canal.glob("r_registro_00001.fit"))  # el que falta ni se enlaza
    assert list(canal.glob("r_registro_00004.fit"))


def test_canal_entero_sin_registrar_falla_claro(tmp_path, siril_falso, apilados):
    """Si ningún frame del canal registró, no se finge una pila."""
    registro = _registro(tmp_path, ["R", "G", "B"])
    (registro.dir / "r_registro_00001.fit").unlink()  # R entero descartado

    with pytest.raises(SirilError, match="descartó todos"):
        apilar_pool(registro, "mi_rgb")


def test_limpia_salidas_viejas(tmp_path, siril_falso, apilados):
    """Re-apilar no mezcla con ficheros de corridas anteriores."""
    viejo = apilados / "apilados" / "mi_pila" / "viejo.fit"
    viejo.parent.mkdir(parents=True)
    viejo.touch()

    apilar_pool(_registro(tmp_path, [None]), "mi_pila")

    assert not viejo.exists()


def test_fallo_de_siril_propaga(tmp_path, monkeypatch, apilados):
    """Si SirIL falla, no se finge una pila."""

    def _falla(comandos, *, cwd=None, **kwargs):
        return SirilResult(ok=False, comandos=list(comandos), motivo="fallo simulado")

    monkeypatch.setattr(stacker, "ejecutar_script", _falla)
    with pytest.raises(SirilError, match="apilado"):
        apilar_pool(_registro(tmp_path, [None]), "x")


def test_sin_salida_aunque_siril_diga_ok(tmp_path, siril_falso, apilados):
    """El éxito lo decide también el fichero en disco, no solo el exit code."""
    siril_falso.crea_salida = False
    with pytest.raises(SirilError, match="apilado"):
        apilar_pool(_registro(tmp_path, [None]), "x")
def test_exportacion_sin_sobrescritura_ni_copias_parciales(tmp_path, apilados):
    """Exporta solo salidas finales y nunca pisa una existente."""
    import pytest

    from stacks.siril_runner import SirilError
    from stacks.stacker import APILADOS_DIR, exportar_apilados

    origen = apilados / APILADOS_DIR / "objetos"
    madre = tmp_path / "sesiones"
    origen.mkdir(parents=True)
    madre.mkdir()
    salidas = [origen / "a.fit", origen / "b.fit"]
    for ruta in salidas:
        ruta.write_bytes(ruta.name.encode())
    (madre / "b.fit").write_bytes(b"anterior")
    with pytest.raises(SirilError):
        exportar_apilados(salidas, madre)
    assert not (madre / "a.fit").exists()
    assert (madre / "b.fit").read_bytes() == b"anterior"
    (madre / "b.fit").unlink()
    assert exportar_apilados(salidas, madre) == [madre / p.name for p in salidas]
    assert (madre / "a.fit").read_bytes() == b"a.fit"


def test_exportacion_rechaza_origen_fuera_de_la_carpeta_de_trabajo(tmp_path, apilados):
    """No se exportan ficheros que PASS no generó en su carpeta de apilados."""
    from stacks.siril_runner import SirilError
    from stacks.stacker import APILADOS_DIR, exportar_apilados

    madre = tmp_path / "sesiones"
    madre.mkdir()
    ajeno = tmp_path / "privado"
    ajeno.mkdir()
    secreto = ajeno / "secreto.fit"
    secreto.write_bytes(b"privado")
    escapado = apilados / APILADOS_DIR / "externo.fit"
    escapado.parent.mkdir(parents=True, exist_ok=True)
    escapado.symlink_to(secreto)
    for ruta in (secreto, escapado):
        with pytest.raises(SirilError, match="carpeta de trabajo"):
            exportar_apilados([ruta], madre)
    assert not (madre / "secreto.fit").exists()
