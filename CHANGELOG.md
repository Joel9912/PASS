# Historial de cambios

Cambios relevantes para quienes usan PASS. Los detalles de implementación y cada corrección pequeña quedan en los commits. Las correcciones registradas citan su ID en [`BUGS.md`](BUGS.md), donde constan su severidad y estado. La documentación se mantiene en español.

## Sin publicar — preparación de v0.2-alpha

Cambios desde `v0.1-alpha`. Esta versión **aún no tiene tag ni se ha publicado**; se completará cuando se apruebe el lanzamiento.

### Añadido
- Registro local persistente en `data/logs/pass.log` y `data/logs/apilador.log`: acciones, avisos y errores con fecha y origen; el del Apilador incluye la salida completa de SirIL, incluso mensajes no mostrados en pantalla. Se continúa al reabrir, sin borrar el historial automáticamente; se ocultan credenciales etiquetadas.
- Configuración → 📚 Catálogos sigue el diseño de las otras secciones: panel con título azul, tabla compacta de filas alternas y estados diferenciados por texto/color. Botones en una fila, progreso solo durante operaciones y avisos compactos con detalle en tooltip; sin cambiar el consentimiento ni descargar al abrir.
- Lectura de exposición RAW en metadatos EXIF mediante la librería Python ExifRead, sin revelar ni modificar originales ni necesitar programas externos. Los contenedores no soportados, incluido CR3, quedan sin dato.
- Captura Posible admite Luna a menos de 5° aun con separación insuficiente, según el criterio del usuario. Captura Ideal mantiene sus requisitos.
- Captura Ideal usa bloques completos de cinco minutos; sus restos válidos se suman a Captura Posible sin huecos artificiales.
- Captura Ideal reserva al menos cinco minutos dentro de ambos extremos de la noche astronómica; los márgenes válidos quedan como Posible.

### Corregido
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
