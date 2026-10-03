# ui/config_tab/ — Diálogo de Configuración

## Qué es
El diálogo **«Configuración General de la Aplicación»** que abre el botón ⚙ de la barra lateral: guardado de API keys del clima, ruta de SirIL y carpeta base de proyectos. Solo interfaz; la persistencia vive en `db/settings.py` y `stacks/siril_finder.py`.

## Estado actual
- `__init__.py` — exporta `ConfigDialog`.
- `config_dialog.py` — `ConfigDialog(QDialog)` con **nav lateral de 2 secciones** (📋 General / 🌤 Clima) y páginas apiladas:
  - **General**:
    1. *Motor de Procesamiento (SirIL)* — campo de ruta + «📁 Examinar...» + **estado** con `siril_version()` («✓ Siril x.y detectado y operativo.» en verde, «no responde» en ámbar o «la ruta no existe» en rojo).
    2. *Carpeta Base de Proyectos* — directorio raíz (`settings`, clave `project_root`) + «Examinar...» + hint.
  - **Clima**: API keys de **Clear Outside** y **Meteoblue** (modo contraseña con casilla «Mostrar las claves») → `save_api_key` en `settings`.
  - Pie: **Guardar** (escribe todo de una vez y emite `saved`) / **Cerrar** (descarta; ✕ igual).
- Cableado en `MainWindow._show_settings` (`ui/main_window.py`): al emitirse `saved` se llama a `BusquedaTab.refresh_weather()` para refrescar las tarjetas sin repetir la búsqueda.
- Estilo: `#ConfigNav` en `ui/style.py` (mismo lenguaje que `#NavList`) y objectNames reutilizados (`GroupFrame`, `PanelTitle`, `HintLabel`, `PrimaryButton`).

## Qué hacer aquí
- Tareas típicas: añadir secciones al nav (con su página), nuevos campos de `settings`, validar rutas antes de guardar.
- **Reglas concretas**: nada de lógica de negocio ni SQL — solo leer con los helpers (`get_setting`, `load_api_key`, `find_siril`) y escribir con (`set_setting`, `save_api_key`, `save_user_path`); las API keys jamás en código ni en el repositorio.
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.
- Los textos de estado mientan solo lo comprobado (versión real de SirIL, no «está instalado» sin ejecutarlo).

## Planes futuros
1. Secciones nuevas cuando lleguen: Equipo (ubicación por equipo: lat/long/altitud/sqm), Apilado (criterios de descarte de frames) y pesos del plan de captura.
2. Traducción de los textos (`i18n/es.ts`, `i18n/en.ts`).
3. Detección de versiones mínimas de SirIL si el CLI exige funciones concretas.
