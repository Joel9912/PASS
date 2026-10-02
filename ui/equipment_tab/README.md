# ui/equipment_tab/ — Pestaña Equipo

## Qué es
Gestión del equipo que el usuario ya tiene: sus setups (telescopio + cámara + montura), sus ubicaciones y las imágenes adjuntas.

## Estado actual
- Carpeta sin código (placeholder en `ui/main_window.py`).

## Qué hacer aquí
- Formularios de alta/edición de setups con **datos fríos** (apertura, focal, cámara refrigerada/resolución/bits, montura) usando `equipment/models.py` y `equipment/manager.py`.
- Gestión de localizaciones (`equipment/localizations.py`).
- Adjuntar imágenes al setup (`equipment/images.py`): **solo visuales**, el programa no las analiza.
- Categorías de setup: campo amplio, nebulosas, galaxias (planetario: futuro).

## Planes futuros
1. CRUD completo de setups y localizaciones.
2. Adjuntar/visualizar imágenes (spot, etc.).
3. Duplicar setups y exportar/importar configuraciones.
