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

## Partial

- 🔨 **Community dataset** — the pooling half of the own-data collector: an
  upload endpoint plus an aggregator that turns opt-in game records into the
  stats feed the client already reads. Built; not yet deployed to a host. The
  terms are fixed before it exists: upload is opt-in only (off by default),
  records are anonymised (hero, placement, lobby tribes, final board — no
  names, no battletags), aggregates are free for everyone, and the data is
  never sold or paywalled. Meanwhile `collect.py --local-feed` gives every
  player their own personal feed, and comps fall back to curated families
  computed from the live card pool — so nothing shows a blank panel.

- 🔨 **Combat win % (a Bob's Buddy equivalent)** — shipped as BETA and labelled
  BETA on screen. Both warbands come out of Power.log before the fight
  animates, and a Monte Carlo sim over the vanilla rules, derived deathrattle
  summons and per-card scripts for the highest-impact cards calls the winning
  side ~82% of the time across 251 real logged fights (MAE 17pp, Brier 0.101).
  Because plenty of cards are still unscripted, the odds are deliberately
  widened when the board holds one, so a raw 0% or 100% is never printed. No
  odds are shown at all unless both boards were fully recovered. What is still
  missing is the long tail of per-card triggers, and that is the honest catch:
  a simulator is an
  encyclopedia of card interactions that needs re-verifying every patch,
  forever. `sim/validate.py` names the exact cards to script next. If you want
  the mature version, run HDT's free Bob's Buddy alongside — both tools read
  the same log and coexist happily.
- 🔨 **Duos** — `--duo` reads a `heroes_duo` source if you configure one;
  duo comp/trinket/card data doesn't meaningfully exist anywhere upstream.
  Blocked on data, not code.
- 🔨 **Opponent last-seen board on hover** — the log provably never contains
  opponent boards. Game memory exposes each leaderboard player (hero, health,
  tech level, board tribe), but the actual minion list only populates after
  you mouse over them in-game — so "last-known board" is buildable, exact
  live boards are not. Plan: extend `native/msync` to emit leaderboard players,
  overlay shows the last-seen comp on hover.

## Open

- ⬜ **Per-hero strategy tips on hover** — the most-requested feature in the
  r/BobsTavern thread. HSReplay's tips are paid, hand-written content, so they
  can't be reused; this needs our own or community-written blurbs (with voting,
  ideally) — a content pipeline, not a data feed.
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

## Not possible today (and why)

- ❌ **Dark Gift ratings** — nobody publishes placement data for gifts.
- ❌ **Quest stats** — quests are dead this patch; no source has rows for them.
- ❌ **Provably excluded tribes from the log alone** — seeing a minion proves
  its tribe is in; an unseen tribe is only ever "not seen yet". Exactness
  needs the memory reader.
- ❌ **Tablet/iPad overlay** — iOS can't host an overlay over another app.
