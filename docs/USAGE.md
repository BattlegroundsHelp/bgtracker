# How to use bgtracker

A beta guide for people who just got the link. Ten minutes, start to finish.

bgtracker is a free overlay for Hearthstone Battlegrounds. It reads Hearthstone's
own log file and draws small windows around the game: what the shop is, what the
lobby is running, what your options are when the game makes you choose.

**Read this bit first, it saves confusion later.** The numbers come from the
**community feed**: a pool built only from games players shared through this
tool, read by default when you have no `sources.json`. The pool is young, so
many rows are flagged thin (read: no signal yet). **Sharing goes both ways and
is on by default**: as you play, the overlay sends one anonymised record per
finished game back to that pool (it leaves when the next game starts or when
the overlay closes) - no name, no battletag, no log files - and the
settings panel's DATA section lists every field and holds the off switch
(`--no-upload` turns it off for one run). Section 4 has the details, your own
private feed, and how to point at any other source you have the right to use.
No third party's stats are ever fetched: aggregate placement data belongs to
whoever collected it.

---

## 1. What you need

There are two ways to run it. **The download needs no Python at all**, and it is
the one nearly everyone should take (section 2). Running from source is section
2b, for developers and for anyone who would rather run code they can read.

| | |
|---|---|
| **Windows** | 10 or 11. The overlay is Windows only (it anchors itself to the Hearthstone window). |
| **Python 3.10 or newer** | Only if you run from source (section 2b). From [python.org](https://www.python.org/downloads/windows/), tick **"Add python.exe to PATH"**. The download carries its own copy of Python and does not care what is installed on your machine. |
| **Hearthstone windowed or borderless** | Either works, and fullscreen usually does too (Windows composites it). Only true exclusive fullscreen cannot work, because nothing can draw over it without hooking the game, which this deliberately does not do. `--diag` tells you the mode. |
| **No pip installs** | The core has zero third party packages. `pip install pillow` is optional and only buys you card art (section 5). |
| **Internet on first run** | It downloads the public card database from HearthstoneJSON once (card names, tiers, the minion pool) and caches it for a day. The overlay also talks to the community stats server: it reads the feed (cached an hour), asks for the newest version number on start (section 2c), and shares your finished games unless you switch that off (section 3b). Offline, everything still runs; numbers just come from the caches. |

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

**Step 2. Windowed or borderless. Fullscreen usually works too.**

In game: Options (gear, top right) → Graphics → set the window mode to
**Borderless Windowed**. This is the single most common reason someone sees
nothing at all.

**Step 3. Double-click `bgtracker.exe`.**

That is the whole launch. A console window called **bgtracker** appears on your
taskbar; that is normal, it is where the tool prints what it is doing. Leave it
alone. `bgtracker.bat` starts the same program with that console minimised, if
you prefer it out of the way.

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

The core has no third party dependencies. `pip install pillow` is optional and
only buys card art (section 5). `python overlay.py --diag` prints the same
diagnostic as the packaged build.

---

## 2c. New versions

On start, the tool asks the stats server one small question: is there a newer
build? That is a 200 byte answer, fetched on its own thread while the overlay is
already opening. Then:

- **Nothing is downloaded and nothing is installed.** If there is a new build,
  one line appears in the console saying so, with a link to what changed.
- **If the check does not work, nothing happens and nothing is said.** No
  network, a hotel wifi login page, the server down, a garbled answer: the tool
  gets on with the game. It is not allowed to interrupt you over an update.
- **To install one, you ask for it.** It is downloaded to a temp folder, checked
  against the size and the SHA-256 the manifest published, and only then
  unpacked. If either does not match it is deleted, and nothing on your machine
  is touched.
- **Your files survive.** Your collected games (`data/`), card art (`assets/`),
  window positions (`.overlay.json`), `sources.json` and anything else you put
  in the folder are copied into the new build before it takes over. The old
  install is kept beside it as `bgtracker.old-<version>` until the new one has
  started once.
- **If anything goes wrong part way, the old install stays.** The swap itself is
  two folder renames, and either one failing puts everything back. If the
  machine dies between them you will find a `bgtracker-RECOVER.txt` next to the
  two folders saying which one to rename back.
- **Turn the check off** with `--no-update-check`, or for good by setting
  `BGTRACKER_NO_UPDATE_CHECK=1`, or by putting `{"check_on_start": false}` in
  `data/update.json`.

You can ignore all of this and just download the new zip from the
[Releases page](https://github.com/BattlegroundsHelp/bgtracker/releases) and
extract it over the top. The update does the same thing, more carefully.

`python update.py --check` prints what the server currently offers, which is the
fastest way to see whether the check is reaching anything at all.

---

## 3. What you will see the first time

The overlay is **eleven small windows**, not one big panel (ten without the
optional memory reader - OTHER PLAYERS needs it). Each one opens and closes
on its own trigger, at the moment it is about the thing in front of you. Each one
is **draggable on its own** and remembers its own spot in `.overlay.json`, so
moving the tavern window never moves anything else.

They only draw while Hearthstone (or one of the overlay's own windows) is the
window in front. Alt-tab to your browser and they all disappear. That is on
purpose.

The **settings panel** opens with it. That one is a normal window: it has a
title bar, you can move it, scroll it and close it, and it takes clicks like
any other program. Closing it leaves the overlay running, and the gear in the
bgtracker window's header opens it again. Section 3b says what is in it.

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
| **PICK YOUR HERO** | hero select | All four heroes, named and shown, each with one line saying when that hero is the pick (all 121 heroes have one, and those lines ship with the tool). The ranking numbers come from the community feed by default; a row it holds too few games for is flagged thin or stays blank. |
| **PICK YOUR HERO POWER** | that choice only | One row per hero power on offer, named and lined up. Numbers are the one gap here: the pool now collects and publishes hero-power stats, but this panel does not read that table yet, so most of the time every option shows a dash. |
| **PICK YOUR TRINKET** | trinket offers | The four trinkets, named, with the feed's numbers where they exist. |
| **PICK ONE** | discovers and Dark Gifts | The options, named. Dark Gifts have no published stats anywhere, so those stay unrated even with a source. |
| **OTHER PLAYERS** | while a lobby is running (it steps aside for a trinket offer) | Everyone else in place order: hero, tavern tier, health. For anyone you have fought, the board they were last seen holding, stamped `seen r7 · 2 rounds ago`; click a player to see it. **This window does not appear at all** unless you build the optional memory reader (section 5) - the log never states another player's board while you shop, so there is nothing to show without it. |

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
- The hero tips at the draft: they ship with the tool as plain text, so they
  need no source and no network.

**From the community feed, which is young:** hero and trinket rankings, pick
rates, sample sizes, measured tavern star ratings (the curated stars above stand
in where it is thin), measured comp averages. Anything the pool holds too few
games for is flagged thin or left blank rather than guessed; section 4 is how to
read your own games or another source instead. Two honest gaps at this pool
size: **hero-power numbers** are collected and published but the pick panel does
not read them yet, and the **comps file has no rows in it** because an archetype
is only published once 30 games have been classified into it (the curated
families cover for it meanwhile).

### Two things worth knowing on sight

- **The header dot**: green means the lobby's tribes are exact (memory reader),
  amber means inferred from the log so far, grey means still waiting.
- **Nothing is invented.** A number the log has not stated is drawn as a dash, not
  as a zero and not as a guess. A window with nothing real to say stays shut.

### About the combat odds

Both warbands are read out of the log before the fight animates and a Monte Carlo
simulation gives win / tie / loss. The same rollouts give a second line where
the log stated enough to compute it: roughly how much damage lands each way, and
the chance this fight ends you or them (`hit ~7 · take ~4 · they die 12% · we
die 3%`). Any part of that the log cannot support is left out rather than
guessed. Across 339 real logged fights it called the
winning side about **86%** of the time. It knows the vanilla rules, deathrattle
summons and the highest-impact per-card triggers, but plenty of cards are still
unscripted, so when one is on the board the odds are deliberately widened. It
never shows 0% or 100%. That, and the long tail still missing, is why it is
labelled BETA on screen. If either board could not be fully recovered it shows
no number at all.

If you want the mature version, run HDT's free Bob's Buddy alongside. Both tools
read the same log and coexist happily.

---

## 3b. The settings panel

It opens when the tool starts, and the gear in the bgtracker window's header
brings it back. Everything it saves goes in `settings.json`, next to
`sources.json`. **A flag you type on the command line beats the file for that
run and is never written into it**, so `--mmr 1` once does not quietly make
every later run a top 1% run; the panel says on screen when a flag is
overriding it.

- **DISPLAY.** One scale for the whole overlay, either worked out from the game
  window (a 4K game asks for about 2.00x) or set by hand on the slider. It is
  applied while you drag, so you can size it against the game instead of
  restarting to find out. Below it, a nudge for the badges printed on the cards:
  those already follow the game window on their own, so this only leans on them.
  If the nudge is not enough, drag them by hand: see **Moving the badges** just
  below.
- **DATA.** Sharing your finished games is **on by default**, and this box is
  the off switch: clear it and nothing is sent (or start with `--no-upload`
  to stop it for one run without saving anything). While it is on, the
  overlay sends one record per finished game - shortly after start for your
  whole log history, then per finished game (a record leaves when the next
  game starts, or when you quit). The line under the box lists exactly what a
  record holds: a scrambled game id, the date, the hero you played, your
  placement, whether it was Duos, the lobby tribes, the heroes and trinkets
  you were offered, the trinkets you picked, the first 8 characters of this
  machine's random client id (sent as is, so the feed can group one machine's
  games), and the client version. No name, no battletag, no log files. The pooled
  numbers are free for everyone and are never paywalled, whether you share or
  not. The same section picks where numbers come from (the community feed,
  which is the default, your own games, or whatever `sources.json` already
  says), the MMR bracket, the period, and Duos.
- **WHAT TO SHOW.** One switch per overlay window, built from the window
  registry, so a window added in a later version turns up here on its own. Off
  means the window is not built at all: no panel, no badges on the cards, and
  nothing routed to it. Switching one back on takes effect immediately.
- **UPDATES.** Which version you are running, when it last checked, a check now
  button, and, when there is something newer, what changed and an install
  button. If the server cannot be reached it says so; it never claims you are up
  to date without an answer.

Rows that cannot take effect until the next start say so in the row. That is
the MMR bracket, the period, Duos and the choice of feed: those four tables are
loaded once, when the log reader starts.

`--no-panel` starts without it, and the last checkbox in the panel turns off
opening it on start. The tool works exactly the same if you never open it.

### Moving the badges (calibrate mode)

The numbers and stars printed **on the cards** are not part of any panel. They
are thin transparent strips lying over the game, and they are click-through so
every click reaches Hearthstone. That is also what makes them impossible to
drag, because a drag is a click.

So there is a mode for it. The switch is the **`⇕ badges` chip in the header of
the window titled bgtracker**, just to the right of the title. It lives there
because that window is always up and cannot be switched off, and because no
click can ever land on a strip itself.

1. Click `⇕ badges`. Every strip appears at once, showing a marker per card slot
   and **no numbers at all** (a placeholder number is still a made-up number),
   and the chip turns into `⇕ done`.
2. **Click-through is off for as long as the mode is on.** That is the whole
   point of it, and the trade: while you are calibrating, a click that lands on
   a strip is taken by the strip and does not reach the game. Do it between
   games, not mid-fight. The game stays the front window throughout, so the
   overlay does not hide itself while you drag.
3. Drag each strip onto the row of cards it belongs to. There are four kinds
   (heroes, trinkets, the shop, and choose-one dialogs) and each is positioned
   on its own, because being wrong about one says nothing about the others. The
   pattern shows the number of slots that dialog usually deals, so it sits where
   the real badges will.
4. Click `⇕ done`. Click-through goes straight back on. It also ends on its own two other ways, because a mode left on is four bands of the screen the game cannot be clicked through: it times out after 90 seconds with no drag, and it closes the moment a fight starts, the markers disappear,
   and the real badges return.

What is saved is an offset as a **fraction of the game window**, not a pixel
position, so it survives a resolution or window-size change. The nudge is capped
(a fifth of the width, a bit under half the height) so a fumbled drag cannot
fling a strip off the game and out of reach. Deleting `.overlay.json` clears
the offsets along with the window positions.

---

## 4. Where the numbers come from

Out of the box, nothing to do: with no `sources.json` the overlay reads the
**community feed**, the pool of games players shared through this tool. It is
young, so plenty of rows are flagged thin; every game you play (with sharing
on, which is the default - section 3b) makes it less thin for everyone. The
two options below replace it.

### Option A: your own numbers from your own games only

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

About sharing: the overlay already contributes your finished games to the
community dataset on its own (on by default; the DATA box in the settings
panel and `--no-upload` are the off switches - section 3b). You do not need
to run anything for that. `python collect.py --upload <url>` still exists as
the by-hand version: it mines and sends everything in one pass, useful for
checking your games arrived or for pointing at a different server. Either
way the records are anonymised game results with no names and no battletags,
the aggregates are free for everyone, and the data is never sold. Uploading
was opt-in until 2026-08-12; the default changed then, and the CHANGELOG says
so in plain words.

### Option B: point it at a stats source you have the right to use

Copy `sources.example.json` to `sources.json` next to `bgtracker.py` and fill in
your own URLs or local file paths. `sources.json` is gitignored, so a personal
source never ends up in a commit. Writing the file replaces the built-in
community default entirely: only the keys you name are read, and a key you
leave out is a table you asked to keep empty.

```json
{
  "heroes":     "https://your-host.example/heroes-{time}.json",
  "heropowers": "https://your-host.example/heropowers-{time}.json",
  "trinkets":   "https://your-host.example/trinkets-{time}.json",
  "cards":      "https://your-host.example/cards-{time}.json",
  "comps":      "https://your-host.example/comps-{time}.json",
  "hero_tips":  "https://your-host.example/hero-tips-community.json"
}
```

- `{time}` becomes `all-time` | `past-seven` | `past-three` | `last-patch`, and
  `{mmr}` becomes your `--mmr` bracket. Both come from the command line flags.
- A feed publishes a bracket only once it holds enough games, so `top 1%` often
  does not exist yet. Then the tool reads the all players file instead and
  labels it as such - it will not print pooled numbers under a "top 1%" heading.
  Our own feed also stamps each file with the bracket it is (`"mmr": {"bucket":
  25, "minRating": 7400, ...}`), and that stamp wins over what was asked for.
- A value can be an `https` URL or a local file path (relative paths resolve next
  to `bgtracker.py`).
- URL responses are cached in `.cache/` for one hour.
- Delete a line to leave that table empty. Missing data degrades to "no numbers",
  it never crashes.
- `heroes_duo`, `heropowers_duo`, `trinkets_duo`, `cards_duo` and `comps_duo`
  are optional extra keys, used by `--duo`. They are the same tables built from
  Duos games only. There is deliberately no fallback from them to the solo
  tables: a Duos lobby is four teams finishing 1st-4th where solo is eight
  players finishing 1st-8th, so a solo number under a Duos heading would answer
  the wrong question. Leave them out and `--duo` shows no numbers instead.
  `collect.py --local-feed` writes them for you.
- `heropowers` is the hero **power** table. Nobody else publishes one at any
  price, so the pool computes its own. It is small by nature, since only some
  heroes make you choose a power at all, and the pick panel does not read it
  yet, so setting the key changes nothing on screen today.
- `hero_tips` is the **voted** hero tips feed written by `server/tips.py`. Leave
  it out and the tips that ship with the tool are the only ones you see, which
  is the default. A voted line is marked `▲` in the draft so it is never
  mistaken for a reviewed one.

**The JSON shape.** Each file is one object with one array in it:

| file | top level key | fields read from each row |
|---|---|---|
| heroes | `heroStats` | `heroCardId`, `averagePosition`, `totalOffered`, `totalPicked`, `dataPoints`, `placementDistribution`, `tribeStats[]` (each with `tribe`, `impactAveragePosition`, `dataPoints`, `dataPointsOnMissingTribe`) |
| heropowers | `heroPowerStats` | `heroPowerCardId`, `averagePosition`, `totalOffered`, `totalPicked`, `dataPoints`, `placementDistribution` |
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

`native/msync` is a small helper that reads the things Hearthstone never writes
to any log file:

- the **exact tribes in the lobby, at hero select** instead of learning them
  slowly from minions appearing,
- **hero picks re-scored for the lobby you are actually in** rather than a global
  average,
- your **MMR** in the SESSION window, and your board for synergy marks,
- the **leaderboard** - everyone's hero, tavern tier and health - and the board
  each opponent was last seen holding, which is the whole OTHER PLAYERS window.
  Without this helper that window never appears.

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
| `--mmr 100\|50\|25\|10\|1` | MMR bracket for the stats. `100` = everyone (default), `1` = top 1%. Needs `{mmr}` in your source URL. A bracket your feed has not published yet falls back to the all players numbers, and the tool says which bracket it actually used. |
| `--time last-patch\|past-seven\|past-three\|all-time` | How far back the stats go. Default `last-patch`. |
| `--duo` | Use Duos stats: heroes, trinkets, cards and comps, each from Duos games only (needs the `*_duo` sources). Never pooled with solo. |
| `--demo <path-to-Power.log>` | Replay a finished log through the real windows. Good for testing without playing. |
| `--diag` | Print the version, where it reads and writes, and every window it loaded, then exit. The first thing to paste in a bug report. |
| `--no-update-check` | Do not ask whether there is a newer build (section 2c). Nothing is ever installed either way. |
| `--no-upload` | Do not share finished games with the community feed, for this run only. The DATA box in the settings panel (section 3b) turns sharing off for good; it is on by default. |
| `--no-panel` | Start without opening the settings panel (section 3b). |

**Console version (`python bgtracker.py`)** - no overlay, just text. Takes
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
| `--upload <url>` | Send ALL your collected games to a shared feed, now, by hand. The overlay already shares new games on its own (on by default), so this is for checking your games arrived, or for a different server. |
| `--token <token>` | Upload token, if the server you are uploading to wants one. |

---

## 7. Troubleshooting

| symptom | likely cause | fix |
|---|---|---|
| **Nothing appears at all** | Hearthstone is in exclusive fullscreen. | Options → Graphics → **Borderless Windowed**. This is the number one cause. |
| **Two monitors, and the badges sit off the cards** | The overlay follows the game's rectangle in absolute desktop coordinates, so a second screen is fine in itself. What breaks it is MIXED SCALING: a scaled 4K panel next to an unscaled 1080p one. bgtracker asks Windows for per-monitor coordinates, which is the fix, but a Windows older than 10 version 1703 cannot give them. | Run `bgtracker.exe --diag`: it prints every display and the DPI awareness it actually got. If it says anything other than per monitor, put the game on the primary display or set both displays to the same scaling. |
| **"waiting for game" forever** | Hearthstone is installed somewhere other than the default path, so the overlay is watching an empty folder. The status line and `bgtracker.exe --diag` both name the folder being watched. The registry usually answers this on its own now; when it does not, set it yourself. | Put the install folder in `settings.json`: `{"hs_logs": "D:\Games\Hearthstone"}`. The Logs folder or the install folder both work, and environment variables expand. |
| **Nothing appears, and it is already borderless** | The overlay only draws while Hearthstone is the front window. Or it crashed on launch. | Click on the game. Then restore the minimised **bgtracker** console from the taskbar and read the last lines: `hb ... front=True anchored=True` means it is alive and anchored; `anchored=False` means it cannot see the game window. |
| **`'python' is not recognized`, or the Microsoft Store opens** | Windows ships a fake `python` that just opens the Store. | Easiest fix: use the download (section 2), which needs no Python. Otherwise install real Python from python.org with **Add python.exe to PATH** ticked; if the Store still hijacks it, Settings → Apps → Advanced app settings → **App execution aliases** → turn **off** `python.exe` and `python3.exe`, then relaunch. |
| **Windows are in the wrong place, off screen, or stacked on each other** | A saved drag position from a different resolution or monitor. | Quit the overlay, delete `.overlay.json` in the repo folder, start again. Every window returns to its default slot. (This also clears your session history.) |
| **The overlay covers cards I need to click** | Every window is draggable, individually. | Drag it by its header to somewhere better. It remembers. The badge strips drawn *on* the cards are click-through, so clicks reach the game anyway; to move those, use the `⇕ badges` chip in the bgtracker window's header (section 3b, **Moving the badges**). |
| **The badges sit slightly off the cards** | A resolution or window size the measured slots were not taken on. | Section 3b, **Moving the badges**: `⇕ badges` in the bgtracker header lets you drag each strip into place, and the offset is saved as a fraction of the game window. |
| **No numbers anywhere: hero picks show names but no placements** | The community feed (the default) could not be reached, or a `sources.json` you wrote leaves those tables out. | Check the console for a "feed unreachable" line. Section 4 has the alternatives: `python collect.py` then `python collect.py --local-feed`, then restart the overlay. |
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
   MINIONS, SESSION, OTHER PLAYERS, PICK YOUR HERO, PICK YOUR HERO POWER, PICK
   YOUR TRINKET, or PICK ONE. Eleven independent windows means "the overlay is
   wrong" narrows almost nothing down.
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
