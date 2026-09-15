# Nomad Studio

**Estudio de imagen con IA en local.** Crea, retoca y organiza imágenes en tu propio equipo con [ComfyUI](https://github.com/comfyanonymous/ComfyUI) como motor de imagen y [LM Studio](https://lmstudio.ai/) para escribir prompts y describir imágenes. Tus imágenes se quedan en tu carpeta. Sin créditos ni nube.

[English](README.md) · Español — la aplicación está disponible en inglés, español, chino y coreano.

## Qué es

- **Un núcleo vacío que instala flows como paquetes.** Motores, flows, template packs y complementos llegan como paquetes ZIP ([docs/PACKAGE_FORMAT.md](docs/PACKAGE_FORMAT.md)).
- **Perfiles y Sessions.** Cada perfil tiene sus imágenes, historial y Sessions; una Vanish Session no guarda nada.
- **Asistente de configuración.** En el primer arranque comprueba ComfyUI y LM Studio, detecta qué ficheros de motores tienes, instala lo que falta y recomienda modelos de lenguaje ([docs/SETUP_WIZARD.md](docs/SETUP_WIZARD.md)).
- **Copias de seguridad y reset** desde Ajustes.
- **Servidores compartidos.** Varias instalaciones de Nomad Studio pueden usar el mismo ComfyUI y LM Studio de tu red; se esperan entre ellas en vez de pelearse por la GPU.
- **Servidor MCP** para que los agentes de IA creen y retoquen imágenes.

## Requisitos

- Windows, macOS o Linux
- Python 3.13
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) en marcha (en local o en otro equipo de tu red)
- [LM Studio](https://lmstudio.ai/) — opcional, para ayuda con prompts y descripción de imágenes
- Se recomienda una GPU con 8 GB de memoria de vídeo o más

## Ejecutar desde el código

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.lock   # Windows
# .venv/bin/pip install -r requirements.lock     # macOS / Linux
python app.py
```

Abre http://localhost:5123 — el asistente de configuración arranca la primera vez. Con `PORT=5124 python app.py` eliges otro puerto.

Las versiones portables y las actualizaciones desde la app se describen en [docs/APP_UPDATES.md](docs/APP_UPDATES.md).

## Licencia

Se definirá antes del lanzamiento público. Hasta entonces, todos los derechos reservados.
