#!/usr/bin/env python3
"""The image-backed drawing layer, pinned - it had zero tests until the
2026-08-14 day review said so out loud.

    python tests/test_skin.py

Everything here runs machine-independent: the tile source is SYNTHESIZED
into a temp folder (CI has no fetched art), the tavern-skin gate is driven
explicitly (the lazy settings.json read was reviewed out for making test
outcomes depend on the machine's live file), and a throwaway Tk root hosts
the photo bakes.
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from ui import skin  # noqa: E402


def main() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and cond

    root = tk.Tk()
    root.withdraw()
    c = tk.Canvas(root)

    # 1. The gate: unwired means OFF, regardless of this machine's settings.
    skin._enabled = None
    check(skin.active() is False, "unwired skin defaults OFF (no file reads)")
    skin.set_enabled(True)
    # active() may still be False here if data/skin is absent - that is the
    # files half of the gate and it may differ per machine; the SETTING half
    # is what must not float.
    check(skin._enabled is True, "set_enabled wires the setting half")
    skin.set_enabled(False)

    # 2. The deck tile: synthetic source, real bake, golden folds onto base.
    with tempfile.TemporaryDirectory() as td:
        src = Image.new("RGBA", (256, 59), (200, 60, 40, 255))
        src.save(Path(td) / "BG99_TEST.png")
        real_dir = skin._TILE_DIR
        skin._TILE_DIR = Path(td)
        try:
            t1 = skin.tile(c, "BG99_TEST", 300, 26)
            check(t1 is not None, "tile bakes from a source on disk")
            check(t1 is not None and int(t1.width()) == 300
                  and int(t1.height()) == 26,
                  "tile is exactly the requested pixels")
            t2 = skin.tile(c, "BG99_TEST", 300, 26)
            check(t2 is t1, "same request hits the photo cache")
            g = skin.tile(c, "BG99_TEST_G", 300, 26)
            check(g is not None
                  and "tile:BG99_TEST" in skin._src
                  and "tile:BG99_TEST_G" not in skin._src,
                  "a golden id folds onto its base before the source cache")
            check(skin.tile(c, "BG99_NOPE", 300, 26) is None,
                  "no source on disk answers None (caller falls back)")
        finally:
            skin._TILE_DIR = real_dir

    # 3. The source cache stays bounded.
    before = len(skin._src)
    for i in range(600):
        skin._keep_src(f"synthetic:{i}", None)
    check(len(skin._src) <= 513,
          f"source cache bounded ({before} -> {len(skin._src)})")

    # 4. UI chrome misses answer None, never raise.
    check(skin.ui_icon(c, "definitely_absent_chrome", 20) is None,
          "missing ui chrome answers None")
    check(skin.round_icon(c, "BG00_NO_SUCH_CARD", 20) is None,
          "missing crop answers None")

    root.destroy()
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
