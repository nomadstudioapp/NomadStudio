"""Servidor MCP embebido de Nomad Studio.

Expone tools (`nomad_studio_create_image`, ...) que un host MCP
(Claude Desktop, LM Studio) puede invocar. El servidor no genera nada
por si mismo: traduce cada tool call en llamadas HTTP contra el backend
Flask de Nomad Studio, que es quien habla con ComfyUI.
"""
