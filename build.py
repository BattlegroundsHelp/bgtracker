#!/usr/bin/env python3
"""Build the standalone Windows release - no Python needed to run it.

    pip install pyinstaller
    python build.py

Runs PyInstaller over bgtracker.spec (one folder, four programs), drops the
files a first-time user needs next to the exe, and zips the lot:

    dist/bgtracker/                  the build
    dist/bgtracker-win64-<date>.zip  what you hand a beta tester

The zip is the deliverable because the build is a FOLDER, not a single exe -
the reasoning is in bgtracker.spec. "Extract All", then double-click
bgtracker.bat.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "bgtracker"

# Everything a tester needs beside the exe. Runtime files (.cache, data,
# assets, .overlay.json, sources.json) are created on first use, in this same
# folder - that is what paths.py is for.
EXTRAS = [
    (ROOT / "LICENSE", "LICENSE"),
    (ROOT / "README.md", "README.md"),
    (ROOT / "ROADMAP.md", "ROADMAP.md"),
    (ROOT / "docs" / "USAGE.md", "USAGE.md"),
    (ROOT / "sources.example.json", "sources.example.json"),
]

LAUNCHER = """@echo off
REM Double-click to start the overlay. Keep Hearthstone in BORDERLESS WINDOWED.
REM Options pass straight through, e.g.:  bgtracker.bat --mmr 10 --time past-seven
cd /d "%~dp0"

REM Minimised console, same as running from source: it is where the tool prints
REM what it is doing, and the bug-report guide asks for those lines.
start /min "bgtracker" "%~dp0bgtracker.exe" %*
"""

READ_ME_FIRST = """bgtracker - standalone build (no Python needed)

1. Put Hearthstone in Options > Graphics > BORDERLESS WINDOWED.
2. Double-click bgtracker.exe. A console called "bgtracker" appears on the
   taskbar; that is where it prints what it is doing. Leave it alone.
   (bgtracker.bat runs the same thing with that console minimised.)
3. Quit with the small cross on the window titled "bgtracker", or close the
   console.

Keep this folder somewhere you can write to (Documents is fine, Program Files
is not): the tool writes its cache, your collected games, your saved window
positions and any card art right here beside the exe.

Other programs in this folder:

  bgtracker-cli.exe    the text version, no overlay (--replay, --comps, ...)
  collect.exe          turn your own finished games into your own stats
                       (run "collect.exe", then "collect.exe --local-feed")
  fetch-art.exe        download card portraits into assets\\ (optional)

  bgtracker.exe --diag prints what loaded and where it reads and writes.
                       Paste that into any bug report.

Windows SmartScreen may warn the first time: these exes are not code-signed (a
certificate costs money this free tool does not have). "More info" then "Run
anyway", or run it from source instead: the code is at
github.com/BattlegroundsHelp/bgtracker.

Full guide: USAGE.md. Not affiliated with Blizzard Entertainment.
"""


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode:
        sys.exit(f"FAILED ({r.returncode}): {' '.join(cmd)}")


def size_mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1e6
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zip", action="store_true", help="build only")
    args = ap.parse_args()

    if (ROOT / "build").exists():
        shutil.rmtree(ROOT / "build", ignore_errors=True)
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)

    run([sys.executable, "-m", "PyInstaller", "bgtracker.spec", "--noconfirm",
         "--log-level", "WARN"])

    if not (DIST / "bgtracker.exe").exists():
        sys.exit("no bgtracker.exe in dist - the build did not produce one")

    for src, name in EXTRAS:
        if src.exists():
            shutil.copy2(src, DIST / name)
    (DIST / "bgtracker.bat").write_text(LAUNCHER, encoding="utf-8")
    (DIST / "READ ME FIRST.txt").write_text(READ_ME_FIRST, encoding="utf-8")

    print(f"\nbuilt {DIST}  ({size_mb(DIST):.1f} MB, "
          f"{sum(1 for f in DIST.rglob('*') if f.is_file())} files)")

    if args.no_zip:
        return
    zpath = ROOT / "dist" / f"bgtracker-win64-{date.today().isoformat()}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, Path("bgtracker") / f.relative_to(DIST))
    print(f"zipped {zpath}  ({size_mb(zpath):.1f} MB)")
    print("\nHand over the zip: Extract All, then bgtracker.bat.")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
