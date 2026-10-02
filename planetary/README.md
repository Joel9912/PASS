# planetary/

## Qué es
Planetario virtual de PAS.S: **dos esferas concéntricas** con el usuario en el centro — una con imágenes DSS2 de fondo y otra con los puntos de los objetos (Messier, NGC, IC, LDN).

## Estado actual
- `catalog.py` — modelo `CelestialObject` y contrato de carga de los 4 catálogos (datos pendientes).
- `dss2_sphere.py` — esfera de imágenes DSS2 con caché local de JPG (`data/dss2_cache/`).
- `object_sphere.py` — esfera de puntos con selección por clic y filtrado por campo de visión.
- Implementaciones pendientes (`NotImplementedError`).

## Qué hacer aquí
- **Diseño fijo: dos esferas + usuario al centro.** SIN proyección rectangular (probada en versiones anteriores y descartada por rendimiento).
- Las imágenes DSS2 se descargan una sola vez y se cachean localmente; no re-descargar lo ya guardado.
- Este módulo es lógica pura de visualización de datos: la UI (widgets OpenGL/QPainter) vive en `ui/planetary_tab/`.

## Planes futuros
1. Carga de catálogos reales (ficheros de Messier/NGC/IC/LDN).
2. Renderizado de la esfera DSS2 con texturas.
3. Capa de puntos con interacción y encuadre para planificación de mosaicos.
