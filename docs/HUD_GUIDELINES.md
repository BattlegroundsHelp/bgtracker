# HUD guidelines - the design contract every window follows

This is the law the overlay's look answers to. It exists because the look
was rebuilt three times in one day until the rule underneath it was said
out loud: **copy how the established trackers handle it, never invent an
aesthetic.** HSReplay's overlay and Firestone are the reference; when a new
surface needs a look, open theirs, measure it, and copy the recipe. Where
no reference exists, the fallback ladder below says where the pixels come
from.

## The doctrine, measured

Both references present the same way (measured off their pages and overlay
screenshots, 2026-08-14):

- **Flat ROWS, not flat everything.** Rows are a plain lightening of the
  face: `white @ 8%`, hover `12%`, radius 0, borders 0 - measured on both
  references and true. What was WRONG here until 2026-08-18: this file said
  Firestone's face is `#190505`. That is their DESKTOP app's black. Their
  Battlegrounds overlay is plum (`#1e0116` face, `#40032e` sub-surfaces,
  `#841063` rules) and its panels are a dark radial gradient over a
  photographic backdrop - not flat at all. Our opt-in tavern skin is nearer
  to what they really do than our flat default is. Keep the flat default
  because it is OUR face and it reads; just do not cite it as theirs.
  HSReplay's overlay is the flat one, on `#1a0e1f`.
- **Radius means something.** Theirs is a vocabulary, not a constant: `0`
  for anything docked (panels, rows, headers), `15` for a capsule floating
  over the board, `25` for a full guide card, fully round for a chip or a
  counter. We currently use one radius everywhere, which throws the
  distinction away. See docs/REFERENCE_TEARDOWN.md.
- **The information is the interface.** Numbers and names carry the
  meaning; chrome carries nothing.
- **One accent.** The single loud thing is the row being pointed at - for
  us a thin GOLD outline. Nothing else gets an edge.

## Palette (ui/base.py, the only place colours live)

- Surfaces: `PANEL #191410` face, `PANEL_HI #241d15` raised, `ROW #1e1811`
  plate, `HEADER_BG`, `SHADE`, `EDGE` (the one hairline), `LINE` rules.
- Text: `TEXT #f2ece0`, `SOFT #c6b89f`, `DIM #93876f`, titles `GOLD_TEXT`
  (nearly Firestone's own heading colour, measured `#d9c3ab`).
- **Data colours are law.** `GOOD`/`AMBER`/`BAD`, `avg_color()`,
  `TRIBE_COLOR`, `STAR_COLOR`: the hue IS the number. Never spend a data
  colour on decoration, never recolour data for taste.
- `ACCENT` (cool blue) marks exactly one thing: clickable / yours.
- `#000001` is the click-through hole. No shipped pixel may be exactly it;
  every image bake nudges blue 1 to 2 (ui/skin.py) and outer silhouettes
  binarize their alpha.

## Typography (ScaledFont objects, shared by reference)

| Role | Font | Use |
|---|---|---|
| Window title | F_BRAND 9 semibold, GOLD_TEXT | header only |
| Row name | F_NAME 10 semibold | one per row |
| Body | F_SUB 8 | everything else |
| Label / tag | F_CHIP 7 | column labels, tiny chips |

Labels sit ABOVE values (tiny DIM label, bright value under it) - the
reference's stat pattern. Text over art always goes through
`shadow_text()`.

## Window anatomy

- Header slab 24px: title left (dot optional), status text right, drawn by
  `self.header(...)`. Body starts at the returned y.
- Margins: 14px left and right, in BASE pixels.
- Rows: 22-29px, on `tile_row()` when a card id exists (the game's own
  deck-list slice, gem with the tier on the left), `plate()` otherwise.
- Windows paint in BASE pixels; the canvas transform scales AFTER. Images
  do NOT scale with the canvas - **bake every image at final pixels**
  (`base * get_scale()`), anchor at base coordinates.
- Band budgets are real: `DY + MAX_H` may never cross the next window's
  band, and test_windows fails on ink below a window's returned height.
  Measure with Tk's real line boxes (F_NAME's box is 17px, F_SUB's 13px),
  not font point sizes.

## The recipes (copy these, do not restyle them)

- **Deck-list row** (`skin.tile` / `base.tile_row`): the 256x59 tile art
  full-bleed under the row, dark gradient carrying the name on the left,
  tier gem at x+3. Fallback: icon + text row.
- **Labelled stats** (counters, session MMR): F_CHIP DIM label over the
  value, columns dropped from the right when narrow.
- **Stat cells over cards** (hero/trinket badges): AVG and PICK boxes
  above each card, HALO fill, LINE outline - GOLD outline marks the best.
- **Counter pills** (BUFFS): rounded pill, round source art (or emblem)
  left, `+X / +Y` in F_NAME.
- **Tall plates**: never stretch row art past its aspect - `_slice_filled`
  keeps corners true. The general rule: **art holds its shape at the
  edges; interiors are flat** (the quiet pass enforces brightness <= ~38
  where text sits).

## Where assets come from (the ladder)

1. **HearthstoneJSON CDN** - card tiles and crops (`fetch-art
   --everything`). Runtime-fetched into `assets/`, never committed.
2. **HDT's MIT resources** - tracker chrome (the deck-list gem). Same
   fetch posture.
3. **The user's own game install** - `tools/extract_game_assets.py`
   (UnityPy): the tavern-tier shield, tier star, medals, crown. Extracted
   per user, NEVER in the repository.
4. **Design it, render it headless** - only for chrome nothing publishes
   (the tribe emblems): original glyphs, SVG through headless Chrome,
   `tools/make_ui_icons.py`, shipped in `data/ui/` because they are ours.

Blizzard art never enters the repo. The anonymity sweep before every push
covers names, the battletag, and machine paths.

## Skins and toggles

The flat look is the default. The generated tavern skin (`data/skin/`,
`tools/make_skin.py`) lives behind the settings switch, applied live; the
four drawing helpers (`panel_frame`, `header_slab`, `plate`, `art_frame`)
are the seam, and every skin answer of None falls back to the flat vector
chrome. Nothing may fail closed over a missing image.

## Data that drives words on screen

Curated strategy text ships as dated JSON beside the code
(`data/hero_tips.json`, `data/curves.json`) - written from public guides,
never scraped stats, user-editable beside the exe, refreshed each season.
Stats come only from the community pool. A number the log or the pool has
not stated draws as a dash or nothing - never a guess.

**Measured and guessed are different marks.** The pool is young, so
`data/minion_ratings.json` holds a starting opinion of each minion, frozen
once from the pool itself (`tools/make_minion_priors.py`, every card pulled
toward its own tier's average by how little evidence stood behind it). The
windows blend it with the live table by sample size - `w = n / (n +
MIN_SAMPLE)` - so a card slides off the guess and onto its own record as
games arrive. The rule that keeps this honest, and it is not negotiable:

* **★ solid, colour graded** = the pool's games said this
* **☆ hollow, muted** = the starting guess, `w < 0.5`

Never draw one as the other, never mix the two glyphs on one row, and name
both in the surface's footer where both can appear. The same holds for any
future bootstrap: a value the tool assumed must look different from a value
the tool measured.

## Before you ship a look change

1. Screenshot the window in a REALISTIC state (seed the state, then
   `show()` / `redraw()` / `deiconify()`, and grab the canvas with PIL).
2. Check the band: no ink below the returned height at scale 1 - then
   think about scale 2.
3. Run the battery: test_windows on a CLOSED log (a live one races),
   test_settings, test_skin, test_shopbuff.
4. If it is a new surface: find the reference's version of it first.
