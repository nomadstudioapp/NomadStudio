"""Validate the models catalog (PACKAGE_FORMAT.md §8.2.2).

Checks the schema and, with --online, that every source still answers and
serves the file declared, without downloading anything: Hugging Face's API
listing gives each file's SHA-256 (`lfs.oid`) and size, CivitAI's model-version
API gives its SHA-256. A publisher re-uploading a file under the same name
shows up as a new hash; --update records it (old hash → previous_sha256).

Usage:
    python tools/packages/check_models_catalog.py [catalog.json] [--online [--update]] [--hf-token hf_…]
Exit code 1 if anything is wrong — usable as the Packs repo's GitHub Action.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT = Path(__file__).resolve().parents[2] / "app" / "static" / "data" / "models_catalog.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def check_schema(catalog: dict) -> list[str]:
    errors = []
    if not isinstance(catalog.get("models"), list):
        return ["\"models\" must be a list"]
    seen_sha, seen_names = set(), {}
    for i, m in enumerate(catalog["models"]):
        where = f"models[{i}] {(m.get('names') or ['?'])[0]}"
        if not SHA_RE.match(str(m.get("sha256", ""))):
            errors.append(f"{where}: sha256 must be 64 lowercase hex")
        elif m["sha256"] in seen_sha:
            errors.append(f"{where}: duplicated sha256")
        seen_sha.add(m.get("sha256"))
        if not (isinstance(m.get("size"), int) and m["size"] > 0):
            errors.append(f"{where}: size must be a positive integer")
        if not m.get("names"):
            errors.append(f"{where}: needs at least one name")
        for n in m.get("names") or []:
            if n.lower() in seen_names:
                errors.append(f"{where}: name {n} also in {seen_names[n.lower()]}")
            seen_names[n.lower()] = where
        prev = m.get("previous_sha256", [])
        if not isinstance(prev, list) or not all(SHA_RE.match(str(p)) for p in prev):
            errors.append(f"{where}: previous_sha256 must be a list of 64-hex hashes")
        if not str(m.get("folder", "")).strip():
            errors.append(f"{where}: folder is required")
        if not m.get("sources"):
            errors.append(f"{where}: needs at least one source")
        for s in m.get("sources") or []:
            if not str(s.get("url", "")).startswith("https://"):
                errors.append(f"{where}: source url must be https://")
    return errors


_HF_RE = re.compile(r"^https://huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/([^?]+)")
_CIVITAI_RE = re.compile(r"civitai\.com/api/download/models/(\d+)(?:\?fileId=(\d+))?")
_tree_cache: dict[tuple, list] = {}


def _get_json(url: str, token: str = "") -> object:
    headers = {"User-Agent": "NomadStudio-catalog-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as r:
        return json.loads(r.read())


def remote_identity(url: str, token: str = "") -> tuple[int | str, str | None, int | None]:
    """(status, sha256, size) of the file behind a download address, without
    downloading it. Hugging Face: from the repo's API listing — its `lfs.oid`
    IS the SHA-256 (the ETag of the file itself is not: files on HF's Xet
    storage carry a Xet hash there). CivitAI: from the model version's file
    list. Anything else: reachability only."""
    from urllib.parse import unquote

    hf = _HF_RE.match(url)
    if hf:
        repo, rev, path = hf.group(1), hf.group(2), unquote(hf.group(3))
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        key = (repo, rev, folder)
        try:
            if key not in _tree_cache:
                api = f"https://huggingface.co/api/models/{repo}/tree/{rev}" + (f"/{folder}" if folder else "")
                _tree_cache[key] = _get_json(api, token)
            entry = next((e for e in _tree_cache[key] if e.get("path") == path), None)
        except Exception as exc:  # noqa: BLE001
            return getattr(exc, "code", "ERR"), None, None
        if not entry:
            return 404, None, None
        lfs = entry.get("lfs") or {}
        oid = str(lfs.get("oid") or "").lower()
        # A gated repo lists its files with the hash masked ("****…").
        return 200, oid if SHA_RE.match(oid) else None, lfs.get("size") or entry.get("size")
    cv = _CIVITAI_RE.search(url)
    if cv:
        try:
            version = _get_json(f"https://civitai.com/api/v1/model-versions/{cv.group(1)}")
        except Exception as exc:  # noqa: BLE001
            return getattr(exc, "code", "ERR"), None, None
        files = version.get("files") or []
        f = next((x for x in files if str(x.get("id")) == cv.group(2)), files[0] if len(files) == 1 else None)
        if not f:
            return 404, None, None
        sha = str((f.get("hashes") or {}).get("SHA256") or "").lower() or None
        return 200, sha, None  # CivitAI gives the size in KB, rounded: not usable
    try:
        with urlopen(Request(url, method="HEAD", headers={"User-Agent": "NomadStudio-catalog-check"}), timeout=30) as r:
            return r.status, None, None
    except Exception as exc:  # noqa: BLE001
        return getattr(exc, "code", "ERR"), None, None


def _head(url: str, token: str) -> tuple[int | str, str | None, int | None]:
    return remote_identity(url, token)


def check_online(catalog: dict, token: str, update: bool = False) -> tuple[list[str], list[str]]:
    """(errors, revisions). A revision is the FIRST source of an entry now
    serving another file: the publisher re-uploaded it under the same name
    (Comfy-Org revised several in 2026). With ``update`` the entry takes the
    new hash and size and keeps the old hash in previous_sha256, so packages
    built against the old one still find it."""
    jobs = [(m, i, s) for m in catalog["models"] for i, s in enumerate(m.get("sources") or [])]
    errors, revisions = [], []
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda job: _head(job[2]["url"], token), jobs))
    for (m, i, s), (status, sha, size) in zip(jobs, results):
        name = m["names"][0]
        if status in (401, 403) and s.get("gated") and not token:
            continue  # expected without a token
        if status != 200:
            errors.append(f"{name}: {s['url']} answered {status}")
        elif sha and sha != m["sha256"]:
            if i == 0 and update:
                m.setdefault("previous_sha256", [])
                if m["sha256"] not in m["previous_sha256"]:
                    m["previous_sha256"].append(m["sha256"])
                m["sha256"] = sha
                if size:
                    m["size"] = size
                revisions.append(f"{name}: revised upstream → catalog updated (sha256 {sha[:12]}…)")
            else:
                errors.append(f"{name}: {s['url']} now serves a different file (sha256 {sha[:12]}…)"
                              + (" — run with --update if this is a legitimate revision" if i == 0 else ""))
        elif size and size != m["size"]:
            errors.append(f"{name}: {s['url']} now serves {size} bytes, catalog says {m['size']}")
    return errors, revisions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("catalog", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--update", action="store_true",
                    help="with --online: record upstream revisions in the catalog (writes the file)")
    ap.add_argument("--hf-token", default="")
    args = ap.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    errors = check_schema(catalog)
    revisions: list[str] = []
    if args.online and not errors:
        more, revisions = check_online(catalog, args.hf_token, args.update)
        errors += more
    if revisions:
        args.catalog.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in revisions:
        print("↻", r)
    for e in errors:
        print("✗", e)
    print(f"{len(catalog.get('models', []))} models · {'OK' if not errors else f'{len(errors)} problems'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
