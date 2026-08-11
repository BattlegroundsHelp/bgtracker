#!/usr/bin/env python3
"""
Ingest endpoint - the write side of the independent dataset.

Receives opt-in, anonymised game records from clients (the overlay / collect.py)
and appends them to a local SQLite store. It computes nothing; aggregate.py turns
the store into the stats feed the client reads. Splitting the two means the public
endpoint only ever does a tiny validated INSERT, and the heavy grouping runs on a
timer, off the request path.

Design goals, in order: safe to expose, cheap to run, zero pip installs.
  - stdlib only (http.server + sqlite3) - nothing to `pip install` on the VPS.
  - one small validated INSERT OR IGNORE per game, de-duped on an opaque uid, so a
    client re-uploading its whole backlog is idempotent and free.
  - never trusts the payload: size cap, strict schema, optional shared token, and a
    crude per-IP rate limit. Stats poisoning is the real long-term threat - see the
    "Hardening" note in server/README.md; this is the honest MVP, not the finish.

Run it behind the reverse proxy you already have (see server/README.md), never
naked on the internet. Nginx/Caddy serves the aggregated JSON as static files; this
process only handles POST /upload and GET /health.

    python ingest.py                 # 127.0.0.1:8787, data/games.db
    BGTRACKER_UPLOAD_TOKEN=... python ingest.py    # require X-Upload-Token

Env: BGTRACKER_DB, BGTRACKER_BIND, BGTRACKER_PORT, BGTRACKER_UPLOAD_TOKEN,
     BGTRACKER_MAX_BODY (bytes), BGTRACKER_RATE (uploads/min/IP).
"""

import json
import os
import re
import sqlite3
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

DB_PATH = Path(os.environ.get("BGTRACKER_DB", Path(__file__).parent.parent / "data" / "games.db"))
BIND = os.environ.get("BGTRACKER_BIND", "127.0.0.1")
PORT = int(os.environ.get("BGTRACKER_PORT", "8787"))
TOKEN = os.environ.get("BGTRACKER_UPLOAD_TOKEN") or None
MAX_BODY = int(os.environ.get("BGTRACKER_MAX_BODY", str(256 * 1024)))   # 256 KB / request
RATE = int(os.environ.get("BGTRACKER_RATE", "120"))                     # uploads / minute / IP

# What a valid game looks like. Everything past the core four is optional - the
# log backfill fills {uid, date, hero, place, tribes}; the live overlay can later
# add offers / final board, which unlock pick-rate and card deltas in aggregate.py.
HERO_RE = re.compile(r"^(BG\d+_HERO_\d+|TB_BaconShop_HERO_\d+)$")
CARD_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
DATE_RE = re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}$")
UID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
# Tribe names exactly as Hearthstone writes them to the log (CARDRACE value=...),
# which is what collect.py uploads. MECHANICAL is spelled out, not "MECH".
RACES = {"MURLOC", "DEMON", "MECHANICAL", "ELEMENTAL", "BEAST", "PIRATE", "DRAGON",
         "QUILBOAR", "UNDEAD", "NAGA", "ALL"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    uid              TEXT PRIMARY KEY,   -- opaque, client-hashed; the de-dupe key
    ts               INTEGER NOT NULL,   -- server receive time (epoch s)
    date             TEXT,               -- game date, YYYY-MM-DD
    hero             TEXT,
    place            INTEGER,            -- 1..8
    mmr              INTEGER,
    tribes           TEXT,               -- json array of race names
    offered_heroes   TEXT,               -- json array of cardIds (pick-rate denominator)
    offered_trinkets TEXT,
    picked_trinkets  TEXT,
    final_board      TEXT,               -- json array of cardIds (card stats)
    client           TEXT                -- opaque client tag, for rate/abuse only
);
CREATE INDEX IF NOT EXISTS games_date ON games(date);
"""


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _clean_ids(v, limit=16):
    """A bounded list of cardId-shaped strings, or None."""
    if not isinstance(v, list):
        return None
    out = [x for x in v if isinstance(x, str) and CARD_RE.match(x)][:limit]
    return out or None


def validate(rec):
    """Return a normalised row dict, or raise ValueError. Bad-typed CORE fields
    (uid/date/hero/place) reject the record; bad extras just fall to null - a
    partial game still aggregates."""
    if not isinstance(rec, dict):
        raise ValueError("record is not an object")

    uid = rec.get("uid")
    if not isinstance(uid, str) or not UID_RE.match(uid):
        raise ValueError("uid missing or malformed")

    date = rec.get("date")
    if not isinstance(date, str) or not DATE_RE.match(date):
        raise ValueError("date missing or not YYYY-MM-DD")
    date = date.replace("_", "-")

    hero = rec.get("hero")
    if hero is not None and not (isinstance(hero, str) and HERO_RE.match(hero)):
        raise ValueError("hero malformed")

    place = rec.get("place")
    if place is not None and not (isinstance(place, int) and 1 <= place <= 8):
        raise ValueError("place out of range")

    mmr = rec.get("mmr")
    if mmr is not None and not (isinstance(mmr, int) and 0 <= mmr <= 30000):
        raise ValueError("mmr out of range")

    tribes = rec.get("tribes")
    if tribes is not None:
        if not isinstance(tribes, list) or any(t not in RACES for t in tribes):
            raise ValueError("tribes has an unknown race")
        tribes = tribes[:8]

    if hero is None and place is None:
        raise ValueError("record carries no signal (no hero, no place)")

    oh, ot, pt = _clean_ids(rec.get("offered_heroes")), _clean_ids(rec.get("offered_trinkets")), _clean_ids(rec.get("picked_trinkets"))
    fb = _clean_ids(rec.get("final_board"), limit=14)
    return {
        "uid": uid, "ts": int(time.time()), "date": date, "hero": hero,
        "place": place, "mmr": mmr,
        "tribes": json.dumps(tribes) if tribes else None,
        "offered_heroes": json.dumps(oh) if oh else None,
        "offered_trinkets": json.dumps(ot) if ot else None,
        "picked_trinkets": json.dumps(pt) if pt else None,
        "final_board": json.dumps(fb) if fb else None,
        "client": (rec.get("client") or "")[:64] or None,
    }


COLS = ("uid", "ts", "date", "hero", "place", "mmr", "tribes",
        "offered_heroes", "offered_trinkets", "picked_trinkets", "final_board", "client")
INSERT = f"INSERT OR IGNORE INTO games ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})"


class Limiter:
    """Crude per-IP sliding-window limiter. In-memory, resets on restart - enough
    to blunt a script, not a substitute for the reverse proxy's own limits."""
    def __init__(self, per_min):
        self.per_min = per_min
        self.hits = {}
        self.lock = Lock()

    def ok(self, ip):
        now = time.time()
        with self.lock:
            q = self.hits.setdefault(ip, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


class Handler(BaseHTTPRequestHandler):
    server_version = "bgtracker-ingest/1.0"
    limiter = Limiter(RATE)

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass   # quiet; the reverse proxy logs requests

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            try:
                with db() as c:
                    n = c.execute("SELECT COUNT(*) FROM games").fetchone()[0]
                self._send(200, {"ok": True, "games": n})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/upload":
            return self._send(404, {"ok": False, "error": "not found"})

        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        if not self.limiter.ok(ip):
            return self._send(429, {"ok": False, "error": "rate limited"})

        if TOKEN and self.headers.get("X-Upload-Token") != TOKEN:
            return self._send(401, {"ok": False, "error": "bad or missing upload token"})

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"ok": False, "error": f"body must be 1..{MAX_BODY} bytes"})

        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            return self._send(400, {"ok": False, "error": "body is not valid JSON"})

        # accept a single record or {"games": [...]} - the backfill sends batches
        records = payload.get("games") if isinstance(payload, dict) and "games" in payload else [payload]
        if not isinstance(records, list) or not records:
            return self._send(400, {"ok": False, "error": "no records"})
        if len(records) > 500:
            return self._send(413, {"ok": False, "error": "max 500 games per request"})

        rows, rejected = [], []
        for rec in records:
            try:
                v = validate(rec)
                rows.append(tuple(v[c] for c in COLS))
            except ValueError as e:
                rejected.append(str(e))

        stored = 0
        if rows:
            try:
                with db() as c:
                    before = c.total_changes
                    c.executemany(INSERT, rows)
                    c.commit()
                    stored = c.total_changes - before   # INSERT OR IGNORE: real inserts only
            except Exception as e:
                return self._send(500, {"ok": False, "error": f"store failed: {e}"})

        self._send(200, {"ok": True, "accepted": len(rows), "stored": stored,
                         "rejected": len(rejected), "reasons": rejected[:10]})


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"bgtracker ingest on http://{BIND}:{PORT}  db={DB_PATH}  "
          f"token={'on' if TOKEN else 'off'}  rate={RATE}/min")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
