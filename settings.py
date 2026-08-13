#!/usr/bin/env python3
"""The user's settings: one JSON file, one precedence rule, no surprises.

WHERE. ``settings.json`` in ``paths.app_dir()`` - the same folder as
``.overlay.json`` and ``sources.json``, i.e. beside the exe in a build and the
repo folder from source. Never inside the bundle: an update replaces that
folder wholesale, and the point of a setting is that it survives.

PRECEDENCE, stated once and obeyed everywhere:

    an explicit command-line flag  >  the saved file  >  the built-in default

and the flag wins FOR THAT RUN ONLY. A flag is never written back into the
file. That is not a detail - a tool that silently persists ``--duo`` teaches
the user that flags are permanent, and the next plain run then lies about what
it is showing. ``source_of(key)`` answers which of the three a value came from,
so a panel can say "set by --mmr for this run" instead of showing a control
that appears to do nothing.

WHAT IS NOT HERE. Two settings live where their owner already keeps them, and
duplicating them would create the two-sources-for-one-number bug the overlay's
window contract exists to prevent:

  * the update check on/off and the skipped version -> ``update.py``
    (``data/update.json``);
  * which stats feed the tables load from -> ``sources.json``, the file the
    user was always told to edit.

A MISSING FILE IS NORMAL. A CORRUPT ONE IS NOT FATAL. Either way every value
falls back to its default and ``problems`` says so in plain words, which the
panel shows and the console prints. Nothing here raises: a settings file is
not allowed to stop the overlay from starting. The file is only rewritten when
the user actually changes something, so a hand-edited file with one bad line
keeps its other lines until then.

Every value is validated on the way in. A value that is not in its choice list
or not the right type is dropped back to the default and named in
``problems``, because "the file said 200 so the scale is 200" is how a saved
setting turns into an unusable window with no way back.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from paths import app_dir

# The --mmr and --time values, in one place. overlay.py's argument parser is
# built from these very tuples and the settings panel offers exactly these, so
# the panel can never offer a value the command line would reject (and a new
# bracket is added once, not twice).
MMR_CHOICES = ("100", "50", "25", "10", "1")
TIME_CHOICES = ("all-time", "past-three", "past-seven", "last-patch")

# What each MMR bucket meant when it was last measured, and WHEN that was.
# Shown in the panel because "top 25%" means nothing without the rating behind
# it, and the rating means nothing without its date - the ladder inflates, so
# a figure with no date reads as a live reading, which it is not. Update both
# together. It is a property of whichever feed you point at, not a promise.
MMR_LABEL = {"100": "everyone", "50": "1901+", "25": "3277+",
             "10": "4812+", "1": "6728+"}
MMR_MEASURED = "2026-08-07"

# The community feed's ingest endpoint: the host sources.example.json already
# ships, which is also the box that serves the update manifest.
COMMUNITY_UPLOAD = "https://165-227-41-29.sslip.io"

SCALE_MIN, SCALE_MAX = 0.75, 3.0        # mirrors ui.base, without importing Tk
BADGE_MIN, BADGE_MAX = 0.5, 2.0

DEFAULTS = {
    # None means "work it out from the display" (ui.base.auto_scale). Stored as
    # null, not as the number auto happened to pick: someone who chose auto on a
    # 1080p laptop and plugs in a 4K screen wants 4K sizing, not a frozen 1.0.
    "ui_scale": None,
    "badge_scale": 1.0,
    "mmr": "100",
    "time": "last-patch",
    "duo": False,
    # ON by default (the author's call, 2026-08-12; it shipped opt-in before
    # that): everyone who plays feeds the community pool, and the off switch
    # is the panel's DATA box or --no-upload for one run. Nothing about the
    # upload is subtle: see the copy in ui/settings.py, which lists every
    # field collect.py actually sends, and pool.py, which does the sending.
    "upload": True,
    "upload_url": COMMUNITY_UPLOAD,
    "last_upload": None,          # epoch seconds of the last successful share
    "open_on_start": True,
    # key -> bool, from ui.WINDOWS. A key that is absent is ON: a window added
    # in a later version must appear for people who already have a settings
    # file, or new work would ship invisible to exactly the users who have been
    # here longest.
    "windows": {},
}


def settings_path() -> Path:
    return app_dir() / "settings.json"


def _num(v, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < lo or f > hi:      # f != f catches NaN, which compares False
        return None
    return f


def _clean(data: dict) -> tuple[dict, list[str]]:
    """Everything the file got right, plus a plain line for everything it did
    not. Unknown keys are kept untouched: a settings file written by a newer
    build must survive being read by an older one."""
    out, bad = {}, []
    for k, v in data.items():
        if k not in DEFAULTS:
            out[k] = v                  # not ours; leave it exactly as it was
            continue
        if k == "ui_scale":
            if v is None:
                out[k] = None
            else:
                n = _num(v, SCALE_MIN, SCALE_MAX)
                if n is None:
                    bad.append(f"ui_scale {v!r} is not a number between "
                               f"{SCALE_MIN} and {SCALE_MAX}")
                else:
                    out[k] = n
        elif k == "badge_scale":
            n = _num(v, BADGE_MIN, BADGE_MAX)
            if n is None:
                bad.append(f"badge_scale {v!r} is not a number between "
                           f"{BADGE_MIN} and {BADGE_MAX}")
            else:
                out[k] = n
        elif k == "mmr":
            if v in MMR_CHOICES:
                out[k] = v
            else:
                bad.append(f"mmr {v!r} is not one of {', '.join(MMR_CHOICES)}")
        elif k == "time":
            if v in TIME_CHOICES:
                out[k] = v
            else:
                bad.append(f"time {v!r} is not one of {', '.join(TIME_CHOICES)}")
        elif k in ("duo", "upload", "open_on_start"):
            if isinstance(v, bool):
                out[k] = v
            else:
                bad.append(f"{k} {v!r} is not true or false")
        elif k == "upload_url":
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
            else:
                bad.append(f"upload_url {v!r} is not a url")
        elif k == "last_upload":
            n = _num(v, 0, 4e18)
            out[k] = None if n is None else n
        elif k == "windows":
            if isinstance(v, dict):
                out[k] = {str(a): bool(b) for a, b in v.items()}
            else:
                bad.append(f"windows {v!r} is not a list of on/off switches")
    return out, bad


class Settings:
    """The saved file, the flags for this run, and which is which.

    ``get`` is the only reader. Nothing else in the app reaches into ``data``,
    so the precedence rule has exactly one implementation.
    """

    def __init__(self, path: Path | None = None, data: dict | None = None,
                 overrides: dict | None = None, problems: list[str] | None = None):
        self.path = Path(path) if path else settings_path()
        self.data = data or {}
        self.overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
        self.problems = list(problems or [])
        self.on_change = None       # set by the panel: called after every save

    # ------------------------------------------------------------- loading

    @classmethod
    def load(cls, path: Path | None = None, overrides: dict | None = None):
        p = Path(path) if path else settings_path()
        problems, data = [], {}
        if p.exists():
            raw = None
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                problems.append(f"{p.name} could not be read ({e}). Defaults are "
                                f"in use; saving here overwrites the file.")
            if raw is not None and not isinstance(raw, dict):
                problems.append(f"{p.name} is not a settings object "
                                f"({type(raw).__name__}). Defaults are in use.")
                raw = None
            if isinstance(raw, dict):
                data, bad = _clean(raw)
                problems += [b + " - using the default" for b in bad]
        return cls(p, data, overrides, problems)

    # ------------------------------------------------------------- reading

    def get(self, key):
        """The value in force: flag, then file, then built-in default."""
        if key in self.overrides:
            return self.overrides[key]
        if key in self.data:
            return self.data[key]
        return DEFAULTS[key]

    def source_of(self, key) -> str:
        """"flag" | "file" | "default" - where get(key) just came from."""
        if key in self.overrides:
            return "flag"
        if key in self.data:
            return "file"
        return "default"

    def window_enabled(self, key: str) -> bool:
        """Unknown window -> ON. See the note on DEFAULTS["windows"]."""
        return bool(self.get("windows").get(key, True))

    # ------------------------------------------------------------- writing

    def set(self, key, value):
        """Save one setting. A CLI override for the same key stays in force for
        this run - the file is what the NEXT run reads, and pretending
        otherwise would show the user a value the run is not using."""
        if key not in DEFAULTS:
            raise KeyError(key)
        self.data[key] = value
        self.save()

    def set_window_enabled(self, key: str, on: bool):
        wins = dict(self.get("windows"))
        wins[key] = bool(on)
        self.data["windows"] = wins
        self.save()

    def save(self) -> bool:
        """Write the file. Returns False and records the reason rather than
        raising: a read-only folder must not take the overlay down mid-game.

        Written to a temporary file in the same folder and renamed over the
        real one, because the alternative - truncating the live file and then
        writing - is how a crash at the wrong moment leaves a zero-byte
        settings file behind.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                       prefix=".settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, sort_keys=True)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception as e:
            self.problems.append(f"could not save {self.path.name}: {e}")
            return False
        if self.on_change is not None:
            try:
                self.on_change(self)
            except Exception:
                pass
        return True

    # --------------------------------------------------------- diagnostics

    def describe(self) -> list[str]:
        """One line per setting, with where it came from. --diag prints this."""
        out = []
        for k in DEFAULTS:
            if k == "windows":
                off = sorted(w for w, on in self.get(k).items() if not on)
                out.append("  windows      all on" if not off
                           else f"  windows      off: {', '.join(off)}")
                continue
            out.append(f"  {k:12} {self.get(k)!r}  ({self.source_of(k)})")
        return out


if __name__ == "__main__":
    s = Settings.load()
    print(f"settings file: {s.path} "
          f"({'present' if s.path.exists() else 'not written yet'})")
    print("\n".join(s.describe()))
    for p in s.problems:
        print(f"  ! {p}")
