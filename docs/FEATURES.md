# Features

What every surface shows, why it helps you play better, where the information
comes from, and what it needs to work.

The overlay is **eleven small independent windows** — ten without the optional
memory reader, since OTHER PLAYERS cannot exist without it. Each one opens and
closes on its own trigger and is dragged and remembered on its own
(`.overlay.json`).
There is no shared mode anywhere, so a bug in one surface cannot make another
one lie. [USAGE.md](USAGE.md) is how to install and run it,
[ARCHITECTURE.md](ARCHITECTURE.md) is how it is built, and this file is what it
does.

Two rules run through everything below:

* **Nothing is ever invented.** A number the log has not stated is drawn as a
  dash, and a window with nothing real to say stays shut.
* **The repo ships no stats data and points at no feed.** Every *feature* works
  out of the box; *numbers* appear once you configure a source in
  `sources.json` or grow your own with `collect.py --local-feed`. See
  [Your own data and the community dataset](#your-own-data-and-the-community-dataset).

## Contents

| area | window(s) | needs |
|---|---|---|
| [The pick moments](#the-pick-moments) | PICK YOUR HERO, PICK YOUR HERO POWER, PICK YOUR TRINKET, PICK ONE | nothing to detect and name; a stats source for numbers; hero tips ship with the tool |
| [The tavern](#the-tavern-stars-and-comp-tags) | TAVERN | nothing; a cards source for real star ratings |
| [Comps and your board](#comps-and-your-board) | bgtracker | nothing; a comps source for measured rows; memory reader for your board |
| [Lobby tribes](#lobby-tribes) | bgtracker, SESSION, MINIONS | nothing; memory reader for exactness at turn zero |
| [Counters](#counters) | COUNTERS | nothing; memory reader for board tribe counts |
| [Minion browser](#minion-browser) | MINIONS | nothing; a cards source for star ratings |
| [Session](#session) | SESSION | nothing; memory reader for MMR |
| [The other players](#the-other-players) | OTHER PLAYERS | the memory reader — without it the window never appears |
| [Combat odds BETA](#combat-odds-beta) | COMBAT | nothing |
| [Your own data](#your-own-data-and-the-community-dataset) | `collect.py`, `server/` | nothing |

Also: [What is deliberately NOT here](#what-is-deliberately-not-here) and
[How it compares to HDT / Tier7](#how-it-compares-to-hdt--tier7).

## Two data sources, and one of them is optional

**The log (default, and what everything is built on).** Hearthstone writes
`Power.log` itself. Reading it is exactly what Hearthstone Deck Tracker does,
Blizzard has publicly said log reading trackers are fine, and nothing here
injects, hooks or automates anything.

**Game memory (`native/msync`, optional, off unless you build it).** The lobby's
tribe list, your rating and your board are the things Hearthstone never writes
to any log. `msync` reads them out of the game's managed heap. That is against
the letter of Blizzard's EULA (section 1.C.vi prohibits software that reads or
mines information stored by the platform). Established trackers do the same for
some features and bans are unheard of, but this is the one component that
crosses the written line, which is why **it is not bundled**: you build it
yourself with `dotnet build native/msync -c Release`, or you leave it unbuilt
and every window still works with less, later. Where a feature needs it, this
document says so plainly.

## The pick moments

Four separate windows, one per kind of choose one dialog. Splitting them is why
picking a hero power no longer looks like picking a minion. All four sit down
the **left** edge, because a panel on the right would sit over the cards you are
choosing between (the trinket row reaches x 0.79 of the game window).

Ranked panels also draw a **badge strip**: a click through, transparent band
that writes each option's number over the actual card on screen, so the number
is attached to the thing it belongs to instead of being a list in a corner. A
higher priority strip hides a lower one, which is how the shop's stars step out
of the way while a pick is up.

### Heroes (PICK YOUR HERO)

**Shows.** The heroes on offer, ranked best first: one big colour graded
placement number each (greener is a better expected finish), the name, a sub
line reading `12% pick · 4,318 games`, a bar whose length maps the expected
finish, and the standout row highlighted. The same number is badged over each
portrait, with `best` under the best one and the pick rate under the others.
Under 30 games the sub line adds `thin!` and that row can never be marked best.
With no hero source, every row shows a dash, reads `no data at this MMR`, and
the panel prints `NO HERO STATS CONFIGURED`.

**Why it helps.** Hero choice is the highest leverage decision in a run and it
is made in about sixty seconds, from four names you may not know.

**From.** The draft burst in the log (each hero is dealt into `zone=HAND` under
your player id, already carrying its display name), plus your configured
`heroes` table. On screen order is corrected by the slot lines the client writes
just after the burst, so the badges land on the right portraits.

**Needs.** Nothing to open, list and name the heroes. A `heroes` source for the
numbers.

**Tips.** Under each hero's name, one line of written advice saying when that
hero is the pick — `strongest when the lobby has Beasts`, and so on. It is
drawn in the strip the placement bar would use, so the panel is exactly as tall
with tips as without and cannot grow past its band. **A hero with no tip shows
nothing at all**: no placeholder, no "no tip yet".

The tips are not data, they are text, so unlike every stats table they **ship
with the tool** — [`data/hero_tips.json`](../data/hero_tips.json), a plain file
you can edit next to the exe (your copy wins over the bundled one, so an edit
survives an update). 111 of the 121 heroes have a line. The ten that do not are
the ones whose hero power names a reward the card itself never describes, and
an empty line beats an invented one.

Anyone can add or fix one: open a pull request against that file, and that
review is the voting mechanism until something better exists. The rules are in
[CONTRIBUTING.md](../CONTRIBUTING.md), the contract is
[`data/hero_tips.schema.json`](../data/hero_tips.schema.json), and CI checks
every entry against it — including that the hero id actually exists, so a typo
fails the build instead of silently never appearing. Every seeded line was
written from the hero's own printed hero-power text; nothing is taken from
anyone else's guide, because those are that site's paid product.

**Lobby tuned scores.** When the tribes in the lobby are known *at draft time*
and your hero rows carry per tribe data (`tribeStats`), each hero is re scored
for the lobby you are actually in: base average plus the summed impact of every
tribe that is in, dropping tribe rows too thin to trust on either side. The
header then reads `tuned to this lobby` and each card gains a delta line
(`-0.06 here`). In practice this **needs the memory reader**, because the log
has not seen a single minion yet at hero select, so it knows no tribes at that
moment.

**Closes.** On the first shop minion appearing (which proves the hero is
picked), with a 75 second backstop.

### Hero powers (PICK YOUR HERO POWER)

**Shows.** One row per option: art, name, and a placement number or a dash. When
no option has a number the panel says `no hero-power stats - names only`.

**Why it helps.** It names and lines up the options while the dialog is up,
which is the whole honest job when no data for them exists anywhere.

**From.** Its own choose one block in the log, classified by card identity
against the card database (a hero power reads `TB_BaconShop_HP_...`, or the
hero id with a trailing `p`).

**Needs.** Nothing. **There is no hero power stats feed anywhere.** A number
appears only if a source you configured happens to carry a row for that exact
cardId. A power never borrows the average of the hero that owns it.

### Trinkets (PICK YOUR TRINKET)

**Shows.** The four trinkets on offer in the same ranked layout as the hero
draft, with the number badged on each card. With no trinket source the panel
prints `NO TRINKET STATS CONFIGURED` and `names only - see sources.json`.

**Why it helps.** Trinkets swing a run, there are two picks per game, and the
choice cannot be undone.

**From.** The trinket choose one block, which carries the exact on screen order
(the offer burst stages all four at `zonePos=0`, so its order is meaningless and
would badge the wrong cards). A genuine offer is **always exactly four options**,
which is what separates it from the opponents' trinkets staged in the same zone
every time you fight them. Numbers come from your `trinkets` table, preferring
the row for your MMR bracket when the source carries per bracket placements.

**Needs.** Nothing to open and name. A `trinkets` source for the numbers.

### Discovers and Dark Gifts (PICK ONE)

**Shows.** One row per option: art, a star rating, the name, and on the right
either `▶ yours` (it feeds the build your board is already on), or the comp it
belongs to, or its tavern tier. While this panel is up, the tavern's now stale
star badges hide themselves.

**Why it helps.** A discover is a free card you get to read once, under a clock,
and the useful question is not "is this good" but "is this good *for what I am
building*".

**From.** The discover choose one block in the log, scored exactly the way
tavern minions are (see below). Every option that can be scored is scored and
the rest show as no data, rather than dropping the whole panel because one token
or one brand new card is unknown.

**Needs.** Nothing to open and list. Stars behave as in the tavern. A **Dark
Gift shows its name only**: gifts are not pool minions and nobody publishes
placement data for them, so there is nothing honest to rate them with.

## The tavern: stars and comp tags

**Shows.** The shop you are looking at right now, rebuilt from scratch on every
roll, buy, sell and tavern spell. Each row: art, a 1 to 5 star rating, the name,
and on the right `▶ yours`, or the comp that minion belongs to, or its tavern
tier. The header carries the gold **already banked for next turn** (`+3g next`),
a `building <comp>` line when your board has a clear lean, and a `roll N`
counter at the foot. The same stars are badged over the real shop cards in slot
order, while the panel itself lists the best first.

**Why it helps.** It answers "which of these six actually helps me" at the only
moment it matters, and it flags the ones that feed the build you are already on
rather than the ones that are good in the abstract.

**From.** The shop is sampled from tracked entity state (what sits in play under
Bob's controller), because a reroll reuses the existing drag tokens and *no log
line ever says "this minion entered the shop"*. Ratings come from your `cards`
table.

Stars use the **differential**, `averagePlacement` minus
`averagePlacementOther`: how players who bought the card finished against
players who did not, binned inside the minion's **own tavern tier** and banded
top heavy (top 8% of its tier is five stars, top quarter is four). Raw averages
measure who buys a card, not whether it helps, and once rated an entire shop
five stars. A tier with fewer than ten rated minions gets no band at all, so its
minions show no stars rather than a rank invented out of three samples. A minion
that appears on at least 10% of the winning boards of the comp you are leaning
into gets one extra star.

**Needs.** Nothing to list the shop and tag comps. With no stats at all, stars
fall back to a coarse, deliberately blunt curated signal (3 stars for a core
minion of a comp family this lobby can build, 4 if it also feeds your current
build, 2 for a minion of a viable tribe, otherwise none), and the comp tags come
from those same curated families. A `cards` source turns the stars into measured
ratings. The `▶ yours` marker and the extra star need a `comps` source carrying
winning board frequencies, plus the memory reader for your board.

## Comps and your board

The window titled **bgtracker**. The only one that stays up the whole session,
and the one that owns the status line and the quit control.

**Shows.**

* **Tribe chips** for all ten tribes, coloured when the tribe is in this lobby.
* **YOUR BOARD (n)** with the comp it is leaning into and how many of your
  minions hit it (`▶ murloc poison 4/6`), or `no comp match yet`.
* **The comps still open to you**, one row each: a colour graded average
  placement, a tribe dot, the name, and the first few core minions underneath.
  The header link toggles between the best build per tribe and every build this
  lobby can make. Click a row to expand it into up to eight core minions with
  the percentage of winning boards each appears on.
* Rows under 300 games are labelled `thin data`. Rows with no measured data at
  all show a dot instead of a placement and are labelled `curated`.

**Why it helps.** It turns "what am I building towards" into a short list
already filtered to what this lobby can actually produce, and it tells you
whether the board you have is on one of those tracks or on none of them.

**From.** Your `comps` table when you have one. Without one, the window falls
back to **curated comp families**: evergreen tribe archetypes whose core minions
are computed from the **live card pool** (HearthstoneJSON, cached a day), so
they are always this patch's cards and never a hand written list going stale.
Curated rows carry no average and no sample, and say so. Your board comes from
the memory reader, sampled during recruit only (during a fight the game's play
zone is the combat copy, and reading it showed a board of 2 against a real board
of 7).

**Needs.** Nothing: the curated families always give the window something true
to say. A `comps` source replaces them with measured rows and real winning board
percentages. The board line and the lean need the **memory reader**; the log
cannot give a trustworthy board, so without it that block simply does not
appear.

## Lobby tribes

**Shows.** Which of the ten tribes are in this lobby, as chips in the bgtracker
window and the session window, as the default filter in the minion browser, and
as the filter behind every comp list. A header dot says how sure it is: green is
exact, amber is inferred so far, grey is waiting. The labels change with it
(`COMPS IN THIS LOBBY` versus `COMPS SEEN SO FAR`, `TRIBES IN LOBBY` versus
`TRIBES SEEN`).

**Why it helps.** Half of Battlegrounds strategy is knowing which builds are
even possible. Knowing at hero select rather than at turn 5 changes the hero you
pick, not just the minions you buy.

**From.** Two ways.

* **The log**, always available, partial. Every minion line carries its tribe,
  so seeing one **proves** that tribe is in. An unseen tribe is only ever "not
  seen yet"; the log can never prove a tribe is out. Measured on a real game, 6
  of 7 tribes were known within about 6 minutes (roughly turn 5) and the last
  one much later.
* **Game memory**, exact, and available from hero select onward.

**Needs.** Nothing for the inferred list. The **memory reader** for the exact
list, which is also what unlocks lobby tuned hero scores.

## Counters

**Shows.** One dense two row strip along the top of the right column: the turn,
gold `cur/max`, your tavern tier, what the next tier costs **right now**, gold
already banked for next turn, the tavern's elemental buff, your Blood Gem size,
what your board is made of (the three biggest tribe counts, plus a separate
count for minions that count as every tribe), free rerolls, triples earned, and
turns until the next trinket.

Gold, tier and the next tier price always keep their slot and show a **dash**
when the log has not stated them. Every other counter is simply absent until it
is real, never a zero. Chips are drawn most useful first, and when the two rows
are full the least important ones drop off rather than being clipped.

**Why it helps.** These are the numbers you keep in your head badly: what the
upgrade costs after this turn's discount, how much gold is already banked, how
big your Blood Gems are now. Reading them instead of remembering them is free
tempo.

**Why it is trustworthy.** Every value is a counter Hearthstone itself writes
into the log, taken from the `PowerTaskList` copy only (the copy in sync with
the screen), and everything written during a fight is held until the shop is
back. Inside one real fight our own tier read 4, then 0, then 6, then 4 as the
client mirrored the opponent onto our entity.

**From.** The log, tailed directly by this window. It backfills when you start
the overlay mid game, so the strip is populated immediately instead of a turn
later.

**Needs.** Nothing, and no stats source is involved in any of it. The board
tribe counts are the one exception: they need your board, which needs the
**memory reader**.

## Minion browser

**Shows.** A slim one line bar that is always on screen with a `browse` button.
Click it and it expands into the whole current minion pool, filtered by:

* **tier**: all, or any combination of 1 to 7,
* **tribe**: chips per tribe plus tribeless minions, defaulting to the tribes in
  **this lobby** (touch a chip and you take control, the `lobby` chip hands it
  back),
* **trait**: the mechanics the live pool actually carries, ordered by how often
  players think of them, with internal marker mechanics filtered out,
* **sort**: tier, name, or rating (rating is only offered when something real is
  behind it).

Rows show art, name, tavern tier, a tribe chip (`MIX` for multi tribe, `ALL` for
an Amalgam), and stars when rated. Click a row to expand it: tier, tribes and
traits, up to three lines of the real card text, and, only with a card table
behind it, `3.92 avg when bought vs 4.21 without · 12,904 games`. Page with the
up and down buttons or the mouse wheel; the footer reads `1-14 of 274` and
either `rated vs own tier · top 100%` or `no stats source`.

**Why it helps.** It answers the slow question between fights: what exists at
tier 5 for this tribe, which minions actually have Divine Shield, what does that
card you were just offered even do.

**From.** The live HearthstoneJSON card data, so it is always this patch's pool
and nobody's hand maintained list. Ratings use the same differential and the
same per tier bands as the tavern stars.

**Needs.** Nothing but the card database (fetched once, cached a day; fully
offline with no cache it says the pool is unavailable rather than showing a
wrong one). A `cards` source for the stars, and a minion inside a configured
table that has no row of its own shows a **dash**, never a guess.

## Session

**Shows.** How this sitting is going: how long it has been running, your rating
now in large type, the delta against the rating you started the sitting at
(`+128`, or `even`), then every game that **finished while the overlay was
running**, newest first, with a colour coded placement pill (first is gold, top
four green, 5 and 6 grey, 7 and 8 red), the hero, and the time it ended. The
list header carries the count and the average placement. When more games than
fit have been played, the rest are summed as `+N earlier this session`. At the
foot, this lobby's tribes. A `reset ›` link starts a fresh sitting by hand.

The sitting itself is saved next to this window's position, so relaunching the
overlay resumes the same session; a gap longer than five hours means the sitting
is over and the next launch starts a new one.

**Why it helps.** It is the honest scoreboard for the sitting, and the average
placement across it is the number that actually tells you whether to keep
playing.

**From.** The log, tailed live. A game counts only when the log **proves** it:
the hero draft identified you as the local player, and that player's last
leaderboard placement is read about two seconds of log time after the game turns
complete (reading it on the completion line itself scored three real games one
place too low). If the overlay was started mid game the draft is not in the
tail, so that game is simply not counted. These are the same records `collect.py`
writes, and the two de duplicate against each other.

**Needs.** Nothing for the games, placements and average. The rating needs the
**memory reader**: without it the whole rating block is replaced by one line
saying so, and with it but no successful read (Hearthstone closed) the number is
a **dash**, never the last reading dressed up as current.

## The other players

**Shows.** The leaderboard as its own window: every other player in place order,
their hero, their tavern tier and their health (armour shown as `30+9`), with
anyone who is out marked `out`. For each player you have already fought, the
board they were **last seen holding**, stamped with the round it was seen in and
how long ago that was — `seen r7 · 2 rounds ago`. Click a player to open that
board: their minions with the attack and health they had, in their real order.

**Why it helps.** It is the one thing you cannot get from the log while you
shop: what the people you are about to face actually had. Combined with their
tier and health it is the difference between "I think I am fine" and knowing.

**From.** Game memory only, through the **memory reader**. Hearthstone does not
write another player's board to Power.log during recruit — that has been checked
against real logs repeatedly and it is still true.

**Never invented.** A player you have not fought has no board line at all, not
an empty board and not a guess from their tier. The hero, tier and health are
live every reading; only the board is historical, and only the board carries the
"seen" stamp. Two measured facts shape what is kept: the seat that holds an
enemy warband in memory *also* holds Bob's shop, so anything the tavern is
offering is excluded (an early version reported the shop as somebody's board,
caught by checking a capture against the log's own record of the same fight);
and the warband is complete in memory before a fight animates and again after
it, but is being killed off *during* it, so the reading kept is the first of
each fight. Any reading that cannot be a board — more than seven minions, or
positions that are not a clean 1..N — is discarded rather than shown.

**Needs.** The **memory reader**. Without it this window never appears at all,
and nothing else in the overlay changes.

## Combat odds BETA

**Shows.** The round that is fighting, and one clearly flagged BETA line of
win / tie / loss percentages for the fight on screen, with the number of
simulated fights (3,000 by default) and a `log-only sim` marker. It opens the
instant the screen enters combat, holds for the whole fight, and closes the
instant the tavern is back.

**Why it helps.** Knowing you are 30% to win this fight is what tells you
whether to take the hit and push tier, or spend everything on the board now.

**From.** Both warbands are read out of the log **before the fight animates**.
Hearthstone writes each combat twice: the server batch lands roughly 1.4 seconds
ahead of the animation (measured across 222 real combats) with both boards and
the outcome in it, and the animation replay follows. The boards are taken from
the early copy, while every show and hide keys off the copy that is in sync with
the screen. A Monte Carlo simulator then replays the fight thousands of times.

**Needs.** Nothing at all. It is log only and involves no stats source.

**What BETA means here, honestly.**

* Across 251 real logged fights it called the winning side about **82%** of the
  time, with a mean absolute error around 17 percentage points and a Brier
  score of 0.101.
* It implements the vanilla combat rules (attack order, taunt, stealth, divine
  shield, poisonous and venomous, windfury, reborn, deathrattle ordering, the
  seven minion cap, hero damage as the tier sum) plus deathrattle token summons
  and cleave derived automatically from the current card pool, plus
  hand written scripts for the cards that were measurably costing the most
  accuracy: Rally on attack triggers, deathrattle buffs, Reborn watchers,
  rule changing auras and the trigger style Dark Gifts.
* The long tail of cards is still **unscripted**, and that is the honest catch:
  a simulator is an encyclopedia of card interactions that needs re verifying
  every patch, forever. Rather than hide that, the sim counts how many
  unscripted combat effects are on the two boards and **widens its odds**
  accordingly, so it never prints a 0% or a 100% it cannot back.
* **No number is ever shown for a board it could not fully recover.** If any
  minion lacks a card id, or a side is empty (rounds 1 and 2 genuinely produce
  this), the window says the boards were not fully readable instead of guessing.
  Board recovery measured over 6 real logs: 149 of 149 combats from round 5 on,
  220 of 222 across all rounds.
* HDT's **Bob's Buddy** is the mature option and the two coexist happily: both
  read the same log, so run it alongside if you want the trustworthy number.
* `sim/validate.py` scores the simulator against your own logs and names the
  exact cards worth scripting next.

## Your own data and the community dataset

**The stance.** Aggregate placement data belongs to whoever collected it. The
big stats sites' numbers are their collectors' property and none of them permit
third party redistribution. So this tool **bundles no stats, fetches none by
default, and points at nobody's feed**. A public URL is not a licence. Offers
are still detected and named without any data, because recognition comes from
the public card database.

**`python collect.py`** mines every finished game out of your whole Power.log
history into `data/games.jsonl`: date, game id, hero, placement, lobby tribes,
the heroes and trinkets you were offered, and the trinkets you took. It touches
nothing live (safe to run while the overlay is running) and de duplicates on the
game's start position, so re running only adds new games. `--stats` prints what
you have so far. The offer fields are what make pick rate computable at all: an
average needs only the result, but "how often is this taken when it is shown"
needs the options you turned down. Honest limit: the backfill recovers tribes
and dates reliably, while hero and placement come out thinner from old log files
than they do from games the overlay watches live.

**`python collect.py --local-feed`** runs the same aggregator the community
server uses over your own games, writes hero, trinket, card and comp feeds into
`data/feed/` for each of the four time windows, and (only if you have no
`sources.json` yet) writes one pointing at them. The overlay then shows **your
own numbers**, with no third party involved. Thin samples stay flagged until
they fill in; under 30 games an average reads as no signal at all.

**The community dataset** is **up**, and `sources.example.json` points at it.
It is new, so it holds a few dozen games: expect most rows to be flagged thin,
which means no signal rather than weak signal. Its terms were fixed before it
existed: uploading is **opt in only** and off by default
(nothing leaves your machine unless you turn it on), records are anonymised game
results (hero, placement, lobby tribes, final board, no names, no battletags, no
account ids) under an opaque per machine id, the aggregates are **free for
everyone**, and the data is **never sold or paywalled**. The server half is
deliberately tiny: stdlib Python, no pip install, its own SQLite file, a
validated insert on the public endpoint and the heavy grouping on a timer off
the request path. What it does not do yet is honest too: comp classification is
not built (the comps file is written empty, so the client falls back to curated
families instead of erroring), pick rates only appear once clients upload the
offers, and per tribe hero impact is not split out yet. MMR brackets ARE split
(five of them, the same `--mmr 100|50|25|10|1` the client asks for), but a
bracket is only published once it holds 30 games, so on a young pool most of
them do not exist and the client falls back to the all players numbers and says
so rather than labelling the whole pool "top 1%". A
public write endpoint is not tamper proof against a determined stats poisoner,
and it is not advertised as one.

**Needs.** Nothing, and nothing leaves your machine unless you pass `--upload`
yourself.

## What is deliberately NOT here

* **Combat odds are BETA, not Bob's Buddy.** About 82% winner accuracy over 251
  real logged fights, with the highest impact cards scripted but a long tail
  that is not. It is labelled BETA on screen for exactly that reason. If you
  want the mature version, run HDT's free Bob's Buddy alongside.
* **Hero tips are one line, not a strategy guide.** The pick panel says when a
  hero is the pick and stops there. Full written guides are hand written content
  and the paid sites' versions cannot be reused, so what exists here is a
  community file anyone can extend by pull request, seeded from each hero's own
  printed power text. Depth comes from contributors or not at all.
* **No bundled stats and no default feed.** Not an oversight, see the stance
  above. Every feature works without them.
* **No Dark Gift ratings and no quest stats.** Nobody publishes gift placement
  data, and quests are dead this patch. Heroes, trinkets, tribes, comps and
  minions are the complete set of what can honestly be shown.
* **No proof that a tribe is out, from the log alone.** Seeing a minion proves
  its tribe is in; an unseen tribe is only ever "not seen yet". Exactness needs
  the memory reader.
* **No exclusive fullscreen support.** Nothing can draw over it without hooking
  the game, which this deliberately does not do. Keep Hearthstone in borderless
  windowed.
* **No injection, no client modification, no automation of any kind**, and no
  account, no subscription, no ads.
* **Not built yet, tracked in [ROADMAP.md](../ROADMAP.md):** movable badges (the
  strips are click through so clicks reach the game, which is exactly what makes
  them undraggable), badges drawn on the discover cards themselves, turn by turn
  minion advice, mechanical synergy ("you have 4 beasts, this buffs beasts"),
  and opponent last seen boards.
* **Duos** is collected and counted separately from solo. The collector marks
  every game from the log itself, and `--duo` reads Duos-only heroes, trinkets,
  cards and comps. The two are never pooled - a Duos lobby is four teams
  finishing 1st-4th, a solo lobby is eight players finishing 1st-8th.

## How it compares to HDT / Tier7

HDT is the incumbent. It is free, it is fine, and it does things this does not.

| | HDT / Tier7 | this |
|---|---|---|
| Combat odds (Bob's Buddy) | free, mature | **beta**: log only, clearly flagged, about 82% of fights called correctly over 251 real logged fights. Run Bob's Buddy alongside if you want the mature one |
| Counters (gold, tier price, buffs, tribes) | free | yes |
| Minion browser | free | yes, the live pool, no stats needed |
| MMR session tracker | free | yes, with the memory reader for the rating |
| Hero pick stats | overlay is Tier7 | yes, from your own data source |
| Trinket pick stats | Tier7 | yes, from your own data source |
| Comps filtered to your lobby, with key minions | Tier7 | yes, from your own data source |
| Tribes in the lobby | exact | exact with the memory reader, else inferred |
| Hero picks tailored to the lobby's tribes | Tier7 | yes, with the memory reader |
| Written hero advice at the draft | Tier7, paid and hand written | one line per hero, community written, ships with the tool and free |
| Opponents' last-seen boards | free | yes, with the memory reader, stamped with the round it was seen |
| Duos | some of it | heroes, trinkets, cards and comps from Duos games only, never pooled with solo |

The last row needs `native/msync` built. The lobby scoring arithmetic itself is
standard and documented in open source trackers; what you bring is a data source
with per tribe rows on each hero. The other thing that was ever missing is
knowing the tribes at turn zero, and that comes out of memory.

## See also

* [README](../README.md), install, flags, and the safety section in full
* [USAGE.md](USAGE.md), the step by step guide for a first run
* [ROADMAP.md](../ROADMAP.md), what is open and why the unbuilt things are unbuilt
* [ARCHITECTURE.md](ARCHITECTURE.md), how it is built, including every log
  parsing gotcha that cost real debugging time
* [server/README.md](../server/README.md), the aggregator and the upload contract
