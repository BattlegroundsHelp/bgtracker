# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: a standalone Windows build that needs no Python.

    pip install pyinstaller
    python build.py                 # or: pyinstaller bgtracker.spec --noconfirm

Produces ONE FOLDER, dist/bgtracker/, holding four programs that share one
runtime, with everything the tool writes at runtime landing beside them:

    bgtracker.exe        the overlay              (overlay.py)
    bgtracker-cli.exe    the text version         (bgtracker.py)
    collect.exe          grow your own numbers    (collect.py)
    fetch-art.exe        download card art        (fetch_art.py)

Three decisions worth keeping:

ONE FOLDER, NOT ONE FILE. A --onefile exe unpacks the whole runtime into a temp
folder on every launch (slower start, and the folder the app runs from is a
throwaway), and it is the shape antivirus heuristics flag hardest. A folder in
a zip costs the user one extra "Extract All".

ui/ AND sim/ ARE COLLECTED WHOLE. ui/__init__.py imports its windows by name
today, but a registry is exactly the thing that grows a dynamic import later,
and the failure mode of one missed window module is silent: the overlay starts
and shows nothing. collect_submodules pins every module in both packages
whether or not the import graph reaches it. `bgtracker.exe --diag` prints what
actually loaded, so the claim is checkable rather than assumed.

NO native/msync. The memory reader stays an opt-in source build (docs/USAGE.md
section 5). The overlay picks it up beside the exe if the user ever builds it.
"""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 - injected by PyInstaller

# Both packages, every module, regardless of what the import graph reaches.
HIDDEN = (
    collect_submodules("ui")
    + collect_submodules("sim")
    + [
        "tkinter", "tkinter.font", "tkinter.ttk",
        "paths", "bgtracker", "collect",        # ui.session imports collect
    ]
)

# Pillow is optional at runtime (ui/base.py degrades to colored dots when it is
# missing, and to dots again when the art files are absent), but if it is
# installed here, ship it so card art works out of the box.
try:
    import PIL  # noqa: F401
    HIDDEN += ["PIL", "PIL.Image", "PIL.ImageTk"]
except ImportError:
    pass

# server/aggregate.py is CODE, imported by `collect --local-feed` off
# BUNDLE_DIR/server (see paths.py). Shipping it as data keeps it importable
# from that path inside the bundle.
DATAS = [(os.path.join(ROOT, "server", "aggregate.py"), "server")]

# The community hero tips are written text, not collected stats, so unlike
# every stats table they DO ship inside the build. bgtracker.hero_tips() reads
# APP_DIR/data first and BUNDLE_DIR/data second, so a user's own edited copy
# beside the exe wins and survives an update.
DATAS.append((os.path.join(ROOT, "data", "hero_tips.json"), "data"))

# The comp roles are the same kind of shipped text (bgtracker.comp_roles reads
# the same APP_DIR-then-BUNDLE_DIR pair). Without this line the comps window's
# CORE / ADD-ONS split is dead in the standalone build with no error anywhere:
# a missing roles file just means "no roles", by design.
DATAS.append((os.path.join(ROOT, "data", "comp_roles.json"), "data"))

# Every file promised above must exist NOW, by its exact name. The failure
# mode this catches is a rename or a fresh checkout missing a data file: the
# feature that reads it degrades silently at runtime (that is its offline
# behavior), so the only place the absence can be loud is the build.
for _src, _dest in DATAS:
    if not os.path.isfile(_src):
        raise SystemExit(f"bgtracker.spec: bundled data file missing: {_src}")

EXCLUDES = [
    "numpy", "scipy", "pandas", "matplotlib", "IPython", "pytest",
    "setuptools", "pip", "PyInstaller",
]


def analyze(script):
    return Analysis(  # noqa: F821
        [os.path.join(ROOT, script)],
        pathex=[ROOT],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
        optimize=0,
    )


def program(analysis, name, console=True):
    pyz = PYZ(analysis.pure)  # noqa: F821
    return EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        # UPX off on purpose: packed sections are the single biggest antivirus
        # false-positive trigger for unsigned PyInstaller output.
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


a_overlay = analyze("overlay.py")
a_cli = analyze("bgtracker.py")
a_collect = analyze("collect.py")
a_art = analyze("fetch_art.py")

# console=True for the overlay too: the troubleshooting guide, the bug-report
# instructions and the `hb` heartbeat all assume a console you can read. The
# shipped bgtracker.bat starts it minimised, exactly as the source launcher does.
e_overlay = program(a_overlay, "bgtracker")
e_cli = program(a_cli, "bgtracker-cli")
e_collect = program(a_collect, "collect")
e_art = program(a_art, "fetch-art")

coll = COLLECT(  # noqa: F821
    e_overlay, a_overlay.binaries, a_overlay.datas,
    e_cli, a_cli.binaries, a_cli.datas,
    e_collect, a_collect.binaries, a_collect.datas,
    e_art, a_art.binaries, a_art.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="bgtracker",
)
