# stacks/

## Qué es
Integración de PAS.S con **SirIL** para calibrar, auditar y apilar sesiones completadas. SirIL es una herramienta externa (CLI): aquí NO se programa ningún motor propio de calibrado o apilado.

## Estado actual
- `siril_finder.py` — detección de SirIL: PATH del sistema → ruta guardada por el usuario en `settings` (`siril_path`), vía los helpers de `db.settings`.
- `session_parser.py` — detecta estructura de cada sesión (`lights`, `flats`, `darks`, `bias`, `dark_flats` y carpeta `masters/`).
- `calibrator.py` — calibración **automática** por sesión → salida a `data/working/calibrados/<sesion>/`.
- `global_pool.py` — pool global de **referencias** a los lights calibrados (cero copias).
- `registration.py` — registro con SirIL desde el pool.
- `metrics.py` — métricas de SirIL (FWHM, redondez, transparencia), gráficas, ranking y descarte de extremos.
- `stacker.py` — apilado con todas las opciones de SirIL (drizzle, rechazo, ponderación, integración) + multihilo.
- **Solo `siril_finder.py` está operativo**: `session_parser`, `calibrator`, `global_pool`, `registration`, `metrics` y `stacker` son hoy stubs (`NotImplementedError`) — las líneas anteriores describen el diseño previsto para la fase del Apilador, no el estado actual.

## Qué hacer aquí
- **Reglas duras (no negociables):**
  1. Los originales de sesión son **solo lectura**: jamás modificar ni borrar nada en la carpeta de la sesión.
  2. **Prohibido copiar ficheros en cadena**: se trabaja por rutas/referencias; la única escritura es la salida de calibración en la carpeta de trabajo.
  3. Todo procesamiento lo ejecuta SirIL (CLI); no reimplementar algoritmos de SirIL.
- Detectar SirIL con `find_siril()`; si devuelve `None`, la UI ofrece seleccionar la ruta.
- Exponer las opciones de SirIL tal cual (no inventar límites); documentar cada parámetro aquí.
- Aprovechar todos los hilos de la CPU en registro y apilado.

## Planes futuros
1. Parser real de sesiones y detección de másters.
2. Calibración automática por sesión con SirIL.
3. Pool global + registro + extracción de métricas y auditoría.
4. Apilado completo con opciones de SirIL y progreso en la UI.
