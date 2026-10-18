"""Server-side image persistence helpers.

PNG tEXt chunk layout (per spec):
    4B  chunk data length (big-endian uint32)
    4B  chunk type  = b'tEXt'
    NB  keyword \\x00 value   (both latin-1/UTF-8; keyword ≤ 79 chars)
    4B  CRC-32 of (type bytes + data bytes)

tEXt chunks are inserted immediately before the IEND chunk so that the
resulting file is still a valid PNG understood by every viewer.
"""

from __future__ import annotations

import json
import logging
import struct
import zlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keyword prefix used for every tEXt entry written/read by this module.
_KW_PREFIX = "oj:"

# PNG 8-byte file signature.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def read_png_dimensions(png_bytes: bytes) -> tuple[int, int] | tuple[None, None]:
    """Return (width, height) from the PNG IHDR chunk, or (None, None) if unreadable.

    PNG layout: 8-byte signature + IHDR chunk.
    IHDR data starts at byte 16: 4B width (big-endian), 4B height (big-endian).
    """
    if len(png_bytes) < 24 or not png_bytes.startswith(_PNG_SIG):
        return None, None
    try:
        width = struct.unpack(">I", png_bytes[16:20])[0]
        height = struct.unpack(">I", png_bytes[20:24])[0]
        return width, height
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Low-level PNG tEXt helpers
# ---------------------------------------------------------------------------


def _make_text_chunk(keyword: str, value: str) -> bytes:
    """Return raw bytes for a single PNG tEXt chunk."""
    data = keyword.encode("latin-1") + b"\x00" + value.encode("utf-8")
    length = struct.pack(">I", len(data))
    chunk_type = b"tEXt"
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def write_png_text_chunks(png_bytes: bytes, metadata: dict[str, str]) -> bytes:
    """Embed *metadata* as tEXt chunks in *png_bytes*, returning the modified PNG.

    Keys that don't already start with ``oj:`` have the prefix prepended.
    Chunks are inserted immediately before the IEND chunk.
    If *png_bytes* is not a valid PNG the original bytes are returned unchanged.
    """
    if not png_bytes.startswith(_PNG_SIG):
        return png_bytes

    # Locate the IEND chunk.
    pos = 8
    iend_pos = -1
    while pos + 8 <= len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        if chunk_type == b"IEND":
            iend_pos = pos
            break
        pos += 12 + chunk_len  # 4 length + 4 type + N data + 4 CRC

    if iend_pos == -1:
        return png_bytes  # malformed — don't corrupt the file

    extra = b""
    for key, val in metadata.items():
        kw = key if key.startswith(_KW_PREFIX) else (_KW_PREFIX + key)
        extra += _make_text_chunk(kw, str(val))

    return png_bytes[:iend_pos] + extra + png_bytes[iend_pos:]


def _coerce_image_bytes_to_png(image_bytes: bytes) -> bytes:
    """Return PNG bytes, converting non-PNG input when possible."""
    if image_bytes.startswith(_PNG_SIG):
        return image_bytes
    try:
        from PIL import Image  # type: ignore

        with Image.open(io.BytesIO(image_bytes)) as im:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return image_bytes


def read_png_text_chunks(png_bytes: bytes) -> dict[str, str]:
    """Return a dict of all tEXt chunks whose keyword starts with ``oj:``.

    Strips the ``oj:`` prefix from returned keys.
    Returns an empty dict if the file is not PNG or has no matching chunks.
    """
    if not png_bytes.startswith(_PNG_SIG):
        return {}

    result: dict[str, str] = {}
    pos = 8
    while pos + 8 <= len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        if chunk_type == b"IEND":
            break
        if chunk_type == b"tEXt":
            data = png_bytes[pos + 8 : pos + 8 + chunk_len]
            if b"\x00" in data:
                sep = data.index(b"\x00")
                kw = data[:sep].decode("latin-1", errors="replace")
                val = data[sep + 1 :].decode("utf-8", errors="replace")
                if kw.startswith(_KW_PREFIX):
                    result[kw[len(_KW_PREFIX) :]] = val
        pos += 12 + chunk_len

    return result


# ---------------------------------------------------------------------------
# Sidecar helpers (tags / favorite / diamond stored in PNG tEXt chunks)
# ---------------------------------------------------------------------------

# User-editable keys stored inside the PNG tEXt chunks (not in a .json file).
_SIDECAR_KEYS: frozenset[str] = frozenset({"tags", "favorite", "diamond", "tray"})


def _sidecar_path(image_path: Path) -> Path:
    """Legacy .json sidecar path — kept for backward-compat migration only."""
    return image_path.with_suffix(".json")


def _rewrite_png_text_chunks(png_bytes: bytes, updates: dict[str, str]) -> bytes:
    """Return *png_bytes* with tEXt chunks for *updates* keys replaced/added.

    Existing ``oj:<key>`` chunks whose key appears in *updates* are dropped;
    the new values are inserted just before IEND.  All other chunks are kept.
    """
    if not png_bytes.startswith(_PNG_SIG):
        return png_bytes

    kw_replace = {(k if k.startswith(_KW_PREFIX) else _KW_PREFIX + k) for k in updates}

    result = bytearray(png_bytes[:8])  # PNG signature
    pos = 8
    iend_raw = b""

    while pos + 8 <= len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        chunk_end = pos + 12 + chunk_len

        if chunk_type == b"IEND":
            iend_raw = png_bytes[pos:chunk_end]
            break

        if chunk_type == b"tEXt":
            data = png_bytes[pos + 8 : pos + 8 + chunk_len]
            if b"\x00" in data:
                sep = data.index(b"\x00")
                kw = data[:sep].decode("latin-1", errors="replace")
                if kw in kw_replace:
                    pos = chunk_end
                    continue  # drop — will be re-added below

        result += png_bytes[pos:chunk_end]
        pos = chunk_end

    for key, val in updates.items():
        kw = key if key.startswith(_KW_PREFIX) else (_KW_PREFIX + key)
        result += _make_text_chunk(kw, str(val))

    result += iend_raw or b"\x00\x00\x00\x00IEND\xaeB`\x82"
    return bytes(result)


def _sidecar_from_meta(meta: dict[str, str]) -> dict[str, Any]:
    """Convert raw tEXt meta values to properly-typed sidecar fields."""
    out: dict[str, Any] = {}
    for bool_key in ("diamond", "favorite", "tray"):
        if bool_key in meta:
            out[bool_key] = meta[bool_key].strip().lower() in ("true", "1", "yes", "on")
    if "tags" in meta:
        try:
            parsed = json.loads(meta["tags"])
            out["tags"] = parsed if isinstance(parsed, list) else []
        except Exception:
            out["tags"] = []
    return out


def read_sidecar(image_path: Path) -> dict[str, Any]:
    """Return sidecar data (tags/favorite/diamond) for *image_path*.

    PNG: reads from embedded tEXt chunks.
    Fallback: reads the legacy ``.json`` sidecar for backward compatibility.
    """
    if image_path.suffix.lower() == ".png":
        try:
            meta = read_png_text_chunks(image_path.read_bytes())
            if any(k in meta for k in _SIDECAR_KEYS):
                return _sidecar_from_meta(meta)
        except Exception:
            pass
    sp = _sidecar_path(image_path)
    try:
        return json.loads(sp.read_text("utf-8"))
    except Exception:
        return {}


def write_sidecar(image_path: Path, data: dict[str, Any]) -> None:
    """Write sidecar fields into the PNG tEXt chunks, rewriting the file in-place.

    Deletes the legacy ``.json`` sidecar afterwards if it exists.
    For non-PNG files the legacy ``.json`` sidecar is written instead.
    """
    if image_path.suffix.lower() != ".png":
        _sidecar_path(image_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
        )
        return

    updates: dict[str, str] = {}
    for k in _SIDECAR_KEYS:
        if k not in data:
            continue
        val = data[k]
        if k == "tags":
            updates[k] = json.dumps(
                val if isinstance(val, list) else [], ensure_ascii=False
            )
        else:
            updates[k] = "true" if val else "false"

    image_path.write_bytes(_rewrite_png_text_chunks(image_path.read_bytes(), updates))

    sp = _sidecar_path(image_path)
    if sp.is_file():
        try:
            sp.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_image(
    output_dir: str,
    filename: str,
    png_bytes: bytes,
    metadata: dict[str, str],
) -> Path:
    """Persist *png_bytes* with embedded tEXt metadata to *output_dir/filename*.

    The directory is created if it does not already exist.
    Returns the saved ``Path``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    png_compatible_bytes = _coerce_image_bytes_to_png(png_bytes)
    enhanced = write_png_text_chunks(png_compatible_bytes, metadata)
    dest = out / filename
    dest.write_bytes(enhanced)
    return dest


def list_image_files_sorted(output_dir: str) -> list[Path]:
    """Return image files sorted by mtime desc and filename desc for stable paging."""
    out = Path(output_dir)
    if not out.is_dir():
        return []

    exts = (".png", ".jpg", ".jpeg", ".webp")
    files = [p for p in out.iterdir() if p.suffix.lower() in exts]
    files.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    return files


def read_image_entry(image_path: Path) -> dict[str, Any] | None:
    """Return gallery payload for *image_path*, or None when unreadable."""
    try:
        mtime = image_path.stat().st_mtime
        created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        raw_bytes = image_path.read_bytes()
        is_png = image_path.suffix.lower() == ".png"
        meta = read_png_text_chunks(raw_bytes) if is_png else {}
        # Derive sidecar from the already-read meta to avoid re-reading the file.
        if is_png and any(k in meta for k in _SIDECAR_KEYS):
            sidecar = _sidecar_from_meta(meta)
        else:
            # Fallback: legacy .json sidecar (non-PNG or pre-migration PNG).
            sp = _sidecar_path(image_path)
            try:
                sidecar = json.loads(sp.read_text("utf-8"))
            except Exception:
                sidecar = {}

        # Fill in width/height from IHDR (PNG) or via Pillow (JPG/WEBP).
        if not meta.get("width") or not meta.get("height"):
            if image_path.suffix.lower() == ".png":
                w, h = read_png_dimensions(raw_bytes)
                if not w or not h:
                    try:
                        from PIL import Image as _PILImage  # type: ignore

                        with _PILImage.open(io.BytesIO(raw_bytes)) as _im:
                            w, h = _im.size
                    except Exception:
                        w, h = None, None
            else:
                try:
                    from PIL import Image as _PILImage  # type: ignore

                    with _PILImage.open(io.BytesIO(raw_bytes)) as _im:
                        w, h = _im.size
                except Exception:
                    w, h = None, None
            if w and h:
                meta.setdefault("width", str(w))
                meta.setdefault("height", str(h))

        return {
            "filename": image_path.name,
            "url": f"/api/images/{image_path.name}",
            "createdAt": created_at,
            "meta": meta,
            "sidecar": sidecar,
        }
    except Exception:
        logger.exception("Error reading image metadata for %s", image_path)
        return None


def list_images(output_dir: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return up to *limit* most-recently-modified image files (PNG/JPG/WEBP) from *output_dir*.

    Each item in the returned list::

        {
            "filename": "...",
            "url": "/api/images/<filename>",
            "createdAt": "2026-04-19T12:00:00Z",
            "meta": {<stripped oj: keys from tEXt chunks>},
            "sidecar": {<tags/favorite/diamond from PNG tEXt chunks>},
        }

    Returns an empty list if the directory does not exist.
    """
    files = list_image_files_sorted(output_dir)[:limit]

    result: list[dict[str, Any]] = []
    for p in files:
        entry = read_image_entry(p)
        if entry is None:
            continue
        result.append(entry)

    return result


_PIXEL_INDEX = ".pixel-hashes.json"


def pixel_hash(image_bytes: bytes) -> str:
    """Hash of the decoded pixels (+ size), not of the file: the same picture
    re-encoded or with other PNG metadata gets the same hash."""
    import hashlib
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        rgba = im.convert("RGBA")
        return hashlib.sha256(f"{rgba.size}".encode() + rgba.tobytes()).hexdigest()


def _load_pixel_index(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / _PIXEL_INDEX).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pixel_index(folder: Path, index: dict[str, Any]) -> None:
    try:
        (folder / _PIXEL_INDEX).write_text(json.dumps(index), encoding="utf-8")
    except Exception:
        pass


def _cached_pixel_hash(path: Path, index: dict[str, Any]) -> str | None:
    """pixel_hash of *path*, reusing *index* while the file's size and mtime
    are unchanged (decoding every image on each listing would be slow)."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = f"{st.st_size}:{st.st_mtime_ns}"
    cached = index.get(path.name)
    if isinstance(cached, dict) and cached.get("key") == key:
        return cached.get("hash")
    try:
        digest = pixel_hash(path.read_bytes())
    except Exception:
        return None
    index[path.name] = {"key": key, "hash": digest}
    return digest


def find_same_pixels(folder: str, image_bytes: bytes) -> Path | None:
    """An image already in *folder* with the same pixels as *image_bytes*."""
    out = Path(folder)
    if not out.is_dir():
        return None
    try:
        wanted = pixel_hash(image_bytes)
    except Exception:
        return None
    index = _load_pixel_index(out)
    found = None
    for p in list_image_files_sorted(folder):
        if _cached_pixel_hash(p, index) == wanted:
            found = p
            break
    _save_pixel_index(out, index)
    return found


def list_unique_images(output_dir: str, limit: int = 200) -> list[dict[str, Any]]:
    """Like list_images, but each picture once (newest copy): copies with
    the same pixels are skipped."""
    out = Path(output_dir)
    index = _load_pixel_index(out)
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for p in list_image_files_sorted(output_dir):
        digest = _cached_pixel_hash(p, index)
        if digest is not None:
            if digest in seen:
                continue
            seen.add(digest)
        entry = read_image_entry(p)
        if entry is not None:
            result.append(entry)
        if len(result) >= limit:
            break
    _save_pixel_index(out, index)
    return result


def serve_image(output_dir: str, filename: str) -> bytes | None:
    """Return raw bytes of *filename* inside *output_dir*, or ``None``.

    Path-traversal safe: rejects filenames containing directory separators or
    ``..`` components.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = Path(output_dir) / filename
    try:
        return p.read_bytes() if p.is_file() else None
    except Exception:
        return None


def resize_image_bytes(img_bytes: bytes, max_size: int = 400) -> tuple[bytes, str] | None:
    """Resize raw image *img_bytes* to fit within *max_size* px.

    Returns ``(bytes, content_type)``, re-encoding to JPEG when a resize
    actually happens. Returns the original bytes untouched (with a guessed
    content type) if the image is already small enough, or ``None`` if
    Pillow can't decode it.
    """
    try:
        from PIL import Image  # type: ignore
        import io

        with Image.open(io.BytesIO(img_bytes)) as im:
            w, h = im.size
            if w <= max_size and h <= max_size:
                content_type = "image/jpeg" if img_bytes[:2] == b"\xff\xd8" else "image/png"
                return img_bytes, content_type
            im.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=82, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.exception("Thumbnail resize failed")
        return None


def serve_image_thumb(
    output_dir: str, filename: str, max_size: int = 400
) -> bytes | None:
    """Return a JPEG thumbnail of *filename* resized to fit within *max_size* px.

    Returns ``None`` if the image is not found or Pillow is unavailable.
    Falls back to the original bytes only if the image is already smaller.
    Path-traversal safe.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = Path(output_dir) / filename
    if not p.is_file():
        return None
    try:
        from PIL import Image  # type: ignore
        import io

        with Image.open(p) as im:
            w, h = im.size
            if w <= max_size and h <= max_size:
                # Already small enough — serve original PNG bytes
                return p.read_bytes()
            im.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=82, optimize=True)
            return buf.getvalue()
    except Exception:
        logger.exception("Thumbnail generation failed for %s", filename)
        return None
