---
name: Verificación de fixes
description: Protocolo para comprobar que un test de regresión falla sin el fix y pasa con él (revert-verify), con los gotchas de PowerShell en Windows. Usar antes de dar por bueno cualquier fix con test nuevo o modificado.
---

# Verificación de fixes (revert-verify)

Un test de regresión **no vale nada si no se ha visto fallar**. Antes de dar
un fix por bueno y commitearlo:

1. **Invertir el fix** en el fichero (volver al código anterior).
2. Ejecutar SOLO el test nuevo → **debe FALLAR** (si pasa, el test no mide
   el fix: rediseñarlo).
3. **Restaurar** el fix exactamente.
4. Ejecutar el test → pasa; después **suite completa** → verde.
5. `git status`/`git diff --stat` al final: solo los ficheros previstos
   deben aparecer (si aparece alguno más, algo de la verificación se coló).

Ejemplo de ejecución en un paso (revert → test → restaurar → test):

```powershell
$f = "ruta\fichero.py"
$orig = Get-Content -Raw -Encoding UTF8 $f
$nuevo = $orig.Replace('texto_del_fix', 'texto_viejo')
Set-Content -Path $f -Value $nuevo -NoNewline -Encoding UTF8
& ".venv\Scripts\python.exe" -X utf8 -m pytest tests/...::test_x -q   # debe FALLAR
Set-Content -Path $f -Value $orig -NoNewline -Encoding UTF8
& ".venv\Scripts\python.exe" -X utf8 -m pytest tests/...::test_x -q   # debe pasar
git diff --stat
```

## Gotchas de PowerShell (aprendidos a la fuerza)

- **Siempre `-Encoding UTF8` en `Get-Content` y `Set-Content`.** Sin él,
  `Get-Content` lee en ANSI: los acentos se vuelven «Ã¡» y el `.Replace()`
  **no coincide en silencio** → el «revert» no se aplica y la verificación
  miente (pasó: el test «falló sin fix» que en realidad no se había
  revertido). Comprobarlo: `"coincide: $($orig.Contains($busca))"` antes de
  reemplazar.
- **`Set-Content -Encoding UTF8` en PowerShell 5.1 añade BOM** (EF BB BF).
  Si el fichero no lo tenía, hay que quitarlo después:

  ```powershell
  $b = [System.IO.File]::ReadAllBytes($p)
  if ($b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191) {
      [System.IO.File]::WriteAllBytes($p, $b[3..($b.Length-1)])
  }
  ```

  Señal de que se coló: `git diff` enseña la primera línea como cambiada
  con `﻿` delante.
- PowerShell **no tiene `&&`**: encadenar con `;` y revisar `$LASTEXITCODE`.
- Restaurar SIEMPRE con `$orig` (lectura completa del original) en el mismo
  comando que hace el revert, para que un fallo intermedio no deje el
  fichero a medias.

## Qué NO hace falta verificar

- Fixes cuyo test nuevo referencia una API que no existía antes (falla por
  `ImportError`/`KeyError` sin el fix): la regresión es obvia; no merece un
  revert manual. El revert manual vale para tests que podrían pasar igual
  con código viejo (cableados, constantes, orden de llamadas).
