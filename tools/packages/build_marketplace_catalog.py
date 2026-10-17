"""Build the in-app Marketplace catalogue (app/static/marketplace/) from the Ko-fi shop.

    python tools/packages/build_marketplace_catalog.py

Source of truth: NomadStudioPacks/kofi/listings.json (one entry per Ko-fi
product). Every product's zip is the very file that was attached on Ko-fi, so
its sha256 is what lets the app tell "official Nomad Studio pack" apart from
any other zip at install time (packages_routes.inspect_package). Run it again
whenever a pack is rebuilt and re-uploaded, before each release.

Writes app/static/marketplace/catalog.json and covers/<id>.webp (640 px).
Products without a kofi_url (not on Ko-fi yet) are left out.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
PACKS = Path(r"D:\NOMADSTUDIO_PACKS")
LISTINGS = PACKS / "kofi" / "listings.json"
# Where the zips attached on Ko-fi live: flow packs built here, templates and
# styles built in NomadStudioPacks, the bundle in kofi/bundles.
ZIP_DIRS = [REPO / "dist" / "optional-packages", PACKS / "dist", PACKS / "kofi", REPO / "dist" / "packages"]
WEB_COVERS = Path(r"D:\NOMAD_STUDIO_MARKETING\assets\marketplace")
APP_COVERS = Path(__file__).resolve().parent / "marketplace_covers"
OUT = REPO / "app" / "static" / "marketplace"
COVER_WIDTH = 640

# Which hub catalogue a pack belongs to, by id; the bundle shows in all.
TAB_BY_PREFIX = [("nomad.refine-", "refine"), ("nomad.mix-", "mix"),
                 ("nomad.templates-", "create"), ("nomad.styles-", "create")]
TAB_OVERRIDES: dict[str, list[str]] = {}

# The app shows no prices (it says "Get it", like the website, and Ko-fi has
# the price). The shop texts that mention one get a price-free version here.
DESCRIPTION_OVERRIDES: dict[str, dict[str, str]] = {
    "bundle.studio-pro": {
        "en": "Every pack to create and edit in one go: the nine packs of More ways to create and edit, together.",
        "es": "Todos los packs para crear y editar de una vez: los nueve packs de Más formas de crear y editar, juntos.",
        "zh": "一次拥有全部创作与编辑内容包：“更多创作与编辑方式”中的九个内容包，合为一套。",
        "ko": "만들고 편집하는 모든 팩을 한 번에: '더 많은 제작·편집 방법'의 아홉 개 팩을 함께.",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_zip(rel: str) -> Path:
    for base in ZIP_DIRS:
        path = base / rel
        if path.is_file():
            return path
    raise SystemExit(f"zip not found for {rel} in {', '.join(map(str, ZIP_DIRS))}")


def tabs_for(pid: str, kind: str) -> list[str]:
    if pid in TAB_OVERRIDES:
        return TAB_OVERRIDES[pid]
    if kind == "bundle":
        return ["create", "refine", "mix"]
    for prefix, tab in TAB_BY_PREFIX:
        if pid.startswith(prefix):
            return [tab]
    raise SystemExit(f"no hub tab for {pid}: add it to TAB_OVERRIDES")


def contents_of(text: str) -> dict:
    """'21 flows' -> {"n": 21, "unit": "flows"}; the app translates the unit."""
    m = re.fullmatch(r"(\d+)\s+(\w+)", text.strip())
    if not m:
        raise SystemExit(f"unexpected contents: {text!r}")
    return {"n": int(m.group(1)), "unit": m.group(2)}


def inside_of(zf: zipfile.ZipFile, manifest: dict) -> dict:
    """What the side panel lists under "What's inside", in 4 languages:
    each flow (name + one line), the style categories (with how many), or the
    template themes."""
    contributes = manifest.get("contributes") or {}
    if contributes.get("flows"):
        items = []
        for rel in contributes["flows"]:
            flow = json.loads(zf.read(rel))
            card = flow.get("card") if isinstance(flow.get("card"), dict) else {}
            label = card.get("label") or {"en": flow.get("label", flow.get("id", ""))}
            desc = card.get("desc") or {"en": flow.get("card_desc", "")}
            items.append({"label": label, "desc": desc})
        return {"type": "flows", "items": items}
    if contributes.get("styles"):
        styles = json.loads(zf.read("data/styles.json"))
        groups: dict[str, dict] = {}
        for style in styles:
            cat = style.get("category") or {}
            # "Anime & Manga/Anime" -> the top-level category, "Anime & Manga".
            top = {lang: str(text).split("/")[0] for lang, text in cat.items()}
            key = top.get("en", "")
            groups.setdefault(key, {"name": top, "count": 0})["count"] += 1
        return {"type": "styles", "groups": list(groups.values())}
    if contributes.get("template_packs"):
        themes = json.loads(zf.read("data/template_packs.json"))
        return {"type": "themes", "items": [t.get("theme") or {"en": t.get("key", "")} for t in themes]}
    return {}


def write_cover(product: dict, dest: Path) -> None:
    # App-only covers first (make_marketplace_covers.py: the shop's own show a price).
    candidates = [APP_COVERS / f"{product['id']}.{ext}" for ext in ("webp", "jpg", "png")]
    if product.get("cover"):
        candidates.append(WEB_COVERS / product["cover"])
    candidates.append(WEB_COVERS / f"pack-{product['id'].removeprefix('nomad.').replace('.', '-')}.webp")
    if product.get("cover_jpg"):
        candidates.append(PACKS / "kofi" / product["cover_jpg"])
    candidates += [PACKS / "kofi" / rel for rel in product.get("images") or []]
    src = next((c for c in candidates if c.is_file()), None)
    if src is None:
        raise SystemExit(f"no cover for {product['id']}")
    img = Image.open(src).convert("RGB")
    if img.width > COVER_WIDTH:
        img = img.resize((COVER_WIDTH, round(img.height * COVER_WIDTH / img.width)), Image.LANCZOS)
    img.save(dest, "WEBP", quality=82, method=6)


def main() -> None:
    listings = json.loads(LISTINGS.read_text(encoding="utf-8"))
    (OUT / "covers").mkdir(parents=True, exist_ok=True)
    previous: dict[str, list[str]] = {}
    if (OUT / "catalog.json").is_file():
        for old in json.loads((OUT / "catalog.json").read_text(encoding="utf-8")).get("products", []):
            previous[old["id"]] = old.get("sha256") or []
    products = []
    for p in listings["products"]:
        if not p.get("kofi_url"):
            continue
        path = find_zip(p["zip"])
        data = path.read_bytes()
        entry = {
            "id": p["id"],
            "kind": p["kind"],
            "tabs": tabs_for(p["id"], p["kind"]),
            "kofi_url": p["kofi_url"],
            "contents": contents_of(p["contents"]),
            "description": DESCRIPTION_OVERRIDES.get(p["id"]) or p.get("description") or {},
            "cover": f"covers/{p['id']}.webp",
            "sha256": [sha256(data)],
        }
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if "manifest.json" in names:
                manifest = json.loads(zf.read("manifest.json"))
                name = manifest.get("name")
                entry["name"] = name if isinstance(name, dict) else {"en": str(name or p["name"])}
                entry["version"] = manifest.get("version")
                entry["inside"] = inside_of(zf, manifest)
            else:
                # A bundle: a zip of package zips. Each inner zip is official too,
                # since the app inspects (and checks) them one by one.
                # A brand name: the same in every language.
                entry["name"] = {lang: p["name"] for lang in ("en", "es", "zh", "ko")}
                entry["includes"] = p.get("includes") or []
                inner = [n for n in names if n.lower().endswith(".zip")]
                entry["sha256"] += [sha256(zf.read(n)) for n in inner]
        # Earlier uploads stay official: buyers keep the zip they downloaded,
        # and a rebuilt pack must not turn theirs into an "unofficial" one.
        entry["sha256"] += [h for h in previous.get(p["id"], []) if h not in entry["sha256"]]
        write_cover(p, OUT / entry["cover"])
        products.append(entry)
        print(f"{p['id']:38} {', '.join(entry['tabs']):18} {len(entry['sha256'])} hash")
    # The bundle first, then by tab and name, the order the hub shows them in.
    order = {"create": 0, "refine": 1, "mix": 2}
    products.sort(key=lambda e: (e["kind"] != "bundle", order[e["tabs"][0]], e["name"].get("en", "")))
    catalog = {
        "_about": "Generated by tools/packages/build_marketplace_catalog.py from NomadStudioPacks/kofi/listings.json. Do not edit by hand.",
        "shop_url": listings.get("shop"),
        "products": products,
    }
    (OUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in (OUT / "covers").iterdir()) / 1024 / 1024
    print(f"{len(products)} products -> {OUT / 'catalog.json'} · covers {size:.1f} MB")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
