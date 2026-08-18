<!-- Written 2026-08-18 from a four-lens teardown of the reference tracker
     (Zero-to-Heroes/firestone) plus screenshots of its paid client, against
     our own code. It records MEASUREMENTS AND RULES so every item can be
     re-implemented from scratch in Tk. No code and no data from that project
     is present here or anywhere in this repository - it carries no licence,
     which means all rights reserved.  -->

# BUILD SPEC — what we take from Firestone, and how

Reference: `Zero-to-Heroes/firestone` (TypeScript/Angular, Overwolf, **no LICENCE file**). Read for behaviour and measurement only. Nothing is copied — not a line of code, not a byte of data.

---

## 1. What the reference actually is

**It is one window, not many.** The whole in-game HUD is a single Overwolf window sized to the game rectangle at 0,0, hosting ~40 surfaces as children. Their manifest declares only 11 OS windows for the entire app. Ours is 22 Tk Toplevels. That difference is topology, not look, and it is the one thing we should *not* chase — but it explains why every one of their surfaces can share a tooltip layer, a z-order and a hover state for free.

**The look is a token system, not a stylesheet.** One `battlegrounds-theme` class sets ~14 CSS custom properties; no component ever names a hex. The Battlegrounds face is plum — `#1e0116` panel, `#40032e`/`#39122e` sub-surfaces, `#841063` for every 1px rule, `#dfb3d3` headings, `#ffb948` titles and values, `#d9c3ab` body. Note for our contract: the `#190505` our `docs/HUD_GUIDELINES.md` attributes to Firestone is their *desktop* theme's `$black`, not the BG overlay. That line is wrong and must be fixed.

**Rows are flat; panels are not.** Rows really are `rgba(255,255,255,0.08)`, hover `0.12`, radius 0, no border — our contract got that half right. But the panel *under* the rows is a dark radial gradient over a photographic background image. Our opt-in tavern skin (`data/skin/`) is closer to their real panel than our flat default is.

**Radius is a semantic.** 0px = docked (rows, headers, lists, panels). 15px = a floating capsule over the board. 25px = the big centred guide card. 50% = a chip, a counter, a portrait. They never round a docked row. We apply `RADIUS = 14` to every window and `r=9` to every row, which erases the meaning.

**Emphasis is colour and opacity, never bold and never fill-swap.** Open Sans 400 carries the whole interface at 13px body / 15px group header / 14px section title. Two display faces exist only for numbers sitting on card art. Unselected things sit at opacity 0.4–0.6 and go to 1 on hover; the selected one gains a 2px outline. Inside a comp list they spend a *second* outline colour with its own meaning: lilac `#cb9fd7` = you already control this card, gold `#ffb948` = it is in the shop right now.

**Numbers are coloured continuously, and bands are letters.** A placement is lerped in HSL between one red and one green, clamped at two named thresholds — so the colour *is* the ranking. Separately, comps, heroes and trinkets carry a letter band S/A/B/C/D/E with six fixed, deliberately non-ramp hues (S periwinkle, A pink, B sage, C gold, D red, E burnt orange), riding in a 22px circle outlined in its own colour.

**Every grouping is the same object.** A tribe header, a CORE/ADD-ONS sub-head, a comp title: a solid full-bleed bar 26–35px tall, centred 15px text, 2px gap to the next thing. Empty panels are a centred icon + 14px bold title + 13px sentence saying what will appear here and when — never a grey shrug.

**Settings are data, not code.** A tree of nodes → sections → settings, with keywords for search, `advancedSetting` flags, per-setting tooltips, and `disabledIf(prefs)` so a master switch greys its children *without hiding them*. Every feature family has a kill switch. Visibility of a surface is a three-way AND — scene × prefs × game state — plus a separate `hidden` state that keeps position and data while invisible.

**The organising idea underneath all of it:** a surface declares what it is (docked / floating / popup), what preference owns it, what scene it belongs to, and where it defaults *as a function of the game rectangle*. The framework does the rest once. We hand-write each of those decisions per window today.

---

## 2. The structure we should adopt

### 2.1 The window contract (`ui/__init__.py`, `ui/base.py`)

Add five declarations to the plugin contract. All are static class attributes; none change the router.

| New attribute | Values | Replaces |
|---|---|---|
| `SURFACE` | `"docked"` \| `"floating"` \| `"popup"` | implied by which column it sits in |
| `MASTER` | key of a parent switch, or `None` | nothing — our 22 switches are flat |
| `SCENE` | tuple of phases it may appear in | the per-window `EVENTS` hacks |
| `BOUNDS` | how far off the game rect it may hang | nothing — offsets are raw screen deltas |
| `SCALE_KEY` / `OPACITY_KEY` | its own prefs, on top of global | nothing — one global scale |

Add a **third visibility state**. Today `show()`/`hide()` cannot say "not now". Introduce `soft_hide()`: the window keeps its data, its position and its band, and draws nothing. Our session-window band-yield hack (hides on `hero`, returns on `hero_over`, only while undragged) becomes one declarative line instead of bespoke code.

Add a **scene value to the event bus**. The router gains `scene` (`menu | lobby | hero_select | recruit | combat | game_over`) derived from what we already parse (`BACON_CURRENT_COMBAT_PLAYER_ID`, the DragBuy burst, the hero draft). Gating then reads `scene in cls.SCENE and prefs_allow(cls) and state_has_data(cls)` for every window, once, in one place.

Make **default positions functions of the game rect**, not fixed 1920×1080 bands: `default_xy(gw, gh) -> (x, y)`, then clamp against `BOUNDS`. This is why a window dragged at 1080p lands oddly at 4K today.

### 2.2 The base drawing kit (`ui/base.py`)

Retire `RADIUS = 14` as a global. Replace with a vocabulary and use it by meaning:

```
RADIUS_DOCKED = 0    # panels, rows, headers   (today: 14 and 9)
RADIUS_FLOAT  = 15   # capsules over the board
RADIUS_CARD   = 25   # the one big guide card
# chips, counters, portraits: full round
```

Add four helpers so recipes live in one place, not in ten modules:

- `strip_header(c, x1, x2, y, text)` — full-bleed 26px bar, centred, 2px gap below. Replaces `ui/base.py header()`'s left-aligned slab for *group* headers, `ui/browser.py:749` and the bare labels at `ui/comps.py:357/366`.
- `empty_state(c, w, h, icon, title, sentence)` — centred, 14px bold title + 13px sentence. Replaces the four one-line DIM shrugs (`ui/comps.py:291`, `ui/counters.py:914`, `ui/heropick.py:161`, `ui/players.py:162`).
- `tooltip(...)` — a coloured slab with an arrow, deliberately unlike a panel. We have no tooltip layer at all today.
- `band_letter(c, x, y, letter)` — 22px circle, 1px outline in its own hue.

Widen `avg_color()` from four steps to a two-colour lerp with our own thresholds, computed from our own pool. The formula is arithmetic; the thresholds must be ours.

Grade the dim states instead of one flat "off": name at 0.5 for locked/out-of-tier, 0.3 for banned. Our `DIM`/`OFF_CHIP`/`OFF_TRIBE` recolour is one state doing three jobs.

### 2.3 The settings panel (`ui/settings.py`)

Split it in two. `ui/settings_tree.py` declares the tree as data; `ui/settings.py` becomes a renderer that walks it.

```
Node(id, title, keywords, children=[], sections=[])
Section(title, texts=[], settings=[], buttons=[])
Setting(key, kind, label, tooltip, disabled_if=None, indent=False, advanced=False)
  kind: toggle | tri | slider | dropdown | text | number
Button(label, action, confirm=None)
```

`_build_display` / `_build_data` / `_build_windows` / `_build_updates` stop hand-building frames and become four node definitions. The window switches keep generating themselves from `ui.GROUPS` / `ui.GROUP_OF` (already correct) but gain `MASTER` so children grey out instead of sitting equal. Add: a search box filtering on `keywords`, a "show advanced" toggle, per-setting tooltips, and a `disabled_if` that dims a whole subtree.

Add three global controls in one section: **lock positions** (one boolean, all windows), **reset positions** (clears every `dx/dy` in `.overlay.json`, behind a confirm), and per-window **scale** and **opacity** sliders on top of the existing global `ui_scale`.

### 2.4 Counters (`ui/counters.py`, `ui/micro.py`)

Keep one window per counter — that is the maintainer's 2026-08-15 call and it is not reversed. Change what drives them: a registry of counter *definitions* (`id`, source card for the art, `value(state)`, `tooltip(state)`, `is_active(state, prefs)`), with **three-state** visibility per counter: `off` / `auto` (appear only while its cards are actually in play) / `always`. `CounterState` already is the single shared source; only the registry shape and the third state are missing.

---

## 3. Feature ledger

"Honest?" means: can we back what appears on screen with our own measurement, our own dated curation, or pure local state — with measured and guessed drawn differently (`HUD_GUIDELINES.md`).

| Feature | What it does | Our data source | Honest? | Effort | Value |
|---|---|---|---|---|---|
| Tavern pinning | Pin a card / tribe / tier / mechanic; matching shop cards light up all game | `tavern` event (Power.log) + card DB via `bgtracker.bg_pool()` | yes — pure local state, claims nothing | medium | high |
| Comp pinning + remember | One click pins every card in a comp; ask to re-arm next game | `data/comp_roles.json` (`comp_role_split`) — already computes CORE/ADD-ON | yes | small | high |
| Lock / unlock overlay + reset | One switch makes everything draggable; one button restores defaults | `settings.json` + `.overlay.json` | yes | small | high |
| Master switch + greyed children | Family kill switch; sub-options stay visible, dimmed | `settings.json` only | yes | medium | high |
| Declarative settings tree | Nodes/sections/settings as data; search, tooltips, advanced tier | none | yes | medium | high |
| Per-window scale + opacity | Own sliders on top of global scale | `settings.json`; `ui/base.py` already scales each canvas | yes | medium | high |
| Per-surface gear / reset / X | Each window closes itself, and closing writes the pref off | none | yes | medium | high |
| Scene × prefs × state gating + soft-hide | One rule for every window; "not now" ≠ "off" | our events + a new `scene` value | yes | medium | high |
| Empty states | Icon + title + a sentence saying what appears here and when | none | yes | small | high |
| Full-bleed section header strips | Tribe / CORE / ADD-ONS headers become one object | none | yes | small | high |
| Radius vocabulary | 0 docked / 15 floating / 25 card / round chips | none | yes | medium | high |
| Two selection outlines | lilac = on your board, gold = in the shop right now | board (memory) + shop (log), both already held | yes | small | high |
| Merged browser (tiers \| mechanics \| comps) | One surface, hover previews, click locks, leave clears | existing `ui/tavern.py` + `ui/browser.py` + `ui/comps.py` | yes | medium | high |
| Comp guides prose | How to Play, When to Commit, difficulty, author, date | new curated dated JSON beside `comp_roles.json` | yes — curated, authored, dated on screen | medium | high |
| Hero guides prose + per-turn actions | Longer body, author, "last updated"; curves gain buy/roll/sell/level steps | `data/hero_tips.json`, `data/curves.json` | yes — curated, dated | medium | high |
| Curated provenance on screen | Print author + date wherever curated text appears | both files already carry `updated` / `_comment` | yes — this is what makes the rest honest | small | high |
| Continuous stat colour | Lerp instead of 4 steps; colour *is* the ranking | pool numbers | yes | small | medium |
| Letter tier bands (S/A/B/C/D/E) | One-glyph verdict per comp / hero / trinket | our pool | **conditional** — only above the n≥30 floor, hollow/omitted below | medium | high |
| Mechanics filter | Battlecry / Deathrattle / Divine Shield / Taunt / Reborn / Venomous / Magnetic… | card DB mechanics tags | yes | medium | medium |
| Hover tooltip on a shop minion | "Comps — Enabler / Commit Piece", then the comp and its band | `comp_roles.json` + pool | yes | medium | medium |
| Counter registry + tri-state | off / auto / always, driven by definitions | `CounterState` (already shared) | yes | medium | high |
| Counter look | Ringed round crop + inverted light value pill | `assets/crops/*.png` | yes | medium | medium |
| Round icons from card art | Clipped crops instead of an 8px coloured dot (`ui/comps.py:319`) | `assets/crops` (1,172 heroes + trinkets) | yes | small | medium |
| Graded dim (0.5 / 0.3) | Locked vs banned readable apart | none | yes | small | medium |
| Session = a saved timestamp | Session is a date filtering `data/games.jsonl`, not a second copy | `collect.py` | yes — removes the duplicate in `.overlay.json` | small | medium |
| Game-rect default positions + clamp | Defaults computed from live game size, clamped in bounds | none | yes | medium | medium |
| Fading gold edge | 1–2px edge fading left→right; their one ornament | none | yes | medium | low |
| Available-tribes strip | Standing row of tribe icons | log `CARDRACE` sightings only | **partial** — "confirmed / not seen yet", never "banned" | small | medium |
| One-host-window topology | 40 surfaces inside one OS window | none | yes but pointless | large | low |
| Pick rate per option | "% of players took this" | — | **no** — we cannot observe other players' picks | — | — |
| Combat win % | Simulated odds | — | **no** — that is Bob's Buddy; settled | — | — |

---

## 4. The order to build in

1. **Fix the contract, then the vocabulary.** `docs/HUD_GUIDELINES.md` currently states a measurement that is wrong (`#190505` is their desktop theme, not the BG overlay) and calls their panels flat when they are gradient-over-art. Every look item below inherits from this document, so it goes first. Ship it with the radius vocabulary and the four new helpers in `ui/base.py`. Nothing else is safe to build on a contract we know is wrong.

2. **Tavern pinning.** The single most-loved small feature in the reference, and it needs zero new data — the shop already arrives on our `tavern` event and tribe/tier/mechanic come from the card DB. It is local state plus a mark on rows we already draw. Highest value-per-byte on the list.

3. **Comp pinning + remember next game.** Rides directly on #2 and is nearly free: `comp_role_split` already computes each family's CORE and ADD-ON set. Do it in the same pass or the pin code gets written twice.

4. **The settings tree, with masters and greying.** Our 22 flat switches were already called a wall of checkboxes (project owner, 2026-08-18); grouping helped, but a group is not a master. This must land before per-window scale, opacity, gear and close — each of those adds rows to a panel that is hand-built today, and hand-adding them makes the wall worse.

5. **Lock positions + reset positions.** One boolean and one button, both small, both in the section #4 just created. Reset is a genuine rescue: a window dragged off-screen at one resolution has no recovery path today.

6. **Per-surface gear / reset / X, plus per-window scale and opacity.** Exactly one window carries the X and the gear today (`QUIT_BUTTON`), and that refusal is correct and stays — but every *other* window should close itself, and closing should write the pref off. This is the item that makes the overlay feel owned rather than dumped on screen.

7. **Empty states, header strips, provenance stamps.** Three small changes, one afternoon, disproportionate effect. The empty state turns four dead panels into panels that teach. The provenance stamp is what makes a curated opinion visibly *an opinion* — it is our own honesty rule (`measured and guessed are different marks`) applied to words instead of stars.

8. **The merged browser.** TAVERN, MINIONS and COMPS are one surface in the reference with two-level nav: hover previews a tier, click locks it, leaving clears it, and your tavern tier only follows you if you were not deliberately locked elsewhere. This is the largest structural win, and it goes last of the eight because it consumes items 1, 4 and 6 — do it before them and it gets rebuilt.

Below the line for now, in order: counter registry + tri-state, mechanics filter, tooltip layer, hover tooltips on shop minions, comp/hero guide prose, game-rect default positions, counter medallion look, round crops replacing dots.

---

## 5. What we will not copy

**Their code.** The repo has no LICENCE file, which means all rights reserved by default — not "free to use". We read it to understand behaviour and to measure recipes. Nothing is pasted, no file is ported, no SCSS is translated. Every item above is re-implemented in Tk from a described measurement, which is why this spec records *dimensions and rules* rather than snippets.

**Their data.** Settled 2026-08-10 and not reopened: `static.zerotoheroes.com/api/bgs/*` is accessible but their ToS §7 bans scraping, republishing and redistribution. Our shipped build uses our own community pool (~130 games) and our own dated curated JSON. Self-hosting a cached copy is the same violation with extra steps.

**Their words.** Hero guides, comp guides, tips and the authors' names are content they commissioned. Our `data/hero_tips.json`, `data/curves.json` and the new comp guide file are written by us, dated by us, and signed by us.

**Their brand face.** Their plum theme is Firestone's identity, not a usability finding. Our copy-not-invent rule says copy how established trackers *handle* a problem — tokens, radius semantics, row washes, header strips, opacity states — not wear their colours. We keep the wood-and-gold face and the opt-in tavern skin, and we adopt the token *system* so a future re-skin is one block instead of ten modules. If the maintainer wants the plum, it is one token block and half a day — but it should be a deliberate call, not a side effect of this spec.

**Any claim we cannot measure.**
- **Pick rate: never.** We can see what *we* were offered and took. We cannot see what anyone else picked. There is no honest way to print a pick %.
- **Combat win %: never.** That is Bob's Buddy, a closed per-patch simulator. Our sim reports its own numbers as its own (~86%, Brier 0.072) or nothing.
- **Letter bands: only above the floor.** A comp gets an S/A/B letter only when our own pool has cleared n≥30 for it. Below that, no letter — not a grey letter, no letter. And the letter is computed from our pool, never transcribed from theirs.
- **Banned tribes: never say banned.** The log proves a tribe is *in* by a `CARDRACE` sighting; it can never prove one is out. The strip says "confirmed / not seen yet", as it does today.
- **Memory-only surfaces stay optional.** The published build is log-only by default; `tribes.exe` / `msync` are not bundled. Anything in this spec that needs a memory read (the moused-over card for popup tooltips, the opponent board) degrades to "the window never opens", exactly as `players` does now.

**Their art.** No Blizzard or Firestone image enters the repo. Card tiles and crops are runtime-fetched from HearthstoneJSON, game chrome is extracted per-user by `tools/extract_game_assets.py`, and the tribe emblems stay ours because nobody publishes them. The anonymity sweep before every push still covers the name, the battletag and machine paths.