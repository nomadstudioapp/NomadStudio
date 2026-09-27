# Usar Nomad Studio desde Claude Desktop, ChatGPT y Bionic (MCP)

Nomad Studio incluye un servidor **MCP** (Model Context Protocol). Con él, tu asistente de IA puede generar, retocar y combinar imágenes en tu propio PC — con tus modelos, tu ComfyUI y sin API keys — solo pidiéndoselo en el chat, y guardarlas paso a paso en tus Sessions.

> English: [MCP_SETUP.md](MCP_SETUP.md) · 中文: [MCP_SETUP_ZH.md](MCP_SETUP_ZH.md) · 한국어: [MCP_SETUP_KO.md](MCP_SETUP_KO.md)

## Antes de empezar

1. **Abre Nomad Studio** con `NomadStudio.bat` y déjalo abierto. El asistente habla con la app en marcha: si está cerrada, contestará que no puede conectar.
2. **ComfyUI** tiene que estar funcionando, igual que para generar desde la app.
3. **Localiza tu carpeta de Nomad Studio**: la que contiene `NomadStudio.bat` y la carpeta `app`. En esta guía la llamamos `C:\NomadStudio` — cámbiala por la tuya en todo lo que copies.

Los tres programas necesitan los mismos datos:

| Dato | Valor |
|---|---|
| Comando | `C:\NomadStudio\app\python\python.exe` |
| Argumentos | `-m` `app.mcp.server` |
| Variable `PYTHONPATH` | `C:\NomadStudio\app\lib;C:\NomadStudio\app` |
| Variable `PYTHONUTF8` | `1` |

Si abres Nomad Studio en otro puerto que no sea el 5123 (variable `PORT`), añade también `NOMAD_STUDIO_BASE_URL` = `http://127.0.0.1:<tu puerto>`.

---

## Claude Desktop

1. En Claude Desktop: **Settings → Developer → Edit Config**. Se abre `claude_desktop_config.json` (en `%APPDATA%\Claude\`).
2. Añade `nomad-studio` dentro de `mcpServers` (si el archivo está vacío, pega todo). En este archivo cada `\` se escribe doble:

```json
{
  "mcpServers": {
    "nomad-studio": {
      "command": "C:\\NomadStudio\\app\\python\\python.exe",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "PYTHONPATH": "C:\\NomadStudio\\app\\lib;C:\\NomadStudio\\app",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

3. **Cierra Claude del todo** (también desde el icono junto al reloj) y vuelve a abrirlo. En el chat, el icono de herramientas debe mostrar las de `nomad_studio`.

## ChatGPT (app de escritorio)

Funciona en los modos **Codex** y **ChatGPT Work** de la app de escritorio, que ejecutan servidores MCP locales. El chat normal de ChatGPT solo admite servidores remotos por internet, así que ahí no aparece.

**Opción A — desde la app:** `Ctrl + ,` → **Integrations → Plugins → Add → Add MCP Server** → tipo **STDIO**, nombre `nomad_studio`, y rellena comando, argumentos y variables con los datos de la tabla de arriba.

**Opción B — editando el archivo** (con la app cerrada): abre `%USERPROFILE%\.codex\config.toml` y añade al final:

```toml
[mcp_servers.nomad_studio]
command = 'C:\NomadStudio\app\python\python.exe'
args = ["-m", "app.mcp.server"]
startup_timeout_sec = 60
tool_timeout_sec = 600

[mcp_servers.nomad_studio.env]
PYTHONPATH = 'C:\NomadStudio\app\lib;C:\NomadStudio\app'
PYTHONUTF8 = "1"
```

`tool_timeout_sec = 600` da hasta 10 minutos por generación: en calidad máxima o con varias imágenes se tarda más de lo que ChatGPT espera por defecto. Vuelve a abrir la app. ChatGPT te pedirá permiso antes de generar o retocar; las consultas (modelos, acciones, última imagen) no lo necesitan.

## Bionic (LM Studio)

1. En Bionic abre la configuración de **servidores MCP** y añade uno nuevo.
2. Nombre `Nomad Studio`, tipo **stdio**, y comando, argumentos y variables de la tabla de arriba.
3. Guarda y reinicia Bionic (o el servidor).

Si prefieres editar el archivo (con Bionic cerrado), es `%USERPROFILE%\.lmstudio\apps\bionic\.internal\ng-mcp.json`:

```json
{
  "name": "Nomad Studio",
  "enabled": true,
  "connection": {
    "type": "stdio",
    "command": "C:\\NomadStudio\\app\\python\\python.exe",
    "args": ["-m", "app.mcp.server"],
    "env": {
      "PYTHONPATH": "C:\\NomadStudio\\app\\lib;C:\\NomadStudio\\app",
      "PYTHONUTF8": "1"
    }
  }
}
```

(Esa entrada va dentro de la lista `servers` del archivo.)

**Modelo recomendado en LM Studio:** uno con uso de herramientas (tool use). Probados: **Ornith 1.5 9B** (el que mejor lo hace), Qwythos 9B y Gemma QAT.

---

## Probarlo

Escribe en el chat:

```
¿Qué modelos tengo en Nomad Studio?
```

y luego:

```
Genera con Nomad Studio: a weathered shop sign that says OPEN SOURCE, brick wall, golden hour --ar 16:9 --v monaco --q max
```

Los ajustes pueden ir al final del prompt, como en Midjourney: `--ar 16:9` (formato), `--no people` (lo que no debe salir), `--seed 42`, `--v <identificador del modelo>` (lo ves en Settings › Images y en la respuesta a "¿qué modelos tengo?"), `--q fast|balanced|max`, `--r 2` (varias imágenes).

Las imágenes quedan en el **álbum del agente** (una carpeta por programa: Claude, Codex, Bionic…), visible en la pantalla «¿Quién genera?» de Nomad Studio.

## Si algo falla

| Síntoma | Solución |
|---|---|
| «No se pudo conectar con Nomad Studio» | Abre Nomad Studio. Si usas otro puerto, añade `NOMAD_STUDIO_BASE_URL`. |
| Las herramientas no aparecen | Revisa las rutas (que `python.exe` exista ahí) y reinicia el programa del todo. |
| Has movido la carpeta de Nomad Studio | Cambia las rutas en la configuración y reinicia. |
| Pregunta formato, velocidad o modelo | Es normal la primera vez; contéstale o ponlo en el prompt (`--ar`, `--q`, `--v`). |
| Se corta en generaciones largas (ChatGPT) | Sube `tool_timeout_sec`. |
