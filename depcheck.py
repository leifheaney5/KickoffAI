#!/usr/bin/env python3
"""
Kickoff Pulse — dependency freshness check.

This module exists because of a real, expensive failure. The project venv was
built on Python 3.9. yt-dlp had already dropped 3.9, so `pip install --upgrade
yt-dlp` kept resolving to an October 2025 build and reported success every time.
YouTube extractors rot fast; that frozen build could only resolve 360p. Nothing
errored, so the 360p ceiling got written down as "YouTube PO-token gating" and
the roadmap was steered around a limitation that did not exist. A current yt-dlp
resolves 1080p and 4K on the same URLs.

The failure mode is not "a dependency broke". It is "a dependency quietly stayed
old because the interpreter was too old, and pip said OK". Nothing in the app
could see it. So this check looks at three things that are all knowable offline:

  1. the running interpreter against the floor the project needs,
  2. installed versions against the floors in the requirements files,
  3. the age of date-versioned tools, read straight out of their version string.

All three are comparisons over locally available facts, so this runs in CI and
in tests without touching the network. `--online` exists for the one case worth
a real query — asking PyPI what the actual latest is — and the tests never use
it.

The check reports rather than repairs, but it reports loudly: `main()` exits
non-zero so a launcher or a CI step cannot step over a stale toolchain.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# The interpreter floor. 3.13 is not a preference — it is the version at which
# current builds of the whole stack (yt-dlp, numpy, torch, ultralytics) are
# actually installable. Anything older silently resolves to archived wheels.
REQUIRED_PYTHON: Tuple[int, int] = (3, 13)

OK = "ok"
STALE = "stale"
MISSING = "missing"
ERROR = "error"

# Levels that mean "do not carry on as if this were fine".
FAILING = (STALE, ERROR)


@dataclass(frozen=True)
class Package:
    """A dependency worth watching, and what "current enough" means for it."""

    dist: str                 # name on PyPI and in the requirements files
    module: str               # import name, when it differs from `dist`
    why: str                  # what goes wrong in this app when it goes stale
    min_version: Optional[str] = None
    # yt-dlp versions are release dates (2025.10.14). That makes staleness
    # measurable without asking anyone: parse the version, subtract from today.
    date_versioned: bool = False
    max_age_days: int = 90


# Only tools whose staleness is invisible from inside the app belong here. A
# stale pandas raises somewhere; a stale yt-dlp just returns worse answers.
CRITICAL: Dict[str, Package] = {
    "yt-dlp": Package(
        dist="yt-dlp",
        module="yt_dlp",
        why=(
            "YouTube extractors break every few weeks. A stale yt-dlp does not "
            "error, it resolves lower-quality formats or none at all."
        ),
        # No version floor on purpose. Naming a "known good" yt-dlp release here
        # would need updating by hand and would go stale exactly like the thing
        # it is meant to catch. Age is the honest signal and it maintains
        # itself, because the version string is the release date.
        date_versioned=True,
        # yt-dlp ships every few weeks. Three months behind is already enough to
        # have lost formats on a live URL.
        max_age_days=90,
    ),
    "numpy": Package(
        dist="numpy",
        module="numpy",
        # 2.0.2 was the last numpy that installed on 3.9, so a fresh venv
        # holding it means the interpreter, not a pin, chose the version.
        why="Something is capping it: an old interpreter, or another package's pin.",
        min_version="2.1.0",
    ),
    "torch": Package(
        dist="torch",
        module="torch",
        # Same tell-tale as numpy: 2.8.0 is the newest torch 3.9 could resolve.
        why="A held-back torch drags the Eye onto slower kernels.",
        min_version="2.9.0",
    ),
    "ultralytics": Package(
        dist="ultralytics",
        module="ultralytics",
        why="Tracker and model-loading fixes land continuously.",
        min_version="8.3.0",
    ),
}


@dataclass(frozen=True)
class Finding:
    """One line of the report: what was checked, how it went, why it matters."""

    name: str
    level: str
    message: str

    @property
    def failed(self) -> bool:
        return self.level in FAILING


def parse_version(text: str) -> Tuple[int, ...]:
    """Return `text` as a comparable tuple of ints.

    Deliberately lenient: suffixes (rc1, .post0, +cpu) are truncated rather than
    rejected, because this answers "is it at least X", not full PEP 440
    ordering. An unparseable leading segment gives an empty tuple, which sorts
    below every real version and so reads as "too old" — the safe direction.
    """
    parts: List[int] = []
    for chunk in str(text).split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def version_release_date(version: str) -> Optional[_dt.date]:
    """Read the release date out of a date-based version like 2025.10.14."""
    parts = parse_version(version)
    if len(parts) < 3:
        return None
    year, month, day = parts[0], parts[1], parts[2]
    if not 2000 <= year <= 2999:
        return None
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def installed_version(dist: str) -> Optional[str]:
    """Installed version of `dist`, or None when it is not installed."""
    from importlib import metadata

    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def check_python(
    version_info: Optional[Sequence[int]] = None,
    required: Tuple[int, int] = REQUIRED_PYTHON,
) -> Finding:
    """Compare the running interpreter against the floor the project needs.

    This is the check that would have caught the original incident on day one.
    """
    current = tuple(version_info or sys.version_info[:2])[:2]
    shown = ".".join(str(n) for n in current)
    want = ".".join(str(n) for n in required)
    if current >= required:
        return Finding("python", OK, f"Python {shown} (floor {want})")
    return Finding(
        "python",
        ERROR,
        f"Python {shown} is below the {want} floor. pip will keep resolving "
        f"archived builds of yt-dlp, numpy and torch, and will report success "
        f"while doing it. Rebuild the venv on Python {want}.",
    )


def check_package(
    pkg: Package,
    version: Optional[str],
    today: Optional[_dt.date] = None,
) -> Finding:
    """Judge one package from its installed version. No network, no imports."""
    if version is None:
        # Absent is not the same as stale: the vision extras are optional, so
        # the caller decides whether a missing package matters.
        return Finding(pkg.dist, MISSING, f"{pkg.dist} is not installed")

    if pkg.min_version and parse_version(version) < parse_version(pkg.min_version):
        return Finding(
            pkg.dist,
            STALE,
            f"{pkg.dist} {version} is below the {pkg.min_version} floor. {pkg.why}",
        )

    if pkg.date_versioned:
        released = version_release_date(version)
        if released is None:
            return Finding(
                pkg.dist,
                ERROR,
                f"{pkg.dist} {version} is not a date version, so its age cannot "
                f"be checked. Expected something like 2026.01.15.",
            )
        age = ((today or _dt.date.today()) - released).days
        if age > pkg.max_age_days:
            return Finding(
                pkg.dist,
                STALE,
                f"{pkg.dist} {version} was released {age} days ago (limit "
                f"{pkg.max_age_days}). {pkg.why} Fix: pip install --upgrade "
                f"{pkg.dist}",
            )
        days = "day" if age == 1 else "days"
        return Finding(pkg.dist, OK, f"{pkg.dist} {version} ({age} {days} old)")

    return Finding(pkg.dist, OK, f"{pkg.dist} {version}")


def check_all(
    packages: Optional[Dict[str, Package]] = None,
    version_lookup: Callable[[str], Optional[str]] = installed_version,
    today: Optional[_dt.date] = None,
    version_info: Optional[Sequence[int]] = None,
) -> List[Finding]:
    """Run every offline check and return the findings in report order.

    `version_lookup`, `today` and `version_info` are injected so a test can
    describe a whole environment without installing anything or moving a clock.
    """
    findings = [check_python(version_info=version_info)]
    for pkg in (packages or CRITICAL).values():
        findings.append(check_package(pkg, version_lookup(pkg.dist), today=today))
    return findings


def failures(findings: Sequence[Finding]) -> List[Finding]:
    return [f for f in findings if f.failed]


_MARK = {OK: "  ok  ", STALE: " STALE", MISSING: "  --  ", ERROR: " FAIL "}


def format_report(findings: Sequence[Finding]) -> str:
    """Plain-text report. Failures are marked so they survive a wall of log."""
    lines = ["Kickoff Pulse — dependency freshness"]
    for f in findings:
        lines.append(f"[{_MARK.get(f.level, '  ??  ')}] {f.message}")
    bad = failures(findings)
    if bad:
        lines.append("")
        lines.append(
            f"{len(bad)} problem(s). A stale toolchain fails quietly — it "
            "returns worse answers instead of errors — so fix these before "
            "trusting what the pipeline produces."
        )
    return "\n".join(lines)


def latest_on_pypi(dist: str, timeout: float = 5.0) -> Optional[str]:
    """Ask PyPI for the newest published version. Network. Not used by tests.

    Returns None on any failure. This check is an extra; a flaky network must
    not be able to turn the offline verdict into a failure.
    """
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{dist}/json", timeout=timeout
        ) as resp:
            return str(json.load(resp)["info"]["version"])
    except Exception:
        return None


def check_against_pypi(
    packages: Optional[Dict[str, Package]] = None,
    fetch: Callable[[str], Optional[str]] = latest_on_pypi,
) -> List[Finding]:
    """Compare installed versions with the newest published release."""
    findings: List[Finding] = []
    for pkg in (packages or CRITICAL).values():
        have = installed_version(pkg.dist)
        if have is None:
            findings.append(Finding(pkg.dist, MISSING, f"{pkg.dist} is not installed"))
            continue
        latest = fetch(pkg.dist)
        if latest is None:
            findings.append(
                Finding(pkg.dist, OK, f"{pkg.dist} {have} (PyPI unreachable)")
            )
        elif parse_version(have) < parse_version(latest):
            findings.append(
                Finding(
                    pkg.dist,
                    STALE,
                    f"{pkg.dist} {have} is behind the published {latest}. {pkg.why}",
                )
            )
        else:
            findings.append(Finding(pkg.dist, OK, f"{pkg.dist} {have} is current"))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report stale critical dependencies and an out-of-date interpreter."
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="also ask PyPI for the newest release of each critical package",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="print the report but exit 0 (for launchers that must not block)",
    )
    args = parser.parse_args(argv)

    findings = check_all()
    if args.online:
        findings += check_against_pypi()

    print(format_report(findings))
    return 0 if args.warn_only or not failures(findings) else 1


if __name__ == "__main__":
    raise SystemExit(main())
