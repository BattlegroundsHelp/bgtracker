# bgtracker aggregator

The independent stats backend. It turns players' own game results into the exact
JSON feed the client already reads, so bgtracker can show average placement,
pick-rate and card deltas computed from **our own pooled data** - no third-party
stats service, nothing to ask anyone's permission for.

It is deliberately tiny and self-contained: **stdlib Python only, no `pip install`**,
two small scripts, its own SQLite file. It drops onto a VPS you already run as an
isolated tenant that can't touch your other project.

```
   client (overlay / collect.py --upload)
        │  POST /upload   {uid, date, hero, place, tribes, ...}   (anonymised; on by default, opt-out)
        ▼
   ingest.py ──writes──► data/games.db (SQLite)
        ▲                     │
        │ 127.0.0.1:8787      │ read hourly
   reverse proxy         aggregate.py ──writes──► out/*.json[.gz]
        │                                              ▲
        │  GET /heroes-all-time.json  ◄────static──────┘
        ▼
   client (bgtracker.py, via sources.json)
```

Two processes, on purpose: the public endpoint only ever does a small validated
`INSERT`; the heavy grouping runs on a timer, off the request path. Reads are plain
static files, so a thousand clients fetching stats never touch the app or the DB.

## Run it

### Option A - Docker (recommended)

```bash
cd server
# optional shared upload secret:
echo "BGTRACKER_UPLOAD_TOKEN=$(openssl rand -hex 16)" > .env
docker compose up -d --build
curl -s http://127.0.0.1:8787/health          # {"ok":true,"games":0}
```

`ingest` publishes **only to 127.0.0.1:8787** - the host reverse proxy exposes it.
`aggregate` re-runs every hour (`AGG_INTERVAL` seconds) writing `server/out/`.
Both are capped (`mem_limit`/`cpus`) so an upload spike can't starve the box.

### Option B - systemd (no Docker)

```bash
sudo mkdir -p /opt/bgtracker && sudo cp -r . /opt/bgtracker/server
sudo useradd -r -s /usr/sbin/nologin bgtracker
sudo chown -R bgtracker /opt/bgtracker
sudo cp deploy/bgtracker.env.example /etc/bgtracker.env      # then edit
sudo cp deploy/bgtracker-*.{service,timer} /etc/systemd/system/
sudo systemctl enable --now bgtracker-ingest.service bgtracker-aggregate.timer
```

### Expose it (either option)

Add the subdomain vhost - it's an **extra** server block, it does not touch your
other project:

```bash
sudo cp deploy/nginx-bgtracker.conf /etc/nginx/sites-available/bgtracker
# edit server_name + certs, then:
sudo ln -s ../sites-available/bgtracker /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Put **Cloudflare** (free) in front of the subdomain. The stats files are static and
cacheable, so the CDN absorbs essentially all read traffic - the VPS only ever does
ingest + the hourly rebuild, both cheap, no matter how popular the tool gets.

## Wire the client to it

Copy `sources.example.json` (repo root) to `sources.json` and point it at your host:

```json
{
  "heroes":     "https://stats.example.com/heroes-{mmr}-{time}.json",
  "heropowers": "https://stats.example.com/heropowers-{mmr}-{time}.json",
  "trinkets":   "https://stats.example.com/trinkets-{mmr}-{time}.json",
  "cards":      "https://stats.example.com/cards-{mmr}-{time}.json",
  "comps":      "https://stats.example.com/comps-{mmr}-{time}.json"
}
```

`{time}` is one of `all-time | past-seven | past-three | last-patch`; `{mmr}` is
the client's `--mmr` bracket, `100 | 50 | 25 | 10 | 1`. Leaving `{mmr}` out still
works (that file name is bracket 100), and a `{mmr}` URL still works against a
server built before brackets existed - see "MMR buckets" below.

## Contribute data

The overlay does this on its own, on by default since 2026-08-12 (it was
opt-in before): pool.py mines the log history once on start, then uploads each
game as it finishes, throttled to stay well under this server's rate limits.
The off switch is the settings panel's DATA box, or `--no-upload` for one run.
The by-hand path still works and sends the whole backlog in one pass:

```bash
python collect.py                              # mine your own Power.log history
python collect.py --upload https://stats.example.com
```

Only the aggregate signal leaves the machine - **hero, placement, lobby tribes,
date, the offers** - under an opaque per-machine id
(`sha256(local-random-salt : game-id)`). Never a battletag, never the logs.
Re-running is idempotent (the server de-dupes on that id). Add
`--token <secret>` if the server requires one.

## The upload contract

`POST /upload`, JSON body, either one record or `{"games":[...]}` (<=500):

| field              | req | example                        | notes |
|--------------------|-----|--------------------------------|-------|
| `uid`              | yes | `"a1b2..."` (8-128 chars)      | opaque de-dupe key |
| `date`             | yes | `"2026-08-10"` / `"2026_08_10"`| game date |
| `hero`             | *   | `"BG26_HERO_104"`              | hero cardId |
| `place`            | *   | `3`                            | 1..8 |
| `tribes`           |     | `["MURLOC","BEAST"]`           | lobby races |
| `offered_heroes`   |     | `["BG26_HERO_104", ...]`       | unlocks hero pick-rate |
| `offered_trinkets` |     | `[...]`                        | unlocks trinket pick-rate |
| `picked_trinkets`  |     | `[...]`                        | trinket placement |
| `final_board`      |     | `["BG26_888", ...]`            | unlocks card played-vs-not |
| `v`                |     | `"0.3.0-alpha"`                | the client's version |

\* at least one of `hero`/`place` is required; a no-signal record is rejected.
Reply: `{"ok":true,"accepted":N,"stored":M,"rejected":K,"reasons":[...]}`.

`v` is stored so a strange week in the numbers can be checked against **which
builds sent them** before anyone concludes the meta moved. `GET /health` reports
the tally: `{"ok":true,"games":N,"solo":N,"duo":N,"unclassified":N,
"versions":{"0.3.0-alpha":N,"unknown":N}}`. Rows stored before clients sent a
version read `unknown`, never a guessed one. The column is added by the same
`migrate()` that added `duo`, so a server that has been collecting for weeks
picks it up on restart with no data loss.

## What's computed - and what isn't

Nothing here invents a number. Empty beats fake.

- **heroes** - `averagePosition`, placement spread, sample. Pick-rate only once
  clients upload `offered_heroes`.
- **heropowers** - the same numbers for the hero **power**, from the games whose
  hero offered a choice of one. No stats site publishes these at any price, so
  before this the pick panel could name your three options and rate none of
  them. Only some heroes offer a choice, so the table is small by nature. One
  game can pick several powers (a power that hands out another power re-offers),
  so a placement counts once per distinct power per game, while `totalOffered` /
  `totalPicked` count every showing - pick rate is asking "how often is this
  taken when it is on screen".
- **trinkets** - `averagePlacement`, sample. Pick-rate needs `offered_trinkets`.
- **cards** - played-vs-not placement delta, from games that upload `final_board`.
- **comps** - **yes, from the boards players finished on.** Each board is
  labelled with the client's own families and core roles
  (`bgtracker.classify_board`, over `COMP_FAMILIES` + `data/comp_roles.json`),
  imported rather than restated so the feed and the panels cannot drift apart.
  The rule: a board belongs to the tribe it is mostly made of, and only if that
  family's engine piece is standing on it. A board that matches nothing is
  counted as `none` and its placement goes nowhere - sweeping piles into the
  nearest bucket would drag every archetype's average toward the middle.
  Rows are published only once an archetype has `BGTRACKER_COMP_MIN` (30) games;
  below that the file carries the counts (`compClassification`) and no rows, and
  the client falls back to its curated family list. That gap is deliberate: the
  client drops the curated list the moment one measured row arrives, so a
  four-game ranking would replace something useful with something misleading.
  The image needs `bgtracker.py`, `paths.py` and `data/comp_roles.json`, which
  is why the Docker build context is the repo root; without them the file says
  the classifier was unavailable rather than guessing.
- **MMR buckets** - yes, five of them. See "MMR buckets" below for what the
  boundaries are and why.
- **per-tribe hero impact** (`tribeStats`) - not split yet; turns on with volume.

## MMR buckets

The client asks for one of five brackets (`--mmr 100|50|25|10|1`, "the top N% of
players"), so the aggregator writes each table once per bracket:

```
heroes-{mmr}-{time}.json      trinkets-{mmr}-{time}.json
heropowers-{mmr}-{time}.json  comps-{mmr}-{time}.json
cards-{mmr}-{time}.json
buckets.json                  # which brackets exist, per period, with counts
```

Bracket `100` is **also** written under the old un-bucketed name
(`heroes-{time}.json`), so a `sources.json` from before brackets existed keeps
working with no edit.

### Where the boundaries come from

**The top N% of the ratings shared with this server, in that same time window.**
Not a fixed rating ladder, and deliberately not anyone else's cut-offs.

Nobody publishes the real distribution of Battlegrounds rating, and copying
another site's bracket numbers would be using their data - the one thing this
project does not do. The only distribution we can honestly measure is our own
pool, so that is what a bracket is measured against, and every file says so in
its own `mmr` block:

```json
"mmr": {"bucket": 25, "minRating": 7400, "games": 100,
        "basis": "rating >= 7400: the top 25% of the ratings shared with this server in this window"}
```

Two deliberate details:

- **Nearest-rank percentile, rounded DOWN to a round hundred.** Rounding down
  keeps the published boundary off one individual player's exact rating and
  holds it steady while the pool wobbles. It can pull in a few games below the
  strict percentile, which is the honest direction to err: more sample, never
  less.
- **A game with no rating counts only in bracket 100.** The log never states
  your rating (only the optional memory reader knows it), so most early records
  have none. Placing them by guesswork would be inventing a number.

### A bracket is published only when it has data

Below **30 games** (`BGTRACKER_MMR_MIN`, the same number as the client's
`MIN_SAMPLE`) the bracket file is **not written at all**. Four games at "top 1%"
is not granularity, it is noise wearing a label - and a wrong number is treated
here exactly like a made-up one.

When a bracket is missing the client does not go blank: it falls back to the
all-players file, and says which bracket the numbers actually came from
(`stats: 81 heroes (top 100%)`, plus a one-line note on stderr). It never
prints pooled numbers under a "top 1%" heading. The fallback order is: the
bracket asked for, then bracket 100, then the pre-bracket file name - so a
client configured with `{mmr}` also works against a server that has not been
rebuilt yet.

Expect exactly this while the pool is young: **only bracket 100 exists**, and
`--mmr 1` quietly shows everyone. `buckets.json` lists what is really published:

```json
{"minGamesPerBucket": 30,
 "periods": {"past-seven": {"solo": [{"bucket": 100, "minRating": null, "games": 392},
                                     {"bucket": 50, "minRating": 5600, "games": 178}],
                            "duo": [...], "unclassified": 0}}}
```

Trinkets carry a bonus: the all-players file also holds each trinket's
per-bracket placement inline (`averagePlacementAtMmr`), which the client already
prefers when it matches the request - so trinket brackets work even for a
`sources.json` whose URL has no `{mmr}` in it.

> **Data note:** `collect.py`'s log backfill reliably recovers tribes + date, but
> hero + placement come out thin from the logs alone. The overlay's **memory
> reader** is what fills those at game-over (see ROADMAP). Until that's wired, the
> feed is real but sparse - it grows correct, just slowly.

## The update manifest

The same box also answers "is there a newer build?" - and only that. It serves
`update.json`, about 200 bytes, dropped in `out/` beside the stats files. It
does **not** serve the build.

That split is the whole design. A release zip is 28 MB; every client checking on
start costs this box a couple of hundred bytes, while the bytes themselves come
off GitHub's CDN for free, from the same Releases asset the README already links
to. The download location is a plain `url` field, so pointing it somewhere else
later (a mirror, or this box once bandwidth stops mattering) is a manifest edit
rather than a client release - which matters because the clients that would need
that change are exactly the ones that cannot be updated yet.

```json
{
  "schema": 1,
  "version": "0.3.0-alpha",
  "url": "https://github.com/BattlegroundsHelp/bgtracker/releases/download/v0.3.0-alpha/bgtracker-windows.zip",
  "sha256": "3b1f…64 hex characters…9c",
  "size": 27913121,
  "published": "2026-08-12",
  "notes": "https://github.com/BattlegroundsHelp/bgtracker/releases/tag/v0.3.0-alpha"
}
```

| field | required | what it is |
|---|---|---|
| `schema` | no | manifest format number, `1` today; the client ignores it, it exists so a future format can be told apart |
| `version` | yes | the newest build's version, compared with semver rules (`0.10.0` beats `0.9.0`, and `0.3.0-alpha` is older than `0.3.0`) |
| `url` | yes | where the zip is. **Must be https** - the client refuses anything else, and so does `make_manifest.py` |
| `sha256` | yes | of the zip, 64 hex characters. A mismatch refuses the install, full stop |
| `size` | yes | of the zip in bytes. Checked before the hash and used to cut off a download that runs long |
| `published` | no | `YYYY-MM-DD`, for the "released on" line |
| `notes` | no | link to the patch notes, shown so nobody installs a surprise |

A client that cannot reach this file, gets HTML from a hotel wifi, or reads a
manifest older than what it is running, does nothing at all and says nothing.
Checking is on by default; downloading and installing only ever happen when the
user asks.

**One honest limit.** The sha256 proves the bytes are the ones *this manifest*
named. That is exactly as trustworthy as the channel the manifest came over, and
today that is plain HTTP because the box has no certificate. Putting a domain and
TLS in front of this (or Cloudflare, which is free and already recommended above)
is the one thing worth doing before the tool has many users.

## Ship a release

Three lines, after `python build.py` has produced the zip:

```bash
# 1. upload dist/bgtracker-win64-<date>.zip to a GitHub release as bgtracker-windows.zip
# 2. write the manifest from the zip that was actually uploaded (sha256 and size computed, never typed)
python server/make_manifest.py dist/bgtracker-win64-2026-08-12.zip \
    --url https://github.com/BattlegroundsHelp/bgtracker/releases/download/v0.3.0-alpha/bgtracker-windows.zip
# 3. put it on the box
scp server/out/update.json root@<IP>:/opt/bgtracker/server/out/update.json
```

`bash server/deploy/deploy.sh root@<IP>` does step 3 for you when
`server/out/update.json` exists locally, and then fetches it back to prove it is
being served. Either way, check what the world now sees before walking away:

```bash
curl -s http://<IP>/update.json
python update.py --check          # from a checkout on the old version
```

`make_manifest.py` reads the version out of the zip's own `version.txt`, so it
refuses a manifest that disagrees with the build it describes. That is the
mistake worth engineering against: a manifest one version ahead of its zip ships
an update that installs, still reports the old version, and gets offered again
on every start forever.

CI does **not** build or publish releases - `.github/workflows/ci.yml` runs the
lint, the offline regression and the updater's failure-mode suite on
windows-latest, and nothing else. The build and the upload are done by hand, on
purpose: the release is a 28 MB unsigned binary and there is no signing key.

## Hardening (honest MVP, not the finish)

In place: strict schema validation, body-size cap, optional shared upload token,
per-IP rate limit, loopback-only bind, resource caps, non-root, idempotent inserts.

The real long-term threat is **stats poisoning** - someone scripting fake games to
skew the numbers. The uid + rate limit blunt volume, not a determined attacker. The
planned answer is trusted-client signing + outlier/`dataPoints` floors in the
aggregator (ROADMAP). Don't advertise a public write endpoint as tamper-proof; it
isn't yet.
