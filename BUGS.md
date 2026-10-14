# PASS — Registro de bugs

Lista de los problemas encontrados en PASS y su estado. Cada entrada tiene un ID único y su severidad; la referencia de cada arreglo es el commit que se indica en su estado.

## Cómo leer esta lista

- **ID**: `<ÁREA>-<NNNN>` — letra del área + 4 dígitos secuenciales **dentro del área**. El número se asigna al registrar y **nunca se reutiliza**, aunque el bug se cierre.
- **Severidad**: 🔴 Grave (pierde o corrompe datos, procesa mal en silencio o bloquea el arranque) · 🟠 Medio (comportamiento erróneo visible, sin pérdida) · 🟡 Bajo (detalles, deuda, rendimiento por medir).
- **Estado**: ✅ Corregido (con su commit) · 🟡 Contenido (mitigado, queda trabajo) · ⏳ Pendiente · 🔎 Sin reproducir.

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

**100 hallazgos**: 🔴 18 graves · 🟠 55 medios · 🟡 18 bajos · 9 decisiones (7 pendientes).
Estado: ✅ 77 corregidos · 🟡 3 contenidos · ⏳ 10 pendientes · 🔎 1 sin reproducir.

---

## 🔴 Graves

| ID | Bug | Estado |
|---|---|---|
| **S-0001** | Calibrar una sesión cuyo origen vivía dentro de `working/calibrados` borraba las tomas originales al limpiar el destino. | ✅ `264b5d0`, `5df5e12` |
| **S-0002** | Dos sesiones homónimas de raíces distintas compartían la carpeta de calibrado; la UI marcaba como «calibrada» la que no lo estaba, heredaba sus exposiciones/fichas y el pool se quedaba con una sola. | ✅ `5df5e12` |
| **S-0003** | La ruta completa de la sesión llegaba al nombre de enlace de SirIL: ficheros con `:` y `\`, imposibles de crear en Windows. | ✅ `5df5e12` |
| **S-0004** | Nombres idénticos de lights entre filtros distintos colisionan en disco. | ✅ `983f5de` |
| **S-0005** | Índices o salidas de registro incompletos o mal nombrados se admiten como válidos: métricas atribuidas al frame equivocado. | ✅ `9bac15a` |
| **S-0006** | Restos de corridas anteriores en la carpeta de registro se usan como si fueran de la corrida actual. | ✅ limpieza existente desde `01813e3`, verificada en `9bac15a` |
| **S-0007** | Filtros con nombres normalizados idénticos sobrescriben el mismo canal. | ✅ `69f1c19` |
| **B-0001** | La migración de BD v1 hacía `DROP COLUMN` sobre `telescope_name` poblado, perdiendo el dato del usuario. | 🟡 `264b5d0` (contenida; la migración espera a una decisión) |
| **B-0002** | Una conexión SQLite cuyo esquema fallaba quedaba publicada y era reutilizable en el proceso. | ✅ `e3993a7` |
| **B-0003** | Una descarga del catálogo vacía o truncada se validaba, borraba y confirmaba el catálogo del usuario. | ✅ `ef62ef6` (política conservadora y caché verificada) |
| **B-0009** | Refrescar OpenNGC eliminaba los LDN previamente cargados aunque no se refrescara ese catálogo. | ✅ `0da9548` |
| **E-0001** | Dos adjuntos con el mismo nombre se sobrescribían al guardarlos en una entidad de Equipo. | ✅ `ec6d2ee` |
| **E-0002** | Un filtro inexistente confirmaba el equipo y la imagen antes de que la FK fallara (estado a medias en BD). | ✅ `e5bf105` |
| **P-0001** | El tránsito UTC del día vecino puede puntuar con la Luna o la altura de la fecha equivocada. | ✅ `97d5787` |
| **P-0002** | Las mejores noches pueden quedar sin ventana de captura (criterio de recomendación). | ⏳ |
| **U-0001** | `_metric_text` lanzaba `KeyError('value')` con valores numéricos en la respuesta del worker. | ✅ `0a04cee` |
| **T-0001** | `pytest` a secas migraba y escribía la BD real del usuario y descargaba en `data/downloads`. | ✅ `b9118a4` |
| **T-0002** | Un test escribía, actualizaba y borraba sesiones planificadas en la BD real: se perdió el objeto `M31` del usuario. | ✅ `0407ba9` |

## 🟠 Medios

| ID | Bug | Estado |
|---|---|---|
| **B-0004** | Objetos nuevos del Catálogo Personal no aparecían tras guardarlos (reportado por el usuario). | 🔎 sin reproducir |
| **B-0005** | El arranque bloquea la ventana hasta 120 s si la red está lenta (`ensure_catalog` antes de pintar). | ✅ `9c86381` |
| **B-0006** | La conexión SQLite del hilo principal no debe pasar a hilos Qt; hoy se cumple por diseño. | ⏳ revisión continua |
| **S-0008** | Mezcla de RAW y FITS en una misma sesión no se rechaza pese al contrato declarado. | ✅ `8210353` (validación por secuencia) |
| **S-0009** | Una carpeta creada por una calibración fallida bloquea el reintento: `exists()` cuenta como «ya calibrada». Sigue vigente tras **S-0002**. | ✅ `1f91334` |
| **S-0011** | `_hilo` se libera al recibir el resultado y no al emitir `finished`. | ✅ `7bf6c24` |
| **S-0012** | `wait(3000)` sobre tareas Python sin cancelación cooperativa puede congelar el cierre. | ✅ `a53098c` (cancelación cooperativa) |
| **S-0013** | Un error al escribir en stdin podría dejar un hijo de SirIL vivo. | ✅ `afe3a09` |
| **S-0014** | Solo se valida el primer FITS como 16-bit; el resto de la sesión se asume correcto. | ✅ `497637a` |
| **S-0015** | Un `EXPTIME` textual puede hacer fallar el escaneo completo de la sesión. | ✅ `ab37304` |
| **S-0016** | `exportar_apilados` acepta un origen arbitrario por API aunque la UI pase la carpeta de trabajo. | ✅ `f09085f` (origen acotado y resuelto) |
| **S-0020** | La limpieza de salidas anteriores podía dejar restos y la corrida nueva los mezclaba con sus resultados. | ✅ `4e1e5c0` |
| **S-0022** | El registro rechaza hardlinks válidos cuando Windows no permite crear symlinks. | ✅ `265d35c` |
| **S-0023** | Abrir PASS sin consola (`pythonw`/acceso directo) hace aparecer terminales en las llamadas CLI de SirIL y al comprobar su versión. | ✅ `be768df` |
| **S-0024** | La auditoría promedia FWHM y FWHM ponderado de SirIL como si fueran los ejes X/Y y presenta esa mezcla como FWHM. | ⏳ |
| **S-0025** | La lectura de métricas acepta filas de registro incompletas sin validar su correspondencia con toda la secuencia; la UI atribuye la ausencia a un descarte de SirIL. | ⏳ |
| **S-0026** | FWHM o fondo infinitos contaminan las puntuaciones con NaN y pueden dejar los frames sin recomendación de descarte. | ⏳ |
| **S-0027** | Con exposición desconocida se mezclan fondos en ADU equivalentes y ADU equivalentes/s dentro de la misma puntuación. | ⏳ |
| **E-0003** | Una pieza usada en dos roles deja el formulario y los totales desactualizados tras editar o borrar. | ✅ `dbc82e4` |
| **E-0004** | El precio de un filtro editado no repinta el total hasta otra interacción. | ✅ `dbc82e4` |
| **E-0005** | `NaN`/infinito y precio o peso negativos no se filtran antes de persistir un setup. | ✅ `a491664` |
| **E-0006** | Bortle/SQM no cambia el color base del disco en la rosacea. | ✅ `95f599f` |
| **E-0007** | Una fuente de Claridad de Luz >100 km se trunca en el slider al editar otra propiedad. | ✅ `4568fd1` |
| **E-0008** | Las claves de FOV no usaban la focal efectiva del reductor. | ✅ |
| **E-0009** | Los borrados de piezas no comprobaban usos en sesiones/setups ni sus cascadas. | ✅ |
| **E-0010** | Imágenes de equipo con nombre homónimo podían sobrescribirse. | ✅ |
| **P-0003** | El factor lunar se puntúa en el tránsito diurno en vez de dentro de la ventana de captura. | 🟡 `97d5787` (evaluación nocturna; pendientes tiempo útil y casos sin bordes) |
| **P-0004** | Cálculo incorrecto en latitudes altas (geometría polar). | ✅ `68e1326` (alturas constantes en polos) |
| **P-0005** | El tránsito se ordena tras el `LIMIT` y desplaza la ventana elegida. | ✅ `255252c` |
| **P-0006** | La noche polar queda truncada en el cálculo de ventanas. | ⏳ (rediseño del Planificador) |
| **P-0007** | Alias NGC/IC tratados de forma inconsistente al resolver el objetivo. | ✅ `d346937` (alias de designación) |
| **P-0008** | Una duración puede exceder el intervalo de la ventana por un paso. | ✅ `6bd5810` |
| **P-0009** | La separación lunar diurna se usa en el ranking de noches. | 🟡 `97d5787` (evaluación nocturna; pendientes tiempo útil y casos sin bordes) |
| **P-0010** | La excepción de un proveedor de clima en hilo secundario rompía la consulta (las claves se leían desde el hilo de trabajo). | ✅ `0a04cee` |
| **P-0012** | Las tarjetas de clima lanzaban una excepción al recibir métricas numéricas del proveedor. | ✅ `0a04cee` |
| **P-0013** | El minuto anterior a la salida lunar se cuenta completo aunque la Luna cruce el horizonte dentro de él e invalide la captura. | ✅ `c21be5f` (cruces interpolados de 0°/5° y margen lunar bajo aprobado) |
| **P-0014** | El resumen puede extender captura más allá del fin de la noche astronómica al contar completa la última muestra nocturna. | ✅ `f9aef1c` |
| **P-0015** | Guardar una sesión usa las coordenadas originales del objetivo e ignora el centro editado del encuadre. | ✅ `b4262de` |
| **U-0002** | Arrastrar la vista no actualiza el encuadre visible antes de guardar. | ✅ `885ba55` |
| **U-0003** | Quitar el último target deja el plan y el planetario obsoletos. | ✅ `885ba55` |
| **U-0004** | Si la región no está en el cielo, el target anterior queda resaltado. | ✅ `885ba55` |
| **U-0005** | Añadir un duplicado recarga la lista y puede cambiar la selección. | ✅ `885ba55` |
| **C-0001** | Se admiten umbrales de sub/sobremuestreo contradictorios entre sí. | ✅ `a7f5ead` |
| **C-0002** | Configuración guarda varias claves sin atomicidad: un fallo a mitad deja ajustes a medias. | ✅ `a7f5ead` |
| **C-0003** | Editar la ruta de SirIL deja el ✓ de «encontrado» obsoleto hasta reabrir. | ✅ `600200c` |
| **T-0003** | La suite depende de los catálogos reales del usuario; faltan fixtures offline sintéticos. | ✅ `39593f3` |
| **T-0004** | Fixtures que usan red o estrellas reales: inestables según el día y la ubicación. | ✅ `39593f3` |
| **T-0005** | Symlinks en fixtures: no portables en Windows. | ✅ `265d35c` |
| **T-0006** | Tests con geometría dependiente de temporizadores o DPI de la pantalla. | ✅ `09d0a8f` |
| **T-0007** | El modo offscreen se activa con `setdefault` y puede no aplicarse. | ✅ `8930f6d` |
| **X-0001** | El README raíz contradice la GPL al prohibir la venta. | ✅ `18c384e` |
| **X-0002** | El README raíz describe un ranking de objetos que no existe. | ✅ `18c384e` |
| **X-0003** | El README raíz presenta el Planetario como dependiente de red. | ✅ `18c384e` |
| **X-0004** | `planners/README.md` mantiene como pendiente un CRUD ya implementado. | ✅ `18c384e` |
| **X-0007** | `tests/README.md` describe la UI offscreen y la cobertura del README de forma errónea. | ✅ `bd7211b` (documentación interna cotejada) |

## 🟡 Bajos

| ID | Bug | Estado |
|---|---|---|
| **B-0007** | `_download_tap` referencia `urllib.request` sin import directo: `NameError` latente. | ✅ `ef62ef6` (import explícito; hipótesis antigua no reproducida) |
| **S-0017** | Las previews de auditoría cargan el FITS entero en el hilo de UI. | ⏳ medido; optimización diferida de baja prioridad |
| **S-0018** | El stdout de SirIL y la terminal crecen sin límite en corridas largas. | ✅ `4862c86` (historial en disco; terminal/resultado acotados) |
| **S-0019** | Código muerto (símbolos sin consumidores) acumulado en `stacks/` y `ui/`. | ✅ |
| **L-0001** | QMenu y paneles efímeros con parent retenidos: posible fuga de widgets. | ✅ `afe3a09` |
| **L-0002** | Los diálogos acumulaban hijos ocultos al cerrar (fuga medida 20/20). | ✅ |
| **U-0006** | El `QDateEdit` de «Editar sesión» no reflejaba la fecha seleccionada. | ✅ |
| **X-0005** | `i18n/` declara traducciones vacías como si fueran válidas. | ⏳ (carpeta aún sin implementar) |
| **X-0006** | Búsqueda decía «sin datos hasta que haya API key» aunque hubiera claves. | ✅ |
| **X-0008** | `tests/README.md` atribuía la BD a `siril_finder`. | ✅ `bd7211b` (documentación interna cotejada) |
| **X-0009** | `tests/README.md` citaba rutas y tests equivocados. | ✅ `bd7211b` (documentación interna cotejada) |
| **X-0010** | El README de Configuración atribuía la persistencia a `siril_finder`. | ✅ |
| **X-0011** | Resumen y `STRUCTURE.md` presentaban como actual un flujo aún futuro. | ✅ |
| **X-0012** | Los totales del catálogo se repetían en `MEMORY.md`. | ✅ |
| **X-0013** | Roadmap histórico obsoleto en `MEMORY.md`. | ✅ |
| **X-0014** | Errata «conversión» en el README de planificación. | ✅ |
| **X-0015** | Prosas extensas en la documentación frente a la regla de brevedad. | ⏳ poda continua |
| **X-0016** | El README público citaba documentos de trabajo que no se distribuyen. | ✅ `0da24f5` |

## Decisiones

Cuestiones que requieren decidir el comportamiento; las resueltas indican su acuerdo:

| ID | Pendiente |
|---|---|
| **B-0008** | Añadir una región con un nombre repetido se descarta en silencio (`INSERT OR IGNORE`). |
| **E-0011** | Migración aprobada: separar datos de equipo v1 en piezas independientes y vincularlas a equipos, sin inventar características ni fusionar por nombre. ⏳ Implementación y verificación pendientes. |
| **E-0012** | ✅ Todo o nada para guardar setups: BD y adjuntos; aplicado en `e5bf105`. |
| **E-0013** | ✅ Total guardado y previsualización diferenciados; Guardar/Descartar/Cancelar con guardados separados de piezas y equipo. Descartar recupera lo persistido; Cancelar mantiene ediciones. Aplicado en `f5d02d7`. |
| **S-0010** | Una secuencia nueva pide métricas `wfwhm`/`nbstars` que SirIL no vuelve a calcular. |
| **P-0011** | Las horas se calculan con un offset fijo por ubicación: no se tiene en cuenta el cambio de hora (DST). |
| **U-0007** | Al planificar no está decidido si se selecciona la noche sugerida o la fecha guardada por el usuario. |
| **U-0008** | No está definida la precedencia del FOV entre la región del objetivo y el encuadre del equipo. |
| **C-0004** | Precedencia aprobada: ruta elegida de SirIL primero; PATH solo sin ruta configurada. Ruta elegida inválida produce aviso, sin fallback silencioso. ⏳ Implementación y verificación pendientes. |
