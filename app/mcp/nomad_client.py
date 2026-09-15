"""Cliente HTTP delgado contra el backend Flask de Nomad Studio.

Mantiene un unico httpx.AsyncClient con cookie jar persistente: una vez
seleccionado un "agent viewer" (ver agent_identity.py), la cookie de sesion
de Flask se reutiliza en todas las llamadas siguientes (generate...).

La lectura de la imagen generada NO pasa por aqui: el MCP server corre en
la misma maquina que Nomad Studio, asi que lee el fichero directamente del
disco (ver server.py, usa app.services.image_service). Este cliente solo
hace HTTP para lo que de verdad requiere el backend (agentes, imports,
generacion, settings)."""

from __future__ import annotations

from typing import Any

import httpx

from app.mcp.config import NOMAD_BASE_URL, REQUEST_TIMEOUT_SECONDS


class NomadClientError(RuntimeError):
    """Error al hablar con el backend Flask de Nomad Studio."""


class NomadClient:
    def __init__(self, base_url: str = NOMAD_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=REQUEST_TIMEOUT_SECONDS)
        self._output_dir_cache: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── Agent viewers ─────────────────────────────────────────────────

    async def list_agents(self) -> list[dict[str, Any]]:
        data = await self._get("/api/agents")
        agents = data.get("agents")
        return agents if isinstance(agents, list) else []

    async def create_agent(self, name: str) -> dict[str, Any]:
        data = await self._post("/api/agents", {"name": name})
        return data.get("agent", {})

    async def select_agent(self, agent_id: str) -> dict[str, Any]:
        data = await self._post(f"/api/agents/{agent_id}/select", {})
        return data.get("agent", {})

    # ── Generation ────────────────────────────────────────────────────

    async def list_imports(self) -> list[dict[str, Any]]:
        data = await self._get("/api/models/imports")
        imports = data.get("imports")
        return imports if isinstance(imports, list) else []

    async def get_active_import(self) -> dict[str, Any] | None:
        """Registro completo (con analysis.quantization) del import activo en
        Nomad Studio, o None si no hay ninguno activo."""
        data = await self._get("/api/models/imports/active")
        active = data.get("active")
        return active if isinstance(active, dict) else None

    async def get_import(self, import_id: str) -> dict[str, Any]:
        data = await self._get(f"/api/models/imports/{import_id}")
        record = data.get("import")
        return record if isinstance(record, dict) else {}

    async def check_files(self, files: list[dict[str, str]]) -> dict[str, bool]:
        """Mapa "subfolder/filename" -> descargado, contra la carpeta de
        modelos de ComfyUI."""
        if not files:
            return {}
        data = await self._post("/api/models/imports/check-files", {"files": files})
        exists = data.get("exists")
        return exists if isinstance(exists, dict) else {}

    async def generate(
        self,
        import_id: str,
        basic_values: dict[str, Any],
        advanced_values: dict[str, Any] | None = None,
        num_images: int = 1,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"basicValues": basic_values, "numImages": num_images}
        if advanced_values:
            payload["advancedValues"] = advanced_values
        return await self._post(f"/api/models/imports/{import_id}/generate", payload)

    async def submit_refine(
        self,
        workflow_file: str,
        image_data_url: str,
        advanced_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta un flow de Refine de principio a fin contra ComfyUI —
        POST /api/models/refine/generate, la contraparte sincrona/autocontenida
        de generate() para Refine (sube la imagen, aplica advancedValues,
        encola, hace polling y guarda el resultado, todo en el servidor)."""
        payload: dict[str, Any] = {"workflowFile": workflow_file, "imageDataUrl": image_data_url}
        if advanced_values:
            payload["advancedValues"] = advanced_values
        return await self._post("/api/models/refine/generate", payload)

    async def list_flows(
        self, category: str | None = None, available: bool = True, full: bool = True
    ) -> list[dict[str, Any]]:
        """Catalogo de flows conocidos por Nomad Studio (built-in + packs instalados) —
        GET /api/flows, mismo endpoint que usa la web UI. Con full=True cada item trae la
        definicion completa (steps/fields), no solo metadatos, para poder introspeccionar
        el schema de cada flow sin una peticion por flow."""
        params: dict[str, str] = {"available": "true" if available else "false", "full": "true" if full else "false"}
        if category:
            params["category"] = category
        data = await self._get("/api/flows", params=params)
        flows = data.get("flows")
        return flows if isinstance(flows, list) else []

    async def get_output_dir(self) -> str:
        """Ruta base del Album (``<output_dir>/<viewer-slug>/<filename>`` es
        donde vive cada imagen guardada). Cacheada tras la primera llamada —
        cambia solo si el usuario la reconfigura en Nomad Studio, algo que
        requeriria reiniciar igualmente el proceso MCP para reflejarse."""
        if self._output_dir_cache is not None:
            return self._output_dir_cache
        data = await self._get("/api/models/settings")
        output_dir = str(data.get("settings", {}).get("outputDir", "") or "").strip()
        if not output_dir:
            raise NomadClientError("Nomad Studio no tiene configurado un output dir (settings.outputDir vacio).")
        self._output_dir_cache = output_dir
        return output_dir

    def image_url(self, filename: str, viewer_id: str | None = None) -> str:
        url = f"{self._base_url}/api/images/{filename}"
        if viewer_id:
            url += f"?viewer={viewer_id}"
        return url

    # ── Internals ─────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = await self._http.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NomadClientError(f"GET {path} fallo: {exc}") from exc
        return response.json()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.post(path, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            error_response = getattr(exc, "response", None)
            if error_response is not None:
                try:
                    detail = f" — {error_response.json().get('error', '')}"
                except Exception:
                    detail = ""
            raise NomadClientError(f"POST {path} fallo: {exc}{detail}") from exc
        return response.json()
