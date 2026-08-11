#!/usr/bin/env python3
"""Regression tests for settings.json and configured Power.log discovery."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bgtracker as bg  # noqa: E402


def write_settings(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_default_fallbacks(tmp: Path) -> None:
    missing = tmp / "missing-settings.json"
    bg.configure_log_path(missing)
    assert bg.HS_LOGS == bg.default_hs_logs_dir()
    assert bg.HS_LOGS_SOURCE == "default"

    empty = tmp / "empty-settings.json"
    write_settings(empty, {"hearthstone_logs_dir": "   "})
    bg.configure_log_path(empty)
    assert bg.HS_LOGS == bg.default_hs_logs_dir()
    assert bg.HS_LOGS_SOURCE == "default"


def test_custom_relative_and_environment_path(tmp: Path) -> Path:
    custom = tmp / "custom-logs"
    settings = tmp / "settings.json"
    write_settings(settings, {"hearthstone_logs_dir": "custom-logs"})
    bg.configure_log_path(settings)
    assert bg.HS_LOGS == custom.resolve()
    assert bg.HS_LOGS_SOURCE == "settings.json"

    env_name = "BGTRACKER_TEST_LOGS"
    os.environ[env_name] = str(custom)
    try:
        write_settings(settings, {"hearthstone_logs_dir": f"%{env_name}%"})
        bg.configure_log_path(settings)
        assert bg.HS_LOGS == custom.resolve()
        assert bg.HS_LOGS_SOURCE == "settings.json"
    finally:
        os.environ.pop(env_name, None)
    return custom


def test_newest_and_rotation(tmp: Path) -> None:
    custom = test_custom_relative_and_environment_path(tmp)
    first = custom / "Hearthstone_2026_01_01_00_00_00"
    first.mkdir(parents=True)
    first_log = first / "Power.log"
    first_log.write_text("first\n", encoding="utf-8")
    os.utime(first_log, (1000, 1000))

    second = custom / "Hearthstone_2026_01_01_00_00_01"
    assert bg.newest_power_log() == first_log

    seen = []

    def reader() -> None:
        stream = bg.follow(first_log)
        try:
            for item in stream:
                seen.append(item)
                if item == "rotated\n":
                    return
        finally:
            stream.close()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(0.35)
    with first_log.open("a", encoding="utf-8") as handle:
        handle.write("live\n")
        handle.flush()
    time.sleep(0.35)

    second.mkdir(parents=True)
    second_log = second / "Power.log"
    second_log.write_text("rotated\n", encoding="utf-8")
    future = time.time() + 10
    os.utime(second_log, (future, future))
    thread.join(timeout=8)

    if thread.is_alive():
        # Ensure a failed rotation assertion cannot leave a Windows file handle
        # open while TemporaryDirectory tries to clean up.
        rescue = custom / "Hearthstone_2026_01_01_00_00_02"
        rescue.mkdir(parents=True)
        rescue_log = rescue / "Power.log"
        rescue_log.write_text("stop\n", encoding="utf-8")
        rescue_time = time.time() + 20
        os.utime(rescue_log, (rescue_time, rescue_time))
        thread.join(timeout=3)
    assert not thread.is_alive(), "follow() did not rotate to the configured directory"
    assert "live\n" in seen
    assert "rotated\n" in seen
    assert bg.newest_power_log() == second_log


def test_invalid_and_missing_custom_directory(tmp: Path) -> None:
    invalid = tmp / "invalid-settings.json"
    invalid.write_text("{ not json", encoding="utf-8")
    try:
        bg.load_log_settings(invalid)
    except bg.LogSettingsError as exc:
        assert "Invalid JSON" in str(exc)
        assert "line" in str(exc)
    else:
        raise AssertionError("invalid JSON was accepted")

    bg.configure_log_path(invalid)
    try:
        bg.newest_power_log()
    except bg.LogSettingsError as exc:
        assert "Invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON did not stop log discovery")

    missing_dir = tmp / "does-not-exist"
    settings = tmp / "missing-dir-settings.json"
    write_settings(settings, {"hearthstone_logs_dir": str(missing_dir)})
    bg.configure_log_path(settings)
    assert bg.HS_LOGS == missing_dir.resolve()
    assert bg.HS_LOGS != bg.default_hs_logs_dir()
    assert bg.newest_power_log() is None
    message = bg.no_power_log_message(waiting=True)
    assert str(missing_dir) in message
    assert "source: settings.json" in message
    assert "directory does not exist" in message
    assert "still running" in message


def test_frozen_application_path(tmp: Path) -> None:
    sentinel = object()
    old_frozen = getattr(sys, "frozen", sentinel)
    old_executable = sys.executable
    exe_dir = tmp / "published"
    exe_dir.mkdir()
    try:
        sys.frozen = True
        sys.executable = str(exe_dir / "bgtracker.exe")
        assert bg.application_dir() == exe_dir.resolve()
        assert bg.settings_file_path() == exe_dir.resolve() / "settings.json"
    finally:
        sys.executable = old_executable
        if old_frozen is sentinel:
            del sys.frozen
        else:
            sys.frozen = old_frozen


def test_collect_uses_configured_directory(tmp: Path) -> None:
    import collect

    logs_dir = tmp / "collect-logs"
    log_dir = logs_dir / "Hearthstone_2026_01_01_00_00_00"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "Power.log"
    log_path.write_text("test\n", encoding="utf-8")
    settings = tmp / "collect-settings.json"
    write_settings(settings, {"hearthstone_logs_dir": str(logs_dir)})
    bg.configure_log_path(settings)

    old_data, old_out = collect.DATA, collect.OUT
    old_games_in = collect.games_in
    seen = []
    collect.DATA = tmp / "data"
    collect.OUT = collect.DATA / "games.jsonl"
    collect.games_in = lambda path: seen.append(Path(path)) or []
    try:
        collect.collect()
    finally:
        collect.DATA, collect.OUT = old_data, old_out
        collect.games_in = old_games_in
    assert seen == [log_path]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bgtracker-log-config-") as raw:
        tmp = Path(raw)
        test_default_fallbacks(tmp)
        test_newest_and_rotation(tmp)
        test_invalid_and_missing_custom_directory(tmp)
        test_frozen_application_path(tmp)
        test_collect_uses_configured_directory(tmp)
    bg.configure_log_path(ROOT / "settings.json")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
