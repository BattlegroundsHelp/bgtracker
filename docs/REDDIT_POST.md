# Reddit post pack (r/BobsTavern)

> **STALE, do not repost as is (2026-08-12).** The copy below predates a change
> of terms: sharing games with the community feed is now ON BY DEFAULT with an
> opt-out (the settings panel's DATA box, or `--no-upload` for one run), and
> the community feed is the default stats source. Every "opt in and off by
> default" sentence below was true when posted and is false now. Rewrite those
> paragraphs from README "Where the numbers come from (and where they go)"
> before using any of this again.

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

## THE CONSOLIDATED POST (DRAFT, NOT POSTED)

Posting gates, in order, all three before pasting:
1. The v0.3.0-alpha release is live on the Releases page.
2. The update manifest is live: fetching http://165.227.41.29/update.json returns the new
   version (posted before that, the "tells you when a new version is out" line describes a
   check that silently finds nothing).
3. Eyeball the thread once so the six u/ names are typed exactly as they render there
   (case and hyphens matter).

Paste mechanics: this REPLACES the whole post body. The original paragraphs stay verbatim
at the top (every comment answers them); EDIT 2, 3 and 4 fold into the one section below.
The live body is 6.1K characters and holds no images (screenshots live in comments), so a
full replace loses nothing. On new Reddit, switch to the MARKDOWN editor before pasting,
or edit via old.reddit.com: the rich text editor turns the bullets into literal asterisks.
One more mechanic worth knowing: editing a post does NOT notify the six people named. If
the credits should reach them, that takes a comment; the drafted one is at the end.

---

I'm so upset about paying 5$/month

So I decided to pay my subscription for Claude code 280$ month and build my own

Comps, synergies, tracker etc. almost everything

Planning to publish it for FREE (no ads or weird bs) and open-source in case you'd like to help me out

Now the million dollar question,
What feature is a MUST to have in a hs battleground companion?

Will edit the post with the name/link/github as soon as it's stable and ready

EDIT, current as of v0.3.1 (EDIT 2, 3 and 4 are folded into this one section):

It is out and it keeps growing: https://github.com/BattlegroundsHelp/bgtracker

No account, no paywall, ever. Windows only. No Python needed: grab the zip from Releases, extract, run. Unsigned build, so Windows warns once; the source is public if you want to check first.

On the data question this thread raised: it uses nobody else's data. It builds its own pool from the games of the people who run it: as you play, the overlay shares one anonymised record per game (hero, placement, lobby tribes, what was offered and picked, no names, no battletags) and reads its numbers from that same pool. Sharing is on by default now. That is a change from the last edit and the call is mine: a pool nobody feeds serves nobody. The settings panel lists every single field that leaves and holds the off switch, and everything still works with it off. The aggregates stay free for everyone, never sold, never paywalled.

WHAT IT DOES

* Hero, trinket and discover picks rated on the actual cards (hero power options named), with 5 MMR brackets and time filters. Brackets fill in as the shared pool grows; a thin bracket falls back to all players and says so on screen
* Tavern minions star-rated, comps filtered to your lobby with core pieces vs add-ons and a computed difficulty
* Combat odds with damage and lethal: win/tie/loss, how hard the fight hits, and the chance it kills you or them
* Counters, minion browser, session tracker, and Duos stats kept separate from solo, never pooled
* If you build the optional memory reader (a separate .NET build, not in the zip): exact lobby tribes at hero select, and the board every opponent was last seen holding
* A settings panel on start: UI scale (the 4K fix), what to show, updates

Numbers need a feed: one click in the settings panel picks the community pool, your own games, or any source you configure. With none picked everything still runs, names only.

Straight numbers on the odds, since people asked: it calls the winning side about 86% of the time across 339 of my own logged fights, it never claims 0% or 100%, and Bob's Buddy is still the more mature simulator. They read the same log and run side by side fine.

Most of this build is this thread's requests, so credit where due: u/Joshs424 (the 4K text scaling), u/l337hackzor (Duos and finer MMR brackets), u/Ok-Acanthisitta7190 (opponents' last boards), u/Deep-Sky-3365 and u/Taverntrainer (the per hero tips at the draft), u/Deathoftheages (it now tells you when a new version is out, and never installs anything on its own).

Beta testers still wanted. Tell me which window helped and which one lied, that is the whole QA process.

---

### Credit comment (post this AS A COMMENT so the six actually get notified)

v0.3.0 is up, and most of it is this thread's requests: u/Joshs424 the UI now scales, drag it to fit a 4K screen. u/l337hackzor Duos has its own stats and there are 5 MMR brackets. u/Ok-Acanthisitta7190 opponents' last seen boards are in (needs the optional memory reader). u/Deep-Sky-3365 u/Taverntrainer per hero tips at the draft, 111 of 121 heroes. u/Deathoftheages it tells you when a new build is out and never installs anything on its own. Details in the post, zip on the Releases page.
