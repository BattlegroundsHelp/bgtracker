#!/usr/bin/env python3
"""Write the update manifest from a built zip. Nothing here is typed by hand.

    python server/make_manifest.py dist/bgtracker-win64-2026-08-12.zip \
        --url https://github.com/BattlegroundsHelp/bgtracker/releases/download/v0.3.0-alpha/bgtracker-windows.zip

The sha256 and the size are computed from the file on disk, because those two
numbers are the only thing standing between a user and running whatever a
tampered download served them. A hash pasted from a terminal into a JSON file
is a hash nobody checked.

The version is read out of the zip's own `version.txt`, which build.py writes
from version.py. That closes a gap that would otherwise open on every release:
a manifest saying 0.3.0 next to a zip built before the bump ships an update
that every client installs and then still reports the old version, so it gets
offered again on the next start, forever.

The output goes to server/out/update.json, the folder the web server already
publishes (deploy/nginx-bgtracker.conf, root /opt/bgtracker/server/out). Putting
it on the box is one scp - see "Ship a release" in server/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "server" / "out" / "update.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def version_in_zip(path: Path) -> str | None:
    """The version.txt build.py drops in the build folder, wherever the zip
    holds it. None for a zip built before build.py wrote one."""
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.replace("\\", "/").rsplit("/", 1)[-1] == "version.txt":
                return z.read(name).decode("utf-8").strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="write the update manifest for a built zip")
    ap.add_argument("zip", type=Path, help="the release zip, exactly as uploaded")
    ap.add_argument("--url", required=True,
                    help="where that zip can be downloaded (https, the Releases asset)")
    ap.add_argument("--version", help="only needed for a zip with no version.txt")
    ap.add_argument("--notes", help="link to the patch notes (default: the release page)")
    ap.add_argument("--published", default=date.today().isoformat(),
                    help="YYYY-MM-DD, default today")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()

    if not a.zip.is_file():
        sys.exit(f"no such file: {a.zip}")
    # The client refuses a non-https download url, so refuse to publish one:
    # better to fail here than to ship a manifest every client rejects.
    if not a.url.lower().startswith("https://"):
        sys.exit(f"the download url must be https, got: {a.url}")

    in_zip = version_in_zip(a.zip)
    if in_zip and a.version and in_zip != a.version:
        sys.exit(f"the zip says version {in_zip} but you passed {a.version}. "
                 f"Build the release from the commit that bumped version.py.")
    version = in_zip or a.version
    if not version:
        sys.exit("this zip has no version.txt (built before build.py wrote one) - "
                 "pass --version, and be sure it really is that build")

    notes = a.notes
    if not notes:
        # The release page for the matching tag, worked out from the asset url,
        # which is always .../releases/download/<tag>/<file>.
        parts = a.url.split("/releases/download/")
        notes = (parts[0] + "/releases/tag/" + parts[1].split("/")[0]
                 if len(parts) == 2 else a.url)
    # Clients refuse a non-https notes link (it reaches the OS URL opener on
    # a click, over a manifest that travels plain HTTP), so refuse to publish
    # one - same rule as the download url above.
    if not notes.lower().startswith("https://"):
        sys.exit(f"the notes url must be https, got: {notes}")

    doc = {
        "schema": 1,
        "version": version,
        "url": a.url,
        "sha256": sha256_of(a.zip),
        "size": a.zip.stat().st_size,
        "published": a.published,
        "notes": notes,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(doc, indent=2))
    print(f"\nwritten to {a.out}  ({a.out.stat().st_size} bytes)")
    print("check it before shipping:  python update.py --url file:///"
          + str(a.out).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
