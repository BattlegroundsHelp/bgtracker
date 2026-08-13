#!/usr/bin/env python3
"""Where the Hearthstone logs are looked for, and who gets to decide.

    python tests/test_logsdir.py

Asked for twice in the same week, from both sides of the same wall: the first
outside contributor filed issue #1 (a settings key for a custom install), and
the first beta tester lost an evening to "waiting for game" because their
install was not at the default path and nothing on screen said which folder
was being watched.

The precedence under test: an explicit `hs_logs` in settings.json wins, the
registry's InstallLocation is the zero-configuration fallback, the historical
default is last. The registry leg is not tested here - it reads real machine
state a test cannot own - but the settings leg and the normalization are pure
logic and are pinned exactly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bgtracker as bg  # noqa: E402
import settings  # noqa: E402


class _Fake:
    def __init__(self, d):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


def resolve(hs_logs):
    """bg._hs_logs_dir() with the settings store answering from a dict."""
    real = settings.Settings.load
    settings.Settings.load = staticmethod(lambda: _Fake({"hs_logs": hs_logs}))
    try:
        return bg._hs_logs_dir()
    finally:
        settings.Settings.load = real


def main() -> int:
    ok = True

    # 1. Nothing configured: settings must not decide. The registry or the
    #    default answers, and either way it is somebody's Logs folder.
    got = resolve("")
    print(f"empty setting        -> {got}")
    if got.name.lower() != "logs":
        print("    FAIL: did not resolve to a Logs folder")
        ok = False

    # 2. The install folder is accepted and normalized to its Logs child,
    #    because "where is Hearthstone" is the question a user can answer.
    got = resolve(r"D:\Games\Hearthstone")
    print(f"install folder       -> {got}")
    if got != Path(r"D:\Games\Hearthstone\Logs"):
        print("    FAIL: install folder was not normalized to Logs")
        ok = False

    # 3. A path that already names Logs is taken as it is.
    got = resolve(r"D:\Games\Hearthstone\Logs")
    print(f"logs folder          -> {got}")
    if got != Path(r"D:\Games\Hearthstone\Logs"):
        print("    FAIL: an explicit Logs path was rewritten")
        ok = False

    # 4. Environment variables expand, so one settings.json can travel
    #    between machines with different user names.
    os.environ["BGT_TEST_ROOT"] = r"D:\Elsewhere"
    got = resolve(r"%BGT_TEST_ROOT%\Hearthstone")
    print(f"env expansion        -> {got}")
    if got != Path(r"D:\Elsewhere\Hearthstone\Logs"):
        print("    FAIL: environment variables were not expanded")
        ok = False

    # 5. A configured-but-wrong path is KEPT, not silently replaced by a
    #    guess: the status line and --diag are where the user learns it is
    #    missing. Watching a different folder than the one they named is the
    #    harder bug to see.
    got = resolve(r"Q:\does\not\exist")
    print(f"wrong-but-explicit   -> {got}")
    if got != Path(r"Q:\does\not\exist\Logs"):
        print("    FAIL: an explicit path was second-guessed")
        ok = False

    # 6. The resolver must never raise: the overlay failing to START over a
    #    broken settings store is worse than watching the default folder.
    real = settings.Settings.load
    settings.Settings.load = staticmethod(
        lambda: (_ for _ in ()).throw(RuntimeError))
    try:
        got = bg._hs_logs_dir()
        print(f"broken settings      -> {got}")
        if got.name.lower() != "logs":
            print("    FAIL: broken settings produced a non-Logs answer")
            ok = False
    finally:
        settings.Settings.load = real

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
