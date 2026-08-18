#!/usr/bin/env python3
"""Render the tribe emblems and the buff glyph - the chrome nothing publishes.

    python tools/make_ui_icons.py

Card art is fetched (fetch_art.py) and the deck-list gem comes from HDT's
MIT resources, but two pieces of chrome exist NOWHERE fetchable: tribe
emblems and an icon for a buff whose source card has no art. These are
therefore the one place the chrome is OURS - designed in the overlay's own
flat language (a ring in the tribe's data colour, one bold original glyph),
deliberately NOT imitating Blizzard's emblems, so they can live in the repo
and ship with the build.

Rendered headless: each icon is authored as SVG (crisp curves PIL cannot
draw) and rasterised by Chrome with a transparent background into
data/ui/tribe_<name>.png at 64px. Deterministic - same SVG, same pixels -
so re-running is a no-op for the diff. Every output is scrubbed of #000001,
the overlay's transparency key, same rule as every shipped pixel.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ui"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# The overlay's own tribe colours (ui/base.py TRIBE_COLOR), restated here so
# the tool has no import path into the UI package.
COLOUR = {
    "beast": "#57a05e", "demon": "#a05ec2", "dragon": "#d1793e",
    "elemental": "#4fb3c9", "mechanical": "#8a94a8", "murloc": "#58b8a2",
    "naga": "#5f7fd9", "pirate": "#c2564f", "quilboar": "#b08d4e",
    "undead": "#7a6fae", "all": "#c6b89f", "buff": "#e0b45c",
}

# One bold original glyph each, drawn on a 64x64 canvas, centred. Simple
# geometry only: these read at 14px or they are worthless.
GLYPHS = {
    "beast":      '<circle cx="32" cy="38" r="9"/>'
                  '<circle cx="20" cy="26" r="5"/><circle cx="32" cy="22" r="5"/>'
                  '<circle cx="44" cy="26" r="5"/>',
    "demon":      '<path d="M18 18 Q22 34 32 40 Q42 34 46 18 Q40 26 32 27 '
                  'Q24 26 18 18 Z"/>'
                  '<circle cx="32" cy="46" r="4"/>',
    "dragon":     '<path d="M16 40 Q24 16 48 18 Q38 24 36 32 Q34 40 42 44 '
                  'Q28 48 16 40 Z"/>',
    "elemental":  '<path d="M32 14 Q44 28 44 38 A12 12 0 0 1 20 38 '
                  'Q20 28 32 14 Z"/>',
    "mechanical": '<circle cx="32" cy="32" r="8" fill="none" stroke-width="6"/>'
                  '<g stroke-width="5">'
                  '<line x1="32" y1="14" x2="32" y2="22"/>'
                  '<line x1="32" y1="42" x2="32" y2="50"/>'
                  '<line x1="14" y1="32" x2="22" y2="32"/>'
                  '<line x1="42" y1="32" x2="50" y2="32"/>'
                  '<line x1="19" y1="19" x2="25" y2="25"/>'
                  '<line x1="39" y1="39" x2="45" y2="45"/>'
                  '<line x1="45" y1="19" x2="39" y2="25"/>'
                  '<line x1="25" y1="39" x2="19" y2="45"/></g>',
    "murloc":     '<ellipse cx="28" cy="32" rx="14" ry="9"/>'
                  '<path d="M40 32 L52 22 L52 42 Z"/>',
    "naga":       '<path d="M18 44 Q26 40 26 32 Q26 24 34 22 Q44 20 46 12" '
                  'fill="none" stroke-width="7" stroke-linecap="round"/>'
                  '<circle cx="18" cy="46" r="5"/>',
    "pirate":     '<g stroke-width="6" stroke-linecap="round">'
                  '<line x1="18" y1="18" x2="46" y2="46"/>'
                  '<line x1="46" y1="18" x2="18" y2="46"/></g>'
                  '<circle cx="18" cy="18" r="4"/><circle cx="46" cy="18" r="4"/>',
    "quilboar":   '<path d="M32 14 L46 32 L32 50 L18 32 Z"/>',
    "undead":     '<circle cx="32" cy="28" r="13"/>'
                  '<rect x="26" y="38" width="12" height="8" rx="2"/>',
    "all":        '<path d="M32 12 L37 26 L52 26 L40 35 L45 50 L32 41 L19 50 '
                  'L24 35 L12 26 L27 26 Z"/>',
    "buff":       '<path d="M32 12 L48 30 L38 30 L38 38 L26 38 L26 30 L16 30 Z"/>'
                  '<rect x="26" y="42" width="12" height="8"/>',
}

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">
<circle cx="32" cy="32" r="30" fill="#241d15"/>
<circle cx="32" cy="32" r="30" fill="none" stroke="{colour}" stroke-width="4"/>
<g fill="{colour}" stroke="{colour}" stroke-width="0">{glyph}</g>
</svg>"""

# The counter glyphs: one per micro window (ui/micro.py), in the same flat
# language as the tribe emblems and for the same reason - nothing publishes
# an icon for "your free rerolls". They have to carry their meaning at 18px,
# so the geometry stays blunt. The NUMBER beside them is what gets read; the
# icon only says which number it is.
COUNTER_COLOUR = {
    "gold": "#e0b45c", "upgrade": "#6fbf73", "triples": "#c9a227",
    "rolls": "#6fa8dc", "trinket": "#c58fd6", "turn": "#c6b89f",
    "spells": "#7f6fd0",
}
COUNTER_GLYPHS = {
    # a coin, with a rim so it does not read as a full stop
    "gold":    '<circle cx="32" cy="32" r="17" fill="none" stroke-width="5"/>'
               '<circle cx="32" cy="32" r="7"/>',
    # a tavern upgrade: an arrow standing on its step
    "upgrade": '<path d="M32 12 L48 32 L39 32 L39 42 L25 42 L25 32 L16 32 Z"/>'
               '<rect x="20" y="46" width="24" height="6" rx="2"/>',
    # three of a kind
    "triples": '<circle cx="20" cy="40" r="8"/><circle cx="44" cy="40" r="8"/>'
               '<circle cx="32" cy="20" r="8"/>',
    # a refresh loop, open at the top with an arrow head
    "rolls":   '<path d="M46 32 A14 14 0 1 1 32 18" fill="none" '
               'stroke-width="6" stroke-linecap="round"/>'
               '<path d="M32 8 L32 26 L44 17 Z"/>',
    # a trinket: a stone in its setting
    "trinket": '<path d="M32 12 L46 24 L38 48 L26 48 L18 24 Z" fill="none" '
               'stroke-width="5"/><path d="M32 24 L38 30 L32 40 L26 30 Z"/>',
    # spells cast: a star burst over a wand, blunt enough to read at 18px
    "spells":  '<path d="M18 46 L36 28 L40 32 L22 50 Z"/>'
               '<path d="M42 10 L46 22 L58 26 L46 30 L42 42 L38 30 L26 26 '
               'L38 22 Z"/>',
    # the turn: a clock hand
    "turn":    '<circle cx="32" cy="32" r="18" fill="none" stroke-width="5"/>'
               '<path d="M32 20 L32 33 L41 38" fill="none" stroke-width="5" '
               'stroke-linecap="round"/>',
}


def scrub(p: Path):
    im = Image.open(p).convert("RGBA")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if (r, g, b) == (0, 0, 1):
                px[x, y] = (0, 0, 2, a)
    im.save(p)


def main() -> int:
    if not CHROME.is_file():
        sys.exit(f"no Chrome at {CHROME} - the headless renderer needs it")
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(f"tribe_{n}", COLOUR[n], g) for n, g in GLYPHS.items()]
    jobs += [(f"counter_{n}", COUNTER_COLOUR[n], g)
             for n, g in COUNTER_GLYPHS.items()]
    with tempfile.TemporaryDirectory() as td:
        for name, colour, glyph in jobs:
            svg = Path(td) / f"{name}.svg"
            svg.write_text(SVG.format(colour=colour, glyph=glyph),
                           encoding="utf-8")
            out = OUT / f"{name}.png"
            r = subprocess.run(
                [str(CHROME), "--headless=new", "--disable-gpu",
                 "--default-background-color=00000000",
                 "--window-size=64,64", f"--screenshot={out}",
                 svg.as_uri()],
                capture_output=True, timeout=60)
            if r.returncode != 0 or not out.is_file():
                sys.exit(f"{name}: Chrome refused "
                         f"({r.stderr.decode(errors='replace')[:200]})")
            scrub(out)
            print(f"  {name}.png")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
