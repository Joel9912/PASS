# ui/config_tab/ — Diálogo de Configuración

## Qué es
El diálogo **«Configuración General de la Aplicación»** que abre el botón ⚙: API keys del clima, ruta de SirIL y carpeta base de proyectos. Solo interfaz; la persistencia vive en `db/settings.py` y `stacks/siril_finder.py`.

## Estado actual
- `__init__.py` — exporta `ConfigDialog`.
- `config_dialog.py` — `ConfigDialog(QDialog)` con **nav lateral de 3 secciones** (🔧 General / 🌧 Clima / 🔭 Equipo) y páginas apiladas:
  - **General**:
    1. *Motor de Procesamiento (SirIL)* — campo de ruta + «📁 Examinar...» + **estado comprobado en segundo plano**: `reload()` rellena y llama a `_check_siril()`; sin SirIL o con ruta mala el aviso sale **ya mismo** («no se encontró» en ámbar / «la ruta no existe» en rojo); si existe, «⏳ Comprobando SirIL…» mientras `_BRIDGE.probe()` corre `siril_version()` en `_EXECUTOR` (1 hilo) y la señal `checked` pinta «✓ Siril x.y detectado y operativo.» en verde o «no responde» en ámbar.
    2. *Carpeta Base de Proyectos* — directorio raíz (`settings`, clave `project_root`) + «Examinar...» + hint.
  - **Clima**: API keys de **Clear Outside** y **Meteoblue** (modo contraseña con casilla «Mostrar las claves») → `save_api_key` en `settings`.
  - **Equipo**: grupo **«Muestreo»** con los 2 umbrales del bloque «Cálculos» (`sampling_under_ratio` 1,0 / `sampling_over_ratio` 0,5; `QDoubleSpinBox` > 0 escritos con `set_setting` en el mismo «Guardar»). Sin señal `saved`: el bloque los relee en cada recálculo.
  - Pie: **Guardar** (escribe todo de una vez y emite `saved`) / **Cerrar** (descarta; ✕ igual).
- Cableado en `MainWindow._show_settings` (`ui/main_window.py`): **el diálogo se crea una sola vez y se reutiliza** (`self._config_dialog`); al reabrir solo `reload()`. Al emitirse `saved` se llama a `BusquedaTab.refresh_weather()` para refrescar sin repetir la búsqueda.
- Tests en `tests/test_smoke.py`: `test_config_dialog_*` (abre sin esperar a SirIL, avisos instantáneos, pintado del resultado y señal encolada desde el hilo) y `test_show_settings_keeps_one_dialog`.
- Estilo: `#ConfigNav` en `ui/style.py` (mismo lenguaje que `#NavList`) y objectNames reutilizados (`GroupFrame`, `PanelTitle`, `HintLabel`, `PrimaryButton`).

## Qué hacer aquí
- Tareas típicas: añadir secciones al nav (con su página), nuevos campos de `settings`, validar rutas antes de guardar.
- **Reglas concretas**: nada de lógica de negocio ni SQL — solo leer con los helpers (`get_setting`, `load_api_key`, `find_siril`) y escribir con (`set_setting`, `save_api_key`, `save_user_path`); las API keys jamás en código ni en el repositorio.
- **Nunca congelar la interfaz**: lo que ejecuta SirIL va por `_BRIDGE.probe()` / `_EXECUTOR` (hilo aparte), nunca en el hilo de la UI; los avisos de ruta mala sí salen ya mismo porque no hay nada que arrancar.
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.
- Los textos de estado mientan solo lo comprobado (versión real de SirIL, no «está instalado» sin ejecutarlo).

## Planes futuros
1. Secciones nuevas cuando lleguen: Apilado (criterios de descarte de frames) y pesos del plan de captura.
2. Traducción de los textos (`i18n/es.ts`, `i18n/en.ts`).
3. Detección de versiones mínimas de SirIL si el CLI exige funciones concretas.
