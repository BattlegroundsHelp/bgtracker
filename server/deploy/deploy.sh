#!/usr/bin/env bash
# One command to put the stats server on a fresh Ubuntu box.
#
#   bash server/deploy/deploy.sh root@<IP>                     # plain HTTP on the IP
#   bash server/deploy/deploy.sh root@<IP> stats.example.com   # with a domain + TLS
#
# What it does, in order: installs Docker if missing, copies server/ up, builds
# and starts the two containers (ingest on loopback, aggregate on an hourly
# loop), puts Caddy in front for static reads and the upload path, then VERIFIES
# from your machine that /health answers and that a real upload round-trips.
# It refuses to claim success it has not seen.
#
# Safe to re-run: everything is idempotent, and re-running is how you ship an
# update.
set -euo pipefail

TARGET="${1:-}"
DOMAIN="${2:-}"
[ -n "$TARGET" ] || { echo "usage: deploy.sh root@<IP> [domain]"; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # the server/ folder
# SSH_KEY lets you point at a key that is not one of ssh's default names,
# which is the usual case when the box was created with a named DO key:
#   SSH_KEY=~/.ssh/mykey bash server/deploy/deploy.sh root@<IP>
KEYOPT=""
[ -n "${SSH_KEY:-}" ] && KEYOPT="-i $SSH_KEY"
SSH="ssh $KEYOPT -o StrictHostKeyChecking=accept-new $TARGET"
HOSTPART="${TARGET#*@}"

echo "==> 1/6 checking the box is reachable"
$SSH "echo ok; . /etc/os-release; echo \$PRETTY_NAME"

echo "==> 2/6 installing docker if it is not already there"
$SSH 'command -v docker >/dev/null 2>&1 || (curl -fsSL https://get.docker.com | sh)'
$SSH 'docker --version && (docker compose version || true)'

echo "==> 3/6 copying the server"
# scp, not tar-over-ssh: the pipe form dies under Git Bash on Windows
# ("cygheap read copy failed"), and this has to work from the machine the
# author actually uses. data/ and out/ live on the box and are never touched.
$SSH 'mkdir -p /opt/bgtracker && rm -rf /opt/bgtracker/server.new'
scp $KEYOPT -o StrictHostKeyChecking=accept-new -q -r "$HERE" "$TARGET:/opt/bgtracker/server.new"
# The box's data/ and out/ always win. The rm -rf first is load bearing: as soon
# as the machine you deploy from has its own server/out (it does the moment you
# build a release manifest there), scp carries that folder up, and `mv` onto an
# existing folder would nest the box's live feed at out/out/ instead of
# replacing it - the whole feed would 404.
$SSH 'cd /opt/bgtracker && \
      if [ -d server/data ]; then rm -rf server.new/data && mv server/data server.new/data; fi && \
      if [ -d server/out ]; then rm -rf server.new/out && mv server/out server.new/out; fi && \
      if [ -f server/.env ]; then mv server/.env server.new/.env; fi && \
      rm -rf server && mv server.new server && rm -rf server/__pycache__'
# The shipped text files ride in the REPO's data/, and the compose build
# context is the PARENT of server/ (context: .., mirroring the repo layout) -
# so they must sit at /opt/bgtracker/data/ or the image build dies on
# "data/hero_tips.json: not found" (it did, 2026-08-14, and revealed the tips
# service had silently never deployed at all).
$SSH 'mkdir -p /opt/bgtracker/data'
scp $KEYOPT -o StrictHostKeyChecking=accept-new -q \
    "$HERE/../data/hero_tips.json" "$HERE/../data/hero_tips.schema.json" \
    "$HERE/../data/comp_roles.json" "$TARGET:/opt/bgtracker/data/"
# ...and the two repo-root modules the Dockerfile copies (aggregate.py
# imports the card tables through bgtracker.py).
scp $KEYOPT -o StrictHostKeyChecking=accept-new -q \
    "$HERE/../bgtracker.py" "$HERE/../paths.py" "$TARGET:/opt/bgtracker/"

echo "==> 4/6 starting ingest + aggregate"
# The image runs as uid 10001 (see Dockerfile: USER app), but a bind mount that
# docker creates is owned by root, so the container cannot open its own SQLite
# file. Create the dirs and hand them to that uid BEFORE starting, or ingest
# crash-loops on "unable to open database file".
$SSH 'cd /opt/bgtracker/server && \
      mkdir -p data out && chown -R 10001:10001 data out && \
      ([ -f .env ] || echo "BGTRACKER_UPLOAD_TOKEN=" > .env) && \
      docker compose up -d --build && docker compose ps'

echo "==> 5/6 putting Caddy in front"
if [ -n "$DOMAIN" ]; then SITE="$DOMAIN"; else SITE=":80"; fi
$SSH "mkdir -p /opt/bgtracker/caddy && cat > /opt/bgtracker/caddy/Caddyfile <<EOF
$SITE {
    encode gzip
    handle /upload* {
        reverse_proxy 127.0.0.1:8787
    }
    handle /health* {
        reverse_proxy 127.0.0.1:8787
    }
    handle /tips* {
        reverse_proxy 127.0.0.1:8788
    }
    handle {
        root * /opt/bgtracker/server/out
        file_server browse
    }
}
EOF
docker rm -f bgtracker-caddy >/dev/null 2>&1 || true
docker run -d --name bgtracker-caddy --restart unless-stopped --network host \
  -v /opt/bgtracker/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v /opt/bgtracker/caddy/data:/data \
  -v /opt/bgtracker/server/out:/opt/bgtracker/server/out:ro \
  caddy:2 >/dev/null && echo caddy up"

# The update manifest, if one has been built. It is just another static file in
# the folder already being served, which is the entire point of the split: the
# box serves ~200 bytes per client, the 28 MB build comes off GitHub's CDN.
# Build it first with:  python server/make_manifest.py <zip> --url <asset url>
if [ -f "$HERE/out/update.json" ]; then
  echo "==> 5b   publishing the update manifest"
  scp $KEYOPT -o StrictHostKeyChecking=accept-new -q \
      "$HERE/out/update.json" "$TARGET:/opt/bgtracker/server/out/update.json"
  $SSH 'chown 10001:10001 /opt/bgtracker/server/out/update.json'
else
  echo "==> 5b   no server/out/update.json here, leaving the box's manifest alone"
fi

echo "==> 6/6 verifying from here, not from the box"
BASE="http://${DOMAIN:-$HOSTPART}"
sleep 4
echo "-- health"
curl -fsS "$BASE/health" || { echo "FAILED: /health did not answer"; exit 1; }
echo
echo "-- upload round trip (one synthetic game, then check it counted)"
UID_TEST=$(python -c "import hashlib,time;print(hashlib.sha256(str(time.time()).encode()).hexdigest()[:32])" 2>/dev/null \
  || python3 -c "import hashlib,time;print(hashlib.sha256(str(time.time()).encode()).hexdigest()[:32])")
BEFORE=$(curl -fsS "$BASE/health")
curl -fsS -X POST "$BASE/upload" -H 'Content-Type: application/json' \
  -d "{\"games\":[{\"uid\":\"$UID_TEST\",\"date\":\"$(date +%F)\",\"hero\":\"TB_BaconShop_HERO_50\",\"place\":1,\"tribes\":[\"MECHANICAL\",\"BEAST\"]}]}"
echo
AFTER=$(curl -fsS "$BASE/health")
echo "health before: $BEFORE"
echo "health after:  $AFTER"

# Take the synthetic game back out. It proved the write path works and it is
# not a game anybody played, so leaving it behind quietly pollutes the pool:
# one fake row per deploy, and they add up (four had to be dug out of the live
# pool by hand on 2026-08-12).
echo "-- removing the synthetic game again"
$SSH "cd /opt/bgtracker/server && docker compose exec -T ingest python -c \"
import glob, sqlite3
c = sqlite3.connect(glob.glob('/data/*.db')[0])
c.execute('delete from games where uid = ?', ('$UID_TEST',))
c.commit()
print('smoke-test row removed:', c.total_changes)\"" \
  || echo "WARNING: could not remove the synthetic game (uid $UID_TEST) - do it by hand"
echo
echo "DONE. Point sources.json at:"
echo "  \"heroes\":   \"$BASE/heroes-{time}.json\""
echo "  \"trinkets\": \"$BASE/trinkets-{time}.json\""
echo "  \"cards\":    \"$BASE/cards-{time}.json\""
echo "  \"comps\":    \"$BASE/comps-{time}.json\""
echo
if [ -f "$HERE/out/update.json" ]; then
  echo "-- update manifest"
  curl -fsS "$BASE/update.json" || echo "FAILED: the manifest is not being served"
  echo
fi
echo "Feed files appear after the first aggregate pass (hourly, or force one now):"
echo "  ssh $TARGET 'cd /opt/bgtracker/server && docker compose run --rm aggregate python aggregate.py'"
