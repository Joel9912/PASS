"""Regiones duplicadas: aviso explícito, original intacto y formulario recuperable sin datos personales."""

import pytest

from planners import personal_catalog


def test_region_repetida_se_rechaza_sin_cambiar_original(memory_db):
    """El intento no actualiza centro, encuadre, notas ni fecha de una región ya guardada."""
    personal_catalog.add_region("Región", 1, 20, 100, 80, 2, 3, "Original")
    before = dict(memory_db.execute("SELECT * FROM personal_catalog").fetchone())
    with pytest.raises(ValueError, match="Ya existe"):
        personal_catalog.add_region("Región", 2, 30, 200, 160, 4, 5, "Intento nuevo")
    assert dict(memory_db.execute("SELECT * FROM personal_catalog").fetchone()) == before
    assert memory_db.execute("SELECT count(*) FROM personal_catalog").fetchone()[0] == 1


@pytest.mark.parametrize("rename", [False, True])
def test_aviso_region_duplicada_conserva_entrada_y_no_emite_falso_exito(qt_app, memory_db, monkeypatch, rename):
    """Tras el aviso se puede cancelar o renombrar la misma entrada; no hay éxito ni refresco ficticios."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QDialog

    from ui.planner_tab.catalogo_personal import tab as module

    personal_catalog.add_region("Región", 1, 20, notes="Original")
    page = module.CatalogoPersonalTab()
    page._table.setCurrentCell(0, 1)
    before = personal_catalog.list_objects()
    attempts, warnings, added, refreshed = [], [], [], []

    def enter(dialog):
        """Edita una sola vez; el reintento debe conservar coordenadas y notas del formulario."""
        if not attempts:
            dialog._name.setText("Región")
            dialog._ra.setValue(2)
            dialog._notes.setText("Intento nuevo")
        else:
            assert dialog._ra.value() == 2 and dialog._notes.text() == "Intento nuevo"
            assert personal_catalog.list_objects() == before
            assert page._table.currentRow() == 0
            if not rename:
                return QDialog.DialogCode.Rejected
            dialog._name.setText("Otra región")
        attempts.append(dialog)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(module.RegionDialog, "exec", enter)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(page, "refresh", lambda: refreshed.append(True))
    page.region_added.connect(added.append)
    try:
        page._on_add_region()
        assert len(warnings) == 1 and "Ya existe" in warnings[0]
        assert added == (["Otra región"] if rename else [])
        assert refreshed == ([True] if rename else [])
        if rename:
            rows = {row["object_id"]: row for row in personal_catalog.list_objects()}
            assert rows["Región"] == before[0]
            assert rows["Otra región"]["ra_hours"] == 2
        else:
            assert personal_catalog.list_objects() == before
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert page.findChildren(module.RegionDialog) == []
    finally:
        page.deleteLater()
