# Actualizaciones de la app de Nomad Studio

> Especificación v0.1 (borrador) · 2026-09-14
>
> Cómo se publica una versión nueva de Nomad Studio en **GitHub Releases** del repo `NomadStudio` y cómo la versión portable la detecta, descarga, verifica e instala sin tocar los datos del usuario.
>
> Complementa a [`PACKAGE_FORMAT.md`](PACKAGE_FORMAT.md): los paquetes de flows NO se actualizan por aquí (se importan como ZIP, §13 de esa especificación). Este documento es solo para la app.
>
> **DEBE**, **NO DEBE**, **DEBERÍA** y **PUEDE** tienen sentido normativo.

---

## 0. Decisiones

| # | Decisión |
|---|---|
| U1 | Las versiones se publican como **GitHub Releases** del repo `NomadStudio`. El repo es privado hasta el lanzamiento y público después. |
| U2 | Se actualiza la **versión portable**: carpetas hermanas `NomadStudio/app/` (se reemplaza entera) y `NomadStudio/data/` (nunca se toca). Ver `PACKAGE_FORMAT.md` D9, §12.1. |
| U3 | Cada Release trae un ZIP por plataforma, `SHA256SUMS.txt` y su firma Ed25519 con la **misma clave oficial** que los packs (`PACKAGE_FORMAT.md` §11.4). Una descarga que no verifica se descarta. |
| U4 | Al detectar una versión nueva, la app **la descarga, verifica y prepara sola en segundo plano** (desactivable). Pero **nunca instala ni reinicia sin que el usuario lo diga**: avisa cuando está lista y el usuario elige cuándo aplicarla. |
| U5 | El cambio de carpetas lo hace el **lanzador de la raíz**, que no se reemplaza con `app/`, con vuelta atrás automática si la versión nueva no arranca. |
| U6 | Antes de aplicar una actualización se hace **copia de seguridad de `data/`**. |
| U7 | Sin telemetría: la comprobación es una petición GET a GitHub, sin identificadores del usuario. |
| U8 | **Canal futuro: Microsoft Store** para Windows, como segundo canal junto al ZIP portable (modelo Blender). Paquete MSIX firmado por Microsoft, actualizado por la Store; el actualizador de GitHub se desactiva en esa versión (§12). |

---

## 1. Versiones

- **SemVer**: `MAYOR.MENOR.PARCHE` (`1.3.0`). El tag de git es `v` + versión (`v1.3.0`).
- **Canales**:
  - `stable` (por defecto): Releases normales.
  - `beta`: Releases marcadas como *pre-release* en GitHub, con sufijo SemVer (`1.4.0-beta.2`). Solo las ve quien elige el canal beta en Ajustes.
- **Borradores** (*draft*) de GitHub: nunca los ve la app.

---

## 2. `app/portable.json`

Identifica una instalación portable y su versión. Lo genera el build (§4) y va dentro de `app/`.

> Ojo con el nombre: la carpeta portable `NomadStudio/app/` contiene **el repo entero** (código, `requirements.txt`, lanzadores…), y dentro está a su vez el paquete Python `app/`. `portable.json` va en la raíz del repo, es decir, `NomadStudio/app/portable.json`, al lado de `requirements.txt`, **no** dentro del paquete Python. Lo lee `app/services/app_info.py` (`PORTABLE_FILE`) y NO DEBE subirse a git.

```json
{
  "schema_version": 1,
  "version": "1.3.0",
  "channel": "stable",
  "platform": "windows-x64",
  "python": "3.13.3",
  "built_at": "2026-09-20T18:00:00Z",
  "commit": "a1b2c3d",
  "update_repo": "<usuario>/NomadStudio",
  "data_schema": 3
}
```

| Campo | Uso |
|---|---|
| `version` | Se compara con la última Release |
| `platform` | Elige qué ZIP descargar. Mismas etiquetas que `PACKAGE_FORMAT.md` §8.3 |
| `update_repo` | De dónde se consultan las Releases. PUEDE sobrescribirse (§11) |
| `data_schema` | Versión del formato de `data/` que espera esta versión de la app (§8) |

`channel` admite `stable`, `beta` y `store`. Con `store` (§12) el actualizador de GitHub está desactivado y Ajustes muestra "Actualizaciones gestionadas por Microsoft Store".

**Sin `portable.json`** (copia de desarrollo del repo): el actualizador está desactivado y Ajustes muestra "Versión de desarrollo: actualiza con git".

---

## 3. Anatomía de una Release

**Tag**: `v1.3.0` · **Título**: `Nomad Studio 1.3.0` · **Pre-release**: solo en canal beta.

**Ficheros adjuntos** (*assets*), con nombres exactos, porque la app los busca por nombre:

| Fichero | Contenido |
|---|---|
| `NomadStudio-1.3.0-windows-x64.zip` | Versión portable completa para Windows (Intel y AMD) |
| `NomadStudio-1.3.0-macos-arm64.zip` | macOS con Apple Silicon |
| `NomadStudio-1.3.0-linux-x64.zip` | Linux x86-64 |
| `SHA256SUMS.txt` | Una línea por ZIP: `<sha256>  <nombre del fichero>` |
| `SHA256SUMS.sig` | Firma Ed25519 de `SHA256SUMS.txt` (base64), con `key_id` |
| `release-notes.json` | Notas de la versión por idioma (§3.1) |

Plataformas adicionales (`macos-x64`, `linux-arm64`, `windows-arm64`) se añaden con el mismo patrón cuando se construyan.

**Contenido de cada ZIP**: una única carpeta `app/` en la raíz del ZIP. NO DEBE contener `data/`, `data-location.json` ni ficheros de usuario.

```
NomadStudio-1.3.0-windows-x64.zip
└── app/
    ├── portable.json
    ├── python/               ← Python incluido
    ├── lib/                  ← dependencias instaladas (fichero de bloqueo)
    ├── nomad/                ← código de la app
    ├── launcher/             ← plantillas del lanzador (§7.4)
    └── LICENSE, THIRD_PARTY_NOTICES…
```

La primera instalación usa el mismo ZIP: el usuario lo descomprime en `NomadStudio/` y el primer arranque copia el lanzador de `app/launcher/` a la raíz.

### 3.1 Notas de la versión

El cuerpo de la Release en GitHub va en inglés para la web. La app usa `release-notes.json`, porque todo lo que ve el usuario va en los 4 idiomas (issue #88):

```json
{
  "version": "1.3.0",
  "default_lang": "en",
  "highlights": {
    "en": ["Packages can now add their own interface blocks."],
    "es": ["Los paquetes ya pueden añadir sus propios bloques de interfaz."],
    "zh": ["…"], "ko": ["…"]
  },
  "breaking": { "en": [], "es": [] },
  "min_package_schema": 1
}
```

Orden de idioma: el de la app → `default_lang` → `en` (como `PACKAGE_FORMAT.md` §7.1). Si falta `release-notes.json`, se muestra el cuerpo de la Release.

---

## 4. Construir y publicar (GitHub Actions)

Un workflow `.github/workflows/release.yml` se lanza al hacer `git push` de un tag `v*`.

### 4.1 Trabajos

1. **build** (en paralelo, uno por plataforma): `windows-latest`, `macos-14` (arm64), `ubuntu-latest` (x64).
   - Descarga el código con `fetch-depth: 1`.
   - Prepara el Python incluido con **python-build-standalone** (variante `install_only`) en las tres plataformas: misma versión exacta y mismo origen. NO se usa el *embeddable package* de python.org en Windows: no incluye tkinter, y el selector de carpetas de Ajustes lo necesita (`settings_routes.py`).
   - Instala dependencias desde el **fichero de bloqueo** `requirements.lock` (§4.3) en `app/lib/`, con `--require-hashes` y `--only-binary=:all:`.
   - Copia el código, genera `portable.json` con versión, plataforma, commit y `data_schema`.
   - **Prueba de humo**: arranca la app en modo prueba, espera a que responda `GET /api/health` (§7.5) y la cierra. Si no responde, el trabajo falla y no hay Release.
   - Comprime `app/` en `NomadStudio-<versión>-<plataforma>.zip`, conservando los permisos de ejecución (macOS y Linux).
2. **publish** (cuando terminan los tres):
   - Calcula `SHA256SUMS.txt`.
   - Lo firma con la clave privada guardada como *secret* del repo (`NOMAD_SIGNING_KEY`). El log NO DEBE imprimir la clave.
   - Genera `release-notes.json` desde `CHANGELOG/<versión>.json` del repo.
   - Crea la Release **como borrador** con todos los ficheros.
3. **Revisión manual**: tú revisas el borrador y pulsas *Publish*. Hasta entonces ninguna app lo ve.

### 4.2 Costes y límites

- Mientras el repo sea privado, los minutos de Actions tienen coste y los runners de macOS y Windows gastan más que Linux: comprobar la tarifa vigente en *Settings › Billing*. Público: gratis.
- Límite de GitHub por fichero adjunto: 2 GB. Una versión portable ronda 150–200 MB.
- El workflow se lanza solo con tags, nunca en cada commit.

### 4.3 Fichero de bloqueo de dependencias

`requirements.txt` fija las librerías que se usan directamente (Flask 3.1.0, numpy 2.4.6…), pero no sus dependencias indirectas (Werkzeug, Jinja2, click…, y las de `mcp`). Sin bloqueo, dos builds hechos en fechas distintas, o en plataformas distintas, pueden instalar versiones diferentes sin que nadie lo note.

- **`requirements.lock`**, en la raíz del repo junto a `requirements.txt`: todas las librerías, directas e indirectas, con **versión exacta y hash**, válido para las tres plataformas.
- **Criterio: versiones exactas y bloqueadas en todo.** `requirements.txt` fija con `==` todas las dependencias directas; `requirements.lock` fija todas las demás.
- **Herramienta: `uv`** (Astral, el mismo origen que el Python incluido).
- **Estado actual** (2026-09-14): `requirements.lock` generado con **58 librerías**, todas con hash, y **las mismas versiones exactas que el entorno de desarrollo probado**. Incluye las de una sola plataforma con su marcador (`colorama`, `pywin32` solo en Windows).
- **Cómo se generó**, restringido a lo instalado para no subir ninguna versión:
  ```bash
  pip freeze --exclude-editable > installed-constraints.txt
  uv pip compile requirements.txt --universal --python-version 3.13 --generate-hashes --no-annotate --constraint installed-constraints.txt -o requirements.lock
  ```
- **Regenerar sin `--constraint` actualiza las dependencias indirectas** a sus últimas versiones compatibles. Solo se hace **a propósito**, como una actualización de dependencias: regenerar, instalar en el venv, probar la app y todos los addons, y subir `requirements.txt` y `requirements.lock` en el mismo commit.
- **Añadir o cambiar una dependencia directa**: editarla en `requirements.txt` con `==`, regenerar con `--constraint` (para que el resto no se mueva), probar y subir los dos ficheros.
- El desarrollo diario con el venv no cambia.
- El build (§4.1) instala **solo** desde `requirements.lock`, con `--require-hashes`. Una Action DEBE fallar si alguna versión `==` de `requirements.txt` no aparece idéntica en `requirements.lock`.
- Las versiones de la base para addons (`PACKAGE_FORMAT.md` §9.5, nivel 1) DEBEN coincidir en ambos ficheros.

### 4.4 Firma de la app para el sistema

**Decisión: no se usa firma de código de Apple ni de Microsoft** (ni cuenta de Apple Developer ni certificado de Windows). Se distribuye como ComfyUI portable, sin firmar para el sistema.

No confundir con la firma propia de §3 (`SHA256SUMS.sig`, clave oficial de Nomad Studio), que **sí se mantiene**: es gratuita, automática y es la que protege las actualizaciones.

Consecuencia, **solo la primera vez** que se abre un ZIP descargado con el navegador:
- **Windows**: SmartScreen puede mostrar "Windows protegió tu PC" → *Más información › Ejecutar de todas formas*.
- **macOS**: Gatekeeper bloquea el lanzador y el Python incluido → *Ajustes del Sistema › Privacidad y seguridad › Abrir igualmente*, o `xattr -dr com.apple.quarantine <carpeta NomadStudio>`.
- **Linux**: nada.

Las actualizaciones que descarga la propia app no reciben la marca de "descargado de internet" (§6.3), así que no vuelven a salir estos avisos.

La guía de instalación de la web DEBE explicar estos pasos con capturas, en los 4 idiomas.

---

## 5. Comprobar

### 5.1 Cuándo

- Al arrancar, **como mucho una vez cada 24 h** (se guarda la hora en `data/updates/state.json`).
- Con el botón **Ajustes › Actualizaciones › Comprobar ahora**.
- Nunca si el usuario desactivó "Buscar actualizaciones automáticamente", salvo el botón manual.
- Nunca con `channel: "store"` (§12), ni siquiera con el botón manual: la Store es la única vía de actualización de esa instalación.
- La comprobación NO DEBE retrasar el arranque: va en segundo plano y falla en silencio (se registra en el log, sin aviso) si no hay red.

### 5.2 Petición

- Canal `stable`: `GET https://api.github.com/repos/<update_repo>/releases/latest` (GitHub ya excluye borradores y *pre-releases*).
- Canal `beta`: `GET https://api.github.com/repos/<update_repo>/releases?per_page=10` y se toma la versión mayor, incluidas *pre-releases*.
- Cabeceras: `Accept: application/vnd.github+json`, `User-Agent: NomadStudio/<versión>`, e `If-None-Match` con el `ETag` de la respuesta anterior. Sin credenciales ni identificadores.
- GitHub limita las peticiones sin credenciales por IP (hoy 60 por hora); con una comprobación diaria sobra.

### 5.3 Decisión

Hay actualización si:
1. `tag_name` sin la `v` es una versión SemVer válida **mayor** que `portable.json.version`;
2. existen en la Release el ZIP de `portable.json.platform`, `SHA256SUMS.txt` y `SHA256SUMS.sig`;
3. el usuario no la marcó como **"Omitir esta versión"**.

Si falta el ZIP de la plataforma, no se ofrece (se registra en el log).

---

## 6. Descargar y verificar

### 6.1 Descarga en segundo plano (por defecto)

Con **"Descargar actualizaciones automáticamente"** activado (por defecto, §10):

1. Al detectar la versión (§5.3), la app descarga el ZIP en segundo plano, **sin aviso previo**.
2. Lo verifica (§6.3) y lo prepara en `app.new/` (§7.1).
3. **Solo entonces** muestra el aviso de §6.2.

Reglas de la descarga en segundo plano:
- **Baja prioridad**: un único hilo de descarga, que se pausa mientras haya una generación o una tarea de LM Studio en curso y se reanuda después (la cola de la app sabe cuándo).
- **No bloquea nada**: el usuario puede seguir usando la app. Su progreso solo se ve en Ajustes › Actualizaciones.
- **Si falla** (sin red, espacio, verificación): se reintenta en la siguiente comprobación (§5.1). Solo se avisa al usuario si la **verificación** falla, porque indica un problema serio con la Release.
- **Espacio**: antes de empezar se comprueba espacio libre (tamaño del ZIP × 3: ZIP, extracción y `app.old`). Si no hay, no se descarga y se muestra el aviso de §6.2 en modo manual con el motivo.
- Una versión marcada como **"Omitir esta versión"** no se descarga.

Con la opción **desactivada**, el aviso aparece al detectar la versión, con **[ Descargar ]** **[ Más tarde ]** **[ Omitir esta versión ]**, y la descarga es visible con progreso y **Cancelar**.

En los dos modos, la descarga va a `data/updates/downloads/NomadStudio-1.3.0-<plataforma>.zip.part`, se renombra al terminar y, si se corta, se PUEDE reanudar con cabeceras `Range`.

### 6.2 Aviso: lista para instalar

> **Nomad Studio 1.3.0 listo para instalar** · tienes la 1.2.1
> · Los paquetes ya pueden añadir sus propios bloques de interfaz.
> · …
> **[ Reiniciar ahora ]** **[ Al cerrar la app ]** **[ Omitir esta versión ]**

Aparece como aviso discreto en el hub (no modal) y en Ajustes › Actualizaciones. Si `breaking` tiene contenido o hay paquetes incompatibles (§9), se muestra destacado. **Nunca se reinicia sin pulsar un botón.** "Omitir esta versión" borra `app.new/` y la descarga.

### 6.3 Verificación

En este orden; cualquier fallo descarta la descarga y muestra por qué:

1. Descargar `SHA256SUMS.txt` y `SHA256SUMS.sig`.
2. Verificar la firma Ed25519 de `SHA256SUMS.txt` con las claves de confianza de la app (`app/security/trusted_keys.json`, las mismas de los packs). Clave desconocida o revocada → descartar.
3. Calcular el sha256 del ZIP descargado y compararlo con su línea de `SHA256SUMS.txt`.
4. Comprobar el ZIP: una única carpeta `app/` en la raíz, sin rutas absolutas ni `..`, sin enlaces simbólicos, límites de tamaño (mismas reglas que `PACKAGE_FORMAT.md` §2.2).
5. Leer `app/portable.json` del ZIP: `version` y `platform` DEBEN coincidir con lo anunciado.

La verificación protege aunque alguien llegue a modificar la Release: sin la clave privada no puede generar un `SHA256SUMS.sig` válido.

La descarga la hace la propia app (Python), no el navegador: en macOS los ficheros extraídos no reciben la marca de cuarentena de Gatekeeper.

---

## 7. Aplicar

### 7.1 Preparar (con la app en marcha)

1. Extraer el ZIP a `<raíz>/app.new/`, conservando permisos de ejecución.
2. Comprobar compatibilidad de datos (§8) y de paquetes (§9). Guardar los avisos para mostrarlos en §6.2.
3. Escribir `<raíz>/update-pending.json`:
   ```json
   { "from": "1.2.1", "to": "1.3.0", "prepared_at": "2026-09-21T09:00:00Z", "backup": "data/backups/before-1.3.0" }
   ```
4. Mostrar el aviso de §6.2: **[ Reiniciar ahora ]** **[ Al cerrar la app ]**.

Si el usuario elige "Al cerrar la app", la actualización se aplica la próxima vez que salga normalmente.

### 7.2 Copia de seguridad de datos

Justo antes de salir para actualizar:
- Copia de `data/` a `data/backups/before-<versión nueva>/`, **excluyendo** `data/backups/`, `data/updates/` y las carpetas pesadas regenerables (`packages/*/site-packages/`, cachés).
- Se guardan las **2 últimas** copias; las anteriores se borran.
- Si la copia falla (p. ej. sin espacio), NO se aplica la actualización y se avisa.

### 7.3 Cambio de carpetas (lanzador)

La app no puede reemplazar sus propios ficheros mientras se ejecuta, y en Windows no se puede renombrar una carpeta con ficheros abiertos. Por eso:

1. La app lanza el lanzador de la raíz en modo aplicar, pasándole su PID: `NomadStudio.bat --apply-update --wait-pid 12345` (o `.command` / `.sh`), y se cierra.
2. El lanzador **espera a que ese proceso termine** (máx. 60 s; si no, avisa y no toca nada).
3. Renombra `app/` → `app.old/` y `app.new/` → `app/`. Si el primer renombrado falla (fichero bloqueado por antivirus, explorador abierto en la carpeta…), reintenta unos segundos y, si sigue fallando, deja todo como estaba y arranca la versión anterior con un aviso.
4. Borra `update-pending.json`, escribe `update-applied.json` y arranca la app nueva.

### 7.4 El lanzador

- Es un **script** por plataforma (`NomadStudio.bat`, `NomadStudio.command`, `NomadStudio.sh`) en la raíz, **no un ejecutable**: sin firma de código, un `.exe` propio pequeño es lo que más falsos positivos provoca en los antivirus, mientras que un script que llama al Python incluido casi nunca los da. Es el modelo de ComfyUI portable (`run_nvidia_gpu.bat`). Se renuncia al icono propio.
- Arranca `app/python/…` con el punto de entrada de la app, y en modo `--apply-update` hace §7.3 y §7.5.
- **La lógica de cambio de carpetas y vuelta atrás va en el propio script, no en Python dentro de `app/`**: mientras el Python de `app/` se ejecuta, Windows bloquea la carpeta y no se puede renombrar. El script solo espera, renombra, espera la marca de arranque y deshace si hace falta; todo lo demás (comprobar, descargar, verificar, preparar) lo hace la app.
- **No depende del código de la app** para el cambio de carpetas: si `app/` nueva está rota, el lanzador sigue funcionando.
- Tras arrancar la app, el lanzador **termina**: no queda en ejecución.
- **Actualizar el propio lanzador**: la app nueva, en su primer arranque, compara `app/launcher/` con los de la raíz y los sustituye si cambian. Es seguro porque el lanzador ya no se está ejecutando. Un cambio en el formato de `--apply-update` DEBE mantener compatibilidad con el lanzador anterior durante al menos una versión.

### 7.5 Comprobación de arranque y vuelta atrás

- La app nueva, cuando está lista (servidor respondiendo y datos migrados), escribe `data/updates/started-ok-<versión>`.

**`GET /api/health`** (implementada en `app/__init__.py` + `app/services/app_info.py`) responde solo si Nomad Studio ha arrancado, de forma inmediata y **sin consultar ningún servicio externo**:

```json
{ "status": "ok", "version": "1.3.0", "portable": true, "platform": "windows-x64", "data_schema": 3, "uptime_s": 12.4 }
```

En una copia de desarrollo (sin `portable.json`) o si `portable.json` está dañado: `"version": "dev"`, `"portable": false`, y el resto a `null`. Un `portable.json` dañado nunca impide arrancar ni hace fallar la ruta. Respuesta con `Cache-Control: no-store`.

La usan la prueba de humo del build (§4.1) y esta comprobación de arranque. NO DEBE depender de ComfyUI ni de LM Studio: en los runners de GitHub no existen, y un ComfyUI apagado no significa que la actualización haya fallado (provocaría vueltas atrás sin motivo).

No confundir con los **pilotos de servicios** que ya existen (`app/static/js/services/nav_status.js`): comprueban si ComfyUI (`POST /api/models/settings/test` → `system_stats`) y LM Studio (`GET /api/models/chat/ping`) están accesibles, para mostrarlo al usuario, reintentando cada 30 s mientras están caídos. Son independientes de las actualizaciones.
- El lanzador espera esa marca hasta **90 s**:
  - **Aparece** → actualización correcta. `app.old/` se conserva hasta la siguiente actualización (y se borra entonces).
  - **El proceso termina antes o no aparece** → **vuelta atrás**: `app/` → `app.failed-<versión>/`, `app.old/` → `app/`, restaurar `data/` desde la copia de §7.2 si hubo migración de datos, arrancar la versión anterior y mostrar *"No se pudo actualizar a 1.3.0; se ha vuelto a 1.2.1"* con el log del fallo.
- Tras una vuelta atrás, esa versión queda marcada para no volver a ofrecerse automáticamente (el usuario puede reintentar desde Ajustes).

### 7.6 Resultado

En el primer arranque tras actualizar: *"Nomad Studio actualizado a 1.3.0"*, con las novedades (`release-notes.json`) y, si procede, los avisos de paquetes (§9).

---

## 8. Datos y migraciones

- `data/version.json` guarda el `data_schema` actual de la carpeta de datos.
- Si la app nueva tiene un `data_schema` mayor, ejecuta sus **migraciones** al arrancar, en orden, antes de escribir `started-ok` (§7.5). Cada migración DEBE ser idempotente y registrar lo que hace en el log.
- Si `data/version.json` es **mayor** que el `data_schema` de la app (se intenta volver a una versión anterior a mano), la app NO DEBE tocar los datos: arranca en modo solo lectura y explica que esos datos son de una versión más nueva.
- La copia de §7.2 es la vía de recuperación si una migración sale mal.
- Primera migración prevista: sacar perfiles, Sessions, Depots, Build, ajustes y motores del código a `data/` y pasar los pasos de Session al formato con `flow.package` (`PACKAGE_FORMAT.md` §13.4, §15).

---

## 9. Compatibilidad de paquetes

- Antes de aplicar (§7.1), la app compara el `app_version` de cada paquete instalado con la versión nueva.
- Los que no sean compatibles se listan en el aviso: *"Estos paquetes no funcionarán con 1.3.0: …"*. El usuario PUEDE actualizar igualmente.
- Tras actualizar, esos paquetes quedan `incompatible` (`PACKAGE_FORMAT.md` §11.3), visibles con su motivo, hasta que se importe una versión compatible.
- Si `release-notes.json.min_package_schema` sube, los paquetes con un `schema_version` inferior se tratan igual.

---

## 10. Ajustes › Actualizaciones

| Opción | Por defecto |
|---|---|
| Buscar actualizaciones automáticamente | Activado |
| Descargar actualizaciones automáticamente (§6.1) | Activado |
| Canal | Estable |
| Comprobar ahora | — |
| Última comprobación | Fecha y resultado |
| Versión instalada | `portable.json.version`, plataforma y commit |
| Versiones omitidas | Lista, con opción de quitar |
| Volver a la versión anterior | Solo si existe `app.old/`: aplica el cambio inverso con el lanzador (§7.3), sin restaurar datos salvo que el usuario lo pida |

Todos los textos en los 4 idiomas de la app.

---

## 11. Antes del lanzamiento (repo privado)

`api.github.com` no responde sin credenciales para un repo privado, así que la comprobación no funciona hasta que `NomadStudio` sea público. Para probar el sistema antes:

- **Origen alternativo**: variable `NOMAD_UPDATE_SOURCE` o `update_source` en `data/settings`:
  - `github:<usuario>/<repo-de-pruebas>` → un repo público de pruebas con Releases de prueba;
  - `file:///D:/pruebas/updates/` → carpeta local con los mismos ficheros de §3 y un `latest.json` que imita la respuesta de GitHub.
- Las versiones de prueba DEBEN firmarse con una **clave de pruebas** distinta de la oficial, incluida solo en builds de desarrollo, nunca en `trusted_keys.json` de una versión publicada.
- Probar como mínimo: actualización correcta, firma inválida, hash que no coincide, corte de descarga, carpeta bloqueada en Windows, versión nueva que no arranca (vuelta atrás) y migración de datos.

---

## 12. Canal futuro: Microsoft Store

Segundo canal para Windows, **después** del lanzamiento con el ZIP portable y cuando la app esté estable. macOS y Linux no cambian. Es la forma gratuita de tener una instalación firmada, sin avisos de SmartScreen ni falsos positivos de antivirus, y con actualizaciones automáticas, sin certificado de firma propio (§4.4).

### 12.1 Por qué la Store y no un certificado

- **Firma**: un paquete **MSIX** publicado en la Store lo firma Microsoft al publicarlo. No hace falta certificado propio, token USB ni firma en la nube.
- **Actualizaciones**: las gestiona la Store (como Steam con Blender).
- **Cuenta**: el usuario ya tiene experiencia como desarrollador de la Store. Confirmar las condiciones vigentes de la cuenta individual (coste de alta y verificación de identidad) al abrirla.
- **Ficha de la tienda** en los 4 idiomas (issue #88).
- **Precedentes** de apps que ejecutan extensiones con código (Blender, Python).

Una alternativa descartada: enviar a la Store un instalador `.msi`/`.exe` clásico en lugar de MSIX. Ese tipo de envío exige que el instalador venga firmado con un certificado propio reconocido, que es justo lo que se quiere evitar.

### 12.2 Diferencias con la versión portable

| Aspecto | ZIP portable | Microsoft Store (MSIX) |
|---|---|---|
| Carpeta del programa | `NomadStudio/app/`, escribible | Instalada por Windows en `WindowsApps`, **solo lectura** |
| Carpeta de datos | `NomadStudio/data/` hermana (`PACKAGE_FORMAT.md` §12.1) | **No puede ser hermana**: se aplica el caso de programa no escribible, que pregunta proponiendo `~/NomadStudio` |
| Punto de entrada | `NomadStudio.bat` | **Un `.exe` de entrada**: la Store no admite un `.bat`. Al firmarlo Microsoft no hay falsos positivos |
| `portable.json.channel` | `stable` / `beta` | `store` |
| Actualizaciones | GitHub Releases (§5–7) | La Store. Actualizador de GitHub desactivado (§5.1) |
| Cambio de carpetas y vuelta atrás (§7.3–7.5) | Lanzador | No aplica: Windows reemplaza el paquete |
| Copia de seguridad antes de migrar datos (§7.2, §8) | Antes de aplicar | Al detectar en el arranque que `data_schema` sube respecto a `data/version.json`, antes de migrar |
| Paquetes de flows, addons, wheels | En `data/packages/` | Igual: viven en la carpeta de datos, fuera del paquete MSIX, así que se instalan y actualizan igual |

### 12.3 Reglas para la versión Store

- **Nada en AppData.** Dentro de un MSIX, lo que la app escribe en AppData se redirige a una carpeta privada del paquete, que se borra al desinstalar y el usuario no ve. Toda escritura DEBE ir a la carpeta de datos resuelta (`PACKAGE_FORMAT.md` §12.1). Coincide con D9 (nunca AppData).
- **La carpeta de datos no se borra al desinstalar** desde la Store, porque está fuera del paquete. La guía DEBE explicarlo.
- **Nada se escribe junto al programa**: ni `data-location.json` en la raíz (se usa el puntero `~/NomadStudio/data-location.json`), ni `app.new/`, ni logs.
- **Procesos**: el paquete declara ejecución de confianza total (`runFullTrust`) para poder arrancar el servidor local y abrir el navegador. Instalar dependencias de nivel 3 con pip (`PACKAGE_FORMAT.md` §9.5) escribe en la carpeta de datos, así que funciona igual.
- **El `.exe` de entrada** hace lo mismo que el `.bat` salvo el cambio de carpetas: arranca el Python incluido con el punto de entrada de la app y abre el navegador. Se construye en el build (§12.4).

### 12.4 Build

Un trabajo más en `release.yml` (§4.1), solo para Windows, que parte del mismo contenido de `app/`:

1. Genera `portable.json` con `channel: "store"`.
2. Añade el `.exe` de entrada y el manifiesto del paquete (`AppxManifest.xml`: identidad, versión en formato `1.3.0.0`, logos, idiomas, `runFullTrust`).
3. Empaqueta con `MakeAppx` (Windows SDK, disponible en los runners de Windows) en `NomadStudio-1.3.0-store.msix`.
4. **No se firma**: lo firma la Store al publicar.
5. Se sube como artefacto del workflow, **no** como fichero de la Release pública (un MSIX sin firmar no se puede instalar fuera de la Store).
6. El envío a la Store puede hacerse a mano desde Partner Center o, más adelante, automatizarse con la API de envíos de la Store.

### 12.5 Revisión de Microsoft

- La certificación tarda días. Una versión urgente llega antes por el ZIP portable que por la Store.
- La ficha DEBE declarar que la app depende de software instalado aparte (ComfyUI, LM Studio) para su función principal.
- Antes del primer envío, **revisar las políticas vigentes de la Store** sobre código que se descarga o ejecuta después de instalar (paquetes con addons de Python y bloques de interfaz con JS, `PACKAGE_FORMAT.md` §9) y cómo describirlo en el envío.

---

## 13. Preguntas abiertas

1. ~~Firma de la app para el sistema~~ → **cerrada** (§4.4): no se usa firma de Apple ni de Microsoft; guía de instalación con los pasos para los avisos de la primera vez.
2. ~~Descarga en segundo plano~~ → **cerrada** (U4, §6.1): se descarga, verifica y prepara sola (desactivable); instalar y reiniciar siempre lo decide el usuario.
3. ~~Lanzador~~ → **cerrada** (§7.4): scripts `.bat`/`.command`/`.sh`, no ejecutable.
4. **Actualizaciones parciales** (solo los ficheros que cambian): fuera de la versión 1; siempre se descarga la versión completa.
5. ~~Fichero de bloqueo~~ → **cerrada** (§4.3): `requirements.lock` generado con `uv`, en la raíz del repo.
6. **Microsoft Store** (§12): cuándo abrir el canal, y confirmar antes del primer envío las condiciones de la cuenta y las políticas sobre código descargable.
