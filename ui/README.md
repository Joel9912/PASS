# ui/

## Qué es
Capa de interfaz de usuario (PyQt6). Una subcarpeta por pestaña principal de PAS.S; **solo** contiene widgets, layouts y pantallas — sin lógica de negocio ni cálculos astronómicos (eso vive en `planners/`, `stacks/`, `equipment/`, `planetary/`).

## Estado actual
- `main_window.py` — `MainWindow` con **barra lateral izquierda colapsable** (iconos por pestaña + texto, ☰ para colapsar, Configuración abajo), área de contenido con `QStackedWidget`, pie con nombre + versión (`v0.1`) y la constante `TABS`.
  - `PlannerPage` (antes `_planner_page`) es la página del Planificador: **4 subpestañas en el orden Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**. La `LocationBar` vive **dentro de Búsqueda** (rejilla 3×2, fila 3 izquierda) y `PlannerPage` la expone como `location_bar` para que Planificación la reciba por señal. Aquí se concentra todo el cableado entre subpestañas (ninguna importa a otra).
  - Las demás pestañas son páginas placeholder ("Funcionalidad en construcción").
- `style.py` — tema oscuro azulado (QSS con paleta única), fuente base 13pt, `apply_style(app)`. Campos de entrada con padding compacto (`3px 8px`, incluye `QDateEdit`/`QDateTimeEdit`) y pie a 11pt/2px: el espacio que necesita la rejilla de Búsqueda. Incluye los objectNames de las reglas del Planificador (`PanelTitle`, `SectionTitle`, `MetricCard`, `MetricTitle`, `MetricValue`, `ApplyFilters`, `PrimaryButton`, `CurveTitle`, `CurveSubtitle`, `CurveLegend`, `GroupFrame`, `HintLabel`).
- `planner_tab/` — **implementado** (4 subpestañas, planetario visual, curva de tránsito en PyQtGraph). **Cada subpestaña tiene su propia carpeta con su propio `README.md`** (con esquema ASCII del estado actual): `planner_tab/busqueda/`, `planner_tab/catalogo_personal/`, `planner_tab/planificacion/` (incluye `planetario_visual.py`), `planner_tab/sesiones/`; el módulo de cada una es `tab.py` y el `__init__.py` de cada carpeta re-exporta su clase. Lo compartido sigue en `planner_tab/widgets.py` (raíz). Ver el README índice `planner_tab/README.md`.
- `config_tab/` — **implementado**: diálogo modal «Configuración General de la Aplicación» (nav General/Clima: SirIL con estado real, carpeta base `project_root` y API keys del clima en `settings`). Se abre con la ⚙ de la barra lateral **al instante** (el diálogo se reutiliza y la comprobación de SirIL corre en segundo plano); tras «Guardar» refresca el clima de Búsqueda. Ver su README.
- `summary_tab/`, `planetary_tab/`, `equipment_tab/`, `planner_equip_tab/`, `stacker_tab/` — solo `README.md` (contenido pendiente).

## Qué hacer aquí
- Al implementar una pestaña: crear su módulo en `ui/<pestaña>/` y actualizar su `README.md` (sección "Estado actual") en la misma tarea.
- La UI llama a la lógica de backend; **nunca** la reimplementa (sin SQL, sin cálculos astronómicos aquí).
- Cada carpeta nueva nace con su `README.md` de 4 secciones fijas (ver `AGENTS.md`).

## Planes futuros
- Implementar el contenido de las 5 pestañas que faltan (Resumen, Planetario, Equipo, Planificador de Equipo, Apilador).
- Aplicar i18n (`i18n/es.ts`, `i18n/en.ts`) a todos los textos visibles, empezando por `planner_tab/`.
- **Arranque perezoso de las páginas (M-02)**: `MainWindow` construye las 6 páginas de golpe y el planetario carga todas las estrellas en el constructor. *Medido en la auditoría: el arranque total es 1,51 s y el planetario solo 110 ms de ellos (el grueso son los imports de astropy) → **bajado a «aquí no»**: solo si crece la lista de pestañas.*
- **Bajos de la auditoría de código** (refactors pequeños, sin comportamiento nuevo):
  - `except Exception` amplios que tapan fallos de BD (`widgets.py` en la barra de ubicación, `sesiones/tab.py`).
  - Señales emitidas sin consumidor (`object_selected`, `target_changed`, `region_clicked` — este último rompe su propio docstring — y `sky_at_center()` sin llamantes): cablearlas o quitarlas.
  - `_on_date_changed` es copia literal de `refresh()`; la búsqueda por `object_id` está duplicada en `select_target` y en el clic del planetario.
  - Patrones repetidos → helpers en `widgets.py`: «fila seleccionada → dict» ×4, bloque de config de `QTableWidget` ×4, mapa `setup_id → nombre` ×2.
  - Colores de estado escritos a mano pese a `PALETTE` (5 archivos), `ROW_H = 46` duplicado, variable muerta `catalog` (`planificacion/tab.py`).
  - `_transparency`/`phase_name` (reglas de negocio) viven en `widgets.py` en vez de en `planners/`.
  - `WeatherCards.refresh()` llamará la API real en el hilo de UI (hoy mocks; revisar al activar las keys).
  - Dos fechas independientes Búsqueda/Planificación sin sincronizar (¿intencional? documentar).
  - `fmt_hhmm` vs `_format_hours`: elegir una sola.
