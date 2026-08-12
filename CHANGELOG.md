# Changelog

## Unreleased

Everything here is on `main` and not in a release build yet. It is the work
that came out of the r/BobsTavern thread: the things people asked for there,
answered one at a time.

### OTHER PLAYERS, the eleventh window

- The leaderboard as its own window: every other player in place order, their
  hero, their tavern tier and their health, and for anyone you have already
  fought, **the board they were last seen holding** with the round it was seen
  in and how long ago that was (`seen r7 · 2 rounds ago`). Click a player to
  open that board.
- A player you have not fought shows no board at all. Not an empty board, not a
  guess from their tier: nothing. The hero, tier and health are live every
  reading; only the board is historical, and only the board carries the stamp.
- This one is **memory only**. Power.log does not state another player's board
  while you are shopping, so without the optional memory reader the window
  never appears and nothing else in the overlay changes.
- Two things had to be measured rather than assumed. The seat that holds an
  enemy warband in memory also holds Bob's shop, so an early version reported
  the tavern as somebody's board; shop minions are now excluded by their
  drag-buy token. And a warband is whole in memory before a fight animates and
  again after it, but is being killed off during it, so the reading kept is the
  fullest one of that fight.

### Hero tips at the draft

- Each hero on offer can carry one line of advice under its name, saying when
  that hero is the pick. 111 of the 121 heroes have one. The ten without are
  the ones whose hero power names a reward the card itself never describes, and
  an empty line beats an invented one.
- The tips are a plain file, `data/hero_tips.json`, that ships with the tool.
  Anyone can add or fix one by pull request; that review is the voting
  mechanism until something better exists. `data/hero_tips.schema.json` is the
  contract and CI checks every entry against it, including that the hero
  actually exists.
- Every seeded line was written from the hero's own printed hero-power text.
  Nothing was taken from anyone else's guide, because those are that site's
  paid product.
- The line is drawn inside the row that was already there, replacing the
  placement bar, so the draft window is exactly as tall as it was before.

### Duos is its own dataset

- Every mined game is now marked solo or Duos from the log itself, off the
  `BACON_DUO_TEAM_ID` / `BACON_DUO_TEAMMATE_PLAYER_ID` tags. They agreed with
  the game's own mode line on 33 of 33 real games. Card ids do not work for
  this: `BGDUO_` heroes caught only four of six real Duos games.
- The aggregator writes a parallel Duos feed for heroes, trinkets, cards and
  comps, and `--duo` reads all four. **Nothing is pooled and there is no
  fallback to the solo tables**: a Duos lobby is four teams finishing 1st-4th
  where solo is eight players finishing 1st-8th, so one shared average would
  describe neither. Measured on real games: one hero read 2.0 pooled and 1.5
  solo-only.
- A game mined before this existed is marked neither, and is counted in neither
  feed rather than assumed to be solo. Re-running the collector fills it in.
- The upload endpoint used to reject every Duos game outright: its hero pattern
  had no digits to match in `BGDUO_HERO_223`.

### MMR brackets in the feed

- The aggregator now publishes each bracket the client already asks for
  (`--mmr 100|50|25|10|1`) as its own set of files, and stamps every file with
  the bracket it is and the rating cut it used.
- A bracket is only published once it holds 30 games, so on a young pool most
  of them do not exist yet. The client then reads the all-players file and
  **says which bracket the numbers actually came from** — it will not print
  pooled numbers under a "top 1%" heading. The file's own stamp wins over what
  was asked for.
- The old un-bracketed file names are still written, so an existing
  `sources.json` keeps working untouched.

### Fixed

- The stats cache key ignored which source a table came from, so pointing
  `sources.json` at a different server kept serving the old server's numbers
  for up to an hour, and a failed fetch silently fell back to a feed you were
  no longer using. Found while testing brackets, which is exactly the kind of
  wrong number this project treats as a bug.
- `data/` was ignored wholesale, so the hero tips file could never have reached
  the repository at all. Git does not look inside an excluded directory, so
  un-ignoring a file under one never fires.

## v0.2.0-alpha (11 August 2026)

The big one: **you no longer need Python**, the overlay is now a set of small
independent windows instead of one panel, and the **shared stats server is
live**, so the numbers come from real games instead of nowhere.

### No Python needed

- **Standalone Windows build.** Download the zip from Releases, unzip, run
  `bgtracker.exe`. No Python, no pip, no install. Four tools ship inside it:
  the overlay, the console version, the collector and the art fetcher.
- The `bgtracker.bat` launcher still works for anyone running from source, and
  now says so plainly when Python or tkinter is missing instead of flashing a
  window and vanishing.
- Windows will warn on first launch because the build is unsigned. That is
  expected; the source and the CI runs are there for anyone who wants to check.

### One window per thing

The overlay used to be a single panel that changed shape depending on what the
game was doing. Every bug of that era came from the same place: one state
machine trying to be several surfaces at once. It is now ten separate windows,
each with its own trigger, its own dismissal and its own remembered position.

- **TAVERN** rebuilds on every roll, buy and sell. It used to go stale.
- **COMBAT** shows the odds for the fight in front of you, opens when the fight
  starts and closes when the tavern comes back. It used to lag a fight behind
  and linger over the shop.
- **COUNTERS** (new): turn, gold now and max, your tier and what the next one
  costs right now, gold banked for next turn, buffs, your board's tribes,
  triples, turns until the next trinket. Anything the game has not stated shows
  a dash, never a zero.
- **MINIONS** (new): the whole current pool, filtered by tier, tribe or
  mechanic. Needs no stats source to be useful.
- **SESSION** (new): rating now versus when you sat down, and every game that
  finished while the overlay was running.
- **PICK YOUR HERO / HERO POWER / TRINKET / PICK ONE**: each choice gets its own
  window and its own badges on the cards, so nothing covers what you are reading.

### Combat odds are better and more honest

- Winner accuracy **82.5%** over 251 real logged fights, up from 76.5%.
  Brier score 0.1006, down from 0.1409.
- **It no longer prints 0% or 100%.** There are card effects it does not model,
  so claiming certainty was wrong.
- Added deathrattle buffs, on-attack (Rally) triggers, and Dark Gifts that grant
  triggers. Gifts that only change stats or keywords were already handled,
  because the game writes those onto the minion where the log can see them.
- `sim/validate.py` scores every prediction against your own logged fights and
  names the cards causing the most error, which is the work queue for next time.

### Shared stats, live

- The community server is up. Uploading is **opt-in**, records are anonymised
  (hero, placement, lobby tribes, board), aggregates are free for everyone, and
  the data is never sold or paywalled.
- `collect.py --upload <url>` shares your games. `collect.py --local-feed` keeps
  everything local and builds your own private feed instead.
- The collector now also mines **which heroes and trinkets you were offered**,
  not just what you took, which is what makes pick rate computable at all.
- `sources.example.json` points at the community feed. Copy it to `sources.json`.

### Fixes worth naming

- The collector attributed games to the wrong player in lobbies full of real
  accounts, so placements were wrong in most games. It now keys off the hero
  draft, which is the one signal that proves which player is you.
- Your board count was read from the combat copy mid-fight, which showed dead
  minions as missing. The board is now read only during recruit.
- Comps no longer need a data source: with none configured the tool shows
  curated comp families whose core minions are computed from the live card pool,
  so they are always current-patch.

### Known limits

- Windows only.
- The shared feed is new, so most rows will be flagged thin for a while. Thin
  means treat it as no signal, not weak signal.
- Uploads are unauthenticated by design (an open-source client cannot keep a
  secret), so the endpoint is rate limited and the data is validated. If the
  numbers ever look poisoned, say so and they get purged.
- The memory reader stays an optional, separate build. It is the one part that
  touches the letter of Blizzard's EULA, so it is never bundled.
