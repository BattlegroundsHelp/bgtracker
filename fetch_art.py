#!/usr/bin/env python3
"""
Download card art from the HearthstoneJSON CDN into assets/, so the overlay can
show real portraits instead of colored dots.

Two forms per card, both public and unauthenticated:
  tiles/<id>.png   ~21 KB  the horizontal name-bar art strip (good for list rows)
  256x/<id>.jpg    ~13 KB  a square-ish art crop            (good for badges)

Run once; it skips anything already on disk, so re-runs only fetch new cards.

    python fetch_art.py               # minions (default)
    python fetch_art.py --all         # minions + trinkets
    python fetch_art.py --everything  # the whole Battlegrounds universe:
                                      # heroes, hero powers, buddies, spells,
                                      # trinkets, dark gifts, anomalies, and
                                      # the named enchantments counters point
                                      # at ("Eastern Winds"). Art that does
                                      # not exist for an id just counts as a
                                      # miss; nothing breaks.
"""

import argparse
import concurrent.futures as cf
import urllib.request

import bgtracker as bg
from paths import APP_DIR

CDN = "https://art.hearthstonejson.com/v1"
# Beside the exe when frozen (see paths.py), so the overlay finds the art this
# just downloaded and an update does not wipe it.
ASSETS = APP_DIR / "assets"

# UI chrome the rows wear, from Hearthstone Deck Tracker's own MIT-licensed
# resources - the same deck-list gem the reference overlay draws. Fetched at
# runtime like the card art, never committed.
UI_ASSETS = {
    "gem.png": ("https://raw.githubusercontent.com/HearthSim/"
                "Hearthstone-Deck-Tracker/master/"
                "Hearthstone%20Deck%20Tracker/Images/Themes/Bars/"
                "classic/gem.png"),
}


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
    ap.add_argument("--everything", action="store_true",
                    help="every Battlegrounds card id there is")
    args = ap.parse_args()

    cards = bg.card_table("100", "last-patch")
    tiers = bg.card_tiers()
    ids = [cid for cid in cards if tiers.get(cid, 0) >= 1]   # real minions
    if args.all or args.everything:
        ids += list(bg.trinket_table("last-patch", "100").keys())
    if args.everything:
        # The whole universe, from the same cards.json the name map caches:
        # the id prefixes are the Battlegrounds sets (BG heroes and minions
        # across seasons, TB_BaconShop tokens and hero powers, BGS_ heroes).
        # This is what puts real art on every surface - the offer rows, the
        # session's hero list, the counter pills' sources - instead of only
        # the browsable pool.
        ids += [cid for cid in bg.card_names()
                if cid.startswith(("BG", "TB_Bacon", "BGS_"))]
    ids = sorted(set(ids))

    # The UI chrome first: one tiny file per asset, skipped when present.
    ui_dir = ASSETS / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    for name, url in UI_ASSETS.items():
        out = ui_dir / name
        if out.exists() and out.stat().st_size > 0:
            continue
        try:
            req = urllib.request.Request(url,
                                         headers={"User-Agent": "bgtracker/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out.write_bytes(r.read())
            print(f"ui: {name} fetched")
        except Exception as e:
            print(f"ui: {name} unavailable ({e}) - the drawn fallback stays")

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
