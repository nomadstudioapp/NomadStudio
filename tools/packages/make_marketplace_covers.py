"""App-only Marketplace covers, for the products whose shop cover shows a price
(the app never does). Same collage + title band as the Ko-fi images
(NomadStudioPacks/kofi/tools/make_kofi_images.py), without the price.

    python tools/packages/make_marketplace_covers.py

Writes tools/packages/marketplace_covers/<id>.jpg; build_marketplace_catalog.py
uses these before the website's covers.
"""
import json
import sys
from pathlib import Path

from PIL import Image

KOFI_TOOLS = Path(r"D:\NOMADSTUDIO_PACKS\kofi\tools")
sys.path.insert(0, str(KOFI_TOOLS))
import make_kofi_images as k  # noqa: E402

OUT = Path(__file__).resolve().parent / "marketplace_covers"


def studio_pro(p: dict, by_id: dict) -> Image.Image:
    # As make_kofi_images.make_bundle, minus the price in the subtitle.
    rows = -(-len(p["includes"]) // 3)  # 3 per row, no empty row
    cw, ch = (k.SIZE - 12) // 3, (k.SIZE - 6 * (rows - 1)) // rows
    tiles = [k.fit(Image.open(k.WEB_COVERS / by_id[i]["cover"]), cw, ch, (1.0, 0.6)) for i in p["includes"]]
    cover = k.collage(tiles, 3, rows)
    k.title_band(cover, p["name"], f"{len(p['includes'])} packs")
    return cover


def main() -> None:
    listings = json.loads(k.LISTINGS.read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in listings["products"]}
    OUT.mkdir(exist_ok=True)
    p = by_id["bundle.studio-pro"]
    dest = OUT / f"{p['id']}.jpg"
    studio_pro(p, by_id).convert("RGB").save(dest, "JPEG", quality=90)
    print(dest)


if __name__ == "__main__":
    main()
