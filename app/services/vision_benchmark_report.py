from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .. import paths


def _benchmark_dir() -> Path:
    return paths.data_file("vision_benchmarks")


def resolve_report_path(filename: str) -> Path | None:
    name = str(filename or "").strip()
    if not re.fullmatch(r"vision_benchmark_\d{8}_\d{6}\.md", name):
        return None
    candidate = _benchmark_dir() / name
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _report_filename(now: datetime) -> str:
    return f"vision_benchmark_{now.strftime('%Y%m%d_%H%M%S')}.md"


def _build_markdown(run_data: dict[str, Any]) -> str:
    generated_at = str(run_data.get("generatedAt", "")).strip()
    mode = str(run_data.get("mode", "")).strip()
    output_format = str(run_data.get("outputFormat", "")).strip()
    summary = (
        run_data.get("summary", {}) if isinstance(run_data.get("summary"), dict) else {}
    )
    results = (
        run_data.get("results", []) if isinstance(run_data.get("results"), list) else []
    )

    lines: list[str] = []
    lines.append("# Vision Describe Benchmark")
    lines.append("")
    lines.append(f"- Generated At (UTC): {generated_at}")
    lines.append(f"- Mode: {mode}")
    lines.append(f"- Output Format: {output_format}")
    lines.append(f"- Total Models: {int(summary.get('total', 0))}")
    lines.append(f"- OK: {int(summary.get('ok', 0))}")
    lines.append(f"- Failed: {int(summary.get('failed', 0))}")
    lines.append("")

    for item in results:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model", "")).strip() or "unknown"
        ok = bool(item.get("ok"))
        duration_ms = int(item.get("durationMs", 0) or 0)
        source = str(item.get("visionSource", "unknown")).strip()
        lines.append(f"## {model}")
        lines.append("")
        lines.append(f"- Status: {'ok' if ok else 'failed'}")
        lines.append(f"- Vision Source: {source}")
        lines.append(f"- Duration Ms: {duration_ms}")
        lines.append("")

        if ok:
            description = str(item.get("description", "")).strip()
            lines.append("### Output")
            lines.append("")
            lines.append("```")
            lines.append(description)
            lines.append("```")
            lines.append("")
        else:
            error_text = str(item.get("error", "")).strip() or "Unknown error"
            lines.append("### Error")
            lines.append("")
            lines.append("```")
            lines.append(error_text)
            lines.append("```")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_vision_benchmark_report(run_data: dict[str, Any]) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    out_dir = _benchmark_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _report_filename(now)
    abs_path = out_dir / filename

    payload = dict(run_data)
    payload["generatedAt"] = now.isoformat()
    markdown = _build_markdown(payload)
    abs_path.write_text(markdown, encoding="utf-8")

    rel_path = str(Path("app") / "data" / "vision_benchmarks" / filename)
    return {
        "filename": filename,
        "absolutePath": str(abs_path),
        "relativePath": rel_path,
        "markdown": markdown,
        "generatedAt": now.isoformat(),
    }
