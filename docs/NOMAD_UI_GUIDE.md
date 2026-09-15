# Nomad UI — Guía de referencia del design system

> Fuente viva: `/nomadui` (`app/templates/pages/nomadui.html` + `app/static/css/parts/nomadui.css`) —
> página interactiva dentro de la app con demos de cada componente. Este documento es su versión
> escrita: las reglas CSS reales detrás de cada clase, para no tener que explicarlas cada vez.
> Generado 2026-08-13 leyendo directamente `nomad_studio.css`, `modals.css`, `responsive.css`,
> `create.css`, `variables.css`.
>
> Cobertura: Create está prácticamente todo aquí. Refine está cubierto en los patrones compartidos
> (botones, inputs, panels) pero sus flows más nuevos (los últimos añadidos) puede que usen alguna
> clase que todavía no está en `/nomadui` — si encuentras una clase sin documentar, es candidata a
> añadirse tanto a `/nomadui` como a este fichero.

---

## 0. Las 3 reglas que hay que saber de memoria

### Regla 1 — "Sin borde" casi siempre significa `box-shadow` inset, no `border: none` a secas
El patrón dominante en TODO el sistema (inputs, selects, textarea, botones aspect/num/quality,
icon buttons) es:

```css
.algo {
  border: none;                                          /* o ni se declara */
  box-shadow: inset 0 0 0 1.5px var(--scrollbar-hover);   /* esto ES el borde visual */
}
```

**Por qué:** un `box-shadow` inset no afecta al layout (no cambia el box-sizing ni provoca reflow
al cambiar grosor en hover/focus) y permite bordes de esquina perfectamente uniformes en elementos
con `border-radius`. Es intencional, no un descuido — se repite en decenas de componentes.

Estado por defecto → hover → focus/active suele ser una progresión de intensidad del mismo token:
`var(--scrollbar-hover)` (sutil) → `var(--text-secondary)` (hover) → `var(--accent)` (focus/activo).

**Excepciones con `border` real** (no inset-shadow): `.btn` base, `.panel`, `.describe-switch-toggle`,
`.cs-workflow-strip`, `.cs-workflow-chip`, `.chip`, `.cs-tag`, `.cs-session-badge`,
`.settings-prompt-tab`, `.settings-btn-secondary/-ghost`. Todos estos SÍ tienen un `border: 1px solid`
de verdad — normalmente algo pequeño y decorativo (tag, badge, panel contenedor) o algo con estado
binario claro (toggle, tab).

### Regla 2 — Los colores casi siempre vienen de `var(--token)`, con una lista conocida de excepciones hardcodeadas
La norma es usar variables de tema (`var(--accent)`, `var(--text)`, `var(--muted)`, `var(--line)`,
etc., ver §1) para que todo reaccione a los 8 temas. Hay una lista concreta de sitios que rompen
esto con hex fijo — ver §5 "Inconsistencias conocidas". Si vas a tocar uno de esos componentes,
es una buena oportunidad para tokenizarlo, pero no es obligatorio arreglarlo de paso.

### Regla 3 — El patrón de toggle (pill switch) es: track con inset-shadow + thumb sólido en `--accent`
Ver detalle completo en §2 "Toggles". El track normalmente NO tiene `border` real (usa el truco de
la Regla 1), y el thumb que se desliza SIEMPRE es `background: var(--accent)` sólido — así el ojo
detecta "esto está activo" por el color de marca, no por el borde.

---

## 1. Tokens (design tokens / variables de tema)

Definidos en `app/static/css/parts/variables.css`:
- Bloque `:root` (líneas 1-131): `--bg`, `--bg-soft`, `--bg-panel`, `--line`, `--text`,
  `--text-bright`, `--text-secondary`, `--muted`, `--accent`, `--accent-soft`, `--good` (`#6fb87f`,
  fijo en todos los temas — no se retematiza), `--radius` (14px) y la escala
  `--radius-xs/sm/md/lg/xl/pill` (4/6/9/12/16/999px), `--input-bg`, `--input-border`,
  `--input-focus-border`, `--advanced-bg/-border/-text`, `--scrollbar-hover` (el token gris usado
  para casi todos los "falsos bordes" de la Regla 1).
- **8 temas** como bloques `html[data-theme="1"]` … `[data-theme="8"]` en el mismo fichero
  (Dawn/Dusk/Twilight/Night/Void/Mars/Jupiter/Saturn), cada uno redefiniendo el mismo set de
  variables. Los temas 4 y 5 redefinen menos variables que el resto (heredan del `:root` lo que no
  tocan) — si un color se ve "raro" solo en esos dos temas, es la primera sospecha.
- Ver todos los swatches en vivo: `/nomadui` → botón "Tokens" (arriba a la derecha).

---

## 2. Botones

| Clase | Borde | Fondo | Estado activo/hover |
|---|---|---|---|
| `.btn` (base) | real, `1px solid transparent` | `var(--accent-soft)` | hover: borde → `var(--accent)` |
| `.btn.primary` | real, `var(--accent)` | `var(--accent-soft)` | (= estado hover del base, permanente) |
| `.btn.btn-danger` | real, hardcoded | hardcoded `#1e0d0d` / texto `#ffd5d5` | ⚠️ no usa tokens |
| `.btn.btn-small` | — | — | solo tamaño (`padding:5px 9px`, radius 6px) |
| `.settings-btn-secondary` | real, `var(--scrollbar-hover)` | `var(--bg-soft)` | hover: borde `var(--text-secondary)` |
| `.settings-btn-ghost` | real, `var(--scrollbar-hover)` | transparente | hover: bg `var(--bg-soft)` |
| `.settings-btn-reset` | real, `var(--accent)` | `var(--accent-soft)` | — |
| `.close-round-btn` | — (circular) | hardcoded `#1e0d0d` | ⚠️ no usa tokens |
| `.nsc-icon-btn` | inset-shadow `var(--scrollbar-hover)` | `var(--bg-panel)` | hover: shadow → `var(--text-secondary)` |
| `.nsc-generate-btn` | ninguno | sólido `var(--accent)`, texto `#fff` | hover/active invierten: bg↔texto |
| `.nss-generate-scenes-btn` | ninguno | `var(--nss-accent)` (= `--accent` en flow pages) | `.is-composing` → bg hardcoded `#f5a623` (ámbar) |
| `.ncf-strip-btn` | real, `color-mix(var(--line) 70%, transparent)` | transparente | `.is-active`: tinte accent más fuerte |
| `.ncf-strip-apply` | ninguno | sólido `var(--accent)`, texto `#fff` | — |
| `.describe-switch-toggle` | **real**, `var(--scrollbar-hover)` | transparente | ver §2.1 |
| `.create-action-btn` | real pero `transparent !important` (invisible hasta estado) | transparente | `.active`: bg `var(--oh-accent-soft)`, borde `var(--oh-accent-line)` |
| `.create-basic-similarity-toggle` | ver §2.1 | ver §2.1 | ver §2.1 |

### 2.2 Botones redondos de navegación (posición fija, esquinas)

Dos sub-familias, ambas ya en `/nomadui` → Buttons → "Round nav buttons":

- **Con borde real** (`.cs-theme-cycle-btn`, `.ns-caption-tab`): `border: 1px solid var(--line)`,
  fondo `var(--bg-panel)`. Hover: fondo → `var(--bg-toggle)`, borde → `var(--accent)`.
  `.cs-theme-cycle-btn` es el ciclo de temas (abajo-izquierda en el hub); `.ns-caption-tab` es el
  botón de editar el caption del overlay de vídeo (abajo-derecha, solo visible como herramienta de
  grabación de tutoriales — ver `video_caption.css`, es "click-through": el overlay del caption en
  sí tiene `pointer-events:none`, solo esta pestaña y su popover editor son clicables).
- **Sin borde, solo icono** (`.cs-logo-btn` con `.cs-logo-btn-img` dentro, `.cs-settings-btn`,
  `.cs-history-toggle`, `.cs-card-zoom-btn`): transparente, sin borde, `color: var(--muted)` →
  `var(--text)` en hover. `.cs-logo-btn` es el botón de avatar/cambiar de viewer (arriba-izquierda) —
  el que cambia no es el botón en sí (siempre transparente) sino el `<img>` de 36px dentro, que gana
  un anillo `border-color: var(--accent)` en hover.
- **Tooltip compartido — `.cs-mode-tip`**: todos estos botones (y varios más: Save, History Clear,
  album lightbox, card-zoom) usan el mismo mecanismo de tooltip al hover — `span.cs-mode-tip` como
  hijo del botón, `background: var(--tooltip-bg)`, `border: 1px solid var(--tooltip-border)`,
  aparece con fade + `translateY` de 3px. Por defecto se abre hacia abajo; los botones que viven
  cerca del borde inferior de la pantalla (`.ns-caption-tab`, `.album-card-expand-goto`,
  `.agent-lightbox-copy`) invierten la dirección (`bottom: calc(100% + 8px)`) para que no se corte.

### 2.1 Toggles (pill switch) — el que preguntabas

Hay **dos implementaciones** del mismo patrón visual en el código, con pequeñas diferencias:

**`.describe-switch-toggle`** (usado en el modal Describe, Text/JSON, Full/Scene):
- Track (`.btn.describe-switch-toggle`): **borde real** `1px solid var(--scrollbar-hover)`, fondo transparente, `border-radius: 7px`.
- Thumb (`.describe-switch-thumb`): pastilla que se desliza dentro, `background: var(--accent)` sólido — el color de marca, no un gris neutro.
- `.is-right` en el toggle mueve el thumb con `transform: translateX(100%)`.
- Labels: el lado activo pasa a `var(--text-bright)`, el inactivo se queda en `var(--muted)`.
- Hover/focus: el borde del track sube a `var(--text-secondary)` (el thumb no cambia).

**`.create-basic-similarity-toggle`** (usado en el panel de Create, "Visual similarity"):
- Hay una versión base y una versión `.panel-right` que la sobreescribe (la que realmente se ve en Create). La versión que importa es `.panel-right`: **sin borde real**, usa el truco de la Regla 1 — `box-shadow: inset 0 0 0 1.5px var(--scrollbar-hover)`.
- Track (`.create-basic-switch`): mismo patrón, inset-shadow en vez de borde.
- Thumb (`.create-basic-switch-thumb`): círculo 16px, apagado = `var(--muted)`, encendido = `var(--text)` (no `--accent` en la versión base) mientras el track pasa a `var(--accent)`.
- Cuando está ON, todo el wrapper (`.panel-right .create-basic-similarity-toggle:not(.off)`) gana un `box-shadow: inset 0 0 0 1.5px var(--accent)` — el contorno entero se ilumina en el color de marca, no solo el thumb.
- ⚠️ Inconsistencia menor: la versión base usa `var(--nss-accent)` para el track ON y la versión `.panel-right` usa `var(--accent)` directamente — mismo efecto visual en la práctica (`--nss-accent` suele apuntar a `--accent`), pero si algún día se desacoplan dejarán de verse igual.

**Resumen para replicar un toggle nuevo:** sin borde real (inset-shadow sutil `var(--scrollbar-hover)`), thumb o wrapper entero pasa a `var(--accent)` cuando está ON, texto/labels usan `var(--muted)` → `var(--text-bright)` o `var(--text)` para marcar cuál lado está activo.

---

## 3. Inputs

| Clase | Borde | Fondo | Radius |
|---|---|---|---|
| `.nsc-input` | inset-shadow `var(--scrollbar-hover)` (hover→`text-secondary`, focus→`accent`) | `var(--bg-panel)` | 6px |
| `.nsc-select` | igual que `.nsc-input` | `var(--bg-panel)` | 6px |
| `.nsc-textarea` | **ninguno, plano** (`box-shadow: none` en todos los estados) | `var(--bg-panel)` | `var(--radius-lg)` |
| `.nsc-aspect-btn` | inset-shadow (default) → `.is-active`: fondo se vuelve transparente, ring pasa a `var(--accent)` | `var(--bg-panel)` por defecto | 7px |
| `.nsc-res-btn` | sin borde/shadow en ningún estado | transparente → `.is-active`: sólido `var(--nss-accent, var(--accent))`, texto `#fff` | — |
| `.nsc-num-btn` | igual patrón que aspect-btn | `var(--bg-panel)` → activo: transparente + ring accent | — |
| `.nsc-quality-btn` | igual patrón que res-btn (plano, sin shadow) | transparente → activo: sólido accent, texto `#fff` | — |

Nota: `.nsc-textarea` es la única excepción sin ningún feedback visual de foco/hover — si alguna vez
se siente "muerta" al hacer click, es por diseño, no un bug.

### 3.1 Componentes de Refine reciente (añadidos 2026-08-13)

- **Selector de cuantización**: reutiliza `.nsc-quality-btn` tal cual (mismo pill plano), generado
  dinámicamente por `flow-quantization.js` a partir del bloque `config.quantization` de cada flow —
  no es una clase nueva, es el mismo componente de Quality con otra fuente de datos. `.nsc-quality-dot`
  y el `<small>` dentro de `.nsc-quality-copy` existen en el JS pero están `display:none` en CSS —
  no se usan actualmente aunque el código los renderiza.
- **Slider param block** (`.nsc-param-block` > `.nsc-param-title` + `.nsc-param-value` +
  `.nsc-aspect-slider`): usado para threshold/mask-expand de Smart Selection, el slider de aspect
  ratio, y el scale de Outpaint (`.nsc-scale-slider`, mismo thumb, track más fino). Thumb siempre
  círculo 18px `background: var(--accent)`; track 3px `color-mix(var(--accent) 65%, black)`.
- **Outpaint — position grid** (`.nsc-pos-grid` > `.nsc-pos-cell`): rejilla 3×3, celdas con borde
  real `1px solid var(--border, #333)`, `.is-active` → fondo y borde sólidos `var(--accent)`. Ancla
  dónde se coloca la imagen original dentro del canvas ampliado.
- **Outpaint — canvas preview** (`.nsc-outpaint-preview`): el elemento real es un `<canvas>`
  (no CSS puro), pintado con checkerboard cuando el modo de relleno es "transparent". Estado vacío:
  `.nsc-outpaint-preview--placeholder`.
- **Engine select** (`.nsc-preset-btn--engine`): variante a ancho completo de `.nsc-preset-btn`
  (mismo patrón inset-shadow de la Regla 1), usada en Photo Editing/Portrait Fix cuando el nombre
  del modelo base es largo y no cabe en una fila estrecha.

---

## 4. Panels & Cards

- **`.panel`**: borde real `1px solid var(--line)`, `border-radius: 0` (esquinas cuadradas
  deliberadamente), fondo transparente. Es el contenedor "serio", no decorativo.
- **`.panel.settings-panel-v2`**: no es una caja — solo `border-bottom: 1px solid var(--line)`, se
  usa como separador de sección, no como panel cerrado.
- **`.cs-card`** (las cards de Create/Refine/Explore/Build en el hub): sin borde, fondo es un
  `color-mix()` calculado a partir de `var(--accent)` (reactivo al tema), con spotlight de hover
  vía `::after` + gradiente radial posicionado por JS (`--cs-mx`/`--cs-my`, mousemove). El color de
  acento de cada card (`--cs-card-accent`, `--cs-card-icon-bg`) es **hex fijo por familia**
  (`.cs-card--create` = `#ff4d4d`, `.cs-card--refine` = `#6b8cff`, etc.) — esto SÍ es intencional:
  cada categoría mantiene su color de marca aunque cambies de tema, no es un bug de tokenización.
- **`.cs-workflow-strip` / `.cs-workflow-chip` / `.cs-workflow-edit-btn`**: todos con borde y fondo
  en `color-mix(var(--accent) X%, transparent)` — 100% tokenizados.

---

## 5. Status & Feedback

- **`.nav-led`** (punto de disponibilidad de modelo): ⚠️ **hardcoded**, no usa `var(--good)` pese a
  que ese token existe y se usa en otros sitios (`.nui-alert.success`, otro status-dot en
  `responsive.css:1436`). Gris idle `#6f778a`, verde disponible `#39ff86`, rojo no-disponible
  `#ff6c5f`. Si tocas este componente, es candidato a tokenizar.
- **`.nsc-progress-track` / `.nsc-progress-bar`**: barra plana, track `var(--line)`, fill
  `var(--accent)`, anima `width` en 0.35s.
- **`.nsc-ring` (spinner circular)**: track `var(--line)`, fill `var(--accent)`.
  `.nsc-ring--indeterminate` cambia a dash-array corto + rotación continua en vez de rellenar
  progresivamente. Dentro de botones con fondo sólido de color (ej. `.nsc-generate-btn`), el ring
  se fuerza a blanco (`#fff`/`rgba(255,255,255,.25)`) porque está sobre fondo accent, no por
  inconsistencia.
- **`.chip`**: 100% tokenizado — borde y fondo en `color-mix(var(--accent) X%, transparent)`.
- **`.cs-tag`**: borde real `var(--line)`, fondo `var(--bg)`, texto `var(--muted)`.
- **`.cs-session-badge`**: borde real `color-mix(var(--accent) 25%, transparent)`, fondo
  transparente (pill hueco, no relleno).
- **`.settings-prompt-tab`**: borde real `var(--line)` → `.is-active`: fondo `var(--bg-panel)`,
  borde `var(--accent)`, texto `var(--text-bright)`.

---

## 6. Inconsistencias conocidas (hex hardcodeado en vez de token)

Lista para cuando toque una pasada de limpieza — no bloqueante, pero conviene saberlo antes de
copiar uno de estos componentes como base para algo nuevo:

- `.btn.btn-danger`, `.close-round-btn` → paleta roja fija (`#1e0d0d`/`#ffd5d5`/`#e03c3c`)
- `.nsc-generate-btn`, `.nss-generate-scenes-btn`, `.ncf-strip-apply`, `.nsc-res-btn.is-active`,
  `.nsc-quality-btn.is-active` → texto `#fff` fijo (asumen que siempre van sobre fondo accent sólido)
- `.nss-generate-scenes-btn.is-composing` → ámbar `#f5a623` fijo (estado "trabajando")
- `.nav-led` → verde/rojo/gris fijos, no usa `var(--good)` existente

Estos NO incluyen los `--cs-card-accent` por familia (Create/Refine/Explore/Build) — esos son
intencionales, ver §4.

---

## 7. Cómo usar esto en la práctica

1. Antes de construir un componente nuevo, mira si ya existe algo parecido en `/nomadui` (Create
   está casi completo, Refine parcialmente — revisa igualmente `nomad_studio.css` si no aparece).
2. Aplica la Regla 1 por defecto (inset-shadow, no `border`) salvo que el componente sea un
   tag/badge/panel/tab, donde sí toca usar borde real.
3. Usa `var(--accent)` para "esto está activo/seleccionado", `var(--scrollbar-hover)` → `var(--text-secondary)`
   para la progresión neutral default→hover, y evita hex fijo salvo que sea deliberado (branding de
   card, o icono sobre fondo de color sólido).
4. Si añades un componente realmente nuevo (no una variante de uno existente), considera añadirlo
   también a `/nomadui` (`app/templates/pages/nomadui.html`) para que quede documentado en vivo,
   igual que este fichero.
