"""Perfil operativo por equipo: validación y persistencia sin acceder al hardware."""

from dataclasses import replace

import pytest

from equipment import manager
from equipment.models import EquipmentSetup
from equipment.planning_profile import PlanningProfile, profile_from_data


@pytest.mark.parametrize("data", [{"pause_s":float("nan")}, {"meridian_flip":1}, {"focus_start":True}, {"focus_frames":True}, {"pause_s":-1}])
def test_perfil_invalido_rechazado(data):
    """No convierte perfiles defectuosos en condiciones ideales."""
    with pytest.raises(ValueError):
        replace(PlanningProfile(), **data).validate()


def test_perfil_por_equipo_hace_roundtrip(memory_db):
    """Datos por setup independientes, sin modificar piezas globales."""
    a = EquipmentSetup(name="A", planning_profile=PlanningProfile(pause_s=2).data())
    b = EquipmentSetup(name="B", planning_profile=PlanningProfile(pause_s=5).data())
    manager.create(a)
    manager.create(b)
    assert manager.get(a.id)["planning_profile"]["pause_s"] == 2
    assert manager.get(b.id)["planning_profile"]["pause_s"] == 5
    assert profile_from_data(None).pause_s is None


def test_editar_operacion_no_persiste_hasta_guardar_equipo(qt_app, memory_db):
    """La nueva ficha participa en el mismo guardado del equipo, sin escrituras al mover controles."""
    from ui.equipment_tab.equipos import EquiposTab

    setup = EquipmentSetup(name="Prueba", planning_profile=PlanningProfile(pause_s=2).data())
    manager.create(setup)
    tab = EquiposTab()
    try:
        tab._planning_profile.controls["pause_s"].setValue(5)
        assert manager.get(setup.id)["planning_profile"]["pause_s"] == 2
        assert "sin guardar" in tab._estado_guardado.text()
        assert tab._guardar()
        assert manager.get(setup.id)["planning_profile"]["pause_s"] == 5
    finally:
        tab.close()
