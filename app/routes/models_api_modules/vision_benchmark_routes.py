from __future__ import annotations

from datetime import datetime, timezone
import uuid

from flask import jsonify, request, send_file

from app.config import DEFAULT_LMSTUDIO_CONTEXT_SIZE, DEFAULT_LMSTUDIO_TEMPERATURE
from app.routes.models_api_shared import (
    _append_lmstudio_output_log,
    _clip_text,
    _coerce_context_size,
    _coerce_lmstudio_temperature,
    _ensure_registry,
    _safe_http_url,
    models_api_bp,
)
from app.services.vision_benchmark_report import (
    save_vision_benchmark_report,
    resolve_report_path,
)
from app.services.vision_benchmark_service import (
    run_vision_describe_benchmark,
    list_vision_models_for_benchmark,
)
from app.services import vision_benchmark_control
from app.services import vision_benchmark_progress


@models_api_bp.post("/models/chat/describe-benchmark/stop")
def stop_describe_benchmark_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("runId", "")).strip()
    if not run_id:
        return jsonify({"error": "runId is required"}), 400

    accepted = vision_benchmark_control.request_stop(run_id)
    if not accepted:
        return jsonify(
            {"ok": False, "runId": run_id, "error": "Run is not active"}
        ), 404

    vision_benchmark_progress.mark_stopped(run_id)
    return jsonify(
        {
            "ok": True,
            "runId": run_id,
            "message": "Stop requested. Benchmark will end after current model.",
        }
    )


@models_api_bp.get("/models/chat/describe-benchmark/models")
def list_describe_benchmark_models():
    data = _ensure_registry()
    settings = data.setdefault("settings", {})

    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    models = list_vision_models_for_benchmark(lmstudio_url)
    return jsonify({"models": models})


@models_api_bp.get("/models/chat/describe-benchmark/progress/<run_id>")
def get_describe_benchmark_progress(run_id: str):
    progress = vision_benchmark_progress.get_progress(run_id)
    if progress is None:
        return jsonify({"error": "progress not found"}), 404
    return jsonify(progress)


@models_api_bp.get("/models/chat/describe-benchmark/report/<filename>")
def download_describe_benchmark_report(filename: str):
    report_path = resolve_report_path(filename)
    if report_path is None:
        return jsonify({"error": "report not found"}), 404
    return send_file(
        str(report_path),
        as_attachment=True,
        download_name=report_path.name,
        mimetype="text/markdown",
    )


@models_api_bp.post("/models/chat/describe-benchmark")
def describe_benchmark_with_lmstudio():
    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("runId", "")).strip() or str(uuid.uuid4())

    image_data_url = str(payload.get("imageDataUrl", "")).strip()
    describe_mode = (
        str(payload.get("describeMode", payload.get("describeScope", "full")))
        .strip()
        .lower()
    )
    output_format = (
        str(payload.get("outputFormat", payload.get("describeFormat", "text")))
        .strip()
        .lower()
    )

    if not image_data_url:
        return jsonify({"error": "imageDataUrl is required"}), 400

    if describe_mode not in {"full", "scene", "style"}:
        describe_mode = "full"
    if output_format not in {"text", "json"}:
        output_format = "text"

    data = _ensure_registry()
    settings = data.setdefault("settings", {})

    lmstudio_url = str(settings.get("lmStudioApiUrl", "")).strip()
    if not lmstudio_url:
        return jsonify({"error": "LM Studio URI is not configured"}), 400

    try:
        lmstudio_url = _safe_http_url(lmstudio_url, "LM Studio")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    context_size = _coerce_context_size(
        settings.get("lmStudioContextSize", DEFAULT_LMSTUDIO_CONTEXT_SIZE)
    )
    temperature = _coerce_lmstudio_temperature(
        settings.get("lmStudioTemperature", DEFAULT_LMSTUDIO_TEMPERATURE)
    )
    auto_disconnect = bool(settings.get("lmStudioAutoDisconnect", False))
    custom_prompts = (
        settings.get("customPrompts", {})
        if isinstance(settings.get("customPrompts"), dict)
        else {}
    )
    model_catalog = list_vision_models_for_benchmark(lmstudio_url)
    vision_benchmark_progress.init_run(run_id, model_catalog)

    vision_benchmark_control.start_run(run_id)
    try:
        run_data = run_vision_describe_benchmark(
            image_data_url=image_data_url,
            describe_mode=describe_mode,
            output_format=output_format,
            lmstudio_url=lmstudio_url,
            context_size=context_size,
            temperature=temperature,
            auto_disconnect=auto_disconnect,
            custom_prompts=custom_prompts,
            on_model_start=lambda model_id: (
                vision_benchmark_progress.mark_model_started(run_id, model_id)
            ),
            on_model_finished=lambda item: (
                vision_benchmark_progress.mark_model_finished(run_id, item)
            ),
            should_stop=lambda: vision_benchmark_control.should_stop(run_id),
        )
    except ValueError as exc:
        vision_benchmark_control.finish_run(run_id)
        vision_benchmark_progress.finish_run(run_id, stopped=False)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        vision_benchmark_control.finish_run(run_id)
        vision_benchmark_progress.finish_run(run_id, stopped=False)
        return jsonify({"error": str(exc)}), 502
    finally:
        vision_benchmark_control.finish_run(run_id)

    vision_benchmark_progress.finish_run(
        run_id, stopped=bool(run_data.get("stopped", False))
    )

    report_data = save_vision_benchmark_report(run_data)

    instruction = f"describe-benchmark:{describe_mode}:{output_format}"
    for item in run_data.get("results", []):
        if not isinstance(item, dict):
            continue

        model_name = str(item.get("model", "")).strip()
        description_text = str(item.get("description", "")).strip()
        error_text = str(item.get("error", "")).strip()
        ok = bool(item.get("ok"))

        _append_lmstudio_output_log(
            data,
            settings,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "model": model_name,
                "instruction": instruction,
                "editedPrompt": _clip_text(description_text, 1200),
                "rawOutput": _clip_text(description_text if ok else error_text, 1400),
                "ok": ok,
            },
        )

    return jsonify(
        {
            "runId": run_id,
            "mode": run_data.get("mode", describe_mode),
            "outputFormat": run_data.get("outputFormat", output_format),
            "stopped": bool(run_data.get("stopped", False)),
            "summary": run_data.get("summary", {"total": 0, "ok": 0, "failed": 0}),
            "results": run_data.get("results", []),
        }
    )
