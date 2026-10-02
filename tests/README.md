# tests/

## Qué es
Tests de PAS.S con **pytest** (83 tests): validan que la estructura y la base del programa están sanas y que la lógica de `planners/` da los valores correctos.

## Estado actual
- `test_smoke.py` — valida que `main.py` importa, que las 6 pestañas están definidas, que todos los docs/READMEs existen y que el esquema SQLite se aplica (incluidas `catalog` y `stars`).
- `test_planners.py` — parsing del cargador (OpenNGC/HYG con datos inline, offline), búsqueda con filtros reales, tránsito/noche con astropy y ranking (orden, reasons y pesos configurables). Cubre también los campos nuevos de `NightInfo` (`sunset`, `sunrise`, `moon_age_days`, `waxing`) y `night_curve(utc_offset_hours)`. Los tests de BD llaman `ensure_catalog()`; si no hay datos ni red, se omiten.
- `test_analytical_transit.py` — culminación/altitud sin astropy y consistencia con astropy (<10 min). Incluye `local_utc_offset`: desfase guardado > longitud, y `None` cae a hora solar.
- `test_moon_distance.py` — polinomio de grado 3 (valores de referencia), `capture_windows` y `capture_window_summary`. Regresión del **cruce de medianoche**: `unwrap_hours` y que la ventana Ideal que pasa por las 00:00 no se descarte.
- `test_framing.py` — FOV desde focal/píxel/resolución y `None` si faltan datos.
- `test_capture_plan.py` — puntuación offline y `best_dates` con astropy (orden, ventanas, sin noche → vacío, `utc_offset_hours` en la hora de culminación).
- `test_ldn_loader.py` — parseo de las nebulosas oscuras de Lynds (datos inline, offline).

## Qué hacer aquí
- Ejecutar: `pytest` desde la raíz (con el venv activado). Sin flags: los tests de UI se hacen aparte.
- Añadir un test por cada módulo que pase de `NotImplementedError` a implementado.
- Tests de UI: usar `pytest-qt` si se necesita simular clics (añadir a `requirements.txt` cuando toque). Mientras tanto, las pruebas de render se hacen con `QT_QPA_PLATFORM=offscreen` fuera de pytest.
- Los tests que necesiten la BD real deben pasar por `ensure_catalog()` (fixture `loaded_db` de `test_planners.py`) y **limpiar lo que inserten** (ver roundtrip del catálogo personal). Idealmente marcando las filas con un texto propio y borrando solo esas, para no tocar datos del usuario.
- Toda corrección de un bug lleva su test de regresión en la misma tarea.

## Planes futuros
1. Tests de `stacks/`, `equipment/` y `planetary/` cuando salgan de `NotImplementedError`.
2. Tests de UI con `pytest-qt`.
3. Cobertura de `ui/planner_tab/` (helpers puros como `fmt_hhmm`, `phase_name`, `window_lines` se pueden testear ya sin Qt).
