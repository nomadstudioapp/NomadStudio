# Formato de paquete de Nomad Studio

> Especificación v0.1 (borrador) · 2026-09-13
>
> Principio: **Nomad Studio arranca vacío** y cada flow se instala importando un ZIP, sea del tipo que sea. Este documento define ese ZIP, cómo se valida e instala, el índice que lo registra y cómo se migra el catálogo actual.
>
> Las palabras **DEBE**, **NO DEBE**, **DEBERÍA** y **PUEDE** se usan en sentido normativo.

---

## 0. Decisiones

**Cerradas**

| # | Decisión |
|---|---|
| D1 | Un paquete es **un ZIP**. Se lee, se valida y se importa. |
| D2 | **Cualquier ZIP es instalable**, también con código Python. El importador no restringe el origen: protege contra ZIPs mal formados y avisa antes de instalar código. |
| D3 | Hay un **índice generado por el importador**. El paquete es la verdad; el índice es una copia derivada. El hub solo lee el índice. Motivo: fiabilidad (un paquete roto no puede bloquear el hub). |
| D4 | Basta con **un idioma, el que sea**. El paquete declara `default_lang`. Orden de respaldo: idioma activo → `default_lang` → `en` → cualquiera. |
| D5 | Los textos de los pasos se traducen con **claves por paso y campo**, no con el texto inglés como clave. |
| D6 | La card tiene `style: "icon"` (por defecto) o `"cover"` (imagen a toda la card, recorte anclado arriba por defecto). |
| D7 | Los addons siguen el modelo de Blender Extensions: manifest aparte del código, `register()`/`unregister()` y permisos declarados (informativos). |
| D8 | Plataformas objetivo: **Windows, macOS y Linux**. |
| D9 | **Datos del usuario junto al programa, en carpetas hermanas**: `NomadStudio/app/` (se reemplaza entera al actualizar) y `NomadStudio/data/` (nunca se toca), como ComfyUI portable. Nunca en AppData ni carpetas ocultas. El usuario PUEDE elegir otra carpeta (primer arranque o Ajustes). Ver §12.1. |
| D10 | Dependencias de Python en **tres niveles** (§9.5): 1) base de librerías que trae la app, con versiones exactas; 2) librerías pequeñas o solo Python, como wheels dentro del ZIP; 3) librerías pesadas compiladas, descarga opcional con pip tras confirmación. |
| D11 | **Los modelos de IA se ejecutan siempre en ComfyUI**, nunca dentro del proceso de Nomad Studio. Un addon no trae torch, tensorflow ni similares (§9.7). |
| D12 | **Firma dentro del ZIP** (`SIGNATURE.json`, modelo Firefox/Java/Android): se firma la lista de hashes del contenido, no los bytes del ZIP. Opcional para cualquier paquete; obligatoria para los packs oficiales que traigan código (addon de Python o bloques de interfaz con JS). Un paquete es **oficial o no oficial**, sin claves de terceros: los no oficiales se instalan igual (D2) con el aviso "instálalo solo si confías en la fuente" (§11.4). |
| D13 | Un paquete PUEDE aportar **bloques de interfaz nuevos** (tipos de paso) con su propio JS y CSS, registrados con una API estable. Los bloques de la app se registran por el mismo mecanismo. Es código de terceros en el navegador: mismo aviso y misma firma que el Python (§9.8). |
| D14 | Cada pack tiene su **ficha en el repo público Nomad Studio Packs**, y su manifest la referencia en `info_url`. La ficha contiene el enlace de compra (Ko-fi). Las Sessions guardan de qué pack viene cada flow; si al abrir una falta un pack, un modal enlaza a su ficha oficial (§13.4, §13.5). |

**Abiertas**: ver §14.

---

## 1. Conceptos

| Término | Qué es |
|---|---|
| **Paquete** | Un ZIP con `manifest.json`. Es la unidad que se instala, actualiza y desinstala. |
| **Contribución** | Lo que un paquete aporta a la app: flows, workflows, motores, addon, template packs, presets, etiquetas, página. Un paquete PUEDE aportar varias. |
| **Flow** | Lo que aparece como card en Create, Refine o Mix y se abre como página de flow. |
| **Motor** | Un workflow de generación importado (Krea 2, Flux Klein, Qwen…) que los flows eligen con `workflow_picker`/`engine_select`. Hoy vive en `import_registry.json`. |
| **Addon** | Código Python que se ejecuta en el servidor. PUEDE aportar un flow o solo una capacidad que usan otros flows. |
| **Índice** | Registro de paquetes instalados y de lo que aportan, escrito solo por el importador. |

Correspondencia con los seis tipos de flow que existen hoy:

| Tipo actual | Se expresa como |
|---|---|
| A. Flow + workflow de ComfyUI | `contributes.flows` + `contributes.workflows` |
| B. Workflow con nodo `flow_data` | Igual que A; el importador extrae el `flow_data` a un flow normal (§5.3) |
| C. Solo motor | `contributes.flows` + `requires.engines` |
| D. Addon | `contributes.addon` (+ `contributes.flows` si tiene card) |
| E. Paquete de contenido | `contributes.template_packs` / `contributes.presets` |
| F. Página propia | `contributes.flows` con `page` (§5.6) |

---

## 2. El contenedor ZIP

### 2.1 Estructura

```
mi-paquete.zip
├── manifest.json            ← OBLIGATORIO, en la raíz del ZIP
├── flows/                   ← definiciones de flow (*.json)
├── workflows/               ← workflows de ComfyUI en formato API (*.json)
├── engines/                 ← motores (*.json)
├── i18n/                    ← textos de pasos: en.json, es.json, zh.json, ko.json…
├── assets/                  ← iconos, portadas, imágenes de ejemplo, JS/CSS de páginas
├── addon/                   ← código Python del addon (__init__.py …)
├── ui/                      ← bloques de interfaz: JS y CSS de tipos de paso (§9.8)
├── wheels/                  ← dependencias Python empaquetadas (*.whl)
├── data/                    ← datos de template packs, presets, etc.
├── LICENSE                  ← DEBERÍA existir
└── SIGNATURE.json           ← opcional: firma del contenido (§11.4)
```

Solo `manifest.json` es obligatorio. Las carpetas son una convención: el manifest DEBE referenciar explícitamente cada fichero que use, con rutas relativas a la raíz del ZIP.

### 2.2 Reglas del contenedor

El importador DEBE rechazar el ZIP si:

- `manifest.json` no está en la raíz, o no es JSON válido en UTF-8.
- Alguna entrada tiene ruta absoluta, unidad (`C:`), `..`, o resuelve fuera de la carpeta de destino (*zip slip*).
- Contiene enlaces simbólicos.
- Supera los límites: **200 MB** comprimido, **1 GB** descomprimido, **5.000** ficheros, ratio de compresión > 100:1 en un fichero (bomba ZIP). Los límites son configurables en Ajustes.
- Dos entradas difieren solo en mayúsculas (`Icon.png` y `icon.png`): en Windows y macOS colisionan.

Rutas: siempre con `/`, sensibles a mayúsculas (Linux lo es). El importador DEBE comprobar que cada ruta citada en el manifest existe **con las mismas mayúsculas**.

Se ignoran `__MACOSX/`, `.DS_Store`, `Thumbs.db` y `__pycache__/`.

---

## 3. `manifest.json`

### 3.1 Ejemplo mínimo (flow tipo C)

```json
{
  "schema_version": 1,
  "id": "nomad.simple",
  "version": "1.0.0",
  "default_lang": "en",
  "name": { "en": "Simple", "es": "Simple" },
  "summary": { "en": "Write a prompt, pick an engine, generate." },
  "author": { "name": "Nomad Studio" },
  "license": "Apache-2.0",
  "app_version": ">=0.9.0",
  "requires": {
    "engines": [{ "category": "image" }]
  },
  "contributes": {
    "flows": ["flows/simple.json"]
  }
}
```

### 3.2 Campos

| Campo | Tipo | Obl. | Descripción |
|---|---|---|---|
| `schema_version` | entero | sí | Versión de este formato. Hoy `1`. |
| `id` | string | sí | Id global del paquete. `^[a-z0-9]+(\.[a-z0-9-]+)+$`, p. ej. `nomad.portrait-fix`, `kim.hanbok-looks`. Es la identidad para actualizar y desinstalar. |
| `version` | string | sí | SemVer (`1.2.0`). |
| `default_lang` | string | sí | Idioma de origen (`en`, `es`, `zh`, `ko`, u otro código BCP 47). DEBE existir texto en ese idioma. |
| `name` | textos | sí | Nombre del paquete (§7.1). |
| `summary` | textos | no | Una frase para el importador y la lista de paquetes. |
| `author` | objeto | sí | `name` obligatorio; `url` y `email` opcionales. |
| `license` | string | sí | Identificador SPDX o `"proprietary"`. |
| `homepage` | string | no | URL. |
| `info_url` | string | no* | URL de la **ficha del pack en Nomad Studio Packs** (§13.5), p. ej. `<PACKS_BASE_URL>/packs/nomad.portrait-fix/`. *Obligatorio en packs oficiales: la herramienta `build` en modo oficial DEBE negarse sin él. Es el enlace que guardan las Sessions (§13.4). |
| `store_url` | string | no | Enlace de compra o descarga (Ko-fi). Opcional: en packs oficiales la referencia es la ficha, que ya lo contiene y se puede cambiar sin publicar una versión nueva del pack. Útil para packs de la comunidad sin ficha. |
| `changelog` | objeto | no | Versión → textos (§7.1). P. ej. `{"1.2.0": {"en": "Adds Open Eyes.", "es": "Añade Abrir ojos."}}`. El importador muestra las entradas entre la versión instalada y la nueva (§13.1). |
| `app_version` | string | no | Rango de versiones de Nomad Studio compatibles (`>=0.9.0,<2`). |
| `platforms` | lista | no | Ver §8.3. Si falta: todas. Obligatorio si hay wheels compilados. |
| `requires` | objeto | no | Dependencias (§8). |
| `permissions` | objeto | no | Solo para addons (§9.4). |
| `group` | objeto | no | Grupo del hub en el que aparecen sus flows (§6.4). |
| `contributes` | objeto | sí | Qué aporta (§4). DEBE aportar al menos una cosa. |

"textos" es siempre un objeto idioma → string (§7.1).

---

## 4. `contributes`

```json
"contributes": {
  "flows":          ["flows/remove_bg.json"],
  "workflows":      ["workflows/birefnet_remove_bg.json"],
  "engines":        ["engines/krea2_turbo.json"],
  "addon":          { "entry": "addon/__init__.py", "provides": ["edge-defringe"] },
  "template_packs": ["data/template_packs.json"],
  "presets":        ["flows/presets/wander.json"],
  "tags":           "data/tags.json",
  "i18n":           "i18n/",
  "step_types":     [{ "type": "layer_compositor", "script": "ui/layer_compositor.js", "style": "ui/layer_compositor.css" }]
}
```

| Clave | Contenido |
|---|---|
| `flows` | Definiciones de flow (§5). |
| `workflows` | Workflows de ComfyUI que usan sus flows (§5.2). |
| `engines` | Motores que instala (§8.1). |
| `addon` | Código Python (§9). |
| `template_packs` | Datos de plantillas con placeholders (§10.1). |
| `presets` | Looks de un solo clic (§10.2). |
| `tags` | Etiquetas nuevas con sus traducciones (§7.3). |
| `i18n` | Carpeta con los textos de pasos por idioma (§7.2). |
| `step_types` | Bloques de interfaz nuevos con su JS y CSS (§9.8). |

---

## 5. Definición de flow

El formato de flow es el que ya interpreta el motor (`app/instructions/flows/**/*.json`). Se mantiene tal cual, con los cambios de esta sección.

### 5.1 Esquema

```json
{
  "id": "refine.pf_remove_skin_glare",
  "category": "refine",
  "card": {
    "label": { "en": "Remove Skin Glare", "es": "Quitar brillos de la piel" },
    "desc":  { "en": "Removes shiny specular highlights from the skin." },
    "tags":  ["portrait", "skin", "glare"],
    "style": "icon",
    "icon":  "assets/icon.svg",
    "accent": "#6b8cff"
  },
  "complexity": 1,
  "entry_category": "Portrait",
  "entry_model": "Qwen",
  "llm_required": false,
  "comfyui_required": true,
  "steps": [
    { "id": "image",  "type": "image_picker", "required": true },
    { "id": "params", "type": "workflow_params",
      "workflow_file": "workflows/refine_qwen_2511_edit.json", "image_node": "7",
      "fields": [ { "id": "prompt", "type": "textarea" } ] },
    { "id": "generate", "type": "action", "calls": "generation.submit_refine",
      "input_map": {
        "workflowFile":   "steps.params.output.workflow_file",
        "imageDataUrl":   "steps.image.output.image_data_url",
        "advancedValues": "steps.params.output.adv_values" } },
    { "id": "result", "type": "result_view" }
  ]
}
```

| Campo | Obl. | Notas |
|---|---|---|
| `id` | sí | `<category>.<nombre>`, `nombre` en `^[a-z0-9_]+$`. **Único en toda la instalación.** La URL es `/nomad-studio/<category>/<nombre con - en vez de _>`. |
| `category` | sí | `create`, `refine` o `mix`. DEBE coincidir con el prefijo del `id`. |
| `card` | sí | Presentación en el hub (§6). Sustituye a `label`, `card_desc`, `card_tags` y `card_css_modifier`. |
| `complexity` | no | `1`–`3`. Sin él no se muestra indicador. |
| `entry_category`, `entry_model` | no | Igual que hoy. |
| `llm_required`, `comfyui_required` | no | Igual que hoy; el importador los usa para avisar. |
| `status` | no | `active` (por defecto) o `planned`. |
| `steps` | sí* | Pasos. *Salvo flows con `page` (§5.6). |
| `page` | no | §5.6. |

**Tipos de paso.** Un paso (`type`) es un bloque de la columna izquierda de la página de flow. Hay dos orígenes:

- **Bloques de la app** (versión 1): `action`, `bulk_vision`, `civitai_paste`, `ideogram_composer`, `image_picker`, `json_input`, `lettering_builder`, `llm_transform`, `param_group`, `prompt_input`, `result_view`, `scene_builder`, `template_picker`, `upscale_picker`, `vision_describe`, `workflow_params`, `workflow_picker`. Se usan por su nombre.
- **Bloques de paquetes** (§9.8): se usan con el id del paquete delante, `"type": "nomad.layer-composer/layer_compositor"`. Hoy `layer_compositor` es un bloque de la app; con la migración pasa al paquete de Layer Composer.

Un tipo que no sea de la app ni de un paquete instalado DEBE marcar el flow como incompatible (§11.3), no romper la importación del resto del paquete. Si el tipo es de otro paquete, el flow DEBE declararlo en `requires.packages`.

**Acciones** (`calls`) de la versión 1: `generation.submit_queue`, `generation.submit_refine`, `layer_compose.submit`, `llm.edit_prompt`, `llm.ideogram_compose`, `llm.ideogram_storyboard`, `llm.story_continue`, `llm.studio_enhance`, `llm.studio_scenes`, `llm.studio_templateize`, `llm.studio_variations`, `llm.studio_variations_json`, más las que registren addons instalados (§9.3).

Los campos `label`, `placeholder`, `hint`, `note`, `description` y las `label` de `options` que aparecen dentro de `steps` son el texto en `default_lang`. Sus traducciones van en `i18n/` (§7.2).

### 5.2 Workflows

- Formato **API de ComfyUI** (el que hoy guarda `app/workflows/`).
- Las rutas en `workflow_file` son **relativas al paquete** (`workflows/x.json`). El importador las reescribe al instalar; el flow nunca apunta a `app/workflows/`.
- Un workflow PUEDE declarar los modelos que necesita (§8.2).

### 5.3 Workflows con `flow_data` (tipo B)

Un workflow que lleve el nodo `{"_meta": {"title": "flow_data"}}` se admite en `contributes.workflows`. El importador:

1. Extrae el JSON del nodo.
2. Lo convierte en un flow normal: mapea `label`/`card_desc`/`card_tags` a `card`, y `params`/`image_node` a un paso `workflow_params` que apunta a ese workflow.
3. Lo registra como flow del paquete.

El nodo `flow_data` queda en el workflow, pero la app ya no lo busca en tiempo de ejecución. Desaparece `_load_flows_from_workflows`.

### 5.4 Motor frente a workflow fijo

- **Workflow fijo** (`workflow_params.workflow_file`): el flow trae su workflow.
- **Motor elegible** (`workflow_picker`, o campo `engine_select`): el flow usa uno de los motores instalados. El flow DEBE declarar la categoría en `requires.engines` (§8.1).

### 5.5 Colisiones de id

- **Mismo `id` de flow en otro paquete**: el importador DEBE rechazar la instalación y nombrar el paquete que ya lo tiene. No hay sobrescritura silenciosa.
- **Mismo `id` de paquete**: es una actualización (§13).

### 5.6 Flows con página propia (tipo F)

Para interfaces que no se construyen con pasos (Canvas Composer):

```json
{
  "id": "mix.canvas_composer",
  "category": "mix",
  "card": { "...": "..." },
  "page": {
    "html": "assets/page/index.html",
    "scripts": ["assets/page/app.js"],
    "styles": ["assets/page/app.css"]
  }
}
```

La app pinta su cabecera estándar (breadcrumb, BACK, visor) y dentro inserta el HTML del paquete. Los assets se sirven desde `/packages/<id>/assets/...`. El HTML NO DEBE ser una plantilla Jinja: el paquete no ejecuta plantillas del servidor. Si necesita datos del servidor, los pide a una ruta de su addon.

---

## 6. La card

### 6.1 Campos de `card`

| Campo | Obl. | Descripción |
|---|---|---|
| `label` | sí | Textos (§7.1). |
| `desc` | no | Textos. Con `style: "cover"` no se muestra en la card, pero sí en búsqueda y tooltip. |
| `tags` | no | Lista de **ids** de etiqueta (§7.3). |
| `style` | no | `"icon"` (por defecto) o `"cover"`. |
| `icon` | no | SVG del paquete. Sin él, un icono genérico por categoría. SVG saneado (§11.2). |
| `accent` | no | Color `#rrggbb` para el tinte de la card. Sin él, la app lo deriva de la primera etiqueta (como hoy). |
| `cover` | con `cover` | Imagen `png`, `jpg` o `webp`, máx. 2 MB, relación recomendada 16:9.5. |
| `cover_position` | no | `top` (por defecto), `center`, `bottom` o valor CSS `object-position` (`50% 20%`). |

Si `style` es `"cover"` y la imagen falta o no carga, la card DEBE mostrarse con `style: "icon"`.

### 6.2 Qué desaparece de la app

Con `card.icon` y `card.accent` sobran:
- las ramas `if action == ...` de `flow_icon`/`refine_icon`/`mix_icon` en `nomad_studio.html`;
- las reglas `cs-card--<flow>` de CSS;
- `card_css_modifier`.

### 6.3 Etiquetas en la card

La card muestra la etiqueta traducida (§7.3). El filtro, el tinte y los iconos de etiqueta usan el id.

### 6.4 Grupos del hub

```json
"group": {
  "id": "portrait-fix",
  "label": { "en": "Portrait Fix", "es": "Retoque de retrato" },
  "order": 40
}
```

Todos los flows del paquete aparecen bajo ese grupo dentro de su categoría. Si varios paquetes declaran el mismo `group.id`, se fusionan y se usa el `label` del primero instalado. Sin `group`, van a un grupo con el nombre del paquete. Desaparece `_GROUP_LABELS`.

---

## 7. Idiomas

### 7.1 Textos cortos (manifest y card)

Objeto idioma → texto:

```json
"label": { "ko": "배경 제거", "en": "Remove Background" }
```

DEBE contener `default_lang` del paquete. Para mostrar un texto se busca, en orden: idioma activo → `default_lang` → `en` → primer valor disponible.

### 7.2 Textos de los pasos: `i18n/<lang>.json`

Un fichero por idioma, plano, con claves por ruta dentro del flow:

```json
{
  "refine.pixel_matcher": {
    "steps.image.label": "Imagen de origen",
    "steps.params.label": "Parámetros",
    "steps.params.fields.pixel_size.label": "Tamaño de píxel (px)",
    "steps.params.fields.pixel_size.note": "Tamaño de celda en píxeles…",
    "steps.params.fields.auto_detect.options.true": "Automático",
    "steps.params.fields.auto_detect.options.false": "Manual"
  }
}
```

- Primer nivel: id del flow. Debajo: ruta `steps.<id de paso>[.fields.<id de campo>].<propiedad>`; las opciones se identifican por su `value`.
- El texto en `default_lang` es el que ya está dentro del flow. El fichero de `default_lang` no es necesario.
- Una clave que falte en un idioma usa el orden de §7.1.
- Una clave que no corresponda a ningún texto del flow DEBE producir un aviso (errata), no un error.
- Los placeholders `{nombre}` DEBEN ser los mismos en todos los idiomas; si no, aviso y se usa `default_lang` para esa clave.

### 7.3 Etiquetas

- Cada etiqueta tiene un **id** estable `^[a-z0-9-]+$` (`background`, `klein-9b`).
- La app trae un **diccionario común** de etiquetas con traducciones e icono.
- Un paquete que use una etiqueta que no está en el diccionario DEBE declararla en `contributes.tags`:

```json
{ "hanbok": { "label": { "ko": "한복", "en": "Hanbok" }, "icon": "shirt" } }
```

- Si dos paquetes declaran la misma etiqueta nueva, se queda la primera y las traducciones que falten se completan con las de la segunda.

### 7.4 Qué registra el índice

Por paquete: `languages` (idiomas con textos presentes) y `translation_status` por idioma (`complete` o `partial` con número de claves que faltan). Es informativo; nunca bloquea.

---

## 8. Requisitos (`requires`)

```json
"requires": {
  "engines":  [{ "category": "image" }, { "id": "nomad.engine.qwen-image-edit-2511" }],
  "packages": [{ "id": "nomad.edge-defringe", "version": ">=1.0.0" }],
  "capabilities": ["edge-defringe"],
  "models": [
    { "folder": "diffusion_models", "file": "qwen_image_edit_2511_fp8.safetensors",
      "size": 20430000000, "sha256": "…", "url": "https://…" }
  ],
  "comfy_nodes": ["comfyui-birefnet"],
  "python": ">=3.13",
  "python_packages": ["scipy>=1.17,<2", "numpy>=2.4,<3"],
  "wheels": ["wheels/mi_libreria-1.0.0-py3-none-any.whl"],
  "python_downloads": [
    { "requirement": "opencv-python-headless==5.0.0.93", "size_mb": { "windows-x64": 44, "macos-arm64": 48, "linux-x64": 57 } }
  ],
  "llm": true,
  "vision": true
}
```

| Clave | Significado | Qué hace el importador si falta |
|---|---|---|
| `engines` | Motor por categoría o por id de paquete | Instala y marca `missing_requirements` |
| `packages` | Otro paquete con rango de versión | Instala y marca `missing_requirements` |
| `capabilities` | Capacidad que aporta algún addon (§9.2) | Instala y marca `missing_requirements` |
| `models` | Ficheros de modelo de ComfyUI | Comprueba en la carpeta de modelos configurada; ofrece descarga si hay `url` |
| `comfy_nodes` | Nodos personalizados de ComfyUI | Avisa (si ComfyUI responde, comprueba con `/object_info`) |
| `python` | Versión de Python de la app | **Rechaza** si no cumple |
| `python_packages` | Nivel 1: librerías de la base de la app (§9.5) | **Rechaza** si la app no las tiene en versión compatible |
| `wheels` | Nivel 2: wheels dentro del ZIP (§9.5) | **Rechaza** si no hay wheel para la plataforma |
| `python_downloads` | Nivel 3: descarga opcional con pip (§9.5) | Pide confirmación; si no se acepta o no hay red, instala y marca `missing_requirements` |
| `llm`, `vision` | Necesita LM Studio / modelo de visión | Avisa |

Regla: lo que no se puede resolver instalando otras cosas (Python, librerías de la base, wheels del paquete) rechaza. Lo que sí (motores, paquetes, modelos, descargas de nivel 3) instala el paquete y lo marca como pendiente, con la card visible y deshabilitada explicando qué falta.

### 8.1 Motores como paquetes

Un motor es un paquete con `contributes.engines`. El fichero contiene lo que hoy guarda cada entrada de `import_registry.json`: `category`, `name`, `workflow`, `analysis`, `basicValues`, `advancedValues`, `annotation`. No lleva `comfyApiUrl`: la URL de ComfyUI es un ajuste de la app. El id del motor es el id del paquete.

### 8.2 Modelos

`size` y `sha256` DEBERÍAN estar para poder verificar descargas. El importador NO DEBE descargar modelos sin confirmación del usuario.

### 8.3 Plataformas

Etiquetas: `windows-x64`, `windows-arm64`, `macos-arm64`, `macos-x64`, `linux-x64`, `linux-arm64`. `windows-x64` cubre Intel y AMD. Si el paquete tiene wheels compilados o descargas de nivel 3, `platforms` es obligatorio y DEBE coincidir con las plataformas para las que existen.

---

## 9. Addons

### 9.1 Declaración

```json
"contributes": {
  "addon": {
    "entry": "addon/__init__.py",
    "provides": ["edge-defringe"],
    "actions": ["edge_defringe.apply"]
  }
},
"permissions": {
  "files": "Lee y escribe imágenes en la carpeta de salida",
  "network": "No"
}
```

- `entry`: módulo de entrada. DEBE definir `register(ctx)` y PUEDE definir `unregister(ctx)`.
- `provides`: capacidades que otros paquetes pueden requerir (§8).
- `actions`: acciones que sus flows usan en `calls`.
- `ADDON_INFO` pasa a ser opcional y se ignora; los metadatos están en el manifest.

### 9.2 Addon con flow y addon sin flow

- **Con flow** (Pixel Matcher, Chroma Key, Layer Composer): `contributes.addon` + `contributes.flows`.
- **Sin flow** (Edge Defringe): solo `contributes.addon` con `provides`. Remove Background declara `requires.capabilities: ["edge-defringe"]`.

### 9.3 API para addons

Un addon NO DEBE importar módulos internos de la app (`from app…`). Recibe un contexto con la API pública estable:

```python
def register(ctx):
    ctx.routes.add("process", process, methods=["POST"])   # → /api/addons/<id>/process
    ctx.actions.add("edge_defringe.apply", apply_defringe)  # usable en flows y postproceso
    ctx.log.info("ready")

def unregister(ctx):
    pass
```

`ctx` ofrece (versión 1): `routes`, `actions`, `log`, `images` (leer/guardar en la salida del visor activo), `paths` (carpeta de datos propia del paquete, carpeta de salida), `settings` (ajustes propios del paquete), `package` (id, versión, idioma activo), `i18n.t(clave)`, `comfy` (enviar un workflow del paquete a ComfyUI y recoger el resultado por la cola de la app, §9.7) y `llm` (texto y visión por el cliente de LM Studio de la app).

Las rutas del addon se sirven bajo **`/api/addons/<id del paquete>/…`** mediante una única ruta de la app que reenvía al addon cargado. Así se instala y desinstala sin reiniciar (Flask no admite registrar blueprints en caliente). Es incompatible con las URLs actuales (`/api/models/pixel-match/process`): la migración (§15) actualiza los flows que las llaman.

### 9.4 Permisos

Claves: `files`, `network`, `clipboard`, `subprocess`, `gpu`. Cada valor es el motivo, en texto. Son **informativos**: el importador los muestra antes de instalar, pero la app no aísla el código.

### 9.5 Dependencias de Python: tres niveles

Python solo carga **una versión de cada librería por proceso**, y las librerías compiladas pesan decenas de MB por plataforma (scipy ~37 MB, opencv ~50 MB). Por eso las dependencias se resuelven en tres niveles, en este orden de preferencia.

#### Nivel 1: base de la app (`requires.python_packages`)

La app trae un conjunto de librerías con **versiones exactas**, fijadas en `requirements.txt` y probadas con todos los addons oficiales:

| Librería | Versión |
|---|---|
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| Pillow | 12.2.0 |
| scikit-learn | 1.9.0 |
| joblib | 1.5.3 |
| threadpoolctl | 3.6.0 |
| Flask | 3.1.0 |

Todas tienen wheels cp313 para `windows-x64`, `macos-arm64`, `macos-x64`, `linux-x64` y `linux-arm64`.

- Un paquete que use una librería de la base DEBE declararla en `requires.python_packages` con un rango (`"scipy>=1.17,<2"`) y NO DEBE empaquetarla ni descargarla.
- El importador compara el rango con la versión de la base. Si no es compatible, **rechaza**: no puede haber dos versiones.
- La base se amplía en versiones de la app, nunca desde un paquete. Cambiar una versión de la base obliga a volver a probar los addons oficiales.
- La app expone la lista de la base (librería y versión) para que la herramienta `build` y el importador la consulten.

#### Nivel 2: wheels dentro del ZIP (`requires.wheels`)

Para librerías **pequeñas o solo Python** que no están en la base.

- Van en `wheels/` y se declaran en `requires.wheels`.
- DEBERÍAN ser `py3-none-any` (valen para todas las plataformas). Un wheel compilado solo es admisible si es pequeño: **máx. 10 MB por wheel y 25 MB entre todos los wheels de una plataforma**. Por encima, nivel 3.
- Al instalar: `pip install --no-index --no-deps --target <paquete>/site-packages <wheel>`. Sin red.
- Solo se instalan los wheels compatibles con la plataforma y la versión de Python actuales. Si falta el de la plataforma, **rechaza**.
- Un wheel de una librería que está en la base (nivel 1) → **rechaza**.

#### Nivel 3: descarga opcional (`requires.python_downloads`)

Para librerías **pesadas y compiladas** que no están en la base.

```json
"python_downloads": [
  { "requirement": "opencv-python-headless==5.0.0.93",
    "size_mb": { "windows-x64": 44, "macos-arm64": 48, "linux-x64": 57 },
    "hashes": { "windows-x64": "sha256:…", "macos-arm64": "sha256:…", "linux-x64": "sha256:…" } }
]
```

- `requirement` DEBE fijar versión exacta (`==`). `size_mb` es informativo para el aviso. `hashes` DEBERÍA estar.
- Al instalar el paquete, el importador muestra: *"Este addon necesita opencv-python-headless (48 MB). ¿Descargar e instalar?"*.
- **Si se acepta**: `pip install --only-binary=:all: --no-deps --target <paquete>/site-packages <requirement>`, con `--require-hashes` si hay hashes. Nunca compila desde código fuente. Nunca instala en el entorno de la app.
- **Si no se acepta o no hay red**: el paquete se instala en estado `missing_requirements`. Desde la lista de paquetes se puede reintentar la descarga más tarde.
- Una descarga de una librería de la base (nivel 1) → **rechaza**.
- Las dependencias de la librería descargada DEBEN declararse también en `python_downloads` o estar en la base: con `--no-deps`, pip no las resuelve solo. La herramienta `build` las calcula.
- Para instalaciones sin red se PUEDE publicar aparte un ZIP de dependencias por plataforma, que el importador acepta como fuente local de estos wheels.

#### Común a los niveles 2 y 3

- Todo se instala en `<data>/packages/<id>/site-packages/`, nunca en el Python de la app.
- Al activar el addon, esa carpeta se añade a `sys.path` antes de importar su código; al desactivar, se quita.
- Si dos addons instalan la misma librería en versiones distintas, se carga la del primero que se activa. El importador DEBE avisar al detectar el conflicto.
- Desinstalar el paquete borra su `site-packages`.

### 9.6 Ciclo de vida

- **Instalado** y **activado** son estados distintos. Tras instalar, un addon queda desactivado hasta que el usuario lo activa. Antes de activar se muestra el aviso de código y los permisos.
- **Activar**: importar el módulo y llamar a `register(ctx)`. Si lanza una excepción, el paquete queda `broken` con el error y la app sigue funcionando.
- **Desactivar**: `unregister(ctx)`, retirar sus rutas y acciones del despachador y del registro, quitar su `site-packages` de `sys.path`. Los módulos ya importados pueden quedar en memoria hasta reiniciar; el despachador deja de enrutar hacia ellos.
- Al arrancar la app, los addons activados se activan en orden de dependencias. Uno que falle no impide cargar los demás.

### 9.7 Modelos de IA: siempre a través de ComfyUI

**Regla:** un paquete que necesite ejecutar un modelo de IA (difusión, segmentación, detección, upscaler neuronal, eliminación de fondo…) lo hace **en ComfyUI**, con un workflow del paquete, nunca cargando el modelo dentro del proceso de Nomad Studio. Los modelos de lenguaje y visión, igual, a través de LM Studio.

**Por qué:**
- ComfyUI ya trae su propio torch; una segunda copia dentro de la app pesa cientos de MB por plataforma (torch: ~125 MB en Windows y macOS, ~555 MB en Linux) y compite por la misma GPU.
- La cola de la app que reparte la GPU entre ComfyUI y LM Studio (Ajustes › Avanzado) solo puede ordenar lo que pasa por ella.
- El addon queda en procesado clásico (numpy, scipy, Pillow), que funciona igual en las tres plataformas.

**Cómo lo hace un addon:**
- Trae el workflow en `contributes.workflows` y lo lanza con `ctx.comfy` (§9.3). El resultado vuelve por la cola de la app.
- Declara los nodos personalizados en `requires.comfy_nodes` y los ficheros de modelo en `requires.models` (§8.2).
- Para LLM o visión, usa `ctx.llm` y declara `requires.llm` / `requires.vision`.

**Qué valida el importador:** si `requires.wheels` o `requires.python_downloads` incluyen un runtime de modelos, **rechaza** el paquete con un mensaje que explica esta regla. Lista de versión 1:

`torch`, `torchvision`, `torchaudio`, `tensorflow`, `tensorflow-*`, `keras`, `jax`, `flax`, `onnxruntime`, `onnxruntime-*`, `openvino`, `tensorrt`, `transformers`, `diffusers`, `accelerate`, `xformers`, `ultralytics`, `rembg`, `llama-cpp-python`, `vllm`, `mlx`, `mlx-*`.

La lista está en la app y se amplía con sus versiones. Es una barrera para descuidos, no un aislamiento: un addon podría descargar algo por su cuenta, y por eso se muestra el aviso de código y los permisos (§9.4, §9.6).

### 9.8 Bloques de interfaz (tipos de paso con JS)

Un flow se describe con bloques (§5.1). Si un paquete necesita un bloque que la app no tiene (un pincel de máscara, una rueda de color, el compositor de capas), trae su propio JavaScript y CSS. Un bloque de interfaz PUEDE existir sin addon de Python, y un addon PUEDE traer varios bloques.

#### Declaración

```json
"contributes": {
  "step_types": [
    { "type": "layer_compositor",
      "script": "ui/layer_compositor.js",
      "style":  "ui/layer_compositor.css" }
  ]
}
```

- `type`: `^[a-z0-9_]+$`. El nombre completo es `<id del paquete>/<type>` (`nomad.layer-composer/layer_compositor`), y así se usa en los flows. No choca con bloques de otros paquetes ni de la app.
- `script`: obligatorio. JavaScript clásico (no módulo ES), sin dependencias externas por CDN: todo lo que use va dentro del paquete.
- `style`: opcional.

#### Registro

El script DEBE registrar el bloque con la única función global que la app expone para esto:

```js
NomadStudio.registerStepType('layer_compositor', {
  apiVersion: 1,
  render: function (stepDef, el, api) {
    // Dibuja el bloque dentro de el. Devuelve opcionalmente { destroy, validate }.
    var box = document.createElement('div');
    box.className = api.cssScope;          // clase propia del bloque (ver Estilos)
    el.appendChild(box);
    api.onValuesChange(function () { /* redibujar la vista previa */ });
    return {
      validate: function () { return api.getValue('overlay_x') != null; },
      destroy:  function () { /* quitar listeners */ }
    };
  }
});
```

El nombre que se pasa es el `type` corto; la app le añade el id del paquete según el script que lo registra. Registrar un `type` no declarado en el manifest DEBE fallar.

#### API para bloques (`api`, versión 1)

| Miembro | Qué hace |
|---|---|
| `api.step` | Definición del paso (`stepDef`), de solo lectura |
| `api.flowId`, `api.packageId`, `api.lang` | Contexto |
| `api.setValue(campo, valor)` / `api.getValue(campo)` | Valores de este paso, que leen los pasos `action` por `input_map` (`steps.<id>.output.<campo>`). Equivale al `setVal`/`getVal` actual |
| `api.getStepValue(idPaso, campo)` | Leer valores de otros pasos del flow (p. ej. la imagen de fondo elegida) |
| `api.onValuesChange(cb)` | Aviso cuando cambia cualquier valor del flow. Sustituye a ganchos globales como `window._ncfLcRefresh` |
| `api.t(clave, fallback)` | Texto traducido del `i18n/` del paquete (§7.2) |
| `api.openPanel(título, fillFn, opciones)` / `api.closePanel()` | Panel lateral de la app, con su estilo |
| `api.addon.fetch(ruta, cuerpo)` | Llamada a `/api/addons/<id del paquete>/<ruta>` (§9.3). Solo a las rutas de su propio paquete |
| `api.assetUrl(ruta)` | URL pública de un fichero del paquete |
| `api.images.toDataUrl(fuente)` | Utilidades de imagen compartidas con los bloques de la app |
| `api.notify(texto, tipo)` | Aviso breve con el sistema de la app |

Un bloque NO DEBE llamar a funciones internas de la app (`setVal`, `openOptionsPanel`, `window._ncf…`) ni leer o modificar DOM fuera de `el`, salvo a través de `api`. Esas funciones pueden cambiar entre versiones sin aviso; `api` no.

Si `apiVersion` es mayor que la que soporta la app, el flow queda `incompatible` (§11.3).

#### Estilos

- La app envuelve el bloque en un contenedor con la clase `api.cssScope` (p. ej. `ns-step--nomad-layer-composer--layer_compositor`).
- Todas las reglas del `style` DEBEN empezar por esa clase. El importador DEBE avisar de selectores que no la lleven (`body`, `.nsc-input`…), porque podrían romper la app.
- Los bloques DEBERÍAN seguir la guía de estilos de Nomad Studio (`docs/NOMAD_UI_GUIDE.md`) y usar los tokens de color (`var(--accent)`, `var(--bg-panel)`…) para funcionar en todos los temas.

#### Carga

- La app carga el `script` y el `style` de un bloque **solo cuando abre un flow que lo usa**, una vez por página, antes de dibujar los pasos.
- Si el script falla al cargar o `render` lanza una excepción, ese paso muestra un error visible dentro del bloque ("No se pudo cargar el bloque layer_compositor: …") y el resto de la página sigue funcionando.
- Los ficheros se sirven desde `/packages/<id>/ui/…` con la versión del paquete en la URL, para que una actualización no deje en el navegador el JS antiguo en caché.

#### Seguridad

El JS de un bloque se ejecuta en la página con los mismos permisos que la app: puede leer lo que ve el usuario y llamar a cualquier ruta del servidor. **Es código de terceros**, igual que el Python de un addon:
- El paquete cuenta como `has_code` y se muestra el mismo aviso de código antes de activarlo (§9.6).
- La firma (§11.4) cubre `ui/` como el resto de ficheros.
- `api` restringe lo que un bloque bien hecho necesita; no impide que un bloque malicioso haga otra cosa. Aislarlo (iframe con `sandbox`) queda para una versión posterior.

#### Cambio en la app

Hoy `flow-render-all.js` elige el bloque con un `switch` fijo. Pasa a un **registro de tipos**: los 17 bloques de la app se registran con el mismo `registerStepType` (sin prefijo de paquete) y el render busca en el registro. Así el mecanismo se usa y se prueba con los propios bloques de la app.

---

## 10. Contenido

### 10.1 Template packs

`data/template_packs.json`: lista con el formato actual (`id`, `name`, `pack`, `theme`, `template`, `images[]` con `filename` y `prompt`).

- `filename` es relativo al paquete (`assets/templates/90s_smalltown.webp`).
- El paquete aporta una card de pack en el grupo **Template Packs** de Create, con `style: "cover"` y, por defecto, la primera imagen como portada. PUEDE fijarla con `card.cover`.
- Los ids de plantilla se prefijan con el id del paquete al instalar, para que no choquen.
- Opcional: `i18n` de nombres de tema. Los prompts no se traducen (son entrada del modelo).

### 10.2 Presets

Cada look es un flow con `preset_meta` (formato actual: `pack_id`, `pack_name`, `card_title`, `card_description`, `cover_image`). `cover_image` es relativo al paquete. Los looks se muestran en su galería (hoy Photo Packs), no como cards sueltas en el hub.

---

## 11. Instalación

### 11.1 Proceso

1. **Recibir** el ZIP (arrastrar o elegir fichero). Se guarda en una carpeta temporal.
2. **Leer el contenedor**: reglas de §2.2. Sin extraer todavía.
3. **Validar el manifest** contra el esquema (`schema_version`).
4. **Extraer** a `packages/.staging/<id>-<version>/`.
5. **Validar contenido y firma**: §11.2 y §11.4.
6. **Resolver requisitos**: §8. Construir el informe (rechazos, pendientes, avisos).
7. **Mostrar el resumen** al usuario: qué operación es (instalar, actualizar, reinstalar o volver a una versión anterior, §13.1), nombre, autor, versión, estado de firma, qué aporta, idiomas, requisitos pendientes, cambios desde la versión instalada y, si trae código (addon de Python o bloques de interfaz con JS), aviso de código y permisos. Pedir confirmación.
8. **Instalar dependencias de Python** (§9.5): wheels del paquete (nivel 2) y, si el usuario las aceptó en el paso 7, las descargas de nivel 3.
9. **Mover** de `.staging` a `packages/<id>/` (renombrado atómico; en actualización, la versión anterior pasa a `packages/.previous/<id>/`).
10. **Copiar assets servibles** a la carpeta pública del paquete.
11. **Escribir el índice** (§12.2).
12. Si hay addon y el usuario lo activa: §9.6.

Cualquier fallo antes del paso 9 deja la instalación como estaba y borra `.staging`.

### 11.2 Validaciones de contenido

Errores (rechazan el paquete):
- Fichero citado en el manifest que no existe (o existe con otras mayúsculas).
- JSON inválido en un flow, workflow o motor.
- Flow sin `id`, sin `category`, con prefijo que no coincide, sin `card.label`, o con id repetido (§5.5).
- `default_lang` sin textos en `name` o en algún `card.label`.
- `workflow_file` que no apunta a un workflow del paquete.
- `entry` de addon que no existe.
- `step_types` (§9.8): `script` que no existe, `type` con formato inválido o repetido dentro del paquete, o flow que usa un tipo de paquete sin declararlo en `requires.packages` ni aportarlo él mismo.
- Dependencias (§9.5): rango de `python_packages` incompatible con la base; wheel o descarga de una librería que ya está en la base; falta el wheel de nivel 2 para la plataforma; wheel compilado por encima del límite de tamaño; `python_downloads` sin versión exacta.
- Runtime de modelos de IA en `wheels` o `python_downloads` (§9.7).

Avisos (instala igualmente):
- Tipo de paso o `calls` desconocidos → ese flow queda `incompatible`.
- Claves de `i18n` que no corresponden a nada, o placeholders distintos entre idiomas.
- Etiqueta usada sin declarar ni existir en el diccionario común.
- SVG con `<script>`, `on*=` o referencias externas: se sanea y se avisa.
- Sin `LICENSE`.

### 11.3 Estados

Por paquete: `active`, `disabled`, `missing_requirements`, `broken`.
Por flow: además, `incompatible` (paso o acción desconocidos).

Un paquete `broken` o un flow `incompatible` DEBE verse en el hub y en la lista de paquetes con su motivo. Nunca se oculta en silencio.

### 11.4 Firma

Descargar un pack de la tienda oficial (Ko-fi) garantiza su origen solo en el momento de la descarga: una vez en disco, el ZIP se comparte, se renombra o se modifica, y el importador no puede saber de dónde vino. La firma viaja **dentro** del fichero.

#### Qué se firma

No se firman los bytes del ZIP (meter la firma los cambiaría), sino **la lista de hashes de su contenido**. Da igual cómo se recomprima el ZIP: se verifica el contenido, no el contenedor. Es el modelo de las extensiones de Firefox, los `.jar` de Java y los `.apk` de Android.

`SIGNATURE.json`, en la raíz del ZIP:

```json
{
  "signature_version": 1,
  "package": { "id": "nomad.pixel-matcher", "version": "1.0.0" },
  "algorithm": "ed25519",
  "key_id": "nomad-studio-2026",
  "signed_at": "2026-09-14T10:00:00Z",
  "files": {
    "addon/__init__.py": "sha256:9c1e…",
    "addon/service.py": "sha256:41d7…",
    "flows/pixel_matcher.json": "sha256:77b0…",
    "manifest.json": "sha256:3f2a…"
  },
  "signature": "base64:RWQ…"
}
```

- `files` DEBE incluir **todos** los ficheros del ZIP salvo `SIGNATURE.json` y las entradas ignoradas de §2.2 (`__MACOSX/`, `.DS_Store`, `Thumbs.db`, `__pycache__/`). Rutas con `/`, con las mayúsculas exactas.
- `package.id` y `package.version` DEBEN coincidir con el manifest: así una firma no se puede trasplantar a otro paquete o versión.
- `signature` firma el **JSON canónico** del objeto sin la clave `signature`: claves ordenadas, UTF-8, sin espacios (`separators=(",", ":")`), sin escapar caracteres no ASCII. La herramienta `build` y el importador DEBEN usar la misma función de canonicalización.
- Algoritmo de la versión 1: **Ed25519** (firmas de 64 bytes, verificación rápida, sin parámetros que configurar mal).

#### Verificación en el importador

Entre los pasos 3 y 5 de §11.1, sin ejecutar nada del paquete:

1. Si no hay `SIGNATURE.json` → estado de firma `unsigned`. Sigue la instalación.
2. Buscar `key_id` en las **claves de confianza** de la app. Si no está → `unknown_key`.
3. Verificar `signature` sobre el JSON canónico con esa clave pública. Si falla → `invalid`.
4. Comprobar que `package` coincide con el manifest. Si no → `invalid`.
5. Recalcular el hash de cada fichero del ZIP y compararlo con `files`. Cualquier diferencia, **fichero de más** (p. ej. un `.py` añadido) o fichero de menos → `invalid`.
6. Si la clave está revocada (lista de revocación de la app) → `revoked`.
7. Todo correcto → `verified`.

**Oficial o no oficial.** Cualquier persona puede crear un pack, y no hay un sistema de claves de otros autores: un paquete **es oficial** (firmado con una clave de Nomad Studio) **o no lo es**, y en ese caso el usuario decide si confía en quien se lo dio. `unsigned` y `unknown_key` se tratan igual.

| Estado | Qué ve el usuario en el resumen (paso 7 de §11.1) | ¿Instala? |
|---|---|---|
| `verified` | **✓ Oficial · Nomad Studio** | Sí |
| `unsigned` / `unknown_key`, solo datos | *"Este paquete no es oficial. Instálalo solo si confías en quien te lo ha dado."* | Sí, con el botón de instalar normal |
| `unsigned` / `unknown_key`, con código (§9.6, §9.8) | *"Este paquete no es oficial y ejecuta código en tu equipo. Instálalo solo si confías plenamente en quien te lo ha dado."* + permisos declarados | Sí, con confirmación explícita (casilla "Confío en la fuente") |
| `invalid` | **"Este paquete dice estar firmado pero ha sido modificado."** Lista de ficheros que no cuadran | Solo con confirmación explícita; queda marcado como modificado y nunca como oficial |
| `revoked` | "La clave con la que se firmó ya no es válida" | Solo con confirmación explícita |

**Suplantación.** Si el paquete no es `verified` pero su manifest declara como autor a Nomad Studio (`author.name` coincide, sin distinguir mayúsculas ni espacios, con un nombre oficial de `trusted_keys.json`) o su `id` empieza por un prefijo reservado (`nomad.`), el resumen DEBE mostrar además: *"Dice ser de Nomad Studio, pero no está firmado por Nomad Studio."*. El importador DEBE rechazar un `id` con prefijo reservado que no esté firmado.

**Después de instalar.** En el hub y en la lista de paquetes solo se marca lo oficial (✓). Los paquetes no oficiales no llevan ninguna etiqueta de alarma: el aviso es para el momento de decidir. En la ficha del paquete (lista de paquetes) se indica "No oficial" y el autor declarado, con la nota "declarado por el paquete".

Todos estos textos están en los 4 idiomas de la app.

El índice guarda por paquete `signature: { "status": "verified", "key_id": "nomad-studio-2026" }`. Un paquete `invalid` o `revoked` NUNCA muestra la marca oficial, ni en el importador ni en el hub ni en la lista de paquetes.

Tras instalar, la firma no se vuelve a comprobar en cada arranque. El reescaneo (§12.4) sí la recalcula y marca `invalid` si alguien modificó los ficheros instalados.

#### Obligatoriedad

- **Opcional** para cualquier paquete. Sin firma se instala igual (D2).
- **Obligatoria para los packs oficiales que traigan código** (`contributes.addon` o `contributes.step_types`) desde el primero que se publique. La herramienta `build` en modo oficial DEBE negarse a generar un paquete así sin firmar.
- Los packs oficiales solo de datos DEBERÍAN firmarse también, para que muestren la marca.

#### Claves

- **Clave privada**: la tiene solo el autor. NUNCA en el repo, en el ZIP, en capturas ni en logs. Guardada fuera del equipo de trabajo con copia de seguridad cifrada. Si se firma en GitHub Actions, como *secret* del repo, y el log del build no DEBE imprimirla.
- **Claves de confianza**: las claves públicas oficiales van dentro de la app (`app/security/trusted_keys.json`), con `key_id`, clave y fecha, junto con los nombres de autor oficiales (`"Nomad Studio"`) y los prefijos de `id` reservados (`nomad.`) que se usan para detectar suplantación. Cambiarlas requiere una versión nueva de la app.
- **Rotación**: se PUEDEN tener varias claves activas a la vez. Una clave nueva entra en una versión de la app antes de empezar a usarse.
- **Revocación**: si una clave se filtra, se añade a la lista de revocación de la app en la siguiente versión. Los paquetes firmados con ella pasan a `revoked`.
- **Pérdida**: si se pierde la clave privada no se pueden firmar versiones nuevas con ella; se genera otra y se distribuye con una versión de la app.

#### Implementación

- Verificación con la librería `cryptography` (Ed25519). DEBE añadirse a la base de la app (nivel 1, §9.5) con versión exacta cuando se implemente.
- La herramienta `build --sign <ruta a la clave>` calcula los hashes, genera `SIGNATURE.json` y lo verifica con el mismo código del importador antes de cerrar el ZIP.

---

## 12. Índice

### 12.1 Ubicación: la carpeta de datos

`<data>` es la carpeta con todo lo que pertenece al usuario y no al programa: paquetes instalados e índice, perfiles, Sessions, Depots, Build, ajustes y motores. Las imágenes generadas siguen en la carpeta de salida elegida en Ajustes.

**Por defecto, junto al programa en carpetas hermanas** (D9). La versión portable se distribuye así:

```
D:\NomadStudio\                  ← <raíz>: la carpeta que el usuario descomprime
├── app/                         ← el programa: código, Python incluido, requisitos
│   ├── portable.json            ← marca de versión portable (versión, plataforma)
│   └── …
├── data/                        ← <data>: los datos del usuario
├── data-location.json           ← opcional: puntero a otra carpeta de datos
└── NomadStudio.bat / .command / .sh   ← lanzador
```

- **`app/` se reemplaza entera** al actualizar la app. Nada de lo que hay dentro es del usuario.
- **`data/` nunca la toca una actualización**: al ser hermana y no hija de `app/`, reemplazar `app/` no puede llevársela por delante.
- **El lanzador y `data-location.json` están en la raíz**, fuera de `app/`, por la misma razón.
- Todo es visible, se copia o se mueve de disco moviendo `NomadStudio/`, y es el modelo que ya conocen los usuarios de ComfyUI portable. Nunca se usa AppData ni carpetas ocultas.

**Cómo se resuelve al arrancar**, en este orden:

1. Variable de entorno `NOMAD_DATA_DIR`, si existe.
2. Fichero puntero `<raíz>/data-location.json` (`{"path": "E:/MisDatos/Nomad"}`), si existe.
3. Fichero puntero `~/NomadStudio/data-location.json`, si existe (caso de programa no escribible, abajo).
4. `<raíz>/data/`, si la raíz se puede escribir. **Es el caso normal.**
5. Si no se puede escribir (macOS en `/Applications`, Linux en `/opt`, o Windows instalado desde Microsoft Store, ver `APP_UPDATES.md` §12): la app NO DEBE fallar. Pregunta dónde guardar los datos proponiendo `~/NomadStudio` (visible en el perfil del usuario) y guarda la elección en el puntero del paso 3.

`<raíz>` es la carpeta padre de `app/` cuando existe `app/portable.json`. **En desarrollo** (una copia del repo, sin `portable.json`), `<raíz>` es la carpeta del repo y `<data>` es `<repo>/data/`, fuera de git.

Si la ruta resuelta no existe se crea. Si existe pero no se puede escribir, la app arranca en modo solo lectura con un aviso que explica qué carpeta falla y cómo cambiarla.

**Elegir otra carpeta** (opción, como el vault de Obsidian):
- En el primer arranque se muestra la carpeta propuesta con un botón "Cambiar".
- En Ajustes › Datos › "Mover carpeta de datos": copia todo a la nueva ruta, verifica la copia, escribe el puntero y pide reiniciar. La carpeta antigua no se borra hasta que el usuario lo confirma tras el reinicio.

**Reglas:**
- `.staging/` y `.previous/` van dentro de `<data>/packages/`, nunca en `%TEMP%` ni `/tmp`: así el renombrado final es atómico y no depende de que `/tmp` permita ejecutar.
- La app DEBERÍA avisar si detecta que se ejecuta como administrador o root al crear `<data>`: la carpeta quedaría a nombre del administrador y después no se podría escribir como usuario normal.
- En Windows, rutas cortas dentro de `<data>` (sin versión en la carpeta del paquete) para no superar los 260 caracteres al instalar wheels. El importador DEBE comprobar la longitud de las rutas extraídas.
- `data/` y `data-location.json` van en `.gitignore`. Una instalación nueva trae el índice vacío.

```
<data>/packages/
├── index.json
├── index.json.bak          ← última versión buena
├── .staging/
├── .previous/
├── nomad.portrait-fix/
│   ├── manifest.json
│   ├── flows/ workflows/ i18n/ assets/ …
│   └── site-packages/      ← solo si hay wheels
└── …
```

### 12.2 Esquema

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-13T20:00:00Z",
  "packages": {
    "nomad.portrait-fix": {
      "version": "1.0.0",
      "installed_at": "2026-09-13T19:58:00Z",
      "state": "active",
      "state_detail": null,
      "default_lang": "en",
      "languages": ["en", "es", "zh", "ko"],
      "translation_status": { "zh": "complete", "ko": { "partial": 3 } },
      "platforms": null,
      "has_code": false,
      "step_types": [],
      "info_url": "<PACKS_BASE_URL>/packs/nomad.portrait-fix/",
      "store_url": null,
      "signature": { "status": "verified", "key_id": "nomad-studio-2026" },
      "group": { "id": "portrait-fix", "label": { "en": "Portrait Fix" }, "order": 40 },
      "flows": ["refine.pf_remove_skin_glare"],
      "provides": [],
      "requires_missing": []
    }
  },
  "flows": {
    "refine.pf_remove_skin_glare": {
      "package": "nomad.portrait-fix",
      "category": "refine",
      "slug": "pf-remove-skin-glare",
      "file": "nomad.portrait-fix/flows/pf_remove_skin_glare.json",
      "state": "active",
      "status": "active",
      "complexity": 1,
      "group": "portrait-fix",
      "card": { "label": { "en": "…" }, "desc": { "en": "…" }, "tags": ["skin"],
                "style": "icon", "icon": "/packages/nomad.portrait-fix/assets/icon.svg",
                "accent": "#6b8cff", "cover": null, "cover_position": "top" }
    }
  },
  "tags": { "hanbok": { "label": { "ko": "한복" }, "icon": "shirt", "package": "kim.hanbok-looks" } },
  "capabilities": { "edge-defringe": "nomad.edge-defringe" },
  "engines": { "nomad.engine.krea2-turbo": { "category": "image", "state": "active" } }
}
```

### 12.3 Reglas

- Solo lo escriben el importador, el desinstalador, activar/desactivar y el reescaneo.
- **Escritura atómica**: fichero temporal en la misma carpeta, `fsync` y renombrado. Antes de sustituir, la versión vigente se copia a `index.json.bak`.
- **Al arrancar**: si `index.json` no se puede leer, se usa `index.json.bak`; si tampoco, se reconstruye (§12.4). Si la reconstrucción falla, la app arranca vacía con un aviso. Nunca bloquea.
- **El hub y las rutas solo leen el índice.** Abrir un flow lee su fichero del paquete; si falla, falla ese flow con un error visible.

### 12.4 Reescaneo

Se lanza a mano (Ajustes › Paquetes › Rescan) o para recuperar un índice perdido. Nunca en cada carga.

- Recorre `packages/*/manifest.json`, cada paquete por separado.
- Límites por fichero: tamaño y tiempo de lectura.
- **No ejecuta código de addons**; conserva el estado activado/desactivado del índice anterior si existe, y si no, los deja desactivados.
- El paquete que falle queda `broken` con su error.

---

## 13. Actualizar, desactivar y desinstalar

### 13.1 Qué operación es

Los packs de pago no tienen nada especial: se compran en Ko-fi, se descarga el ZIP y se importa como cualquier otro. No hay licencias, claves ni comprobación de compra. Actualizar un pack es importar el ZIP de la versión nueva.

El importador compara `id` y `version` del ZIP con el índice (orden SemVer) y DEBE presentar la operación correcta:

| Caso | Título del resumen | Acciones |
|---|---|---|
| `id` no instalado | **Instalar** *Portrait Fix 1.0.0* | Instalar · Cancelar |
| Versión mayor | **Actualizar** *Portrait Fix 1.0.0 → 1.2.0* + cambios (`changelog`) de las versiones intermedias | Actualizar · Cancelar |
| Misma versión | *Portrait Fix 1.2.0 ya está instalado* | Reinstalar (repara ficheros) · Cancelar |
| Versión menor | **Volver a una versión anterior** *Portrait Fix 1.2.0 → 1.0.0*, con aviso | Solo con confirmación explícita · Cancelar |

Si el paquete instalado está `broken` o `invalid`, el título lo dice ("Reparar Portrait Fix") y la misma versión se trata como reinstalación recomendada.

En una actualización, el resumen DEBE avisar además de:
- flows que desaparecen respecto a la versión instalada (las Sessions que los usen mostrarán "flow no instalado");
- requisitos nuevos, código nuevo (si la versión anterior no traía addon) o permisos nuevos;
- cambio de estado de firma (p. ej. la instalada era `verified` y la nueva `unsigned`).

### 13.2 Progreso y resultado

Instalar puede tardar (wheels, descargas de nivel 3, muchas imágenes). El importador DEBE mostrar el paso en curso, con textos traducidos: *Comprobando paquete · Verificando firma · Resolviendo requisitos · Instalando dependencias · Copiando imágenes · Registrando · Listo*. Si un paso falla, se muestra cuál y por qué, y la instalación queda como estaba (§11.1).

Al terminar, un resumen: *Portrait Fix 1.2.0 actualizado · 13 flows en Refine › Portrait Fix* (y qué queda pendiente, si algo), con un botón para ir a esos flows.

### 13.3 Actualizar, desactivar y desinstalar

- **Actualizar**: importar un ZIP con el mismo `id` y otra `version` (§13.1). Mismo proceso (§11.1). La versión anterior queda en `.previous/` hasta la siguiente actualización, y desde la lista de paquetes se puede volver a ella.
- **Desactivar**: el paquete sigue instalado; sus flows desaparecen del hub y sus rutas dejan de responder.
- **Desinstalar**: si otro paquete lo requiere, avisar y nombrarlo. Desactivar, borrar `packages/<id>/` y sus assets públicos, actualizar el índice.
- **Nunca se borran datos del usuario**: imágenes generadas, historial, Sessions y Album quedan intactos, aunque referencien un flow desinstalado (§13.4).

### 13.4 Sessions y Album con flows que no están instalados

El caso típico: alguien comparte una Session hecha con un pack que el receptor no tiene. También cubre desinstalar un pack propio.

#### Qué guarda una Session

Hoy cada paso de una Session guarda solo `flowCategory` y `flowLabel` (el nombre visible), sin id de flow ni pack. No basta. Cada paso DEBE guardar, en el momento de usarlo:

```json
"flow": {
  "id": "refine.pf_remove_skin_glare",
  "label": { "en": "Remove Skin Glare", "es": "Quitar brillos de la piel" },
  "package": {
    "id": "nomad.portrait-fix",
    "version": "1.2.0",
    "name": { "en": "Portrait Fix", "es": "Retoque de retrato" },
    "info_url": "<PACKS_BASE_URL>/packs/nomad.portrait-fix/",
    "store_url": null
  }
}
```

La información viaja dentro de la Session exportada (`session.json` del ZIP de export): quien la recibe sabe qué le falta sin internet. Las imágenes de Album que vienen de una Session llevan la misma referencia.

#### Al abrir una Session o importarla

Si uno o varios flows no están instalados, la app muestra **un modal** que agrupa por pack (no uno por paso):

> **Esta Session usa packs que no tienes**
> [portada] **Portrait Fix** · hecho con la versión 1.2.0 · **Enlace oficial ✓**
> Lo necesitan 3 pasos: Remove Skin Glare, Dark Circles, Open Eyes
> **[ Ver pack ]** **[ Ya lo tengo: importar ZIP ]**
>
> **[ Abrir sin ellos ]**

- **Ver pack**: abre `info_url` en el navegador (la ficha, con su botón de Ko-fi).
- **Importar ZIP**: abre el importador (§11) y, al terminar, vuelve a la Session ya funcionando.
- **Abrir sin ellos**: la Session se abre y todas las imágenes se ven (son ficheros). Solo quedan desactivadas, con una etiqueta "Necesita Portrait Fix", las acciones que dependen del flow: regenerar, reutilizar parámetros, abrir en el flow, enviar a ese flow.
- La portada del modal se toma del pack instalado si lo hubo; si no, del catálogo (§13.5) si hay red; si no, sin portada.
- Todos los textos del modal están en los 4 idiomas de la app; los nombres de pack y flow siguen el orden de §7.1.

#### Enlace oficial o no verificado

Una Session compartida es un fichero de otra persona: podría traer un enlace a una web falsa con nombre de pack oficial. Por eso:

- La app lleva una lista de **prefijos de confianza** (`app/security/trusted_urls.json`): la base del repo Nomad Studio Packs y la página oficial de Ko-fi.
- Si `info_url` (o `store_url`) empieza por un prefijo de confianza → botón **"Ver pack"** con **"Enlace oficial ✓"**.
- Si no → se muestra el **dominio** bien visible y *"Enlace incluido en la Session, no verificado"*. El botón pide confirmación antes de abrir.
- Si hay red y el catálogo de Nomad Studio Packs (§13.5) tiene ese `package.id`, se usa el enlace del catálogo antes que el de la Session.
- Solo se aceptan enlaces `https://`. Nunca se abre un enlace automáticamente.

#### Otros casos

| Caso | Qué ve el usuario |
|---|---|
| Pack instalado en versión **anterior** a la de la Session | Aviso suave en la Session: *"Hecho con Portrait Fix 1.2.0; tienes la 1.0.0. Algunos pasos pueden no coincidir."* + Ver pack |
| El flow ya **no existe** en la versión instalada (se quitó en una actualización) | El modal, indicando *"Este flow no está en tu versión de Portrait Fix"* |
| Pack **desinstalado** por el propio usuario | El modal, con un botón **Reinstalar** si la versión anterior sigue en `.previous/` |
| **Album**: reutilizar parámetros o abrir en el flow una imagen de un pack que no está | El mismo modal, para ese pack. La imagen se ve siempre |
| Session **antigua** (solo `flowLabel`) | Al migrar, se busca el flow por categoría y nombre en los packs instalados. Si no aparece: paso marcado "flow desconocido", sin enlace |

### 13.5 Ficha del pack en Nomad Studio Packs

Repo público **Nomad Studio Packs**, publicado con GitHub Pages en `<PACKS_BASE_URL>`. Solo información: los ZIP de pago están en Ko-fi.

```
NomadStudioPacks/
├── packs/
│   └── nomad.portrait-fix/
│       ├── pack.json        ← ficha: datos para la app y la web
│       ├── index.html       ← página pública (generada desde pack.json)
│       ├── cover.webp
│       └── screenshots/
├── catalog.json             ← todas las fichas, generado
└── trusted_keys.json        ← claves públicas oficiales (§11.4), para consulta
```

`pack.json`:

```json
{
  "id": "nomad.portrait-fix",
  "name": { "en": "Portrait Fix", "es": "Retoque de retrato" },
  "summary": { "en": "13 one-click portrait repairs." },
  "latest_version": "1.2.0",
  "price": "paid",
  "store_url": "https://ko-fi.com/s/…",
  "cover": "cover.webp",
  "category": "refine",
  "flows": ["refine.pf_remove_skin_glare", "refine.pf_dark_circles"],
  "languages": ["en", "es", "zh", "ko"],
  "has_code": false,
  "platforms": null
}
```

Reglas:
- La URL de la ficha (`<PACKS_BASE_URL>/packs/<id>/`) NO DEBE cambiar nunca: está guardada en packs y Sessions ya distribuidos. Un pack retirado conserva su ficha con el aviso de retirado.
- `store_url` SÍ puede cambiar: se actualiza la ficha y todos los enlaces siguen funcionando.
- Una GitHub Action del repo valida cada cambio: JSON correcto, `id` igual al nombre de la carpeta, portada presente, `store_url` con `https://`, y regenera `catalog.json` e `index.html`.
- La herramienta `build` en modo oficial rellena `info_url` a partir de `<PACKS_BASE_URL>` y el id, y avisa si la ficha todavía no existe.
- `<PACKS_BASE_URL>` se fija cuando se cree el repo; hasta entonces es un marcador en este documento y en `trusted_urls.json`.

---

## 14. Preguntas abiertas

1. ~~Ubicación de `<data>`~~ → **cerrada** (D9, §12.1): junto al programa por defecto, carpeta elegible como opción.
2. ~~Dependencias de Python~~ → **cerrada** (D10, §9.5): tres niveles. Y D11 (§9.7): modelos de IA solo por ComfyUI.
3. ~~Firmas~~ → **cerrada** (D12, §11.4): firma dentro del ZIP, obligatoria en packs oficiales con código. No hay claves de otros autores: un paquete es oficial o no lo es, y si no lo es el importador avisa de que solo se instale si se confía en la fuente.
4. ~~Repositorio remoto~~ → **decidido, fuera de la versión 1**: los packs NO se autoactualizan. Habrá un repo público **Nomad Studio Packs** solo con información (catálogo, portadas, fichas y enlace de Ko-fi) para una pestaña "Descubrir". Lo que se actualiza automáticamente es la app, desde las Releases del repo `NomadStudio` cuando sea público (documento aparte).
5. ~~Paquetes de pago~~ → **cerrada** (§13.1): el ZIP de pago se descarga de Ko-fi y se importa como cualquier otro, sin licencias ni claves.
6. ~~Tipos de paso~~ → **cerrada** (D13, §9.8): los paquetes pueden aportar bloques con JS y CSS en la versión 1. Queda para más adelante aislarlos en iframe.
7. ~~Sessions y Album~~ → **cerrada** (D14, §13.4, §13.5): la Session guarda pack y `info_url`; modal con enlace oficial a la ficha en Nomad Studio Packs.

---

## 15. Migración del catálogo actual

### 15.1 Plan

1. **Implementar** importador, índice y lectura del hub desde el índice, manteniendo temporalmente la lectura antigua detrás de un ajuste.
2. **Convertir uno de cada tipo** como prueba: Simple (C), Remove Skin Glare (A), Qwen 2511 Relight (B), Edge Defringe (D sin flow), Pixel Matcher (D con flow), Cinematic (template pack), WANDER (preset), Canvas Composer (F), Krea 2 Turbo (motor).
3. **Herramienta `build`**: genera un ZIP por paquete a partir del repo actual y lo valida con el mismo código del importador.
4. **Convertir todo** y agrupar en paquetes: un paquete por grupo actual (Core Create, Layout, Core Refine, Photo Editing, Portrait Fix, Creator Pack, Upscale, Look Book, Presets, Core Mix), uno por addon, uno por template pack y uno por motor.
5. **Sacar los datos del usuario del código**: mover `app/data/viewers.json`, `sessions.json`, `depots.json`, `library_flows.json` y los ajustes y motores de `app/workflows/import_registry.json` a `<data>/` (§12.1), dejarlos fuera de git y migrar automáticamente en el primer arranque de una instalación existente. En la misma migración, los pasos de Sessions que solo tienen `flowCategory`/`flowLabel` pasan al formato de §13.4.
6. **Vaciar la app**: retirar `app/instructions/index.json`, los flows de `app/instructions/flows`, los workflows con `flow_data` de `app/workflows`, `addons/` y `data/template_packs.json` del arranque. La instalación de desarrollo instala todos los paquetes generados.
7. **Quitar el acoplamiento**: `switch` de `flow-render-all.js` convertido en registro de tipos (§9.8), con `layer_compositor` y su gancho `window._ncfLcRefresh` movidos al paquete de Layer Composer; ramas de icono por action en `nomad_studio.html`, reglas `cs-card--<flow>`, `TAG_ICONS` (pasa al diccionario común), `_GROUP_LABELS`, Canvas Composer añadido en `_load_mix_flows`, las 19 rutas y los 16 `if` de clic duplicados, y las entradas de flows en `flow.flowLabels` de los JSON de idioma de la app (pasan al `i18n/` de cada paquete).
8. **Estado vacío del hub**: cada sección sin flows explica que no hay nada instalado y lleva al importador.

### 15.2 Correspondencia de campos

| Hoy | En el paquete |
|---|---|
| `index.json` → `file`, `status`, `llm_required`… | Desaparece; lo genera el índice |
| `label` | `card.label[default_lang]` |
| `card_desc` | `card.desc[default_lang]` |
| `card_tags` (texto) | `card.tags` (ids) |
| `card_css_modifier` | `card.accent` + `card.icon` |
| `group` (string) | `group` del manifest |
| `workflow_file: "workflows/refine/x.json"` | `workflow_file: "workflows/x.json"` (relativo al paquete) |
| nodo `flow_data` | flow normal (§5.3) |
| `addons/<x>/__init__.py` con `ADDON_INFO` | `addon/__init__.py` + `contributes.addon`; `register(ctx)` |
| `addons/<x>/flow.json` | `flows/<x>.json` |
| `/api/models/pixel-match/process` | `/api/addons/nomad.pixel-matcher/process` |
| entrada de `import_registry.json` → `imports[]` | paquete de motor (§8.1) |
| `data/template_packs.json` (global) | `data/template_packs.json` por paquete |
| `preset_meta.cover_image` | relativo al paquete |
| `es.json` → `flow.flowLabels["Remove Background"]` | `card.label.es` / `i18n/es.json` |
