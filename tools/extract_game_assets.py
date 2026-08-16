#!/usr/bin/env python3
"""Extract the game's own HUD art from YOUR Hearthstone install.

    pip install UnityPy
    python tools/extract_game_assets.py

The normal game icons - the tavern-tier shield, the tier star, the
placement medals and the first-place crown - live in the game's Unity
bundles on this machine. This pulls them out of YOUR install into
assets/ui/game/ (gitignored, like every fetched asset): Blizzard's art
never enters the repository, it is extracted per-user from the copy of the
game they already own, exactly the way the established trackers do it.

What it produces:
    tier_1.png .. tier_7.png   the tavern-tier shield wearing its stars
    star.png                   the tier star on its own
    medal_1.png / _2.png / _3.png   gold / silver / bronze placement medals
    crown.png                  the leaderboard crown (finishing first)

Recipes are (bundle glob, texture name, crop) triples measured against the
current game build; a patch that moves a texture makes that ONE asset a
loud miss here, and the overlay's drawn fallback keeps working. The Unity
version is read from the game's own UnityPlayer.dll, so a game update does
not strand the parser on a stale hardcoded version.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bgtracker as bg  # noqa: E402  (the install locator lives there)
from paths import APP_DIR  # noqa: E402

OUT = APP_DIR / "assets" / "ui" / "game"


def game_dir() -> Path:
    """The install, from the same resolution chain the log reader trusts."""
    return bg._hs_logs_dir().parent


def unity_version(install: Path) -> str:
    """Read the engine version off UnityPlayer.dll - never hardcoded."""
    try:
        import ctypes

        path = str(install / "UnityPlayer.dll")
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf)
            val = ctypes.c_void_p()
            length = ctypes.c_uint()
            if ctypes.windll.version.VerQueryValueW(
                    buf, "\\StringFileInfo\\040904b0\\ProductVersion",
                    ctypes.byref(val), ctypes.byref(length)):
                s = ctypes.wstring_at(val.value, length.value).rstrip("\x00")
                m = re.match(r"[\d.]+[a-z]\d+", s)
                if m:
                    return m.group(0)
    except Exception:
        pass
    return "6000.3.11f1"        # the build this was written against


def tight(im: Image.Image) -> Image.Image:
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def keyed(im: Image.Image) -> Image.Image:
    """Alpha for a texture drawn on a flat opaque backdrop.

    Several of the game's small icons ship with no usable alpha channel and
    the art simply painted onto a solid colour. The corner pixel IS that
    colour, so transparency is distance from it - graded rather than
    thresholded, or every edge comes out as stairs.
    """
    rgb = im.convert("RGB")
    bg = rgb.getpixel((1, rgb.height - 2))
    alpha = Image.new("L", rgb.size)
    ap, sp = alpha.load(), rgb.load()
    for yy in range(rgb.height):
        for xx in range(rgb.width):
            r, g, b = sp[xx, yy]
            d = abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
            ap[xx, yy] = 255 if d >= 88 else (0 if d <= 24 else
                                              (d - 24) * 255 // 64)
    return Image.merge("RGBA", (*rgb.split(), alpha))


def main() -> int:
    try:
        import UnityPy
        import UnityPy.config
    except ImportError:
        sys.exit("UnityPy is not installed - run:  pip install UnityPy")
    warnings.filterwarnings("ignore")

    install = game_dir()
    win = install / "Data" / "Win"
    if not win.is_dir():
        sys.exit(f"no game data at {win} - is Hearthstone installed?")
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version(install)
    print(f"install {install}  (unity {UnityPy.config.FALLBACK_UNITY_VERSION})")
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- the source textures ---------------------------------------------
    # The two atlases the shield, star, medals and crown are cut from, plus
    # the three standalone icons the micro counter windows wear. Those three
    # were found by name across the whole install (2026-08-15); the game has
    # no icon at all for a free reroll or for the turn, which is why those
    # two windows keep a designed glyph and these do not.
    wanted = {"Bacon_TechLevel_Banner", "BaconLeaderboardIcons",
              "GoldCoin", "TrinketIconHeroSelect", "Bacon_TripleUpgradeArrow"}
    found: dict[str, Image.Image] = {}
    for p in sorted(win.glob("*.unity3d")):
        if wanted <= set(found):
            break
        try:
            env = UnityPy.load(str(p))
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            try:
                d = obj.read()
            except Exception:
                continue
            if d.m_Name in wanted and d.m_Name not in found:
                found[d.m_Name] = d.image.convert("RGBA")
                print(f"  {d.m_Name}  {d.image.size}  <- {p.name}")
    missing = wanted - set(found)
    if missing:
        sys.exit(f"not found in this game build: {', '.join(sorted(missing))} "
                 f"- the recipes need re-measuring against the new patch")

    # ---- the tier shield and star (atlas quadrants, alpha-tightened) -----
    tech = found["Bacon_TechLevel_Banner"]
    w, h = tech.size
    # This atlas carries NO real alpha (extrema 255..255, measured
    # 2026-08-15): the game packs each shape's alpha as a separate
    # silhouette next to the colour art - the shield's colour sits in the
    # top-left quadrant and its BLACK-on-white mask in the top-right.
    # Cropping the colour alone bakes the atlas background into the icon
    # (that is exactly the opaque grey box plus white edge the first
    # extraction shipped); the mask, inverted, IS the alpha.
    q = w // 2
    rgb = tech.crop((0, 0, q, q)).convert("RGB")
    mask = ImageOps.invert(tech.crop((q, 0, 2 * q, q)).convert("L"))
    shield = tight(Image.merge("RGBA", (*rgb.split(), mask)))

    # The star has no packed mask, only a flat backdrop - keyed out below.
    star = tight(keyed(tech.crop((int(w * 0.84), int(h * 0.84), w, h))))
    shield.save(OUT / "shield.png")
    star.save(OUT / "star.png")

    # tier_N: the shield wearing N of its own stars, the way the game says
    # "tavern tier". The stars sit in a shallow arc across the shield's
    # upper half, tighter as the count grows.
    for n in range(1, 8):
        base = shield.resize((128, 128), Image.LANCZOS)
        s = star.resize((34, 34), Image.LANCZOS)
        span = min(94, 26 * n)
        for i in range(n):
            cx = 64 - span / 2 + span * (i + 0.5) / n
            cy = 44 + abs(cx - 64) * 0.25
            base.alpha_composite(s, (int(cx - 17), int(cy - 17)))
        base.save(OUT / f"tier_{n}.png")
    print("  tier_1..7 composited from shield + star")

    # ---- the placement medals and the crown (4x4 grid, bottom row) -------
    # This atlas DOES carry real alpha (extrema 0..255, measured
    # 2026-08-15) - a straight crop is correct here.
    lead = found["BaconLeaderboardIcons"]
    cell = lead.size[0] // 4
    row = 3
    for i, name in enumerate(("medal_1", "medal_2", "medal_3", "crown")):
        tight(lead.crop((i * cell, row * cell,
                         (i + 1) * cell, (row + 1) * cell))).save(
            OUT / f"{name}.png")
    print("  medal_1..3 + crown")

    # ---- the counter icons the micro windows wear ------------------------
    # Straight copies where the texture already carries its own alpha, and a
    # backdrop key where it does not (the triple arrow is drawn on opaque
    # black, the same trick the star needed).
    for src, name in (("GoldCoin", "counter_gold"),
                      ("TrinketIconHeroSelect", "counter_trinket"),
                      ("Bacon_TripleUpgradeArrow", "counter_upgrade")):
        im = found[src]
        if im.getchannel("A").getextrema()[1] == im.getchannel("A").getextrema()[0]:
            im = keyed(im)
        tight(im).save(OUT / f"{name}.png")
        print(f"  {name} <- {src}")

    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
