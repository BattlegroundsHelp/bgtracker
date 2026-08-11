"""Where the app's files live - running from source, or as a frozen build.

Two different questions, and getting them the wrong way round is the classic
PyInstaller failure:

``app_dir()``    where the app WRITES and where the USER's files are: the
                 cache, saved window positions (.overlay.json), collected
                 games (data/), downloaded card art (assets/), sources.json.
                 Running from source that is the repo folder. Frozen, it is the
                 folder holding bgtracker.exe - NOT the bundle, so the user can
                 see, edit and delete these files, and so they survive
                 re-extracting the zip over the top.

``bundle_dir()`` where the app's own CODE and read-only bundled data live.
                 Running from source that is the repo folder again. Frozen it
                 is PyInstaller's private extraction folder (sys._MEIPASS,
                 `_internal` beside the exe in a one-folder build), which is
                 replaced wholesale on every update and must never be written
                 to.

``Path(__file__).parent`` answers the SECOND question in a frozen build while
reading like it answers the first, which is how a working app turns into one
that writes its cache into a folder the user never sees - or, from a temp
extraction, loses it on every launch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def frozen() -> bool:
    """True when running inside a PyInstaller build."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def app_dir() -> Path:
    """The folder the app treats as its own: writable, user visible."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return _HERE


def bundle_dir() -> Path:
    """The folder the app's code was loaded from: read only when frozen."""
    if frozen():
        return Path(sys._MEIPASS).resolve()
    return _HERE


APP_DIR = app_dir()
BUNDLE_DIR = bundle_dir()
