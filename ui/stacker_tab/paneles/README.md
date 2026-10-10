# ui/stacker_tab/paneles/

## Qué es
Los cinco paneles (pasos) del asistente de apilado: widgets puro-presentación, uno por módulo.

## Estado actual
- `sesiones.py` — paso 1: banner, tabla de tomas (con reparto de anchos propio) y fichas FITS de solo lectura; cartas FOV/estrellado con rotación.
- `calibrar.py` — paso 2: material disponible por sesión y acceso al calibrado.
- `auditar.py` — paso 3: pesos, tabla de métricas, gráfica pyqtgraph y visor FITS con autoestirado moderado (solo pantalla).
- `apilar.py` — paso 4: integración, norma, ponderación, rechazo y salida.
- `final.py` — paso 5: resumen del apilado y apertura del FITS en SirIL gráfico.
- `__init__.py` — re-exporta los 5 paneles: la API es `from ui.stacker_tab.paneles import PanelSesiones, …`.

## Qué hacer aquí
- Los paneles solo presentan: sus botones emiten señales y la orquestación vive en `ui/stacker_tab/__init__.py` (la página).
- Lo compartido (formato de fichas, QSS, tablas, miniaturas) va a `../pasos_common.py`, no duplicado en varios paneles.
- Cada cambio de comportamiento visible lleva su test en `tests/test_stacker_tab.py`.

## Planes futuros
- Ninguno previsto: la división resuelve el tamaño del antiguo `pasos.py` (2 382 líneas).
