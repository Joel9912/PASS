# ui/

## Qué es
Capa de interfaz de usuario (PyQt6). Una subcarpeta por pestaña principal; **solo** widgets, layouts y pantallas — sin lógica de negocio ni cálculos astronómicos (eso vive en `planners/`, `stacks/`, `equipment/`, `planetary/`).

## Estado actual
- `main_window.py` — `MainWindow` con **barra lateral izquierda colapsable** (iconos por pestaña + texto, ☰ para colapsar, Configuración abajo), `QStackedWidget` de contenido, pie con nombre + versión (`v0.1`) y la constante `TABS`.
  - Las páginas reales salen de **`_PAGE_BUILDERS`** (dict por clave; sin entrada → placeholder): `planner_tab` → `PlannerPage`, `equipment_tab` → `EquipmentPage` y `stacker_tab` → `StackerPage`; ningún índice mágico de `TABS`.
  - `PlannerPage` es la página del Planificador: **4 subpestañas en el orden Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**. La `LocationBar` vive **dentro de Búsqueda** (rejilla 3×2, fila 3 izquierda) y `PlannerPage` la expone como `location_bar` para Planificación. Aquí se concentra el cableado entre subpestañas (ninguna importa a otra).
  - `_wire_equipo()` — Equipo → Planificador: `locations_changed` → `location_bar.reload()` + `reemit()`; `setups_changed` → `planificacion.reload_setups()` + `sesiones.refresh()`.
  - Resumen, Planetario y Planificador de Equipo siguen como placeholder.
- `style.py` — tema oscuro azulado (QSS con paleta única), fuente base 13pt, `apply_style(app)`. Campos de entrada con padding compacto (`3px 8px`, incluye `QDateEdit`/`QDateTimeEdit`), pie a 11pt/2px (la rejilla de Búsqueda) y los objectNames de las reglas del Planificador (lista en el código).
- `planner_tab/` — **implementado**: 4 subpestañas con planetario visual y curva de tránsito en PyQtGraph. Cada subcarpeta con su `README.md` y su módulo `tab.py`: `busqueda/`, `catalogo_personal/`, `planificacion/` (incluye `planetario_visual.py`), `sesiones/`; lo compartido en `planner_tab/widgets.py`. Índice: `planner_tab/README.md`.
- `config_tab/` — **implementado**: diálogo modal «Configuración General de la Aplicación» (nav General/Clima/Equipo: SirIL con estado real, carpeta base `project_root`, API keys del clima y umbrales de muestreo en `settings`). Se abre con la ⚙ **al instante** (diálogo reutilizado, comprobación de SirIL en segundo plano) y tras «Guardar» refresca el clima de Búsqueda. Ver su README.
- `equipment_tab/` — **implementado**: `EquipmentPage` con **Equipos** (lista, cabecera con «Guardar equipo», sub-subpestañas Telescopio/Cámara/Montura/Filtros, bloque «Cálculos») y **Ubicaciones** (ficha de sitio y CL). Ver su README.
- `stacker_tab/` — asistente de cinco pasos; Sesiones reutiliza la carta de catálogos de Planificación para el FOV capturado, con alternativa FITS y sin funciones del futuro Planetario principal. Ver su README.
- `summary_tab/`, `planetary_tab/`, `planner_equip_tab/` — solo `README.md` (contenido pendiente).

## Qué hacer aquí
- Al implementar una pestaña: crear su módulo en `ui/<pestaña>/` y actualizar su `README.md` (sección "Estado actual") en la misma tarea.
- La UI llama a la lógica de backend; **nunca** la reimplementa (sin SQL, sin cálculos astronómicos aquí).
- Cada carpeta nueva nace con su `README.md` de 4 secciones fijas (Qué es / Estado actual / Qué hacer aquí / Planes futuros).

## Planes futuros
- Implementar el contenido de las 3 pestañas que faltan (Resumen, Planetario, Planificador de Equipo).
- Aplicar i18n (`i18n/es.ts`, `i18n/en.ts`) a todos los textos visibles, empezando por `planner_tab/`.
- **Arranque perezoso de las páginas (M-02)**: hoy `MainWindow` construye las 6 páginas de golpe y el planetario carga sus estrellas en el constructor. Medido: 1,51 s de arranque total y solo 110 ms de planetario (el grueso son imports de astropy) → **bajado a «aquí no»**: solo si crece la lista de pestañas.
- **Bajos de la auditoría de código** (refactors pequeños, sin comportamiento nuevo):
  - `except Exception` amplios que tapan fallos de BD (`widgets.py` en la barra de ubicación, `sesiones/tab.py`).
  - Señales emitidas sin consumidor (`object_selected`, `target_changed`, `region_clicked` — rompe su docstring — y `sky_at_center()`): cablearlas o quitarlas.
  - `_on_date_changed` es copia literal de `refresh()`; la búsqueda por `object_id` está duplicada en `select_target` y en el clic del planetario.
  - Patrones repetidos → helpers en `widgets.py`: «fila seleccionada → dict» ×4, bloque de config de `QTableWidget` ×4, mapa `setup_id → nombre` ×2.
  - Colores de estado escritos a mano pese a `PALETTE` (5 archivos) y `ROW_H = 46` duplicado.
  - `_transparency`/`phase_name` (reglas de negocio) viven en `widgets.py` en vez de en `planners/`.
  - `WeatherCards.refresh()` llamará la API real en el hilo de UI (hoy mocks; revisar al activar las keys).
  - Dos fechas independientes Búsqueda/Planificación sin sincronizar (¿intencional? documentar).
