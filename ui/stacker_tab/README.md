# ui/stacker_tab/ — Pestaña Apilador

## Qué es
Cargar sesiones completadas, calibrarlas automáticamente, auditarlas con las métricas de SirIL y apilarlas con todas las opciones de SirIL.

## Estado actual
- Carpeta sin código (placeholder en `ui/main_window.py`); la lógica vive en `stacks/`.

## Qué hacer aquí

### Carga de sesiones
- Mostrar las sesiones detectadas (`stacks/session_parser.py`): lights, flats, darks, bias, dark flats y másters por sesión.
- Resumen por sesión: nº de lights por día → **tiempo de exposición total** (lo consume Resumen).

### Calibración (automática)
- Un botón calibra cada sesión con SirIL → salida en `data/working/calibrados/<sesion>/` (`stacks/calibrator.py`).
- Mostrar progreso; **nunca tocar los originales** (solo lectura).

### Auditoría
- Tras registrar (`stacks/registration.py`): gráficas de FWHM, redondez y transparencia a lo largo de sesiones (`stacks/metrics.py`).
- Ranking de frames y descarte de valores extremos, con confirmación del usuario.

### Apilado
- Exponer **todas** las opciones de SirIL (`stacks/stacker.py`): drizzle, criterios de rechazo, ponderación, integración.
- Si SirIL no está en el PATH (`stacks/siril_finder.py`), pedir al usuario que seleccione la ruta.
- Usar todos los hilos de la CPU y mostrar progreso.
- **Prohibido copiar ficheros en cadena**: la UI trabaja con los datos ya referenciados por el pool.

## Planes futuros
1. Carga e inspección de sesiones.
2. Calibración con progreso.
3. Auditoría con gráficas y descarte.
4. Apilado con opciones completas de SirIL.
