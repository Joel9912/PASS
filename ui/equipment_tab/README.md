# ui/equipment_tab/ — Pestaña Equipo

## Qué es
Gestión del equipo que el usuario ya tiene: sus equipos (combinaciones de componentes globales), las piezas globales (telescopios, cámaras, monturas, filtros) y sus ubicaciones, con imágenes adjuntas **solo visuales**.

## Estado actual
- `__init__.py` — exporta `EquipmentPage` (QTabWidget: **Equipos → Ubicaciones**) y declara las señales `setups_changed` y `locations_changed`; aquí también el cableado interno (ubicación guardada → combo de Ubicación de Equipos).
- `equipos.py` — `EquiposTab`: splitter con la lista + «Nuevo…»/«Eliminar» a la izquierda; a la derecha, cabecera (`nombre*`, categoría con las 6 de `CATEGORIES`, ubicación, precio €, peso kg, notas y **«Guardar equipo»**), sub-subpestañas Telescopio / Cámara / Montura / Filtros y bloque «Cálculos» en vivo (escala ″/px, Dawes, F/d y veredicto de muestreo, con `HintLabel` de qué falta). `setups_changed` tras guardar equipo, pieza o filtro.
- `componentes.py` — `TelescopeForm`/`CameraForm`/`MountForm` (datos comparables; «—» = no informado → `None`; lecturas vivas de focal efectiva y F/d; imágenes en memoria) + `PartPicker`/`PartEditor` (combo de piezas globales con **«Nuevo…», «Guardar componente», «Eliminar»** — este último avisa con `count_setups_using`) y `FiltersPanel` (tabla con la casilla «lo lleva este equipo» + CRUD de filtros globales).
- `sitio.py` — `HorizonWidget` (malla 3×3 de las 8 direcciones con menú de tipos que no se cierra al marcar) y `LightPollutionWidget` (CL 0-3 por dirección, Bortle obligatorio, SQM opcional, mapa único y `consider_lp`).
- `ubicaciones.py` — `UbicacionesTab`: lista + ficha en panel (Geografía con huso Auto, Horizonte y CL) con **«Guardar ubicación»** siempre visible; `locations_changed` tras guardar.
- Dos niveles de guardado (decisión del usuario): lo global se guarda con «Guardar componente» y lo del equipo con «Guardar equipo»; nada llega a la BD ni a `data/` hasta su botón (D-5: cambiar de fila sin guardar descarta).

## Qué hacer aquí
- Formularios y layouts con los objectNames de `ui/style.py` (`GroupFrame`, `PanelTitle`, `HintLabel`, `PrimaryButton`); literales en castellano (sin i18n).
- La UI llama a `equipment/` (manager, components, localizations, images, metrics); **nunca** SQL ni cálculos propios.
- Datos faltantes → «—» en pantalla, nunca ceros inventados; validaciones delegated a `equipment/validaciones.py` (el `ValueError` se enseña en un `QMessageBox`).
- Imágenes: lista en memoria hasta guardar (copia a `data/` en el create/update; `sync` parte de `list_images`).
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.

## Planes futuros
1. Adjuntar imágenes del propio setup (spot) en la cabecera de Equipos.
2. Duplicar setups y exportar/importar configuraciones.
