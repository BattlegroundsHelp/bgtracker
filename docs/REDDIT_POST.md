# Reddit post pack (r/BobsTavern)

Copy and paste source. Everything below the headings is the copy itself.

The image slots below now name real files. All of them live in `docs/img/`, cut from a screen
recording of one full game on 11 August, cropped so no account name, opponent name or wall
clock is anywhere in frame, and stripped of metadata. `docs/img/SHOTLIST.md` records what each one shows and what is still
missing.

Two captions carry a caveat you should keep: the session window in
`counters-session-strip.png` says "no finished games yet this session" because that was the
first game of the sitting, and hero select shows one badge rather than four because only one
of the four heroes had any data in the local feed. Both are honest states, not bugs, but do
not caption them as if they were the full picture.

The whole recording was made with **no stats source configured**, which is why the browser
reads "no stats source" and the trinket window reads "NO TRINKET STATS CONFIGURED". That is
the state the post argues for, so it works in your favour.

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

[IMAGE: docs/img/overlay-full-game.png: turn 8, five windows at once: session top left,
tavern with star ratings, counters, the minions bar, and comps down the right edge]

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

[IMAGE: docs/img/tavern-shop-stars.png: the tavern window listing all six shop minions with
their tier and star rating, the comp-feeding one tagged, and the same six on the board below]

[IMAGE: docs/img/tavern-reroll.gif: the shop rolls and the tavern window rebuilds with it,
roll 32 becomes roll 33]

[IMAGE: docs/img/discover-pick-one.png: a discover dialog with the PICK ONE window naming
all three options while the tavern window is still up beside it]

[IMAGE: docs/img/counters-session-strip.png: counters, tavern and session across the top of
the game, mid run]

[IMAGE: docs/img/minion-browser-open.png: the minion browser open, 274 in the pool filtered
down to 29 Beasts, card art and tier on every row]

**Needs a stats source that you supply**

- Average placement, pick rate, top 4 rate and sample size on heroes, trinkets and
  discovers.
- Star ratings per minion in the shop (each minion rated inside its own tavern tier).
- Measured comp rankings in place of the curated families.

[IMAGE: docs/img/hero-select-picks.png: hero select with the four portraits and the PICK
YOUR HERO window on the left edge. Only one hero carries a score here because the only data
configured was one game of my own from collect.py; the other three read "no data at this
MMR", which is what you get with nothing configured]

[IMAGE: docs/img/trinket-pick.png: the trinket shop, with the PICK YOUR TRINKET window
naming all four and saying plainly that no trinket stats are configured]

[IMAGE: docs/img/trinket-panel-opens.gif: combat closes on its own, the shop comes back,
the tavern window rebuilds, then the trinket window opens with the offer]

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

[IMAGE: docs/img/comps-curated.png: the comps window with no stats source configured, every
row labelled "curated", one row opened to show its core minions, no measured numbers
anywhere]

**Combat odds are BETA, and here is the real number**

Both warbands are readable in the log about a second before the fight animates, so a Monte
Carlo sim runs there and shows win / tie / loss. Measured against 251 real logged fights it
calls the winning side about 82% of the time. It knows the vanilla combat rules, deathrattle
summons derived from card text, and hand written scripts for the cards that were costing the
most accuracy (Rally triggers, deathrattle buffs, Reborn watchers, Titus). Plenty of cards
are still unscripted, so when one is on the board the sim widens its own odds instead of
pretending, and it never prints a 0% or a 100%. It is flagged BETA on screen, and it shows
nothing at all when either board could not be fully recovered from the log.

HDT's Bob's Buddy is the mature option for this and it is free. Both read the same log, so
they coexist with no conflict. Run them side by side and trust Bob's Buddy where the two
disagree.

[IMAGE: docs/img/combat-odds-beta.png: the combat window reading ODDS BETA, W 37% / T 14% /
L 50% over 3,000 simulated fights, with the round 8 fight swinging behind it]

[IMAGE: docs/img/combat-odds-appear.gif: the tavern window closes itself, combat opens, and
the odds line is already up before the first attack plays]

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
  animates and a sim shows win / tie / loss. About 82% winner accuracy over 251 logged
  fights, with the highest impact cards scripted and the rest handled by widening the odds.
  Bob's Buddy is still the mature option and runs alongside it fine.
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

## EDIT 5 (DRAFT, NOT POSTED)

Hold this until v0.3.0 is actually on the Releases page. Duos, MMR brackets, the other
players window and the hero tips are all on `main` but are NOT in the v0.2.0-alpha zip, so
posting this before a build ships would point people at a download that does not contain
the things it announces. One edit, after one release, is also less noisy than two.

It answers six people in the thread by name, which is the point of it.

---

EDIT 5: v0.3.0, AND THE THREAD'S REQUESTS ARE IN

Most of this edit is other people's ideas from this thread. Named, because they earned it.

u/Joshs424 said the text was too small at 4K. There is now a settings panel with a UI scale
you can drag, and the badges over the cards size themselves off the game window, so a 4K
client gets 4K badges instead of 1080p ones sitting in the right place at half size.

u/l337hackzor asked for Duos and for finer MMR filtering than the two bands HSReplay gives
you. Duos is now its own dataset, not a filter: a Duos lobby is four teams finishing 1st to
4th and a solo lobby is eight players finishing 1st to 8th, so pooling them would describe
neither. Nothing falls back to solo numbers. There are five MMR brackets, and a bracket only
appears once it holds enough games. Until then the tool reads the all players file and says
so on screen instead of labelling the whole pool top 1%.

u/Ok-Acanthisitta7190 asked for the last players board, "even if it's only a screenshot". It
is better than a screenshot. There is a window listing every other player with their hero,
tier and health, and for anyone you have fought, the board they were last seen holding with
the round it was seen in and how long ago. A player you have not fought shows no board at
all, not a guess. This one needs the optional memory reader, because the log genuinely never
states another player's board while you are shopping.

u/Deep-Sky-3365 and u/Taverntrainer asked for per hero strategy lines. 111 of the 121 heroes
now carry one at the draft. Every line was written from that hero's own printed hero power
text, not copied from anyone's guide, and the ten without a line are the ones whose power
names a reward the card never describes. They live in a plain file in the repo, so anyone can
fix one with a pull request. The upvote and downvote system for these is still to come.

u/Deathoftheages asked about keeping up with patches. It now checks for updates itself and
tells you when there is one. It never installs anything behind your back.

Also in this build: a settings panel that opens on start, where the data sharing opt in
lives (still off by default, still anonymised, still free forever), along with which windows
you want on screen at all.

ON THE COMBAT ODDS, since people asked how accurate it really is

86% winner accuracy over 343 of my own logged fights. Be careful reading that against the
82.5% in the last edit: most of that jump is the sample growing from 251 fights to 343, not
the code getting better. The same unchanged code scores 85.7% on the bigger sample. Six more
cards got scripted and that bought exactly one extra correct fight out of 343. Saying so
because the honest number is more useful than the flattering one.

Something surprising came out of that work. Dark Gifts sound like they should be the hard
part, and they are not. There are 40 of them. 24 only grant stats or keywords, which are
already sitting on the minion by the time the board is read, so modelling them again would
make the sim worse rather than better. 9 change your cards rather than the fight. 6 fire
during combat and are modelled. 1 cannot be offered any more. The gap is zero.

The pool minions are the same story. Of 274 minions only 39 do anything during a fight at
all. 141 have already finished their work before the boards are read, and 94 do nothing in
combat. So the remaining work is 33 cards, not 274. That list is generated from the live card
database and is in the repo, so it stays right when the patch changes.

Still Windows only. Still free, no ads, no account, no paywall, and your games stay yours.
