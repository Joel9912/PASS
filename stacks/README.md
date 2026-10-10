# stacks/

## Qué es
Integración de SirIL **externo** por CLI. Los originales se leen, nunca se modifican; calibración, registro y apilado los realiza SirIL, no PASS.

## Estado actual
- `session_parser.py` — sesiones, alias de carpetas, FITS/RAW, ficha de cabeceras (CROTA2, elevación del sitio en metros y `OBJCTALT` del objeto en grados, sin confundirlos) y campo angular si la escala o focal/píxel lo permiten.
- `siril_finder.py` — binario CLI desde PATH o la ruta que aporta el llamante (settings lo lee la UI, A-03), versión con `--version`.
- `siril_runner.py` — scripts por stdin, ini aislado, progreso/cancelación, binario capturado en UI por contexto de tarea, enlaces symlink→hardlink y limpieza restringida a `data/working/`. El log visible muestra el guion y omite líneas `HDU` repetitivas y controles ANSI; el resultado conserva la salida íntegra. El borrado explícito valida rutas y desenlaza sin seguir enlaces a originales.
- `calibrator.py` — másters, calibración cruda por sesión y persistencia en `calibrated_sessions` desde el hilo UI; la carpeta global configurada se pasa al worker como dato. El log identifica procedencia, enlaces y medianas FITS sin atribuir unidades ADU a valores normalizados.
- `global_pool.py` — referencias a los lights calibrados, sin copias.
- `registration.py` — auditoría `register -2pass` reutilizable solo con manifiesto de lights y secuencia coincidentes; registro final (debayer **o** drizzle) con encuadre, escala, pixfrac, kernel y flat explícito.
- `frame_metrics.py` — lectura `.seq`, conversión del fondo normalizado de SirIL a ADU equivalentes de 16 bits/s (÷ exposición), puntuación y recomendaciones; la transparencia es un proxy relativo del fondo, no una medición directa. El usuario decide qué descartar.
- `stacker.py` — opciones de `stack` (rechazo/mapas, normalización, precisión, RGB), apilado por canal y composición R/G/B inequívoca. Exportación exclusiva de FITS finales a la carpeta madre sin sobrescribir.

## Qué hacer aquí
- **Nunca** escribir/borrar originales ni copiar frames en cadena. Limpiar solo subcarpetas ancladas a `WORKING_FOLDER`; detenerse si symlink y hardlink fallan (otros volúmenes/permisos).
- Solo SirIL procesa píxeles; astropy/numpy leen FITS y sirven a las miniaturas de UI. No acceder a SQLite desde el worker.
- La gramática de SirIL se comprueba con el CLI instalado en Windows, no se presupone compatible por pasar mocks.

## Planes futuros
- Ampliar la matriz E2E real a másters bias/dark/flat, errores y cancelación con sesiones sintéticas/autorizadas. Ya se comprobó en Windows SirIL 1.4.4: mono, CFA sin/con drizzle ×2 y R/G/B con `rgbcomp` (hashes de originales intactos).
