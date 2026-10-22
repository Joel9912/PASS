# Historial de cambios

Cambios relevantes para quienes usan PASS. Los detalles de implementación y cada corrección pequeña quedan en los commits. Las correcciones registradas citan su ID en [`BUGS.md`](BUGS.md), donde constan su severidad y estado. La documentación se mantiene en español.

## Sin publicar — preparación de v0.2-alpha

Cambios desde `v0.1-alpha`. Esta versión **aún no tiene tag ni se ha publicado**; se completará cuando se apruebe el lanzamiento.

### Añadido
- Configuración → Catálogos incluye «Fuentes y licencias»: consulta offline de procedencia, revisión, atribuciones y licencias declaradas de cada componente, con sus documentos de texto incluidos. No inventa procedencia para catálogos heredados ni abre enlaces automáticamente.
- Preparación offline de fichas SIMBAD para LDN/Barnard a partir de instantáneas TAP con unidades, referencia de coordenadas y procedencia verificadas. Conserva campos ausentes e identidades entre revisiones, sin fusionar por semejanza de coordenadas. No sustituye automáticamente los catálogos instalados; los componentes definitivos siguen en preparación.
- Los paquetes globales pueden almacenar kernels planetarios SPK locales, verificando estructura, segmentos, cobertura y huella antes de activarlos. Curvas, efemérides y ranking usan el Sol y la Luna del modelo seleccionado, con cachés separadas por edición y cálculos concurrentes sin mezclar modelos. Un kernel seleccionado ausente o corrupto no provoca descarga ni sustitución silenciosa. Los paquetes científicos definitivos siguen pendientes; no se garantiza precisión uniforme para 1950–2100.
- Las curvas de tránsito indican el modelo actual y si usan datos IERS locales, predicciones o fechas fuera de tabla. El detalle explica las limitaciones sin prometer precisión uniforme para 1950–2100; no cambia los cálculos ni descarga tablas automáticamente.
- Soporte de ediciones globales que vinculan catálogo y recursos de texto/JSON mediante versiones, dependencias y huellas. Configuración identifica la edición y los opcionales no instalados; actualizar o recuperar conserva el conjunto y los datos personales posteriores. Los componentes idénticos se reutilizan tras verificarlos y un recurso seleccionado perdido o alterado impide declarar disponible la edición. Imágenes, efemérides binarias y paquetes definitivos aún pendientes.
- Búsqueda y carta reconocen los alias explícitos de los nuevos paquetes sin duplicar objetos. La búsqueda muestra candidatos si un alias es compartido; la carta solo centra coincidencias inequívocas o el vínculo estable del objeto guardado, manteniendo su rótulo personal y sin mover la vista ante un destino ambiguo o ausente.
- Soporte de paquetes con identidades estables, alias, relaciones y procedencia original. Los objetos guardados pueden mantener su vínculo aunque cambie la designación; referencias ambiguas y regiones no se fusionan. Activar o recuperar el catálogo conserva notas, nombres y encuadres de las sesiones. La preparación definitiva de estos datos y sus permisos siguen pendientes.
- Las actualizaciones de catálogos preparan una SQLite separada y verificada antes de activarla. Se conservan las tablas legacy y la edición anterior; Configuración permite recuperarla con consentimiento sin restaurar notas, equipos o sesiones antiguos. Búsqueda y cartas fijan una edición coherente, y los archivos ausentes, alterados o de formato incompatible se señalan sin recurrir silenciosamente a otra edición.
- Los cálculos de planificación validan el rango de noches 1950–2100 y el intervalo completo solicitado. Fuera de él se avisa, sin recortar fechas ni conservar resultados de otro cálculo; las sesiones guardadas no se reescriben. Este límite no garantiza precisión uniforme ni sustituye la selección pendiente de efemérides offline.
- El paso Apilar estima el espacio adicional y la exportación a partir de las cabeceras de las tomas seleccionadas, con recálculo de drizzle, canales y mapas de rechazo. El tiempo se extrapola únicamente de una corrida completa comparable medida durante la misma apertura; sin datos suficientes se muestra desconocido. Son previsiones informativas, no reservas ni garantías de espacio o duración.
- En Sesiones del Apilador se comparan y superponen los FOV disponibles de cada carpeta. El área común se mide respecto al campo menor: >80 % indica el mismo encuadre y <80 % mosaico según esa regla. Los encuadres aislados se contrastan con otro FITS aleatorio; discrepancias, límites y datos ausentes se señalan para revisión. Solo lee cabeceras y muestra geometría estimada: no construye mosaicos ni modifica las tomas o su selección.
- Orden de revisión «Sesión y fecha» en Auditar, basado en `DATE-OBS`, sin inferir fechas de los nombres. Conserva casillas y toma visible. La gráfica acompaña el orden cronológico como secuencia de revisión, con intervalos no a escala. El visor presenta hora local según una ubicación guardada coincidente con la posición FITS o una alternativa seleccionable y recordada; mantiene UTC para ordenar. Los desfases automáticos por longitud se indican como aproximados, sin prometer horario de verano histórico.
- Botón «Seleccionar todo» en Auditar: vuelve a marcar las tomas utilizables sin habilitar las rechazadas por SirIL ni cambiar criterios. La selección masiva se conserva en el borrador.
- Auditar permite elegir el corte FWHM `media + (media − mínimo)/6` por sesión y filtro, con límite consultable por toma. El descarte por puntuación puede desactivarse sin ocultar el ranking ni alterar casillas; se conservan las opciones anteriores por defecto y los borradores antiguos siguen siendo recuperables.
- Apilador conserva un borrador de sesiones, opciones y descartes, independiente del log. Al volver ofrece recuperar sin iniciar SirIL; comprueba entradas y resultados antes de acreditar pasos. El registro final se confirma como punto de recuperación antes de apilar, y puede reutilizarse con las mismas opciones de registro y tomas. Descartar el borrador no borra imágenes; los resultados parciales existentes no se sobrescriben.
- Planificación conserva automáticamente un borrador separado de las sesiones guardadas, con parámetros, encuadre y ubicación. Al volver ofrece Continuar, Más tarde o Descartar borrador; no sustituye referencias desaparecidas ni crea sesiones automáticamente. Un fallo de guardado deja aviso y cancela el cierre.
- Equipo avisa de cambios sin guardar al cambiar de equipo o componente, iniciar otro, salir de la pestaña o cerrar PASS: Guardar, Descartar o Cancelar. Piezas globales y equipo se guardan por separado; los errores mantienen las ediciones. La cabecera distingue el total guardado de la previsualización y descartar no revierte piezas o filtros ya guardados.
- Registro local persistente en `data/logs/pass.log` y `data/logs/apilador.log`: acciones, avisos y errores con fecha y origen; el del Apilador incluye la salida completa de SirIL, incluso mensajes no mostrados en pantalla. Se continúa al reabrir, sin borrar el historial automáticamente; se ocultan credenciales etiquetadas.
- Configuración → 📚 Catálogos sigue el diseño de las otras secciones: panel con título azul, tabla compacta de filas alternas y estados diferenciados por texto/color. Botones en una fila, progreso solo durante operaciones y avisos compactos con detalle en tooltip; sin cambiar el consentimiento ni descargar al abrir.
- Las tres columnas de Catálogos, incluidos sus nombres, se muestran centradas.
- Lectura de exposición RAW en metadatos EXIF mediante la librería Python ExifRead, sin revelar ni modificar originales ni necesitar programas externos. Los contenedores no soportados, incluido CR3, quedan sin dato.
- Captura Posible admite Luna a menos de 5° aun con separación insuficiente, según el criterio del usuario. Captura Ideal mantiene sus requisitos.
- Captura Ideal usa bloques completos de cinco minutos; sus restos válidos se suman a Captura Posible sin huecos artificiales.
- Captura Ideal reserva al menos cinco minutos dentro de ambos extremos de la noche astronómica; los márgenes válidos quedan como Posible.

### Corregido
- Los cálculos offline no fallan por caducidad de predicciones IERS locales: conservan los avisos de aproximación y no intentan descargar tablas (P-0017).
- La validación directa de recursos rechaza formatos desconocidos en lugar de interpretarlos como texto (B-0012).
- La sugerencia de nombre de sesión se actualiza al cambiar la fecha, sin modificar el nombre escrito por el usuario (U-0009).
- La carga inicial de paquetes vuelve a comprobar que cada componente siga vacío y no sustituye el catálogo instalado por otra operación mientras tanto (B-0011).
- Tres filtros que no forman un R/G/B inequívoco, por ejemplo R/r/G, conservan sus pilas separadas sin fallar ni inventar el canal ausente (S-0032).
- Se rechazan antes de limpiar o ejecutar las ponderaciones wfwhm/nbstars cuando una secuencia por canal o recortada pierde los datos de registro necesarios. La elección no se sustituye silenciosamente; en varios filtros se avisa antes del registro final (S-0010).
- Los paquetes de catálogos validan también tipos, familias e identidades antes de sustituir datos o versiones, aunque el tamaño y SHA sean correctos. El preparador usa el mismo contrato y no escribe artefactos inválidos; los fallos conservan los catálogos anteriores y los datos personales (B-0010).
- Añadir una región con nombre repetido avisa y conserva la existente, en lugar de simular un guardado. Permite renombrar o cancelar sin perder lo escrito en el formulario (B-0008).
- Las bases antiguas de Equipo migran sus datos v1 a piezas independientes, sin fusionar por nombre ni perder vínculos de sesiones. Se conservan los valores originales; un conflicto con una asignación actual detiene la migración sin sobrescribir datos. Esquema y piezas se revierten juntos ante un fallo (B-0001, E-0011).
- La ruta de SirIL elegida en Configuración tiene prioridad sobre PATH. Si es inválida se informa del fallo sin usar otra instalación; «Abrir en SirIL» respeta también la instalación elegida (C-0004).
- Apilador reúne el estado del trabajo y del borrador en una sola fila junto a la navegación, sin ocultar errores de guardado ni el acceso a recuperar. La gráfica de Auditar puede ceder más altura para dejar separados la tabla, el pie FITS y los controles inferiores (S-0031).
- El pie del visor FITS de Auditar mantiene una sola línea con fecha corta y descarte sí/no (o Revisar). Los motivos, puntuación, año, UTC y procedencia horaria quedan en la ayuda, sin reducir la imagen por textos largos (S-0030).
- Auditoría deja fondo por segundo y proxy de transparencia sin evaluar cuando falta la exposición, en lugar de mezclar unidades. Muestra «Revisar» si un criterio activo necesita esos datos y permite evaluar solo las métricas estelares al desactivar los criterios dependientes (S-0027).
- Previsualizaciones FITS con autoestirado más moderado: fondo oscuro sin levantar tanto el ruido, conservando estrellas y contraste de sombras/nubes. Solo cambia la visualización, no las imágenes ni los criterios de descarte (S-0029).
- Auditoría interpreta FWHM y FWHM ponderado de SirIL por separado; muestra estrellas, ponderado y canal en la ayuda del FWHM. Valida la secuencia y rechaza datos no finitos antes de puntuar; respeta la selección de SirIL y su canal de registro RGB (S-0024, S-0025, S-0026).
- Una nueva auditoría fallida invalida el permiso de apilado anterior, conservando las elecciones manuales por archivo para reintentar (S-0028).
- Las llamadas CLI de SirIL y la comprobación de versión no abren terminales en Windows al iniciar PASS sin consola desde el acceso directo; log, progreso y errores siguen capturados (S-0023).
- Guardar una sesión respeta el centro editado del encuadre cuando el objetivo tiene coordenadas conocidas (P-0015).
- Terminal y resultados de SirIL acotados en memoria, conservando marcadores de fallo/identidad aunque aparezcan al principio y el historial completo en disco (S-0018).
- Los fallos al enviar comandos, cerrar stdin o recibir logs de SirIL terminan y recolectan el proceso hijo, y cierran sus pipes (S-0013).
- Los menús de obstrucciones y paneles de contaminación lumínica liberan sus widgets al cerrarse, sin acumular hijos ocultos ni perder datos del sitio (L-0001).
- El registro reconoce hardlinks válidos cuando Windows no permite crear symlinks; mantiene el rechazo de índices duplicados o ajenos. Las pruebas de secuencias ya no exigen privilegios de symlink; solo los casos específicos de enlaces simbólicos reales se omiten si el sistema no los permite (S-0022, T-0005).
- Tests de interfaz estables con escalado de pantalla: la prueba de la rosácea no confunde una línea de rejilla con el fondo y la de Efemérides controla la maximización diferida antes de fijar su tamaño (T-0006).
- Arranque sin descargas bloqueantes (B-0005). Configuración incorpora Catálogos: comprobación e instalación consentida de paquetes PASS en segundo plano, con tamaño/SHA-256 y reemplazo transaccional. Los paquetes incluidos rellenan catálogos ausentes sin Internet; no se ha publicado aún ningún paquete.
- Pruebas independientes de los catálogos personales y de Internet: base sintética aislada, HTTP simulado y tablas astronómicas locales (T-0003, T-0004).
- Catálogos: se rechazan descargas sin longitud verificable, incluso en la primera carga; se conserva la base anterior. Se validan CSV/gzip y filas útiles antes de reemplazar datos; los errores de inserción revierten el refresco. Las cachés requieren tamaño y huella SHA-256 registrados tras una transferencia comprobada; una caché antigua o alterada exige volver a descargar (B-0003).
- Las horas sobre una altura mínima ya no inventan doce horas cuando el observador o el objeto está exactamente en un polo y la altura es constante (P-0004).
- Las pruebas fuerzan el modo offscreen aunque el entorno tenga otra plataforma Qt configurada (T-0007).
- Calibración: las carpetas incompletas ya no bloquean reintentos. Al comenzar se eliminan restos fallidos y salidas de sesiones ajenas al último escaneo, incluso calibraciones correctas; se conservan los éxitos actuales y el material global compartido. Limpieza limitada al trabajo de PASS, con rechazo de enlaces y solapes con originales (S-0009).
- Configuración rechaza límites de muestreo invertidos sin cambiarlos automáticamente; guarda todos los ajustes en una única transacción para evitar cambios parciales si falla la base de datos (C-0001, C-0002).
- Configuración: editar la ruta de SirIL retira el estado anterior y la comprueba al terminar la edición (C-0003).
- Planificación: encuadre actualizado al mover la vista, limpieza del plan y planetario al quitar el último objetivo y del resaltado al seleccionar una región ausente; añadir un duplicado conserva la selección (U-0002–U-0005).
- Rosácea: el fondo refleja el SQM o Bortle con una escala fija de 17,66–22 mag/arcsec² y colores aproximados de las referencias; los valores exteriores saturan el color sin cambiar el dato (E-0006).
- Al guardar o borrar una pieza de componente desde un rol, el otro rol que usaba esa misma pieza (por ejemplo, la misma cámara como Principal y como Guía) refresca su formulario y la suma de la cabecera deja de contar el precio viejo (E-0003).
- Crear, editar o borrar un filtro global repinta al instante el total del equipo en la cabecera, sin esperar a otra interacción (E-0004).
- Reabrir el panel de Contaminación Lumínica de una dirección con una fuente a más de 100 km ya no la recorta: el límite de 100 km se mantiene solo para fuentes nuevas (E-0007).
- Búsqueda de un objeto por designación: se aceptan alias como `m31`, `ngc224` o `IC  001`; los alias numéricos NGC/IC/Messier resuelven por su número de cruce (P-0007).
- El orden «Tránsito» de Búsqueda ya no recorta la lista por magnitud antes de ordenar: el límite se aplica después de calcular los tránsitos, así que se ven los objetos cuya culminación cae antes (P-0005).
- Cancelar una tarea del Apilador que no usa SirIL (escaneo, auditoría) la corta en su siguiente paso de progreso o log, en vez de dejarla correr hasta el final mientras el cierre esperaba (S-0012).
- El Apilador ya no suelta la referencia a su hilo de trabajo al recibir el resultado: la libera cuando Qt confirma que terminó, evitando que el cierre de la app destruya un QThread aún corriendo (S-0011).
- La exportación del apilado solo copia ficheros generados por PASS dentro de su carpeta de trabajo; un origen ajeno o un enlace que escapa no se copia (S-0016).
- La comprobación de 16 bits revisa todos los FITS de la secuencia, no solo el primero, e identifica el fichero incompatible antes de calibrarlo (S-0014).
- La calibración rechaza una misma secuencia con RAW y FITS mezclados antes de crear enlaces o invocar SirIL, evitando que parte de las tomas quede ignorada (S-0008).
- Una exposición FITS textual inválida no aborta la lectura; se busca un alias válido y, si falta, queda desconocida. Se rechazan segundos no finitos o no positivos (S-0015).
- Conteo y bandas se cortan en el cruce solar interpolado, sin prolongar captura al crepúsculo (P-0014).
- Los cruces lunares de 0° y 5° se interpolan entre muestras para no contar el minuto entero con condiciones caducadas (P-0013).
- Las bandas de captura coinciden con el resumen y la última muestra no añade tiempo fuera de la curva (P-0008).
- Los setups rechazan precios y pesos negativos o no finitos antes de crear o editar; las piezas también rechazan NaN e infinitos en esos campos (E-0005).
- El plan de captura reconoce las culminaciones de la madrugada del día UTC vecino y evita evaluar la separación lunar en un tránsito diurno cuando hay bordes nocturnos. Se conserva la puntuación provisional hasta el rediseño por tiempo útil ideal (P-0001, P-0003, P-0009).
- Guardar un equipo confirma juntos sus datos, filtros y adjuntos; un fallo revierte la BD y retira las copias nuevas sin borrar las anteriores. Los errores de copia y SQLite se muestran conservando el formulario (E-0002; decisión E-0012).
- Refrescar OpenNGC ya no elimina las nebulosas LDN previamente cargadas (B-0009).
- Los lights homónimos de filtros distintos conservan referencias independientes al calibrar (S-0004).
- Registro y debayer rechazan índices incompletos, duplicados o mal nombrados en lugar de atribuir datos a otro frame (S-0005).
- Los filtros que generan el mismo nombre de canal, incluso por mayúsculas en Windows, ya no sobrescriben sus pilas (S-0007).
- El Apilador detiene una corrida si no consigue limpiar por completo salidas temporales anteriores, en vez de mezclarlas con resultados nuevos.
- Un fallo de migración ya no deja una conexión SQLite incompleta reutilizable en el proceso.
- Un filtro inexistente impide guardar el equipo antes de crear adjuntos o confirmar cambios parciales.
- Dos adjuntos con el mismo nombre de archivo ya no se sobrescriben al guardarlos en una entidad de Equipo.
- La ejecución normal de `pytest` aísla la BD, descargas y carpeta de trabajo: las pruebas no migran ni escriben en los datos del usuario.
- Las tarjetas de clima ya no lanzan una excepción al recibir métricas numéricas de un proveedor.
- Una BD antigua con componentes embebidos de equipo ya no los pierde al abrir: se detiene la migración y conserva esos datos hasta acordar cómo trasladarlos.
- La calibración rechaza una sesión cuyo origen o cuyas tomas coincidan con la carpeta de salida, para evitar borrar originales al limpiar el área de trabajo.
- Cada sesión tiene carpeta de salida propia (`calibrados/<nombre>-<hash>` derivado de su ruta): dos sesiones homónimas de proyectos distintos ya no comparten calibrados ni se limpian la una a la otra.
- Las sesiones se identifican por su ruta de origen en todo el Apilador: una homónima ya no aparece como «calibrada» con la calibración de la otra, ni hereda sus exposiciones, fichas ni avisos, y el pool de lights no se queda solo con una de las dos.
- Las pruebas del Catálogo Personal y de Sesiones Planificadas ya no insertan ni borran datos en la base del usuario; se ejecutan sobre una base aislada.
- Las tarjetas de clima ya no provocan un error de SQLite al consultar el pronóstico desde un hilo secundario. Las claves se leen en el hilo principal y se pasan al trabajador; un fallo del proveedor se muestra como falta de datos.
- Corregidos detalles del Apilador y del Planificador detectados durante la revisión del código, con pruebas de regresión para evitar que reaparezcan.

### Cambiado
- Reorganizado internamente el Apilador en paneles por paso y separadas las pruebas por pestaña; el flujo de usuario sigue siendo el mismo.
- Los enlaces de registro de SirIL usan el nombre de la carpeta de la sesión, nunca su ruta completa.
- Unificadas utilidades compartidas de formato, cálculo y tablas; retirado código sin uso y aclarados los límites entre interfaz, lógica y base de datos.
- Actualizadas la documentación de carpetas y la información de versión mostrada por la aplicación.

### Pendiente
- Clear Outside y Meteoblue siguen sin consultar servicios reales: las tarjetas muestran «Sin datos» aunque haya claves guardadas.
- Resumen, Planetario y Planificador de Equipo siguen en construcción.

## v0.1-alpha — versión inicial

- Primera versión etiquetada de PASS, con Planificador, Equipo y asistente de Apilador mediante SirIL externo.

La versión se publicará como **pre-release `v0.2-alpha`**, solo cuando se apruebe el lanzamiento. Entonces se añadirán la fecha y el enlace.
