# Roadmap

Status of everything asked for so far - by the author or by the r/BobsTavern
community. ✅ shipped · 🔨 partial · ⬜ open · ❌ not possible (with why).
If you want to pick something up, [CONTRIBUTING.md](CONTRIBUTING.md) has the
ground rules and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) the map.

## Shipped

- ✅ **Hero + trinket pick stats at the moment of choice** - average placement,
  pick rate, top-4, sample size, as badges on the actual cards. MMR bracket and
  time-window filters (5 MMR buckets - finer than HSReplay's free tier).
- ✅ **Ranked tavern minions** - per-tier star ratings on the shop cards, from
  the placement *differential* (players-who-bought vs not), not raw averages.
- ✅ **Comps filtered to your lobby** - best archetypes still open to you given
  the tribes in play; click a comp to expand its core minions with how often
  they appear on winning boards.
- ✅ **Lobby tribes** - exact at hero select with the opt-in memory reader,
  inferred progressively from the log without it.
- ✅ **Lobby-tuned hero scores** - heroes re-scored for the tribes actually in
  this lobby (memory reader).
- ✅ **Board synergy** - reads your warband and shows which comps it's hitting,
  marks tavern minions that feed your build (memory reader).
- ✅ **Discover / Dark Gift pick panels** - per-option ratings, stale shop
  badges hidden while a pick is up.
- ✅ **Card portraits** - `python fetch_art.py --all` pulls tiles + crops from
  HearthstoneJSON; overlay degrades to colored dots without them.
- ✅ **One window per thing** - the overlay is a set of small independent
  windows (counters, combat, tavern, comps, minion browser, session, and one
  per kind of choose-one), each opening and closing on its own trigger and
  draggable on its own. No shared mode, so a bug in one surface cannot make
  another one lie. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- ✅ **Counters** - turn, gold `cur/max`, tavern tier and what the next tier
  costs right now, gold already banked for next turn, elemental and Blood Gem
  buffs, your board's tribe counts, free rerolls, triples, turns until the next
  trinket. Every one of them is a counter the game itself writes; anything the
  log has not stated is a dash, never a zero.
- ✅ **Minion browser** - the whole current pool, filtered by tavern tier,
  tribe and mechanic, with card text and art. Built from the live card data, so
  it is always this patch's pool, and it needs no stats source to be useful.
- ✅ **Session tracker** - MMR now vs when the sitting started, and every game
  that finished while the overlay was running with its placement and hero. The
  rating needs the opt-in memory reader; without it the games and placements
  still count and the rating is a dash, never a guess.
- ✅ **Combat odds (BETA)** - see the note below: shipped, clearly flagged, and
  honest about being approximate.
- ✅ **Own-data collector** (`collect.py`) - mines your finished games out of
  the log history into `data/games.jsonl`. The seed of an independent dataset:
  with enough users pooling their own play, the same average-placement numbers
  can be computed without leaning on anyone else's feed.
- ✅ **Duos** - collected and counted as its own dataset. Every mined game is
  marked solo or Duos from the log itself (the `BACON_DUO_TEAM_ID` /
  `BACON_DUO_TEAMMATE_PLAYER_ID` tags on the player entity, which agreed with
  the game's own `GameType` line on 33 of 33 real games), and the aggregator
  writes a separate Duos feed for heroes, trinkets, cards and comps. `--duo`
  reads those. Nothing is pooled: a Duos lobby is four teams finishing 1st-4th,
  a solo lobby is eight players finishing 1st-8th, so one shared average would
  describe neither. This used to be "blocked on data" - it wasn't, the data was
  in your own logs all along.
- ✅ **Opponents' last-seen boards** - the log provably never contains opponent
  boards during recruit, so this one is memory-only: `native/msync` now emits
  the leaderboard (`players`) and the OTHER PLAYERS window shows every other
  player's hero, tavern tier and health, plus the board each was last seen
  holding, stamped with the round and how long ago. Two things had to be
  measured rather than assumed. The seat that hosts the enemy warband also
  hosts Bob's shop, so an early version reported the tavern as somebody's
  board (caught by checking a captured board against the log's own snapshot of
  the same fight); shop minions are now excluded by their drag-buy token. And
  the warband is complete in memory *before* the fight animates and again
  after it, but decimated *during* it - so the reading kept is the fullest one
  of each fight. Needs the memory reader; without it the window never appears.
- ✅ **Per-hero tips at the draft** - the most-requested feature in the
  r/BobsTavern thread, built as a mechanism rather than a corpus: one line per
  hero saying when it is the pick, drawn under the name at hero select. They
  live in [`data/hero_tips.json`](data/hero_tips.json), ship with the tool, and
  anyone can add or fix one by pull request. **All 121 heroes now have a line**,
  each written from the hero's own printed hero-power text. The last ten were
  the awkward ones, whose power names a reward the card itself never spells out
  (a Quest, a Timewarp, a Darkmoon Prize); their lines describe the cost, the
  timing and what the power actually asks of you, and stop where the card stops
  rather than inventing the reward. Nothing is copied from anyone else's guide,
  since those are that site's paid product.
- ✅ **Voting on the tips** - the pull request is no longer the only route.
  `server/tips.py` takes submissions and votes and publishes
  `hero-tips-community.json`, which the client reads like any other feed (the
  `hero_tips` key in `sources.json`; leave it out and that feed stays off). A
  line reaches that file only once distinct voters, its score, and a margin
  over the shipped line have all cleared their floor, so a handful of
  manufactured voters changes nothing anybody sees, and below the floor the
  shipped line stands. A voted line is marked `▲` in the draft so it is never
  mistaken for a reviewed one. There is deliberately no vote button in the
  overlay: the hero draft is a sixty second decision, the band is full at four
  heroes, and a one-click vote from an anonymous overlay is a ballot box with
  no lock. Voting happens on the feed's own page, which the draft header names
  when the feed names one. Honest limit: nothing here knows who anyone is, so
  somebody rotating client ids across many addresses can still manufacture
  voters. The floors are the lock, not the ballot box.
- ✅ **MMR brackets in our own feed** - the aggregator publishes the same five
  brackets the client asks for and stamps every file with the bracket it is. A
  bracket appears only once it holds 30 games, and until then the client reads
  the all-players file and says so instead of labelling the whole pool
  "top 1%".
- ✅ **Movable badges** - the badge strips are click-through so every click
  reaches the game, which is exactly what made them undraggable. The way out is
  a mode, not a permanent compromise: the `⇕ badges` chip in the bgtracker
  window's header turns **calibrate mode** on, which drops click-through on
  every strip so it can be dragged, and puts it back the moment you press
  `⇕ done`. While it is on the strips show a marker per slot and no numbers at
  all, because a placeholder number is still a made-up number. What is saved is
  a per-kind offset in fractions of the game window, so it survives a
  resolution change, and the nudge is capped (0.20 of the width, 0.40 of the
  height) so a fumbled drag cannot fling a strip out of reach.
- ✅ **Badges on the discover/dark-gift cards themselves** - the PICK ONE and
  PICK YOUR HERO POWER windows now carry their own badge strip, so the star
  rating is written over the card you are reading instead of only in the panel.
  The band had to be re-measured: on the Choose One frame the cards run y
  302-617, with the name banner at ~475 and the tribe and stat banners at
  630-670, so the old 0.63 landed the stars on top of the tribe banner. 0.30
  puts them across the top of the card art, clear of the tier gem and of every
  line of text the card prints.
- ✅ **Mechanical synergy** - "this card pays off Beasts, and you are holding
  four of them", read out of the card database alone (`ui/synergy.py`), so it
  works with no stats source, no community feed and no memory reader. Three
  things count and nothing else: the card's own text naming a tribe, Magnetic
  (which attaches to a Mech without saying the word), and Blood Gems (a
  Quilboar mechanic the text spells differently). "Your minions", Spellcraft
  and simply belonging to a tribe are deliberately not counted, because a tag
  that fires on nearly every card says nothing. The tavern shows the short form
  on a row that has no comp to name, the PICK ONE panel gives every option its
  own line. The COUNT needs the memory reader; without it the payoff is still
  named and no number is printed, because "how many Beasts do you hold" has no
  answer in Power.log.
- ✅ **Turn-by-turn minion advice** - opening a row in the minion browser now
  answers *when* a minion pays off, when the configured feed carries a per-turn
  breakdown: four stretches of the game, each showing the same
  buy-it-vs-skip-it difference the stars use. Splitting one card's games across
  fourteen turns is how a healthy sample becomes fourteen small ones, so a
  stretch under the sample floor prints the word `thin` with its game count and
  never a number, a stretch nobody played it in is a dash, and a feed with no
  breakdown says so in one line rather than drawing an empty grid.
- ✅ **A hero-power table, which nobody else publishes at any price** - only
  some heroes offer a power to choose between, and no stats site sells numbers
  for that choice. The collector now mines the offer and the pick
  (`offered_hero_powers` / `picked_hero_powers`), the aggregator turns them into
  a `heropowers` feed built exactly like the hero table, and the client reads it
  (`bgtracker.hero_power_table`, the `heropowers` key in `sources.json`). See
  Partial below for the half that is not wired yet.

## Partial

- 🔨 **Community dataset** - the pooling half of the own-data collector: an
  upload endpoint plus an aggregator that turns shared game records into the
  stats feed the client already reads. The server is **up**, it splits solo
  from Duos and publishes MMR brackets, and since 2026-08-12 the overlay
  itself feeds it: with no `sources.json` the client reads the community feed,
  and the overlay uploads each finished game on its own (`pool.py`). What is
  still thin is the pool itself: it holds a few dozen games, so most rows are
  flagged thin and most brackets are not published yet. **The terms CHANGED on
  2026-08-12**, and saying so is part of the terms: uploading was opt-in and
  off by default from the day the server existed until then; it is now **on by
  default with an opt-out** (the settings panel's DATA box, or `--no-upload`
  for one run), the author's call, made because a pool nobody feeds serves
  nobody. The rest stands exactly as first promised: records are anonymised
  (hero, placement, lobby tribes, offers; no names, no battletags), the
  aggregates are free for everyone, and the data is never sold or paywalled.
  **Comp classification is now built**: `server/aggregate.py` runs every shared
  final board through the client's own rule (`bgtracker.classify_board` - a
  board belongs to the tribe it is mostly made of, and only when that family's
  engine piece is standing on it), and a board that matches nothing is counted
  under "none" rather than forced into the nearest bucket. Rows only publish
  above a 30-game floor, though, so **on today's pool the comps file still
  carries no rows** - it carries the counts instead, saying how many boards were
  classified, how many matched nothing, and what the floor is. "We classified
  this many boards and no archetype has 30 games yet" is a fact; a table of
  four-game averages is not. Still missing: per-tribe hero impact, and any
  real defence against a
  determined stats poisoner. Meanwhile `collect.py --local-feed` gives every
  player their own personal feed, and comps fall back to curated families
  computed from the live card pool - so nothing shows a blank panel.

- ✅ **Hero-power numbers in the pick panel** - the pick panel used to name
  the options and rate none of them, because no feed anywhere published hero
  power numbers. The collector mines them now (the choose-one block whose every
  option is a hero power), the aggregator publishes a table in the same shape
  as the hero one, and PICK YOUR HERO POWER reads THAT table: never the owning
  hero's average, and never the card table, which could not match a hero power
  by construction. An option the feed does not carry, or carries too thinly to
  stand behind, draws a dash.
- 🔨 **Combat win % (a Bob's Buddy equivalent)** - shipped as BETA and labelled
  BETA on screen. Both warbands come out of Power.log before the fight
  animates, and a Monte Carlo sim over the vanilla rules, derived deathrattle
  summons and per-card scripts for the highest-impact cards calls the winning
  side ~86% of the time across 339 real logged fights (MAE 13pp, Brier 0.072).
  Beside win/tie/loss the same rollouts give the damage bands (`hit ~7 ·
  take ~4`, hero tavern tier included) and the chance the fight kills you or
  them. Because plenty of cards are still unscripted, the odds are deliberately
  widened when the board holds one, so a raw 0% or 100% is never printed. No
  odds are shown at all unless both boards were fully recovered. What is still
  missing is the long tail of per-card triggers, and that is the honest catch:
  a simulator is an
  encyclopedia of card interactions that needs re-verifying every patch,
  forever. It is a smaller encyclopedia than it sounds, though, and
  [`docs/CARD_EFFECTS.md`](docs/CARD_EFFECTS.md) counts it exactly: of 274
  pool minions only 39 act during combat at all, 18 of them still unscripted,
  because 141 have already resolved into the stats by the time the boards are
  captured. Dark Gifts are finished: all 40 are accounted for and none is
  missing. `sim/validate.py` names the exact cards to script next. If you want
  the mature version, run HDT's free Bob's Buddy alongside - both tools read
  the same log and coexist happily.

## Open

- ⬜ **Quick disconnect/reconnect button** - reconnecting is the standard fix
  for a hung fight or a frozen shop, and doing it by hand costs a full client
  relaunch. It is doable: closing the TCP socket Windows owns for the
  Hearthstone process makes the client show its own reconnect, which is what
  Sysinternals TCPView does and touches nothing inside the game. It is not in
  this repository, and the reason is a judgement rather than a technical one:
  it needs an Administrator shell, and a free unsigned tool that asks for
  Administrator to close a network connection is a thing users are right to be
  suspicious of. Open until that trade is worth making.
- ⬜ **macOS** - untouched, and it is not a small job. The log parsing is plain
  Python and would port as is, but everything that puts a window over the game
  (finding the Hearthstone window, following it, click-through, staying hidden
  while the game is not in front) is Win32, and so is the memory reader. Nobody
  has started it and there is no Mac here to test on, so no promises.
- ⬜ **Linux** - same story, one step further: the game itself only runs there
  through Wine or Proton, so an overlay has to deal with that as well.
  Unaddressed.

## Not possible today (and why)

- ❌ **Dark Gift ratings** - nobody publishes placement data for gifts.
- ❌ **Quest stats** - quests are dead this patch; no source has rows for them.
- ❌ **Provably excluded tribes from the log alone** - seeing a minion proves
  its tribe is in; an unseen tribe is only ever "not seen yet". Exactness
  needs the memory reader.
- ❌ **Tablet/iPad overlay** - iOS can't host an overlay over another app.
