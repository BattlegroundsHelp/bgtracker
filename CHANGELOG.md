# Changelog

## Unreleased

On `main`, not in a release build yet. Nearly all of it was asked for in the
r/BobsTavern thread.

### Added

- **OTHER PLAYERS window.** Every other player in place order with hero, tavern
  tier and health. For anyone you have fought, the board they were last seen
  holding, stamped with the round and how long ago. Click a player to open it.
  A player you have not fought shows no board, not a guess. Needs the optional
  memory reader; the log does not state opponent boards during recruit.
- **Hero tips at the draft.** One line per hero saying when it is the pick.
  111 of 121 heroes. In `data/hero_tips.json`, fixable by pull request. The ten
  missing are heroes whose power names a reward the card never describes.
- **Duos as its own dataset.** Marked solo or Duos from the log
  (`BACON_DUO_TEAM_ID`), agreeing with the game's own mode line on 33 of 33
  games. Separate feed for heroes, trinkets, cards and comps. `--duo` reads it.
  No pooling and no fallback to solo: Duos places 1st to 4th, solo 1st to 8th.
- **MMR brackets in the feed.** The aggregator publishes each bracket
  (`--mmr 100|50|25|10|1`) as its own files, stamped with the bracket and the
  rating cut used. A bracket is published only once it holds 30 games; until
  then the client reads the all players file and says so instead of labelling
  the whole pool "top 1%". Old file names still written, so existing
  `sources.json` files keep working.
- **Card effects catalogue.** `python tools/catalog.py` generates
  [`docs/CARD_EFFECTS.md`](docs/CARD_EFFECTS.md) from the live card database,
  so it is always this patch's pool. Of 274 pool minions, 39 act during combat,
  141 have already resolved before both boards are read, 94 do nothing in a
  fight. The 141 are listed as do-not-script. Work queue: 33 cards.

### Changed

- **Combat odds: 86% winner accuracy over 343 logged fights** (MAE 14pp, Brier
  0.077). Read the jump from 82.5% carefully: that number came from 251 fights,
  and the same unchanged code scores 85.7% on today's 343. The jump is the
  sample, not the code.
- Six more in-combat effects modelled: Fish of N'Zoth, Plaguerunner, Forest
  Rover's Beetle counter, Reborn copies inheriting side-wide grants, goldens
  read off the golden card instead of guessed by doubling, and manual scripts
  merging with derived ones per hook instead of replacing them. **Measured
  worth: one extra correct fight out of 343.** Accuracy 85.7% to 86.0%, Brier
  0.0784 to 0.0771. A null result on accuracy, a small calibration gain.
- **Dark Gifts are complete.** All 40 accounted for: 24 grant only stats or
  keywords (already on the minion when the board is read, so modelling them
  again would make the sim worse), 9 change your cards not the fight, 6 fire
  during combat and are modelled, 1 can no longer be offered. Gap: zero.

### Fixed

- The Dark Gift miner looked for `tag=ATTACHED` and found nothing across 1.3 GB
  of logs. The signal is `DARK_GIFT_ENTITY`, which `sim/boards.py` was already
  reading correctly.
- The stats cache key ignored which source a table came from, so pointing
  `sources.json` at a different server kept serving the old server's numbers for
  up to an hour.
- `data/` was ignored wholesale, so the hero tips file could never have reached
  the repository.
- The upload endpoint rejected every Duos game: its hero pattern had no digits
  to match in `BGDUO_HERO_223`.

### Known limits

- Of 48 wrong odds calls, 13 were fights that really tied. Boards where every
  card is modelled are called right 91.3% of the time; boards with at least one
  unmodelled card, 82.9%. Rounds 5 to 8 are the worst stretch at 80.5%.
- The long tail of unmodelled cards is the error. Per-card scripting has a low
  ceiling because the remaining cards are individually rare.

## v0.2.0-alpha (11 August 2026)

No Python needed, one window per thing, and the shared stats server is live.

### Added

- **Standalone Windows build.** Download the zip from Releases, unzip, run
  `bgtracker.exe`. No Python, no pip, no install. Four tools inside: the
  overlay, the console version, the collector, the art fetcher.
- **COUNTERS window.** Turn, gold now and max, your tier and what the next one
  costs, gold banked for next turn, buffs, your board's tribes, triples, turns
  until the next trinket. Anything the game has not stated shows a dash.
- **MINIONS window.** The whole current pool, filtered by tier, tribe or
  mechanic. Needs no stats source.
- **SESSION window.** Rating now versus when you sat down, and every game that
  finished while the overlay was running.
- **Shared stats server.** Uploading is opt in and off by default, records are
  anonymised (hero, placement, lobby tribes, board), aggregates are free for
  everyone and never sold or paywalled. `collect.py --upload <url>` shares;
  `collect.py --local-feed` keeps everything local.
- The collector now mines which heroes and trinkets you were **offered**, not
  just what you took, which is what makes pick rate computable.

### Changed

- **One window per thing.** The single morphing panel became ten independent
  windows, each with its own trigger, dismissal and remembered position. Every
  bug of that era came from one state machine trying to be several surfaces.
  TAVERN used to go stale; COMBAT used to lag a fight behind and linger over
  the shop.
- **Combat odds: 82.5% winner accuracy over 251 logged fights**, up from 76.5%.
  Brier 0.1006, down from 0.1409.
- **The odds no longer print 0% or 100%.** There are card effects the sim does
  not model, so claiming certainty was wrong.
- Comps no longer need a data source: with none configured the tool shows
  curated families whose core minions are computed from the live card pool.
- `bgtracker.bat` says plainly when Python or tkinter is missing instead of
  flashing a window and vanishing.

### Fixed

- The collector attributed games to the wrong player in lobbies full of real
  accounts, so most placements were wrong. It now keys off the hero draft, the
  one signal that proves which player is you.
- Board count was read from the combat copy mid-fight, showing dead minions as
  missing. The board is now read only during recruit.

### Known limits

- Windows only.
- Windows warns on first launch because the build is unsigned.
- The shared feed is new, so most rows are flagged thin. Thin means no signal,
  not weak signal.
- Uploads are unauthenticated by design (an open-source client cannot keep a
  secret), so the endpoint is rate limited and the data is validated.
- The memory reader is an optional separate build, never bundled. It is the one
  part that touches the letter of Blizzard's EULA.
