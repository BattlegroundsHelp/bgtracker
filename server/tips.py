#!/usr/bin/env python3
"""
Hero tips - the community pipeline for the one line shown under each hero in
the draft. Submissions in, votes on them, and a published static file the
overlay reads exactly like every other feed.

Same shape as ingest.py on purpose (stdlib only, sqlite3, one small validated
write per request, a crude per-IP limiter, and the heavy step OFF the request
path writing static JSON). Read that file first; this one is its sibling, not
a new pattern.

    python tips.py                      # 127.0.0.1:8788, data/tips.db
    python tips.py --seed ../data/hero_tips.json    # the shipped lines, votable
    python tips.py --publish            # write out/hero-tips-community.json

Endpoints
    POST /tips/submit  {hero, when, bullets?, name?, client?}
                       -> {ok, id, stored}
    POST /tips/vote    {id, value: 1|-1, client?}  -> {ok, id, score, voters}
                       also accepts a form POST, which is how the page below
                       votes without a line of JavaScript
    GET  /tips?hero=ID -> every tip for that hero with its score, best first
    GET  /tips/page    -> a plain HTML list with vote buttons; ?hero=ID for one
    GET  /tips/health  -> counts

WHAT STOPS A BAD ACTOR - the honest version. Uploads here are anonymous, so
there is no identity to enforce one person one vote with. What exists:
  - a per-IP sliding window, same as ingest.py, which blunts a loop;
  - a voter KEY = sha256(server salt + client tag + address block), and votes
    are PRIMARY KEY (tip, voter), so a second vote REPLACES the first. One
    machine keeping its client id and its address gets exactly one vote per
    tip, however many times it asks;
  - the publish floors below. A tip only reaches a client once distinct voters
    and score clear a floor AND it beats the shipped line by a margin, so a
    handful of manufactured voters changes nothing anybody sees.
What is NOT solved: someone rotating client ids across many addresses can
still manufacture voters, because nothing here knows who anyone is. The floors
are the lock, not the ballot box, and the feed is a file a maintainer
regenerates and can inspect and revert. Do not call this tamper-proof.

Nothing here is required for the tool to work. No server, no feed file, no
network: the client shows the tips that ship in data/hero_tips.json, which is
also what it shows for every hero the community has not out-voted.

Env: BGTRACKER_TIPS_DB, BGTRACKER_TIPS_BIND, BGTRACKER_TIPS_PORT,
     BGTRACKER_TIPS_TOKEN, BGTRACKER_TIPS_SALT, BGTRACKER_TIPS_RATE,
     BGTRACKER_TIPS_MAX_BODY, BGTRACKER_OUT, BGTRACKER_TIPS_VOTE_URL,
     BGTRACKER_TIPS_MIN_VOTERS, BGTRACKER_TIPS_MIN_SCORE,
     BGTRACKER_TIPS_MARGIN, BGTRACKER_TIPS_SUBMIT_CAP
"""

import gzip
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

HERE = Path(__file__).parent
DB_PATH = Path(os.environ.get("BGTRACKER_TIPS_DB", HERE.parent / "data" / "tips.db"))
OUT = Path(os.environ.get("BGTRACKER_OUT", HERE / "out"))
BIND = os.environ.get("BGTRACKER_TIPS_BIND", "127.0.0.1")
PORT = int(os.environ.get("BGTRACKER_TIPS_PORT", "8788"))
TOKEN = os.environ.get("BGTRACKER_TIPS_TOKEN") or None
RATE = int(os.environ.get("BGTRACKER_TIPS_RATE", "60"))          # requests/min/IP
MAX_BODY = int(os.environ.get("BGTRACKER_TIPS_MAX_BODY", "8192"))
VOTE_URL = os.environ.get("BGTRACKER_TIPS_VOTE_URL") or None

# The publish floors. A community line REPLACES a written, reviewed one on a
# stranger's screen, so the bar is deliberately higher than "most upvotes".
MIN_VOTERS = int(os.environ.get("BGTRACKER_TIPS_MIN_VOTERS", "5"))
MIN_SCORE = int(os.environ.get("BGTRACKER_TIPS_MIN_SCORE", "3"))
MARGIN = int(os.environ.get("BGTRACKER_TIPS_MARGIN", "2"))
# Submissions per voter per day. One person writing 200 tips in an hour is not
# a contributor, and the tips table is what the publish step has to read.
SUBMIT_CAP = int(os.environ.get("BGTRACKER_TIPS_SUBMIT_CAP", "20"))

# The same shapes the shipped file obeys - data/hero_tips.schema.json is the
# contract and tests/test_regression.py enforces it there. Restated rather than
# imported because this process must not need the client's code to run.
HERO_RE = re.compile(r"^(BG[A-Z0-9]*_HERO_\d+|TB_BaconShop_HERO_\d+)$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
WHEN_MIN, WHEN_MAX = 8, 80
BULLET_MIN, BULLET_MAX = 8, 100
# Text a human wrote, and nothing else. Dashes as pauses are banned in this
# project's user-facing copy, a link in a tip line is an advert, and a control
# character would break the single line the overlay draws with it.
BANNED = ("—", "–", "http://", "https://", "www.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tips (
    id      TEXT PRIMARY KEY,   -- sha256(hero + text)[:32]: the same line sent
                                -- twice is ONE tip with two votes, not two tips
    hero    TEXT NOT NULL,
    txt     TEXT NOT NULL,      -- the 'when' line, the only thing drawn on screen
    bullets TEXT,               -- json array, 0-3, the reference half
    name    TEXT,               -- the hero's name, for the page. Informational.
    shipped INTEGER DEFAULT 0,  -- 1 = seeded from data/hero_tips.json
    ts      INTEGER NOT NULL,
    author  TEXT                -- voter key of the submitter, for rate accounting
);
CREATE INDEX IF NOT EXISTS tips_hero ON tips(hero);
CREATE TABLE IF NOT EXISTS votes (
    tip     TEXT NOT NULL,
    voter   TEXT NOT NULL,
    value   INTEGER NOT NULL,   -- +1 or -1
    ts      INTEGER NOT NULL,
    PRIMARY KEY (tip, voter)    -- one voter, one standing vote per tip
);
"""


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def salt() -> str:
    """The secret the voter key is hashed with.

    It has to survive a restart or every voter becomes a new voter and the one
    vote per tip rule quietly stops meaning anything. From the environment when
    the operator sets one, otherwise generated once next to the database.
    Keeping it secret is the point: the key is derived from an address, and a
    stored hash anyone could recompute would be a stored address."""
    env = os.environ.get("BGTRACKER_TIPS_SALT")
    if env:
        return env
    p = DB_PATH.parent / "tips.salt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    s = secrets.token_hex(16)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass                     # Windows dev box; the file is still not served
    return s


def ip_block(ip: str) -> str:
    """The address narrowed to a block, so a household is one voter and a phone
    that re-dials is still the same one. /24 for v4, /48 for v6."""
    ip = (ip or "").strip()
    if ":" in ip:
        return ":".join(ip.split(":")[:3])
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) == 4 else ip


def voter_key(ip: str, client) -> str:
    """Who is voting, as far as anything here can tell. Salted so the stored key
    cannot be turned back into an address, and bound to the client tag as well
    as the address block so two people behind one router still vote twice."""
    c = client if isinstance(client, str) and CLIENT_RE.match(client) else ""
    return hashlib.sha256(f"{salt()}:{c}:{ip_block(ip)}".encode()).hexdigest()[:32]


def tip_id(hero: str, txt: str) -> str:
    return hashlib.sha256(f"{hero}\n{txt}".encode()).hexdigest()[:32]


def clean_line(v, lo, hi):
    """One line of human text, or a ValueError saying what is wrong with it."""
    if not isinstance(v, str):
        raise ValueError("text must be a string")
    s = " ".join(v.split())                    # a tip is one line, always
    if not lo <= len(s) <= hi:
        raise ValueError(f"text must be {lo} to {hi} characters, got {len(s)}")
    if s.rstrip().endswith("."):
        raise ValueError("a tip line does not end in a full stop")
    low = s.lower()
    for b in BANNED:
        if b in low:
            raise ValueError(f"text may not contain {b!r}")
    if any(ord(ch) < 32 for ch in s):
        raise ValueError("text may not contain control characters")
    return s


def validate_tip(rec):
    """A submitted tip, normalised, or a ValueError. Same rules as the file that
    ships, so anything stored here could be pasted into it unchanged."""
    if not isinstance(rec, dict):
        raise ValueError("record is not an object")
    hero = rec.get("hero")
    if not isinstance(hero, str) or not HERO_RE.match(hero):
        raise ValueError("hero missing or malformed")
    txt = clean_line(rec.get("when"), WHEN_MIN, WHEN_MAX)
    raw = rec.get("bullets") or []
    if not isinstance(raw, list) or len(raw) > 3:
        raise ValueError("bullets must be a list of at most 3 lines")
    bullets = [clean_line(b, BULLET_MIN, BULLET_MAX) for b in raw]
    name = rec.get("name")
    name = name.strip()[:60] if isinstance(name, str) else None
    return {"id": tip_id(hero, txt), "hero": hero, "txt": txt,
            "bullets": json.dumps(bullets) if bullets else None,
            "name": name or None}


class Limiter:
    """Crude per-IP sliding-window limiter, the same one ingest.py runs.
    In-memory, resets on restart - enough to blunt a script, not a substitute
    for the reverse proxy's own limits."""
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


def scores(conn, hero=None):
    """Every tip for one hero, or for all of them, best first."""
    where, args = ("WHERE t.hero = ?", (hero,)) if hero else ("", ())
    rows = conn.execute(
        "SELECT t.id, t.hero, t.txt, t.bullets, t.name, t.shipped, "
        "       COALESCE(SUM(v.value), 0), COUNT(v.voter) "
        f"FROM tips t LEFT JOIN votes v ON v.tip = t.id {where} "
        "GROUP BY t.id ORDER BY 7 DESC, t.ts ASC", args).fetchall()
    return [{"id": r[0], "hero": r[1], "when": r[2],
             "bullets": json.loads(r[3]) if r[3] else [],
             "name": r[4], "shipped": bool(r[5]), "score": r[6], "voters": r[7]}
            for r in rows]


def winners(conn):
    """The community's choice per hero, where there is one.

    "A clear winner" is a real test, not the top of a list: the tip has to clear
    a distinct-voter floor and a score floor, and beat BOTH the shipped line and
    the next community line by MARGIN. A tie, a thin vote, or a line that only
    just edges the shipped one leaves the hero alone and the client keeps what
    it shipped with. Same rule the rest of the tool uses for numbers: too little
    evidence is not a result."""
    per_hero = {}
    for t in scores(conn):
        per_hero.setdefault(t["hero"], []).append(t)
    out = {}
    for hero, tips in per_hero.items():
        shipped = max([t["score"] for t in tips if t["shipped"]], default=0)
        others = sorted([t for t in tips if not t["shipped"]],
                        key=lambda t: t["score"], reverse=True)
        if not others:
            continue
        best = others[0]
        beat = max(shipped, others[1]["score"]) if len(others) > 1 else shipped
        if (best["voters"] >= MIN_VOTERS and best["score"] >= MIN_SCORE
                and best["score"] - beat >= MARGIN):
            out[hero] = best
    return out


def publish(conn):
    """Write the static file the client reads. Same discipline as
    server/aggregate.py: a plain .json plus a gzip twin, and a hero with no
    clear winner is ABSENT rather than written out with the shipped text -
    absent is exactly what tells the client to use its own copy."""
    OUT.mkdir(parents=True, exist_ok=True)
    tips = {}
    for hero, t in sorted(winners(conn).items()):
        try:                       # re-checked at publish time, so a rule
            when = clean_line(t["when"], WHEN_MIN, WHEN_MAX)      # tightened
            bullets = [clean_line(b, BULLET_MIN, BULLET_MAX)      # after a tip
                       for b in t["bullets"]]                     # was stored
        except ValueError:                                        # cleans the
            continue                                              # feed anyway
        tips[hero] = {"when": when, "bullets": bullets, "id": t["id"],
                      "score": t["score"], "voters": t["voters"]}
    doc = {"version": 1, "source": "community",
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "rules": {"min_voters": MIN_VOTERS, "min_score": MIN_SCORE,
                     "margin": MARGIN},
           "tips": tips}
    if VOTE_URL:
        doc["vote_url"] = VOTE_URL
    raw = json.dumps(doc, indent=1).encode()
    (OUT / "hero-tips-community.json").write_bytes(raw)
    with gzip.open(OUT / "hero-tips-community.json.gz", "wb") as f:
        f.write(raw)                                # bandwidth-friendly twin
    return doc


def seed(conn, path):
    """Put the shipped lines in the table so they can be voted on too.

    Without this the vote is unopposed: people could only rank new submissions
    against each other, and the line already on screen - the one they actually
    want to keep or replace - would not be on the ballot."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for hero, e in (doc.get("tips") or {}).items():
        try:
            v = validate_tip({"hero": hero, "when": e.get("when"),
                              "bullets": e.get("bullets"), "name": e.get("name")})
        except ValueError as err:
            print(f"  ! {hero}: {err}", file=sys.stderr)
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO tips (id, hero, txt, bullets, name, shipped, ts, author)"
            " VALUES (?,?,?,?,?,1,?,NULL)",
            (v["id"], v["hero"], v["txt"], v["bullets"], v["name"], int(time.time())))
        n += cur.rowcount
    conn.commit()
    return n


PAGE_CSS = """body{background:#14140f;color:#ddd;font:14px/1.5 system-ui,sans-serif;
margin:0 auto;max-width:44rem;padding:2rem 1rem}h1{font-size:1.2rem;color:#d8b45a}
li{margin:.9rem 0;list-style:none}form{display:inline}button{background:#222;color:#ddd;
border:1px solid #444;border-radius:4px;cursor:pointer;padding:.1rem .5rem}
.s{color:#888;font-size:.85rem}.k{color:#d8b45a}"""


def page(conn, hero=None):
    """The whole voting UI: a list and two buttons, no JavaScript.

    It exists so the link the client shows leads somewhere a person can act.
    Every value that reaches the HTML is escaped, and the only writer is the
    same POST /tips/vote the API uses, so the rate limit and the voter key
    cover the page for free."""
    rows = scores(conn, hero)
    title = f"hero tips: {html.escape(hero)}" if hero else "hero tips"
    body = [f"<!doctype html><meta charset=utf-8><title>{title}</title>",
            f"<style>{PAGE_CSS}</style><h1>{title}</h1>",
            "<p class=s>One vote per tip. Voting again replaces your last vote. "
            "The top line only replaces the tip that ships with the tool once it "
            f"clears {MIN_VOTERS} voters, {MIN_SCORE} points and a {MARGIN} point "
            "margin.</p><ul>"]
    if not rows:
        body.append("<li class=s>nothing submitted yet</li>")
    for r in rows:
        who = html.escape(r["name"] or r["hero"])
        mark = " <span class=k>[ships with the tool]</span>" if r["shipped"] else ""
        buttons = "".join(
            f"<form method=post action=/tips/vote>"
            f"<input type=hidden name=id value={r['id']}>"
            f"<input type=hidden name=value value={v}>"
            f"<button>{lbl}</button></form> "
            for v, lbl in ((1, "up"), (-1, "down")))
        body.append(f"<li><b>{who}</b>{mark}<br>{html.escape(r['when'])}<br>"
                    f"<span class=s>{r['score']:+d} from {r['voters']} voter(s)</span> "
                    f"{buttons}</li>")
    body.append("</ul>")
    return "\n".join(body).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "bgtracker-tips/1.0"
    limiter = Limiter(RATE)

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass   # quiet; the reverse proxy logs requests

    @property
    def ip(self):
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def _route(self):
        parts = urllib.parse.urlsplit(self.path)
        return parts.path.rstrip("/") or "/", urllib.parse.parse_qs(parts.query)

    def _body(self):
        """The request body as a dict, from JSON or from a plain HTML form."""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError(f"body must be 1..{MAX_BODY} bytes")
        raw = self.rfile.read(length)
        if "form-urlencoded" in (self.headers.get("Content-Type") or ""):
            return {k: v[0] for k, v
                    in urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
        try:
            out = json.loads(raw)
        except Exception:
            raise ValueError("body is not valid JSON")
        if not isinstance(out, dict):
            raise ValueError("body is not an object")
        return out

    def do_GET(self):
        path, q = self._route()
        if not self.limiter.ok(self.ip):
            return self._send(429, {"ok": False, "error": "rate limited"})
        hero = (q.get("hero") or [None])[0]
        if hero is not None and not HERO_RE.match(hero):
            return self._send(400, {"ok": False, "error": "hero malformed"})
        try:
            if path == "/tips/health":
                with db() as c:
                    n = c.execute("SELECT COUNT(*) FROM tips").fetchone()[0]
                    sh = c.execute("SELECT COUNT(*) FROM tips WHERE shipped=1").fetchone()[0]
                    v = c.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
                    w = len(winners(c))
                return self._send(200, {"ok": True, "tips": n, "shipped": sh,
                                        "votes": v, "published": w})
            if path == "/tips/page":
                with db() as c:
                    return self._send(200, page(c, hero), "text/html; charset=utf-8")
            if path == "/tips":
                if not hero:
                    return self._send(400, {"ok": False, "error": "hero required"})
                with db() as c:
                    return self._send(200, {"ok": True, "tips": scores(c, hero)})
        except Exception as e:
            return self._send(500, {"ok": False, "error": str(e)})
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path, _ = self._route()
        if not self.limiter.ok(self.ip):
            return self._send(429, {"ok": False, "error": "rate limited"})
        if TOKEN and self.headers.get("X-Upload-Token") != TOKEN:
            return self._send(401, {"ok": False, "error": "bad or missing token"})
        try:
            rec = self._body()
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        if path == "/tips/submit":
            return self._submit(rec)
        if path == "/tips/vote":
            return self._vote(rec)
        self._send(404, {"ok": False, "error": "not found"})

    def _submit(self, rec):
        try:
            v = validate_tip(rec)
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        who = voter_key(self.ip, rec.get("client"))
        now = int(time.time())
        try:
            with db() as c:
                made = c.execute("SELECT COUNT(*) FROM tips WHERE author = ? AND ts > ?",
                                 (who, now - 86400)).fetchone()[0]
                if made >= SUBMIT_CAP:
                    return self._send(429, {"ok": False,
                                            "error": f"at most {SUBMIT_CAP} tips a day"})
                cur = c.execute(
                    "INSERT OR IGNORE INTO tips (id, hero, txt, bullets, name, shipped, ts, author)"
                    " VALUES (?,?,?,?,?,0,?,?)",
                    (v["id"], v["hero"], v["txt"], v["bullets"], v["name"], now, who))
                stored = cur.rowcount
                # The submitter's own vote, and only ever one: whoever writes a
                # line endorses it, and without this a brand new tip starts at
                # zero and cannot be told from one voted down to zero. It is an
                # ordinary vote, so every floor still applies to it.
                c.execute("INSERT OR IGNORE INTO votes (tip, voter, value, ts)"
                          " VALUES (?,?,1,?)", (v["id"], who, now))
                c.commit()
        except Exception as e:
            return self._send(500, {"ok": False, "error": f"store failed: {e}"})
        self._send(200, {"ok": True, "id": v["id"], "stored": bool(stored)})

    def _vote(self, rec):
        tid = rec.get("id")
        if not isinstance(tid, str) or not ID_RE.match(tid):
            return self._send(400, {"ok": False, "error": "id missing or malformed"})
        try:
            value = int(rec.get("value"))
        except (TypeError, ValueError):
            value = 0
        if value not in (1, -1):
            return self._send(400, {"ok": False, "error": "value must be 1 or -1"})
        who = voter_key(self.ip, rec.get("client"))
        try:
            with db() as c:
                if not c.execute("SELECT 1 FROM tips WHERE id = ?", (tid,)).fetchone():
                    return self._send(404, {"ok": False, "error": "no such tip"})
                # Replaces, never accumulates: the primary key is (tip, voter),
                # so asking a thousand times leaves exactly one row.
                c.execute("INSERT INTO votes (tip, voter, value, ts) VALUES (?,?,?,?)"
                          " ON CONFLICT(tip, voter) DO UPDATE SET value=excluded.value,"
                          " ts=excluded.ts", (tid, who, value, int(time.time())))
                c.commit()
                score, voters = c.execute(
                    "SELECT COALESCE(SUM(value),0), COUNT(*) FROM votes WHERE tip = ?",
                    (tid,)).fetchone()
        except Exception as e:
            return self._send(500, {"ok": False, "error": f"store failed: {e}"})
        if "form-urlencoded" in (self.headers.get("Content-Type") or ""):
            # Came from the page: send the browser back to it rather than
            # showing a person a wall of JSON.
            self.send_response(303)
            self.send_header("Location", "/tips/page")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(200, {"ok": True, "id": tid, "score": score, "voters": voters})


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        c.commit()
    if "--seed" in argv:
        path = argv[argv.index("--seed") + 1]
        with db() as c:
            print(f"seeded {seed(c, path)} shipped tip(s) from {path}")
        return 0
    if "--publish" in argv:
        with db() as c:
            doc = publish(c)
        print(f"wrote {OUT / 'hero-tips-community.json'}: "
              f"{len(doc['tips'])} hero(es) with a clear winner")
        return 0
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"bgtracker tips on http://{BIND}:{PORT}  db={DB_PATH}  "
          f"token={'on' if TOKEN else 'off'}  rate={RATE}/min")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
