#!/usr/bin/env python3
"""The update channel: a tiny manifest from the stats box, the bytes from GitHub.

WHY THE TWO HOSTS ARE SPLIT, because it is the whole point of the design:
the VPS serves the MANIFEST and nothing else. That is a static file of about
200 bytes, so every client in the world can ask "is there a new one?" on every
start and the $6 droplet that also runs the stats feed never notices. What it
must never serve is the build: a release zip is 28 MB, and one popular week
would be the whole month's bandwidth. So the manifest carries a plain `url`
field pointing at the GitHub Releases asset, which comes off GitHub's CDN for
free and is already where the download link in the README points. The field is
plain data on purpose: pointing it at the VPS, at a mirror, or anywhere else
later is a manifest edit, not a client release - which matters because the
clients that would need the change are exactly the ones that cannot be updated.

WHAT IT WILL NOT DO. It never installs anything on its own. The build is
unsigned and trips SmartScreen, so a surprise swap of the folder someone
downloaded by hand is precisely the wrong move: the check on start is a
2-second JSON fetch on a daemon thread, and downloading and installing happen
only when the user asks. `--no-update-check` (or `BGTRACKER_NO_UPDATE_CHECK=1`,
or the stored setting) turns even the check off.

WHAT IT REFUSES, and why the refusals are absolute:
  * a download url that is not https - the bytes are executable code, and
    plaintext means anyone on the path can choose which code you run;
  * a notes url that is not https - the "What changed" button opens it with
    the system opener, and on Windows that is os.startfile, which will run a
    UNC or file:/// path handed to it just as happily as it opens a web page;
  * a sha256 that does not match, or a size that does not match, both checked
    BEFORE anything is unpacked and before the running install is touched;
  * an archive member with an absolute path, a `..` in it, or a symlink;
  * an archive that expands past STAGE_RATIO (4x) the verified zip's own
    size - a compression bomb is a few hundred bytes to make, and the real
    build extracts to under 2x its zip;
  * running anything at all out of the archive except the app's own launcher,
    after the swap, by name.
Honest limit, stated because a sha256 looks stronger than it is: the hash only
proves the bytes are the ones the MANIFEST named. It is exactly as trustworthy
as the channel the manifest arrived over, and today that channel is plain HTTP
(the stats box has no certificate yet). Serving the manifest over https is what
closes that, and is the one thing worth doing before this is pointed at a large
number of people. Everything else here is defence in depth behind that.

The API the rest of the app uses:

    check()                  -> Update           (never raises, never blocks)
    start_check(callback)    -> Thread | None    (the on-start check)
    result()                 -> Update | None    (the last check's answer)
    download(update, progress=cb) -> Path        (verified zip, or raises)
    install(update, progress=cb)  -> int         (stages, hands off, returns
                                                  the helper pid; the app must
                                                  then quit)
    checks_enabled() / set_checks_enabled(bool)
    skipped_version() / skip_version(v) / clear_skip()
    problems()               -> list[str]        config this could not read,
                                                 in plain words, for the
                                                 settings panel's problems line

    python update.py --check        ask the real manifest, print what it says
    python update.py --selftest     the failure modes, offline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from paths import app_dir, frozen
from version import USER_AGENT, VERSION, is_newer, parse

# The stats box, at the bare address sources.example.json already ships. One
# more static file in the folder the web server already publishes as its root
# (server/deploy/nginx-bgtracker.conf: root /opt/bgtracker/server/out).
DEFAULT_MANIFEST_URL = "http://165.227.41.29/update.json"

MANIFEST_NAME = "update.json"

# A manifest is ~200 bytes and a release zip is ~28 MB. Both caps exist so a
# hostile or broken server cannot make the client read forever: the first stops
# a wifi login page being parsed as a manifest, the second stops a download
# filling the disk.
MAX_MANIFEST_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024

# The download caps how much lands on disk, but a verified zip can still be a
# compression bomb: a 0.31 MB archive expanded to 314 MB when this was tried
# for real (a 1028x ratio - at release size that is ~28 GB of disk). So
# unpacking has its own budget, stated against the verified file's own size,
# which download() has already proved equal to the manifest's `size` field.
# The real build extracts to under 2x its zip; 4x is generous headroom, and
# anything past it is refused mid-extraction, counted as bytes actually land
# rather than from headers a hostile zip can write however it likes.
STAGE_RATIO = 4

CHECK_TIMEOUT = 6.0          # seconds; a check slower than this is not worth having
DOWNLOAD_TIMEOUT = 60.0      # per socket read, not for the whole download

_LOCK = threading.Lock()
_RESULT: "Update | None" = None
# When that result landed, as time.time(). Kept beside the result because a
# settings panel has to be able to say "checked at 14:32" rather than implying
# a fresh answer - and "never checked this run" is a third state that must not
# read as "up to date".
_RESULT_AT: "float | None" = None


class UpdateError(Exception):
    """Anything that makes an update refuse. The message is user-facing."""


# --------------------------------------------------------------------------
# where things live
#
# Both are inside app_dir(), the folder holding the exe, because that is the
# folder the user can see and the one guaranteed writable (paths.py). Both are
# also on the same volume as the install, which the swap depends on: a rename
# inside one volume is instant and atomic, a move across volumes is a copy.


def work_dir() -> Path:
    """Where the download and the unpacked build wait. Throwaway."""
    return app_dir() / ".cache" / "update"


def settings_path() -> Path:
    """The two settings this module owns. Beside the user's other state, so it
    survives an update the same way data/ does."""
    return app_dir() / "data" / MANIFEST_NAME


# Anything this module could not read, in the words a person would use - the
# same shape settings.Settings.problems carries, and printed on the same line
# of the settings panel. It exists because both files below are HAND-EDITABLE
# and the old behaviour on a typo was to fall back to a DIFFERENT behaviour
# than the file was asking for and say nothing: a private build quietly
# checking the public box, a switched-off check quietly switching itself on.
# Every line names the file and says what is being done INSTEAD.
_PROBLEMS: list[str] = []


def _problem(msg: str) -> None:
    """Record one, once per run, and say it out loud - a console line is what
    reaches somebody running from source or reading --diag."""
    if msg not in _PROBLEMS:
        _PROBLEMS.append(msg)
        print(f"  ! {msg}", file=sys.stderr)


def problems() -> list[str]:
    """Every config file this module could not read, in plain words. Empty is
    the normal answer."""
    return list(_PROBLEMS)


def _read_settings() -> tuple[dict, bool]:
    """(settings, readable).

    The second value is the point. "There is no file, so use the defaults" and
    "there is a file and it is gibberish" were being collapsed into the same
    empty dict, which is how a hand-edit typo silently switched the update
    check back ON and forgot the version the user had skipped. They are
    different states and the callers that must refuse need to tell them apart.
    """
    p = settings_path()
    if not p.exists():
        return {}, True
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        _problem(f"{p.name} could not be read ({e}). The update check is off "
                 f"until it is fixed, because there is no way to know what it "
                 f"was asking for. Ticking the box in the settings panel "
                 f"writes a fresh one.")
        return {}, False
    # The docs invite hand-editing this file, and `false`, `[]` and `null` are
    # all valid JSON that is not a settings object. Calling .get on them used
    # to kill the MAIN thread on start, before any window existed - the same
    # shape check settings.py makes on its own file.
    if not isinstance(d, dict):
        _problem(f"{p.name} is not a settings object ({type(d).__name__}). The "
                 f"update check is off until it is fixed. Ticking the box in "
                 f"the settings panel writes a fresh one.")
        return {}, False
    return d, True


def _load_settings() -> dict:
    return _read_settings()[0]


def _save_settings(d: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")


def checks_enabled() -> bool:
    """False turns the on-start check off entirely: no request is made.

    A settings file that cannot be read is also False, and that is deliberate.
    The check is a network request, this file is the only place to switch it
    off, and defaulting a broken file back to ON would make the request the
    user may have spent that file forbidding. Off plus a problems line says
    what happened; on plus silence does not.
    """
    if os.environ.get("BGTRACKER_NO_UPDATE_CHECK", "").strip() not in ("", "0"):
        return False
    d, ok = _read_settings()
    return bool(d.get("check_on_start", True)) if ok else False


def set_checks_enabled(on: bool) -> None:
    d = _load_settings()
    d["check_on_start"] = bool(on)
    _save_settings(d)


def skipped_version() -> str | None:
    """A version the user said no to. Newer ones are still offered."""
    v = _load_settings().get("skip")
    return v if isinstance(v, str) else None


def skip_version(v: str) -> None:
    d = _load_settings()
    d["skip"] = v
    _save_settings(d)


def clear_skip() -> None:
    d = _load_settings()
    d.pop("skip", None)
    _save_settings(d)


def manifest_url() -> str | None:
    """Env var, then an `updates` key in sources.json, then the default.

    sources.json is already the file a user edits to point the tool at their
    own feed, so it is also where someone running a private build points the
    update check. Read directly rather than through bgtracker.py: this module
    has to stay importable with nothing else loaded.

    None when the file EXISTS and cannot be read, and that is the whole point
    of the return type. Falling back to the default in that case sends a build
    that was deliberately pointed somewhere private to ask the public box
    instead - a different server than the file was asking for, chosen silently,
    on the strength of a missing comma. A missing file is not that: nothing was
    configured, so the default is what was asked for.
    """
    env = os.environ.get("BGTRACKER_UPDATE_URL", "").strip()
    if env:
        return env
    p = app_dir() / "sources.json"
    if p.exists():
        try:
            src = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            _problem(f"{p.name} could not be read ({e}). The update check is "
                     f"off until it is fixed: this build will not fall back to "
                     f"the public manifest when the file says to use another "
                     f"one.")
            return None
        if not isinstance(src, dict):
            _problem(f"{p.name} is not a sources object ({type(src).__name__}). "
                     f"The update check is off until it is fixed.")
            return None
        u = src.get("updates")
        if isinstance(u, str) and u.strip():
            return u.strip()
    return DEFAULT_MANIFEST_URL


# --------------------------------------------------------------------------
# the manifest


@dataclass
class Update:
    """What a check found. Keeps three different answers apart: there is a
    newer build, this build is current, or the check never got an answer.
    `error` is set only for the third - a check that failed must never be shown
    as "you are up to date"."""

    current: str = VERSION
    latest: str | None = None
    url: str | None = None
    sha256: str | None = None
    size: int | None = None
    published: str | None = None
    notes: str | None = None
    newer: bool = False
    error: str | None = None
    source: str | None = None            # the manifest url this came from
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def available(self) -> bool:
        """The only thing a caller should gate an "Update" button on."""
        return self.newer and bool(self.url) and self.error is None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        d["available"] = self.available
        return d

    def __str__(self) -> str:
        if self.error:
            return f"update check failed: {self.error}"
        if self.newer:
            return f"bgtracker {self.latest} is available (you have {self.current})"
        return f"bgtracker {self.current} is the newest build"


def _get(url: str, timeout: float, cap: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(cap + 1)
    if len(body) > cap:
        raise UpdateError(f"the manifest is bigger than {cap} bytes - that is not a manifest")
    return body


def parse_manifest(body: bytes, source: str | None = None) -> Update:
    """Bytes to an Update, or raise UpdateError. Every field is checked here so
    nothing downstream has to trust the server."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise UpdateError(f"the manifest is not valid JSON ({e})") from None
    if not isinstance(doc, dict):
        raise UpdateError("the manifest is not a JSON object")

    latest = doc.get("version")
    try:
        parse(latest)
    except ValueError as e:
        raise UpdateError(str(e)) from None

    url = doc.get("url")
    if not isinstance(url, str) or not url:
        raise UpdateError("the manifest has no download url")
    # Absolute, non-negotiable: these bytes become code that runs on the user's
    # machine. Over plain http anyone on the path picks that code. A manifest
    # that asks for it is treated as broken, not as a warning.
    if not url.lower().startswith("https://"):
        raise UpdateError(f"the download url is not https: {url}")

    sha = doc.get("sha256")
    if (not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in sha)):
        raise UpdateError("the manifest has no usable sha256")

    size = doc.get("size")
    if (not isinstance(size, int) or isinstance(size, bool)
            or not (0 < size <= MAX_DOWNLOAD_BYTES)):
        raise UpdateError("the manifest has no usable size")

    # Same rule as `url`, for the same reason: the notes link is OPENED, and
    # webbrowser.open on Windows is os.startfile, which runs a UNC path or a
    # file:/// path exactly as it opens a web page. The manifest travels plain
    # http today, so an unchecked notes field hands "What changed" to anyone
    # on the network path. A manifest that asks for it is broken, not a
    # warning. Absent or empty notes are fine - the button just stays off.
    notes = doc.get("notes")
    notes = notes.strip() if isinstance(notes, str) else None
    if not notes:
        notes = None
    elif not notes.lower().startswith("https://"):
        raise UpdateError(f"the notes url is not https: {notes}")

    return Update(
        current=VERSION,
        latest=latest.strip(),
        url=url,
        sha256=sha.lower(),
        size=size,
        published=doc.get("published") if isinstance(doc.get("published"), str) else None,
        notes=notes,
        newer=is_newer(latest, VERSION),
        source=source,
        raw=doc,
    )


def check(url: str | None = None, timeout: float = CHECK_TIMEOUT) -> Update:
    """Ask the manifest what the newest build is. NEVER raises.

    Every way this can go wrong ends in the same quiet place - an Update whose
    `available` is False - because the overlay's job is to show Battlegrounds
    stats and an update check is not allowed to interrupt that. Covered, and
    each one exercised in --selftest: no network, the box down, a captive
    portal answering with HTML, a truncated or hand-edited manifest, a manifest
    for a version older than this one, and a manifest whose url is not https.
    """
    global _RESULT, _RESULT_AT
    src = url or manifest_url()
    if not src:
        # sources.json exists and could not be read, so there is no configured
        # manifest to ask. This lands in `error`, never in "you are up to
        # date": a check that was never made must not read as a check that
        # passed. manifest_url() has already recorded the reason.
        out = Update(error="no manifest url - " + (_PROBLEMS[-1] if _PROBLEMS
                            else "sources.json could not be read"))
        with _LOCK:
            _RESULT = out
            _RESULT_AT = time.time()
        return out
    try:
        out = parse_manifest(_get(src, timeout, MAX_MANIFEST_BYTES), source=src)
    except UpdateError as e:
        out = Update(error=str(e), source=src)
    except urllib.error.HTTPError as e:
        out = Update(error=f"the update server answered {e.code}", source=src)
    except Exception as e:                       # socket, DNS, TLS, anything
        out = Update(error=f"{type(e).__name__}: {e}", source=src)
    with _LOCK:
        _RESULT = out
        _RESULT_AT = time.time()
    return out


def result() -> Update | None:
    """The last check's answer, or None if none has landed yet. Cheap: a
    settings window reads this instead of asking the network again."""
    with _LOCK:
        return _RESULT


def checked_at() -> float | None:
    """When result() landed (time.time()), or None if nothing has been asked
    yet this run. Not persisted: a timestamp from a previous run would be
    describing a check this process never made."""
    with _LOCK:
        return _RESULT_AT


def start_check(on_result=None, disabled: bool = False,
                url: str | None = None) -> threading.Thread | None:
    """The on-start check. Returns immediately.

    A daemon thread, because this must not stall the overlay for one moment:
    the Tk loop and the log reader start regardless, and if the network hangs
    the thread hangs alone and dies with the process. Returns None when checks
    are switched off, so a caller can tell "off" from "running".
    """
    if disabled or not checks_enabled():
        return None

    def run():
        try:
            cleanup()                       # the last update's leftovers, if any
        except Exception:
            pass
        out = check(url)
        if on_result:
            try:
                on_result(out)
            except Exception:
                pass

    t = threading.Thread(target=run, name="update-check", daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------
# the download


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub answers a release download with a redirect to its CDN, which is
    fine. A redirect to http is not: it would undo the https rule one hop
    later, where nothing is looking."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise UpdateError(f"the download redirected to a non-https url: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(update: Update, progress=None, dest: Path | None = None) -> Path:
    """Fetch the zip and prove it is the one the manifest described.

    Nothing is unpacked and nothing of the installed app is touched until BOTH
    the size and the sha256 match. The file is written under a .part name and
    renamed only once it passes, so a zip sitting in the work folder is always
    a verified one - a half-finished download can never be mistaken for a
    build. `progress(done, total)` is called as it goes, for a progress bar.
    """
    if not update.url or not update.sha256 or not update.size:
        raise UpdateError("nothing to download: the manifest was not usable")

    out = dest or (work_dir() / f"bgtracker-{update.latest}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    part.unlink(missing_ok=True)

    opener = urllib.request.build_opener(_HttpsOnlyRedirect)
    req = urllib.request.Request(update.url, headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    got = 0
    try:
        with opener.open(req, timeout=DOWNLOAD_TIMEOUT) as r, part.open("wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                # Stop the moment it runs past what the manifest promised, so a
                # server that streams forever cannot fill the disk.
                if got > update.size:
                    raise UpdateError("the download is bigger than the manifest said")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(got, update.size)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"the download failed: {type(e).__name__}: {e}") from None

    if got != update.size:
        part.unlink(missing_ok=True)
        raise UpdateError(f"wrong size: got {got} bytes, the manifest said {update.size}")
    digest = h.hexdigest()
    if digest != update.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError(f"sha256 does not match: got {digest}, "
                          f"the manifest said {update.sha256}")

    out.unlink(missing_ok=True)
    part.rename(out)
    return out


# --------------------------------------------------------------------------
# unpacking


def _members(zf: zipfile.ZipFile):
    """Every member, path-checked, with the archive's single top folder
    stripped. A zip is attacker-controlled input even when the hash matched:
    the hash proves it is the file the manifest named, not that the file is
    kind."""
    names = [i.filename.replace("\\", "/") for i in zf.infolist()]
    roots = {n.split("/", 1)[0] for n in names if n.strip("/")}
    strip = (roots.copy().pop() + "/") if len(roots) == 1 else ""
    if strip and not all(n.startswith(strip) for n in names):
        strip = ""

    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/") or ":" in name:
            raise UpdateError(f"the archive holds an unsafe path: {info.filename!r}")
        rel = name[len(strip):] if strip else name
        if not rel or rel.endswith("/"):
            continue
        if any(p in ("", ".") for p in rel.split("/")):
            raise UpdateError(f"the archive holds an unsafe path: {info.filename!r}")
        # Unix mode lives in the top 16 bits. A symlink in an archive is a way
        # to make an extractor write outside the folder it was pointed at.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise UpdateError(f"the archive holds a symlink: {info.filename!r}")
        yield info, rel


def stage(zip_path: Path, into: Path | None = None,
          exe_name: str = "bgtracker.exe") -> Path:
    """Unpack a verified zip into a staging folder and check it is an install.

    The result is a complete new copy of the app sitting beside the old one and
    touching nothing of it. Everything up to here is undone by deleting one
    folder.
    """
    staged = (into or work_dir()) / "staged"
    tmp = staged.with_name("staged.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    # The extraction budget (see STAGE_RATIO): counted on the bytes actually
    # written, never on the sizes the zip's headers claim, and checked before
    # each chunk lands so a bomb is stopped within one chunk of the budget
    # instead of after filling the disk. On any refusal the partial unpack is
    # deleted - a refused archive must not leave hundreds of MB behind.
    budget = max(1, zip_path.stat().st_size) * STAGE_RATIO
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                raise UpdateError(f"the archive is corrupt at {bad}")
            for info, rel in _members(zf):
                target = tmp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > budget:
                            raise UpdateError(
                                "the archive expands to more than "
                                f"{STAGE_RATIO}x its own size - that is a "
                                "compression bomb, not a bgtracker build")
                        dst.write(chunk)

        if not (tmp / exe_name).is_file():
            raise UpdateError(f"the archive has no {exe_name} - it is not a bgtracker build")
    except UpdateError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    shutil.rmtree(staged, ignore_errors=True)
    tmp.rename(staged)
    return staged


# --------------------------------------------------------------------------
# the swap
#
# The running exe cannot overwrite itself and cannot delete the folder it runs
# from, so the swap happens AFTER this process exits, in a small helper this
# module writes from a fixed template and drops in TEMP - never anything out of
# the archive, and never inside a folder it is about to move.
#
# It does the whole swap with renames inside one volume. A rename is a metadata
# operation: instant, atomic, and unable to half-copy a 45 MB folder.
#
#   1. wait for this process to exit (up to 60s; it never kills it)
#   2. move the staged build out to <name>.new-<version>, beside the install
#   3. COPY across everything the old folder holds that the new build does not
#      ship: data, assets, .overlay.json, sources.json and anything else the
#      user put there. Copy, not move, so the old install stays whole - and
#      EVERY copy's exit code is checked, because a copy that half-worked and
#      was not noticed is how an updater eats somebody's collected games
#   4. rename the install to <name>.old-<version>
#   5. rename the new one into its place
#   6. start the app's own launcher, by name, out of the new install
#
# CRASH MID-SWAP, since that is the question that matters:
#   before 4  nothing has been touched; the old install runs as it always did.
#             A failed copy in step 3 lands here on purpose: the helper logs
#             which entry failed, deletes the half-filled .new- folder and
#             stops, so what the user has is the install they already had
#   4 -> 5    the only real window, one rename wide. Both folders exist and are
#             complete, named .old-<version> and .new-<version>, and the user's
#             files are in both because step 3 copied them. RECOVER.txt is
#             written beside them BEFORE step 4 and deleted after step 5, so if
#             it is still there it says which folder to rename back
#   after 5   the new install is live and the old one is still on disk. It does
#             NOT survive long: step 6 starts the new build immediately, and
#             that start runs cleanup() below - about two seconds later, not
#             "some future session", which is what this comment used to claim.
#             So the backup is only worth having if something checks it before
#             deleting it, and cleanup() does: it removes .old- only once every
#             file in it is present in the new install, and otherwise keeps the
#             folder and says which files are missing
#   step 5 failing is handled rather than crashed on: the helper renames
#   .old-<version> straight back and leaves the install exactly as it was


_HELPER_BODY = r"""
rem The paths, the pid and the version this script works on arrive in its
rem ENVIRONMENT, set by update.install() - see _write_helper for why nothing
rem user-specific is ever written into this file. Run without them (by hand,
rem out of TEMP) there is nothing safe to do: an empty %APP% would point the
rem dir/move lines below at a literal percent string, so it refuses instead.
if not defined APP exit /b 1
if not defined APPNAME exit /b 1
if not defined APPEXE exit /b 1
if not defined STAGED exit /b 1
if not defined NEW exit /b 1
if not defined OLD exit /b 1
if not defined RECOVER exit /b 1
if not defined LOG exit /b 1
if not defined PID exit /b 1
if not defined VER exit /b 1
if not defined SystemRoot set "SystemRoot=C:\Windows"
call :log "update to %VER% starting"

rem 1. Wait for the app to exit. Never kill it: it is mid-write on the user's
rem own files (collected games, window positions) and a forced exit is how an
rem updater eats them.
rem
rem Every external tool below is called by FULL PATH, and the wait is a `for /f`
rem over tasklist rather than the usual `tasklist | find "%PID%"`. Measured, not
rem guessed: on a machine with Git for Windows on PATH, `find` resolves to GNU
rem find, which reads the pid as a filename, prints "find: '46036': No such file
rem or directory" and exits nonzero - so the `||` fired and the wait loop fell
rem straight through while the app was still running. That would abort the swap
rem for every user with Git, MSYS or Cygwin on PATH.
rem With /FO CSV /NH a live process is one comma-separated row, and "no such
rem task" is a bare INFO sentence with no comma at all, so a second token exists
rem only when the process is still there. No text filter needed.
set /a TRIES=0
:wait
set "ALIVE="
for /f "tokens=2 delims=," %%A in ('%SystemRoot%\System32\tasklist.exe /FI "PID eq %PID%" /FO CSV /NH 2^>nul') do set "ALIVE=1"
if not defined ALIVE goto gone
set /a TRIES+=1
if %TRIES% GEQ 120 (
    call :log "the app was still running after 60s, nothing was changed"
    exit /b 1
)
%SystemRoot%\System32\ping.exe -n 2 127.0.0.1 >nul
goto wait
:gone

if not exist "%STAGED%\%APPEXE%" (
    call :log "the staged build has no %APPEXE%, nothing was changed"
    exit /b 1
)

rem 2. Out of the install folder, so renaming that folder cannot take it along.
if exist "%NEW%" rmdir /s /q "%NEW%"
call :trymove "%STAGED%" "%NEW%"
if errorlevel 1 (
    call :log "could not move the staged build out, nothing was changed"
    exit /b 1
)

rem 3. Anything the new build does not ship is the user's: the collected games,
rem the card art, the saved window positions, sources.json, and whatever else
rem they put beside the exe. COPIED, so an abort after this still leaves the
rem old install complete. The cache is skipped on purpose: it is rebuilt from
rem the card database on demand and there is no point copying it twice.
rem
rem EVERY COPY IS CHECKED, and this is the step that eats people's data when it
rem is not. robocopy's exit code is a bitmask, and the documented meanings are
rem 1 files copied, 2 extra, 4 mismatched, 8 some files could not be copied
rem (retry limit exceeded), 16 fatal - so 0-7 is success and 8 or more is a
rem failure. `if errorlevel 8` is exactly "8 or more". Measured here rather
rem than taken on trust: with one file in the source held open by another
rem process (an antivirus scanning what was just written, a text editor with
rem games.jsonl open), robocopy /R:1 /W:1 returns 9 - copied something, failed
rem something - and the file is simply absent from the destination. Unchecked,
rem the swap then went ahead and the ONLY remaining copy of it was the
rem .old- folder, which the build started at step 6 deleted seconds later.
rem A failure here aborts before anything is renamed, so the install the user
rem already has is untouched and still runs.
rem Each name that IS copied is written to a list inside the new build, and
rem cleanup() checks exactly that list rather than the whole folder. It has to
rem be a list, not "compare everything": the entries the new build SHIPS are
rem deliberately not copied, so a release that drops a file from _internal
rem would otherwise look identical to a copy that failed, and the app would
rem keep a 45 MB backup and warn about it on every start, forever.
set "COPYFAIL="
set "COPIED=%NEW%\.update-copied"
for /f "delims=" %%I in ('dir /b /a "%APP%" 2^>nul') do (
    if /i not "%%~nxI"==".cache" (
        if not exist "%NEW%\%%~nxI" (
            if exist "%APP%\%%~nxI\" (
                %SystemRoot%\System32\robocopy.exe "%APP%\%%~nxI" "%NEW%\%%~nxI" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
                if errorlevel 8 (set "COPYFAIL=%%~nxI") else (>>"%COPIED%" echo %%~nxI)
            ) else (
                copy /y "%APP%\%%~nxI" "%NEW%\" >nul
                if errorlevel 1 (set "COPYFAIL=%%~nxI") else (>>"%COPIED%" echo %%~nxI)
            )
        )
    )
)
if defined COPYFAIL (
    call :log "could not copy %COPYFAIL% into the new build, nothing was changed"
    rem The half-filled new build is not a backup of anything and must not be
    rem left looking like one. The verified zip is still in .cache\update, so
    rem retrying costs no download.
    if exist "%NEW%" rmdir /s /q "%NEW%"
    exit /b 1
)

rem 4 and 5. The swap. Two renames, and the note that explains them if the
rem machine dies between the two.
> "%RECOVER%" echo bgtracker was part way through an update and did not finish.
>>"%RECOVER%" echo.
>>"%RECOVER%" echo Your old, working install is the folder ending .old-%VER%
>>"%RECOVER%" echo Rename it back to "%APPNAME%" and everything is as it was.
>>"%RECOVER%" echo The half-installed new one ends .new-%VER% and can be deleted.
>>"%RECOVER%" echo Nothing of yours was moved, only copied, so both folders hold it.

call :trymove "%APP%" "%OLD%"
if errorlevel 1 (
    call :log "could not set the old install aside, nothing was changed"
    del "%RECOVER%" >nul 2>&1
    exit /b 1
)
call :trymove "%NEW%" "%APP%"
if errorlevel 1 (
    call :log "could not move the new build in, putting the old one back"
    call :trymove "%OLD%" "%APP%"
    rem The install is back where it was, so the note must go: it points at an
    rem .old- folder that no longer exists. Live-tested - the first version of
    rem this branch left the note behind and it read like a failed update.
    del "%RECOVER%" >nul 2>&1
    exit /b 1
)
del "%RECOVER%" >nul 2>&1
call :log "swapped in %VER%, the old install is at %OLD%"

rem 6. The ONLY thing ever run out of the new build: the app's own launcher, by
rem name, after the hash check and after the swap.
start "" /d "%APP%" "%APP%\%APPEXE%"
exit /b 0

rem Windows refuses to rename a folder anything still holds: a process whose
rem current directory is inside it, an antivirus reading what was just written,
rem an open Explorer window. Both kinds show up as the same message, and only
rem one of them clears on its own, so every rename retries for 15 seconds before
rem it is called a failure. Retrying cannot corrupt anything - a rename either
rem happens or it does not.
rem
rem The one that does NOT clear was measured here, and is why step 6 starts the
rem exe and never a .bat: `start` given a batch file runs it as `cmd /K`, and
rem that shell STAYS, sitting in the folder it was started in. During the swap
rem rehearsals a leftover `cmd /K` from a previous run held the install folder
rem open indefinitely, and the swap correctly refused every attempt for as long
rem as it lived.
:trymove
set /a MV=0
:trymoveloop
move %1 %2 >nul 2>&1 && exit /b 0
set /a MV+=1
if %MV% GEQ 15 exit /b 1
%SystemRoot%\System32\ping.exe -n 2 127.0.0.1 >nul
goto trymoveloop

:log
>>"%LOG%" echo [%DATE% %TIME%] %~1
goto :eof
"""


def _write_helper(app: Path, staged: Path, exe_name: str, pid: int, ver: str,
                  helper_dir: Path | None = None) -> tuple[Path, dict]:
    """Write the swap script and return it with the values it runs on.

    The script lives in TEMP: it must not sit inside any folder it moves, and
    it must not come out of the archive.

    The VALUES - install path, pid, version - are returned for install() to
    put in the helper's ENVIRONMENT, never written into the file. cmd decodes
    a batch file in the CONSOLE codepage, not in whatever Python wrote it as,
    so any non-ASCII install path baked into the file comes back as a
    different string: the old ascii/errors="replace" write turned an accented
    Windows profile (Jose with an accent) into "Jos?", and `?` is a wildcard
    to `move` - the swap died mid-update, or worse, could move a folder it
    was never pointed at. Environment variables reach cmd as Unicode whatever
    the codepage, and they keep the file itself pure ASCII, which is asserted
    below so a future edit cannot quietly reintroduce the bug.
    """
    d = Path(helper_dir) if helper_dir else Path(tempfile.mkdtemp(prefix="bgtracker-update-"))
    d.mkdir(parents=True, exist_ok=True)
    parent = app.parent
    values = {
        "VER": ver,
        "PID": str(pid),
        "APP": str(app),
        "APPNAME": app.name,
        "APPEXE": exe_name,
        "STAGED": str(staged),
        "NEW": str(parent / f"{app.name}.new-{ver}"),
        "OLD": str(parent / f"{app.name}.old-{ver}"),
        "RECOVER": str(parent / "bgtracker-RECOVER.txt"),
        "LOG": str(d / "update.log"),
    }
    body = "@echo off\nsetlocal enableextensions\n" + _HELPER_BODY
    if not body.isascii():
        raise UpdateError("the swap helper script is no longer pure ASCII - "
                          "refusing to write a file the console would mis-decode")
    path = d / "swap.cmd"
    path.write_text(body, encoding="utf-8")
    return path, values


def install(update: Update | None = None, progress=None, zip_path: Path | None = None,
            exe_name: str = "bgtracker.exe") -> int:
    """Download if needed, verify, stage, and hand the swap to the helper.

    Returns the helper's process id. THE CALLER MUST QUIT THE APP straight
    after: the helper waits for this process to disappear and gives up after 60
    seconds, leaving the old install untouched. Raises UpdateError, with a
    message worth showing, for every refusal.
    """
    if not frozen():
        raise UpdateError("this is the source checkout, not an installed build - "
                          "update it with git pull")
    upd = update or result() or check()
    if upd.error:
        raise UpdateError(upd.error)
    if not upd.available:
        raise UpdateError(f"nothing to install: {upd}")

    app = app_dir()
    # The swap renames the install folder, which means writing in its parent.
    # Find that out now, with a clear message, rather than half way through.
    try:
        probe = app.parent / f".bgtracker-write-test-{os.getpid()}"
        probe.mkdir()
        probe.rmdir()
    except Exception as e:
        raise UpdateError(f"cannot write next to the install folder ({app.parent}): {e}. "
                          "Move bgtracker somewhere you own, or download the new "
                          "build by hand.") from None

    zp = zip_path or download(upd, progress=progress)
    staged = stage(zp, exe_name=exe_name)
    helper, values = _write_helper(app, staged, exe_name, os.getpid(),
                                   upd.latest or "new")

    # Detached, its own process group, its own working directory: a child whose
    # cwd is the install folder would hold that folder open and the rename in
    # step 4 would fail. The paths travel in the environment (Unicode end to
    # end), which is what lets the script itself stay pure ASCII.
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED, NEW GROUP, NO WINDOW
    p = subprocess.Popen(["cmd", "/c", str(helper)], cwd=str(helper.parent),
                         env={**os.environ, **values},
                         creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    return p.pid


#: Written by the helper into the new build: one top-level name per line, for
#: every entry step 3 copied across. Deleted once the backup it justifies is
#: gone.
COPIED_LIST = ".update-copied"


def copied_entries(new: Path) -> list[str] | None:
    """The top-level names the helper copied into `new`, or None if it never
    said. None is not "nothing" and the caller must not treat it as such."""
    p = new / COPIED_LIST
    try:
        names = [ln.strip() for ln in p.read_text(encoding="utf-8",
                                                  errors="replace").splitlines()]
    except OSError:
        return None
    return [n for n in names if n and n != ".cache"]


def missing_from(old: Path, new: Path, limit: int = 8) -> list[str]:
    """Files the update was supposed to carry across and did not, by relative
    path. Empty means the new install holds everything the old one did.

    This is the question the helper's step 3 answers with a copy and this
    answers with a look, and both are needed: robocopy can report a failure the
    helper acts on, and it can also be killed, run out of disk, or lose a
    machine mid-copy, in which case nobody reported anything.

    WHAT IS COMPARED, because comparing everything would be wrong. The helper
    copies only the top-level entries the new build does NOT ship - the user's
    data, art, settings - and it writes their names into COPIED_LIST. Those are
    the trees checked. The shipped ones are deliberately excluded: a release
    that drops a file from _internal is a normal release, and counting it here
    would keep a 45 MB backup alive and warn about it on every start forever.
    `.cache` is skipped for the same reason the helper skips it - it is rebuilt
    from the card database on demand.

    With no list (an update FROM a build older than this mechanism, or a helper
    that died before writing one) every entry is compared instead. That is the
    cautious direction on purpose: it can keep a backup that did not need
    keeping, which costs disk and a line of text, where the other mistake costs
    somebody every game they have ever collected.
    """
    only = copied_entries(new)
    roots = ([old / n for n in only] if only is not None
             else [p for p in old.iterdir() if p.name != ".cache"])
    out = []
    for root in roots:
        if not root.exists():
            out.append(root.name)
            if len(out) >= limit:
                break
            continue
        files = [root] if root.is_file() else root.rglob("*")
        for f in files:
            if not f.is_file():
                continue
            rel = f.relative_to(old)
            if not (new / rel).exists():
                out.append(str(rel))
                if len(out) >= limit:
                    return out
    return out


def cleanup(app: Path | None = None) -> list[str]:
    """Delete what a finished update left behind. Runs on the next start.

    Only ever removes folders named after this install with the exact .old- or
    .new- suffix the helper writes, and only when they really are a build (they
    hold the exe). Deleting 45 MB out of somebody's Downloads folder on a name
    match alone is not something to be relaxed about.

    AND THE .old- FOLDER IS CHECKED FIRST, which is the whole reason it exists.
    "The old install stays until the next start" sounds like a grace period and
    is not one: the helper's last act is to START the new build, so this runs
    seconds after the swap. If the copy in step 3 did not finish, the user's
    collected games, window positions and sources.json exist ONLY in that
    folder, and deleting it on sight destroys the last copy. So a .old- folder
    is removed only once every file in it is present in the new install; when
    something is missing the folder is kept, named, and reported on the
    problems line, and the app carries on running.

    A .new- folder is a different thing and is always removed: it is a half
    installed build that never went live, and it is a backup of nothing.
    """
    app = app or app_dir()
    removed = []
    for p in app.parent.glob(f"{app.name}.*"):
        suffix = p.name[len(app.name):]
        if not p.is_dir() or not (suffix.startswith(".old-") or suffix.startswith(".new-")):
            continue
        if not (p / "bgtracker.exe").is_file():
            continue
        if suffix.startswith(".old-"):
            gone = missing_from(p, app)
            if gone:
                _problem(f"the update did not copy everything across, so the "
                         f"previous install is being kept at {p.name}. Missing "
                         f"from this one: {', '.join(gone[:4])}"
                         + (" and more" if len(gone) > 4 else "")
                         + ". Copy them back by hand, then delete that folder.")
                continue
            # Nothing left to check against, so the helper's note goes with the
            # folder it was about rather than sitting in the install forever.
            (app / COPIED_LIST).unlink(missing_ok=True)
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            removed.append(p.name)
    if work_dir().is_dir():
        for junk in work_dir().glob("*.part"):
            junk.unlink(missing_ok=True)
        shutil.rmtree(work_dir() / "staged.tmp", ignore_errors=True)
    return removed


# --------------------------------------------------------------------------
# CLI: a real check, and the offline failure-mode suite


def _selftest() -> int:                                  # noqa: C901 - it is a list of cases
    """Stand a manifest up on loopback and walk every way this can go wrong.

    Offline on purpose so CI runs it: no release, no GitHub, no stats box.
    """
    import http.server
    import socketserver

    ok = True

    def say(name, passed, detail=""):
        nonlocal ok
        ok = ok and bool(passed)
        print(f"  {'PASS' if passed else 'FAIL'}  {name}{'  |  ' + detail if detail else ''}")

    # --- the version comparison, the part a string compare gets wrong --------
    cases = [("0.10.0", "0.9.0", True), ("0.9.0", "0.10.0", False),
             ("1.0.0", "0.999.999", True), ("0.3.0", "0.3.0-alpha", True),
             ("0.3.0-alpha", "0.3.0", False), ("0.3.0-alpha.10", "0.3.0-alpha.2", True),
             ("0.2.0-alpha", "0.2.0-alpha", False), ("v0.4.0", "0.3.0-alpha", True)]
    wrong = [(a, b, e) for a, b, e in cases if is_newer(a, b) is not e]
    say("version compare (0.10.0 beats 0.9.0)", not wrong, str(wrong))

    # --- data/update.json holds whatever a hand-edit left in it -------------
    # `false`, `[]` and `null` are all valid JSON that is not an object, and
    # .get on them used to kill the MAIN thread on start - taking the overlay
    # AND --diag down before a single window existed.
    sdir = Path(tempfile.mkdtemp(prefix="bgtracker-selftest-settings-"))
    real_settings_path = globals()["settings_path"]
    try:
        globals()["settings_path"] = lambda: sdir / MANIFEST_NAME
        got = []
        for payload in ("false", "[]", "null", '"off"', "{not json"):
            (sdir / MANIFEST_NAME).write_text(payload, encoding="utf-8")
            _PROBLEMS.clear()
            try:
                got.append((payload, checks_enabled(), skipped_version(),
                            len(problems())))
            except Exception as e:
                got.append((payload, f"RAISED {type(e).__name__}: {e}", None, 0))
        # OFF, not on. A file we cannot read is not permission to make the
        # network request the file may exist to forbid, and it is not permission
        # to re-offer a version the user skipped either - both of which the old
        # "return {} and carry on with the defaults" quietly did.
        say("an unreadable update.json turns the check off and says so",
            all(g[1] is False and g[2] is None and g[3] == 1 for g in got), str(got))
        (sdir / MANIFEST_NAME).write_text("[]", encoding="utf-8")
        _PROBLEMS.clear()
        set_checks_enabled(True)
        saved = json.loads((sdir / MANIFEST_NAME).read_text(encoding="utf-8"))
        say("saving over a broken settings file recovers it",
            checks_enabled() is True and isinstance(saved, dict), str(saved))
        _PROBLEMS.clear()
    finally:
        globals()["settings_path"] = real_settings_path
        shutil.rmtree(sdir, ignore_errors=True)

    # --- a broken sources.json must not quietly ask a different server ------
    # sources.json is where a private build points the update check. Falling
    # back to the default on a missing comma means that build asks the PUBLIC
    # box instead - a different server, chosen silently. It refuses instead.
    srcdir = Path(tempfile.mkdtemp(prefix="bgtracker-selftest-sources-"))
    real_app_dir = globals()["app_dir"]
    try:
        globals()["app_dir"] = lambda: srcdir
        _PROBLEMS.clear()
        (srcdir / "sources.json").write_text('{"updates": "https://mine.invalid/u.json"',
                                             encoding="utf-8")   # missing brace
        u = check()
        say("a broken sources.json refuses rather than falling back to the "
            "public manifest",
            manifest_url() is None and not u.available and u.error
            and "sources.json" in u.error and len(problems()) == 1,
            f"{u.error} | problems={problems()}")
        _PROBLEMS.clear()
        (srcdir / "sources.json").write_text('{"heroes": "x"}', encoding="utf-8")
        say("a sources.json with no updates key still uses the default",
            manifest_url() == DEFAULT_MANIFEST_URL and not problems(),
            str(manifest_url()))
        (srcdir / "sources.json").unlink()
        say("no sources.json at all uses the default, silently",
            manifest_url() == DEFAULT_MANIFEST_URL and not problems(),
            str(manifest_url()))
    finally:
        globals()["app_dir"] = real_app_dir
        _PROBLEMS.clear()
        shutil.rmtree(srcdir, ignore_errors=True)

    payload = b"x" * 5000
    good_sha = hashlib.sha256(payload).hexdigest()
    routes: dict[str, tuple[int, bytes]] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = routes.get(self.path, (404, b"nope"))
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def manifest(**kw):
        d = {"schema": 1, "version": "9.9.9", "url": "https://example.invalid/b.zip",
             "sha256": good_sha, "size": len(payload), "published": "2026-08-12",
             "notes": "https://example.invalid/notes"}
        d.update(kw)
        return json.dumps(d).encode()

    routes["/up-to-date.json"] = (200, manifest(version=VERSION))
    routes["/older.json"] = (200, manifest(version="0.0.1"))
    routes["/newer.json"] = (200, manifest())
    routes["/plainhttp.json"] = (200, manifest(url=f"{base}/b.zip"))
    routes["/garbage.json"] = (200, b"<html>sign in to use this wifi</html>")
    routes["/truncated.json"] = (200, manifest()[:40])
    routes["/noversion.json"] = (200, manifest(version="latest-and-greatest"))
    routes["/badsha.json"] = (200, manifest(sha256="zz"))
    routes["/badsize.json"] = (200, manifest(size=-1))
    routes["/500.json"] = (500, b"server on fire")
    routes["/huge.json"] = (200, b" " * (MAX_MANIFEST_BYTES + 10))
    # notes is opened by "What changed", and os.startfile runs all three of
    # these. Each one was accepted by webbrowser's own checks when this was
    # tried for real - the refusal has to be ours, at parse time.
    routes["/notes-http.json"] = (200, manifest(notes="http://165.227.41.29/notes"))
    routes["/notes-file.json"] = (200, manifest(notes="file:///C:/Windows/System32/calc.exe"))
    routes["/notes-unc.json"] = (200, manifest(notes="\\\\evil-box\\share\\payload.exe"))
    routes["/b.zip"] = (200, payload)

    u = check(f"{base}/up-to-date.json")
    say("up to date", u.error is None and not u.newer and not u.available, str(u))
    u = check(f"{base}/older.json")
    say("manifest for an OLDER version", u.error is None and not u.newer and not u.available, str(u))

    u = check(f"{base}/newer.json")
    say("update available", u.available and u.latest == "9.9.9" and u.size == len(payload)
        and u.published == "2026-08-12" and u.sha256 == good_sha
        and u.notes == "https://example.invalid/notes", str(u))
    good = u

    u = check(f"{base}/plainhttp.json")
    say("download url is not https", not u.available and "https" in (u.error or ""), str(u))
    for route in ("notes-http", "notes-file", "notes-unc"):
        u = check(f"{base}/{route}.json")
        say(f"notes url refused ({route})",
            not u.available and u.notes is None and "notes" in (u.error or ""), str(u))
    u = check(f"{base}/garbage.json")
    say("garbage response (captive portal)", not u.available and u.error, str(u))
    u = check(f"{base}/truncated.json")
    say("truncated manifest", not u.available and u.error, str(u))
    u = check(f"{base}/noversion.json")
    say("version field is not a version", not u.available and u.error, str(u))
    u = check(f"{base}/badsha.json")
    say("unusable sha256", not u.available and "sha256" in (u.error or ""), str(u))
    u = check(f"{base}/badsize.json")
    say("unusable size", not u.available and "size" in (u.error or ""), str(u))
    u = check(f"{base}/500.json")
    say("server error", not u.available and "500" in (u.error or ""), str(u))
    u = check(f"{base}/huge.json")
    say("oversized body", not u.available and u.error, str(u))
    u = check(f"{base}/does-not-exist.json")
    say("no manifest on the server", not u.available and "404" in (u.error or ""), str(u))

    srv.shutdown()
    u = check(f"{base}/newer.json", timeout=3.0)
    say("server down", not u.available and u.error, str(u))
    u = check("http://127.0.0.1:9/never.json", timeout=3.0)
    say("nothing listening", not u.available and u.error, str(u))
    u = check("http://bgtracker-no-such-host.invalid/update.json", timeout=3.0)
    say("no network / dns fails", not u.available and u.error, str(u))

    # --- the download. Served over loopback http on purpose: the https rule is
    # on the manifest's url, and this is testing the hash and size gates -------
    tmp = Path(tempfile.mkdtemp(prefix="bgtracker-selftest-"))
    srv2 = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    zip_url = f"http://127.0.0.1:{srv2.server_address[1]}/b.zip"

    try:
        p = download(Update(latest="9.9.9", url=zip_url, sha256=good_sha,
                            size=len(payload), newer=True), dest=tmp / "ok.zip")
        say("download verifies", p.exists() and p.stat().st_size == len(payload))
    except UpdateError as e:
        say("download verifies", False, str(e))

    try:
        download(Update(latest="9.9.9", url=zip_url, sha256="0" * 64,
                        size=len(payload), newer=True), dest=tmp / "bad.zip")
        say("bad sha256 refused", False, "it accepted the file")
    except UpdateError as e:
        say("bad sha256 refused",
            "sha256" in str(e) and not (tmp / "bad.zip").exists()
            and not (tmp / "bad.zip.part").exists(), str(e))

    try:
        download(Update(latest="9.9.9", url=zip_url, sha256=good_sha,
                        size=len(payload) - 1, newer=True), dest=tmp / "short.zip")
        say("wrong size refused", False, "it accepted the file")
    except UpdateError as e:
        say("wrong size refused", not (tmp / "short.zip").exists(), str(e))
    srv2.shutdown()

    # --- unpacking ----------------------------------------------------------
    zp = tmp / "build.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("bgtracker/bgtracker.exe", "not really an exe")
        z.writestr("bgtracker/_internal/base_library.zip", "x")
        z.writestr("bgtracker/version.txt", "9.9.9\n")
    try:
        staged = stage(zp, into=tmp, exe_name="bgtracker.exe")
        say("unpack strips the archive's top folder",
            (staged / "bgtracker.exe").is_file() and (staged / "_internal").is_dir())
    except UpdateError as e:
        say("unpack strips the archive's top folder", False, str(e))

    evil = tmp / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("bgtracker/bgtracker.exe", "x")
        z.writestr("bgtracker/../../evil.txt", "pwned")
    try:
        stage(evil, into=tmp / "evil-out", exe_name="bgtracker.exe")
        say("zip slip refused", False, "it unpacked it")
    except UpdateError as e:
        say("zip slip refused", "unsafe" in str(e)
            and not (tmp.parent / "evil.txt").exists(), str(e))

    empty = tmp / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("bgtracker/readme.txt", "x")
    try:
        stage(empty, into=tmp / "empty-out", exe_name="bgtracker.exe")
        say("archive with no app refused", False, "it accepted it")
    except UpdateError as e:
        say("archive with no app refused", "not a bgtracker build" in str(e), str(e))

    # The repro's shape: a tiny zip that expands three orders of magnitude
    # (64 MB of zeros deflates to ~64 KB). The budget must stop it within a
    # chunk of STAGE_RATIO x the zip size and delete the partial unpack.
    bomb = tmp / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bgtracker/bgtracker.exe", "x")
        z.writestr("bgtracker/blob.bin", b"\0" * (64 * 1024 * 1024))
    ratio = 64 * 1024 * 1024 / bomb.stat().st_size
    try:
        stage(bomb, into=tmp / "bomb-out", exe_name="bgtracker.exe")
        say("compression bomb refused", False, f"it unpacked a {ratio:.0f}x zip")
    except UpdateError as e:
        leftover = sum(f.stat().st_size for f in (tmp / "bomb-out").rglob("*")
                       if f.is_file()) if (tmp / "bomb-out").exists() else 0
        say("compression bomb refused",
            "bomb" in str(e) and leftover == 0,
            f"{ratio:.0f}x zip, {leftover} bytes left behind | {e}")

    # --- the swap helper, on an accented install path ------------------------
    # The old helper was written ascii/errors="replace", so an accented profile
    # became "Jos?" inside the script and the swap died (or wildcarded). The
    # fix keeps the script pure ASCII and passes the paths in the environment,
    # so this runs the REAL helper against a real folder with an accented name
    # and checks the swap end to end: new build in, old set aside, user files
    # in both, recovery note gone.
    accroot = tmp / "José Müller"
    appdir = accroot / "bgtracker"
    (appdir / "data").mkdir(parents=True)
    (appdir / "bgtracker.exe").write_text("old build", encoding="utf-8")
    (appdir / "data" / "games.jsonl").write_text("the user's games", encoding="utf-8")
    stagedir = accroot / "staged-build"
    stagedir.mkdir()
    (stagedir / "bgtracker.exe").write_text("new build 9.9.9", encoding="utf-8")
    dead = subprocess.Popen([sys.executable, "-c", "pass"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dead.wait()                       # a pid that is certainly gone
    helper, values = _write_helper(appdir, stagedir, "bgtracker.exe",
                                   dead.pid, "9.9.9", helper_dir=tmp / "helper")
    say("helper script is pure ASCII", helper.read_bytes().isascii())
    say("helper script holds no user path",
        "Jos" not in helper.read_text(encoding="utf-8"))
    r = subprocess.run(["cmd", "/c", str(helper)], cwd=str(helper.parent),
                       env={**os.environ, **values}, capture_output=True,
                       text=True, timeout=120)
    old = accroot / "bgtracker.old-9.9.9"
    swapped = (r.returncode == 0
               and (appdir / "bgtracker.exe").read_text(encoding="utf-8") == "new build 9.9.9"
               and (appdir / "data" / "games.jsonl").read_text(encoding="utf-8") == "the user's games"
               and (old / "bgtracker.exe").read_text(encoding="utf-8") == "old build"
               and (old / "data" / "games.jsonl").is_file()
               and not (accroot / "bgtracker-RECOVER.txt").exists()
               # The note cleanup() checks against, written by the helper. The
               # whole "keep the backup until the files are proved across"
               # rule rests on this file existing and naming what was copied.
               and copied_entries(appdir) == ["data"]
               and not missing_from(old, appdir))
    say("swap succeeds on an accented install path", swapped,
        f"rc={r.returncode} log={(tmp / 'helper' / 'update.log').read_text(encoding='utf-8', errors='replace').strip() if (tmp / 'helper' / 'update.log').exists() else 'missing'}")

    # --- the swap when a COPY FAILS -----------------------------------------
    # Step 3 is the one place an update can destroy data that exists nowhere
    # else. A file held open with no sharing is exactly what an antivirus
    # scanning a just-written folder, or an editor with games.jsonl open, does
    # to it; robocopy then answers 9 (1 copied | 8 could not be copied) and
    # leaves the file out. Unchecked, the swap went ahead and the last copy of
    # it was the .old- folder the new build deleted seconds later.
    def _lock(path: Path):
        """Open a file the way another process holding it does: no sharing."""
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.kernel32.CreateFileW
        fn.restype = wintypes.HANDLE
        fn.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                       wintypes.HANDLE)
        return fn(str(path), 0x80000000, 0, None, 3, 0x80, None)

    failroot = tmp / "copyfail"
    appdir2 = failroot / "bgtracker"
    (appdir2 / "data").mkdir(parents=True)
    (appdir2 / "bgtracker.exe").write_text("old build", encoding="utf-8")
    games = appdir2 / "data" / "games.jsonl"
    games.write_text("the user's games", encoding="utf-8")
    (appdir2 / "sources.json").write_text('{"heroes": "mine"}', encoding="utf-8")
    stagedir2 = failroot / "staged-build"
    stagedir2.mkdir()
    (stagedir2 / "bgtracker.exe").write_text("new build 9.9.9", encoding="utf-8")
    helper2, values2 = _write_helper(appdir2, stagedir2, "bgtracker.exe",
                                     dead.pid, "9.9.9", helper_dir=tmp / "helper2")
    handle = _lock(games)
    try:
        r2 = subprocess.run(["cmd", "/c", str(helper2)], cwd=str(helper2.parent),
                            env={**os.environ, **values2}, capture_output=True,
                            text=True, timeout=120)
    finally:
        import ctypes as _c
        _c.windll.kernel32.CloseHandle(handle)
    log2 = ((tmp / "helper2" / "update.log").read_text(encoding="utf-8",
                                                       errors="replace").strip()
            if (tmp / "helper2" / "update.log").exists() else "missing")
    intact = (r2.returncode != 0
              and (appdir2 / "bgtracker.exe").read_text(encoding="utf-8") == "old build"
              and games.read_text(encoding="utf-8") == "the user's games"
              and (appdir2 / "sources.json").is_file()
              and not (failroot / "bgtracker.old-9.9.9").exists()
              and not (failroot / "bgtracker.new-9.9.9").exists()
              and not (failroot / "bgtracker-RECOVER.txt").exists())
    say("a failed copy aborts the swap and leaves the old install runnable",
        intact, f"rc={r2.returncode} log={log2}")

    # --- cleanup will not delete the last copy of somebody's files ----------
    # The helper's last act is to START the new build, so cleanup runs about two
    # seconds after the swap - not "some future session". If step 3 did not
    # finish, deleting .old- on sight destroys the only remaining copy.
    croot = tmp / "cleanupcheck"
    live = croot / "bgtracker"
    kept = croot / "bgtracker.old-9.9.9"
    stale = croot / "bgtracker.new-9.9.9"
    for d in (live, kept, stale):
        (d / "data").mkdir(parents=True)
        (d / "bgtracker.exe").write_text("build", encoding="utf-8")
    (kept / "data" / "games.jsonl").write_text("the only copy", encoding="utf-8")
    # The helper's own note: it copied data, and nothing else was its to carry.
    (live / COPIED_LIST).write_text("data\n", encoding="utf-8")
    # A file the release DROPPED from the shipped part of the build. It is in
    # the old install and not in the new one, and it must not be mistaken for
    # a failed copy - that mistake would keep a 45 MB backup alive and warn
    # about it on every start for good.
    (kept / "_internal").mkdir()
    (kept / "_internal" / "dropped-dependency.pyd").write_text("x", encoding="utf-8")
    (live / "_internal").mkdir()
    real_work_dir = globals()["work_dir"]
    try:
        globals()["work_dir"] = lambda: croot / ".cache" / "update"
        _PROBLEMS.clear()
        gone = cleanup(live)
        say("cleanup keeps a backup whose files are missing from the install",
            kept.is_dir() and (kept / "data" / "games.jsonl").is_file()
            and kept.name not in gone and stale.name in gone
            and len(problems()) == 1,
            f"removed={gone} problems={problems()}")
        # Put the file where the swap should have put it: now the backup is
        # genuinely redundant and goes - and the shipped file the release
        # dropped must not hold it back.
        shutil.copy2(kept / "data" / "games.jsonl", live / "data" / "games.jsonl")
        _PROBLEMS.clear()
        gone = cleanup(live)
        say("a release that drops a shipped file does not look like a failed "
            "copy, and the backup goes",
            kept.name in gone and not kept.exists() and not problems()
            and not (live / COPIED_LIST).exists(),
            f"removed={gone} problems={problems()}")

        # Same again with NO note - an update from a build older than this
        # mechanism. Everything is compared, so it errs toward keeping.
        kept2 = croot / "bgtracker.old-9.9.8"
        (kept2 / "data").mkdir(parents=True)
        (kept2 / "bgtracker.exe").write_text("build", encoding="utf-8")
        (kept2 / "data" / "only-copy.jsonl").write_text("games", encoding="utf-8")
        _PROBLEMS.clear()
        gone = cleanup(live)
        say("with no note from the helper, a backup holding a file the install "
            "lacks is still kept",
            kept2.is_dir() and kept2.name not in gone and len(problems()) == 1,
            f"removed={gone} problems={problems()}")
    finally:
        globals()["work_dir"] = real_work_dir
        _PROBLEMS.clear()

    # --- install refuses to touch a source checkout -------------------------
    try:
        install(good)
        say("install refuses to run from source", False, "it went ahead")
    except UpdateError as e:
        say("install refuses to run from source", "source checkout" in str(e), str(e))

    shutil.rmtree(tmp, ignore_errors=True)
    print("  ---")
    print(f"  {'all cases passed' if ok else 'SOMETHING FAILED'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="bgtracker update channel")
    ap.add_argument("--check", action="store_true",
                    help="ask the manifest and print what it says")
    ap.add_argument("--url", help="a manifest url to use instead of the configured one")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--selftest", action="store_true", help="offline failure-mode suite")
    a = ap.parse_args()

    if a.selftest:
        print("update.py selftest")
        return _selftest()

    u = check(a.url)
    if a.json:
        print(json.dumps(u.as_dict(), indent=2))
        return 0
    print(f"this build   {u.current}")
    print(f"manifest     {u.source}")
    if u.error:
        print(f"result       could not check: {u.error}")
    else:
        print(f"newest       {u.latest}   published {u.published or '-'}")
        print(f"download     {u.url}")
        print(f"sha256       {u.sha256}")
        print(f"size         {u.size} bytes")
        print(f"notes        {u.notes or '-'}")
        print(f"result       {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
