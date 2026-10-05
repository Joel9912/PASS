# ui/equipment_tab/ — Pestaña Equipo

## Qué es
Gestión del equipo que el usuario ya tiene: sus equipos (combinaciones de componentes globales), las piezas globales (telescopios, cámaras, monturas, filtros) y sus ubicaciones, con imágenes adjuntas **solo visuales**.

## Estado actual
- `__init__.py` — exporta `EquipmentPage` (QTabWidget: **Equipos → Ubicaciones**) y declara las señales `setups_changed` y `locations_changed`; aquí también el cableado interno (ubicación guardada → combo de Ubicación de Equipos).
- `equipos.py` — `EquiposTab`: splitter con la lista + «Nuevo…»/«Eliminar» a la izquierda; a la derecha, cabecera (`nombre*`, categoría con las 6 de `CATEGORIES`, ubicación, precio €/peso kg **en solo lectura = suma en vivo** de las 5 piezas + filtros marcados —+0,5 kg por cada telescopio con «Con aplanador/reductor», filtros sin peso— que «Guardar equipo» persiste en `price_eur`/`weight_kg` del setup —D-3—, notas y **«Guardar equipo»**), sub-subpestañas Telescopio / Cámara / Montura / Filtros y bloque «Cálculos» en vivo (escala ″/px, Dawes, F/d y veredicto de muestreo, con `HintLabel` de qué falta). `setups_changed` tras guardar equipo, pieza o filtro.
- `componentes.py` — `TelescopeForm`/`CameraForm`/`MountForm` (datos comparables; fila «Precio|Peso» tras el Nombre, sin flechas, «—» = no informado → `None`; **Subtipo = combo solo seleccionable** con `SUBTYPE_SUGGESTIONS` —conserva el valor guardado ajeno a la lista—; lecturas vivas de focal efectiva y F/d; imágenes en memoria) + `PartPicker`/`PartEditor` (combo de piezas globales con **«Nuevo…», «Guardar componente», «Eliminar»** — este último avisa con `count_setups_using`) y `FiltersPanel` (tabla con columna **«Precio»** y la casilla «lo lleva este equipo» + CRUD de filtros globales; `_FiltroDialog` con su campo de precio). Los spins de precio/peso salen de los helpers `spin_precio`/`spin_peso`.
- `rosaceas.py` — discos de la ubicación, dueño de la paleta muestreada de CL (19,6-21,8 mag/arcsec²) y de la convención «mirando el cielo, N arriba, E a la izquierda»: `RosaDirecciones` (solo orientación), `DiscoObstrucciones` (menú radio con los 5 grados de `OBSTRUCTION_ALTITUDES`), `DiscoLumen` (`_PanelLumen` con las 4 fuentes + «Sin fuente» y slider de km) y `DiscoEsquematico` (campo de color por fuente, rejilla punteada, cuñas rojas de obstrucción —ocultables con `set_mostrar_obstaculos`, solo pintado— y barra de mag/arcsec²).
- `sitio.py` — `SitioPanel`: los 3 discos a ancho completo (HFW cuadrado, tercios iguales) y, debajo, dos cuadros a mitades: **Representación esquemática** (casillas «Usar CL y Obstáculos al Planificar» y «Mostrar obstáculos» —esta, sin entrar en `valores()`— juntas en la fila superior, a la cota de la fila de nombre/botones del mapa, para que los dos discos arranquen iguales) y **Mapa de Contaminación Lumínica** («Añadir»/«Cambiar» según haya mapa + «Quitar» + vista previa `_VistaMapa` escalada al cuadro); `set_valores`/`valores` hacen roundtrip con `equipment/localizations.py`.
- `ubicaciones.py` — `UbicacionesTab`: lista + ficha con fila superior **Geografía** (Nombre|Altitud, Latitud|Longitud y Desfase = `round(longitud/15)` —misma regla que el planificador— con huso automático, editable sin el check) | **Cielo** (Bortle* + SQM, que puede volver a «—» y manda sobre la gráfica si está informado, + **Seeing típico ″ FWHM** opcional en la fila de la antigua pista —cuyo texto vive ahora en los tooltips de Bortle/SQM—) y debajo el `SitioPanel`, con **«Guardar ubicación»** siempre visible y sin botones de paso en ningún spinner; `locations_changed` tras guardar.
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
3. Recortar/encuadrar la imagen del mapa de CL en la vista previa (estético; diferido por el usuario).
