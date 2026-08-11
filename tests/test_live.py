"""
Verifies the LIVE path (follow + rotate), not just replay.

Points bgtracker at a fake Hearthstone Logs dir through settings.json, starts the follower in a
thread, then appends the real hero-select lines from sample_heroselect.log to
simulate a game happening. Also drops a NEWER session dir mid-run to prove the
rotation branch works.

Needs the network once (fetches the card database for recognition, cached a
day). Stats tables load only if you configured sources.json - the test passes
either way. For the offline check CI runs, see test_regression.py.
"""
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bgtracker

TMP = Path(__file__).parent / ".livetest"
S1 = TMP / "Hearthstone_2026_01_01_00_00_00"
S2 = TMP / "Hearthstone_2026_01_01_00_00_01"
for d in (S1, S2):
    d.mkdir(parents=True, exist_ok=True)
    (d / "Power.log").unlink(missing_ok=True)
(S1 / "Power.log").write_text("warmup\n", encoding="utf-8")
SETTINGS = TMP / "settings.json"
SETTINGS.write_text(json.dumps({"hearthstone_logs_dir": "."}), encoding="utf-8")
bgtracker.configure_log_path(SETTINGS)

heroes = bgtracker.hero_table("100", "last-patch")     # {} unless sources.json is set
det = bgtracker.OfferDetector(heroes, bgtracker.trinket_universe(),
                              bgtracker.hero_universe())

hits = []


def reader():
    for line in bgtracker.follow(S1 / "Power.log"):
        ev = det.flush() if line is None else det.feed(line)
        if ev:
            hits.append(ev)
            bgtracker.render(ev[0], ev[1], heroes, "100", "last-patch")


threading.Thread(target=reader, daemon=True).start()
time.sleep(1.0)

lines = (Path(__file__).parent / "sample_heroselect.log").read_text(
    encoding="utf-8", errors="ignore").splitlines(keepends=True)

print(">>> simulating a game: appending hero-select lines to the watched file")
with open(S1 / "Power.log", "a", encoding="utf-8") as f:
    for ln in lines:
        f.write(ln)
        f.flush()
time.sleep(1.5)

print(">>> simulating Hearthstone restart: newer session dir appears")
with open(S2 / "Power.log", "w", encoding="utf-8") as f:
    f.write("new session\n")
time.sleep(1.5)
# A real second game re-uses the same entity ids but has LATER timestamps.
# Replaying byte-identical lines would be an impossible input, so shift the clock.
game2 = [ln.replace("D 13:2", "D 14:2").replace("D 13:3", "D 14:3") for ln in lines]
with open(S2 / "Power.log", "a", encoding="utf-8") as f:
    for ln in game2:
        f.write(ln)
        f.flush()
time.sleep(2.0)

# The trailing offer only flushes when a later timestamp arrives, so nudge it.
ev = det.flush()
if ev:
    hits.append(ev)
    bgtracker.render(ev[0], ev[1], heroes, "100", "last-patch")

print(f"\nRESULT: {len(hits)} offer(s) detected live (expected >=2: one per session)")
print("PASS" if len(hits) >= 2 else "FAIL")
sys.exit(0 if len(hits) >= 2 else 1)
