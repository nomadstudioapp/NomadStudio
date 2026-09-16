# Asistente de primer arranque y formato de imagen

> Especificación v0.1 (borrador) · 2026-09-14
>
> Qué ve el usuario la primera vez que abre Nomad Studio, y cómo se elige y aplica el formato en que se guardan las imágenes (WebP o PNG), con la explicación de la pérdida de calidad.
>
> Relacionado: [`PACKAGE_FORMAT.md`](PACKAGE_FORMAT.md) (carpeta de datos §12.1, flows §5) y [`APP_UPDATES.md`](APP_UPDATES.md).
>
> **DEBE**, **NO DEBE**, **DEBERÍA** y **PUEDE** tienen sentido normativo.

---

## 0. Decisiones

| # | Decisión |
|---|---|
| W1 | La primera vez que se abre la app aparece un **asistente de configuración** paso a paso. Sustituye al aviso actual "Setup required" de `app/static/js/services/nav_status.js`, que solo manda a Ajustes. |
| W2 | El usuario elige el **formato de imagen**: **PNG** (primero y por defecto) o **WebP** para ahorrar espacio, con la explicación de la pérdida. |
| W3 | La conversión la hace **Nomad Studio al guardar** (`image_service.save_image`), **no** el nodo de salida de ComfyUI. Los workflows no se tocan. |
| W4 | Cada flow PUEDE cambiar el formato en **Avanzado** para esa generación. Un flow PUEDE declarar un formato recomendado (p. ej. pixel art → PNG). |
| W5 | Los metadatos que hoy van dentro del PNG (prompt, parámetros, etiquetas, favorito, diamante) DEBEN guardarse también dentro del WebP. Sin esto no se ofrece WebP. |
| W6 | Todo lo del asistente se puede cambiar después en Ajustes, y el asistente se puede volver a lanzar. |
| W7 | Todos los textos del asistente en los 4 idiomas (EN/ES/ZH/KO). |
| W8 | **Ahorro de espacio, desactivado por defecto**: si se activa, ComfyUI no guarda su copia en `output/` (cambio dinámico `SaveImage` → `PreviewImage` al enviar), porque Nomad Studio ya guarda cada imagen en la carpeta de cada usuario. Desactivado por defecto por el riesgo de §3.3. Opción en el asistente y en Ajustes › Avanzado (§3.3). |
| W9 | **Lo primero, después del idioma, es comprobar ComfyUI y LM Studio**, y a continuación **detectar qué ficheros de modelo tiene el usuario** para saber cuáles de los 7 motores ya puede usar. Lo que falte se instala con el sistema de descargas que ya existe (§4). |
| W10 | La detección de modelos usa **la API de ComfyUI** (`GET /models/{carpeta}`), no la ruta de la carpeta: funciona con carpetas extra de ComfyUI y con ComfyUI en otro equipo. La ruta de la carpeta de modelos solo hace falta para **descargar**. |

---

## 1. El asistente

### 1.1 Cuándo aparece

- Si `data/settings` no tiene `setupCompleted: true`.
- Antes que la pantalla de perfiles ("¿Quién genera?"), porque uno de sus pasos crea el primer perfil.
- Se PUEDE relanzar desde **Ajustes › General › Volver a ejecutar el asistente**. Al relanzarlo, cada paso muestra el valor actual.
- En una **actualización** de la app no vuelve a aparecer. Si una versión añade un paso nuevo obligatorio, se muestra solo ese paso.

### 1.2 Pasos

Orden: primero el idioma (para leer el resto), **después ComfyUI y sus motores, luego LM Studio y sus modelos**, y al final las carpetas, el formato y el perfil.

| # | Paso | Obligatorio | Qué hace |
|---|---|---|---|
| 1 | **Idioma** | Sí | Elige EN/ES/ZH/KO. Primero, para que el resto del asistente salga ya en ese idioma. Propone el del sistema si es uno de los 4. |
| 2 | **ComfyUI** | No* | Comprobación **automática** al entrar (`system_stats`: responde, versión, GPU y memoria de vídeo) de la dirección guardada (por defecto `http://127.0.0.1:8188`). Si no responde, **busca sola** en este equipo y en la red local (§1.4) y presenta lo encontrado como una lista donde elegir; si solo aparece un servidor, lo usa directamente. Escribir la dirección a mano es una opción ("Escribir otra dirección"), y la ayuda de "¿está en otro equipo?" va plegada. *Sin ComfyUI no se puede generar: se avisa claramente, pero no bloquea. |
| 3 | **Motores** | No | **Detecta qué ficheros de modelo tiene ComfyUI** y muestra el estado de cada uno de los 7 motores (listo / le falta algo / no instalado). Ofrece instalar lo que falte (§4). Solo si ComfyUI respondió en el paso 2. |
| 4 | **LM Studio** | No | La misma vista que el paso 2 (`serverStep` en `setup.js`), con el puerto 1234. Indica que solo lo necesitan algunos flows (asistencia de prompts, visión). |
| 5 | **Modelos** | No | Los **4 modelos de lenguaje recomendados** (la misma lista medida de la web, página Engines): Qwythos 9B, Ornith 1.5 9B, Gemma 4 12B QAT y Ministral 3 14B Reasoning. Ninguno es obligatorio; se recomienda tener al menos uno (Gemma 4 12B QAT, o Qwythos 9B en tarjetas de menos de 12 GB). Detecta cuáles tiene LM Studio (`GET /api/v1/models`), instala los que falten con la API de descargas de LM Studio (`POST /api/v1/models/download` + estado), y deja elegir cuál escribe prompts y cuál describe imágenes. Si no hay ninguno elegido, usa el primero instalado. Lista en `app/static/data/recommended_llm_models.json`. |
| 6 | **Carpeta de datos** | Sí | Muestra dónde viven los datos: `~/Nomad Studio/data` en la versión portable y `<repo>/data` en una copia de desarrollo (`app/paths.py`). Explica que, al estar fuera del programa, se puede borrar o sustituir Nomad Studio sin perder nada. |
| 7 | **Carpeta de imágenes** | Sí | Dónde se guardan las imágenes generadas. Comprueba que existe y se puede escribir (misma prueba que hoy en Ajustes). Avisa si está dentro de una carpeta sincronizada (OneDrive, Dropbox, iCloud) o protegida contra ransomware en Windows. |
| 8 | **Formato de imagen** | Sí | WebP o PNG (§2), más la **opción de ahorro de espacio** "no guardar copia en la carpeta de ComfyUI", desactivada por defecto (§3.3): estaba en el paso 2 y se movió aquí, el paso que trata de cómo se guardan las imágenes. |
| 9 | **Primer perfil** | Sí | Nombre, avatar y PIN opcional (mismo formulario que "Añadir perfil"). |
| 10 | **Listo** | — | Resumen: servicios, motores, modelos, carpetas, formato. Botón **Empezar**. Si hay descargas en curso (§4.5), siguen en segundo plano y se ve su progreso. |

### 1.5 Si el usuario no tiene ComfyUI ni LM Studio

El asistente daba por hecho que existían en algún sitio y solo estaban apagados. Para alguien que empieza de cero (`app/services/local_apps.py`, `GET /api/setup/local-apps`):

1. **Instalado pero sin arrancar**: se busca en las rutas habituales (portable, app de escritorio de ComfyUI, LM Studio en programas del usuario) y se ofrece **arrancarlo**. Si hay varias instalaciones manda la **portable** (`_COMFY_PREFERENCE`): es la que ComfyUI publica para esto, su carpeta de modelos es un directorio normal al que apuntar y admite `--listen` para servir en la red. Si solo está la de escritorio se ofrece arrancarla igual, y además instalar la portable. Con la portable sale una casilla, **"que otros equipos de mi red puedan usarlo"**: marcada, se arranca su Python propio (`python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 0.0.0.0`) en vez del `.bat`, que no reenvía argumentos. La primera vez Windows pregunta por el cortafuegos. La app de escritorio tiene eso en sus propios ajustes. Con LM Studio se usa su propio `lms server start` si está, que levanta el servidor sin abrir la ventana. Después se reintenta la comprobación sola, hasta 20 veces cada 4 s, porque ComfyUI tarda en arrancar.
2. **No instalado**: se ofrece **instalar ComfyUI** descargando el portable oficial de su repo (unos 2 GB, se elige el build según la tarjeta detectada) y descomprimiéndolo con el `tar.exe` que trae Windows (bsdtar lee 7z; sin dependencias nuevas). Antes se comprueba el espacio libre. LM Studio es un instalador con ventana propia: solo se enlaza su página de descarga.
3. **Sin tarjeta adecuada**: se lee la GPU del equipo sin ayuda de ComfyUI y, si no hay NVIDIA ni AMD, se avisa antes de que alguien descargue 2 GB para nada.

Arrancar e instalar solo desde el propio equipo (`local_only`): desde el navegador de otro PC no aparecen esos botones.

### 1.4 Buscar servidores en la red

`POST /api/setup/discover` (`setup_service.discover_services`) prueba los puertos de ComfyUI (8188, 8000) y LM Studio (1234) en `127.0.0.1` y en las /24 privadas de este equipo, y confirma con su propia API lo que responde. Solo redes privadas; no guarda nada.

Va en **dos rondas**: la primera espera 0,4 s por dirección y la segunda reintenta solo lo que no contestó, con 1,2 s. La segunda ronda existe porque por wifi la primera conexión a una IP que todavía no está en la caché ARP tarda más que el tiempo de espera corto: sin ella la primera búsqueda no encontraba nada y la segunda sí (visto en el portátil, 2026-09-16).

### 1.3 Comportamiento

- Botones **Atrás**, **Siguiente** y, en pasos opcionales, **Saltar**.
- Lo elegido se guarda **al pulsar Siguiente** en cada paso, no solo al final: si se cierra la app a mitad, al volver continúa donde se quedó.
- `setupCompleted: true` se escribe al pulsar **Empezar**.
- Un fallo de comprobación (ComfyUI apagado) NUNCA bloquea el asistente: se informa y se deja seguir.
- Diseño según la guía de estilos de Nomad Studio (`docs/NOMAD_UI_GUIDE.md`) y en todos los temas.

---

## 2. Formato de imagen

### 2.1 Cifras reales

Medidas el 2026-09-14 con las 30 últimas imágenes generadas (tamaños de 192×108 a 768×1344; 3 con transparencia), convirtiendo en memoria:

| Formato | Tamaño medio | 30 imágenes | Ahorro frente a PNG |
|---|---|---|---|
| PNG (actual) | 1,92 MB | 57,7 MB | — |
| **WebP calidad 95** | 0,32 MB | 9,7 MB | **83 %** |
| WebP calidad 90 | 0,21 MB | 6,4 MB | 89 % |
| WebP sin pérdida | 1,42 MB | 42,5 MB | 26 % |

Referencia: 1.000 imágenes pasan de unos 1,9 GB en PNG a unos 320 MB en WebP calidad 95.

### 2.2 Qué es la pérdida

PNG guarda **cada píxel exactamente**. WebP con calidad ajustable (con pérdida) consigue ocupar mucho menos **descartando información que el ojo apenas percibe**. No es un recorte ni un cambio de resolución: la imagen mantiene sus dimensiones.

**Qué se descarta primero**, por orden de lo que antes se nota:
- **Degradados muy suaves** (cielos, fondos lisos, viñetas): pueden aparecer escalones o bandas ligeras (*banding*).
- **Bordes nítidos y detalle fino**: texto y rotulación, líneas finas, pixel art, pelo muy detallado. Pueden verse un poco más blandos o con un leve halo alrededor del borde.
- **Grano y ruido**: la textura de película o de sensor puede suavizarse.
- **Colores muy saturados en zonas pequeñas**: se pueden mezclar ligeramente con los de al lado, porque WebP guarda el color con menos resolución que la luminosidad.

**A calidad 95** estas diferencias son, en la práctica, invisibles a tamaño normal en fotografía, retrato e ilustración. A calidad 90 empiezan a notarse en los casos de la lista anterior si se amplía la imagen.

**La pérdida no se recupera.** Una imagen guardada en WebP con pérdida no vuelve a ser la original aunque después se guarde como PNG.

### 2.3 Pérdida acumulada al refinar

Es el caso que más importa en Nomad Studio. Cuando una imagen WebP se usa como entrada de un flow de Refine (upscale, retoque, cambio de fondo…) y el resultado se guarda otra vez en WebP, **la compresión se aplica de nuevo** sobre una imagen que ya había perdido algo. Una pasada no se nota; **muchas pasadas encadenadas** sobre la misma imagen sí pueden acumular bandas y blandura.

Mitigaciones:
- **Calidad 95 por defecto**, no 90.
- **Formato por flow en Avanzado** (§3.2): para una cadena de retoques importante, se elige PNG en los pasos intermedios.
- **Formato recomendado por flow** (§3.4): los flows donde la pérdida se nota especialmente piden PNG por defecto.
- Nomad Studio envía siempre la entrada a ComfyUI **sin volver a comprimirla** (se decodifica y se manda como PNG), así que la única pérdida por paso es la del guardado final.

### 2.4 Cuándo elegir PNG

- Edición profesional o impresión, donde se quiere el original exacto.
- Imágenes con **texto o rotulación**, **pixel art**, logos o colores planos.
- Recortes con **transparencia** que se van a componer después (WebP admite transparencia, pero los bordes semitransparentes sufren con la pérdida).
- **Upscales muy grandes**: WebP no admite imágenes de más de **16.383 píxeles** de ancho o alto. Por encima de ese tamaño se guarda siempre en PNG (§3.1).
- Cadenas largas de refinado sobre la misma imagen (§2.3).

### 2.5 Texto del paso en el asistente

> **¿Cómo guardamos tus imágenes?**
>
> ◉ **PNG**: guarda cada píxel exactamente, sin ninguna pérdida.
>
> ○ **WebP**: si necesitas ahorrar espacio, usa esta opción.
>
> *(Decisión del usuario, 2026-09-15: PNG primero y marcado por defecto; textos neutros, sin presentar PNG como "ocupa mucho más". La explicación de la pérdida sigue en el desplegable "¿Qué significa pérdida?".)*
>
> *Puedes cambiarlo en Ajustes cuando quieras, y elegir otro formato para una generación concreta en **Avanzado**. Las imágenes ya guardadas no se convierten.*
>
> [ Ver ejemplo ampliado ]

**Ver ejemplo ampliado** muestra la misma zona de una imagen de muestra, ampliada, en PNG y en WebP 95 lado a lado, con el tamaño de cada fichero.

### 2.6 Discord y otras apps

- Discord, navegadores, WhatsApp, Telegram y la mayoría de apps muestran WebP y PNG.
- Una imagen WebP de ~0,3 MB cabe holgadamente en los límites de subida de las cuentas gratuitas; un PNG de 2 MB o más no siempre.
- Algunos programas antiguos de edición no abren WebP. La guía de ayuda DEBE indicarlo.
- **Metadatos al compartir**: ni en PNG ni en WebP se puede garantizar que el prompt y los parámetros sobrevivan al subir la imagen a Discord u otras plataformas, que pueden procesar o recomprimir la imagen. No se DEBE prometer lo contrario.

---

## 3. Implementación

### 3.1 Dónde se convierte

Flujo actual: el workflow termina en `SaveImage` → ComfyUI guarda un PNG en su `output/` → Nomad Studio lo descarga por `/view` → `image_service.save_image()` le incrusta los metadatos (bloques `tEXt` con prefijo `oj:`) y lo guarda en la carpeta de imágenes.

**La conversión se hace en `save_image()`**, el único punto por el que pasan todos los guardados de flows:

1. Recibe los bytes de ComfyUI (PNG, sin pérdida).
2. Resuelve el formato: override del flow en Avanzado (§3.2) → formato recomendado del flow (§3.4) → ajuste global.
3. Si el formato es WebP y la imagen supera 16.383 px en algún lado, **guarda en PNG** y lo registra en el log.
4. WebP: `quality` del ajuste (95 por defecto), `method` 4–6, conservando transparencia. PNG: como hoy.
5. Incrusta los metadatos en el formato correspondiente (§3.5).
6. Extensión del fichero según el formato (`.webp` / `.png`).

**Por qué no en el nodo de salida de ComfyUI:**
- Habría que modificar todos los workflows (de motores y de paquetes) o depender de nodos personalizados de WebP instalados en cada ComfyUI.
- El formato quedaría en manos de cada workflow en lugar de un ajuste de la app.
- Recibir de ComfyUI un PNG sin pérdida y comprimir una sola vez al final da el mejor resultado posible por paso.

Revisar también los guardados que no pasan por `save_image()` (hoy: `refine_routes.py` genera PNG intermedios en memoria para enviar a ComfyUI, que DEBEN seguir en PNG; `backgrounds_routes.py` y `characters_routes.py` guardan imágenes de Build, que quedan fuera de este ajuste en la versión 1).

### 3.2 Formato por flow en Avanzado

- En el panel **Avanzado** de cada flow que genera imágenes: **Formato de salida**: *Predeterminado (WebP 95)* · *WebP* · *PNG*. La etiqueta de "Predeterminado" muestra el ajuste global vigente.
- Se aplica a esa generación y se recuerda por flow (como otros valores de Avanzado), sin cambiar el ajuste global.
- Se envía en la petición de generación y llega a `save_image()`.
- Con WebP, un deslizador de **calidad** (80–100) PUEDE mostrarse en Avanzado; por defecto, el valor global.

### 3.3 Ahorro de espacio: sin copia duplicada en ComfyUI

Hoy cada imagen se guarda **dos veces**: el PNG en `ComfyUI/output/` y la copia de Nomad Studio en su carpeta de imágenes **por usuario**. La de ComfyUI es un duplicado que nadie usa desde Nomad Studio.

**Opción de ahorro**, en el paso de ComfyUI del asistente y en **Ajustes › Avanzado**:

> **Ahorrar espacio: no guardar copia en la carpeta de ComfyUI** ☐ (desactivado por defecto)
> *Nomad Studio ya guarda cada imagen en tu propia carpeta de usuario, así que ComfyUI no necesita guardar otra copia en su carpeta de salida.*
- **Activado**: justo antes de enviar el workflow, Nomad Studio cambia dinámicamente cada nodo `SaveImage` por `PreviewImage`, igual que en las sesiones Vanish. ComfyUI deja la imagen en su carpeta `temp/` y Nomad Studio la descarga igual por `/view`. El workflow guardado (del motor o del paquete) no se modifica: el cambio es solo en la copia que se envía.
- **Desactivado** (por defecto): ComfyUI guarda también su copia en `ComfyUI/output/`, que sirve de respaldo si la descarga falla.
- **Solo con un usuario activo**: sin perfil activo Nomad Studio no guarda la imagen, así que el cambio no se aplica y se conserva la copia de ComfyUI.
- **No afecta** a los workflows que el usuario lance directamente desde la interfaz de ComfyUI.

**Verificado en el código (2026-09-14):**
- Todas las descargas usan el `type` que devuelve ComfyUI en lugar de fijar `output`: `generation_routes.py` (`image_entry.get("type", "output")`), `refine_routes.py`, `upscale_routes.py`, `compose_routes.py`, `mobile_routes.py` (`first.get("type", "output")`) e `images_routes.py` (`img_type`). Por tanto funcionan con `type=temp`.
- Los workflows actuales terminan en el nodo estándar `SaveImage`, y ninguno lee como entrada un fichero de `output/`.

**Implementado (2026-09-15):** un único helper, `models_api_shared._apply_comfy_output_policy(data, workflow)`, que aplica Vanish o el ajuste `skipComfyOutputCopy`. Se llama en los 11 puntos de envío: `generation_routes.py` (generate, submit, prepare-queue, submit-queue), `refine_routes.py` (mix/prepare, refine/prepare, refine/generate), `upscale_routes.py` (prepare, generate), `compose_routes.py` y `mobile_routes.py`. El botón Queue de las tarjetas de prompt (`flow-generation.js` `_generateOneCard`) no guardaba la imagen en la carpeta del usuario; ahora la guarda con `saveFlowImage` como el resto.

**Nodos de guardado distintos:** si un workflow usa otro nodo de salida (p. ej. de un paquete de nodos personalizado), no se cambia y ComfyUI guardará su copia como hasta ahora. El log DEBERÍA indicarlo.

**Riesgo conocido:** ComfyUI vacía `temp/` al arrancar. Si Nomad Studio se cierra entre que ComfyUI termina la imagen y la descarga, y después se reinicia ComfyUI, esa imagen se pierde. La ventana es de segundos; la descarga DEBE reintentarse mientras ComfyUI siga en marcha antes de dar la imagen por perdida.

### 3.4 Formato recomendado por flow

Un flow PUEDE declarar su formato recomendado en su definición (`PACKAGE_FORMAT.md` §5.1):

```json
"output": { "format": "png", "reason": { "en": "Pixel art keeps hard edges only without compression.", "es": "El pixel art solo conserva los bordes nítidos sin compresión." } }
```

- `format`: `png`, `webp` o `any` (por defecto).
- Se usa si el usuario no ha elegido otro formato en Avanzado para ese flow. Avanzado muestra el motivo.
- Candidatos: Pixel Matcher, Remove Background / Chroma Key / Extract Background (transparencia), Layout Lettering y Posters (texto), upscales de gran tamaño.

### 3.5 Metadatos dentro del WebP (requisito previo)

Hoy `image_service.py` guarda en bloques `tEXt` del PNG los metadatos `oj:*` (prompt, parámetros…) y los campos editables del Album (`tags`, `favorite`, `diamond`), y el Album los lee de ahí (`read_png_text_chunks`, `read_sidecar`, `write_sidecar`). Para un fichero que no es PNG, hoy cae al mecanismo antiguo de `.json` al lado de la imagen.

Antes de ofrecer WebP:
- **Escritura**: incrustar los mismos pares `oj:*` en el bloque **XMP** del WebP (Pillow admite `xmp=` al guardar WebP), en un espacio de nombres propio de Nomad Studio.
- **Lectura**: `read_*` y `read_sidecar` DEBEN leer XMP de WebP con el mismo resultado que los `tEXt` de PNG.
- **Edición** de etiquetas/favorito/diamante: reescribir el XMP del WebP sin recomprimir la imagen (solo cambia el bloque de metadatos).
- **Album, "reutilizar parámetros", listados**: DEBEN aceptar `.webp` igual que `.png` (revisar filtros de extensión, p. ej. `list_image_files_sorted`).
- **Prueba de regresión**: guardar, leer, editar etiquetas y reutilizar parámetros con PNG y con WebP deben dar los mismos datos.

### 3.6 Ajustes

| Ajuste | Por defecto | Dónde |
|---|---|---|
| `imageFormat` | `png` | Asistente, paso Formato · Ajustes › Imágenes |
| `webpQuality` | `95` | Ajustes › Imágenes › Avanzado |
| `skipComfyOutputCopy` | `false` (ahorro desactivado) | Asistente, paso ComfyUI · Ajustes › Avanzado (§3.3) |
| `setupCompleted` | `false` | Interno |

Se guardan con el resto de ajustes en la carpeta de datos.

---

## 4. Motores: detectar e instalar modelos

Paso 4 del asistente, y también disponible en **Ajustes › Motores** para volver a comprobar.

### 4.1 Qué necesita cada motor

Cada motor (hoy, cada entrada de `import_registry.json` → `imports`; en la app vacía, cada paquete de motor gratuito, `PACKAGE_FORMAT.md` §8.1) necesita unos ficheros en las carpetas de modelos de ComfyUI. Hay dos fuentes y el asistente DEBE usar **las dos juntas**:

1. **Descargas declaradas** en el nodo de configuración del workflow (`_extract_downloads_from_workflow`, formato `subcarpeta:fichero;uri:URL`): qué ficheros son y de dónde descargarlos.
2. **Ficheros referenciados por los nodos** del workflow (`_extract_model_files`): qué usa realmente el grafo. Detecta ficheros que no están en la lista de descargas.

**Variantes de cuantización**: varios motores declaran varias versiones del mismo modelo (fp8, int8, int4, nvfp4, bf16…). **No hacen falta todas**: basta con una variante del modelo principal más los ficheros comunes (codificador de texto, VAE, LoRAs obligatorias). La detección DEBE agrupar las variantes y dar el motor por listo si hay al menos una.

### 4.2 Detección por la API de ComfyUI

- `GET {comfy}/models` → lista de carpetas; `GET {comfy}/models/{carpeta}` → ficheros de esa carpeta, con subcarpetas (en Windows con `\`).
- Comparación por ruta relativa normalizada (`/`, sin distinguir mayúsculas). Si el fichero está en otra subcarpeta de la misma carpeta, se da por encontrado.
- **Carpetas equivalentes**: ComfyUI trata `clip` y `text_encoders` como la misma; lo mismo `unet` y `diffusion_models`, y `checkpoints`. La detección DEBE aceptar el fichero en cualquiera de sus equivalentes.
- Ventajas frente a mirar el disco: incluye las carpetas extra que ComfyUI tenga configuradas (`extra_model_paths.yaml`), funciona con ComfyUI en otro equipo y no necesita que el usuario indique la ruta.

Estado por motor:

| Estado | Condición |
|---|---|
| **Listo** | Hay al menos una variante del modelo principal y todos los ficheros comunes |
| **Incompleto** | Falta algún fichero; se listan cuáles, con tamaño si se conoce |
| **No instalado** | No hay ninguna variante del modelo principal |
| **Instalación manual** | Faltan ficheros y el motor no declara URL de descarga para ellos |

### 4.3 Recomendar variante según la GPU

`system_stats` devuelve la GPU y su memoria (`devices[].vram_total`). Al instalar un motor no instalado, el asistente PUEDE preseleccionar la variante más adecuada, explicando por qué, y dejar elegir otra. Criterios orientativos, a confirmar con pruebas:
- Mucha memoria: fp8 / bf16.
- Memoria media (~12–16 GB): int8 o fp8 según el modelo.
- Poca memoria: int4.
- **nvfp4** solo en GPUs que lo soporten (arquitectura Blackwell, RTX 50xx); no ofrecerlo en otras.

Ejemplo real (2026-09-14): el equipo de desarrollo tiene una **NVIDIA GeForce RTX 4060 Ti con 16 GB** (ComfyUI 0.32.0).

### 4.4 Instalar

Reutiliza el sistema existente:
- `POST /api/models/imports/download-file` con `force: true`: descarga en streaming a `{carpeta de modelos}/{subcarpeta}/{fichero}` vía `.part` y renombrado, con progreso (`application/x-ndjson`).
- Requiere la **carpeta de modelos de ComfyUI** (`comfyModelsFolder`). Si no está configurada, el asistente la pide en este momento, con **Examinar**, y la **valida contra la API**: los ficheros que ComfyUI lista deben existir en esa ruta. Así se evita descargar a una carpeta que ComfyUI no lee.
- Antes de empezar: tamaño total (cabecera `Content-Length` de cada URL) y comprobación de espacio libre.
- Tras cada descarga, nueva consulta a la API de ComfyUI para confirmar que el fichero aparece.
- Motores con **instalación manual** (sin URL): se muestran los ficheros que faltan y dónde colocarlos, sin botón de descarga.

### 4.5 Descargas largas

- Un motor puede superar los 20 GB. Las descargas siguen **en segundo plano** si el usuario continúa con el asistente o termina.
- Progreso visible en el paso 9 y después en Ajustes › Motores.
- Cancelar borra el `.part`. DEBERÍA poder reanudarse (cabecera `Range`); hoy `download-file` no reanuda.
- Varias descargas se hacen **de una en una** para no saturar la conexión ni el disco.

### 4.6 Problemas encontrados al analizarlo (2026-09-14)

Verificado contra el código y los datos de OPENHIKER. Hay que corregirlos antes de montar este paso:

1. **`GET /api/models/imports/<id>/requirements` da error 500.** `_extract_model_files` se movió a `imports_lora_catalog.py`, pero la constante `_MODEL_FILE_EXTENSIONS` que usa sigue definida en `imports_routes.py` (`NameError`). Confirmado en el servidor en marcha.
2. **Krea 2 Turbo declara mal la subcarpeta de descarga**: `krea2` en lugar de `diffusion_models/krea2`. El sistema de instalación descargaría a `models/krea2/`, donde ComfyUI no busca. Los ficheros del equipo de desarrollo están bien colocados porque se pusieron a mano.
3. **Qwen Image usa una LoRA que no está en sus descargas** (`loras/qwen_2511/Qwen-Image-Lightning-4steps-V2.0-bf16.safetensors`): referenciada por el grafo, pero sin URL. Por eso la detección debe combinar las dos fuentes (§4.1).
4. **Z Anime y Krea2 Roma no declaran ninguna descarga**: hoy quedarían como instalación manual. Antes de publicarlos como paquetes gratuitos hay que añadir sus URLs y, en Krea2 Roma, revisar la licencia de los ficheros de terceros (issue #91).

Estado en el equipo de desarrollo: los 7 motores tienen todos sus ficheros de nodo presentes.

---

## 5. Estado de la implementación en OPENHIKER (2026-09-14)

Montado para revisarlo antes de migrar al repo `NomadStudio`.

| Pieza | Fichero |
|---|---|
| Página | `app/templates/pages/setup.html` (misma carcasa visual que la pantalla de perfiles) |
| Lógica de pasos | `app/static/js/pages/setup.js` |
| Estilos | `app/static/css/setup.css` |
| API y página | `app/routes/setup_routes.py` (blueprint `setup`, registrado en `app/__init__.py`) |
| Comprobaciones y detección de motores | `app/services/setup_service.py` |
| URLs que faltan en los workflows | Dentro de cada paquete de motor, en `annotation.downloads` (las pone `tools/packages/build_packages.py`, del vault: Z Anime, LoRA Lightning de Qwen, codificador y VAE de Krea2 Roma). El núcleo no guarda listas de descargas por motor. |
| Textos | `setup.*` y `settings.setup.*` en `en/es/zh/ko.json` (113 claves) |
| Entrada desde Ajustes | Sección "Asistente de configuración" › **Ver el asistente** → `/setup?preview=1` |
| Primer arranque | `/` redirige a `/setup` si no está terminado; `nav_status.js` también. Las instalaciones que ya tenían carpeta de salida cuentan como terminadas |

API nueva: `GET/PATCH /api/setup/state`, `POST /api/setup/check/comfy`, `POST /api/setup/check/lmstudio`, `POST /api/setup/check/output-dir`, `POST /api/setup/engines`, `POST /api/setup/models-folder/validate`, `POST /api/setup/downloads/sizes`. Reutiliza sin cambios: pruebas y "Examinar" de Ajustes, `POST /api/viewers` y `POST /api/models/imports/download-file`.

**Vista previa** (`?preview=1`): hace las comprobaciones y la detección reales, pero no guarda ajustes, no descarga y no crea perfiles. Cambiar el idioma sí se aplica (es una preferencia del navegador).

**Limitaciones de esta versión:**
- **Formato WebP**: el paso guarda la elección, marcado "Próximamente"; todavía no cambia nada (falta §3.5).
- **Ahorro de espacio en ComfyUI**: implementado (§3.3), desactivado por defecto; también en Ajustes › Avanzado.
- **Carpeta de datos**: solo informativa (OPENHIKER aún guarda los datos dentro de `app/`).
- **Descargas**: van dentro de la página del asistente, de una en una, con aviso al intentar cerrarla; no siguen en segundo plano si se cierra (§4.5). No se reanudan.
- **Recomendación de variante**: nunca propone una variante que no se pueda descargar (W4A8 no tiene URL).
- Motores con ficheros sin URL (modelo y LoRAs de Krea2 Roma, variantes W4A8) quedan como instalación manual.

## 6. Preguntas abiertas

1. **Imagen de muestra** para "Ver ejemplo ampliado": elegir una con degradado, texto y detalle fino donde la diferencia sea honesta de ver.
2. **Convertir imágenes existentes**: ¿se ofrece más adelante una herramienta para convertir el Album de PNG a WebP, avisando de que la pérdida es irreversible? Fuera de la versión 1.
3. **Imágenes de Build** (personajes, fondos): ¿aplicar también el ajuste de formato?
4. **Límite de 16.383 px**: confirmar el comportamiento exacto de Pillow al guardar WebP por encima del límite y cubrirlo con una prueba.
5. **Criterios de variante por GPU** (§4.3): tabla definitiva de memoria de vídeo → variante recomendada por motor, validada con pruebas reales.
6. **Qué motor preseleccionar** para instalar si el usuario no tiene ninguno.
