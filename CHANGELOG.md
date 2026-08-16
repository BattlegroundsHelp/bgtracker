# Changelog

## Unreleased

### Added

- **The shop has stars again, and they say which kind they are.** A minion
  needs about thirty games in the pool before its rating means anything, and
  the pool is young, so most rows showed nothing at all. There is now a
  starting opinion of each minion frozen from the pool itself
  (`data/minion_ratings.json`, written by `tools/make_minion_priors.py`):
  every card's record was pulled toward the average of its own tavern tier by
  how little evidence stood behind it, so a card with one game says nothing
  and a card with ten says something. The windows blend that with the live
  table by sample size, so each game played slides a card off the guess and
  onto its own record with nothing to switch on. A solid colour-graded star
  is a measurement, a hollow muted one is the starting guess, and neither is
  ever drawn as the other. It is our own pool either way - no third-party
  stats, same as everything else here.
- **The other players' tavern tier is right.** The game writes two tags whose
  names nearly match: `TECH_LEVEL` is the tier printed on a card and
  `PLAYER_TECH_LEVEL` is the tavern a player is standing in. The memory
  reader took the first one off each hero, which is why the whole lobby read
  the same number. It comes from the log now, per hero.
- **The minion browser opens a row with the card itself** beside the text -
  the finished card art where the CDN has it, the square art crop where it
  does not - and its tribe filter wears the tribe emblems.
- **Every counter is its own micro window: an icon and its number, nothing
  else.** Gold, gold banked for next turn, tavern tier, the upgrade price,
  triples, free rerolls, the trinket timer and the turn each get a tiny
  frame you drag where you want it, sized to its own content, which is the
  shape they were always meant to have. Hovering one names it. Run
  `tools/extract_game_assets.py` and five of them wear the game's own art -
  the gold coin, the tavern shield, the upgrade arrow, the tier star, the
  trinket medallion; without it they wear the designed set. Free rerolls
  and the turn always wear a designed glyph, because the game ships no icon
  for either. Each window hides itself when it has nothing true to say (no
  triples yet, nothing banked) instead of showing a zero. The old one-row
  strip is still there for a small screen: switch every micro off and it
  comes back, reading the same numbers. The buff pills got tighter too.

### Fixed

- **`fetch-art` was only asking for minions the stats feed had measured**, so
  the art for anything nobody had played yet was never even requested. It
  asks for the whole browsable pool now. Card renders download in a slower
  pass, because the CDN refuses a wide burst of them.

## v0.3.7-alpha (15 August 2026)

### Fixed

- **The session window drew hero names on top of their portraits.** Only for
  people who had run `fetch-art`, which is most of the reason to run it. The
  frame around each little portrait was called but never imported, so it
  raised, and a blanket `except Exception` around the whole art block
  swallowed it - taking the "move past the portrait" step down with it. The
  import is there, that catch is now narrowed to the Tk failure it was
  written for, and a coding error goes back to being a traceback instead of
  a silently overlapping row. Shipped in v0.3.6-alpha; this is the only
  change on top of it.

## v0.3.6-alpha (15 August 2026)

### Added

- **The extracted game icons the HUD was still sitting on are worn now.**
  The minion browser's tier filter is the game's own seven tavern-tier
  shields - the tab strip the reference overlay fronts its browser with -
  lit when selected, faded when not, at the 28px where the star count
  actually reads (at row size the shields are mush, which is why minion
  rows keep the number on the shield instead - measured, not guessed).
  The other-players list crowns the current leader with the game's own
  crown, the way the in-game scoreboard does. Both fall back to the old
  drawing on a machine that has not run the extractor.
- **A LEVELING window: the ideal curve for your hero, live.** A little
  draggable window that opens with the first shop: the tier-per-turn
  milestones for your hero's bucket (economy, 1-gold power, 2-gold power,
  tempo, tank, dark-gift heroes - everyone else gets the standard line),
  the next milestone lit, one honest verdict (on curve / behind / ahead)
  from your actual tier and turn, and the bucket's own advice underneath.
  The curves are curated written strategy in `data/curves.json` - dated,
  per season, researched from public guides the way the hero tips were,
  never scraped stats - and a user can edit their copy beside the exe.
  The hero is read from its own entity entering play at the draft's end.
- **The overlay survives a flaky Tk start.** Creating the very first window
  can transiently fail to read Tcl's own startup file on a busy Windows
  machine (measured at roughly one launch in four during test batteries) -
  it now retries before giving up, so a real launch stops rolling that die.
- **The HUD has a written design contract.** docs/HUD_GUIDELINES.md: the
  reference-copying rule, the measured flat doctrine, palette and
  typography law, window anatomy, the four drawing recipes, the asset
  ladder, and the checks to run before shipping a look change.

### Fixed

- **The game's own icons were being drawn as opaque squares.** The
  atlas they come out of carries no transparency at all: the game packs
  each shape's alpha as a separate black-on-white silhouette beside the
  colour art, so cropping the colour alone baked a grey backdrop and a
  white edge into every tavern-tier shield the rows wear. The extractor
  now composes that silhouette back in as the alpha (and keys the star
  off its own backdrop), so re-running it gives the real shapes. The
  placement medals were always fine - that atlas has true alpha.
- **A 22-screenshot polish review swept all thirteen windows** and its
  findings shipped: five-star rows no longer run under the name (tavern
  and discover); the BUFFS window has its title bar, a caption that fits,
  and room for three pill rows; measured text fits replace every blind
  character cut (comps, discover, the buff caption); the hero-pick tip
  sits inside its plate instead of striking through the gold outline; the
  opened browser row wears ONE gold outline; over-art labels carry halos
  everywhere; comps core lists, discover options and opponents' boards
  draw as deck-list tiles like every other minion row; session medals
  centre on their digits and hero crops get their frame; margins align on
  the 14px rule across windows; and every colour used against its meaning
  went back to it (a tier is not a link, a caveat is not clickable, a
  wide minion is not "good", a plain count is not a warning).

## v0.3.5-alpha (14 August 2026)

### Changed

- **The counters are separate pills you can move on their own.** Copied off
  the reference overlay's pictures: each standing tavern effect (a Waveling
  stamp under the name the game shows, a tribe-wide shop buff, Blood Gems)
  is a pill - the source's round card art beside "+X / +Y" - clustered in
  their own little BUFFS window that drags anywhere and remembers its spot,
  independent of the counters strip. The strip keeps the resources: gold,
  tier, upgrade, triples, rolls, trinket, as labelled columns.
- **The hero pick reads like the reference's.** Each offered hero wears
  labelled stat cells directly above its card - AVG over the placement,
  PICK over the pick rate - in flat dark boxes; the best offer's cells are
  outlined in the one gold accent instead of a word saying "best". Trinket
  offers get the same cells.
- **The minion browser groups by type.** Tribe section headers with the
  tiers ordered inside each - the reference's resting view - as the default
  sort, with tier, name and rating still one tap away.
- **The look copies the shipped trackers now, because that was the brief.**
  Minion rows are the game's own deck-list tiles - the same 256x59 art
  slices HSReplay and Firestone draw, full-bleed under the row with a dark
  gradient carrying the name (the tiles were already on disk from
  fetch-art). Panels and headers are flat: one dark face, one hairline, no
  rims, no bevels - measured off how Firestone and HSReplay actually
  present (flat translucent rows, zero radius, zero borders). The one
  accent left is the thin gold outline on the row being pointed at.

### Added

- **The whole art universe, three ways.** `fetch-art --everything` pulls
  tiles and crops for every Battlegrounds card id there is - heroes, hero
  powers, buddies, spells, trinkets - so offer rows, the session's hero
  list and the buff pills wear real portraits; it also fetches the
  deck-list gem that now sits on every minion row carrying the tier.
  `tools/extract_game_assets.py` (with UnityPy installed) goes further and
  pulls the game's own tavern-tier shield, tier star, placement medals and
  first-place crown out of YOUR Hearthstone install - rows wear the real
  shield, session top-three finishes wear the real medals, and none of it
  ever enters the repository. The one thing no source publishes - tribe
  emblems - ships as twelve original designed icons in the session
  widget's tribe row and as the pills' fallback.
- **The session widget reads like the reference's.** START and CURRENT MMR
  as labelled columns with the coloured session delta, the games list under
  them, the tribe emblem row at the bottom.
- **A generated tavern skin, opt-in.** Wood, brass and parchment art
  (`data/skin/`) for every panel, header and plate, behind a settings-panel
  switch ("Tavern skin") - off by default, applied live, and the exe wears
  the tavern-shield icon either way. A build without the skin folder or
  without Pillow paints the flat chrome; nothing fails closed. All labels,
  numbers and data colours are untouched in both looks - paint changes,
  meaning does not.

### Fixed

- **The log reader survives what used to kill it silently.** Twice over: a
  card the daily pool cache does not know yet (every patch day) crashed the
  reader thread and froze every window on its last state while the overlay
  still looked alive - guarded; and the log-follow loop itself could die on
  a rotation race when the client prunes old log folders at launch - now it
  reports "reconnecting" in the status line and re-attaches.
- **A day-long adversarial review swept everything above** and its fixes
  shipped with it: the BUFFS window no longer goes dead or stale when the
  COUNTERS window is switched off; its pill icons scale with the UI; five
  or more live buffs no longer clip; hero-pick cells cannot overlap
  neighbouring offers at high badge scales; an off-by-one that could strand
  an orphan tribe header at the bottom of the minion browser; the
  hero-power panel's no-stats footer no longer overruns its band; image
  source caches are bounded; and test outcomes no longer depend on the
  machine's live settings file.
- **The tavern-buff counters track the numbers the game actually shows now.**
  Caught live: the game's tooltip said the standing elemental buff was
  +59/+54 while the strip said "elem +3/+4". The strip was faithfully
  mirroring a pair of player tags whose meaning the game changed under it -
  the real totals moved to hidden accumulator enchantments. The strip now
  reads those accumulators (verified against a full replayed game: every
  value matches the log's own shop-phase truth), labels a tribe-wide buff by
  its tribe and a stamping buff by the name the game shows ("Eastern Winds
  +103/+101"), and only falls back to the legacy tags for old logs. Found in
  the same sweep: a battletag containing a space would have made every
  counter unreadable (fixed), the player tags are now also read from the
  game's own mirror enchantment as a second road, and the "extra gold next
  turn" tag simply no longer exists in current logs - it is kept for old
  ones, and finding its replacement needs a game that actually banks gold.
- **Text sits on quiet wood again.** The generated art broke the brief's own
  readability rule exactly where text lives: the highlighted row plate hit
  brightness 118 where the contract says 38. The skin bake now flattens the
  interior of every text-bearing surface and leaves the edges - the gold
  rim, the plate lip, the header rule - as loud as the art drew them.
- **The stats server is whole for the first time.** The deploy script never
  shipped the image build's context files, so every server build since the
  tips service was written had failed on the box - silently, because docker
  kept running the old images. Fixed: the tips voting server is deployed
  and routed at last (the 121 shipped hero tips are its seed ballot), and
  the hero-powers feed publishes - which retires the "heropowers feed
  unreachable" warning every overlay start printed. That feed stays empty
  until enough shared games carry hero-power picks; that part is data, not
  code.

## v0.3.4-alpha (13 August 2026)

### Fixed

- **Hearthstone installs anywhere now, not just the default path.** The first
  outside contribution (issue #1, thanks Levtos) and the first beta tester's
  lost evening were the same bug from two sides: an install on another drive
  left the overlay saying "waiting for game" forever, watching an empty folder
  it never named. Three answers, most deliberate first: `hs_logs` in
  `settings.json` (the install folder or its Logs folder, environment
  variables expand), then the registry's InstallLocation, so a moved install
  is found with zero configuration, then the default exactly as before. The
  status line and `--diag` now name the folder being watched, because
  "waiting for game" over the wrong path looked identical to a broken overlay.
- **The update manifest is signed now, and the reason it is not simply served
  over HTTPS is worth writing down.** Installing already refused a non-https
  download and checked the SHA-256 before unpacking, but the hash comes FROM
  the manifest, so over plain http anyone on the path could serve their own
  manifest naming their own https zip and its own matching hash, and every
  check downstream would have passed. TLS was tried first: the box is a bare IP
  that no certificate authority will certify, so it was given a real hostname
  through wildcard DNS and Caddy fetched a Let's Encrypt certificate for it.
  Modern curl accepted the result. Python refused it, and so did
  `letsencrypt.org` from the same interpreter, because Let's Encrypt now issues
  under roots that older trust stores do not carry. Shipping that would have
  silently ended update checks for exactly the people least likely to have a
  fresh trust store, while looking perfect in a browser. So the manifest
  carries an RSA signature instead, verified with about thirty lines of modular
  arithmetic and no new dependency. A manifest that is unsigned, altered, or
  signed by anything else is refused before a single field is believed. The
  server still answers https for anyone who wants it.
- The stats and upload addresses stay on plain http on purpose: the same
  trust stores that refused the manifest's certificate would have refused
  these too, and both must keep working on a machine that has never updated
  its roots. The manifest is the channel that decides what code runs, and it
  is the one that is signed.
- Every alpha release is now flagged as a prerelease on GitHub. They were
  marked as full releases, which is what an automated tool reads to decide
  what "latest" means.

## v0.3.3-alpha (13 August 2026)

### Added

- **`reconnect.exe`, a one-click disconnect and reconnect.** Reconnecting is
  the standard fix for a hung fight, a frozen shop or animations that have
  fallen behind, and doing it by hand costs a full client relaunch. This closes
  the TCP socket Windows owns for the Hearthstone process, so the client shows
  its own reconnect and rejoins the game in progress. It touches nothing inside
  the game: no memory read, no file written. It is the same act as Sysinternals
  TCPView's Close Connection, and combat resolves on Blizzard's servers, so
  reconnecting cannot change a fight you are in.
  Two limits, both deliberate and both stated rather than hidden. It needs an
  Administrator shell, which is exactly why it is a SEPARATE program instead of
  a button in the overlay: a free unsigned tool that wants Administrator to
  start at all is a thing users are right to refuse, and this way the prompt
  appears only when somebody runs it on purpose. And the Windows call is IPv4
  only, so an IPv6 connection is reported and skipped rather than silently
  counted as dropped; `reconnect.exe --restart` is the fallback that works
  either way.

## v0.3.2-alpha (13 August 2026)

### Added

- **A rating computed from the card was built, measured, and cut.** A new
  install has measured almost nothing, so the shop is a row of blank stars
  exactly when someone is deciding whether to keep the tool. The obvious fix is
  to rate the card from the card: stat line against its own tavern tier,
  keywords, whether an archetype is built around it. That was built and wired
  in, drawn as a hollow star so an opinion could never pass for a measurement.
  Then it was measured against the mode and it ranks BODIES: Brann Bronzebeard,
  whose whole text is "your Battlecries trigger twice", came out at one star;
  Titus Rivendare at one; a vanilla 10/11 at five; the score tracked raw stats
  at +0.67 to +0.90 in every tier. That is not a weighting to tune. What a card
  is worth here lives in the board around it, and the board is not printed on
  the card. A hollow star still asserts a rank, and an honestly labelled wrong
  rank is still wrong, so it was cut rather than shipped. An unmeasured minion
  shows no star, and the minion browser shows what the card does prove instead:
  how its body compares with its own tier average, and which comps are built
  around it. The measurement is kept in `grades.py` so nobody repeats it.

- **Hero-power stats, which nobody else publishes at any price.** Some heroes
  make you choose a power, and no stats site sells numbers for that choice, so
  the pool computes its own. The collector mines which powers you were offered
  and which you took, the aggregator builds a `heropowers` table exactly the way
  it builds the hero table (the offer is the denominator, the pick is the
  numerator, the placement is the game's own result), and the client can read
  it. The PICK YOUR HERO POWER panel reads that table and only that table: never
  the owning hero's average, never the card table. Only some heroes offer
  the choice at all, so this is a small table by nature and it will need a much
  bigger pool than today's before a row clears the 30 game floor.
- **Comps are classified now.** Every shared final board goes through the
  client's own rule: a board belongs to the tribe it is mostly made of, and only
  when that family's engine piece is standing on it. A board that matches
  nothing is counted under "none" rather than forced into the nearest bucket,
  because piling leftovers into the closest archetype drags every average toward
  the middle and makes the whole table say nothing. An archetype is only
  published once 30 games have been classified into it, so **on today's pool the
  comps file still carries no rows at all** - it carries the counts instead, and
  the client goes on showing the curated families. "We classified this many
  boards and nothing has cleared the floor" is a fact; a table of four-game
  averages is not.
- **Move the badges printed on the cards.** The strips are click-through so
  every click reaches the game, which is exactly what made them impossible to
  drag. So there is a mode: the `⇕ badges` chip in the bgtracker window's
  header drops click-through on every strip for as long as it is on, the strips
  show a marker per slot and no numbers at all while you position them (a
  placeholder number is still a made-up number), and `⇕ done` puts click-through
  back. The offset is saved per kind of strip as a fraction of the game window,
  so it survives a resolution change, and it is capped so a fumbled drag cannot
  fling a strip off the game and out of reach. The chip lives in that window
  because it is the only surface that is always up and cannot be switched off,
  and because no click can ever land on a strip itself.
- **Stars on the discover and Dark Gift cards themselves.** PICK ONE and PICK
  YOUR HERO POWER now carry their own badge strip. The band had to be measured
  rather than guessed: on the Choose One frame the cards run y 302 to 617 with
  the tribe and stat banners at 630 to 670, so the first value put the stars on
  top of the tribe banner. They sit across the top of the card art instead,
  clear of the tier gem and of every line the card prints.
- **What a card pays off, from the card's own text.** "Beasts 4" on a shop row
  means this card names Beasts and you are holding four. It reads the card
  database and nothing else, so it works with no stats source, no community feed
  and no memory reader, and it is this patch's data by definition. Three things
  count and no more: the text naming a tribe, Magnetic (which attaches to a Mech
  without saying the word), and Blood Gems (a Quilboar mechanic the text spells
  differently). "Your minions" and Spellcraft are ignored, because a tag that
  fires on nearly every card says nothing, and simply belonging to a tribe is
  only mentioned once you hold two of them. The tavern shows the short form
  where a row has no comp to name; PICK ONE gives every option its own line. The
  count needs the memory reader - without it the payoff is still named and no
  number is printed, because "how many Beasts do you hold" has no answer in
  Power.log.
- **When a minion pays off, not just whether.** Opening a row in the minion
  browser splits the buy-it-versus-skip-it difference across four stretches of
  the game, where the feed carries a per-turn breakdown. Splitting one card's
  games across fourteen turns is how a healthy sample becomes fourteen small
  ones, so a stretch under the sample floor prints the word `thin` with its game
  count and never a number, a stretch nobody played it in is a dash, and a feed
  with no breakdown says so in one line instead of drawing an empty grid. Needs
  a feed carrying turn data behind it; the community pool is nowhere near that
  yet.
- **All 121 heroes now have a tip at the draft**, up from 111. The last ten were
  the awkward ones, whose printed power names a reward the card itself never
  spells out (a Quest, a Timewarp, a Darkmoon Prize). Their lines say what the
  power costs, when it pays out and what it asks of you, and stop where the card
  stops rather than inventing the reward.
- **Voting on the tips, for people who will never open a pull request.**
  `server/tips.py` takes submissions and votes and publishes a community tips
  feed the client reads like any other source. A line only reaches that feed
  once distinct voters, its score and a margin over the shipped line have all
  cleared a floor, so a handful of manufactured voters changes nothing anybody
  sees. A voted line is marked `▲` in the draft and named in the header, because
  a stranger's wording and a reviewed one are not the same claim. There is
  deliberately no vote button in the overlay: a hero pick is a sixty second
  decision, the panel's band is full at four heroes, and a one-click vote from
  an anonymous overlay is a ballot box with no lock. Honest limit: nothing here
  knows who anyone is, so somebody rotating client ids across many addresses can
  still manufacture voters. The floors are the lock, not the ballot box. With no
  feed, an unreachable feed or a corrupt one you get the tips that ship.

### Changed

- **The overlay is warm dark now instead of blue-grey.** Battlegrounds is
  stained wood, stone, aged parchment and lamplight, and a cool charcoal slab
  beside it always read as a different program's window sitting on top of the
  game. Panels sit in a three-tone rim, rows sit on raised plates, and card art
  gets a frame. Nothing about what a colour **means** changed: the placement
  colours, the star colours and the tribe colours are untouched, because their
  hue is the number.

### Fixed

- **Lobby tribes were being overcounted, and the pool was being fed the wrong
  ones.** A `CARDRACE` tag says what a CARD is, not what the LOBBY holds, and
  the collector counted every one of them. So a card generated into your hand
  (a Get, a discover, a Dark Gift reward) or a token summoned mid fight (a
  Skeleton, a Beetle, a Golem) added a tribe that lobby never dealt. Measured
  over 60 real games: six claimed 9 tribes, one of them with four impossible
  ones. Now a tribe is counted only from a buyable minion standing in play,
  keyed to Bob's shop wherever the log names him. Six bad games became one, and
  that one is honest residual: its doubtful tribes have 1, 2, 4 and 4 sightings
  against 42 to 71 for the real ones, and the log offers nothing that tells a
  single shop sighting from a single card played out of hand. It still never
  claims a tribe is OUT, only that a seen tribe is in.
- Records now carry which mining rules produced them, so a fix to an
  extraction rule re-mines the games it affected instead of leaving them
  looking complete forever. That repaired 44 records here, and the corrected
  ones replace their old rows in the shared pool on the next share.
- `server/deploy/deploy.sh` removes the synthetic game it posts to prove the
  write path works. It was leaving one fake row in the live pool per deploy.

### Changed

- **Two monitors with different scaling put the badges in the wrong place.**
  The overlay asked Windows only for system DPI awareness, and a system aware
  process is handed virtualized coordinates for any monitor whose scaling
  differs from the primary one. It reads the game's rectangle from exactly
  that call, so on the common setup of a scaled 4K panel beside an unscaled
  1080p one the badges landed offset or the wrong size, and it looked like the
  tool was broken rather than misinformed. It now asks for per monitor
  awareness, with fallbacks for older Windows. Two monitors were never the
  problem on their own: the overlay follows the game in absolute desktop
  coordinates, and mixed scaling was the problem.
- The new display mode check measured the game against the primary monitor
  rather than the monitor the game is on, so a second screen of a different
  size would have been described wrongly.
- `--diag` now prints every display with its position and size, the DPI
  awareness actually granted, and the game's window mode, because "the badges
  sit off the cards" and "nothing appears in fullscreen" are the two questions
  that cannot be answered without them.

## v0.3.1-alpha (12 August 2026)

- **Community sharing is now ON BY DEFAULT, and this is a change of an
  earlier promise.** Until now every copy surface said uploading was opt in
  and off by default. The author changed that default on 12 August 2026,
  because a pool nobody feeds shows everybody thin numbers forever. Plainly:
  unless you switch it off, the overlay now sends one anonymised record per
  finished game to the community feed - your whole log history once, shortly
  after start, then each game as it ends, and a last attempt when you quit.
  The record holds exactly what it always held (the settings panel lists
  every field: scrambled game id, date, hero, placement, Duos or not, lobby
  tribes, the offers, the picks, an opaque per-install id, the client
  version - no name, no battletag, no log files). **The off switch:** untick
  "Share my finished games" in the settings panel's DATA section (saved), or
  start with `--no-upload` (that run only, writes nothing). The aggregates
  stay free for everyone and are never sold or paywalled, whether you share
  or not. `collect.exe` remains as the by-hand path.
- **The community feed is now the default stats source.** With no
  `sources.json`, the overlay reads the community tables (the same URLs
  `sources.example.json` documents), so a fresh install shows numbers and
  gives games back with zero setup - both halves of the same default. Writing
  your own `sources.json` replaces it entirely, exactly as before; nothing is
  written to disk on your behalf.
- New module `pool.py` does the sending: incremental (a ledger in
  `data/uploaded.json` remembers what was sent, so nothing uploads twice),
  throttled to one request every 2 seconds (a quarter of the server's own
  rate limit), quiet on failure (a dead server means "try again at the next
  game", never an error in your face), and always off the UI thread -
  quitting waits at most about 2 seconds for a send in flight.

## v0.3.0-alpha (12 August 2026)

Nearly all of it was asked for in the r/BobsTavern thread.

### Added

- **A settings panel, and it opens when the tool starts.** A normal window you
  can move, scroll and close, not one of the click-through overlay surfaces.
  Four sections. DISPLAY: one UI scale for everything, automatic from the game
  window or a slider you drag, applied while you drag it rather than on the next
  start, plus a nudge for the badges printed on the cards. That is the fix for a
  4K screen, where the whole overlay used to draw at half the size it should.
  DATA: the sharing opt-in, off by default, with one line saying exactly what
  leaves the machine and that the pooled numbers stay free; which feed the
  numbers come from; the MMR bracket, the period, and Duos. WHAT TO SHOW: one
  switch per overlay window, generated from the window registry so a window
  added later appears on its own. A window switched off is not built at all: no
  panel, no badges, nothing routed to it, and switching it back on is live.
  UPDATES: the version, when it was last checked, check now, and what changed
  plus install when there is something newer. Rows that cannot take effect until
  the next start say so. Choices live in `settings.json` beside `sources.json`;
  a flag on the command line beats the file for that run and is never written
  back to it. `--no-panel` starts without it, and the gear in the bgtracker
  window's header reopens it.
- **OTHER PLAYERS window.** Every other player in place order with hero, tavern
  tier and health. For anyone you have fought, the board they were last seen
  holding, stamped with the round and how long ago. Click a player to open it.
  A player you have not fought shows no board, not a guess. Needs the optional
  memory reader; the log does not state opponent boards during recruit.
- **Hero tips at the draft.** One line per hero saying when it is the pick.
  111 of 121 heroes. In `data/hero_tips.json`, fixable by pull request. The ten
  missing are heroes whose power names a reward the card never describes.
- **Duos as its own dataset.** Marked solo or Duos from the log
  (`BACON_DUO_TEAM_ID`), agreeing with the game's own mode line on 33 of 33
  games. Separate feed for heroes, trinkets, cards and comps. `--duo` reads it.
  No pooling and no fallback to solo: Duos places 1st to 4th, solo 1st to 8th.
- **MMR brackets in the feed.** The aggregator publishes each bracket
  (`--mmr 100|50|25|10|1`) as its own files, stamped with the bracket and the
  rating cut used. A bracket is published only once it holds 30 games; until
  then the client reads the all players file and says so instead of labelling
  the whole pool "top 1%". Old file names still written, so existing
  `sources.json` files keep working.
- **It can tell you there is a new version.** On start it fetches a 200 byte
  manifest from the stats server, on its own thread, and prints one line if
  there is a newer build. It never installs anything on its own: the build is
  unsigned, and swapping out a folder somebody extracted by hand without asking
  is not on. Downloading and installing happen when you ask, and the download is
  refused unless its SHA-256 and its size both match what was published. Your
  collected games, card art, window positions and `sources.json` are carried
  across, and the previous install is kept until the new one has run once.
  `--no-update-check` turns the check off; `BGTRACKER_NO_UPDATE_CHECK=1` and
  `{"check_on_start": false}` in `data/update.json` do it permanently. Details
  in [docs/USAGE.md](docs/USAGE.md) section 2c.
- **The version now exists as a number the program knows.** It was only ever a
  CHANGELOG heading and a git tag before. `--diag` prints it, uploads carry it
  so the server can tell which builds are in the wild, and the build writes it
  into `version.txt` inside itself so a release manifest cannot describe a
  different build than the one it points at.
- **Card effects catalogue.** `python tools/catalog.py` generates
  [`docs/CARD_EFFECTS.md`](docs/CARD_EFFECTS.md) from the live card database,
  so it is always this patch's pool. Of 274 pool minions, 39 act during combat,
  141 have already resolved before both boards are read, 94 do nothing in a
  fight. The 141 are listed as do-not-script. Work queue: 18 cards.

### Changed

- **Combat odds: about 86% winner accuracy over 339 logged fights** (MAE 13pp,
  Brier 0.072, the release's final measure). Read the jump from 82.5% carefully:
  that number came from 251 fights, and the same unchanged code scores 85.7% on
  the larger sample. The jump is the sample, not the code.
- Six more in-combat effects modelled: Fish of N'Zoth, Plaguerunner, Forest
  Rover's Beetle counter, Reborn copies inheriting side-wide grants, goldens
  read off the golden card instead of guessed by doubling, and manual scripts
  merging with derived ones per hook instead of replacing them. **Measured
  worth: one extra correct fight out of 343.** Accuracy 85.7% to 86.0%, Brier
  0.0784 to 0.0771. A null result on accuracy, a small calibration gain.
- Nine more in-combat scripts, each read off the card's own text: Kangor's
  Apprentice, Sewer Lord, Leeroy the Reckless, Motley Phalanx, Scarlet Skull,
  Eternal Summoner (a board-visible floor, like Forest Rover), Turquoise
  Skitterer, golden Wildfire Elemental splashing both neighbours, golden
  Deflect-o-Bot gaining +4. Pre-BG25 goldens now resolve under their real
  `TB_BaconUps_*` ids instead of only `_G`, and cleave is derived from both
  printed wordings. The sim can now also say how hard a fight hits: damage
  bands that include the hero's tavern tier, plus the chance this fight kills
  you (or them), widened the same way as the odds so they never print 0% or
  100%. Measured on the same 339-fight harness, identical seeds: Brier 0.0752
  to 0.0720, MAE 13.8pp to 13.2pp, accuracy 86.1% to 85.8% (one net fight,
  two gained and three lost). Same lesson as last time: scripts buy
  calibration, not accuracy.
- **Dark Gifts are complete.** All 40 accounted for: 24 grant only stats or
  keywords (already on the minion when the board is read, so modelling them
  again would make the sim worse), 9 change your cards not the fight, 6 fire
  during combat and are modelled, 1 can no longer be offered. Gap: zero.

### Fixed

- The Dark Gift miner looked for `tag=ATTACHED` and found nothing across 1.3 GB
  of logs. The signal is `DARK_GIFT_ENTITY`, which `sim/boards.py` was already
  reading correctly.
- The card effects catalogue counted only hand-written scripts, so five cards
  whose printed text already derives a working script (token summons, cleave)
  sat in the work queue as if they were missing. With those counted and this
  batch's new scripts, the queue stands at 18 cards, down from 33.
- The stats cache key ignored which source a table came from, so pointing
  `sources.json` at a different server kept serving the old server's numbers for
  up to an hour.
- `data/` was ignored wholesale, so the hero tips file could never have reached
  the repository.
- The upload endpoint rejected every Duos game: its hero pattern had no digits
  to match in `BGDUO_HERO_223`.

### Known limits

- Of 48 wrong odds calls, 13 were fights that really tied. Boards where every
  card is modelled are called right 91.3% of the time; boards with at least one
  unmodelled card, 82.9%. Rounds 5 to 8 are the worst stretch at 80.5%.
- The long tail of unmodelled cards is the error. Per-card scripting has a low
  ceiling because the remaining cards are individually rare.

## v0.2.0-alpha (11 August 2026)

No Python needed, one window per thing, and the shared stats server is live.

### Added

- **Standalone Windows build.** Download the zip from Releases, unzip, run
  `bgtracker.exe`. No Python, no pip, no install. Four tools inside: the
  overlay, the console version, the collector, the art fetcher.
- **COUNTERS window.** Turn, gold now and max, your tier and what the next one
  costs, gold banked for next turn, buffs, your board's tribes, triples, turns
  until the next trinket. Anything the game has not stated shows a dash.
- **MINIONS window.** The whole current pool, filtered by tier, tribe or
  mechanic. Needs no stats source.
- **SESSION window.** Rating now versus when you sat down, and every game that
  finished while the overlay was running.
- **Shared stats server.** Uploading is opt in and off by default, records are
  anonymised (hero, placement, lobby tribes, board), aggregates are free for
  everyone and never sold or paywalled. `collect.py --upload <url>` shares;
  `collect.py --local-feed` keeps everything local.
- The collector now mines which heroes and trinkets you were **offered**, not
  just what you took, which is what makes pick rate computable.

### Changed

- **One window per thing.** The single morphing panel became ten independent
  windows, each with its own trigger, dismissal and remembered position. Every
  bug of that era came from one state machine trying to be several surfaces.
  TAVERN used to go stale; COMBAT used to lag a fight behind and linger over
  the shop.
- **Combat odds: 82.5% winner accuracy over 251 logged fights**, up from 76.5%.
  Brier 0.1006, down from 0.1409.
- **The odds no longer print 0% or 100%.** There are card effects the sim does
  not model, so claiming certainty was wrong.
- Comps no longer need a data source: with none configured the tool shows
  curated families whose core minions are computed from the live card pool.
- `bgtracker.bat` says plainly when Python or tkinter is missing instead of
  flashing a window and vanishing.

### Fixed

- The collector attributed games to the wrong player in lobbies full of real
  accounts, so most placements were wrong. It now keys off the hero draft, the
  one signal that proves which player is you.
- Board count was read from the combat copy mid-fight, showing dead minions as
  missing. The board is now read only during recruit.

### Known limits

- Windows only.
- Windows warns on first launch because the build is unsigned.
- The shared feed is new, so most rows are flagged thin. Thin means no signal,
  not weak signal.
- Uploads are unauthenticated by design (an open-source client cannot keep a
  secret), so the endpoint is rate limited and the data is validated.
- The memory reader is an optional separate build, never bundled. It is the one
  part that touches the letter of Blizzard's EULA.
