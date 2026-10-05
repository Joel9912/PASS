# ui/equipment_tab/ — Pestaña Equipo

## Qué es
Gestión del equipo que el usuario ya tiene: sus equipos (combinaciones de componentes globales), las piezas globales (telescopios, cámaras, monturas, filtros) y sus ubicaciones, con imágenes adjuntas **solo visuales**.

## Estado actual
- `__init__.py` — exporta `EquipmentPage` (QTabWidget: **Equipos → Ubicaciones**) y declara las señales `setups_changed` y `locations_changed`; aquí también el cableado interno (ubicación guardada → combo de Ubicación de Equipos).
- `equipos.py` — `EquiposTab`: splitter con la lista + «Nuevo…»/«Eliminar» a la izquierda; a la derecha, cabecera (`nombre*`, categoría con las 6 de `CATEGORIES`, ubicación, precio €, peso kg, notas y **«Guardar equipo»**), sub-subpestañas Telescopio / Cámara / Montura / Filtros y bloque «Cálculos» en vivo (escala ″/px, Dawes, F/d y veredicto de muestreo, con `HintLabel` de qué falta). `setups_changed` tras guardar equipo, pieza o filtro.
- `componentes.py` — `TelescopeForm`/`CameraForm`/`MountForm` (datos comparables; «—» = no informado → `None`; lecturas vivas de focal efectiva y F/d; imágenes en memoria) + `PartPicker`/`PartEditor` (combo de piezas globales con **«Nuevo…», «Guardar componente», «Eliminar»** — este último avisa con `count_setups_using`) y `FiltersPanel` (tabla con la casilla «lo lleva este equipo» + CRUD de filtros globales).
- `rosaceas.py` — discos de la ubicación, dueño de la paleta muestreada de CL (19,6-21,8 mag/arcsec²) y de la convención «mirando el cielo, N arriba, E a la izquierda»: `RosaDirecciones` (solo orientación), `DiscoObstrucciones` (menú radio con los 5 grados de `OBSTRUCTION_ALTITUDES`), `DiscoLumen` (`_PanelLumen` con las 4 fuentes + «Sin fuente» y slider de km) y `DiscoEsquematico` (campo de color por fuente, rejilla punteada, cuñas rojas de obstrucción y barra de mag/arcsec²).
- `sitio.py` — `SitioPanel`: fila con la rosácea + el esquemático a la izquierda y el mapa de CL a la derecha («Añadir mapa…»/«Quitar» + `consider_lp` + vista previa `_VistaMapa` escalada al cuadro); `set_valores`/`valores` hacen roundtrip con `equipment/localizations.py`.
- `ubicaciones.py` — `UbicacionesTab`: lista + ficha con fila superior **Geografía** (a medio ancho, huso Auto) | **Cielo** (Bortle* + SQM + hint) y debajo el `SitioPanel`, con **«Guardar ubicación»** siempre visible y sin botones de paso en ningún spinner; `locations_changed` tras guardar.
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
