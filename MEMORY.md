# Estado Actual y Planes del Programa PAS.S

## 📅 Situación Actual (3 de Octubre 2026)

| Aspecto | Estado |
|---------|--------|
| **Etapa de desarrollo** | Esqueleto completo + **`planners/` implementado** + **pestaña Planificador implementada** (4 subpestañas); resto de pestañas aún placeholder |
| **Estructura de carpetas** | ✅ Creada: `db/`, `planners/`, `stacks/`, `equipment/`, `planetary/`, `ui/` (6 pestañas), `i18n/`, `tests/`, `data/` |
| **Docs** | ✅ Raíz: README, AGENTS, PROGRAM, MEMORY, STRUCTURE + LICENSE GPL-3.0 + requirements.txt |
| **Entry point** | ✅ `main.py` con tema oscuro, barra lateral colapsable, pie `v0.1` y las 6 pestañas; carga catálogos al arrancar; se abre **maximizado** |
| **Tests** | ✅ pytest: **142 tests** (`test_smoke`, `test_settings`, `test_weather`, `test_planners`, `test_dialogos`, `test_equipment` + módulos `moon_distance`, `framing`, `analytical_transit`, `capture_plan`, `ldn_loader`) |
| **Librerías Python** | Instaladas en venv: PyQt6 6.11, **pyqtgraph 0.14.0**, astropy 8.0, numpy 2.5, PyYAML 6.0, pytest |
| **Catálogos astronómicos** | ✅ OpenNGC (13,372 objetos) + HYG (41,487 estrellas mag ≤ 8) + **LDN (1,787)** en `data/pass.db` |
| **Pestaña Planificador** | ✅ `ui/planner_tab/`: Búsqueda → Catálogo Personal → Planificación → Sesiones Planificadas, planetario QPainter, curva de tránsito PyQtGraph (doble eje), plan de captura, barra de ubicación compartida |
| **Integración SirIL** | Diseñada en `stacks/` (detección PATH + ruta usuario); sin implementar |
| **APIs clima/seeing** | Clear Outside + Meteoblue con mocks (sin API keys todavía) → tarjetas "Sin datos" |
| **Persistencia** | ✅ SQLite (stdlib) con esquema completo + migración de columnas (`_MIGRATIONS` en `db/connection.py`) |
| **i18n** | Estructura `i18n/es.ts` + `en.ts` creada; sin integrar en `main.py` |

## 📋 Planes Corto Plazo (Próximos 1-3 meses)

### Objetivos Principales
1. **UI de las pestañas pendientes** — estado y detalle en «Próximos Pasos» y en el README de cada carpeta.

2. **Sistema básico de gestión de equipos**
   - CRUD básico (Crear, Leer, Actualizar, Borrar) de setups de equipo
   - Guardar equipos en formato local/JSON/archivo de texto
   - Asociación de localizaciones geográficas

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
   - Flujo de trabajo calibración → astrofotometría → apilamiento
   - Auditoría automática de sesiones
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
| **Descuidar la planificación por el apilado** | PAS.S se vuelve "otro procesador de imágenes" | Enfocarse en roadmap: planificación primero, procesamiento segundo |
| **Estructura de MDs inconsistente** | Agentes pierden contexto, tiempo perdido en adivinar | MDs por carpeta obligatorios, formato estandarizado |

## 📊 Roadmap Visual

```
MES 1-3                          MES 4-6                          MES 7-12
│                                  │                                  │
│   Estructura base         │   UI funcional                   │   Feature avanzadas
│   MDs por carpeta        │   Navegación tabs                │   Comparativas completas
│   Gestión equipos         │   Búsquedas básicas              │   Inteligencia artificial
│   APIs astronómicas       │   Planetario básico              │   Integración SirIL profunda
│                          │                                  │   Recomendaciones automáticas
```

## 💡 Próximos Pasos Inmediatos
*(solo pendientes: lo completado vive en «Situación Actual»)*

1. 🔜 UI de `equipment_tab`: crear/editar localizaciones (con su `utc_offset_hours`) y setups — hace falta para que `LocationBar` deje de estar vacía
2. 🔜 UI de `planner_equip_tab`: comparativa con las métricas que defina el usuario (`RankingWeights`, `CaptureWeights` expuestos)
3. 🔌 Llamadas reales a Clear Outside/Meteoblue cuando haya API keys
4. 🔌 i18n (`QTranslator` + `.ts/.qm`) empezando por `planner_tab/`
5. 📂 Documentos de plan (fuera del repo): `plan-rediseno-planificacion.md` (rediseño de Planificación) e `informe-auditoria-codigo.md` (auditoría: Tanda A/B aplicadas).
6. 🔜 Tanda C de la auditoría de código (M-17, M-18, M-20, D-5, D-6, D-8) — junto al paso 1 (Equipo).