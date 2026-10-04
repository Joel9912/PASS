# equipment/

## Qué es
Modelos y persistencia del equipo del usuario: setups (telescopio + cámara + montura + ubicación + categoría) y localizaciones geográficas.

## Estado actual
- `models.py` — dataclasses: `Location`, `Telescope`, `Camera`, `Mount`, `EquipmentSetup`. Solo campos comparables (apertura, focal, resolución, bits, refrigeración).
  - `Camera` incluye **`pixel_size_um`/`width_px`/`height_px`** (los que permiten el FOV; ya estaban en el esquema y faltaban en el modelo — C-1 de la auditoría).
  - `Location` lleva además **`utc_offset_hours`**: desfase de la hora de reloj frente a UTC (España en verano = 2). Si es `None`, la lógica de `planners/` infiere el huso de la longitud (`round(lon/15)`, huso estándar).
- `manager.py` — CRUD de setups en SQLite (`equipment_setups`); `list_setups()` devuelve dicts con todas las columnas (la UI calcula el FOV a partir de ellos). `get()`/`list_setups()` **anotan `dict`**, el contrato que usa la UI (C-2).
- `localizations.py` — CRUD de localizaciones (`locations`); `list_locations()` (anota `list[dict]`, M-16) y `delete()` funcionan.
- `images.py` — adjuntar imágenes al setup (`equipment_images`), **solo visuales**. `attach()` **copia** el fichero a `data/equipment_images/<setup_id>/` (decisión D-1): la imagen persiste aunque el original se mueva o se borre; si la copia falla, guarda la ruta original.
- Esquema: `equipment_setups` incluye **`price_eur`** y **`weight_kg`** (decisión D-3).
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
4. **De la auditoría (Equipo paso 1)**: `list_setups()` con `LEFT JOIN locations` (clave `location_name`) para poder mostrar la ubicación en la tabla del plan (M-17); confirmación al borrar un setup con el nº de sesiones planificadas afectadas, porque `ON DELETE SET NULL` las desvincula en silencio (M-20).
