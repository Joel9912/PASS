# ui/planner_tab/ — Pestaña Planificador (corazón del programa)

## Qué es
El núcleo de PAS.S: buscar objetos, evaluar cuándo fotografiarlos, guardar los que interesan y concretar sesiones de captura. Tiene **4 subpestañas** en este orden: **Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**.

## Estado actual
Carpeta **implementada** y probada (render offscreen + arranque real de `python main.py`):

- `__init__.py` — documenta el orden de las subpestañas y exporta `BusquedaTab`, `CatalogoPersonalTab`, `PlanificacionTab`, `SesionesTab`, `LocationBar`.
- `widgets.py` — componentes compartidos:
  - `LocationBar` (combo de `locations` + lat/lon + huso, compacta en 3 filas: "📍 Ubicación" / Lat / Lon + Huso). **Única fuente de verdad** de latitud, longitud y `utc_offset_hours` para las 4 subpestañas. Vive **solo en Búsqueda** (fila 3, columna izquierda); `PlannerPage` la expone como `location_bar` y Planificación la recibe por señal. Si hay ubicaciones guardadas selecciona la primera; si no, no inventa un punto (aviso "escribe lat/long"; el combo ofrece "Manual — escribe aquí"). El huso ofrece **«Auto» = huso inferido de la longitud** (`round(lon/15)`, nunca la hora del sistema: con un huso de otro continente la noche salía «invertida») y horas de reloj fijas (override político: España +1/+2, India +5.5…). Lat y lon se mueven con **◀ / ▶ de 34 px como los de Efemérides** (`_stepper`: un clic = 1°, tomando el paso del propio spinbox); el spinbox va **sin flechitas nativas** (`ButtonSymbols.NoButtons`), que eran minúsculas y el clic a veces no acertaba, y el valor sigue siendo editable a mano (3 decimales).
  - `EphemerisPanel` (fecha con botones **◀ / ▶ día a día** + "Hoy", "LUNA", fase lunar dibujada con `QPainterPath` sin recorte, `DayNightBar` día/crepúsculo/noche, puesta/salida y noche astronómica; **el cuadro llena su celda**: su container usa `addWidget(panel, 1)` — sin el `addStretch(1)` posterior, que se tragaba el sobrante y dejaba el hueco medido de **177 px** antes de Ubicación en 1919×1026 — y el aire interior se reparte con stretches (**Luna ×1, Puesta de Sol ×3, Noche astronómica ×3**): la `DayNightBar` va **sin stretch y de altura fija (44 px**, `DAY_NIGHT_BAR_HEIGHT` — petición del usuario: **no crece ni con los datos ni con el sobrante** del cuadro, que se lo llevan los dos rótulos de abajo—) y pinta su franja a la altura disponible (`max(14, height−20)` = 24 px a esa altura); el rótulo de la sección se **renombró** de «LUZ DEL DÍA Y NOCHE ASTRONÓMICA» a **«PUESTA DE SOL Y NOCHE ASTRONÓMICA»**, y las dos etiquetas llevan `AlignVCenter` para que el texto no quede pegado arriba. El **eje de la barra es dinámico, como el de la curva**: de **1 h antes de la puesta del Sol a 1 h después de la salida** (`set_marks` → `hour_range()`, en horas locales desenvueltas para cruzar la medianoche; sin puesta/salida, día completo 00–24 h), con marcas **`HH:MM` cada 2 h** dentro del rango (`tick_hours()`: sube sola a 3/4/6 h si no caben y descarta etiquetas repetidas — p. ej. los dos «00:00» de un día completo—); los hitos (puesta/ocaso/amanecer/salida) que caen fuera del rango no se pintan), `TransitCurve` (PyQtGraph, **un solo eje izquierdo** 0-90°, sin eje derecho — se retiró con la curva de separación y el umbral, para que la gráfica ocupe todo el ancho —, en `GroupFrame` con título/estado en azul; **dos curvas**: altitud del objeto (azul) y **altitud de la Luna** (gris `COLOR_MOON`, entrada/salida y altura máxima visibles sobre el eje), bandas Ideal/Posible/noche con `_BandPool`; subtítulo con **Separación** y **Mínimo** (texto, sin línea de umbral) y una línea de rangos **Captura Ideal / Captura Posible** con horarios y duración (`window_lines`, rangos unidos con « y »; la ★ de Ideal va **envuelta en `<span>` verde** #22c55e — igual que la banda y la ■ de la leyenda — porque sin él tomaba el color azul del texto y se perdía sobre la interfaz); leyenda `Altitud · 30° · Luna · Ideal · Posible`; **eje horario dinámico** de 1 h antes a 1 h después de la noche astronómica — sin noche, la muestra completa — y **fija de verdad**: sin zoom de rueda ni arrastre), `WeatherCards` (6 tarjetas con **título corto y color propio**: Seeing verde, Nubosidad azul, Humedad cian, Rocío ámbar, Viento violeta, Transparencia turquesa; aviso genérico «Falta conectar la API del clima» — o «API guardada: integración pendiente» cuando ya hay key — con el detalle en el tooltip, que apunta a Configuración general), `MetricCard` (acepta `title_color`).
  - Helpers: `fmt_hhmm`, `iso_to_local_hours`, `unwrap_hours`, `format_duration`, `window_lines`, `phase_name`; locales de `widgets.py`: `_contiguous_spans`, `_step_of` y `_BandPool` (una banda = pool de `LinearRegionItem`, un item por tramo).
- `busqueda.py` — `BusquedaTab`: **rejilla 3×2 repartida a la baja** (a la ventana por defecto 1280×800 las filas miden ~309 / 309 / 103 px —reparto 3:3:1—; sus mínimos son 264 (filtros/objetos) / 237 (efemérides/curva) / 99 (ubicación/clima) + 2×8 de spacing = **616 px**; en la ventana mínima 1024×640 solo caben 577 px, así que las dos primeras filas se comprimen ligeramente, sin recortes visibles): Filtros | **Catálogo** (tabla; el panel se titula «Catálogo», antes «Objetos por filtro»), Efemérides | Curva, Ubicación | Condiciones meteorológicas. Tabla de 10 columnas: `#`, ID (en azul), Tipo, Constelación, Mag, RA J2000, Dec J2000, Tamaño, **Tránsito**, **Horas >30°**; **todas las celdas centradas**, igual que sus cabeceras (antes Mag/Tránsito/Horas iban a la derecha y el resto a la izquierda); **filas a 42 px** y **sobrante de ancho repartido en proporción** (`_spread_surplus`, sin `stretchLastSection`); botón "⭐ Añadir a Mi Lista" arriba a la derecha. Señales `object_selected` y `add_to_personal`.
- `catalogo_personal.py` — `CatalogoPersonalTab`: tabla de objetos y regiones con quitar / editar notas / añadir región (`RegionDialog`). Señales `target_selected` y `region_added`.
- `planificacion.py` — `PlanificacionTab`: barra Target/Fecha/Equipo, `PlanetarioVisual` con **editor de encuadre** (RA/Dec/FOV/teselas, sincronizado con la vista), `TransitCurve`, **Plan de captura** (`best_dates`, 30 noches → top 5) y **Parámetros de sesión** con "💾 Guardar sesión". Señales `session_saved` y `target_changed`.
- `sesiones.py` — `SesionesTab`: tabla con Editar / Marcar completada / Eliminar (`EditSessionDialog`). Señal `sessions_changed`.
- `planetario_visual.py` — lienzo de cielo con QPainter (proyección gnomónica, norte arriba, 41 487 estrellas y 15 159 objetos; zoom con rueda y arrastre que sigue al cursor). Expone `set_target`, `set_center`, `set_framing`, `clear_framing`, `view` y `reset_view`, y las señales `object_clicked`, `region_clicked` y `view_changed`. Hoy lo usa Planificación; más adelante será la pestaña Planetario.

El **cableado** entre subpestañas vive en `PlannerPage` (`ui/main_window.py`), nunca aquí: ninguna subpestaña importa a otra.

## Qué hacer aquí — las 4 subpestañas

### 1. Búsqueda
- Filtros (buscar, tipo, catálogo, constelación, magnitud, altitud mínima, orden) → tabla (`planners/celestial_search.py`, `limit=500`).
- Al seleccionar una fila: **curva de tránsito** (`planners/transit.night_curve`) con **altitud del objeto y de la Luna** (gris: salida/ocaso y altura máxima), línea de 30°, banda de noche y ventanas Captura Ideal/Posible (`planners/moon_distance`, **sin banda de transición**: la zona ±2° se retiró); el subtítulo da separación y mínimo en texto más los rangos horarios de las dos ventanas (★ verde / ⚠ ámbar). La curva es **fija** (solo se actualiza con objeto/fecha/filtros/ubicación) y el eje va de 1 h antes a 1 h después de la noche astronómica.
- Rejilla 3×2: fila 1 = Filtros | Tabla; fila 2 = **efemérides Sol y Luna** (fecha editable, luna, barra día/noche, puesta/salida, noche astronómica) | curva; fila 3 = **barra de Ubicación** | 6 tarjetas de clima/seeing (mock → "Sin datos").
- "Añadir a Mi Lista" emite `add_to_personal`; **no** escribe en la base directamente.

### 2. Catálogo Personal
- Tabla de lo guardado (`planners/personal_catalog.py`). Las **regiones de interés** se crean aquí (`RegionDialog`) y **no se pintan en el planetario** (decisión del usuario).
- Al seleccionar una fila emite `target_selected` → Planificación cambia de target.

### 3. Planificación
- Planetario (clic → target si está guardado), encuadre desde el equipo (`planners/framing.calculate_fov`): **si faltan focal/resolución/píxel, el encuadre NO se activa** y el editor lo dice explícitamente.
- Curva de tránsito + Plan de captura (cursor de espera; ~1,5 s por cálculo) + guardar sesión.
- La región no aparece en el planetario, solo aquí como encuadre de referencia.

### 4. Sesiones planificadas
- `planners/planned_sessions.py`. **La pestaña Resumen las lee** para saber en qué sesión está el usuario.

### Reglas concretas de esta carpeta
- **Sin SQL ni cálculos astronómicos**: todo pasa por `planners/`. Aquí solo se compone y se formatea.
- Una sola conversión UTC → hora local: `planners.analytical_transit.local_utc_offset` (usa `utc_offset_hours` de la ubicación si existe; si no, el huso inferido de la longitud `round(lon/15)`). No duplicar la fórmula.
- Horas que cruzan la medianoche se desenvuelven con `moon_distance.unwrap_hours` antes de graficar o de resumir ventanas.
- Nunca inventar datos: sin clima → "Sin datos"; sin equipo → "Sin encuadre"; sin ubicación → "--".
- `QTableWidget(n, 0)` + `setHorizontalHeaderLabels` **no crea columnas**: pasar siempre `QTableWidget(0, ncols)`.
- **Nunca rellenar la tabla con la cabecera en `ResizeToContents`**: Qt recalcula el tamaño de todas las filas en cada `setItem` (~36 ms/celda con 500 filas = ~90 s de congelación). `_fill_table` la pone en `Interactive` durante el llenado, calcula los anchos una sola vez al final (~0,11 s) y llama a `_spread_surplus`, que reparte el ancho libre proporcionalmente (base estable `_content_widths`; **no** usar `stretchLastSection`, que volcaba todo el sobrante en «Horas >30°»).
- pyqtgraph 0.14 **no hace lo que parece**: `LinearRegionItem.setRegion` pinta **un solo tramo** por item (los pares extra se ignoran → bandas con `_BandPool`, un item por tramo) e `InfiniteLine` usa `angle=0` para horizontal y 90 para vertical (al revés de lo que sugiere el nombre). Ante la duda, captura + inspección de píxeles.
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.

## Planes futuros
1. Planetario completo: paneles de objeto, región de interés visible al hacer zoom, medición angular.
2. Ranking de objetos desde Planificación (`planners/ranking.py`) con pesos editables por el usuario.
3. Editor de encuadre con mosaicos y vista previa de teselas reales.
4. i18n de todos los textos (`i18n/es.ts`, `i18n/en.ts`).
