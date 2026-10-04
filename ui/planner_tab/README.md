# ui/planner_tab/ — Pestaña Planificador (corazón del programa)

## Qué es
El núcleo de PAS.S: buscar objetos, evaluar cuándo fotografiarlos, guardar los que interesan y concretar sesiones de captura. Tiene **4 subpestañas** en este orden: **Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**.

**Cada subpestaña tiene su propia carpeta con su propio `README.md`** (4 secciones fijas + esquema ASCII del estado actual):

| Carpeta | Subpestaña | Contenido |
|---|---|---|
| `busqueda/` | 1. Búsqueda | Rejilla 3×2: filtros, tabla del catálogo, efemérides Sol/Luna, curva de tránsito, ubicación y clima. **Aquí vive la `LocationBar`.** |
| `catalogo_personal/` | 2. Catálogo Personal | Objetos guardados y regiones; señales `target_selected` / `region_added`. |
| `planificacion/` | 3. Planificación | Planetario (`planetario_visual.py`), editor de encuadre, curva, plan de captura y «Guardar sesión». |
| `sesiones/` | 4. Sesiones Planificadas | Tabla de sesiones + Editar / completar / eliminar. |

## Estado actual
Carpeta **implementada** y probada (105 tests + render offscreen + arranque real de `python main.py`), reorganizada en **una carpeta por subpestaña** (cada una con su README y su esquema):

- `__init__.py` — re-exporta `BusquedaTab`, `CatalogoPersonalTab`, `PlanificacionTab`, `SesionesTab` y `LocationBar`: la API pública no cambió (`from ui.planner_tab import …` sigue igual que antes de la reorganización).
- `widgets.py` (raíz) — **compartido por las 4 subpestañas**, con su sección aquí:
  - `LocationBar` (combo de `locations` + lat/lon + huso, compacta en 3 filas: "📍 Ubicación" / Lat / Lon + Huso). **Única fuente de verdad** de latitud, longitud y `utc_offset_hours` para las 4 subpestañas. Vive **solo en Búsqueda** (fila 3, columna izquierda); `PlannerPage` la expone como `location_bar` y Planificación la recibe por señal. Si hay ubicaciones guardadas selecciona la primera; si no, no inventa un punto (aviso "escribe lat/long"; el combo ofrece "Manual — escribe aquí"). El huso ofrece **«Auto» = huso inferido de la longitud** (`round(lon/15)`, nunca la hora del sistema) y horas de reloj fijas (override político: España +1/+2, India +5.5…). Lat y lon se mueven con **◀ / ▶ de 34 px** (`_stepper`: un clic = 1°); spinbox sin flechitas nativas (`ButtonSymbols.NoButtons`), valor editable a mano (3 decimales).
  - `EphemerisPanel` (fecha con botones ◀ / ▶ + "Hoy", "LUNA" con fase dibujada, `DayNightBar`, puesta/salida y noche astronómica; **el cuadro llena su celda** sin el `addStretch(1)` que dejaba un hueco de 177 px, aire interior **Luna ×1 / Puesta ×3 / Noche ×3**, `DayNightBar` de **altura fija 44 px** que no crece ni con datos ni con el sobrante — se lo llevan los dos rótulos —, rótulo **«PUESTA DE SOL Y NOCHE ASTRONÓMICA»**, **eje dinámico** de 1 h antes de la puesta a 1 h después de la salida con marcas `HH:MM` cada 2 h que suben a 3/4/6 h si no caben).
  - `TransitCurve` (PyQtGraph, un solo eje izquierdo 0-90°, en `GroupFrame`; dos curvas: altitud del objeto en azul y de la Luna en gris, bandas Ideal/Posible/noche con `_BandPool`; subtítulo con Separación y Mínimo; rótulo **★ en verde `#22c55e`** envuelto en `<span>`; **la línea «★ Captura Ideal / ⚠ Captura Posible» se reserva con texto en blanco desde el arranque** — ocultarla subía el mínimo del panel +21 px y refluía toda la rejilla—).
  - `WeatherCards` (6 tarjetas clima/seeing, mock → "Sin datos"), `MetricCard`, `MoonPhaseWidget`.
  - Helpers: `fmt_hhmm`, `iso_to_local_hours`, `unwrap_hours`, `format_duration`, `window_lines`, `phase_name` y el **formato de catálogo compartido** `format_ra` / `format_dec` / `format_size` / `_type_label` + `TYPE_LABELS` (en `busqueda.py` hasta la reorganización; se mudó aquí para que Catálogo Personal no importara de Búsqueda).
- El **cableado** entre subpestañas vive en `PlannerPage` (`ui/main_window.py`), nunca en estas carpetas: ninguna subpestaña importa a otra.

## Qué hacer aquí
- **Reglas globales de las 4 subpestañas** (el detalle de cada una, en su README):
  - **Sin SQL ni cálculos astronómicos**: todo pasa por `planners/`. Aquí solo se compone y se formatea.
  - Una sola conversión UTC → hora local: `planners.analytical_transit.local_utc_offset`. No duplicar la fórmula.
  - Horas que cruzan la medianoche se desenvuelven con `moon_distance.unwrap_hours` antes de graficar o resumir.
  - Nunca inventar datos: sin clima → "Sin datos"; sin equipo → "Sin encuadre"; sin ubicación → "--".
  - `QTableWidget(n, 0)` + `setHorizontalHeaderLabels` **no crea columnas**: pasar siempre `QTableWidget(0, ncols)`.
  - **Nunca rellenar la tabla con la cabecera en `ResizeToContents`** (~36 ms/celda con 500 filas = ~90 s de congelación): `_fill_table` la pone en `Interactive`, calcula anchos una vez y llama a `_spread_surplus` (sin `stretchLastSection`).
  - pyqtgraph 0.14: `LinearRegionItem.setRegion` pinta **un solo tramo** por item (bandas con `_BandPool`) e `InfiniteLine` usa `angle=0` para horizontal y 90 para vertical. Ante la duda, captura + inspección de píxeles.
  - Al modificar cualquier subcarpeta: actualizar **su** README ("Estado actual") en la misma tarea; si cambia el conjunto, este índice.
- Cada subcarpeta nueva nace con su `README.md` de 4 secciones (lo garantiza `test_every_code_folder_has_readme`).

## Planes futuros
1. **Rediseño de Planificación** aprobado y pendiente (especificación en `C:\Users\Usuario\.opencode\plan\plan-rediseno-planificacion.md`) — detallado en `planificacion/README.md`.
2. Ranking de objetos desde Planificación (`planners/ranking.py`) con pesos editables por el usuario.
3. Planetario completo (paneles de objeto, región visible al hacer zoom, medición angular).
4. i18n de todos los textos (`i18n/es.ts`, `i18n/en.ts`), empezando por esta pestaña.
