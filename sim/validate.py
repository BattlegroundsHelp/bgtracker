"""Validate the combat sim (sim/engine.py) against real fights (sim/boards.py).

Scans Power.logs, extracts every combat whose BOTH pre-fight boards were fully
recovered AND whose outcome is known (boards.py flags.complete), simulates each
with engine.simulate(), and scores the prediction against what actually
happened in the game.

Metrics reported:
- combats_usable: fights scored (complete boards + known outcome only).
- winner_accuracy_pct: how often argmax(win/tie/loss) == the real outcome.
- mean_abs_error_pct: mean |p - empirical| where p = win + tie/2 (the
  predicted probability-of-not-losing credit, standard expected score) and
  empirical is 1.0 win / 0.5 tie / 0.0 loss. This is the calibration miss.
- reliability: deciles of predicted p vs the empirical mean in each bucket.
- confusion: predicted vs actual outcome counts.
- worst_misses: the K fights with the largest |p - empirical|, with both
  boards' cardIds - the shortlist of card scripts to write next.
- worst_cards / highest_error_cards_overall: cardIds aggregated from the
  misses, flagged with whether a (manual or derived) script already exists.

Usage:
    python sim/validate.py                       scan all Hearthstone_*/Power.log
    python sim/validate.py <log|dir> [...]       score specific logs
    options: [--n 1000] [--min-round N] [--seed 1] [--worst 5] [--indent]

Honesty rules: only flags.complete combats are scored; nothing is guessed.
If too few usable combats exist, the numbers say so - they are never padded.
Note: each game's FINAL fight is not finalized by the parser (the log ends
before the combat-over marker), so counts trail the true fight count slightly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import boards  # noqa: E402
import engine  # noqa: E402

HS_LOGS = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Hearthstone"
    / "Logs"
)

EMPIRICAL = {"us": 1.0, "tie": 0.5, "them": 0.0}


def discover_logs(args_paths: list[str]) -> list[Path]:
    """Explicit files/dirs if given, else every Hearthstone_*/Power.log."""
    if not args_paths:
        return sorted(HS_LOGS.glob("Hearthstone_*/Power.log"))
    out: list[Path] = []
    for a in args_paths:
        p = Path(a)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            direct = p / "Power.log"
            if direct.is_file():
                out.append(direct)
            else:
                out.extend(sorted(p.glob("Hearthstone_*/Power.log")))
        else:
            out.extend(sorted(Path().glob(a)))
    return out


def score_combats(
    logs: list[Path], n: int, min_round: int, seed: int
) -> tuple[list[dict], dict]:
    """Parse every log, simulate every usable combat, return per-combat rows
    plus parse bookkeeping (games / parsed / skipped counts)."""
    rows: list[dict] = []
    meta = {"logs": [], "games": 0, "combats_parsed": 0, "skipped_incomplete": 0}
    idx = 0
    for lp in logs:
        print(f"parsing {lp} ...", file=sys.stderr, flush=True)
        res = boards.parse_log(str(lp))
        usable = 0
        for c in res["combats"]:
            meta["combats_parsed"] += 1
            if c["round"] < min_round or not c["flags"].get("complete"):
                meta["skipped_incomplete"] += 1
                continue
            b = c["boards_pre_attack"]
            r = engine.simulate(b["friendly"], b["enemy"], n=n, seed=seed + idx)
            idx += 1
            usable += 1
            pred = max(
                (("us", r["win"]), ("them", r["loss"]), ("tie", r["tie"])),
                key=lambda kv: kv[1],
            )[0]
            actual = c["outcome"]["winner"]
            p = r["win"] + 0.5 * r["tie"]
            rows.append(
                {
                    "log": lp.parent.name,
                    "game": c["game"],
                    "round": c["round"],
                    "opponent_hero": c.get("opponent_hero"),
                    "win": r["win"],
                    "tie": r["tie"],
                    "loss": r["loss"],
                    "p": round(p, 4),
                    "pred": pred,
                    "actual": actual,
                    "abs_err": round(abs(p - EMPIRICAL[actual]), 4),
                    "friendly_cards": [m["cardId"] for m in b["friendly"]],
                    "enemy_cards": [m["cardId"] for m in b["enemy"]],
                }
            )
        meta["logs"].append({"log": str(lp), "games": res["games"], "usable": usable})
        meta["games"] += res["games"]
    return rows, meta


def reliability_table(rows: list[dict], buckets: int = 10) -> list[dict]:
    table = []
    for k in range(buckets):
        lo, hi = k / buckets, (k + 1) / buckets
        sel = [
            r
            for r in rows
            if lo <= r["p"] < hi or (k == buckets - 1 and r["p"] == 1.0)
        ]
        if not sel:
            continue
        table.append(
            {
                "bucket": f"{lo:.1f}-{hi:.1f}",
                "n": len(sel),
                "mean_pred": round(sum(r["p"] for r in sel) / len(sel), 3),
                "mean_actual": round(
                    sum(EMPIRICAL[r["actual"]] for r in sel) / len(sel), 3
                ),
            }
        )
    return table


def confusion(rows: list[dict]) -> dict:
    m: dict[str, dict[str, int]] = {}
    for r in rows:
        row = m.setdefault(f"actual_{r['actual']}", {})
        row[f"pred_{r['pred']}"] = row.get(f"pred_{r['pred']}", 0) + 1
    return m


def card_tables(
    rows: list[dict], worst: list[dict], registry: dict
) -> tuple[list, list]:
    """(worst_cards from the worst misses, global per-card error table)."""

    def has_script(cid: str) -> bool:
        return cid in registry or engine._strip_golden(cid) in registry

    # cards in the worst misses, ranked by how many misses they sit in
    agg: dict[str, dict] = {}
    for w in worst:
        for cid in set(w["friendly_cards"] + w["enemy_cards"]):
            a = agg.setdefault(cid, {"cardId": cid, "miss_combats": 0, "err_sum": 0.0})
            a["miss_combats"] += 1
            a["err_sum"] += w["abs_err"]
    worst_cards = sorted(
        agg.values(), key=lambda a: (-a["miss_combats"], -a["err_sum"])
    )
    for a in worst_cards:
        a["err_sum"] = round(a["err_sum"], 3)
        a["has_script"] = has_script(a["cardId"])

    # global: mean combat error when the card is present (n >= 3 to matter)
    g: dict[str, list[float]] = {}
    for r in rows:
        for cid in set(r["friendly_cards"] + r["enemy_cards"]):
            g.setdefault(cid, []).append(r["abs_err"])
    table = [
        {
            "cardId": cid,
            "combats": len(errs),
            "mean_abs_err": round(sum(errs) / len(errs), 3),
            "has_script": has_script(cid),
        }
        for cid, errs in g.items()
        if len(errs) >= 3
    ]
    table.sort(key=lambda x: -x["mean_abs_err"])
    return worst_cards, table[:20]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="*", help="Power.log files or Hearthstone dirs")
    ap.add_argument("--n", type=int, default=1000, help="rollouts per combat")
    ap.add_argument("--min-round", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--worst", type=int, default=5, help="worst misses to list")
    ap.add_argument("--indent", action="store_true")
    args = ap.parse_args(argv)

    logs = discover_logs(args.paths)
    if not logs:
        print(json.dumps({"error": f"no Power.log found (looked in {HS_LOGS})"}))
        return 1

    data = engine.load_scripts()
    registry = dict(data["scripts"])
    registry.update(engine.SCRIPTS)

    rows, meta = score_combats(logs, args.n, args.min_round, args.seed)
    nn = len(rows)
    correct = sum(1 for r in rows if r["pred"] == r["actual"])
    mae = sum(r["abs_err"] for r in rows) / nn if nn else None
    worst = sorted(rows, key=lambda r: -r["abs_err"])[: args.worst]
    worst_cards, err_table = card_tables(rows, worst, registry)

    doc = {
        "logs_scanned": len(logs),
        "games": meta["games"],
        "combats_parsed": meta["combats_parsed"],
        "combats_usable": nn,
        "skipped_incomplete": meta["skipped_incomplete"],
        "rollouts_per_combat": args.n,
        "min_round": args.min_round,
        "scripts_loaded": {
            "derived": len(data["scripts"]),
            "manual": len(engine.SCRIPTS),
            "tiers": len(data["tiers"]),
        },
        "winner_accuracy_pct": round(100.0 * correct / nn, 1) if nn else None,
        "predicted_correctly": correct,
        "mean_abs_error_pct": round(100.0 * mae, 1) if mae is not None else None,
        "error_definition": "p = win + tie/2 vs empirical 1.0 us / 0.5 tie / 0.0 them",
        "confusion": confusion(rows),
        "reliability": reliability_table(rows),
        "worst_misses": worst,
        "worst_cards": worst_cards,
        "highest_error_cards_overall": err_table,
        "per_log": meta["logs"],
    }
    print(json.dumps(doc, indent=2 if args.indent else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
