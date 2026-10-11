# PASS — Registro de bugs y hallazgos

Fuente única de verdad sobre problemas del proyecto: aquí vive cada bug encontrado (auditorías, revisiones y tareas corrientes), con su ID, severidad y estado. Otros documentos no repiten esta lista; solo enlazan a ella.

## Cómo se usa

- **ID**: `<ÁREA>-<NNNN>` — letra del área + 4 dígitos secuenciales **dentro del área**. El número se asigna al registrar y **nunca se reutiliza**, aunque el bug se cierre.
- **Severidad**: 🔴 Grave (pierde o corrompe datos, procesa mal en silencio o bloquea el arranque) · 🟠 Medio (comportamiento erróneo visible, sin pérdida) · 🟡 Bajo (detalles, deuda, rendimiento por medir).
- **Estado**: ✅ Corregido (con commit) · 🟡 Contenido (mitigado; queda trabajo) · ⏳ Pendiente (falta reproducir o corregir) · 🔎 Sin reproducir (hace falta medir o confirmar) · ⛔ Bloqueado por una decisión del usuario.
- Un bug corregido **no se borra**: se pasa a ✅ con su commit. La historia vive en git.
- **Todo agente que audite o corrija escribe aquí**: registrar en la misma tarea el hallazgo nuevo, y cerrar el que se arregle. Si un fix cambia el comportamiento visible, `CHANGELOG.md` y el README de la carpeta se actualizan aparte (R1/R3).

## Áreas

| Letra | Área |
|---|---|
| **B** | Datos y base de datos (`db/`, catálogos, migraciones) |
| **E** | Equipo (`equipment/`, `ui/equipment_tab/`) |
| **S** | Apilador (`stacks/`, `ui/stacker_tab/`, SirIL) |
| **P** | Planificación, clima y planetario lógico (`planners/`) |
| **U** | Interfaz (`ui/`, Qt) |
| **C** | Configuración y arranque |
| **L** | Fugas de memoria y recursos |
| **T** | Tests y entorno de pruebas |
| **X** | Documentación |

## Resumen

**87 hallazgos**: 🔴 17 graves · 🟠 44 medios · 🟡 17 bajos · ⛔ 9 decisiones.
Estado: ✅ 21 corregidos · 🟡 3 contenidos · ⏳ 48 pendientes · 🔎 6 sin reproducir · ⛔ 9 bloqueados.

---

## 🔴 Graves

| ID | Bug | Evidencia | Estado |
|---|---|---|---|
| **S-0001** | Calibrar una sesión cuyo origen vivía dentro de `working/calibrados` borraba las tomas originales al limpiar el destino. | `stacks/calibrator.py` (`calibrate_session`); test `test_calibrar_conserva_el_origen_vivo_bajo_calibrados` | ✅ `264b5d0`, `5df5e12` |
| **S-0002** | Dos sesiones homónimas de raíces distintas compartían la carpeta de calibrado; la UI marcaba como «calibrada» la que no lo estaba, heredaba sus exposiciones/fichas y el pool se quedaba con una sola. | `ui/stacker_tab/__init__.py`, `stacks/global_pool.py` | ✅ `5df5e12` |
| **S-0003** | La ruta completa de la sesión llegaba al nombre de enlace de SirIL: ficheros con `:` y `\`, imposibles de crear en Windows. | `stacks/registration.py` (`_preparar_secuencia`, `_debayerizar`) | ✅ `5df5e12` |
| **S-0004** | Nombres idénticos de lights entre filtros distintos colisionan en disco. | `stacks/session_parser.py` | ⏳ |
| **S-0005** | Índices o salidas de registro incompletos o mal nombrados se admiten como válidos: métricas atribuidas al frame equivocado. | `stacks/registration.py` | ⏳ |
| **S-0006** | Restos de corridas anteriores en la carpeta de registro se usan como si fueran de la corrida actual. | `stacks/registration.py` | ⏳ |
| **S-0007** | Filtros con nombres normalizados idénticos sobrescriben el mismo canal. | `stacks/session_parser.py` | ⏳ |
| **B-0001** | La migración de BD v1 hacía `DROP COLUMN` sobre `telescope_name` poblado, perdiendo el dato del usuario. | `db/connection.py` (`_drop_legacy_columns`) | 🟡 `264b5d0` (contenida; migración pendiente → **E-0011**) |
| **B-0002** | Una conexión SQLite cuyo esquema fallaba quedaba publicada y era reutilizable en el proceso. | `db/connection.py` (`get_connection`) | ✅ `e3993a7` |
| **B-0003** | Una descarga del catálogo vacía o truncada se validaba, borraba y confirmaba el catálogo del usuario. | `db/catalog_loader.py`, `db/ldn_loader.py` (`_download_tap`) | ⏳ |
| **E-0001** | Dos adjuntos con el mismo nombre se sobrescribían al guardarlos en una entidad de Equipo. | `equipment/images.py` | ✅ `ec6d2ee` |
| **E-0002** | Un filtro inexistente confirmaba el equipo y la imagen antes de que la FK fallara (estado a medias en BD). | `equipment/manager.py` | 🟡 `183b2b1` (valida IDs antes de escribir; falta transacción global → **E-0012**) |
| **P-0001** | El tránsito UTC del día vecino puede puntuar con la Luna o la altura de la fecha equivocada. | `planners/capture_plan.py` | ⏳ |
| **P-0002** | Las mejores noches pueden quedar sin ventana de captura (criterio de recomendación). | `planners/capture_plan.py` | ⏳ |
| **U-0001** | `_metric_text` lanzaba `KeyError('value')` con valores numéricos en la respuesta del worker. | `ui/planner_tab/widgets.py` | ✅ `0a04cee` |
| **T-0001** | `pytest` a secas migraba y escribía la BD real del usuario y descargaba en `data/downloads`. | `tests/conftest.py` (sandbox) | ✅ `b9118a4` |
| **T-0002** | Un test escribía, actualizaba y borraba sesiones planificadas en la BD real: se perdió el objeto `M31` del usuario. | `tests/test_planners.py` | ✅ `0407ba9` (recuperar M31 requiere autorización y copia previa) |

## 🟠 Medios

| ID | Bug | Evidencia | Estado |
|---|---|---|---|
| **B-0004** | Objetos nuevos del Catálogo Personal no aparecían tras guardarlos (reportado por el usuario). | `ui/planner_tab/catalogo/`, `db/personal_catalog.py` | 🔎 no reproducido con el snapshot actual; hacen falta IDs y pasos concretos |
| **B-0005** | El arranque bloquea la ventana hasta 120 s si la red está lenta (`ensure_catalog` antes de pintar). | `main.py` | ⏳ |
| **B-0006** | La conexión SQLite del hilo principal no debe pasar a hilos Qt; regla a vigilar en cada tarea (hoy cumplida por diseño). | `ui/**/worker`, `stacks/siril_runner.py` | ⏳ revisión continua |
| **S-0008** | Mezcla de RAW y FITS en una misma sesión no se rechaza pese al contrato declarado. | `stacks/session_parser.py` | ⏳ |
| **S-0009** | Una carpeta creada por una calibración fallida bloquea el reintento: `exists()` cuenta como «ya calibrada». Sigue vigente tras **S-0002**. | `ui/stacker_tab/__init__.py` (`calibrar`) | ⏳ |
| **S-0011** | `_hilo` se libera al recibir el resultado y no al emitir `finished`. | `ui/stacker_tab/worker.py` | ⏳ |
| **S-0012** | `wait(3000)` sobre tareas Python sin cancelación cooperativa puede congelar el cierre. | `ui/stacker_tab/worker.py` | ⏳ |
| **S-0013** | Un error al escribir en stdin podría dejar un hijo de SirIL vivo. | `stacks/siril_runner.py` | 🔎 sin reproducir |
| **S-0014** | Solo se valida el primer FITS como 16-bit; el resto de la sesión se asume correcto. | `stacks/calibrator.py` | ⏳ |
| **S-0015** | Un `EXPTIME` textual puede hacer fallar el escaneo completo de la sesión. | `stacks/session_parser.py` | ⏳ |
| **S-0016** | `exportar_apilados` acepta un origen arbitrario por API aunque la UI pase la carpeta de trabajo. | `stacks/stacker.py` | ⏳ |
| **E-0003** | Una pieza usada en dos roles deja el formulario y los totales desactualizados tras editar o borrar. | `ui/equipment_tab/componentes.py` | ⏳ |
| **E-0004** | El precio de un filtro editado no repinta el total hasta otra interacción. | `ui/equipment_tab/equipos.py` | ⏳ |
| **E-0005** | `NaN`/infinito y precio o peso negativos no se filtran antes de persistir un setup. | `equipment/validaciones.py` | ⏳ |
| **E-0006** | Bortle/SQM no cambia el color base del disco en la rosacea. | `ui/equipment_tab/rosaceas.py` | ⏳ |
| **E-0007** | Una fuente de Claridad de Luz >100 km se trunca en el slider al editar otra propiedad. | `ui/equipment_tab/rosaceas.py` | ⏳ |
| **E-0008** | Las claves de FOV no usaban la focal efectiva del reductor. | `equipment/metrics.py` | ✅ auditoría anterior |
| **E-0009** | Los borrados de piezas no comprobaban usos en sesiones/setups ni sus cascadas. | `equipment/manager.py` | ✅ auditoría anterior |
| **E-0010** | Imágenes de equipo con nombre homónimo podían sobrescribirse. | `equipment/images.py` | ✅ auditoría anterior |
| **P-0003** | El factor lunar se puntúa en el tránsito diurno en vez de dentro de la ventana de captura. | `planners/capture_plan.py` | ⏳ |
| **P-0004** | Cálculo incorrecto en latitudes altas (geometría polar). | `planners/capture_plan.py`, `planners/night_curve.py` | ⏳ |
| **P-0005** | El tránsito se ordena tras el `LIMIT` y desplaza la ventana elegida. | `planners/capture_plan.py` | ⏳ |
| **P-0006** | La noche polar queda truncada en el cálculo de ventanas. | `planners/night_curve.py` | ⏳ |
| **P-0007** | Alias NGC/IC tratados de forma inconsistente al resolver el objetivo. | `planners/catalog.py` | ⏳ |
| **P-0008** | Una duración puede exceder el intervalo de la ventana por un paso. | `planners/capture_plan.py` | ⏳ |
| **P-0009** | La separación lunar diurna se usa en el ranking de noches. | `planners/capture_plan.py` | ⏳ |
| **P-0010** | La excepción de un proveedor de clima en hilo secundario rompía la consulta (las claves se leían desde el hilo de trabajo). | `ui/planner_tab/busqueda/weather` | ✅ `0a04cee` |
| **U-0002** | Arrastrar la vista no actualiza el encuadre visible antes de guardar. | `ui/planner_tab/planificacion/tab.py` | ⏳ |
| **U-0003** | Quitar el último target deja el plan y el planetario obsoletos. | `ui/planner_tab/planificacion/tab.py` | ⏳ |
| **U-0004** | Si la región no está en el cielo, el target anterior queda resaltado. | `ui/planner_tab/planetario` | ⏳ |
| **U-0005** | Añadir un duplicado recarga la lista y puede cambiar la selección. | `ui/planner_tab/catalogo/` | ⏳ |
| **C-0001** | Se admiten umbrales de sub/sobremuestreo contradictorios entre sí. | `ui/config_tab/`, `equipment/metrics.py` | ⏳ |
| **C-0002** | Configuración guarda varias claves sin atomicidad: un fallo a mitad deja ajustes a medias. | `ui/config_tab/` | ⏳ |
| **C-0003** | Editar la ruta de SirIL deja el ✓ de «encontrado» obsoleto hasta reabrir. | `ui/config_tab/` | ⏳ |
| **T-0003** | La suite depende de los catálogos reales del usuario; faltan fixtures offline sintéticos. | `tests/conftest.py` | 🟡 `b9118a4` (sandbox; falta independencia) |
| **T-0004** | Fixtures que usan red o estrellas reales: inestables según el día y la ubicación. | `tests/` | ⏳ |
| **T-0005** | Symlinks en fixtures: no portables en Windows. | `tests/` | ⏳ |
| **T-0006** | Tests con geometría dependiente de temporizadores o DPI de la pantalla. | `tests/test_dialogos.py`, `tests/test_stacker_tab.py` | ⏳ |
| **T-0007** | El modo offscreen se activa con `setdefault` y puede no aplicarse. | `tests/conftest.py` | ⏳ |
| **X-0001** | El README raíz contradice la GPL al prohibir la venta. | `README.md` | ⏳ |
| **X-0002** | El README raíz describe un ranking de objetos que no existe. | `README.md` | ⏳ |
| **X-0003** | El README raíz presenta el Planetario como dependiente de red. | `README.md` | ⏳ |
| **X-0004** | `planners/README.md` mantiene como pendiente un CRUD ya implementado. | `planners/README.md` | ⏳ |
| **X-0007** | `tests/README.md` describe la UI offscreen y la cobertura del README de forma errónea. | `tests/README.md` | ⏳ |

## 🟡 Bajos

| ID | Bug | Evidencia | Estado |
|---|---|---|---|
| **B-0007** | `_download_tap` referencia `urllib.request` sin import directo: `NameError` latente. | `db/ldn_loader.py` | 🔎 sin reproducir con proceso limpio |
| **S-0017** | Las previews de auditoría cargan el FITS entero en el hilo de UI. | `ui/stacker_tab/pasos_common.py` | 🔎 medir antes de priorizar |
| **S-0018** | El stdout de SirIL y la terminal crecen sin límite en corridas largas. | `ui/stacker_tab/__init__.py` | 🔎 medir |
| **S-0019** | Código muerto (símbolos sin consumidores) acumulado en `stacks/` y `ui/`. | pin en `tests/test_codigo_muerto.py` | ✅ auditoría anterior |
| **L-0001** | QMenu y paneles efímeros con parent retenidos: posible fuga de widgets. | `ui/equipment_tab/` | 🔎 medir hijos tras N ciclos |
| **L-0002** | Los diálogos acumulaban hijos ocultos al cerrar (fuga medida 20/20). | `ui/dialogs/` | ✅ auditoría anterior (`deleteLater()`) |
| **U-0006** | El `QDateEdit` de «Editar sesión» no reflejaba la fecha seleccionada. | `ui/planner_tab/` | ✅ auditoría anterior |
| **X-0005** | `i18n/` declara traducciones vacías como si fueran válidas. | `i18n/` | ⏳ stub conocido |
| **X-0006** | Búsqueda decía «sin datos hasta que haya API key» aunque hubiera claves. | `ui/planner_tab/busqueda/README.md` | ✅ `d45a2d8` |
| **X-0008** | `tests/README.md` atribuía la BD a `siril_finder`. | `tests/README.md` | ⏳ |
| **X-0009** | `tests/README.md` citaba rutas y tests equivocados. | `tests/README.md` | ⏳ |
| **X-0010** | El README de Configuración atribuía la persistencia a `siril_finder`. | `ui/config_tab/README.md` | ✅ `d45a2d8` |
| **X-0011** | Resumen y `STRUCTURE.md` presentaban como actual un flujo aún futuro. | `ui/summary_tab/README.md`, `STRUCTURE.md` | ✅ `d45a2d8` |
| **X-0012** | Los totales del catálogo se repetían en `MEMORY.md` (violación R2). | `MEMORY.md` | ✅ `18c384e` |
| **X-0013** | Roadmap histórico obsoleto en `MEMORY.md`. | `MEMORY.md` | ✅ `d45a2d8` |
| **X-0014** | Errata «conversión» en el README de planificación. | `ui/planner_tab/planificacion/README.md` | ✅ `d45a2d8` |
| **X-0015** | Prosas extensas en la documentación frente a la regla de brevedad (R3). | varios `README.md` | ⏳ poda continua |

## ⛔ Decisiones pendientes (bloquean una corrección)

| ID | Decisión | Alternativas | Estado |
|---|---|---|---|
| **E-0011** | Cómo migrar los datos de equipos v1 embebidos (telescopio, cámara, montura) sin borrarlos ni inventar piezas. | Diseñar migración 1→2 · pedir al usuario que asigne piezas existentes · mantener la migración detenida | ⛔ |
| **E-0012** | Política ante un fallo a mitad de guardado de Equipo (transacción global + compensación de imágenes). | Revertir todo · confirmar a medias · guardar por partes explícitas | ⛔ |
| **E-0013** | Qué representa el «total» guardado de un setup: datos persistidos o ediciones del formulario. | Persistir todo al guardar · etiquetar el total como «sin guardar» | ⛔ |
| **S-0010** | Comportamiento con secuencias nuevas: si se piden métricas `wfwhm/nbstars` que SirIL no vuelve a calcular. | Pedirlas solo si existen · recalculadas · ocultar la columna | ⛔ |
| **P-0011** | DST y zona horaria reales frente a un offset fijo por ubicación. | Offset fijo · zona IANA con `zoneinfo` · avisar del cambio de hora | ⛔ |
| **U-0007** | Al planificar: seleccionar la noche sugerida o la fecha guardada por el usuario. | Siempre la sugerida · siempre la guardada · preguntar | ⛔ |
| **U-0008** | Precedencia del FOV: la región del objetivo o el encuadre del equipo. | Región manda · equipo manda · mostrar ambos con aviso | ⛔ |
| **C-0004** | Ruta de SirIL guardada por el usuario frente a la detección del PATH. | PATH primero · guardada primero · preguntar en cada corrida | ⛔ |
| **B-0008** | `add_region` con nombre repetido usa `INSERT OR IGNORE`: ¿preservar, avisar o editar? | Preservar y avisar · rechazar el duplicado · fusionar | ⛔ |

## ❌ Falsos positivos descartados

- El `LEFT JOIN` del catálogo preserva las entradas personales aunque se refresque el catálogo base.
- `exportar_apilados` ya escribe con `xb` (sobrescritura bloqueada).
- La limpieza explícita rechaza rutas fuera de `data/working/`.
- Los proveedores de clima son mocks declarados: no hay llamadas reales ocultas.
- `planetary/` e `i18n/` son stubs conocidos, no implementaciones rotas.
- No se atribuyen fugas a Qt sin medición previa.

## Equivalencias con los IDs de la auditoría

El informe de auditoría (`C:\Users\Usuario\.opencode\plan\informe-auditoria-integral-pass.md`) usa el esquema antiguo `<severidad>-<área>-<nn>` (p. ej. `C-STK-01` = S-0002, `M-STK-01` = S-0009, `C-DAT-01` = S-0001, `C-DAT-02` = B-0001, `C-EQP-01` = E-0001, `C-EQP-02` = E-0002, `C-UI-01` = U-0001, `A-32` = P-0010, `M-14` = L-0002, `N-1` = U-0006). **Este archivo manda**: los IDs nuevos se registran aquí, con este esquema.
