# bgtracker

[![CI](https://github.com/BattlegroundsHelp/bgtracker/actions/workflows/ci.yml/badge.svg)](https://github.com/BattlegroundsHelp/bgtracker/actions/workflows/ci.yml)

Live Battlegrounds pick helper. When the game offers you heroes or trinkets, it
prints what everyone else's results look like with those options: average
placement, how often people take it, top-4 rate, sample size.

No account, no subscription. It reads Hearthstone's own log file. The numbers
come from the **community feed** by default: a pool built only from games
players shared through this tool, free for everyone, never sold or paywalled.
**Sharing is on by default too** - as you play, the overlay sends one
anonymised record per finished game (no name, no battletag, no log files;
it goes out when the next game starts or when the overlay closes) back to
that pool,
so everyone who plays also feeds the numbers everyone reads. The settings
panel's DATA section lists every field that leaves and holds the off switch;
`--no-upload` stops it for one run. Details, including that this default
CHANGED in August 2026, under "Where the numbers come from (and where they
go)" below.

> **Not affiliated with or endorsed by Blizzard Entertainment.** Hearthstone®
> and all card names and images are © Blizzard Entertainment, Inc. This is a
> free, non-commercial, open-source fan tool.

**Get it:** download
[`bgtracker-windows.zip`](https://github.com/BattlegroundsHelp/bgtracker/releases),
unzip, run `bgtracker.exe`. No Python, no install, Windows only. It tells you
when a newer build exists and never installs one behind your back
([how updates work](docs/USAGE.md#2c-new-versions)).

**New here? Start with [docs/USAGE.md](docs/USAGE.md)** - what you need, the
three steps to running it, what each window shows on the first run, how to get
numbers, and what to do when something looks wrong.
[docs/FEATURES.md](docs/FEATURES.md) is the reference for every surface: what it
shows, why it helps, where the information comes from, and what it needs.

## Safety & what it's allowed to do

The tool has two halves that sit on opposite sides of Blizzard's rules, and the
**default build stays on the safe side**:

- **Reading `Power.log` (default): allowed.** This is exactly what Hearthstone
  Deck Tracker does, and Blizzard has publicly said log-reading trackers are fine
  ("anything you could do with pencil and paper"). No one has been banned for it;
  Blizzard shipped their own tracker in 2024.
- **Reading game memory (`native/msync`, OPTIONAL, off unless you build it):**
  the memory reader gives exact tribes at hero select and board synergy, but
  reading the game's RAM is against the letter of Blizzard's EULA (§1.C.vi
  prohibits software that "reads or mines information stored by the Platform").
  Established trackers do this for some features and bans are unheard of, but it is
  the one component that crosses the written line. **It is not bundled** - the
  overlay falls back to log inference without it, and building `msync` is a
  knowing opt-in. Leave it unbuilt for a strictly-log-only, zero-risk setup.

Keep it free and ad-free (it is) - that removes any commercial-competition angle
and is the strongest protection. It never injects code, modifies the client, or
automates anything.

### Where the numbers come from (and where they go)

Aggregate placement data belongs to whoever collected it - the numbers on the
big stats sites are their collectors' property, and none of them permit
third-party redistribution. A public URL is not a licence, and respecting that
is a design decision here, not a technicality. So this tool touches no third
party's feed. What it reads instead is the **community dataset**: our own
pool, built only from games players shared through this tool. With no
`sources.json`, the overlay reads that feed out of the box (the same URLs
`sources.example.json` documents). The pool is young, so expect thin samples,
flagged as thin, until it fills up.

**Sharing back is on by default.** After each finished game (and once on
start, for your whole log history) the overlay uploads one record per game to
that same server: a scrambled game id, the date, the hero you played, your
placement, whether it was Duos, the lobby tribes, the heroes and trinkets you
were offered, the trinkets you picked, an opaque per-install id, and the
client version. No names, no battletags, no log files. The off switch is the
DATA box in the settings panel (saved), or `--no-upload` (one run); the
aggregated stats stay **free for everyone** and are **never sold or
paywalled** whether you share or not. Honesty note: this is a CHANGE of the
original terms. Uploading was opt-in and off by default until 2026-08-12,
when the author flipped the default so the pool can actually grow. The change
is stated here, in the CHANGELOG, in the ROADMAP and in the panel itself,
rather than slipped in quietly.

To read different numbers instead:

- **Your own games only.** `python collect.py` mines every finished game out
  of your own log history into `data/games.jsonl` - your own gameplay, fully
  yours. Then `python collect.py --local-feed` turns those games into a
  personal stats feed and points `sources.json` at it, so the overlay shows
  **your own numbers** with no third party involved (thin samples are flagged
  until they fill in).
- **Any source you have the right to use.** Create `sources.json` next to
  `bgtracker.py` - see "Stats side" below for the keys and the expected JSON
  shape. It can be a URL or a local file. Your `sources.json` is gitignored, so
  a personal source never ends up in a commit. Writing the file replaces the
  community default entirely; a key you leave out stays empty.

Comps never need a data source to be useful: with no comps data the tool
shows **curated comp families** - evergreen tribe archetypes whose core minions
are computed from the live card pool, so they are always current-patch. They are
labelled `curated`, and measured comp rows replace them the moment a comps
source has data.

Open-source **code** (as distinct from collected data) is free to use under its
own license and is credited where used; that is a separate thing from anyone's
collected stats.

## Run it

Step by step, for a first run: **[docs/USAGE.md](docs/USAGE.md)**.

**The download needs no Python.** Grab **`bgtracker-windows.zip`** from the
[Releases page](https://github.com/BattlegroundsHelp/bgtracker/releases), right
click → **Extract All**, and double-click **`bgtracker.exe`** in the extracted
folder. That is the whole install: it carries its own copy of Python, so nothing
has to be installed on your machine. Keep the folder somewhere you can write to
(`Documents` is fine, `C:\Program Files` is not) because the tool writes its
cache, your saved window positions and your collected games next to the exe.
`bgtracker.bat` starts the same thing with its console minimised.

The exes are not code-signed, since a certificate costs money a free tool does
not have. On a file you just downloaded, Windows SmartScreen may show a blue
**"Windows protected your PC"** box where the only obvious button is **Don't
run**; **More info** then **Run anyway** goes ahead. Whether it appears at all
depends on your Windows version and settings, and some antivirus tools are wary
of unsigned bundled Python for the same reason. If you would rather run code you
can read, the source route is the same program.

**From source (developers).** Python 3.10 or newer, no third party packages for
the core, then double-click **`bgtracker.bat`** or run `python overlay.py`:

```bash
git clone https://github.com/BattlegroundsHelp/bgtracker.git
cd bgtracker
python overlay.py
```

A **settings panel** opens with it, and that one is a normal window you can
move, scroll and close: the scale for the whole overlay (drag it and watch it
resize, which is the fix for a 4K screen), a switch for each of the windows
below, whether to share your games, and whether there is a new version. The
gear in the bgtracker window's header opens it again later, `--no-panel` starts
without it, and the tool works exactly the same if you never open it.
[More](docs/USAGE.md#3b-the-settings-panel).

There is no one big data window: the overlay
is **a set of small windows, one per thing you might want to know**, and each
opens and closes on its own trigger, at the moment it is about the thing in
front of you.

Down the **right** edge of the game - the state of play:

| window | what it shows | when |
|---|---|---|
| **COUNTERS** | turn, gold `cur/max`, your tavern tier and what the next tier costs *right now*, gold banked for next turn, elemental and Blood Gem buffs, what tribes your board is made of, free rerolls, triples, turns until the next trinket | whenever the log has stated any of it |
| **COMBAT** | which round is fighting, and one clearly-flagged BETA line of win / tie / loss odds for the fight on screen | from the fight starting to the tavern coming back |
| **TAVERN** | the shop you are looking at - a star rating per minion, which ones feed the comp you are building, what each one pays off against your board ("Beasts 4", read from the card's own text so it needs no stats source), gold. With a `cards` source the stars are measured inside the minion's own tavern tier; a minion no games have rated yet gets no star, because a rating computed from the card alone was measured and it ranks bodies rather than cards | every roll, buy and sell, in the tavern only |
| **bgtracker** | tribe chips (colored = in this lobby), the comps still open to you, your board's synergy with them. Click a comp to expand its core minions | always |

Down the **left** edge - the cards you are choosing between, so nothing sits on
top of them:

| window | what it shows | when |
|---|---|---|
| **MINIONS** | a slim bar until you click `browse`, then the whole current minion pool filtered by tier / tribe / mechanic, with card text and art. Open a row and, when the feed carries a per-turn breakdown, it splits the buy-it-vs-skip-it difference across four stretches of the game, marking any stretch under the sample floor `thin` rather than printing a number | on click |
| **SESSION** | this sitting: MMR now vs when you started, every game that finished while it was running with its placement and hero, and this lobby's tribes | always, except while the draft is up |
| **PICK YOUR HERO** | the four heroes ranked, one big color-graded number each (green = better finish), best highlighted, pick% and sample size, plus a badge on each portrait, and one line of community-written advice per hero saying when it is the pick (all 121 heroes have one). With the memory reader the lobby's tribes re-score them and the delta is shown ("−0.06 here") | hero select |
| **PICK YOUR HERO POWER** | one row per hero power on offer, named and lined up. The pool publishes hero-power numbers now, but this panel does not read that table yet, so the options usually show a dash | that choice only |
| **PICK YOUR TRINKET** | the four trinkets ranked, badges on the cards | trinket offers |
| **PICK ONE** | discovers and Dark Gifts, rated per option with a star badge on each real card, plus what each one pays off against your board ("Beasts 4"); the shop's stars step out of the way while it is up | that choice only |
| **OTHER PLAYERS** | the leaderboard - every other player's hero, tavern tier and health - and, for anyone you have fought, the board they were last seen holding, stamped with the round and how long ago that was. Click a player to see that board. Needs the memory reader; without it the window never appears | while a lobby is running, except while a trinket offer is up |

- **Every window anchors itself to the Hearthstone window** and is draggable on
  its own - each remembers its own place in `.overlay.json`, so moving the
  tavern never moves anything else. Click `✕` on the bgtracker window to quit.
- **The numbers printed on the cards** are separate click-through strips, so
  every click still reaches the game. To move them, the `⇕ badges` chip in the
  bgtracker window's header turns on a calibrate mode that drops click-through
  while it is on, lets you drag each strip into place, and puts click-through
  back when you press `⇕ done`
  ([how](docs/USAGE.md#moving-the-badges-calibrate-mode)).
- **They close themselves**: the hero panel the moment shopping starts, the
  trinket panel shortly after, the combat window when the tavern is back. A
  window is never left showing a moment that is no longer on screen.
- Header dot: green = tribes exact (memory), amber = inferred from the log so
  far, grey = waiting.
- Nothing is ever invented. A number the log has not stated is a dash, and a
  window with nothing real to say stays shut.

**Windowed or borderless both work. Fullscreen usually does too.** The overlay
is an ordinary always on top window that follows Hearthstone's rectangle, so
any mode the desktop composites works, and windowed with a title bar is fine.
True exclusive fullscreen is the one case that cannot work, because the GPU
sends the game's frames straight to the display and nothing else gets a look
in. In practice Windows 10 and 11 turn on fullscreen optimizations by default,
which runs the game through the compositor anyway, which is why the Discord and
Steam overlays work in fullscreen these days. If you cannot see the overlay in
fullscreen, switch to borderless windowed. `bgtracker.exe --diag` reports the
mode the game is actually in. What this tool will not do to force the issue is
hook the game's swap chain: that means injecting code into Hearthstone, which
is exactly what it refuses to do.

The overlay takes the same options: `bgtracker.bat --mmr 10 --time past-seven`,
plus `--demo <log>` to replay a Power.log through the UI.

Optional, for real card portraits instead of colored dots:
`pip install pillow`, then `python fetch_art.py --everything` once (tiles +
crops for the whole Battlegrounds card universe - minions, heroes, spells,
trinkets - from the HearthstoneJSON CDN into `assets/`, plus the deck-list
gem; re-run after a new card set). In the download that is
`fetch-art.exe --everything`, with Pillow already inside. `--all` still
fetches just minions and trinkets. And with the game installed,
`python tools/extract_game_assets.py` (needs `pip install UnityPy`) pulls
the game's own tavern-tier shield and placement medals out of YOUR install -
they never ship in the repo.

Looks: the default is the flat presentation the established trackers use.
The settings panel's "Tavern skin" switch turns on a generated wood-and-gold
look, live. Standing tavern buffs float in their own draggable BUFFS window.

For the plain console version (`bgtracker-cli.exe` in the download):

```bash
python bgtracker.py
```

Start it before or during a game and leave it running. Options:

| flag | what it does |
|---|---|
| `--mmr 100\|50\|25\|10\|1` | MMR bracket. `100` = everyone (default), `1` = top 1% |
| `--time last-patch\|past-seven\|past-three\|all-time` | how far back the stats go |
| `--duo` | use Duos stats instead of solo - heroes, trinkets, cards and comps all come from Duos games only, never pooled with solo |
| `--replay [path]` | scan a finished log instead of following live (defaults to newest) |
| `--refresh` | ignore the 1-hour cache and re-download |
| `--comps` | print the comp/archetype rankings and exit |
| `--no-lobby` | hide the tribe + comp panel during games |

Example output (with a stats source configured):

```
====================================================================
  HERO CHOICE  -  top 100% MMR, last-patch
====================================================================
  1. Nightmare Lord Xavius      avg 3.26   picked  59.6%  top4 72.4%   n=19,499 <<<
  2. Lady Vashj                 avg 3.63   picked  19.2%  top4 68.9%   n=974
  3. Al'Akir                    avg 3.68   picked  26.7%  top4 65.2%   n=2,722
  4. Captain Hooktusk           avg 3.95   picked  12.7%  top4 59.6%   n=1,315
                                spread 0.69 places between best and worst
====================================================================
```

Lower average placement is better. `<<<` marks the best option that also has a
sample worth trusting; anything under 30 games is marked `(thin!)` and should be
read as no signal at all.

## Tribes and comps

As the game goes on it works out which tribes this lobby is running, and re-ranks
the comps down to the ones you can actually build:

```
--------------------------------------------------------------------
  TRIBES IN  (7/10 confirmed): Demon, Dragon, Elemental, Murloc, Naga, Pirate, Undead
  not seen yet:                Beast, Mech, Quilboar
  best comps available to you (top 100% MMR):
    2.72  murloc scam                [Murloc]  n=1,109
    2.83  elemental boost            [Elemental]  n=2,387
    2.91  murloc handbuff            [Murloc]  n=4,980
    3.04  undead end of turn         [Undead]  n=2,196
--------------------------------------------------------------------
```

There are two ways it learns the tribes.

**From the log** - always available, partial. Every minion carries its tribe, so
seeing one proves that tribe is in; an unseen tribe is merely unconfirmed, never
provably out. It fills in as minions appear: in a real game 6 of 7 were known
within about 6 minutes (roughly turn 5), the last one much later. The panel says
"seen so far" in this mode.

**From game memory** - exact, and available at hero select. Build the helper in
`native/msync` (below) and the full list is known from turn zero, the panel says
"exact", and hero offers are **re-scored for the lobby you're actually in**
instead of ranked on a global average.

`python bgtracker.py --comps` prints the whole archetype ranking on its own
(needs a `comps` source configured).

## How it works

**Game side.** Hearthstone writes `Power.log` under
`C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_<timestamp>\`, driven by
`log.config` in `%LOCALAPPDATA%\Blizzard\Hearthstone`. The offered cards show up
already named:

```
FULL_ENTITY - Updating [entityName=Lady Vashj id=96 zone=HAND zonePos=4 cardId=BG23_HERO_304 player=3]
```

- Heroes on offer land in **`zone=HAND`** under your own player id.
- Trinkets land in **`zone=SETASIDE`** - but so does a lot that is *not* an offer.
  As you fight each opponent, their two trinkets get staged under your own player
  id, and repeat every time you re-fight them.
- All options in one offer share a single timestamp, which is how they get
  grouped into one event.
- A genuine trinket offer is **always exactly four options**, and that is what
  separates it from the noise. Across 19 real games: 36 bursts of four (two per
  game - one if you die before the greater trinket, three with a hero like Marin
  that grants an extra), against 65 twos, 43 ones, 18 threes and 15 sixes of
  opponent reveals.

**Stats side.** The community feed is the built-in default (used only when no
`sources.json` exists). To read anything else, `sources.json` next to
`bgtracker.py` maps table names to a URL or local JSON file **you** supply;
`{mmr}` and `{time}` placeholders are filled from the command-line flags:

```json
{
  "heroes":     "path/or/url/to/hero-stats-{mmr}-{time}.json",
  "heropowers": "path/or/url/to/heropower-stats-{mmr}-{time}.json",
  "trinkets":   "path/or/url/to/trinket-stats.json",
  "comps":      "path/or/url/to/comp-stats.json",
  "cards":      "path/or/url/to/card-stats.json",
  "hero_tips":  "optional, the voted hero tips feed",

  "heroes_duo":     "optional, the same tables from DUOS games only",
  "heropowers_duo": "optional",
  "trinkets_duo":   "optional",
  "comps_duo":      "optional",
  "cards_duo":      "optional"
}
```

The `*_duo` keys are what `--duo` reads, and there is no fallback from
them to the solo tables: Duos is four teams finishing 1st-4th where solo is
eight players finishing 1st-8th, on its own hero pool, so a solo number under a
Duos heading would be the wrong game's answer. Leave them out and `--duo` shows
no numbers instead. `collect.py --local-feed` builds both sets from your own
games and fills these keys in for you.

`heropowers` is the hero **power** table: average placement and pick rate for
the power you choose between when a hero offers one. No stats site publishes
that at any price, so the community pool computes its own. It is small by
nature, and the pick panel does not read it yet, so setting the key changes
nothing on screen today ([roadmap](ROADMAP.md)). `hero_tips` is the voted tips
feed; leave it out and the tips that ship with the tool are the only ones shown.

Expected shapes (any source in this shape works, including one you compute
yourself from `collect.py` output): hero records carry `heroCardId`,
`averagePosition`, `totalOffered`, `totalPicked`, `placementDistribution`,
`dataPoints`, `tribeStats`; trinkets carry `trinketCardId`, `pickRate`,
`averagePlacement`, plus `averagePlacementAtMmr` per bracket; comps carry
`compStats[].archetype/averagePlacement/heroStats[].finalBoards`; cards carry
`cardStats[].cardId/averagePlacement/averagePlacementOther/totalPlayed`.
URL responses are cached in `.cache/` for an hour, per source, so pointing at a
different feed takes effect immediately. With no `sources.json`, the community
feed answers; with one, only what it names is read, and an offer whose table is
empty still appears - named, ranked by nothing, numbers hidden.

**MMR brackets.** `--mmr` only means something if your source URL carries
`{mmr}`. A feed publishes a bracket once it holds enough games, so `top 1%` may
not exist on a young pool; the tool then reads the all-players file and **says
which bracket the numbers actually came from**, rather than printing the whole
pool under a "top 1%" heading. Our own feed stamps every file with the bracket
it is (`"mmr": {"bucket": 25, "minRating": 7400, "games": 412}`) and that stamp
wins over what was asked for.

## Tests

```bash
python tests/test_regression.py
```

The offline regression CI runs on every push - no network, frozen cardId lists
stand in for the live stats tables. Must print `PASS`.

```bash
python tests/test_windows.py [<Power.log> ...]
```

The window harness. It measures a real `Power.log` on its own first (how many
times the shop was refreshed, how many fights the screen actually started and
ended, how many choose-one dialogs of each kind), then replays the same log
through the real Reader → Router → real windows and compares. It also replays
the counters parser separately, paints every window with real payloads, and
checks the default layout for overlapping bands. Needs a real log; it skips
cleanly on a machine with none (real logs are player data and are not in the
repository). Last run, on a 2,643,818-line log: 299 shop refreshes → 299 tavern
rebuilds landing before the next refresh, 113 screen fights → 113 opens / 112
closes with the odds still on screen at the closing instant of 107 of 107 judged
fights, every pick window firing only for its own dialog (18 hero, 22 trinket, 3
hero power, 100 discover blocks), and zero windows raising.

```bash
python tests/test_live.py
```

Exercises the live path against a fake Logs dir: appends real hero-select lines to
a watched file, then drops a newer session folder in mid-run to prove log rotation
works. Prints `PASS`/`FAIL`. Fetches the card database once (cached a day); works
with or without a `sources.json`.

`tests/fixture.log` is a 26k-line extract of one real day - 19 games, boiled down
to just the lines that matter, so a full regression runs in seconds instead of
chewing through 886 MB. You can also replay it through the full console app:

```bash
python bgtracker.py --replay tests/fixture.log
```

**Expect exactly 19 hero offers and 36 trinket offers.** Those numbers are the whole
test. 19 games means 19 drafts; two trinket offers per game, minus one where the
run ended early, plus extras from heroes that grant one. If trinkets come out near
137 instead, the four-option rule has broken and opponent reveals are leaking back
in. Tribes should print about 7 panels per game.

For a read-only check against your own latest game:

```bash
python bgtracker.py --replay
```

## Building the memory reader

The tribe list is the one thing Hearthstone never writes to any log - verified by
checking every tag before hero select (including unnamed numeric ones) and every
other log file. The same is true of the other players' boards while you are
shopping. Both *are* in the game's memory, which is where the established
trackers get them. `native/msync` is a small **clean-room** helper that reads
them (plus your rating, your board, and the leaderboard) by walking the standard
Mono/Unity managed heap.

It's optional. Without it everything still works, just from log inference.

Needs the .NET SDK. One command from the repo root:

```bash
dotnet build native/msync -c Release
```

That produces `native/msync/bin/Release/net48/msync.exe`, which `bgtracker.py`
finds on its own. Run it by hand to check it:

```bash
native/msync/bin/Release/net48/msync.exe
```

`{"ok":true,"rating":8500,"races":[11,14,17],"board":[...],"players":[...]}` when
you're in a lobby; `{"ok":false,"rating":8500,"races":[]}` at the menu; `--diag`
shows where the memory walk resolved. `players` is the leaderboard, and it is what
the OTHER PLAYERS window is made of. Full detail:
[native/msync/README.md](native/msync/README.md).

**On fragility:** this does *not* break on balance or content patches. It resolves
fields by name (`m_availableRacesInBattlegroundsExcludingAmalgam`), so new cards and
number changes are invisible to it. What moves the offsets is a Unity **engine**
upgrade - a few times a year. The offsets in `native/msync/Offsets.cs` are each
annotated with the public Mono struct field they come from, so re-deriving them
against a new engine is mechanical (`DumpFields` in `Mono.cs` is the diagnostic aid).

## How this compares to Hearthstone Deck Tracker / Tier7

HDT is the incumbent. It is free, it is fine, and it does things this does not.

| | HDT / Tier7 | this |
|---|---|---|
| Combat odds (Bob's Buddy) | free, mature | **beta** - log-only, clearly flagged, about 86% of fights called correctly over 339 real logged fights; run Bob's Buddy alongside if you want the mature one |
| Counters (gold, tier price, buffs, tribes) | free | yes |
| Minion browser | free | yes - the live pool, no stats needed |
| MMR session tracker | free | yes, with the memory reader for the rating |
| Opponents' last-seen boards | free | yes, with the memory reader - stamped with the round it was seen |
| Hero pick stats | overlay is Tier7 | yes, from your own data source |
| Trinket pick stats | Tier7 | yes, from your own data source |
| Comps filtered to your lobby, with key minions | Tier7 | yes, from your own data source |
| Tribes in the lobby | exact | exact with the memory reader, else inferred |
| Hero picks *tailored to the lobby's tribes* | Tier7 | yes, with the memory reader |
| Written hero advice at the draft | Tier7, paid and hand-written | one line per hero, community-written, ships with the tool and free |
| Duos | some of it | heroes, trinkets, cards and comps from Duos games only, never pooled with solo |

The last row needs `native/msync` built. The lobby-scoring arithmetic is
standard and documented in open-source trackers (`averagePosition +
Σ impactAveragePosition` over the tribes present, dropping tribe rows with too
little data on either side) - what you bring is a data source with
`tribeStats` on each hero. The other thing that was ever missing is knowing
the tribes at turn zero, and that comes out of memory.

## Known limits

- **Borderless windowed only.** Exclusive fullscreen can't be drawn over without
  hooking the game.
- **Combat odds are BETA.** Both warbands come out of the log before the fight
  animates, and a Monte Carlo sim calls the winning side about 86% of the time,
  measured across 339 real logged fights, using the vanilla rules, derived
  deathrattle summons and hand-written scripts for the highest-impact cards
  (Rally attacks, deathrattle buffs, Reborn watchers, Titus). Plenty of cards
  are still unscripted, so when the board holds one the sim deliberately
  **widens** its odds rather than pretending - it never prints 0% or 100%. It is
  labelled BETA on screen for exactly that reason, and it never shows a number
  when either board could not be fully recovered.
- **The default numbers are young.** Out of the box the stats come from the
  community pool, which is small so far: many rows are flagged thin (read: no
  signal) and most MMR brackets are not published yet. Comps are classified now,
  but an archetype is only published once 30 games have been classified into it,
  so today that file carries no rows at all and the curated families stand in.
  Your own feed (`collect.py --local-feed`) or any source you have the right to
  use replaces it via `sources.json`.
- **Dark Gifts have no stats to show.** They are live this patch, but nobody
  publishes placement data for them. **Quests are dead this patch** entirely.
  So heroes, trinkets, tribes and comps is the complete set of what can be shown.
- Crowd stats are other people's games. Average placement carries selection bias:
  a hero looks good partly because the players who pick it know how to play it.
- **Windows only.** The log parsing would port anywhere, but everything that
  puts a window over the game is Win32, and so is the memory reader. macOS and
  Linux are open on the [roadmap](ROADMAP.md), not started, and there is no Mac
  here to test on. iPad cannot host an overlay at all.

## Contributing

**The easiest thing to contribute is a hero tip.**
[`data/hero_tips.json`](data/hero_tips.json) is the one line of advice shown
under each hero at the draft. All 121 heroes have one now, so the work is
**improving** them, and that is a pull request against a plain text file. The
rules are in [CONTRIBUTING.md](CONTRIBUTING.md), the contract is
[`data/hero_tips.schema.json`](data/hero_tips.schema.json), and CI checks every
entry, so a typo in a hero id fails the build instead of silently never showing
up. Write your own words - nothing here is copied from anyone's paid guides.

There is a second route that needs no pull request: `server/tips.py` takes
submissions and votes and publishes a community tips feed the client reads like
any other source. A line only reaches it once distinct voters, its score and a
margin over the shipped line have all cleared a floor, and the draft marks a
voted line `▲` so it is never mistaken for a reviewed one.

[docs/FEATURES.md](docs/FEATURES.md) is the reference for every surface (what it
shows, why it helps, where the data comes from, what it needs),
[CONTRIBUTING.md](CONTRIBUTING.md) has the ground rules,
[ROADMAP.md](ROADMAP.md) what's open and why the not-built things aren't built,
and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) the full map - including every
log-parsing gotcha that cost real debugging time, so you don't pay for them
twice.

## License & credits

Code is [MIT](LICENSE). Not affiliated with Blizzard; Hearthstone and all card
art © Blizzard Entertainment.

Standing on the shoulders of:

- **[Unity-Technologies/mono](https://github.com/Unity-Technologies/mono)** - the
  public Mono runtime source whose struct layout the optional memory reader
  (`native/msync`) walks. The reader is clean-room; the layout facts are Mono's.
- **[HearthstoneJSON](https://hearthstonejson.com/)** - card database and art CDN.
