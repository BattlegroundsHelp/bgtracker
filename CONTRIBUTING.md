# Contributing

Help is welcome — [ROADMAP.md](ROADMAP.md) lists what's open, sized, and why
the not-built things aren't built. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
is the map of how it all fits together, including every log-parsing gotcha we
know about; read it before touching the parser.

## Setup

- Python 3.10+ on Windows. The core has **zero pip dependencies**.
- `pip install pillow` (optional) + `python fetch_art.py --all` if you want
  real card portraits in the overlay; it degrades to colored dots without.
- The overlay itself is Windows-only (tkinter + Win32 window anchoring). The
  parser and tests run anywhere.

## Tests — run both before a PR

```bash
python tests/test_regression.py
```

Fully offline, must print `PASS`. This is what CI runs. The contract:
`tests/fixture.log` is one real day of play (19 games), and the parser must
find **exactly 19 hero offers and 36 trinket offers**. Trinkets near 137 means
the four-option rule broke and opponent trinket reveals are leaking in.

```bash
python tests/test_live.py
```

Exercises the live path — tail-follow, mid-run log rotation — against a fake
Logs dir. Fetches the stats tables once (cached for an hour).

## Ground rules

- **Read-only, always.** The tool never injects code, modifies the client,
  drives the game, or automates decisions. Don't send PRs that do.
- **Log-first.** Anything that works from `Power.log` ships as default.
  Memory-derived features go through the opt-in `native/msync` helper and
  must degrade gracefully when it isn't built.
- **No bundled third-party stats — and no default feed.** The repo ships code,
  not other people's collected data, and it points at nobody's endpoint.
  Numbers come only from a source the user configures themselves
  (`sources.json`, gitignored) or from their own collected games
  (`collect.py`). Don't send PRs that hardcode someone's stats feed.
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
- Keep the layout flat: `bgtracker.py` = parsing + stats, `overlay.py` = UI,
  `collect.py` = own-data collection, `native/msync` = memory reader.
