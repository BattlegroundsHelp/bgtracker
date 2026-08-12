# Changelog

## v0.3.1-alpha (12 August 2026)

- **Community sharing is now ON BY DEFAULT, and this is a change of an
  earlier promise.** Until now every copy surface said uploading was opt in
  and off by default. The author changed that default on 12 August 2026,
  because a pool nobody feeds shows everybody thin numbers forever. Plainly:
  unless you switch it off, the overlay now sends one anonymised record per
  finished game to the community feed - your whole log history once, shortly
  after start, then each game as it ends, and a last attempt when you quit.
  The record holds exactly what it always held (the settings panel lists
  every field: scrambled game id, date, hero, placement, Duos or not, lobby
  tribes, the offers, the picks, an opaque per-install id, the client
  version - no name, no battletag, no log files). **The off switch:** untick
  "Share my finished games" in the settings panel's DATA section (saved), or
  start with `--no-upload` (that run only, writes nothing). The aggregates
  stay free for everyone and are never sold or paywalled, whether you share
  or not. `collect.exe` remains as the by-hand path.
- **The community feed is now the default stats source.** With no
  `sources.json`, the overlay reads the community tables (the same URLs
  `sources.example.json` documents), so a fresh install shows numbers and
  gives games back with zero setup - both halves of the same default. Writing
  your own `sources.json` replaces it entirely, exactly as before; nothing is
  written to disk on your behalf.
- New module `pool.py` does the sending: incremental (a ledger in
  `data/uploaded.json` remembers what was sent, so nothing uploads twice),
  throttled to one request every 2 seconds (a quarter of the server's own
  rate limit), quiet on failure (a dead server means "try again at the next
  game", never an error in your face), and always off the UI thread -
  quitting waits at most about 2 seconds for a send in flight.

## v0.3.0-alpha (12 August 2026)

Nearly all of it was asked for in the r/BobsTavern thread.

### Added

- **A settings panel, and it opens when the tool starts.** A normal window you
  can move, scroll and close, not one of the click-through overlay surfaces.
  Four sections. DISPLAY: one UI scale for everything, automatic from the game
  window or a slider you drag, applied while you drag it rather than on the next
  start, plus a nudge for the badges printed on the cards. That is the fix for a
  4K screen, where the whole overlay used to draw at half the size it should.
  DATA: the sharing opt-in, off by default, with one line saying exactly what
  leaves the machine and that the pooled numbers stay free; which feed the
  numbers come from; the MMR bracket, the period, and Duos. WHAT TO SHOW: one
  switch per overlay window, generated from the window registry so a window
  added later appears on its own. A window switched off is not built at all: no
  panel, no badges, nothing routed to it, and switching it back on is live.
  UPDATES: the version, when it was last checked, check now, and what changed
  plus install when there is something newer. Rows that cannot take effect until
  the next start say so. Choices live in `settings.json` beside `sources.json`;
  a flag on the command line beats the file for that run and is never written
  back to it. `--no-panel` starts without it, and the gear in the bgtracker
  window's header reopens it.
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
- **It can tell you there is a new version.** On start it fetches a 200 byte
  manifest from the stats server, on its own thread, and prints one line if
  there is a newer build. It never installs anything on its own: the build is
  unsigned, and swapping out a folder somebody extracted by hand without asking
  is not on. Downloading and installing happen when you ask, and the download is
  refused unless its SHA-256 and its size both match what was published. Your
  collected games, card art, window positions and `sources.json` are carried
  across, and the previous install is kept until the new one has run once.
  `--no-update-check` turns the check off; `BGTRACKER_NO_UPDATE_CHECK=1` and
  `{"check_on_start": false}` in `data/update.json` do it permanently. Details
  in [docs/USAGE.md](docs/USAGE.md) section 2c.
- **The version now exists as a number the program knows.** It was only ever a
  CHANGELOG heading and a git tag before. `--diag` prints it, uploads carry it
  so the server can tell which builds are in the wild, and the build writes it
  into `version.txt` inside itself so a release manifest cannot describe a
  different build than the one it points at.
- **Card effects catalogue.** `python tools/catalog.py` generates
  [`docs/CARD_EFFECTS.md`](docs/CARD_EFFECTS.md) from the live card database,
  so it is always this patch's pool. Of 274 pool minions, 39 act during combat,
  141 have already resolved before both boards are read, 94 do nothing in a
  fight. The 141 are listed as do-not-script. Work queue: 18 cards.

### Changed

- **Combat odds: about 86% winner accuracy over 339 logged fights** (MAE 13pp,
  Brier 0.072, the release's final measure). Read the jump from 82.5% carefully:
  that number came from 251 fights, and the same unchanged code scores 85.7% on
  the larger sample. The jump is the sample, not the code.
- Six more in-combat effects modelled: Fish of N'Zoth, Plaguerunner, Forest
  Rover's Beetle counter, Reborn copies inheriting side-wide grants, goldens
  read off the golden card instead of guessed by doubling, and manual scripts
  merging with derived ones per hook instead of replacing them. **Measured
  worth: one extra correct fight out of 343.** Accuracy 85.7% to 86.0%, Brier
  0.0784 to 0.0771. A null result on accuracy, a small calibration gain.
- Nine more in-combat scripts, each read off the card's own text: Kangor's
  Apprentice, Sewer Lord, Leeroy the Reckless, Motley Phalanx, Scarlet Skull,
  Eternal Summoner (a board-visible floor, like Forest Rover), Turquoise
  Skitterer, golden Wildfire Elemental splashing both neighbours, golden
  Deflect-o-Bot gaining +4. Pre-BG25 goldens now resolve under their real
  `TB_BaconUps_*` ids instead of only `_G`, and cleave is derived from both
  printed wordings. The sim can now also say how hard a fight hits: damage
  bands that include the hero's tavern tier, plus the chance this fight kills
  you (or them), widened the same way as the odds so they never print 0% or
  100%. Measured on the same 339-fight harness, identical seeds: Brier 0.0752
  to 0.0720, MAE 13.8pp to 13.2pp, accuracy 86.1% to 85.8% (one net fight,
  two gained and three lost). Same lesson as last time: scripts buy
  calibration, not accuracy.
- **Dark Gifts are complete.** All 40 accounted for: 24 grant only stats or
  keywords (already on the minion when the board is read, so modelling them
  again would make the sim worse), 9 change your cards not the fight, 6 fire
  during combat and are modelled, 1 can no longer be offered. Gap: zero.

### Fixed

- The Dark Gift miner looked for `tag=ATTACHED` and found nothing across 1.3 GB
  of logs. The signal is `DARK_GIFT_ENTITY`, which `sim/boards.py` was already
  reading correctly.
- The card effects catalogue counted only hand-written scripts, so five cards
  whose printed text already derives a working script (token summons, cleave)
  sat in the work queue as if they were missing. With those counted and this
  batch's new scripts, the queue stands at 18 cards, down from 33.
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
