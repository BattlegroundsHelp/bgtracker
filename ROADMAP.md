# Roadmap

Status of everything asked for so far — by the author or by the r/BobsTavern
community. ✅ shipped · 🔨 partial · ⬜ open · ❌ not possible (with why).
If you want to pick something up, [CONTRIBUTING.md](CONTRIBUTING.md) has the
ground rules and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) the map.

## Shipped

- ✅ **Hero + trinket pick stats at the moment of choice** — average placement,
  pick rate, top-4, sample size, as badges on the actual cards. MMR bracket and
  time-window filters (5 MMR buckets — finer than HSReplay's free tier).
- ✅ **Ranked tavern minions** — per-tier star ratings on the shop cards, from
  the placement *differential* (players-who-bought vs not), not raw averages.
- ✅ **Comps filtered to your lobby** — best archetypes still open to you given
  the tribes in play; click a comp to expand its core minions with how often
  they appear on winning boards.
- ✅ **Lobby tribes** — exact at hero select with the opt-in memory reader,
  inferred progressively from the log without it.
- ✅ **Lobby-tuned hero scores** — heroes re-scored for the tribes actually in
  this lobby (memory reader).
- ✅ **Board synergy** — reads your warband and shows which comps it's hitting,
  marks tavern minions that feed your build (memory reader).
- ✅ **Discover / Dark Gift pick panels** — per-option ratings, stale shop
  badges hidden while a pick is up.
- ✅ **Card portraits** — `python fetch_art.py --all` pulls tiles + crops from
  HearthstoneJSON; overlay degrades to colored dots without them.
- ✅ **One window per thing** — the overlay is a set of small independent
  windows (counters, combat, tavern, comps, minion browser, session, and one
  per kind of choose-one), each opening and closing on its own trigger and
  draggable on its own. No shared mode, so a bug in one surface cannot make
  another one lie. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- ✅ **Counters** — turn, gold `cur/max`, tavern tier and what the next tier
  costs right now, gold already banked for next turn, elemental and Blood Gem
  buffs, your board's tribe counts, free rerolls, triples, turns until the next
  trinket. Every one of them is a counter the game itself writes; anything the
  log has not stated is a dash, never a zero.
- ✅ **Minion browser** — the whole current pool, filtered by tavern tier,
  tribe and mechanic, with card text and art. Built from the live card data, so
  it is always this patch's pool, and it needs no stats source to be useful.
- ✅ **Session tracker** — MMR now vs when the sitting started, and every game
  that finished while the overlay was running with its placement and hero. The
  rating needs the opt-in memory reader; without it the games and placements
  still count and the rating is a dash, never a guess.
- ✅ **Combat odds (BETA)** — see the note below: shipped, clearly flagged, and
  honest about being approximate.
- ✅ **Own-data collector** (`collect.py`) — mines your finished games out of
  the log history into `data/games.jsonl`. The seed of an independent dataset:
  with enough users pooling their own play, the same average-placement numbers
  can be computed without leaning on anyone else's feed.
- ✅ **Duos** — collected and counted as its own dataset. Every mined game is
  marked solo or Duos from the log itself (the `BACON_DUO_TEAM_ID` /
  `BACON_DUO_TEAMMATE_PLAYER_ID` tags on the player entity, which agreed with
  the game's own `GameType` line on 33 of 33 real games), and the aggregator
  writes a separate Duos feed for heroes, trinkets, cards and comps. `--duo`
  reads those. Nothing is pooled: a Duos lobby is four teams finishing 1st-4th,
  a solo lobby is eight players finishing 1st-8th, so one shared average would
  describe neither. This used to be "blocked on data" — it wasn't, the data was
  in your own logs all along.
- ✅ **Opponents' last-seen boards** — the log provably never contains opponent
  boards during recruit, so this one is memory-only: `native/msync` now emits
  the leaderboard (`players`) and the OTHER PLAYERS window shows every other
  player's hero, tavern tier and health, plus the board each was last seen
  holding, stamped with the round and how long ago. Two things had to be
  measured rather than assumed. The seat that hosts the enemy warband also
  hosts Bob's shop, so an early version reported the tavern as somebody's
  board (caught by checking a captured board against the log's own snapshot of
  the same fight); shop minions are now excluded by their drag-buy token. And
  the warband is complete in memory *before* the fight animates and again
  after it, but decimated *during* it — so the reading kept is the fullest one
  of each fight. Needs the memory reader; without it the window never appears.
- ✅ **Per-hero tips at the draft** — the most-requested feature in the
  r/BobsTavern thread, built as a mechanism rather than a corpus: one line per
  hero saying when it is the pick, drawn under the name at hero select. They
  live in [`data/hero_tips.json`](data/hero_tips.json), ship with the tool, and
  anyone can add or fix one by pull request — that review is the voting for
  now. 111 of 121 heroes are seeded, each written from the hero's own printed
  hero-power text; the ten left out are the ones whose power names a reward the
  card never describes, and no tip beats an invented one. Nothing is copied
  from anyone else's guide, since those are that site's paid product.
- ✅ **MMR brackets in our own feed** — the aggregator publishes the same five
  brackets the client asks for and stamps every file with the bracket it is. A
  bracket appears only once it holds 30 games, and until then the client reads
  the all-players file and says so instead of labelling the whole pool
  "top 1%".

## Partial

- 🔨 **Community dataset** — the pooling half of the own-data collector: an
  upload endpoint plus an aggregator that turns opt-in game records into the
  stats feed the client already reads. The server is **up**, and it now splits
  solo from Duos and publishes MMR brackets. What is still thin is the pool
  itself: it holds a few dozen games, so most rows are flagged thin and most
  brackets are not published yet. The terms were fixed before it existed:
  upload is opt-in only (off by default), records are anonymised (hero,
  placement, lobby tribes, final board — no names, no battletags), aggregates
  are free for everyone, and the data is never sold or paywalled. Still
  missing: comp classification (that file is written empty rather than faked),
  per-tribe hero impact, and any real defence against a determined stats
  poisoner. Meanwhile `collect.py --local-feed` gives every player their own
  personal feed, and comps fall back to curated families computed from the live
  card pool — so nothing shows a blank panel.

- 🔨 **Combat win % (a Bob's Buddy equivalent)** — shipped as BETA and labelled
  BETA on screen. Both warbands come out of Power.log before the fight
  animates, and a Monte Carlo sim over the vanilla rules, derived deathrattle
  summons and per-card scripts for the highest-impact cards calls the winning
  side ~86% of the time across 339 real logged fights (MAE 13pp, Brier 0.072).
  Because plenty of cards are still unscripted, the odds are deliberately
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
  the mature version, run HDT's free Bob's Buddy alongside — both tools read
  the same log and coexist happily.

## Open

- ⬜ **Movable badges** — the badge strips are click-through so clicks reach
  the game, which is exactly what makes them un-draggable. Plan: a nudge
  hotkey or a settings drag-handle that temporarily disables click-through.
- ⬜ **Badges on the discover/dark-gift cards themselves** — needs one
  calibrated Choose-One frame to measure slot positions, like the hero and
  shop rows were. Ratings currently show in the pick panel instead.
- ⬜ **Turn-by-turn minion advice** — the per-minion stats carry a full
  turn-by-turn breakdown that nothing surfaces yet.
- ⬜ **Mechanical synergy** — cards.json carries every card's keywords, so
  "you have 4 beasts, this buffs beasts" is computable; deeper than the
  current statistical "appears on X% of winning boards".
- ⬜ **Quick disconnect/reconnect button** — would have to drive the game or
  Battle.net, which sits outside the read-only design. Unlikely.
- ⬜ **macOS** — untouched, and it is not a small job. The log parsing is plain
  Python and would port as is, but everything that puts a window over the game
  (finding the Hearthstone window, following it, click-through, staying hidden
  while the game is not in front) is Win32, and so is the memory reader. Nobody
  has started it and there is no Mac here to test on, so no promises.
- ⬜ **Linux** — same story, one step further: the game itself only runs there
  through Wine or Proton, so an overlay has to deal with that as well.
  Unaddressed.

## Not possible today (and why)

- ❌ **Dark Gift ratings** — nobody publishes placement data for gifts.
- ❌ **Quest stats** — quests are dead this patch; no source has rows for them.
- ❌ **Provably excluded tribes from the log alone** — seeing a minion proves
  its tribe is in; an unseen tribe is only ever "not seen yet". Exactness
  needs the memory reader.
- ❌ **Tablet/iPad overlay** — iOS can't host an overlay over another app.
