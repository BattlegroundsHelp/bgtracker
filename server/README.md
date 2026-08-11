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
        │  POST /upload   {uid, date, hero, place, tribes, ...}   (opt-in, anonymised)
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
  "heroes":   "https://stats.example.com/heroes-{time}.json",
  "trinkets": "https://stats.example.com/trinkets-{time}.json",
  "cards":    "https://stats.example.com/cards-{time}.json",
  "comps":    "https://stats.example.com/comps-{time}.json"
}
```

`{time}` is one of `all-time | past-seven | past-three | last-patch`.

## Contribute data (opt-in)

```bash
python collect.py                              # mine your own Power.log history
python collect.py --upload https://stats.example.com
```

Only the aggregate signal leaves your machine - **hero, placement, lobby tribes,
date**, under an opaque per-machine id (`sha256(local-random-salt : game-id)`).
Never your battletag, never the logs. Re-running is idempotent (the server de-dupes
on that id). Add `--token <secret>` if the server requires one.

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

\* at least one of `hero`/`place` is required; a no-signal record is rejected.
Reply: `{"ok":true,"accepted":N,"stored":M,"rejected":K,"reasons":[...]}`.

## What's computed - and what isn't

Nothing here invents a number. Empty beats fake.

- **heroes** - `averagePosition`, placement spread, sample. Pick-rate only once
  clients upload `offered_heroes`.
- **trinkets** - `averagePlacement`, sample. Pick-rate needs `offered_trinkets`.
- **cards** - played-vs-not placement delta, from games that upload `final_board`.
- **comps** - **not yet.** Archetype labelling (Beasts / Murlocs / Menagerie ...)
  needs a classifier we haven't built; the file is written empty so the client
  shows "no comp data" instead of erroring.
- **per-tribe hero impact** (`tribeStats`) and **MMR buckets** - not split yet;
  every request currently serves the whole pool. They turn on with volume.

> **Data note:** `collect.py`'s log backfill reliably recovers tribes + date, but
> hero + placement come out thin from the logs alone. The overlay's **memory
> reader** is what fills those at game-over (see ROADMAP). Until that's wired, the
> feed is real but sparse - it grows correct, just slowly.

## Hardening (honest MVP, not the finish)

In place: strict schema validation, body-size cap, optional shared upload token,
per-IP rate limit, loopback-only bind, resource caps, non-root, idempotent inserts.

The real long-term threat is **stats poisoning** - someone scripting fake games to
skew the numbers. The uid + rate limit blunt volume, not a determined attacker. The
planned answer is trusted-client signing + outlier/`dataPoints` floors in the
aggregator (ROADMAP). Don't advertise a public write endpoint as tamper-proof; it
isn't yet.
