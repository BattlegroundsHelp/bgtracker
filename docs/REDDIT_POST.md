# Reddit post pack (r/BobsTavern)

Copy and paste source. Everything below the headings is the copy itself.

Six images are marked in the post with `[IMAGE: ...]` placeholders, in this order: the whole
overlay in a live game, counters plus session, the minion browser, hero select with badges,
the comps window with no stats source, and the combat window with the BETA odds line. Every
shot wants the overlay visible, not the bare game. Delete a placeholder if the shot is not
ready rather than posting the line as text.

## Post

### Title options (pick one)

1. bgtracker: a free open source Battlegrounds overlay, looking for beta testers
2. Free BG overlay, no account and no bundled stats. Looking for people to break it
3. I have been building a Battlegrounds overlay in the open. It is at beta and I want testers

### Body

bgtracker is a free, open source Battlegrounds overlay for Windows. It reads Hearthstone's
own Power.log and draws ten small windows around the game, each one opening when it has
something to say and closing when that moment has passed.

One person builds it, it is a beta, and this post is a call for testers.

[IMAGE: full game screenshot with the overlay running, windows down both edges of the
Hearthstone window]

**Works the moment you run it, no setup and no account**

- COUNTERS: turn, gold now and max, your tavern tier and what the next tier costs right
  now, gold already banked for next turn, elemental and Blood Gem buffs, your board's
  tribe counts, free rerolls, triples, turns until the next trinket. Anything the log has
  not stated is a dash, never a zero.
- COMBAT: which round is fighting, plus the beta odds line (more on that below).
- TAVERN: the shop in front of you, with the minions that feed the comp you are building
  marked.
- The comps window: tribe chips for this lobby, and the comps still open to you. With no
  stats configured it shows curated comp families whose core minions are computed from the
  live card pool, so they are always this patch's minions. Those rows are labelled
  "curated" so nobody mistakes them for measured numbers.
- MINIONS: the whole current pool, filtered by tavern tier, tribe and mechanic, with card
  text and art.
- SESSION: this sitting, every game that finished while it was running, with its placement
  and hero.
- The pick windows (hero, hero power, trinket, discover and Dark Gift) still detect and
  name every option on offer.

[IMAGE: counters window and session window at the edge of the game, mid run]

[IMAGE: minion browser open, filtered to one tavern tier and one tribe, card text and art
visible]

**Needs a stats source that you supply**

- Average placement, pick rate, top 4 rate and sample size on heroes, trinkets and
  discovers.
- Star ratings per minion in the shop (each minion rated inside its own tavern tier).
- Measured comp rankings in place of the curated families.

[IMAGE: hero select with the four portraits, badges drawn above them, the PICK YOUR HERO
window on the left edge]

**Why the numbers are bring your own**

Aggregate placement data belongs to whoever collected it. The big stats sites built that by
running a client and a backend for years, and none of them licence third party
redistribution. A public URL is not a licence. So this ships with no stats data at all and
points at nobody's feed.

Two honest ways to get numbers:

- Point `sources.json` at a source you have the right to use. It takes a URL or a local
  file.
- Grow your own. `python collect.py` mines your own finished games out of your log history,
  and `python collect.py --local-feed` turns them into a personal feed, so the overlay
  shows your own numbers with nobody else involved.

A pooled community dataset is built but not running anywhere yet. Its terms are fixed
before it exists: uploading is opt in and off by default, records are anonymised (hero,
placement, lobby tribes, final board, no names and no battletags), the aggregates are free
for everyone, and the data is never sold and never paywalled.

[IMAGE: comps window with rows labelled "curated", taken with no stats source configured,
so it is clear what you get with zero setup]

**Combat odds are BETA, and here is the real number**

Both warbands are readable in the log about a second before the fight animates, so a Monte
Carlo sim runs there and shows win / tie / loss. Measured against 231 real logged fights it
calls the winning side about 77% of the time. It is over confident at the extremes (the
fights it calls near certain are not that certain), and it only knows the vanilla combat
rules plus deathrattle summons derived from card text, not per card triggers. It is flagged
BETA on screen, and it shows nothing at all when either board could not be fully recovered
from the log.

HDT's Bob's Buddy is the mature option for this and it is free. Both read the same log, so
they coexist with no conflict. Run them side by side and trust Bob's Buddy where the two
disagree.

[IMAGE: combat window showing the ODDS line with the BETA chip and win / tie / loss
percentages, with the fight on screen behind it]

**What it touches, plainly**

Reading Power.log is the default and is exactly what HDT does. Blizzard has publicly said
log reading trackers are fine, nobody has been banned for it, and Blizzard shipped their
own tracker.

There is one optional extra: a memory reader (`native/msync`) that gives exact lobby tribes
at hero select, your board for comp synergy, and your rating for the session window. It is
not bundled, you build it yourself with the .NET SDK, and it is the one part that crosses
the letter of Blizzard's EULA (§1.C.vi, software that reads information stored by the
platform). Leave it unbuilt and everything else still works, tribes just fill in from the
log as minions appear. The facts are in the README so the call is yours with your eyes
open.

**Running it**

Windows, Python 3, no pip installs. Double click `bgtracker.bat`. Keep Hearthstone in
borderless windowed, since nothing can draw over exclusive fullscreen without hooking the
game, which this deliberately does not do.

Repo: https://github.com/BattlegroundsHelp/bgtracker
How to run it, every window and every flag:
https://github.com/BattlegroundsHelp/bgtracker#run-it

**What I want from testers**

- Which window actually helped during a game, and which one you never looked at.
- Which one lied. A number that was wrong, a window that stayed up after the moment passed,
  a rating that made no sense for the card.
- What broke. Which window, what was on screen at the time, and whether you started the
  overlay before or during the game.
- Combat odds in particular: the fights where it said near certain and you lost anyway.

GitHub issues or comments here, both work. It is a beta and it keeps the beta label until
the measurements say otherwise. Free, no ads, MIT licensed, not affiliated with Blizzard.

## Edit for the existing thread

EDIT (11 August): a fair amount has changed since this post.

- The one big panel is gone. The overlay is now ten small windows, one per thing you might
  want to know, each opening and closing on its own trigger and draggable on its own.
- Combat odds shipped as a BETA. Both warbands come out of the log before the fight
  animates and a sim shows win / tie / loss. About 77% winner accuracy over 231 logged
  fights, over confident at the extremes. Bob's Buddy is still the mature option and runs
  alongside it fine.
- Three new windows: counters (gold, next tier price, buffs, board tribes, triples, trinket
  countdown), a minion browser for the whole current pool, and a session tracker for the
  sitting.
- Comps no longer need any data. With no stats source it shows curated comp families whose
  core minions are computed from the current card pool, labelled "curated".
- Still no bundled stats and still no third party feed. Numbers come from a source you
  configure or from your own games via collect.py.
- Beta testers wanted now, new post here: [LINK TO THE NEW POST]. Tell me which window
  helped and which one lied.

## Comment replies

**"Is this bannable?"**

The default build reads the log file only, which is what HDT has done for years and what
Blizzard has publicly said is fine. Nobody has been banned for it, and Blizzard shipped
their own tracker in 2024. The one part that crosses the written line is the optional
memory reader, EULA §1.C.vi covers software that reads information stored by the platform.
It is not bundled, you have to build it yourself, and everything else works without it. I
am not going to tell you it is risk free. I am telling you which half is which so you can
decide.

**"Why are no stats included?"**

Because those numbers are not mine to hand out. Aggregate placement data is collected by
whoever runs the client and the backend, and a public URL is not a licence to redistribute
it. So the tool ships with none and points at nobody's feed. You either configure a source
you have the right to use, or you grow your own with collect.py, which mines your own
finished games (`--local-feed` turns them into your own stats). Everything that is not a
number works with no source at all: curated comps, tribes, counters, minion browser,
session, combat odds. A pooled community dataset is built but not running yet, opt in only,
anonymised, free for everyone.

**"How is this different from HDT or Tier7?"**

HDT is the incumbent, it is free, it is good, and Bob's Buddy is more accurate than my odds
are today. The difference is what sits behind the subscription. Hero and trinket pick stats
shown in the overlay while you are choosing, and comps filtered to your lobby with their key
minions, are Tier7 features. Here they are free, with the catch that you bring the data
yourself. There are also five MMR brackets and four time windows to filter by, and hero
scores tuned to the tribes in your actual lobby if you build the optional memory reader.
Running both at once is fine, they read the same log.

**"Does it work on Mac?"**

No, Windows only right now. The log parsing itself is not Windows specific, but the overlay
draws through Win32 calls to find and follow the Hearthstone window, and the log path is the
Windows install path. A Mac port means a new window layer and a new path lookup. It is open
source and the parsing half would carry over, but I am not writing that port myself in the
near term.
