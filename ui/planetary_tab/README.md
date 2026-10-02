# ui/planetary_tab/ — Pestaña Planetario

## Qué es
Planetario virtual estilo Stellarium para encuadre y planificación: el usuario ve el cielo desde su ubicación y evalúa cómo queda cada objeto.

## Estado actual
- Carpeta sin código (placeholder en `ui/main_window.py`).

## Qué hacer aquí
- Renderizar las **dos esferas concéntricas** de `planetary/` (fondo DSS2 + puntos de objetos) con el usuario al centro.
- **Sin proyección rectangular** (descartada por rendimiento en versiones anteriores).
- Interacción: navegar por el cielo, seleccionar objetos por clic, ajustar campo de visión.
- Aquí SOLO widgets/renderizado: los datos y la lógica vienen de `planetary/`.

## Planes futuros
1. Vista de esfera con texturas DSS2 y capa de puntos.
2. Selección de objetos y salto desde/hacia el Planificador.
3. Herramientas de encuadre y mosaico.
