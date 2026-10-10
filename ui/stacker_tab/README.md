# ui/stacker_tab/ — Pestaña Apilador

## Qué es
Asistente PyQt6 que organiza el flujo de SirIL sin ejecutar cálculos de procesado en la UI.

## Estado actual
- `__init__.py` — `StackerPage`: Sesiones → Calibrar → Auditar → Apilar → Final, navegación, barra y log plegable, orquestación y persistencia desde el hilo principal. Auditoría ofrece reutilizar un registro coincidente; Apilar siempre exige revisar frames y opciones. Calibrar ofrece conservar o limpiar con confirmación.
- `pasos_common.py` — helpers compartidos de los cinco paneles: formato de fichas FITS y regiones, banners, tabla genérica, estilos QSS, miniaturas de auditoría (`_preview_fits`, `_estirar`) y `configurar_pyqtgraph()` (antialias + fondo, que la página llama al construirse: nada de estado global al importar).
- `paneles/` — un módulo por paso (`sesiones`, `calibrar`, `auditar`, `apilar`, `final`), re-exportados en su `__init__.py` (API: `from ui.stacker_tab.paneles import …`). Sesiones con banner, tabla y fichas FITS de solo lectura (sin flechas; altura `OBJCTALT` visible y elevación del observatorio en el detalle); Auditoría con pesos, tabla y visor FITS con autoestirado moderado solo en pantalla. Apilar admite nombre vacío para usar el tiempo integrado; Final usa el mismo estirado y permite abrir el FITS en SirIL gráfico.
- `visor_sesiones.py` — carta del FOV usando los catálogos/estrellas y proyección de Planificación (solo consulta y navegación, sin crear regiones), marco de captura con rotación CROTA2 si existe, botón Telescopius visible e inerte y capas de texto de la referencia (FOV, rotación, leyenda de catálogos, centro y coordenadas). «Ver FITS» alterna con la imagen original, sin modificarla, y solo aparece cuando hay FITS legible. Sin RA/Dec no se inventa región.
- `worker.py` — `QThread` cancelable: progreso, log, resultado y parada de SirIL al cancelar/cerrar.

## Qué hacer aquí
- Mantener originales solo lectura, casillas de descarte bajo control del usuario y SQL fuera del worker. Usar `stacks/` para todas las fases SirIL.
- Si falta CLI, permitir escaneo pero impedir las fases de procesado; escoger en Windows un ejecutable que responda a `--version`.
- Exportar únicamente el FITS final a la carpeta madre común; nunca reemplazar un archivo existente.
- Al introducir controles SirIL, verificar opciones con la versión efectivamente instalada y probar UI en escritorio real.

## Planes futuros
- Integrar Telescopius cuando se defina su comportamiento; verificar orientación/WCS por cámara y revisión a otras escalas DPI.
