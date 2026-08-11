# Changelog

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
