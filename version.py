#!/usr/bin/env python3
"""The version number, in one place, plus the comparison the updater needs.

Until now the version lived only in CHANGELOG.md and the git tag, and three
separate files each hard-coded `User-Agent: bgtracker/1.0` because there was
nothing to ask. Everything that has to name this build imports it from here:
the updater, the `--diag` dump every bug report is built on, and the upload
payload, so the server can see which client versions are actually in the wild.

Numbering follows CHANGELOG.md. v0.2.0-alpha is published, so the working tree
is the next one. Bump this in the same commit as the CHANGELOG heading and
build the release from that commit: `build.py` writes this string into
`version.txt` inside the build, and `server/make_manifest.py` reads it back out
of the zip and refuses to write a manifest that disagrees with it - a wrong
number here would otherwise become a wrong number in the file every client
fetches.

The comparison is semver's, not a string compare: "0.10.0" is newer than
"0.9.0" (a string compare says the opposite, which is the classic way an
updater goes quiet forever), and a prerelease is older than the release it
leads to, so 0.3.1-alpha < 0.3.0.
"""

from __future__ import annotations

import re

VERSION = "0.3.1-alpha"

#: What this build calls itself over HTTP. Also what the aggregator logs.
USER_AGENT = f"bgtracker/{VERSION}"

# Digits, letters, dots and hyphens only, with an optional leading "v" (git
# tags carry one, manifests should not) and an optional "+build" tail, which
# semver says takes no part in precedence and is therefore dropped.
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse(v: str) -> tuple[tuple[int, int, int], tuple[str, ...]]:
    """("0.3.1-alpha") -> ((0, 3, 0), ("alpha",)). Raises ValueError on junk.

    Junk is a real case, not a theoretical one: the updater has to survive a
    manifest that has been truncated, edited by hand, or replaced by a captive
    portal's login page, and "the version field is not a version" is how most
    of that arrives.
    """
    if not isinstance(v, str):
        raise ValueError(f"version is {type(v).__name__}, not a string")
    m = _VERSION_RE.match(v.strip())
    if not m:
        raise ValueError(f"not a version number: {v!r}")
    parts = [int(p) for p in m.group(1).split(".")][:3]
    while len(parts) < 3:            # "0.3" and "0.3.0" are the same release
        parts.append(0)
    pre = tuple(p for p in (m.group(2) or "").split(".") if p)
    return (parts[0], parts[1], parts[2]), pre


def sort_key(v: str):
    """A key that orders versions correctly under plain `<`."""
    release, pre = parse(v)
    if not pre:
        # No prerelease tag outranks every prerelease of the same release.
        return release, (1,)
    return release, (0,) + tuple(
        # Numeric identifiers compare numerically and rank below alphanumeric
        # ones, so alpha.2 < alpha.10 and alpha.2 < beta.
        (0, int(p), "") if p.isdigit() else (1, 0, p)
        for p in pre
    )


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """True when `candidate` is a version worth offering to `current`."""
    return sort_key(candidate) > sort_key(current)


if __name__ == "__main__":
    print(VERSION)
