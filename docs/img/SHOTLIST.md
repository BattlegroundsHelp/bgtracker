# Screenshot shot list for the beta-test post

What still has to be captured from the **ten-window build**, and the exact moment in a game
to catch each one.

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

*Placeholder: line 46.*

**Moment:** any time, but click the browser bar open first — it sits as a one-line bar until
clicked.

**What must be in frame:** the pool filtered to one tavern tier and one tribe at the same
time (tier 4 + Beast, or tier 5 + Undead), enough rows visible to show the filter is real,
and card text plus art on the rows. If art is missing run `python fetch_art.py` before the
session.

### 4. Hero select with all four badges

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

*Not yet in the post — worth adding next to the TAVERN bullet.*

**Moment:** recruit phase, right after a roll, tier 4 or 5 so the shop has six slots and the
minions are recognisable.

**What must be in frame:** the TAVERN window listing the shop in front of you with the
comp-feeding minions marked, and the same six minions visible on the game board underneath
so the mapping is obvious. If the local feed is running, the star ratings on the shop cards
belong in this frame too.

### 8. A pick dialog that is not hero select

*Not yet in the post.*

**Moment:** a trinket offer (the greater trinket around turn 8 is the safest to plan for),
or a Dark Gift / discover dialog.

**What must be in frame:** the trinket or discover window on the left edge naming every
option, and the game's own dialog on screen behind it. This shot proves the routing claim —
that each dialog type gets its own window instead of one panel morphing.

**Trap:** while a pick dialog is up the shop star badges are hidden on purpose so stale
tavern ratings do not sit behind the pick. That is correct behaviour, not a missing feature.

### 9. The whole desktop, once, for the "it does not cover your screen" question

*Not yet in the post. One reply-comment asset.*

**Moment:** any recruit phase, full screen, uncropped except for the nameplates.

**Point:** every window sits outside the play area in its own band. Someone always asks
whether it blocks the board. One picture ends that thread.

---

## The GIF

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

`game-tavern-shop.png`, `game-tavern-full-board.png`, `game-combat-boards.png`,
`game-combat-wide.png` — four anonymised, metadata-free crops of tonight's captures.

**They show no overlay.** They are clean game-context plates and nothing more. They are
usable as illustration of a moment; they cannot be posted as evidence that the overlay
works, and they should not be captioned as if they were. Every shot above still needs to be
taken.
