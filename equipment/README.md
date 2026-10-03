# equipment/

## Qué es
Modelos y persistencia del equipo del usuario: setups (telescopio + cámara + montura + ubicación + categoría) y localizaciones geográficas.

## Estado actual
- `models.py` — dataclasses: `Location`, `Telescope`, `Camera`, `Mount`, `EquipmentSetup`. Solo campos comparables (apertura, focal, resolución, bits, refrigeración).
  - `Location` lleva además **`utc_offset_hours`**: desfase de la hora de reloj frente a UTC (España en verano = 2). Si es `None`, la lógica de `planners/` infiere el huso de la longitud (`round(lon/15)`, huso estándar).
- `manager.py` — CRUD de setups en SQLite (`equipment_setups`); `list_setups()` funciona y devuelve dicts con todas las columnas (la UI calcula el FOV a partir de ellos).
- `localizations.py` — CRUD de localizaciones (`locations`); `list_locations()` y `delete()` funcionan.
- `images.py` — adjuntar imágenes al setup (`equipment_images`), **solo visuales**.
- El resto de operaciones CRUD están pendientes (`NotImplementedError`).

## Qué hacer aquí
- Aquí SOLO datos y persistencia: **sin PyQt6 ni cálculos de planificación**.
- Guardar solo "datos fríos" comparables; NO guardar gráficas de rendimiento para compararlas.
- Las imágenes (spot, etc.) se adjuntan y se muestran: el usuario las compara visualmente, el programa no.
- Acceso a datos siempre vía `db.connection.get_connection()`.

## Planes futuros
1. Completar CRUD de setups y localizaciones.
2. Exportar/importar setups (JSON) para compartir configuraciones.
3. Categoría `planetario` (astrofotografía planetaria) como añadido futuro.
