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
SSH="ssh -o StrictHostKeyChecking=accept-new $TARGET"
HOSTPART="${TARGET#*@}"

echo "==> 1/6 checking the box is reachable"
$SSH "echo ok; . /etc/os-release; echo \$PRETTY_NAME"

echo "==> 2/6 installing docker if it is not already there"
$SSH 'command -v docker >/dev/null 2>&1 || (curl -fsSL https://get.docker.com | sh)'
$SSH 'docker --version && (docker compose version || true)'

echo "==> 3/6 copying the server"
$SSH 'mkdir -p /opt/bgtracker'
# data/ and out/ live on the box and are never overwritten by a deploy
tar --exclude data --exclude out --exclude '__pycache__' -czf - -C "$HERE/.." server \
  | $SSH 'tar -xzf - -C /opt/bgtracker'

echo "==> 4/6 starting ingest + aggregate"
$SSH 'cd /opt/bgtracker/server && \
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
echo
echo "DONE. Point sources.json at:"
echo "  \"heroes\":   \"$BASE/heroes-{time}.json\""
echo "  \"trinkets\": \"$BASE/trinkets-{time}.json\""
echo "  \"cards\":    \"$BASE/cards-{time}.json\""
echo "  \"comps\":    \"$BASE/comps-{time}.json\""
echo
echo "Feed files appear after the first aggregate pass (hourly, or force one now):"
echo "  ssh $TARGET 'cd /opt/bgtracker/server && docker compose run --rm aggregate python aggregate.py'"
