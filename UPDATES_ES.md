# Novedades de Nomad Studio

[English](UPDATES.md) · Español · [中文](UPDATES_ZH.md) · [한국어](UPDATES_KO.md)

Lo más reciente, arriba. Las descargas y sumas de comprobación de cada versión están en [Releases](https://github.com/nomadstudioapp/NomadStudio/releases). La app te ofrece cada versión nueva por sí sola ("Reiniciar y actualizar").

## Próxima versión (aún sin publicar)

- **Selección inteligente: varios objetos a la vez.** Escríbelos separados por comas (`crow, pig, girl`) y obtienes una máscara y un recorte por objeto, más una imagen compuesta con cada objeto en su color y una leyenda para revisarlos de un vistazo. También por el MCP.

## 2026-10-18 · 1.1.2

- **Borrado inteligente de objetos devuelve la imagen limpia.** Podía guardar la vista previa de la máscara de selección (una silueta blanca sobre negro) en lugar del resultado. Cualquier workflow con un nodo de vista previa devuelve ahora la imagen guardada, en la app y por el MCP.
- **Borrado inteligente de objetos conserva el tamaño del original.** El resultado salía ligeramente reescalado, con bandas transparentes en los bordes. Ahora mide exactamente lo mismo que el original, y todo lo que queda fuera de la selección conserva sus píxeles originales.
- **Entradas usadas antes muestra cada imagen una vez.** La misma referencia elegida varias veces aparecía una vez por uso. Al volver a elegirla se reutiliza la copia guardada en vez de guardar otra.
- **MCP: cada retoque usa una semilla nueva,** como hace la app. Antes, todas las ediciones hechas por el MCP repetían la semilla fija del workflow, y con ella los mismos fallos. Para repetir un retoque exacto, pasa `seed` (o acaba la instrucción con `--seed 1234`); cada respuesta dice la semilla usada.
- **Packs:** Extract 0.1.13 viene con la app e incluye el arreglo del Borrado inteligente de objetos.

## 2026-10-17 · 1.1.1

- **Los packs actualizados en Ko-fi vuelven a salir como oficiales.** La 1.1.0 marcaba como "paquete no oficial" los packs reconstruidos para la variación Turbo de Qwen 2.1. El catálogo de la app ya conoce sus huellas nuevas y conserva las anteriores, así que los packs que descargaste antes siguen siendo oficiales.

## 2026-10-17 · 1.1.0

- **Qwen Image 2.1 Turbo para editar.** Editar Qwen 2.1, Multi-reference Compose y todos los flows con el motor de edición de Qwen 2.1 tienen **Advanced › Variación: Normal / Turbo**. Turbo va a 8 pasos, unas dos veces más rápido (una edición pasa de ~41 s a ~20 s en una RTX 4060 Ti) con una calidad parecida. Cuantización muestra las precisiones de la variación elegida, y Steps la sigue.
- **Proporción de salida en Editar Qwen 2.1.** El panel Resolución ofrece *Original* (por defecto), proporciones de 9:16 a 21:9 que mantienen los píxeles de la fuente con la forma nueva —por ejemplo, recomponer un retrato 9:16 en 16:9— y una **Resolución personalizada** que puedes escribir.
- **MCP:** refine y mix aceptan `variation` (`normal` / `turbo`); Editar Qwen 2.1 acepta `aspect_ratio` o `width`/`height`.
- **Packs:** Core Refine 0.1.6, Extract 0.1.12 y Presets Core 0.1.10 vienen con la app. Los packs de Ko-fi con el motor de edición de Qwen 2.1 tienen versiones nuevas con Turbo; necesitan esta versión de la app.

## 2026-10-15 · 1.0.1

- **Al importar el .zip de una Session** se restauran sus imágenes, así que una Session compartida desde otro ordenador se abre completa.
- **La exportación de Session** indica los archivos de modelo que necesita cada paso.

## 2026-10-13 · 1.0.0

- Primera versión pública: crea y retoca imágenes 100% en local con ComfyUI y LM Studio, sin cuenta ni claves de API. El asistente de configuración instala ComfyUI y LM Studio (Windows y Linux) y descarga un primer motor de imagen.
