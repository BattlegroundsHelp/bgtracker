# How to use bgtracker

A beta guide for people who just got the link. Ten minutes, start to finish.

bgtracker is a free overlay for Hearthstone Battlegrounds. It reads Hearthstone's
own log file and draws small windows around the game: what the shop is, what the
lobby is running, what your options are when the game makes you choose.

**Read this bit first, it saves confusion later.** The tool ships with **no stats
data**. Every *feature* works out of the box, but the placement *numbers* on hero
and trinket picks stay blank until you either grow your own numbers from your own
games (one command, section 4) or point it at a stats source you have the right to
use. That is a deliberate choice, not a missing download: aggregate placement data
belongs to whoever collected it.

---

## 1. What you need

There are two ways to run it. **The download needs no Python at all**, and it is
the one nearly everyone should take (section 2). Running from source is section
2b, for developers and for anyone who would rather run code they can read.

| | |
|---|---|
| **Windows** | 10 or 11. The overlay is Windows only (it anchors itself to the Hearthstone window). |
| **Python 3.10 or newer** | Only if you run from source (section 2b). From [python.org](https://www.python.org/downloads/windows/), tick **"Add python.exe to PATH"**. The download carries its own copy of Python and does not care what is installed on your machine. |
| **Hearthstone in BORDERLESS WINDOWED** | Options (gear) → Graphics → window mode. Nothing can draw over exclusive fullscreen without hooking the game, which this deliberately does not do. |
| **No pip installs** | The core has zero third party packages. `pip install pillow` is optional and only buys you card art (section 5). |
| **Internet on first run** | It downloads the public card database from HearthstoneJSON once (card names, tiers, the minion pool) and caches it for a day. After that it runs fine offline. |

You do **not** need admin rights, a Blizzard login, an account of any kind, or the
game to be restarted. Nothing is injected into the game and nothing is automated.

---

## 2. Get it and run it, in three steps

No Python, no pip, no installer. This is the route for nearly everyone.

**Step 1. Download and unzip.**

Grab **`bgtracker-windows.zip`** from the
[Releases page](https://github.com/BattlegroundsHelp/bgtracker/releases), then
**right click → Extract All**. Running it from inside the ZIP preview window will
not work. Put the folder somewhere you can write to, like `Documents\bgtracker`.
Do not put it in `C:\Program Files`, because the tool writes its cache, your saved
window positions, your collected games and any card art right beside the exe, in
that same folder.

**Step 2. Put Hearthstone in borderless windowed.**

In game: Options (gear, top right) → Graphics → set the window mode to
**Borderless Windowed**. This is the single most common reason someone sees
nothing at all.

**Step 3. Double-click `bgtracker.exe`.**

That is the whole launch. A console window called **bgtracker** appears on your
taskbar; that is normal, it is where the tool prints what it is doing. Leave it
alone. `bgtracker.bat` starts the same program with that console minimised, if
you prefer it out of the way.

### Optional: use a custom Hearthstone Logs directory

Copy `settings.example.json` to `settings.json` in the same folder as
`bgtracker.exe` (download) or `bgtracker.py` (source), then replace the example
value with the parent Logs directory:

```json
{
  "hearthstone_logs_dir": "D:\\Games\\Hearthstone\\Logs"
}
```

This must point to the folder containing the rotating
`Hearthstone_<timestamp>\Power.log` directories, not directly to one
`Power.log`. Relative paths are resolved beside `settings.json`; Windows
environment variables such as `%ProgramFiles(x86)%` and `~` are supported.
`settings.json` is gitignored and should never be committed or shared with
personal paths.
Without `settings.json`, or with an empty `hearthstone_logs_dir`, the historical
default `C:\Program Files (x86)\Hearthstone\Logs` remains active. A non-existing
configured path never falls back to that default: the console reports the path,
and the overlay stays running while waiting for a valid log. Invalid JSON is
reported as a settings error and should be corrected before restarting.

**About the Windows warning.** These exes are not code-signed, because a signing
certificate costs money a free tool does not have. On a file you just downloaded,
Windows SmartScreen may show a blue box titled **"Windows protected your PC"**
with only a **Don't run** button visible; the way through is **More info**, then
**Run anyway**. Some antivirus tools are wary of unsigned bundled Python for the
same reason and may quarantine it. Whether you see any of this depends on your
Windows version and settings, so treat it as "if it shows up" rather than a
promise in either direction. If you would rather not trust a binary at all,
section 2b is the same program, run from source you can read.

You can start it before Hearthstone, after Hearthstone, or in the middle of a
game. It finds the newest log on its own and follows along when the game rotates
to a new one.

**To quit:** click the `✕` in the corner of the window titled **bgtracker** (the
lowest one on the right hand side). Closing the console also works.

The other programs in the folder are the same tools this guide mentions later:

| in this guide | in the download |
|---|---|
| `python overlay.py` | `bgtracker.exe`, or `bgtracker.bat` |
| `python bgtracker.py` | `bgtracker-cli.exe` |
| `python collect.py` | `collect.exe` |
| `python fetch_art.py --all` | `fetch-art.exe --all` |

`bgtracker.exe --diag` prints where it reads and writes and every window it
loaded. Paste that into any bug report.

---

## 2b. Running from source (developers)

Same program, the code you can read. You need Python 3.10 or newer on PATH.

**Step 1. Get the files.**

```bash
git clone https://github.com/BattlegroundsHelp/bgtracker.git
```

Or download the source ZIP from
[github.com/BattlegroundsHelp/bgtracker](https://github.com/BattlegroundsHelp/bgtracker)
(green **Code** button → **Download ZIP**) and extract it properly (right click →
Extract All). Same rule about a folder you can write to: it keeps its cache, your
window positions and your collected games next to itself.

**Step 2.** Borderless windowed, exactly as above.

**Step 3.** Double-click `bgtracker.bat`, or run `python overlay.py`.

A minimised console called **bgtracker** appears on the taskbar; that is where it
prints what it is doing. Quitting works the same way, the `✕` on the window
titled **bgtracker**.

The same optional `settings.json` configuration described in section 2 applies
to source runs. Keep it beside `bgtracker.py`; do not point
`hearthstone_logs_dir` at an individual `Power.log`.

The core has no third party dependencies. `pip install pillow` is optional and
only buys card art (section 5). `python overlay.py --diag` prints the same
diagnostic as the packaged build.

---

## 3. What you will see the first time

The overlay is **ten small windows**, not one big panel. Each one opens and closes
on its own trigger, at the moment it is about the thing in front of you. Each one
is **draggable on its own** and remembers its own spot in `.overlay.json`, so
moving the tavern window never moves anything else.

They only draw while Hearthstone (or one of the overlay's own windows) is the
window in front. Alt-tab to your browser and they all disappear. That is on
purpose.

### Down the right edge, the state of play

| window | when it appears | what you get with zero setup |
|---|---|---|
| **COUNTERS** | as soon as the log states any of it | Everything. Turn, gold `cur/max`, your tavern tier and what the next tier costs *right now*, gold already banked for next turn, elemental and Blood Gem buffs, your board's tribe counts, free rerolls, triples, turns until the next trinket. |
| **COMBAT** | from the fight starting until the tavern comes back | The round that is fighting, plus one clearly flagged **BETA** line of win / tie / loss odds. See the honesty note below. |
| **TAVERN** | every roll, buy and sell, in the tavern only | The shop contents, each minion's tier, which ones you already own (`▶ yours`), which comp a minion feeds, your gold, the roll count. Stars show without any setup as a **coarse curated signal** (a core minion of a comp this lobby can build); a `cards` source turns them into ratings measured inside each minion's own tavern tier. |
| **bgtracker** | always up | Tribe chips for this lobby, the comps still open to you, your board's synergy, the status line, and the quit button. Comps work with no data (see below). |

### Down the left edge, the cards you are choosing between

They sit on the left because a panel on the right would cover the trinket row.

| window | when it appears | what you get with zero setup |
|---|---|---|
| **MINIONS** | always, as a slim one-line bar; click `browse ▸` to expand | The whole current minion pool, filtered by tier, tribe and mechanic, with card text. Built from the live card data, so it is always this patch. **Needs no stats at all.** |
| **SESSION** | always, except while the hero draft is up | Every game that finished while it was running, with placement and hero, and this lobby's tribes. **Your MMR is a dash** unless you build the optional memory reader (section 5). It is never guessed. |
| **PICK YOUR HERO** | hero select | All four heroes, named and shown. **The ranking numbers are blank** without a stats source. |
| **PICK YOUR HERO POWER** | that choice only | One row per hero power on offer. Numbers blank without a source. |
| **PICK YOUR TRINKET** | trinket offers | The four trinkets, named. Numbers blank without a source. |
| **PICK ONE** | discovers and Dark Gifts | The options, named. Dark Gifts have no published stats anywhere, so those stay unrated even with a source. |

### The honest version of "what works right now"

**Works immediately, nothing to configure:**

- Every counter in the COUNTERS strip.
- The minion browser (the whole live pool).
- The tavern window: contents, tiers, `▶ yours`, comp flags, gold, and coarse
  curated stars (a core minion of a comp this lobby can build gets 3, 4 if it
  also feeds the build you are on).
- Lobby tribes, inferred from the log as minions appear. In a real game six of
  seven tribes were known by about turn 5, the last one much later.
- The comps list. With no stats configured it shows **curated comp families**,
  whose core minions are computed from the live card pool, so they are always
  current patch. They are labelled `curated` and show a dot instead of a fake
  average. Measured comp rows replace them the moment a comps source has data.
- Session tracking of games and placements.
- Combat odds (BETA).
- Every pick window firing at the right moment, with the options named.

**Blank until you add numbers (section 4):** hero, hero power and trinket
rankings, pick rates, sample sizes, measured tavern star ratings (the curated
stars above stand in), measured comp averages.

### Two things worth knowing on sight

- **The header dot**: green means the lobby's tribes are exact (memory reader),
  amber means inferred from the log so far, grey means still waiting.
- **Nothing is invented.** A number the log has not stated is drawn as a dash, not
  as a zero and not as a guess. A window with nothing real to say stays shut.

### About the combat odds

Both warbands are read out of the log before the fight animates and a Monte Carlo
simulation gives win / tie / loss. Across 251 real logged fights it called the
winning side about **82%** of the time. It knows the vanilla rules, deathrattle
summons and the highest-impact per-card triggers, but plenty of cards are still
unscripted, so when one is on the board the odds are deliberately widened. It
never shows 0% or 100%. That, and the long tail still missing, is why it is
labelled BETA on screen. If either board could not be fully recovered it shows
no number at all.

If you want the mature version, run HDT's free Bob's Buddy alongside. Both tools
read the same log and coexist happily.

---

## 4. Getting numbers

Two options. Do option A first, it takes one minute and involves nobody else.

### Option A: grow your own numbers from your own games (recommended)

```bash
python collect.py
python collect.py --local-feed
```

Then restart the overlay.

- The first command mines every finished Battlegrounds game out of your whole
  Hearthstone log history into `data/games.jsonl`. It touches nothing live, so
  you can run it while the overlay is running, and it de-dupes, so re-running only
  adds new games.
- The second turns those games into a personal stats feed in `data/feed/` and
  writes a `sources.json` pointing at it. Now the overlay shows **your own
  numbers**, with no third party involved.

Check what you have at any time:

```bash
python collect.py --stats
```

**Be realistic about the sample.** This is your own play, so early on it is thin.
Anything under 30 games for a hero is flagged as thin and should be read as no
signal at all. It fills in as you play. Two practical notes: `--time all-time` is
the useful window early (`last-patch` will be nearly empty), and `--mmr` does
nothing against your own feed because your own games are one bucket.

There is also `python collect.py --upload <url>`, which is strictly opt-in and
needs a server you have. A shared community dataset is built but **not deployed
yet**, so there is nothing to point it at today. When it exists: uploading stays
off by default, records are anonymised game results with no names and no
battletags, the aggregates are free for everyone, and the data is never sold.

### Option B: point it at a stats source you have the right to use

Copy `sources.example.json` to `sources.json` next to `bgtracker.py` and fill in
your own URLs or local file paths. `sources.json` is gitignored, so a personal
source never ends up in a commit.

```json
{
  "heroes":   "https://your-host.example/heroes-{time}.json",
  "trinkets": "https://your-host.example/trinkets-{time}.json",
  "cards":    "https://your-host.example/cards-{time}.json",
  "comps":    "https://your-host.example/comps-{time}.json"
}
```

- `{time}` becomes `all-time` | `past-seven` | `past-three` | `last-patch`, and
  `{mmr}` becomes your `--mmr` bracket. Both come from the command line flags.
- A value can be an `https` URL or a local file path (relative paths resolve next
  to `bgtracker.py`).
- URL responses are cached in `.cache/` for one hour.
- Delete a line to leave that table empty. Missing data degrades to "no numbers",
  it never crashes.
- `heroes_duo` is an optional fifth key, used by `--duo`.

**The JSON shape.** Each file is one object with one array in it:

| file | top level key | fields read from each row |
|---|---|---|
| heroes | `heroStats` | `heroCardId`, `averagePosition`, `totalOffered`, `totalPicked`, `dataPoints`, `placementDistribution`, `tribeStats[]` (each with `tribe`, `impactAveragePosition`, `dataPoints`, `dataPointsOnMissingTribe`) |
| trinkets | `trinketStats` | `trinketCardId`, `averagePlacement`, `pickRate`, `dataPoints`, `averagePlacementAtMmr[]` (`mmr`, `placement`) |
| cards | `cardStats` | `cardId`, `averagePlacement`, `averagePlacementOther`, `totalPlayed` |
| comps | `compStats` | `archetype`, `averagePlacement`, `dataPoints`, `averagePlacementAtMmr[]`, `heroStats[].finalBoards` |

A minimal heroes file looks like this:

```json
{
  "heroStats": [
    {
      "heroCardId": "BG23_HERO_304",
      "averagePosition": 3.26,
      "totalOffered": 32700,
      "totalPicked": 19499,
      "dataPoints": 19499,
      "placementDistribution": [],
      "tribeStats": []
    }
  ]
}
```

`data/feed/*.json` written by `collect.py --local-feed` is exactly this shape, so
it doubles as a working reference.

---

## 5. Optional extras

### Card art (nice to have, 30 seconds)

Without it the overlay draws colored dots instead of card portraits. Everything
works either way.

```bash
pip install pillow
python fetch_art.py --all
```

It pulls tiles and crops from the public HearthstoneJSON CDN into `assets/`, skips
anything already on disk, and only needs re-running after a new card set.

### The memory reader (optional, and please read the risk note)

`native/msync` is a small helper that reads three things Hearthstone never writes
to any log file:

- the **exact tribes in the lobby, at hero select** instead of learning them
  slowly from minions appearing,
- **hero picks re-scored for the lobby you are actually in** rather than a global
  average,
- your **MMR** in the SESSION window, and your board for synergy marks.

**The risk, plainly.** Reading `Power.log` is the default, is what Hearthstone
Deck Tracker does, and Blizzard has publicly said log reading trackers are fine.
Reading the game's *memory* is different: it goes against the letter of Blizzard's
EULA, which prohibits software that reads information stored by the platform.
Established trackers do this for some features and bans for it are unheard of, but
it is the one component that crosses the written line. That is why it is **not
bundled**: you build it yourself, knowingly, or you do not. Leave it unbuilt and
you have a strictly log-only setup with zero risk, and the overlay simply knows
less, later. It opens the game process read only, never writes to it, never
injects and never automates.

If you want it, you need the .NET SDK. One command from the repo root:

```bash
dotnet build native/msync -c Release
```

That produces `native/msync/bin/Release/net48/msync.exe`, which the overlay finds
on its own. Restart the overlay. To check it by hand while you are in a lobby:

```bash
native/msync/bin/Release/net48/msync.exe
```

You should get one JSON line like
`{"ok":true,"rating":8500,"races":[11,14,17],"board":[...]}`. At the menu you get
`{"ok":false,...}`, which is correct. `--diag` shows where the memory walk landed.

It does not break on balance or content patches. A Unity **engine** upgrade (a few
times a year) moves the offsets, and then it needs a rebuild with new values.

---

## 6. Command line flags

`bgtracker.bat` passes anything you give it straight through to the overlay:

```bash
bgtracker.bat --mmr 10 --time past-seven
```

**Overlay (`bgtracker.bat`):**

| flag | what it does |
|---|---|
| `--mmr 100\|50\|25\|10\|1` | MMR bracket for the stats. `100` = everyone (default), `1` = top 1%. Only meaningful if your source has brackets. |
| `--time last-patch\|past-seven\|past-three\|all-time` | How far back the stats go. Default `last-patch`. |
| `--duo` | Use Duos hero stats (needs a `heroes_duo` source). Only heroes exist for Duos anywhere. |
| `--demo <path-to-Power.log>` | Replay a finished log through the real windows. Good for testing without playing. |
| `--diag` | Print where it reads and writes, and every window it loaded, then exit. The first thing to paste in a bug report. |

**Console version (`python bgtracker.py`)** — no overlay, just text. Takes
`--mmr`, `--time` and `--duo` as above, plus:

| flag | what it does |
|---|---|
| `--replay [path]` | Scan a finished log instead of following live. No path = the newest one. |
| `--refresh` | Ignore the one hour cache and re-download the stats. |
| `--comps` | Print the comp rankings and exit. |
| `--no-lobby` | Hide the tribe and comp panel during games. |

**Data (`python collect.py`):**

| flag | what it does |
|---|---|
| *(none)* | Mine your finished games into `data/games.jsonl`. |
| `--stats` | Print what you have collected so far. |
| `--local-feed` | Turn those games into your own stats feed and wire `sources.json` to it. |
| `--upload <url>` | Opt-in contribution to a shared feed. Nothing to point it at yet. |
| `--token <token>` | Upload token, if the server you are uploading to wants one. |

---

## 7. Troubleshooting

| symptom | likely cause | fix |
|---|---|---|
| **Nothing appears at all** | Hearthstone is in exclusive fullscreen. | Options → Graphics → **Borderless Windowed**. This is the number one cause. |
| **Nothing appears, and it is already borderless** | The overlay only draws while Hearthstone is the front window. Or it crashed on launch. | Click on the game. Then restore the minimised **bgtracker** console from the taskbar and read the last lines: `hb ... front=True anchored=True` means it is alive and anchored; `anchored=False` means it cannot see the game window. |
| **`'python' is not recognized`, or the Microsoft Store opens** | Windows ships a fake `python` that just opens the Store. | Easiest fix: use the download (section 2), which needs no Python. Otherwise install real Python from python.org with **Add python.exe to PATH** ticked; if the Store still hijacks it, Settings → Apps → Advanced app settings → **App execution aliases** → turn **off** `python.exe` and `python3.exe`, then relaunch. |
| **Windows are in the wrong place, off screen, or stacked on each other** | A saved drag position from a different resolution or monitor. | Quit the overlay, delete `.overlay.json` in the repo folder, start again. Every window returns to its default slot. (This also clears your session history.) |
| **The overlay covers cards I need to click** | Every window is draggable, individually. | Drag it by its header to somewhere better. It remembers. Note the badge strips drawn *on* the cards are click-through, so clicks reach the game, and they cannot be dragged yet. |
| **No numbers anywhere: hero picks show names but no placements** | No stats source configured. This is the default state, not a bug. | Section 4. `python collect.py` then `python collect.py --local-feed`, then restart the overlay. |
| **The log path is wrong, or settings.json is rejected** | A custom Logs directory is missing, points at a file/Power.log, or the JSON is invalid. | Check the console message for the exact path and source. Correct `settings.json` beside the app, use the parent Logs directory, and restart. |
| **Numbers appear but say "thin"** | Fewer than 30 games behind that row. | Correct behaviour. Read it as no signal. It fills in as you play. |
| **Tavern stars look blunt, or a minion has none** | With no `cards` source the stars are the curated signal, which only rates comp-core minions and minions of a viable tribe. | Expected. Add a `cards` source (section 4) and every rated minion gets a measured star inside its own tavern tier. |
| **Odds are not showing in COMBAT** | One of the warbands could not be fully recovered from the log, so nothing is shown rather than a made up number. Or the fight is already over. | Expected. If it never shows on any fight, report it (section 8) with the round number. |
| **SESSION shows no MMR** | The rating only exists in game memory, and the memory reader is optional and not built. | Either build it (section 5) or accept the dash. It will never guess a rating. |
| **The hero panel did not open at hero select** | The overlay was started after the draft was already on screen. | Start it before you queue. It picks up everything else mid-game fine. |
| **Comps say `curated`** | No comps data configured, so it is showing evergreen families computed from the live card pool. | Working as intended. Measured rows replace them once a comps source has data. |
| **Everything vanishes when I alt-tab** | By design. The windows only exist while the game (or one of them) is in front. | Nothing to fix. |

---

## 8. How to report a bug

Issues go to
[github.com/BattlegroundsHelp/bgtracker/issues](https://github.com/BattlegroundsHelp/bgtracker/issues).
Have a quick look for an existing one first, and one issue per bug please.

### What makes a report actually fixable

1. **Which window.** Name it exactly: COUNTERS, COMBAT, TAVERN, bgtracker,
   MINIONS, SESSION, PICK YOUR HERO, PICK YOUR HERO POWER, PICK YOUR TRINKET, or
   PICK ONE. Ten independent windows means "the overlay is wrong" narrows almost
   nothing down.
2. **What the game was doing at that exact moment.** Hero select, shopping,
   mid-fight, the animation between fight and shop, between games, at the menu.
   Add the turn number and the round if you have them. Most of the hard bugs in
   this thing have been timing bugs, so the moment is the single most useful fact
   in the report.
3. **What you expected versus what you saw.** A screenshot of the overlay is
   worth a lot here.
4. **Your setup.** Whether you built the optional memory reader, whether you have
   a stats source configured (own feed or your own source), which flags you
   launched with, and your screen resolution if it is a layout problem.
5. **The console output.** Restore the minimised **bgtracker** window from the
   taskbar and copy the last 30 or 40 lines. Errors and the `hb` heartbeat lines
   are exactly what is needed.

### About logs

Hearthstone's logs live in:

```
C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_<timestamp>\Power.log
```

**Do not attach a whole `Power.log`.** They run to hundreds of megabytes. If a
slice is needed, someone will ask for the lines around the moment it went wrong.

### Scrub your battletag before you paste anything

This matters. `Power.log` and the overlay's console output both contain your
battletag (`Name#1234`) on a great many lines, and file paths contain your Windows
username. Before pasting anything into a public issue:

- Find and replace your battletag with something like `PLAYER#0000`.
- Replace your Windows username in any path with `USER`.

Your collected games in `data/games.jsonl` do not store your battletag, but the
raw log absolutely does. When in doubt, read what you are about to paste.

---

## Fine print

Not affiliated with or endorsed by Blizzard Entertainment. Hearthstone and all
card names and images are © Blizzard Entertainment, Inc. This is a free,
non-commercial, open-source fan tool, and it is beta software: expect rough edges,
and the combat odds are explicitly approximate.

More detail lives in [../README.md](../README.md) (the full feature tour),
[../ROADMAP.md](../ROADMAP.md) (what is open and why the missing things are
missing), and [ARCHITECTURE.md](ARCHITECTURE.md) (how it works inside).
