# ui/

## Qué es
Capa de interfaz de usuario (PyQt6). Una subcarpeta por pestaña principal de PAS.S; **solo** contiene widgets, layouts y pantallas — sin lógica de negocio ni cálculos astronómicos (eso vive en `planners/`, `stacks/`, `equipment/`, `planetary/`).

## Estado actual
- `main_window.py` — `MainWindow` con **barra lateral izquierda colapsable** (iconos por pestaña + texto, ☰ para colapsar, Configuración abajo), área de contenido con `QStackedWidget`, pie con nombre + versión (`v0.1`) y la constante `TABS`.
  - `PlannerPage` (antes `_planner_page`) es la página del Planificador: **4 subpestañas en el orden Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas**. La `LocationBar` vive **dentro de Búsqueda** (rejilla 3×2, fila 3 izquierda) y `PlannerPage` la expone como `location_bar` para que Planificación la reciba por señal. Aquí se concentra todo el cableado entre subpestañas (ninguna importa a otra).
  - Las demás pestañas son páginas placeholder ("Funcionalidad en construcción").
- `style.py` — tema oscuro azulado (QSS con paleta única), fuente base 13pt, `apply_style(app)`. Incluye los objectNames de las reglas del Planificador (`PanelTitle`, `SectionTitle`, `MetricCard`, `MetricTitle`, `MetricValue`, `ApplyFilters`, `PrimaryButton`, `CurveTitle`, `CurveSubtitle`, `CurveLegend`, `GroupFrame`, `HintLabel`).
- `planner_tab/` — **implementado** (4 subpestañas, planetario visual, curva de tránsito en PyQtGraph). Ver su README.
- `summary_tab/`, `planetary_tab/`, `equipment_tab/`, `planner_equip_tab/`, `stacker_tab/` — solo `README.md` (contenido pendiente).

## Qué hacer aquí
- Al implementar una pestaña: crear su módulo en `ui/<pestaña>/` y actualizar su `README.md` (sección "Estado actual") en la misma tarea.
- La UI llama a la lógica de backend; **nunca** la reimplementa (sin SQL, sin cálculos astronómicos aquí).
- Cada carpeta nueva nace con su `README.md` de 4 secciones fijas (ver `AGENTS.md`).

## Planes futuros
- Implementar el contenido de las 5 pestañas que faltan (Resumen, Planetario, Equipo, Planificador de Equipo, Apilador).
- Aplicar i18n (`i18n/es.ts`, `i18n/en.ts`) a todos los textos visibles, empezando por `planner_tab/`.
