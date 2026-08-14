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

from PIL import Image

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

    # ---- the two source atlases ------------------------------------------
    wanted = {"Bacon_TechLevel_Banner", "BaconLeaderboardIcons"}
    found: dict[str, Image.Image] = {}
    for p in sorted(win.glob("essential_base_global-texture-*.unity3d")):
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
    shield = tight(tech.crop((0, 0, w // 2, h // 2)))
    star = tight(tech.crop((int(w * 0.84), int(h * 0.84), w, h)))
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
    lead = found["BaconLeaderboardIcons"]
    cell = lead.size[0] // 4
    row = 3
    for i, name in enumerate(("medal_1", "medal_2", "medal_3", "crown")):
        tight(lead.crop((i * cell, row * cell,
                         (i + 1) * cell, (row + 1) * cell))).save(
            OUT / f"{name}.png")
    print("  medal_1..3 + crown")

    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
