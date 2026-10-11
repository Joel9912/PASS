# i18n/

## Qué es
Traducciones de la interfaz con el **sistema nativo de Qt**: ficheros `.ts` (fuente, XML) y `.qm` (compilados) que carga `QTranslator`.

## Estado actual
- `es.ts` y `en.ts` — plantillas XML vacías; no contienen traducciones todavía.
- Los `.qm` compilados no están en el repo: se generan con las herramientas de Qt.

## Qué hacer aquí
- Al integrar i18n, marcar los textos visibles de la UI con `self.tr(...)`; hoy no están traducidos.
- Actualizar las traducciones: `pylupdate6 <ficheros .py> -ts i18n/es.ts i18n/en.ts` (pylupdate6 ya está en el venv).
- Compilar a `.qm`: `lrelease i18n/es.ts` (si no está disponible, instalar Qt Linguist o usar `pylupdate6` + toolchain de Qt).
- Cargar en `main.py`: `QTranslator` con el idioma de `settings` (clave `language`, por defecto `es`).
- Al añadir un texto nuevo: recorrer ambos `.ts`; nunca dejar `es.ts` desactualizado.

## Planes futuros
1. Integrar `QTranslator` en `main.py`.
2. Selector de idioma (español/inglés) en Ajustes.
