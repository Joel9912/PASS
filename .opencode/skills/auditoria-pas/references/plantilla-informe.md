# Informe de auditoría — <ámbito> (<fecha>)

**Alcance:** <ficheros/ámbitos> · **Fuera de alcance acordado:** <si lo hay>

**Estado de verificación:** ✓ = verificado manualmente; ⏳ = hallazgo del
agente, pendiente de verificar antes de arreglar.

---

## Resumen ejecutivo

<5-10 líneas: qué se ha mirado, cuántos hallazgos de cada tipo, lo más
importante y qué se decide/pregunta al usuario.>

---

## 1. Críticos

| ID | Estado | Ubicación | Hallazgo | Propuesta |
|---|---|---|---|---|
| **C-1** | ⏳ | `fichero:línea` | Qué falla y por qué importa | Cómo arreglarlo |

## 2. Medios (arreglables ya, sin decisión)

| ID | Estado | Ubicación | Hallazgo | Propuesta |
|---|---|---|---|---|

## 3. Medios que requieren decisión (NO se arreglan sin preguntar)

| ID | Pregunta al usuario | Opciones |
|---|---|---|

## 4. Bajos (a «Planes futuros», no se arreglan en esta tanda)

- `B-1` (`ruta:fichero:línea`) — descripción → README de destino.

## 5. Verificado y NO es hallazgo

- `<ID>` — por qué no lo es, con la evidencia empírica (cómo se comprobó).

---

## 6. Plan de arreglos (commits, `pytest` verde tras cada uno)

**Tanda A — arreglos ejecutables ya:**
- [ ] **ID**: descripción → commit.

**Tanda B — requieren decisión (preguntar):** …

**Tanda C — en su paso:** …

## 7. Mediciones

<si las hay: método, cifras, conclusión>

## 8. Pendientes / checklist

- [ ] Preguntar D-1, D-2…
- [ ] Ejecutar Tanda A en commits pequeños; anotar bajos en «Planes futuros».
- [ ] Recuentos de tests y `pytest` final.
