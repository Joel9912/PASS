---
name: Auditoría PAS.S
description: Metodología de auditoría del proyecto PAS.S (código o documentación) — 3 fases, informe con IDs, verificación de regresiones y arreglos en commits pequeños. Usar cuando el usuario pida "auditoría" del código, de los Markdown, revisar el proyecto o un módulo concreto.
---

# Auditoría PAS.S

Procedimiento de auditoría aprobado por el usuario. Sirve para código **y**
para documentación (`.md`). Ya se usó con éxito en la auditoría de código
(informe previo: ver la plantilla en `references/plantilla-informe.md`).

## Fase 1 — Estática

1. Inventario de los ficheros/ámbito afectado (glob) antes de mirar nada.
2. Comprobaciones automatizadas donde se pueda (script temporal en
   `%TEMP%`, nunca en el repo): cifras repetidas entre docs, rutas citadas
   que existen o no, convención de las 4 secciones en cada `README` de
   carpeta, tablas bien formadas, español (regla dura del proyecto).
3. Anotar cada hallazgo con **ID provisional** y evidencia (fichero:línea).

## Fase 2 — Verificación

1. Los hallazgos del agente están en `⏳`: **verificarlos manualmente antes
   de arreglar** (leer el código/doco real y confirmar). Un hallazgo puede
   resultar falso positivo (así pasó con M-22) → moverlo a «Verificado y NO
   es hallazgo» con la evidencia empírica, no arreglarlo por si acaso.
2. Si hace falta medir (rendimiento, fugas), medir antes de decidir si es
   crítico o no (M-02 bajó a «bajo» porque solo costaba 110 ms).

## Fase 3 — Informe y arreglos

1. Informe en `C:\Users\Usuario\.opencode\plan\informe-auditoria-<ámbito>.md`
   (solo esa carpeta está permitida para planes/informes; el usuario la pide
   explícitamente).
2. Presentar el informe y **esperar a que el usuario clasifique** lo ambiguo
   (IDs `D-` = decisión del usuario: métricas, destinos de ficheros, precios
   — nunca imponer valores).
3. Ejecutar los arreglos aprobados en tandas: **críticos y medios ya**,
   bajos → «Planes futuros» del `README` de su carpeta.
4. **Un commit por paso coherente**, en español, con su test cuando toque
   (regresión: debe fallar sin el fix — ver skill `verificacion-fix`).
5. `pytest` verde tras **cada** commit (hoy: la suite vive en `tests/`;
   `test_smoke` valida que todos los `README`/docs existen — si renombras o
   borras un `.md`, hay que actualizar ese test en el mismo commit).
6. Si cambia la suite: actualizar `tests/README.md` (dueño del recuento) y
   la instantánea fechada de `MEMORY.md` — ningún otro doc repite la cifra
   (R2, fuente única).
7. Al final: resumen de commits + `pytest` final; **lanzar `python main.py`**
   solo si hay cambios visibles en la app (cambios solo en docs → no hace
   falta).

## Reglas duras que la auditoría no puede romper

- Todo en español (docs y mensajes de commit).
- UI separada de lógica; SirIL solo como herramienta externa; las métricas
  las define el usuario.
- Cambios estructurales o ambiguos → proponer al usuario, no imponer.
- **Documentos (R2/R3)**: fuente única (un dato global solo en su fichero
  dueño), prosa concreta (5 palabras si bastan) y **nada obsoleto** — lo
  completado se elimina de los planes; la historia es git.
- **Resúmenes con dudas (R4)**: si comprimir un texto puede perder contexto
  importante, ofrecer al usuario 2-3 variantes numeradas y esperar su
  elección antes de escribir.
- PowerShell: `Get-Content`/`Set-Content` **con `-Encoding UTF8`** y vigilar
  el BOM (detalles en la skill `verificacion-fix`).

## Esquema del informe

Copiar `references/plantilla-informe.md` y rellenar. Clasificación:

| Prefijo | Significado |
|---|---|
| `C-n` | Crítico: lleva a error o impide un paso futuro |
| `M-n` | Medio: arreglo seguro sin decisión |
| `N-n` | Nuevo: hallazgo no previsto |
| `D-n` | Decisión del usuario (preguntar, no imponer) |
| `B-n` | Bajo: anotar en «Planes futuros», no arreglar ya |

Estado por fila: `⏳` sin verificar → `✓` verificado → `✓ **arreglado** \`<commit>\``.
