#!/usr/bin/env python3
"""Hero tips: the submission and voting pipeline, end to end and offline.

    python tests/test_tips.py

Everything runs against a throwaway database in a temp directory and a real
server on a loopback port. Nothing touches a live box and nothing leaves the
machine: the client half is pointed at the file the server just wrote.

What it pins down, in the order these things go wrong:
  * a submitted line obeys the same rules as the file that ships, so anything
    stored could be pasted into data/hero_tips.json unchanged;
  * the same line sent twice is ONE tip, and one machine voting a thousand
    times is ONE vote. That is the whole anti-abuse claim, in one assertion;
  * a tip only reaches the published feed once distinct voters, score, and a
    margin over the shipped line all clear their floor. A thin vote publishes
    NOTHING, which is the same rule the rest of the tool applies to numbers;
  * with no feed, an unreachable feed, or a corrupt one, the client shows the
    tips that ship. That is the degradation promise, tested four ways, because
    it is the one that must never fail.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

HERO = "BG26_HERO_102"
RIVAL = "You upgrade every turn and want the free stats to grow with you"
LONG = "x" * 81


def post(base, path, obj, ctype="application/json"):
    body = (json.dumps(obj) if ctype == "application/json" else obj).encode()
    req = urllib.request.Request(base + path, data=body,
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {}


def get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def rejects(fn, *a):
    """True when the validator refuses - the answer these tests care about."""
    try:
        fn(*a)
        return False
    except ValueError:
        return True


def main() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        print(f"  {'ok  ' if good else 'FAIL'} {label}: {got!r}"
              + ("" if good else f"   want {want!r}"))
        if not good:
            ok = False

    # ignore_cleanup_errors because SQLite on Windows keeps its WAL files open
    # a moment after the last connection drops, and a temp directory that will
    # not delete is not a test result.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        # Set before the import: the module reads its whole configuration off
        # the environment once, exactly like ingest.py.
        os.environ["BGTRACKER_TIPS_DB"] = str(tmp / "tips.db")
        os.environ["BGTRACKER_OUT"] = str(tmp / "out")
        os.environ["BGTRACKER_TIPS_SALT"] = "test-salt-not-a-real-one"
        os.environ["BGTRACKER_TIPS_VOTE_URL"] = "https://example.invalid/tips/page"
        # The functional tests fire more requests a minute than a person ever
        # would; the limiter itself is tested directly further down.
        os.environ["BGTRACKER_TIPS_RATE"] = "100000"
        import tips as T                                          # noqa: E402
        import bgtracker as bg                                    # noqa: E402

        with T.db() as c:
            c.executescript(T.SCHEMA)
            c.commit()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), T.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        print("\nvalidation - the same rules the shipped file obeys")
        check("a good line passes", T.clean_line("Mechs are in the lobby", 8, 80),
              "Mechs are in the lobby")
        check("too short rejected", rejects(T.clean_line, "short", 8, 80), True)
        check("too long rejected", rejects(T.clean_line, LONG, 8, 80), True)
        check("trailing full stop rejected",
              rejects(T.clean_line, "Mechs are in the lobby.", 8, 80), True)
        check("em dash rejected",
              rejects(T.clean_line, "Mechs are in — the lobby", 8, 80), True)
        check("link rejected",
              rejects(T.clean_line, "see https://example.invalid for more", 8, 80), True)
        check("control character rejected",
              rejects(T.clean_line, "Mechs are in\x07 the lobby", 8, 80), True)
        check("unknown hero rejected",
              rejects(T.validate_tip, {"hero": "NOT_A_HERO", "when": RIVAL}), True)
        check("four bullets rejected",
              rejects(T.validate_tip, {"hero": HERO, "when": RIVAL,
                                       "bullets": ["a bullet line"] * 4}), True)

        print("\nsubmission")
        code, r = post(base, "/tips/submit", {"hero": HERO, "when": RIVAL,
                                              "bullets": ["It grows as you climb"]})
        check("accepted", (code, r.get("stored")), (200, True))
        tid = r.get("id")
        code, r2 = post(base, "/tips/submit", {"hero": HERO, "when": RIVAL})
        check("same line again is the same tip", (r2.get("id"), r2.get("stored")),
              (tid, False))
        code, r3 = post(base, "/tips/submit", {"hero": HERO, "when": "short"})
        check("bad line refused", code, 400)
        code, health = get(base, "/tips/health")
        check("one tip stored", json.loads(health)["tips"], 1)

        print("\none machine, a thousand votes")
        for _ in range(1000):
            post(base, "/tips/vote", {"id": tid, "value": 1})
        code, r = post(base, "/tips/vote", {"id": tid, "value": 1})
        check("still one voter", (r.get("score"), r.get("voters")), (1, 1))
        code, r = post(base, "/tips/vote", {"id": tid, "value": -1})
        check("flipping replaces, never adds", (r.get("score"), r.get("voters")),
              (-1, 1))
        code, r = post(base, "/tips/vote", {"id": tid, "value": 7})
        check("only 1 and -1 are votes", code, 400)
        code, r = post(base, "/tips/vote", {"id": "0" * 32, "value": 1})
        check("voting on nothing is 404", code, 404)

        # Distinct client tags are distinct voters even from one address: that
        # is the only thing separating two people behind one router.
        for i in range(6):
            post(base, "/tips/vote", {"id": tid, "value": 1, "client": f"voter-{i}"})
        code, r = post(base, "/tips/vote", {"id": tid, "value": 1, "client": "voter-0"})
        check("six client tags, six voters plus this machine",
              (r.get("score"), r.get("voters")), (5, 7))

        print("\npublish floors")
        with T.db() as c:
            seeded = T.seed(c, ROOT / "data" / "hero_tips.json")
        check("shipped lines are on the ballot", seeded >= 121, True)
        with T.db() as c:
            doc = T.publish(c)
        check("the rival wins its hero", sorted(doc["tips"]), [HERO])
        check("and carries its vote count",
              (doc["tips"][HERO]["voters"], doc["tips"][HERO]["score"]), (7, 5))
        check("the page is named", doc.get("vote_url"),
              "https://example.invalid/tips/page")
        check("gzip twin written", (tmp / "out" / "hero-tips-community.json.gz").exists(),
              True)

        # Now vote the shipped line up so the margin is gone. Nothing publishes:
        # a close vote is not a mandate to replace a reviewed line.
        with T.db() as c:
            shipped_id = c.execute(
                "SELECT id FROM tips WHERE hero = ? AND shipped = 1", (HERO,)
            ).fetchone()[0]
        for i in range(4):
            post(base, "/tips/vote", {"id": shipped_id, "value": 1, "client": f"keep-{i}"})
        with T.db() as c:
            doc = T.publish(c)
        check("no margin, nothing published", doc["tips"], {})

        # Put it back, and check a thin vote (under the voter floor) publishes
        # nothing either.
        for i in range(4):
            post(base, "/tips/vote", {"id": shipped_id, "value": -1, "client": f"keep-{i}"})
        with T.db() as c:
            doc = T.publish(c)
        check("the winner is back", sorted(doc["tips"]), [HERO])
        code, r = post(base, "/tips/submit", {"hero": "BG22_HERO_201",
                                              "when": "A thin line nobody voted on"})
        with T.db() as c:
            doc = T.publish(c)
        check("one voter is not a result", "BG22_HERO_201" in doc["tips"], False)

        print("\nthe voting page")
        code, body = get(base, "/tips/page")
        html = body.decode()
        check("page renders", code, 200)
        check("it lists the rival", RIVAL in html, True)
        check("it says which line ships", "ships with the tool" in html, True)
        code, r = post(base, "/tips/submit",
                       {"hero": "BG23_HERO_304", "when": "<script>alert(1)</script> ok"})
        code, body = get(base, "/tips/page?hero=BG23_HERO_304")
        check("submitted markup is escaped", b"<script>" in body, False)
        check("and still readable", b"&lt;script&gt;" in body, True)

        print("\nthe limiter (its own thing: the functional tests run wide open)")
        lim = T.Limiter(2)
        check("first two pass", (lim.ok("1.2.3.4"), lim.ok("1.2.3.4")), (True, True))
        check("third is refused", lim.ok("1.2.3.4"), False)
        check("a different address is unaffected", lim.ok("5.6.7.8"), True)
        check("addresses narrow to a block", T.ip_block("203.0.113.77"), "203.0.113")
        check("and a key is not the address",
              T.voter_key("203.0.113.77", None) == T.voter_key("198.51.100.9", None),
              False)

        print("\nthe client reads it like any other feed")
        feed = tmp / "out" / "hero-tips-community.json"
        srcs = tmp / "sources.json"
        srcs.write_text(json.dumps({"hero_tips": str(feed)}), encoding="utf-8")
        bg.SOURCES_FILE = srcs
        bg._COMMUNITY_TIPS = None
        tip = bg.hero_tip(HERO)
        check("the voted line wins", (tip["when"], tip["source"]), (RIVAL, "community"))
        check("the page reaches the client", bg.tips_vote_url(),
              "https://example.invalid/tips/page")
        other = bg.hero_tip("TB_BaconShop_HERO_11")
        check("a hero with no winner still shows its shipped line",
              other["source"], "shipped")

        print("\ndegradation - four ways to have no feed")
        bg._COMMUNITY_TIPS = None
        srcs.write_text(json.dumps({"heroes": "whatever"}), encoding="utf-8")
        check("no hero_tips key: no voted tips", bg.community_tips(), {})
        check("shipped tip still shows", bg.hero_tip(HERO)["source"], "shipped")

        bg._COMMUNITY_TIPS = None
        srcs.write_text(json.dumps({"hero_tips": str(tmp / "gone.json")}), encoding="utf-8")
        check("missing file: no voted tips", bg.community_tips(), {})

        bg._COMMUNITY_TIPS = None
        broken = tmp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        srcs.write_text(json.dumps({"hero_tips": str(broken)}), encoding="utf-8")
        check("corrupt file: no voted tips", bg.community_tips(), {})
        check("and the shipped tip is untouched", bg.hero_tip(HERO)["source"], "shipped")

        bg._COMMUNITY_TIPS = None
        junk = tmp / "junk.json"
        junk.write_text(json.dumps({"tips": {
            HERO: {"when": "y" * 5000},
            "BG22_HERO_201": {"when": 17},
            "TB_BaconShop_HERO_11": {"when": "A perfectly ordinary voted line"},
        }}), encoding="utf-8")
        srcs.write_text(json.dumps({"hero_tips": str(junk)}), encoding="utf-8")
        got = bg.community_tips()
        check("a broken entry is dropped alone", sorted(got), ["TB_BaconShop_HERO_11"])

        # With no sources.json at all a fresh install reads the community host.
        # Checked as a STRING: this test never opens a socket to it.
        bg.SOURCES_FILE = tmp / "no-such-sources.json"
        check("a fresh install knows where to look",
              str(bg._community_tips_source()).endswith("/hero-tips-community.json"), True)

        srv.shutdown()
        srv.server_close()

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
