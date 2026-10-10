# Estado Actual y Planes del Programa PASS

## 📅 Situación Actual (10 de Octubre 2026)

| Aspecto | Estado |
|---------|--------|
| **Etapa de desarrollo** | `v0.1` (alpha): pestañas Planificador, Equipo y Apilador implementadas; Resumen, Planetario y Planificador de Equipo aún placeholder |
| **Repositorio público** | ✅ GitHub `Joel9912/PASS`, tag `v0.1-alpha` (10/10/2026); historia conservada desde la primera versión |
| **Licencia** | ✅ GPL-3.0: libre para usar/modificar/vender, pero las versiones derivadas deben publicar su código (no se puede apropiar ni cerrar) |
| **Estructura de carpetas** | ✅ Creada: `db/`, `planners/`, `stacks/`, `equipment/`, `planetary/`, `ui/` (6 pestañas), `i18n/`, `tests/`, `data/` |
| **Docs** | ✅ Raíz: README, PROGRAM, MEMORY, STRUCTURE + LICENSE GPL-3.0 + requirements.txt |
| **Auditoría de código** | ✅ Tandas A, B y C aplicadas (deuda C cerrada 4/10/2026); pendientes anotados: M-02, D-4, D-7 y bajos (§4 del informe) |
| **Entry point** | ✅ `main.py` con tema oscuro, barra lateral colapsable, pie `v0.1` y las 6 pestañas; carga catálogos al arrancar; se abre **maximizado** |
| **Tests** | ✅ pytest (recuento y lista por módulo en `tests/README`) |
| **Librerías Python** | Instaladas en venv: PyQt6 6.11, **pyqtgraph 0.14.0**, astropy 8.0, numpy 2.5, PyYAML 6.0, pytest |
| **Catálogos astronómicos** | ✅ OpenNGC (13 372 objetos) + HYG (41 487 estrellas mag ≤ 8) + **LDN (1 787)** en `data/pass.db` |
| **Pestaña Planificador** | ✅ `ui/planner_tab/`: Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas, planetario QPainter, curva de tránsito PyQtGraph (un eje), plan de captura, barra de ubicación compartida |
| **Pestaña Equipo** | ✅ `ui/equipment_tab/` (4/10/2026): equipos con componentes globales (Telescopio/Cámara/Montura/Filtros) y bloque «Cálculos» con umbrales configurables; ubicaciones v2 con rosácea de 3 discos (orientación/obstrucciones/CL) y esquemático de horizonte; backend `equipment/` CRUD completo + validaciones + `metrics.py`; cableado Equipo → Planificador en `main_window.py` |
| **Integración SirIL** | Flujo de cinco pasos en `stacks/` + `ui/stacker_tab/`; probado con SirIL CLI 1.4.4 Windows sobre FITS sintéticos mono, CFA sin/con drizzle ×2 y R/G/B con `rgbcomp` (originales intactos). |
| **APIs clima/seeing** | Clear Outside + Meteoblue con mocks (sin API keys todavía) → tarjetas "Sin datos" |
| **Persistencia** | ✅ SQLite (stdlib) con esquema completo + migración de columnas (`_MIGRATIONS` en `db/connection.py`) |
| **i18n** | Estructura `i18n/es.ts` + `en.ts` creada; sin integrar en `main.py` |

## 📋 Planes Corto Plazo (Próximos 1-3 meses)

### Objetivos Principales
1. **UI de las pestañas pendientes** — estado y detalle en «Próximos Pasos» y en el README de cada carpeta.

2. **Sistema de gestión de equipos (resto)**
   - Guardar equipos en formato local/JSON/archivo de texto (exportar/importar)
   - Duplicar setups

3. **Integración con APIs astronómicas**
   - API abierta para búsqueda de objetos (posición, fecha)
   - Integración con servicios de clima astronómico
   - API para ver seeing y condiciones atmosféricas

## 🚀 Planes Largo Plazo (Meses 6-12)

### Módulos Avanzados
1. **Algoritmo comparativo completo de equipos**
   - Métricas personalizables por usuario (presupuesto, apertura, focal length, peso, etc.)
   - Sistema de puntuación comparativa
   - Visualización de trade-offs (compromisos)

2. **Planetario virtual avanzado (Stellarium-like)**
   - Renderizado 3D de cielo en tiempo real
   - Integración con bases de datos de objetos Deep Sky
   - Herramientas de mosaico y planificación de campo

3. **Integración profunda con SirIL**
   - Ampliar pruebas reales Windows a másters bias/dark/flat y cancelación
   - Plantillas de procesamiento predefinidas

4. **Recomendaciones inteligentes de equipo**
   - Análisis de: "Para este objetivo en esta ubicación/fecha, este equipo es óptimo"
   - Consideración de: presupuesto, habilidad del usuario, objetivos a largo plazo
   - Historial de decisiones y resultados

## ⚠️ Puntos Críticos a Evitar

| Riesgo | Consecuencia | Mitigación |
|--------|-------------|-----------|
| **Programar motor de apilado propio** | Distracción del objetivo principal, código spaghetti | **QUEDARÍA EXPLÍCITAMENTE PROHIBIDO** - solo integrar SirIL |
| **Especificar métricas impositivas** | Usuario se siente limitado, valor del proyecto disminuye | Las métricas son definidas y ajustables por el usuario |
| **Descuidar la planificación por el apilado** | PASS se vuelve "otro procesador de imágenes" | Enfocarse en roadmap: planificación primero, procesamiento segundo |
| **Estructura de MDs inconsistente** | Agentes pierden contexto, tiempo perdido en adivinar | MDs por carpeta obligatorios, formato estandarizado |

## 📊 Roadmap Visual

```
  MES 1-3                      MES 4-6                      MES 7-12
│ Estructura base              │ UI funcional                │ Feature avanzadas
│ MDs por carpeta              │ Navegación tabs             │ Comparativas completas
│ Gestión equipos              │ Búsquedas básicas           │ Inteligencia artificial
│ APIs astronómicas            │ Planetario básico           │ Integración SirIL profunda
│                              │                             │ Recomendaciones automáticas
```

## 💡 Próximos Pasos Inmediatos
*(solo pendientes: lo completado vive en «Situación Actual»)*

1. 🔍 **Auditoría técnica post-v0.1** — recorrer `stacks/`, `ui/`, `planners/` y `equipment/` con el método de auditoría: informe con IDs, deudas y prioridades (código muerto, imports, docstrings, malas prácticas).
2. 🧹 **Refactor en commits pequeños** — arreglos de la auditoría, uno por tema, cada uno con su test de regresión; `STRUCTURE.md` al día si cambia la estructura.
3. 🔜 UI de `planner_equip_tab`: comparativa con las métricas que defina el usuario (`RankingWeights`, `CaptureWeights` expuestos)
4. 🔌 Llamadas reales a Clear Outside/Meteoblue cuando haya API keys
5. 🔌 i18n (`QTranslator` + `.ts/.qm`) empezando por `planner_tab/`
