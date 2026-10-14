"""Recuperación de Apilador con FITS sintéticos, sin SirIL ni entradas personales."""

import json
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from db import work_drafts
from stacks import global_pool, registration, work_recovery
from stacks.calibrator import CalibrationResult, output_dir_for, save_calibration
from stacks.frame_metrics import extract_metrics
from stacks.registration import Registro
from stacks.session_parser import parse_session
from ui import draft_recovery, stacker_tab


def _registry(directory: Path, frames) -> Registro:
    """Genera una secuencia de identidad con enlaces físicos y métricas legibles."""
    directory.mkdir(parents=True, exist_ok=True)
    for i, ref in enumerate(frames, 1):
        os.link(ref.ruta, directory / f"registro_{i:05d}.fit")
    (directory / "registro_.seq").write_text(
        f"S 'registro_' 1 {len(frames)} {len(frames)} 5 0 6 0 0 0\nL 1\n"
        + "".join(f"I {i} 1\n" for i in range(1, len(frames)+1))
        + "\n".join("R0 2 2 1 0 0.01 10 H 1 0 0 0 1 0 0 0 1" for _ in frames), encoding="utf-8"
    )
    return Registro(directory, "registro_", list(frames), False)


@pytest.fixture
def pipeline(qt_app, memory_db, tmp_path, monkeypatch):
    """Prepara originales y calibrados completos en el sandbox, con auditoría compatible."""
    working = tmp_path / "working"
    for module in (stacker_tab, work_recovery, registration):
        monkeypatch.setattr(module, "WORKING_FOLDER", working)
    monkeypatch.setattr(stacker_tab, "find_siril", lambda *args: "siril-sintetico")
    source = tmp_path / "originales" / "noche"
    (source / "lights").mkdir(parents=True)
    header = fits.Header({"EXPTIME": 30.0})
    for i in (1, 2):
        fits.writeto(source / "lights" / f"light{i}.fit", np.ones((8, 8), dtype=np.int16), header)
    session = parse_session(source)
    output = output_dir_for(source, root=working / "calibrados")
    (output / "light").mkdir(parents=True)
    for i in (1, 2):
        fits.writeto(output / "light" / f"pp_light_{i:05d}.fit", np.ones((8, 8), dtype=np.int16), header)
    save_calibration(CalibrationResult(session, output, n_lights=2, exposure_s=30))
    page = stacker_tab.StackerPage()
    page.sesiones = [session]
    page._input_stamps = work_recovery.input_signature([session])
    page._refrescar_calibradas()
    page._capture_calibration_checkpoints()
    pool = global_pool.pool_desde_calibradas(page._filas_calibradas_actuales(), root=working / "calibrados")
    audit = _registry(working / "registrados" / "auditoria", pool.entries)
    (audit.dir / "pool.json").write_text(json.dumps({
        "entrada": registration._firma_pool(pool),
        "orden": [str(ref.ruta.resolve()) for ref in audit.frames],
    }), encoding="utf-8")
    page.registro, page._pool = audit, pool
    page.metricas = extract_metrics(audit)
    page.panel_auditar.mostrar(audit, page.metricas)
    page._calibrado = page._auditado = True
    page._aviso_trabajo = True
    page._capture_audit_checkpoint()
    page.panel_sesiones.poner_raiz(str(source.parent))
    page.panel_apilar._nombre.setText("pila")
    page._mostrar_paso(3)
    page._draft.changed()
    yield page, session, working
    page._parar_todo()
    page.deleteLater()


def _resume(monkeypatch):
    """Construye otra página y acepta recuperar, nunca ejecutar fases."""
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "resume")
    page = stacker_tab.StackerPage()
    page._draft.offer()
    return page


def _wait(app, condition):
    """Espera únicamente workers sintéticos con límite y bombeo del hilo UI."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


def test_recuperar_auditoria_y_descartes_no_ejecuta_siril(pipeline, monkeypatch):
    """Las marcas se recuperan por archivo, no por fila ordenada, y no arranca un worker."""
    page, session, _ = pipeline
    wanted = {str(page.registro.frames[1].ruta.absolute())}
    page.panel_auditar.restaurar_aceptados(wanted)
    page._draft.changed()
    before = {path: path.read_bytes() for path in session.frames["lights"]}
    restored = _resume(monkeypatch)
    assert not restored._draft.pending
    assert restored._calibrado and restored._auditado
    assert restored._paso == 3
    assert restored._worker is None
    assert {str(restored.registro.frames[i - 1].ruta.absolute()) for i in restored.panel_auditar.aceptados()} == wanted
    assert {path: path.read_bytes() for path in before} == before
    restored.deleteLater()


@pytest.mark.parametrize("changed", ["source", "calibrated", "audit"])
def test_entradas_o_resultados_cambiados_retroceden(pipeline, monkeypatch, changed):
    """Una carpeta existente no acredita el paso cuando falta un archivo o cambió su firma."""
    page, session, _ = pipeline
    before = work_drafts.decode(work_drafts.read("stacker"))
    if changed == "source":
        session.frames["lights"][0].write_bytes(b"cambio-sintetico")
    elif changed == "calibrated":
        page._pool.entries[0].ruta.unlink()
    else:
        page.registro.ruta_seq.write_text("incompleto", encoding="utf-8")
    restored = _resume(monkeypatch)
    assert not restored._auditado
    assert restored._final_checkpoint is None
    assert restored._paso == (0 if changed == "source" else 1 if changed == "calibrated" else 2)
    assert restored._worker is None
    if changed == "source":
        assert not restored._inputs_verified
    after = work_drafts.decode(work_drafts.read("stacker"))
    assert after["audit"] == before["audit"]
    assert after["accepted"] == before["accepted"]
    restored.deleteLater()


def test_toma_anadida_invalida_firma_escaneo(pipeline):
    """La firma detecta también nuevas tomas, no solo modificaciones de las conocidas."""
    page, session, _ = pipeline
    added = session.path / "lights" / "nueva.fit"
    fits.writeto(added, np.ones((8, 8), dtype=np.int16))
    assert not work_recovery.verify_inputs([session], page._input_stamps)


def test_aplazar_no_pisa_trabajo_ni_borra_originales(pipeline, monkeypatch):
    """Conservar para más tarde bloquea nueva corrida sin alterar archivos ni la fila."""
    _page, session, _ = pipeline
    row = work_drafts.read("stacker")
    before = session.frames["lights"][0].read_bytes()
    restored = stacker_tab.StackerPage()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "later")
    restored._draft.offer()
    restored.panel_apilar._nombre.setText("Otro")
    assert work_drafts.read("stacker") == row
    assert not restored._siguiente.isEnabled()
    assert session.frames["lights"][0].read_bytes() == before
    restored.deleteLater()


def test_registro_final_se_guarda_antes_del_fallo_de_apilado(pipeline, monkeypatch, qt_app):
    """Un fallo después de registrar deja un punto reutilizable y no acredita el apilado."""
    page, _, working = pipeline

    def register(pool, name, **kwargs):
        """Simula un registro final terminado, sin procesamiento real."""
        return _registry(working / "registrados" / name, kwargs["aceptados"])

    def fail(*args, **kwargs):
        """Interrumpe después de confirmar el registro final."""
        raise ValueError("apilado interrumpido")

    monkeypatch.setattr(stacker_tab, "register_pool", register)
    monkeypatch.setattr(stacker_tab, "apilar_pool", fail)
    page.apilar()
    assert _wait(qt_app, lambda: page._worker is None and page._final_checkpoint is not None)
    row = work_drafts.decode(work_drafts.read("stacker"))
    assert row["final"] is not None
    assert not page._apilado
    restored = _resume(monkeypatch)
    assert restored._final_checkpoint is not None
    assert restored._worker is None

    def never_register(*args, **kwargs):
        """Falla si recuperar vuelve a registrar sin necesidad."""
        raise AssertionError("No repetir registro")

    def stack(registry, name, **kwargs):
        """Produce únicamente una salida final sintética dentro de working."""
        destination = working / "apilados" / name
        destination.mkdir(parents=True)
        result = destination / f"{name}.fit"
        fits.writeto(result, np.ones((8, 8), dtype=np.int16))
        return [result]

    monkeypatch.setattr(stacker_tab, "register_pool", never_register)
    monkeypatch.setattr(stacker_tab, "apilar_pool", stack)
    monkeypatch.setattr(stacker_tab, "exportar_apilados", lambda paths, parent: paths)
    restored.apilar()
    assert _wait(qt_app, lambda: restored._worker is None and restored._apilado)
    assert work_drafts.read("stacker") is None
    restored._parar_todo()
    restored.deleteLater()


def test_registro_con_indices_ajenos_se_rechaza(pipeline):
    """La recuperación aplica el mismo mapeo físico uno-a-uno que el registro normal."""
    page, _, _ = pipeline
    sealed = page._audit_checkpoint
    extra = page.registro.dir / "registro_00003.fit"
    extra.write_bytes(b"ajeno")
    sealed["signature"] = work_recovery.signature(path for path in page.registro.dir.rglob("*") if path.is_file())
    with pytest.raises(ValueError, match="[Íí]ndices|frames"):
        work_recovery.recover_registry(sealed)


def test_fallo_guardando_registro_impide_iniciar_apilado(pipeline, monkeypatch, qt_app):
    """El worker espera confirmación SQLite; un fallo deja el registro en disco sin apilar."""
    page, _, working = pipeline
    save = work_drafts.save
    stacks = []

    def save_or_fail(workflow, payload, revision):
        """Falla solo al confirmar el registro, no durante la configuración inicial."""
        if payload.get("final") is not None:
            raise sqlite3.OperationalError("sin espacio")
        return save(workflow, payload, revision)

    def register(pool, name, **kwargs):
        """Simula un registro completo con identidad física verificable."""
        return _registry(working / "registrados" / name, kwargs["aceptados"])

    monkeypatch.setattr(work_drafts, "save", save_or_fail)
    monkeypatch.setattr(stacker_tab, "register_pool", register)
    monkeypatch.setattr(stacker_tab, "apilar_pool", lambda *args, **kwargs: stacks.append(True))
    page.apilar()
    assert _wait(qt_app, lambda: page._worker is None and page._final_checkpoint is not None)
    assert stacks == []
    assert work_drafts.decode(work_drafts.read("stacker"))["final"] is None
    assert (working / "registrados" / "pila" / "registro_.seq").is_file()
    assert page.panel_calibrar._opt.isEnabled()
    assert "solo en memoria" in page._draft.label.text()


def test_descartar_borrador_no_elimina_resultados(pipeline, monkeypatch):
    """Descartar retira únicamente el estado personal de recuperación."""
    page, session, _ = pipeline
    paths = [*session.frames["lights"], page.registro.ruta_seq, *[r.ruta for r in page._pool.entries]]
    before = {path: path.read_bytes() for path in paths}
    restored = stacker_tab.StackerPage()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "discard")
    restored._draft.offer()
    assert work_drafts.read("stacker") is None
    assert {path: path.read_bytes() for path in paths} == before
    restored.deleteLater()


def test_recuperar_registro_con_transformadas(pipeline):
    """El registro aplicado exige también su secuencia de salida y archivos sellados."""
    page, _, working = pipeline
    final = _registry(working / "registrados" / "final", page._pool.entries)
    final.transformadas = True
    (final.dir / "r_registro_.seq").write_text("secuencia-sintetica", encoding="utf-8")
    for i in (1, 2):
        fits.writeto(final.dir / f"r_registro_{i:05d}.fit", np.ones((8, 8), dtype=np.int16))
    context = work_recovery.registration_context({}, page._pool.entries)
    checkpoint = work_recovery.seal_registry(final, context)
    restored = work_recovery.recover_registry(checkpoint)
    assert restored.transformadas
    assert restored.seq_apilable == "r_registro_"
    (final.dir / "r_registro_00002.fit").unlink()
    with pytest.raises(ValueError):
        work_recovery.recover_registry(checkpoint)


def test_reauditoria_fallida_no_deja_apilable_la_anterior(pipeline, monkeypatch, qt_app):
    """Un fallo al releer métricas invalida el permiso de apilado, no reutiliza la tabla anterior."""
    from PyQt6.QtWidgets import QMessageBox

    page, _, _ = pipeline
    registry = page.registro
    pool = page._pool
    assert page._auditado
    wanted = {str(registry.frames[1].ruta.absolute())}
    page.panel_auditar.restaurar_aceptados(wanted)
    previous = registry.ruta_seq.read_text(encoding="utf-8")
    registry.ruta_seq.write_text(previous.replace("R0 2 2", "R0 inf 2"), encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(stacker_tab, "audit_pool", lambda *args, **kwargs: registry)
    monkeypatch.setattr(stacker_tab, "pool_desde_calibradas", lambda *args, **kwargs: pool)
    page.auditar()
    assert _wait(qt_app, lambda: page._worker is None)
    assert not page._auditado
    assert page.registro is None
    assert page._pool is None
    assert set(work_drafts.decode(work_drafts.read("stacker"))["accepted"]) == wanted
    registry.ruta_seq.write_text(previous, encoding="utf-8")
    page.auditar()
    assert _wait(qt_app, lambda: page._worker is None and page._auditado)
    assert {str(page.registro.frames[i-1].ruta.absolute()) for i in page.panel_auditar.aceptados()} == wanted


@pytest.mark.parametrize("legacy", [False, True])
def test_recuperar_criterio_fwhm_y_borrador_anterior(pipeline, monkeypatch, legacy):
    """Los nuevos controles se recuperan y un borrador antiguo mantiene MAD y puntuación."""
    page, _, _ = pipeline
    page.panel_auditar._criterio_fwhm.setCurrentIndex(1)
    page.panel_auditar._usar_puntuacion.setChecked(False)
    page._draft.changed()
    if legacy:
        row = work_drafts.read("stacker")
        payload = work_drafts.decode(row)
        payload["controls"].pop("audit_criterio_fwhm")
        payload["controls"].pop("audit_usar_puntuacion")
        work_drafts.save("stacker", payload, row["revision"])
    restored = _resume(monkeypatch)
    try:
        assert not restored._draft.pending
        assert restored.panel_auditar._criterio_fwhm.currentData() == ("mad" if legacy else "media_minimo")
        assert restored.panel_auditar._usar_puntuacion.isChecked() == legacy
        assert restored.panel_auditar._umbral.isEnabled() == legacy
        assert restored._worker is None
    finally:
        restored.deleteLater()
