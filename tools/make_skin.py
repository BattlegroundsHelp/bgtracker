#!/usr/bin/env python3
"""Turn the raw generated HUD art into the skin the overlay actually loads.

    python tools/make_skin.py

Reads the untracked ``assets_hud_raw/`` folder (the images exactly as the
generator saved them, magenta backgrounds and all) and writes ``data/skin/``
(tracked, shipped - NOT ``assets/``, which is the gitignored card-art cache):
magenta cut to alpha, cropped to content, downscaled to sane working sizes,
and scrubbed of the one colour no shipped pixel may be.

Why the magenta cut happens HERE and not at load time: the cut needs a
feathered chroma key plus a despill pass over multi-megapixel images, which is
a second of work per asset - fine once on a dev machine, absurd on every
overlay start. ``ui/skin.py`` loads clean RGBA and only ever resizes.

The one hard rule, from ui/base.py: #000001 is the overlay's transparency
key, so a skin pixel that lands on it exactly would be a click-through HOLE
in the middle of a panel. Every output pixel is checked and nudged to
#000002. That check is here, at the choke point every shipped pixel passes
through, rather than trusted to the art.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets_hud_raw"
OUT = ROOT / "data" / "skin"


def cut_magenta(im: Image.Image) -> Image.Image:
    """Chroma-key the pure-magenta background to alpha, with a despill.

    The key is measured, not exact: these come back through a JPEG encoder,
    so the "pure #FF00FF" the prompt asked for lands anywhere around
    (253..255, 0..5, 247..254). Keying on magenta-ness - how far both red and
    blue sit above green - survives that, and a two-band ramp keeps the edge
    feathered instead of stair-stepped.
    """
    im = im.convert("RGB")
    px = im.load()
    w, h = im.size
    out = Image.new("RGBA", (w, h))
    po = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            m = min(r, b) - g          # magenta-ness: high on the backdrop
            if m >= 110:
                a = 0
            elif m <= 60:
                a = 255
            else:
                a = int(255 * (110 - m) / 50)
            if m > 0:
                # Despill by SUBTRACTING the excess, on every kept pixel. The
                # first bake clamped instead (min(r, g+70)) and only on the
                # feathered ramp, and both halves showed on screen: clamped
                # backdrop becomes dark PURPLE rather than neutral, and the
                # full-alpha pixels one step inside the silhouette kept their
                # glow - a purple hairline under every plate. Subtraction
                # sends backdrop toward neutral dark and is a no-op on the
                # palette (gold, wood, parchment all have m < 0).
                r -= m
                b -= m
            po[x, y] = (r, g, b, a)
    # One pixel of erosion: the outermost kept pixels are the ones the JPEG
    # encoder mixed with the backdrop, and no per-pixel arithmetic can unmix
    # them. Dropping that single ring is invisible at these sizes and takes
    # the last of the fringe with it.
    a = out.getchannel("A").filter(ImageFilter.MinFilter(3))
    out.putalpha(a)
    return out


def scrub_key(im: Image.Image) -> Image.Image:
    """No shipped pixel may be exactly #000001 - that is the click hole."""
    px = im.load()
    w, h = im.size
    bands = len(im.getbands())
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[0] == 0 and p[1] == 0 and p[2] == 1:
                px[x, y] = (0, 0, 2) + tuple(p[3:]) if bands > 3 else (0, 0, 2)
    return im


def crop_content(im: Image.Image, pad: int = 2) -> Image.Image:
    """Crop to the alpha bounding box, keeping a hair of feathered edge."""
    bbox = im.getchannel("A").getbbox()
    if bbox is None:
        sys.exit("cut produced an empty image - the key ate the asset")
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(im.width, x2 + pad), min(im.height, y2 + pad)
    return im.crop((x1, y1, x2, y2))


def shrink(im: Image.Image, target_w: int) -> Image.Image:
    if im.width <= target_w:
        return im
    return im.resize((target_w, round(im.height * target_w / im.width)),
                     Image.LANCZOS)


def save(im: Image.Image, name: str):
    p = OUT / name
    scrub_key(im).save(p)
    print(f"  {name:18s} {im.width}x{im.height}  {p.stat().st_size // 1024} KB")


def main() -> int:
    if not RAW.is_dir():
        sys.exit(f"no {RAW} - generate the assets first (HUD_GENERATION_BRIEF.md)")
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"writing {OUT}")

    # Opaque surfaces: no key to cut, just size and scrub.
    save(shrink(Image.open(RAW / "panel_wood.jpg").convert("RGB"), 1024),
         "panel_wood.png")
    save(shrink(Image.open(RAW / "settings_bg.jpg").convert("RGB"), 848),
         "settings_bg.png")

    # Keyed assets: cut, crop, size. Working sizes are chosen so the LARGEST
    # thing ever painted from each (a 4K panel at UI scale 3) still downscales
    # rather than stretches.
    for raw, name, target in [
        ("frame_gold.jpg", "frame_gold.png", 512),
        ("header_bar.jpg", "header_bar.png", 1024),
        ("plate.jpg", "plate.png", 1024),
        ("plate_best.jpg", "plate_best.png", 1024),
        ("artframe.jpg", "artframe.png", 256),
        ("chip_on.jpg", "chip_on.png", 256),
        ("chip_off.jpg", "chip_off.png", 256),
        ("corner.jpg", "corner.png", 256),
        ("app_icon.jpg", "app_icon.png", 512),
    ]:
        im = crop_content(cut_magenta(Image.open(RAW / raw)))
        save(shrink(im, target), name)

    # The exe / taskbar icon, straight from the cut shield.
    icon = Image.open(OUT / "app_icon.png")
    icon.save(ROOT / "data" / "app.ico",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32),
                     (16, 16)])
    print("  app.ico            multi-size")
    return 0


if __name__ == "__main__":
    sys.exit(main())
