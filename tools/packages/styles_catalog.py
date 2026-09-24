"""Style packs catalog — the curated source of every style pack.

The catalog lives in styles_catalog/: packs.json (which packs exist),
categories.json (translations of every category segment) and one JSON per
pack with its styles. It was curated from OPENHIKER's app/data/styles.json:
each entry's `src` lists the OPENHIKER style ids it came from (several when
duplicates were merged) and the first one gives its preview image.

    python tools/packages/styles_catalog.py --source D:\\OPENHIKER --check
        Validate the catalog: every OPENHIKER style accounted for, no banned
        content words, no trademarks outside the fan pack, clean prefix/suffix
        formatting, translations complete.

build_packages.py --style-packs uses load_catalog() and preview_webp() to
build the zips.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

CATALOG_DIR = Path(__file__).resolve().parent / "styles_catalog"
LANGS = ("en", "es", "zh", "ko")
PREVIEW_MODEL_DIR = "model_imp-72b6ba69"  # Krea 2 Turbo previews in OPENHIKER
PREVIEW_WIDTH = 512

# OPENHIKER styles deliberately left out of every pack.
DROPPED = {
    33: "Empty style (no prefix or suffix).",
    95: "'Enhance' is a quality booster, not a style.",
    104: "'Texture' is not a style.",
}

# Content policy: at most 16+, no nudity, no gore.
BANNED_WORDS = [
    "nude", "nudity", "naked", "nsfw", "sexy", "sexual", "sensual", "erotic", "seductive",
    "lingerie", "bikini", "topless", "cleavage", "busty", "provocative", "revealing",
    "lewd", "fetish", "skimpy", "underwear", "nipple", "nipples", "breast", "breasts",
    "voluptuous", "blood", "bloody", "gore", "gory", "corpse", "corpses", "dismember",
    "dismembered", "decapitated", "violent", "violence", "brutal", "grotesque", "insanity",
    "smoking", "cigarette",
]
# "no gore" / "without gore" state the policy; they don't ask for gore.
NEGATED = re.compile(r"\b(?:no|without)\s+(?:gore|blood|nudity)\b", re.I)

# Names of franchises, studios, brands and artists. Allowed only in the
# free fan pack that is distributed on CivitAI.
TRADEMARKS = [
    "ghibli", "miyazaki", "shinkai", "ufotable", "marvel", "dc comics", "batman", "superman",
    "spider-man", "spiderman", "x-men", "deadpool", "pokemon", "pokémon", "mario", "zelda",
    "minecraft", "gta", "street fighter", "bubble bobble", "kodak", "kodachrome",
    "technicolor", "lomography", "iphone", "play-doh", "octane", "stability ai",
    "warhammer", "rutkowski", "loish", "moebius", "syd mead", "ansel adams", "akira",
    "ec comics", "lovecraft", "cinemascope", "disney", "pixar", "unreal engine",
    "image comics", "dark horse", "frank miller", "jim lee", "mcfarlane",
]
JUNK = ["masterpiece", "best quality", "amazing quality", "score_", "[subject]"]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog() -> dict[str, Any]:
    packs = load_json(CATALOG_DIR / "packs.json")["packs"]
    for pack in packs:
        # A pack is one or more theme files, concatenated in order.
        pack["styles"] = [e for rel in pack["files"] for e in load_json(CATALOG_DIR / rel)]
    categories = {k: v for k, v in load_json(CATALOG_DIR / "categories.json").items() if not k.startswith("_")}
    return {"packs": packs, "categories": categories}


def category_texts(category: str, categories: dict[str, dict[str, str]]) -> dict[str, str]:
    """{'en': 'Photography/Classic', 'es': 'Fotografía/Clásica', ...}"""
    segments = category.split("/")
    out = {"en": category}
    for lang in LANGS[1:]:
        out[lang] = "/".join(categories.get(seg, {}).get(lang, seg) for seg in segments)
    return out


def preview_path(source: Path, entry: dict[str, Any]) -> Path:
    return source / "app" / "images" / "styles" / PREVIEW_MODEL_DIR / f"{entry['src'][0]}.png"


def preview_webp(source: Path, entry: dict[str, Any], width: int = PREVIEW_WIDTH, quality: int = 82) -> bytes | None:
    """The entry's preview, downscaled to *width* px as WebP. None when the
    source style never had a preview."""
    from PIL import Image

    path = preview_path(source, entry)
    if not path.is_file():
        return None
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def _words(text: str) -> str:
    return NEGATED.sub(" ", text.lower())


def check(catalog: dict[str, Any], source: Path | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    categories = catalog["categories"]
    seen_src: dict[int, str] = {}
    keys: dict[str, str] = {}
    banned = re.compile(r"\b(?:" + "|".join(map(re.escape, BANNED_WORDS)) + r")\b", re.I)

    for pack in catalog["packs"]:
        pid = pack["id"]
        fan = pack["tier"] == "free-civitai"
        for lang in LANGS:
            if not pack["name"].get(lang) or not pack["summary"].get(lang):
                errors.append(f"{pid}: pack name/summary missing '{lang}'")
        for e in pack["styles"]:
            where = f"{pid}/{e.get('key')}"
            if e["key"] in keys:
                errors.append(f"{where}: duplicate key (also in {keys[e['key']]})")
            keys[e["key"]] = pid
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", e["key"]):
                errors.append(f"{where}: key must be a lowercase slug")
            for sid in e["src"]:
                if sid in seen_src:
                    errors.append(f"{where}: source #{sid} already used by {seen_src[sid]}")
                seen_src[sid] = where
            names = e["name"]
            for lang in (LANGS if not fan else ("en",)):
                if not names.get(lang):
                    errors.append(f"{where}: name missing '{lang}'")
            for seg in e["category"].split("/"):
                if seg not in categories:
                    errors.append(f"{where}: category segment '{seg}' has no translations")
            if not (e.get("prefix") or e.get("suffix")):
                errors.append(f"{where}: needs a prefix or a suffix")
            if not e.get("prompt"):
                errors.append(f"{where}: needs an example prompt")
            for field in ("prefix", "suffix", "prompt"):
                text = e.get(field) or ""
                low = text.lower()
                if text != text.strip() or text.startswith(",") or text.endswith(","):
                    errors.append(f"{where}: {field} has stray spaces or a leading/trailing comma")
                if ",," in text.replace(" ", "") or ";" in text or "(" in text or "\n" in text:
                    errors.append(f"{where}: {field} has double commas, semicolons, parentheses or newlines")
                for junk in JUNK:
                    if junk in low:
                        errors.append(f"{where}: {field} contains '{junk}'")
                hit = banned.search(_words(text))
                # "guts" is a character name in the fan pack, not a banned word.
                if hit:
                    errors.append(f"{where}: {field} contains banned word '{hit.group(0)}'")
                if not fan:
                    for tm in TRADEMARKS:
                        if re.search(r"(?<![a-z])" + re.escape(tm) + r"(?![a-z])", low):
                            errors.append(f"{where}: {field} mentions trademark/artist '{tm}' outside the fan pack")
            if not fan:
                for tm in TRADEMARKS:
                    if re.search(r"(?<![a-z])" + re.escape(tm) + r"(?![a-z])", names["en"].lower()):
                        errors.append(f"{where}: name mentions trademark/artist '{tm}' outside the fan pack")
            words = len(re.findall(r"\w+", f"{e.get('prefix', '')} {e.get('suffix', '')}"))
            if words > 70:
                warnings.append(f"{where}: prefix+suffix is long ({words} words)")
            if source and not preview_path(source, e).is_file():
                warnings.append(f"{where}: no source preview (#{e['src'][0]})")

    if source:
        styles = load_json(source / "app" / "data" / "styles.json")
        all_ids = {int(s["id"]) for s in styles}
        missing = sorted(all_ids - set(seen_src) - set(DROPPED))
        unknown = sorted(set(seen_src) - all_ids)
        if missing:
            errors.append(f"OPENHIKER styles not in any pack: {missing}")
        if unknown:
            errors.append(f"catalog references unknown OPENHIKER ids: {unknown}")
    return errors, warnings


def summary(catalog: dict[str, Any]) -> str:
    lines = []
    total = 0
    regen = 0
    for pack in catalog["packs"]:
        n = len(pack["styles"])
        r = sum(1 for e in pack["styles"] if e.get("review", {}).get("preview") == "regen")
        total += n
        regen += r
        lines.append(f"  {pack['id']:<34} {pack['tier']:<13} {n:>4} styles  ({r} previews to regenerate)")
    lines.append(f"  {'total':<48} {total:>4} styles  ({regen} previews to regenerate)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="OPENHIKER checkout (read-only) — enables source/preview checks")
    ap.add_argument("--check", action="store_true", help="validate the catalog")
    args = ap.parse_args()
    catalog = load_catalog()
    print(summary(catalog))
    if args.check:
        errors, warnings = check(catalog, args.source)
        for w in warnings:
            print("warning:", w)
        for e in errors:
            print("ERROR:", e)
        print(f"{len(errors)} errors, {len(warnings)} warnings")
        return 1 if errors else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
