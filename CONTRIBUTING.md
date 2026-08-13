# Contributing

Help is welcome - [ROADMAP.md](ROADMAP.md) lists what's open, sized, and why
the not-built things aren't built. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
is the map of how it all fits together, including every log-parsing gotcha we
know about; read it before touching the parser.

## Setup

- Python 3.10+ on Windows. The core has **zero pip dependencies**.
- `pip install pillow` (optional) + `python fetch_art.py --all` if you want
  real card portraits in the overlay; it degrades to colored dots without.
- The overlay itself is Windows-only (tkinter + Win32 window anchoring). The
  parser and tests run anywhere.

## Tests - run the offline ones before a PR

```bash
python tests/test_regression.py
```

Fully offline, must print `PASS`. This is what CI runs. Two contracts in one
file: `tests/fixture.log` is one real day of play (19 games), and the parser
must find **exactly 19 hero offers and 36 trinket offers** (trinkets near 137
means the four-option rule broke and opponent trinket reveals are leaking in);
and `data/hero_tips.json` is validated entry by entry, including that coverage
has not fallen below the 121 heroes that have a line today.

The rest are offline too, each pinning down one thing, and all of them run in
seconds. Run the ones your change touches, or all of them if you are not sure:

```bash
python sim/engine.py                # the combat sim's own inline tests
python tests/test_settings.py       # settings store, panel, window geometry, pooling
python tests/test_comproles.py      # comp roles, and that drawing never hits the network
python tests/test_tribes.py         # a lobby's tribes, counted only from what proves them
python tests/test_badges.py         # click-through, calibrate mode, the turn-by-turn split
python tests/test_tips.py           # hero tip submissions, votes, publish floors
python tests/test_dcrc.py           # the reconnect tool's Win32 structs
python tests/test_logsdir.py        # where the Hearthstone logs are looked for
python tests/test_stats_engine.py   # every stats table's parser and its fallbacks
python -m ruff check --select E9,F63,F7,F82 .
```

Two more need something the repo cannot ship:

```bash
python tests/test_live.py
python tests/test_windows.py [<Power.log> ...]
```

`test_live.py` exercises the live path - tail-follow, mid-run log rotation -
against a fake Logs dir, and fetches the card database once (cached a day).
`test_windows.py` replays a **real** `Power.log` through the real Reader,
Router and windows and compares against what it measured in that log first; it
skips cleanly when you have no logs, because real logs are player data and are
not in the repository.

## Hero tips - the easiest thing to contribute

The overlay prints one line of advice under each hero in the draft. Those lines
live in [`data/hero_tips.json`](data/hero_tips.json), they are plain text, and
**a pull request is how they get added, improved or thrown out**: open a PR,
argue it in the diff, the better wording wins. All 121 heroes have a line
already, so the work now is making them better, not filling gaps.

There is a second route, for people who will never open a pull request:
`server/tips.py` takes submissions and votes and publishes a community feed the
client reads like any other source. It does not replace this file. A submitted
line only reaches the feed once distinct voters, its score and a margin over the
shipped line have all cleared a floor, and the draft marks such a line `▲` so a
voted stranger's wording is never mistaken for a reviewed one. A voted line that
survives is a good candidate for a PR into this file, which is where it becomes
the default for everyone.

### The schema

[`data/hero_tips.schema.json`](data/hero_tips.schema.json) is the contract and
describes every field. One entry per hero cardId:

```json
"BG26_HERO_101": {
  "name": "Cap'n Hoggarr",
  "when": "Pirates are in the lobby",
  "bullets": [
    "Each Pirate you buy hands 1 gold straight back",
    "Chaining Pirate buys in one turn is the whole plan"
  ],
  "tribes": ["PIRATE"]
}
```

- `when` - **one line: when this hero is good.** This is the line that appears
  in the draft, so it has to stand alone and stay short. Past about 50
  characters it is truncated on screen. No trailing full stop.
- `bullets` - one to three short notes (how to play it, what it needs, what it
  costs). Not drawn in the draft window today; this is the detail half of the
  entry.
- `tribes` - optional, and only when the hero's own printed power really is
  tribe-locked. Uppercase, as Hearthstone spells them.
- `name` - informational. The app looks the hero up by cardId; the name is
  there so a human can grep the file.

The key is the hero's cardId as HearthstoneJSON gives it - the same ids
`bgtracker.bg_ids()["heroes"]` returns, e.g. `BG26_HERO_101`. To find one:

```bash
python -c "import bgtracker as bg; print([c for c, n in bg.card_names().items() if n.startswith('Cap')])"
```

### The one hard rule: original text only

Every line in that file must be **your own words, or someone else's words given
to this repo under its licence** (MIT - opening a PR is you licensing it). Do
not copy, re-word, translate or run another site's hero guide through a model.
Those guides are somebody's paid work; taking them is theft, and the fastest
way to get this project taken down.

Writing from the hero's own printed hero-power text is always safe. That is
where every line in the file came from. The awkward ones are the powers that
name a reward the card never explains (a Quest, a Timewarp, a Darkmoon Prize):
those lines were held back for a long time, and what unblocked them was writing
about what the card **does** say - what the power costs, when it pays out, what
it asks of you - and stopping where the card stops. Do that rather than
inventing the reward, and if you cannot, leave the entry out: the draft shows
nothing at all for a hero with no tip, no placeholder and no "no tip yet", which
is a perfectly good outcome. Same rule for numbers - this file is advice, not
statistics. Do not paste placement averages into it from anywhere.

### Submitting one

1. Edit `data/hero_tips.json`. Keep entries in alphabetical order by hero name,
   and keep the file `json.load`-able (trailing commas are not JSON).
2. Run `python tests/test_regression.py`. It validates this file offline:
   unknown cardId, missing `when`, too many bullets, an unknown tribe, an
   over-long line, or coverage falling below where it stands all fail, so CI
   catches a broken tip before a human reads it.
3. Open the PR. One hero per PR is easiest to argue about; a batch is fine when
   the tips belong together (all the Pirate heroes, say).
4. Improving an existing tip is exactly as welcome as adding a missing one. Say
   in the PR *why* the new wording is better - "it is wrong above 8000 MMR"
   beats "it reads nicer".

## Ground rules

- **Read-only, always.** The tool never injects code, modifies the client,
  drives the game, or automates decisions. Don't send PRs that do.
- **Log-first.** Anything that works from `Power.log` ships as default.
  Memory-derived features go through the opt-in `native/msync` helper and
  must degrade gracefully when it isn't built.
- **No bundled third-party stats.** The repo ships code, not other people's
  collected data. The one feed it points at is **our own community pool**,
  built only from games players share (the default since 2026-08-12, off
  switch in the settings panel) and free for everyone. A user's
  `sources.json` replaces it entirely. Don't send PRs that hardcode anyone
  else's stats feed.
- **Zero required dependencies** is a feature. A new runtime dependency needs
  a strong case.
- **Count against reality, not against a slice.** The two subtlest bugs so far
  (opponent-trinket noise, entity re-statements) both passed small-slice tests
  and only showed up when a whole day's replay was checked against how many
  offers a real day actually contains. If you touch detection logic, validate
  against full real logs, and if you find a new invariant, encode it in a test.

## Style

- Match the existing voice: comments explain the non-obvious **game/log
  facts** (why the code must be this way), not what the code does.
- Keep the layout flat, one job per place: `bgtracker.py` = log parsing and the
  stats tables, `overlay.py` = the reader and the router and nothing that
  draws, `ui/` = one module per window plus `ui/base.py` for the shared
  drawing and the badge strips, `sim/` = the combat simulator and its
  validation harness, `collect.py` = mining your own finished games,
  `pool.py` = sharing them, `settings.py` and `update.py` = the settings store
  and the update channel, `server/` = the aggregator, the upload endpoint and
  the tips feed, `tools/` = generators for the docs, `native/msync` = the
  optional memory reader. A new window is a new module in `ui/` plus a line in
  its registry, and nothing else in the overlay has to change.

