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

## Hero tips - the easiest thing to contribute

The overlay prints one line of advice under each hero in the draft. Those lines
live in [`data/hero_tips.json`](data/hero_tips.json), they are plain text, and
**a pull request is how they get added, improved or thrown out**. No account, no
API, no upvote button: open a PR, argue it in the diff, the better wording wins.
If enough people are editing this file for that to stop working, we will build
something better on top of it.

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
where the seed tips came from, and it is also why some heroes have **no** tip:
when the printed power names a reward the card never explains (a Quest, a
Timewarp, a Darkmoon Prize), no honest tip can be derived from the card, and no
entry beats an invented one. Same rule for numbers - this file is advice, not
statistics. Do not paste placement averages into it from anywhere.

### Submitting one

1. Edit `data/hero_tips.json`. Keep entries in alphabetical order by hero name,
   and keep the file `json.load`-able (trailing commas are not JSON).
2. Run `python tests/test_regression.py`. It validates this file offline:
   unknown cardId, missing `when`, too many bullets, an unknown tribe or an
   over-long line all fail, so CI catches a broken tip before a human reads it.
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
