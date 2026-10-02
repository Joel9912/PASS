# ui/planner_tab/ — Pestaña Planificador (corazón del programa)

## Qué es
El núcleo de PAS.S: buscar objetos, evaluar cuándo fotografiarlos, guardar los que interesan y concretar sesiones de captura. Tiene **4 subpestañas** en este orden: **Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**.

## Estado actual
Carpeta **implementada** y probada (render offscreen + arranque real de `python main.py`):

- `__init__.py` — documenta el orden de las subpestañas y exporta `BusquedaTab`, `CatalogoPersonalTab`, `PlanificacionTab`, `SesionesTab`, `LocationBar`.
- `widgets.py` — componentes compartidos:
  - `LocationBar` (barra "📍 Ubicación para cálculos": combo de `locations` + lat/lon + huso). **Única fuente de verdad** de latitud, longitud y `utc_offset_hours` para las 4 subpestañas. Si hay ubicaciones guardadas selecciona la primera; si no, no inventa un punto (aviso "escribe lat/long").
  - `EphemerisPanel` (fecha, fase lunar dibujada con `QPainterPath`, `DayNightBar` día/crepúsculo/noche, puesta/salida y noche astronómica), `TransitCurve` (PyQtGraph, doble eje), `WeatherCards` (6 tarjetas), `MetricCard`.
  - Helpers: `fmt_hhmm`, `iso_to_local_hours`, `unwrap_hours`, `format_duration`, `window_lines`, `phase_name`.
- `busqueda.py` — `BusquedaTab`: rejilla de 2 columnas (filtros | tabla; efemérides | curva) + tarjetas de clima abajo. Tabla de 10 columnas: `#`, ID, Tipo, Constelación, Mag, RA J2000, Dec J2000, Tamaño, **Tránsito**, **Horas >30°**. Señales `object_selected` y `add_to_personal`.
- `catalogo_personal.py` — `CatalogoPersonalTab`: tabla de objetos y regiones con quitar / editar notas / añadir región (`RegionDialog`). Señales `target_selected` y `region_added`.
- `planificacion.py` — `PlanificacionTab`: barra Target/Fecha/Equipo, `PlanetarioVisual` con **editor de encuadre** (RA/Dec/FOV/teselas, sincronizado con la vista), `TransitCurve`, **Plan de captura** (`best_dates`, 30 noches → top 5) y **Parámetros de sesión** con "💾 Guardar sesión". Señales `session_saved` y `target_changed`.
- `sesiones.py` — `SesionesTab`: tabla con Editar / Marcar completada / Eliminar (`EditSessionDialog`). Señal `sessions_changed`.
- `planetario_visual.py` — lienzo de cielo con QPainter (proyección gnomónica, norte arriba, 41 487 estrellas y 15 159 objetos; zoom con rueda y arrastre que sigue al cursor). Expone `set_target`, `set_center`, `set_framing`, `clear_framing`, `view` y `reset_view`, y las señales `object_clicked`, `region_clicked` y `view_changed`. Hoy lo usa Planificación; más adelante será la pestaña Planetario.

El **cableado** entre subpestañas vive en `PlannerPage` (`ui/main_window.py`), nunca aquí: ninguna subpestaña importa a otra.

## Qué hacer aquí — las 4 subpestañas

### 1. Búsqueda
- Filtros (buscar, tipo, catálogo, constelación, magnitud, altitud mínima, orden) → tabla (`planners/celestial_search.py`, `limit=500`).
- Al seleccionar una fila: **curva de tránsito** (`planners/transit.night_curve`) con altitud, separación lunar, línea de 30°, banda de noche y ventanas Captura Ideal/Posible (`planners/moon_distance`).
- Abajo-izquierda: **efemérides Sol y Luna** (fecha editable, fase, barra día/noche, puesta/salida, noche astronómica). Abajo-derecha: curva. Fondo: 6 tarjetas de clima/seeing (mock → "Sin datos").
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
- Una sola conversión UTC → hora local: `planners.analytical_transit.local_utc_offset` (usa `utc_offset_hours` de la ubicación si existe; si no, la longitud = hora solar). No duplicar la fórmula.
- Horas que cruzan la medianoche se desenvuelven con `moon_distance.unwrap_hours` antes de graficar o de resumir ventanas.
- Nunca inventar datos: sin clima → "Sin datos"; sin equipo → "Sin encuadre"; sin ubicación → "--".
- `QTableWidget(n, 0)` + `setHorizontalHeaderLabels` **no crea columnas**: pasar siempre `QTableWidget(0, ncols)`.
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.

## Planes futuros
1. Planetario completo: paneles de objeto, región de interés visible al hacer zoom, medición angular.
2. Ranking de objetos desde Planificación (`planners/ranking.py`) con pesos editables por el usuario.
3. Editor de encuadre con mosaicos y vista previa de teselas reales.
4. i18n de todos los textos (`i18n/es.ts`, `i18n/en.ts`).
