"""Audit the models catalog for what a hash check cannot tell (NomadStudio#11):
who publishes each file, under which license, whether it is gated, and
whether it is a third-party re-upload of someone else's model.

check_models_catalog.py --online already proves every address answers and
serves the declared SHA-256. This asks the hosts' APIs for the rest, without
downloading anything:

- Hugging Face  GET /api/models/<repo>: author, gated, cardData.license /
  license_name / license_link, base_model.
- CivitAI       GET /api/v1/model-versions/<id> + /api/v1/models/<id>: creator,
  base model, allowCommercialUse / allowDerivatives / allowDifferentLicense.

Each file gets flags that need a human decision; the rest is fine as is.

Usage:
    python tools/packages/audit_models_catalog.py [catalog.json] [--md report.md] [--hf-token hf_…]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote
from urllib.request import Request, urlopen

DEFAULT = Path(__file__).resolve().parents[2] / "app" / "static" / "data" / "models_catalog.json"
_HF_RE = re.compile(r"^https://huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/([^?]+)")
_CIVITAI_RE = re.compile(r"civitai\.com/api/download/models/(\d+)")

# Publishers whose uploads are the model's own release or ComfyUI's official
# repackaging. Anyone else is a third party (a quantization, a re-host): not
# wrong, but worth a look at who they are and what they did to the file.
FIRST_PARTY = {
    "Comfy-Org", "black-forest-labs", "lightx2v", "circlestone-labs", "fal",
    "Qwen", "krea", "ideogram-ai", "ByteDance-Seed", "bytedance-research",
}
# Licenses that allow commercial use of the outputs and redistribution of the
# weights with little fuss. Anything else is flagged for reading.
OPEN_LICENSES = {"apache-2.0", "mit", "bsd-3-clause", "cc-by-4.0", "openrail", "openrail++",
                 "creativeml-openrail-m", "bsd-2-clause", "cc0-1.0"}
# Licenses whose flag was already reviewed, with why — reported as a note, not
# a flag.
ACCEPTED_LICENSES = {
    # @Alibaba_Qwen on X, 2026-09-21, replying about Qwen Image 2.1.
    "qwen-research": ("LICENSE is non-commercial for the weights, but Qwen stated that outputs are "
                      "not part of the licensed Materials: users keep the rights to what they generate"),
    # Read 2026-09-28 (Extract): worldwide, royalty-free, commercial use allowed.
    "sam-license": ("Meta SAM License: commercial use allowed worldwide (EU included); redistributing "
                    "the weights requires shipping the license; usual trade-control / weapons exclusions"),
    # Krea 2 model page, "License and Outputs".
    "krea-2-community-license": ("Krea claims no copyright or IP over generated content; users are "
                                 "responsible for their outputs (model use itself: Krea 2 Community License)"),
}
NON_COMMERCIAL_HINTS =("non-commercial", "noncommercial", "-nc", "nc-", "flux-1-dev", "research")

_cache: dict[str, object] = {}


def _get_json(url: str, token: str = "") -> object:
    if url in _cache:
        return _cache[url]
    # Polite pace: one pass is ~50 API reads (cached per repo), well inside
    # both hosts' anonymous limits; the pause keeps a daily run unremarkable.
    time.sleep(0.5)
    headers = {"User-Agent": "NomadStudio-catalog-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as r:
            data = json.loads(r.read())
    except HTTPError as exc:
        data = {"_error": exc.code}
    except Exception as exc:  # noqa: BLE001 — network trouble is reported, not fatal
        data = {"_error": str(exc)}
    _cache[url] = data
    return data


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def audit_hf(url: str, name: str, token: str) -> dict:
    m = _HF_RE.match(url)
    if not m:
        return {"host": "huggingface", "flags": ["unparsed Hugging Face url"]}
    repo, _rev, path = m.group(1), m.group(2), unquote(m.group(3))
    info = _get_json(f"https://huggingface.co/api/models/{repo}", token)
    out = {"host": "huggingface", "repo": repo, "page": f"https://huggingface.co/{repo}", "flags": []}
    if not isinstance(info, dict) or info.get("_error"):
        out["flags"].append(f"model info unavailable ({(info or {}).get('_error')})")
        return out
    card = info.get("cardData") or {}
    author = str(info.get("author") or repo.split("/")[0])
    license_id = str(card.get("license") or "").lower() or next(
        (t.split(":", 1)[1] for t in info.get("tags") or [] if str(t).startswith("license:")), "")
    base = [str(b) for b in _as_list(card.get("base_model"))]
    out.update({
        "author": author,
        "license": license_id or None,
        "license_name": card.get("license_name"),
        "license_link": card.get("license_link"),
        "gated": info.get("gated") or False,
        "base_model": base,
        "downloads": info.get("downloads"),
        "last_modified": str(info.get("lastModified") or "")[:10],
    })
    if author not in FIRST_PARTY:
        origin = f" (base: {', '.join(base)})" if base else ""
        out["flags"].append(f"third-party upload by {author}{origin}")
    accepted = ACCEPTED_LICENSES.get(str(card.get("license_name") or license_id).lower())
    if accepted:
        out["note"] = accepted
    elif not license_id:
        out["flags"].append("no license declared")
    elif license_id == "other":
        out["flags"].append(f"custom license: {card.get('license_name') or '?'} {card.get('license_link') or ''}".strip())
    elif any(h in license_id for h in NON_COMMERCIAL_HINTS):
        out["flags"].append(f"non-commercial license: {license_id}")
    elif license_id not in OPEN_LICENSES:
        out["flags"].append(f"license to read: {license_id}")
    if out["gated"]:
        out["flags"].append(f"gated ({out['gated']}): users must accept terms and set an HF token")
    file_name = path.rsplit("/", 1)[-1]
    if file_name != name:
        out["flags"].append(f"saved under another name: host file is {file_name}")
    return out


def audit_civitai(url: str, name: str) -> dict:
    m = _CIVITAI_RE.search(url)
    out = {"host": "civitai", "flags": []}
    if not m:
        out["flags"].append("unparsed CivitAI url")
        return out
    version = _get_json(f"https://civitai.com/api/v1/model-versions/{m.group(1)}")
    if not isinstance(version, dict) or version.get("_error"):
        out["flags"].append(f"model version unavailable ({(version or {}).get('_error')})")
        return out
    model_id = version.get("modelId")
    model = _get_json(f"https://civitai.com/api/v1/models/{model_id}") if model_id else {}
    model = model if isinstance(model, dict) else {}
    commercial = model.get("allowCommercialUse")
    commercial = commercial if isinstance(commercial, list) else _as_list(commercial)
    out.update({
        "page": f"https://civitai.com/models/{model_id}?modelVersionId={m.group(1)}",
        "model": model.get("name") or (version.get("model") or {}).get("name"),
        "author": (model.get("creator") or {}).get("username"),
        "base_model": [version.get("baseModel")] if version.get("baseModel") else [],
        "allow_commercial": commercial,
        "allow_derivatives": model.get("allowDerivatives"),
        "allow_different_license": model.get("allowDifferentLicense"),
        "allow_no_credit": model.get("allowNoCredit"),
        "nsfw": model.get("nsfw"),
    })
    out["flags"].append(f"third-party upload by {out['author'] or '?'} (CivitAI)")
    if model.get("_error"):
        out["flags"].append(f"model info unavailable ({model.get('_error')})")
    else:
        if not any(str(c).lower() in ("image", "sell", "rent", "rentcivit") for c in commercial):
            out["flags"].append(f"commercial use not allowed ({commercial or 'None'})")
        if out["allow_no_credit"] is False:
            out["flags"].append("requires crediting the creator")
        if model.get("nsfw"):
            out["flags"].append("marked NSFW on CivitAI")
    return out


def audit_model(m: dict, token: str) -> dict:
    name = (m.get("names") or ["?"])[0]
    results = []
    for s in m.get("sources") or []:
        url = str(s.get("url") or "")
        if "huggingface.co" in url:
            results.append(audit_hf(url, name, token))
        elif "civitai.com" in url:
            results.append(audit_civitai(url, name))
        else:
            results.append({"host": s.get("host") or "?", "flags": ["unknown host: nothing to check"], "page": url})
    return {"name": name, "folder": m.get("folder"), "size": m.get("size"), "sources": results}


def _size(n) -> str:
    n = float(n or 0)
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def to_markdown(rows: list[dict]) -> str:
    flagged = [r for r in rows if any(s["flags"] for s in r["sources"])]
    clean = [r for r in rows if r not in flagged]
    lines = [f"# Models catalog audit — {len(rows)} files, {len(flagged)} to look at\n"]
    by_flag: dict[str, int] = {}
    for r in flagged:
        for s in r["sources"]:
            for f in s["flags"]:
                key = f.split(":")[0].split(" (")[0].split(" by ")[0]
                by_flag[key] = by_flag.get(key, 0) + 1
    lines.append("| Flag | Files |\n|---|---|")
    lines += [f"| {k} | {v} |" for k, v in sorted(by_flag.items(), key=lambda kv: -kv[1])]
    lines.append("\n## To look at\n")
    for r in sorted(flagged, key=lambda r: r["name"].lower()):
        for s in r["sources"]:
            lic = s.get("license") or ("CivitAI permissions" if s["host"] == "civitai" else "—")
            lines.append(f"- **{r['name']}** · {r['folder']} · {_size(r['size'])} · [{s.get('repo') or s.get('model') or 'page'}]({s.get('page', '')}) · license: {lic}")
            for f in s["flags"]:
                lines.append(f"  - {f}")
    lines.append(f"\n## No flags ({len(clean)})\n")
    for r in sorted(clean, key=lambda r: r["name"].lower()):
        s = r["sources"][0]
        note = f" — accepted: {s['note']}" if s.get("note") else ""
        lines.append(f"- {r['name']} — {s.get('repo')} · {s.get('license_name') or s.get('license')}{note}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("catalog", nargs="?", default=str(DEFAULT))
    ap.add_argument("--md", help="write a Markdown report here")
    ap.add_argument("--json", help="write the raw results here")
    ap.add_argument("--hf-token", default="")
    args = ap.parse_args()
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda m: audit_model(m, args.hf_token), catalog.get("models") or []))
    report = to_markdown(rows)
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8", newline="\n")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print(report.split("\n## To look at")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
