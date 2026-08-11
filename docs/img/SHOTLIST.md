# Screenshot shot list for the beta-test post

What still has to be captured from the **ten-window build**, and the exact moment in a game
to catch each one.

---

## Status, 11 August 2026

Eight of the nine shots and three GIFs were cut from a **screen recording of one full game**
(`bg help.mp4`, 1892x1000, 30 fps, 13:32) instead of from stills. That solved the capture
problem outright: a screen recorder photographs the screen, so every overlay window is in
every frame, and the whole game can be re-scanned afterwards for the moment you want.

**Anonymity method used on every export.** In this recording the account name sits at
y 924-940 and the wall clock at y 967-985, both at x < 170; the opponent nameplate sits at
x 5-145, y 55-67. Every asset is a rectangular crop chosen so those two rectangles fall
outside it. Full-width shots are cropped to **height 918** (drops the name and clock) and
were taken at moments where the overlay's own SESSION window already covers the nameplate
band, which was checked pixel by pixel on the exported file. Nothing is blurred.

**One caveat for captions.** The recording was made with **no stats source configured** —
the minion browser reads "no stats source", the trinket window reads "NO TRINKET STATS
CONFIGURED", comps read "curated". The one exception is the hero window, which shows
`Al'Akir 7.00 · 50% pick · 1 games · thin!`, i.e. a single game of the author's own local
feed. If that shot is posted, say so.

---

## Read this first: the capture method is the whole problem

**Hearthstone's own screenshot key cannot photograph the overlay.** Nine shots taken on
11 August (`Hearthstone Screenshot 08-11-26 *.png`) contain zero overlay pixels — not the
old panel, not the new windows, nothing. The game's screenshot writes its own rendered
frame to disk; a separate desktop window never appears in it. Same trap applies to Xbox
Game Bar (`Win+Alt+PrtScn`) and to OBS **Game Capture**: all three photograph the game, not
the screen.

**Capture the screen, not the game.** These work:

- `PrtScn` (whole screen to clipboard) then paste into Paint and save. Free, already
  installed, and it does not steal focus.
- ShareX with a hotkey bound to **Capture entire screen**. Not "Capture region".
- OBS with **Display Capture** (never Game Capture), using the Screenshot Output hotkey.

**Do not use `Win+Shift+S`.** The overlay hides itself whenever Hearthstone is not the
foreground window (`ui/base.py:777` — visible only when the foreground window is
Hearthstone or one of the overlay's own windows). The Snipping Tool overlay takes focus, so
every window vanishes a moment before the shot. Any region-select tool has the same
problem. Take one throwaway shot and confirm before spending a session on this.

**Two more setup steps before the capture session:**

1. Hearthstone in **borderless windowed**, so nothing can draw over exclusive fullscreen
   and so the taskbar stays covered.
2. Run `python collect.py --local-feed` first. With no stats source the pick windows name
   every option but show "no data", and the shop stars fall back to comp-core membership
   only. The local feed fills them from your own finished games, so the shots show a tool
   that does something. If a shot ends up showing numbers, say in the caption that they
   came from your own games via `collect.py --local-feed` — the post's whole argument is
   that no stats ship bundled, and a screenshot full of numbers undercuts it unless it is
   labelled.

**Anonymity, every single shot.** Three things must never survive to the post: the opponent
nameplate (top-left), your own account name (bottom-left), and the wall clock next to it.
In tonight's 1899x1000 captures all three sat at x < 165. Crop the left edge at x = 265 and
they are gone with room to spare, and the leaderboard rail survives (it shows portraits,
never names). At 1920x1080 crop at x = 270. Crop them out, never blur them.

---

## The shots

Numbered to match the six `[IMAGE: ...]` placeholders in `docs/REDDIT_POST.md`, plus three
that the post would be better with.

### 1. The hero shot: whole game, windows down both edges

**CAPTURED — `overlay-full-game.png`** (1892x918, 1.77 MB, source t=720s, turn 8).
Five windows at once: SESSION top left, TAVERN with stars and `roll 32`, COUNTERS with
`1/10g · T4 · BST 5 · PIR 1 · 2 triples · trinket in 1`, the MINIONS bar, and the comps
window down the right edge. Cropped to height 918; the nameplate band is covered by SESSION.

*Placeholder: `REDDIT_POST.md` line 21.*

**Moment:** mid-recruit, turn 6 or later, right after the shop rolls, with the mouse away
from every card so no tooltip is covering anything.

**What must be in frame:** the right edge carrying COUNTERS, TAVERN and the comps window
stacked in their bands, and the left edge carrying the minion-browser bar and the SESSION
window. That is five windows at once and it is the most that are ever up outside a pick
dialog. Wait until the counters strip has real values in it (turn 6+ means gold, tier
price, tribe counts and triples are all populated rather than dashes).

**Why turn 6+:** early turns leave half the counters as dashes, which reads as broken
rather than as honest.

### 2. Counters and session, mid run

**PARTIAL — `counters-session-strip.png`** (1892x234, 0.38 MB, source t=720s).
A top strip carrying SESSION, TAVERN and COUNTERS in one frame. **The session half is
short of the brief:** this was the first game of the sitting, so SESSION reads "no finished
games yet this session" instead of listing placements. To fill that properly, record a
second or third game in one sitting and re-cut this strip.

*Placeholder: line 44.*

**Moment:** any recruit phase from turn 8 on, tight crop on the two windows rather than the
whole screen.

**What must be in frame:** COUNTERS showing turn, gold now and max, tavern tier with the
next tier's live price, gold banked for next turn, elemental / Blood Gem buffs, board tribe
counts, free rerolls, triples, turns until the next trinket. SESSION showing at least two
finished games with placement and hero, which means it has to be the second or third game
of one sitting — the window only knows games that finished while it was running.

**Trap:** the counters strip holds everything written during a fight until the shop returns,
so take this in the shop, not during combat.

### 3. Minion browser, open and filtered

**CAPTURED — `minion-browser-open.png`** (660x800, 0.39 MB, source t=145s).
`MINIONS · 274 in the pool`, the TIER / TRIBE / TRAIT filter rows, fourteen rows with art,
tribe chips and tier, the pager reading `1-14 of 29`, and `no stats source` at the foot.
TAVERN and COUNTERS sit above it in the same crop. **Filtered on tribe only** (BST) with
TIER left on `all`, so it is one filter short of the brief's "tier 4 + Beast" framing. The
row count changing from 274 to 29 still proves the filter is real.

*Placeholder: line 46.*

**Moment:** any time, but click the browser bar open first — it sits as a one-line bar until
clicked.

**What must be in frame:** the pool filtered to one tavern tier and one tribe at the same
time (tier 4 + Beast, or tier 5 + Undead), enough rows visible to show the filter is real,
and card text plus art on the rows. If art is missing run `python fetch_art.py` before the
session.

### 4. Hero select with all four badges

**PARTIAL — `hero-select-picks.png`** (1892x830, 1.18 MB, source t=22s).
All four portraits, the PICK YOUR HERO window bottom left naming every option, SESSION with
the lobby tribe chips, and the comps window on the right. **Only one badge is drawn**
(`7.00 best` over Al'Akir) because only one of the four heroes had any data in the local
feed; the other three read "no data at this MMR". Honest, but it is not the four-badge shot
the brief asked for. A real stats source, or a fuller `collect.py --local-feed`, would fill
the other three.

*Placeholder: line 56.*

**Moment:** the hero-select screen itself, after the badges have settled. Badges are drawn
above the four portraits, so wait a beat — the client shuffles the cards after they first
appear and the overlay corrects the badge order when it does.

**What must be in frame:** all four portraits, a badge above each one, and the hero-pick
window on the left edge. If the memory reader is built, this is also the shot where the
comps window shows the exact lobby tribes, which is worth having in the same frame.

**Trap:** SESSION shares that left band and steps aside for the hero window, so do not
expect both in this shot — that is by design and shot 2 covers session.

### 5. Comps window, curated, zero setup

**CAPTURED — `comps-curated.png`** (330x462, 0.12 MB, source t=300s).
Tight crop on the comps window alone: tribe chips, `YOUR BOARD (6) · beast summons
(curated) 2/6`, six comp rows every one of them labelled "curated", and the `dragon attack`
row clicked open showing its eight core minions. No measured percentages, which is exactly
the zero-setup state the shot is meant to prove.

*Placeholder: line 79.*

**Moment:** early recruit, turns 2 to 4, **with `sources.json` absent or renamed** so the
curated fallback is what renders.

**What must be in frame:** the tribe chips for the lobby, the comp rows, and the word
"curated" legible on the rows. Click one row open so the core minions and their percentages
show. This is the shot that proves the tool does something useful with no data configured,
so it has to be taken in that state — if a stats source is live the rows show measured
numbers and the shot no longer makes the point.

**Order note:** take this one BEFORE running `collect.py --local-feed`, or move
`sources.json` aside for it.

### 6. Combat odds with the BETA chip

**CAPTURED — `combat-odds-beta.png`** (1200x580, 0.94 MB, source t=776s).
`COMBAT · round 8` with `ODDS [BETA] W 37% / T 14% / L 50%`, `3,000 simulated fights`,
`log-only sim`, over a live 7-versus-4 swing with damage numbers flying. Exactly the
persuasive split the brief asked for rather than a 99/0/1.

*Placeholder: line 96.*

**Moment:** during a fight, from turn 5 onward, while both warbands are on screen swinging.

**What must be in frame:** the COMBAT window with the round number and the ODDS line —
BETA chip, then win / tie / loss — with the fight visible behind it.

**Timing:** the log hands both boards over about 1.4 seconds before the fight animates, so
the odds line is already up when the first attack plays. You have the whole 20 to 30 second
fight to take the shot. Rounds 1 and 2 will show nothing at all, correctly, because the
enemy board is genuinely empty then.

**Pick a fight with big boards.** A 6v6 with the odds reading something like 62 / 5 / 33 is
persuasive; 99 / 0 / 1 against an empty board is not.

### 7. Tavern window with the shop marked up

**CAPTURED — `tavern-shop-stars.png`** (1250x650, 1.03 MB, source t=720s).
The TAVERN window listing all six shop minions with star ratings and tier, the top row
tagged `pirate economy` as comp-feeding, `building beast summons (curated)` in the header,
`roll 32` at the foot, and the same six minions on the board underneath so the mapping is
obvious. COUNTERS is in frame too.

*Not yet in the post — worth adding next to the TAVERN bullet.*

**Moment:** recruit phase, right after a roll, tier 4 or 5 so the shop has six slots and the
minions are recognisable.

**What must be in frame:** the TAVERN window listing the shop in front of you with the
comp-feeding minions marked, and the same six minions visible on the game board underneath
so the mapping is obvious. If the local feed is running, the star ratings on the shop cards
belong in this frame too.

### 8. A pick dialog that is not hero select

**CAPTURED, twice.**

- `trinket-pick.png` (1600x918, 1.53 MB, source t=802s) — the game's Trinket Shop with all
  four trinkets, the PICK YOUR TRINKET window on the left naming every one of them, and the
  footer reading `NO TRINKET STATS CONFIGURED · names only - see sources.json`. That footer
  is the honest version of the post's whole bring-your-own-data argument.
- `discover-pick-one.png` (1300x700, 1.19 MB, source t=738s) — a Choose One discover with
  the PICK ONE window listing `3 options`, star ratings, tiers and a `beast summons` comp
  tag. TAVERN is still up alongside it, which is what proves the routing claim: two
  different windows, not one panel morphing.

*Not yet in the post.*

**Moment:** a trinket offer (the greater trinket around turn 8 is the safest to plan for),
or a Dark Gift / discover dialog.

**What must be in frame:** the trinket or discover window on the left edge naming every
option, and the game's own dialog on screen behind it. This shot proves the routing claim —
that each dialog type gets its own window instead of one panel morphing.

**Trap:** while a pick dialog is up the shop star badges are hidden on purpose so stale
tavern ratings do not sit behind the pick. That is correct behaviour, not a missing feature.

### 9. The whole desktop, once, for the "it does not cover your screen" question

**STILL MISSING as its own asset.** `overlay-full-game.png` covers the argument (every
window sits in a band outside the play area) but it is the Hearthstone window cropped at
1892x918, not the desktop with a taskbar and a second monitor. If a reply needs the literal
"does it cover my screen" answer, reuse shot 1 rather than re-shooting; a true desktop shot
would need a fresh capture with the taskbar visible, and the taskbar leaks the clock.

**Moment:** any recruit phase, full screen, uncropped except for the nameplates.

**Point:** every window sits outside the play area in its own band. Someone always asks
whether it blocks the board. One picture ends that thread.

---

## The GIFs

**THREE ARE CUT.** The one-loop idea below was split into three shorter loops, because a
single 18-second turn could not be held under the size ceiling at a readable width, and
because each of the three carries one argument on its own.

| File | Size | Frames | Source | What it shows |
|---|---|---|---|---|
| `tavern-reroll.gif` | 780x335, 2.06 MB | 72 @ 12 fps (6.0 s) | t=727.0-733.0 | TAVERN listing the shop at `roll 32`, the Refresh tooltip, the shop rolling, then the window rebuilding to the new six at `roll 33`. The list follows the shop with no lag. |
| `combat-odds-appear.gif` | 760x397, 3.87 MB | 90 @ 12 fps (7.5 s) | t=763.5-771.0 | Recruit with TAVERN and COUNTERS up, the Combat banner, TAVERN closing itself, COMBAT opening with `ODDS [BETA] W 37% / T 14% / L 50%` already on screen before the first attack, then the fight. |
| `trinket-panel-opens.gif` | 800x339, 3.05 MB | 70 @ 10 fps (7.0 s) | t=796.5-803.5 | The fight ending, COMBAT closing on its own, the Recruit banner, TAVERN rebuilding, then the Trinket Shop opening and PICK YOUR TRINKET appearing with `NO TRINKET STATS CONFIGURED`. |

All three were built with a proper `palettegen` / `paletteuse` pass (`stats_mode=diff`,
`dither=bayer`) rather than a flat conversion, which is what keeps them legible at these
sizes. Each is well under the 8 MB ceiling, so there is headroom to go wider or longer.

**Anonymity on the GIFs is geometric, not per-frame luck.** None of the three crop
rectangles intersects the name rectangle (x 0-170, y 918-990) or the nameplate rectangle
(x 0-340, y 40-80): the reroll and combat loops start at x 385 and x 388, and the trinket
loop starts at y 120. Frames were also sampled and eyeballed across each loop.

**If the single long loop is still wanted**, the raw material is there: t=763 to t=805 in
`bg help.mp4` is one uninterrupted fight-to-shop-to-trinket cycle.

---

## The original GIF plan (superseded, kept for the recipe)

**One turn, start to finish.** Roughly 18 to 20 seconds, looping:

fight starts → COMBAT window opens with the ODDS line and the BETA chip → the fight
resolves → the shop comes back → COMBAT closes on its own → TAVERN rebuilds with the new
shop → COUNTERS ticks the turn and the gold.

That single loop is the entire argument of the post: the windows open and close on their
own, and nothing stale is ever left on screen. It is worth more than any of the stills.

**How to record it:**

1. OBS Studio, source = **Display Capture**. Not Game Capture — Game Capture photographs
   the game and the overlay will not be in the recording, the same failure as the in-game
   screenshot key.
2. Output 1920x1080, 30 fps, MP4. Start recording during the fight before the one you want,
   so the clip is not front-loaded with fumbling.
3. Do not touch OBS while recording. Bind start/stop to a hotkey — clicking into OBS makes
   Hearthstone lose focus and every window disappears from the recording.
4. Trim and convert with ffmpeg, cropping the nameplates out in the same pass:

```
ffmpeg -ss 00:00:04 -t 18 -i clip.mp4 \
  -vf "crop=1650:1010:270:30,fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  -loop 0 turn-loop.gif
```

`crop=1650:1010:270:30` takes a 1650x1010 window starting 270 px from the left, which drops
the opponent nameplate, your account name and the clock in one move. Check the first and
last frame of the output before posting.

5. Keep it under about 8 MB. If it is bigger, drop to `fps=10` or `scale=800:-1`. Reddit
   re-encodes GIFs to video anyway, so a smaller GIF costs nothing visually.

**Anonymity check on the GIF specifically:** a video is 200+ chances to leak instead of one.
Scrub the output frame by frame at the start, at the shop transition and at the end before
it goes anywhere near the post.

---

## What is in this folder right now

### Post-ready, overlay visible, anonymised, metadata stripped

Cut from `bg help.mp4` on 11 August. Every one of these was opened and read back after
export to confirm no account name, no opponent name and no wall clock survived.

| File | Size | Shot | Placeholder it fills |
|---|---|---|---|
| `overlay-full-game.png` | 1892x918, 1.77 MB | 1 | REDDIT_POST line 27 |
| `counters-session-strip.png` | 1892x234, 0.38 MB | 2 (partial) | REDDIT_POST line 50 |
| `minion-browser-open.png` | 660x800, 0.39 MB | 3 (tribe filter only) | REDDIT_POST line 52 |
| `hero-select-picks.png` | 1892x830, 1.18 MB | 4 (one badge, not four) | REDDIT_POST line 62 |
| `comps-curated.png` | 330x462, 0.12 MB | 5 | REDDIT_POST line 85 |
| `combat-odds-beta.png` | 1200x580, 0.94 MB | 6 | REDDIT_POST line 102 |
| `tavern-shop-stars.png` | 1250x650, 1.03 MB | 7 | new, next to the TAVERN bullet |
| `trinket-pick.png` | 1600x918, 1.53 MB | 8 | new, next to the pick-windows bullet |
| `discover-pick-one.png` | 1300x700, 1.19 MB | 8 | new, spare / reply comment |
| `tavern-reroll.gif` | 780x335, 2.06 MB | GIF | new |
| `combat-odds-appear.gif` | 760x397, 3.87 MB | GIF | new, next to the odds section |
| `trinket-panel-opens.gif` | 800x339, 3.05 MB | GIF | new, spare / reply comment |

A copy of all twelve is also kept outside the repo, in the local upload folder used for the
post.

### Still open

1. **A second or third game in one sitting**, so SESSION actually lists finished games with
   placement and hero. That is the only thing shot 2 is missing.
2. **A stats source or a fatter local feed**, so hero select shows four badges instead of
   one and the browser rows carry star ratings.
3. **Tier plus tribe together** in the minion browser (the capture has tribe only).
4. **A literal whole-desktop shot** if the "does it cover my screen" reply ever needs one.

### Older plates, no overlay in them

`game-tavern-shop.png`, `game-tavern-full-board.png`, `game-combat-boards.png`,
`game-combat-wide.png` — four anonymised, metadata-free crops of the 11 August stills
session.

**They show no overlay.** They are clean game-context plates and nothing more. They are
usable as illustration of a moment; they cannot be posted as evidence that the overlay
works, and they should not be captioned as if they were. The twelve files above supersede
them for every purpose in the post.
