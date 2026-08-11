#!/usr/bin/env python3
"""
Download card art from the HearthstoneJSON CDN into assets/, so the overlay can
show real portraits instead of colored dots.

Two forms per card, both public and unauthenticated:
  tiles/<id>.png   ~21 KB  the horizontal name-bar art strip (good for list rows)
  256x/<id>.jpg    ~13 KB  a square-ish art crop            (good for badges)

Run once; it skips anything already on disk, so re-runs only fetch new cards.

    python fetch_art.py            # minions (default)
    python fetch_art.py --all      # minions + trinkets
"""

import argparse
import concurrent.futures as cf
import urllib.request
from pathlib import Path

import bgtracker as bg

CDN = "https://art.hearthstonejson.com/v1"
ASSETS = Path(__file__).parent / "assets"


def one(card_id: str, kind: str) -> str:
    """kind: 'tiles' (png bar) or 'crops' (jpg square). Returns a status token."""
    ext = "png" if kind == "tiles" else "jpg"
    out = ASSETS / kind / f"{card_id}.{ext}"
    if out.exists() and out.stat().st_size > 0:
        return "skip"
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{CDN}/tiles/{card_id}.png" if kind == "tiles" \
        else f"{CDN}/256x/{card_id}.jpg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bgtracker/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 200:          # a 404 body, not an image
            return "miss"
        out.write_bytes(data)
        return "ok"
    except Exception:
        return "miss"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="also fetch trinkets")
    args = ap.parse_args()

    cards = bg.card_table("100", "last-patch")
    tiers = bg.card_tiers()
    ids = [cid for cid in cards if tiers.get(cid, 0) >= 1]   # real minions
    if args.all:
        ids += list(bg.trinket_table("last-patch", "100").keys())
    ids = sorted(set(ids))

    print(f"fetching art for {len(ids)} cards into {ASSETS} ...")
    counts = {"ok": 0, "skip": 0, "miss": 0}
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futs = []
        for cid in ids:
            futs.append(ex.submit(one, cid, "tiles"))
            futs.append(ex.submit(one, cid, "crops"))
        done = 0
        for f in cf.as_completed(futs):
            counts[f.result()] += 1
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(futs)}  {counts}", flush=True)
    print(f"done: {counts}")
    print(f"tiles: {len(list((ASSETS/'tiles').glob('*.png')))} | "
          f"crops: {len(list((ASSETS/'crops').glob('*.jpg')))}")


if __name__ == "__main__":
    main()
