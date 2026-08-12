#!/usr/bin/env python3
"""The overlay's own community pooling - on by default, one switch to stop it.

A user who downloads the zip and plays FEEDS THE POOL with zero extra steps:
on start a background thread mines the whole Power.log history once (that is
collect.py's own miner, imported, never reimplemented) and uploads every game
that has not gone yet; after each finished game, and once more on the way out,
it re-mines just the current log and sends the new game. collect.exe stays for
people who want to drive it by hand.

THE SWITCH. One setting, `upload`, default true (settings.py). The panel's
DATA box clears it for good; `--no-upload` clears it for one run (the standard
precedence: a typed flag beats the file, and is never written into it, exactly
like the update check's kill switches). The setting is read at every sync
boundary, so unticking the box stops the NEXT send without a restart.

WHAT LEAVES, in one place: collect.upload_records() builds every record, the
settings panel names every field in it, and tests/test_settings.py holds the
two together. Nothing here adds a field.

THE LEDGER. data/uploaded.json remembers, per uid, a fingerprint of what was
sent, so nothing uploads twice - the server's INSERT OR IGNORE on uid is the
backstop, not the mechanism. The fingerprint (not a bare uid set) is what lets
a record that GAINED data since it was sent - a re-mine filling in `duo` on an
old game - go out again, which is the only way the server's duo backfill ever
hears about it. Written after every batch the server answered, so a killed
backfill resumes where it stopped instead of starting over.

THE THROTTLE, measured from the server's own limits rather than guessed:
server/ingest.py rate-limits at 120 POSTs per minute per IP (BGTRACKER_RATE),
and the nginx vhost in server/deploy caps /upload at a steady 2 requests per
second with a burst of 10. The rule here is to stay under HALF the app limit:
one POST every 2 seconds is 30 a minute - a quarter of ingest's 120, half of
nginx's steady rate - and at 300 games a POST that still moves 9,000 games a
minute, so even a huge first backfill clears in about a minute without ever
tripping either limit.

FAILURE IS QUIET. A dead or refusing server means: nothing marked sent, no
exception, no console noise, try again at the next boundary (next game, next
start). The game must never pay for the pool: everything network runs on one
daemon thread, and shutdown waits at most ~2 seconds for a send in flight
before letting the process go (daemon = the thread dies with it).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

import bgtracker as bg
import collect

# Beside games.jsonl, because it describes games.jsonl. Module-level so tests
# can point it somewhere disposable, same as collect.OUT.
SENT_FILE = collect.DATA / "uploaded.json"

BATCH = 300          # games per POST; the server refuses over 500 (ingest.py)
SPACING = 2.0        # seconds between POSTs - the throttle math above
START_DELAY = 20.0   # let the overlay and the game finish starting first:
#                      the full-history mine is a minute of disk reading, and
#                      it can afford to wait; a hero draft cannot.


def _load_sent():
    """uid -> fingerprint of the record as it was last sent. {} when nothing
    has gone yet, and {} again on a corrupt file - the cost of forgetting is
    one re-send of already-stored games, which the server de-dupes anyway."""
    try:
        d = json.loads(SENT_FILE.read_text(encoding="utf-8"))
        sent = d.get("sent")
        return {str(k): str(v) for k, v in sent.items()} if isinstance(sent, dict) else {}
    except Exception:
        return {}


def _save_sent(sent):
    """Atomic for the same reason games.jsonl is written through a temp file:
    a crash mid-write must not leave a truncated ledger that re-sends the
    whole history next start. Failure to save is swallowed - worst case is
    that same harmless re-send."""
    try:
        SENT_FILE.parent.mkdir(exist_ok=True)
        tmp = SENT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"sent": sent}), encoding="utf-8")
        tmp.replace(SENT_FILE)
    except Exception:
        pass


def _fingerprint(rec):
    """What 'this exact record was sent' means. Hashed over the record's GAME
    fields, so a re-mine that fills any of them in (duo, offers) produces a
    new fingerprint and the record goes out again. The client version is
    excluded on purpose: it is stamped into every record, so hashing it would
    re-upload the user's entire history once after every release for no new
    information. Sixteen hex chars because the ledger only has to tell a
    game's own versions apart, not resist an adversary."""
    return hashlib.sha256(
        json.dumps({k: v for k, v in rec.items() if k != "v"},
                   sort_keys=True).encode()).hexdigest()[:16]


class Pool:
    """Owns the one sharing thread. The overlay calls exactly three things:
    start() once, on_game() at each 'game' event, on_exit() when quitting."""

    def __init__(self, settings, spacing=SPACING, start_delay=START_DELAY):
        self.s = settings
        self.spacing = spacing
        self.start_delay = start_delay
        self._wake = threading.Event()
        self._exiting = threading.Event()
        self._drained = threading.Event()   # the final sync finished
        self._thread = None
        self.last = None                    # the last sync's outcome, for tests

    # ------------------------------------------------------------- the API

    def enabled(self):
        """Read fresh every time: the panel flips the setting mid-run and the
        next boundary must honor it, on or off."""
        return bool(self.s.get("upload")) and bool(
            (self.s.get("upload_url") or "").strip())

    def start(self):
        if self._thread is not None:
            return self._thread
        self._thread = threading.Thread(target=self._run, name="pool-games",
                                        daemon=True)
        self._thread.start()
        return self._thread

    def on_game(self):
        """A new game was detected, so the previous one just finished and is
        now COMPLETE in the current log. Wake the thread; never block here -
        this is called from the Tk poll loop."""
        self._wake.set()

    def on_exit(self, timeout=2.0):
        """Best effort on the way out: trigger one last incremental sync and
        give it ~2 seconds. The thread is a daemon, so a slow mine or a hung
        socket cannot hold the overlay's shutdown hostage past the wait."""
        if self._thread is None:
            return
        self._exiting.set()
        self._wake.set()
        self._drained.wait(timeout)

    # ---------------------------------------------------------- the thread

    def _run(self):
        # The start delay is a wait on the exit flag, not a sleep, so quitting
        # during it returns immediately instead of pinning shutdown.
        self._exiting.wait(self.start_delay)
        try:
            try:
                if not self._exiting.is_set() and self.enabled():
                    self._sync(logs=None)      # the full history, once
            except Exception as e:
                self.last = {"sent": 0, "error": f"{type(e).__name__}: {e}"}
            while not self._exiting.is_set():
                self._wake.wait()
                self._wake.clear()
                if self._exiting.is_set():
                    break
                # _sync already swallows network errors; this guard is for
                # everything else (a log file vanishing mid-stat, a mine
                # error). The module promises "try again at the next
                # boundary", which requires the thread to still exist then.
                try:
                    if self.enabled():
                        self._sync(logs=self._current_log())
                except Exception as e:
                    self.last = {"sent": 0,
                                 "error": f"{type(e).__name__}: {e}"}
            try:
                if self.enabled():             # the on-exit flush
                    self._sync(logs=self._current_log())
            except Exception:
                pass
        finally:
            self._drained.set()

    @staticmethod
    def _current_log():
        """The one log the game is writing now - the only file a game boundary
        can have added anything to. [] (mine nothing, upload the backlog) when
        there is none, never None, which would mean the full history again."""
        cur = bg.newest_power_log()
        return [cur] if cur else []

    def _sync(self, logs):
        """Mine, then upload what the ledger says has not gone. Every failure
        ends quietly with the ledger unchanged for whatever did not land."""
        try:
            collect.collect(logs=logs)
        except Exception:
            pass                    # mining failed; still try to drain backlog
        try:
            recs = collect.upload_records()
        except Exception:
            self.last = {"sent": 0, "error": "unreadable games file"}
            return
        sent = _load_sent()
        todo = []
        for r in recs:
            fp = _fingerprint(r)
            if sent.get(r["uid"]) != fp:
                todo.append((r, fp))
        if not todo:
            self.last = {"sent": 0, "error": None}
            return
        url = collect.upload_url(self.s.get("upload_url").strip())
        done = 0
        for i in range(0, len(todo), BATCH):
            # The DATA box says "clear it and nothing is sent", and that has
            # to hold for the batch about to leave, not just the next sync -
            # a first-launch backfill can run for a minute, and the panel is
            # open right next to it. Re-read the switch before every POST.
            if not self.enabled():
                self.last = {"sent": done, "error": "sharing switched off"}
                return
            if i:
                # Space the POSTs (the first one goes at once). On the way out
                # the wait returns immediately - best effort beats politeness
                # when the process is about to disappear anyway.
                self._exiting.wait(self.spacing)
            chunk = todo[i:i + BATCH]
            try:
                collect.post_batch(url, [r for r, _ in chunk])
            except Exception as e:
                # Quiet, remember nothing for this and later batches, retry at
                # the next boundary. Batches already answered stay in the
                # ledger - the crash-resume property the module doc promises.
                self.last = {"sent": done, "error": f"{type(e).__name__}: {e}"}
                return
            # The server ANSWERED this batch: that is what 'sent' means here.
            # A record it rejected as malformed is deliberately not retried
            # forever - the reply does not say which uid was refused, and the
            # uid de-dupe makes a rare lost one at worst a missing game, never
            # a doubled one.
            for r, fp in chunk:
                sent[r["uid"]] = fp
            _save_sent(sent)
            done += len(chunk)
        if done:
            # The panel's "last shared" row reads this setting; without the
            # stamp it would say "never from this machine" while games flow
            # out every sitting, which is exactly the kind of lie the DATA
            # copy exists to prevent. Best effort: a read-only settings file
            # must not turn a successful share into a failure.
            try:
                self.s.set("last_upload", time.time())
            except Exception:
                pass
        self.last = {"sent": done, "error": None}
