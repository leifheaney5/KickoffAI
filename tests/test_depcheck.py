"""Tests for the dependency freshness check.

Every case here describes an environment by hand — an interpreter version, a
version-lookup function, a date — so nothing installs anything and nothing
touches the network. That is the point of the design: the check has to be able
to run in CI, where the vision extras are absent and PyPI may not be reachable.
"""

import datetime as dt

import depcheck as D


TODAY = dt.date(2026, 8, 20)


def env(**versions):
    """A version_lookup over a fixed dict; anything absent is not installed."""
    return lambda dist: versions.get(dist)


# --------------------------------------------------------------------------- #
# Version parsing
# --------------------------------------------------------------------------- #
def test_versions_compare_numerically_not_as_strings():
    # The bug this guards: "2025.10.14" > "2025.9.1" is false as a string.
    assert D.parse_version("2025.10.14") > D.parse_version("2025.9.1")
    assert D.parse_version("8.10.0") > D.parse_version("8.9.0")


def test_suffixes_are_truncated_rather_than_rejected():
    assert D.parse_version("2.8.0+cpu") == (2, 8, 0)
    assert D.parse_version("1.2.3rc1") == (1, 2, 3)
    # A segment with no leading digit ends the parse rather than guessing.
    assert D.parse_version("2.0.0.post1") == (2, 0, 0)


def test_an_unparseable_version_sorts_as_too_old():
    """Failing towards "stale" is the safe direction for this check."""
    assert D.parse_version("unknown") == ()
    assert D.parse_version("unknown") < D.parse_version("0.0.1")


def test_date_versions_become_dates():
    assert D.version_release_date("2025.10.14") == dt.date(2025, 10, 14)
    assert D.version_release_date("2.8.0") is None      # not a plausible year
    assert D.version_release_date("8.4") is None        # not enough parts
    assert D.version_release_date("2025.13.99") is None  # not a real date


# --------------------------------------------------------------------------- #
# The interpreter floor — the check that would have caught the incident
# --------------------------------------------------------------------------- #
def test_python_39_fails_loudly():
    f = D.check_python(version_info=(3, 9, 6))

    assert f.level == D.ERROR
    assert f.failed is True
    # The message has to explain the silence, not just state a number.
    assert "yt-dlp" in f.message
    assert "3.13" in f.message


def test_python_313_passes():
    assert D.check_python(version_info=(3, 13, 13)).level == D.OK


def test_a_newer_python_also_passes():
    assert D.check_python(version_info=(3, 14, 0)).level == D.OK


# --------------------------------------------------------------------------- #
# Per-package judgement
# --------------------------------------------------------------------------- #
def test_the_frozen_ytdlp_from_the_incident_is_flagged():
    """2025.10.14 is the exact build Python 3.9 pinned the project to."""
    f = D.check_package(D.CRITICAL["yt-dlp"], "2025.10.14", today=TODAY)

    assert f.level == D.STALE
    assert f.failed is True
    assert "pip install --upgrade yt-dlp" in f.message


def test_a_current_ytdlp_passes_the_age_check():
    recent = (TODAY - dt.timedelta(days=10)).strftime("%Y.%m.%d")

    f = D.check_package(D.CRITICAL["yt-dlp"], recent, today=TODAY)

    assert f.level == D.OK
    assert "10 days old" in f.message


def test_ytdlp_staleness_is_judged_purely_on_age():
    """Age is the whole signal: extractors rot on a clock, not on a version bump."""
    pkg = D.CRITICAL["yt-dlp"]
    assert pkg.min_version is None
    old = (TODAY - dt.timedelta(days=pkg.max_age_days + 1)).strftime("%Y.%m.%d")

    f = D.check_package(pkg, old, today=TODAY)

    assert f.level == D.STALE
    assert "days ago" in f.message


def test_a_non_date_version_on_a_date_versioned_tool_is_an_error():
    f = D.check_package(D.CRITICAL["yt-dlp"], "1.2.3", today=TODAY)

    assert f.level == D.ERROR


def test_a_version_below_the_floor_is_stale():
    f = D.check_package(D.CRITICAL["numpy"], "2.0.2", today=TODAY)

    assert f.level == D.STALE
    assert "2.1.0" in f.message


def test_a_version_at_the_floor_passes():
    assert D.check_package(D.CRITICAL["numpy"], "2.1.0", today=TODAY).level == D.OK


def test_missing_is_reported_but_does_not_fail():
    """The vision extras are optional; absent must not read as broken."""
    f = D.check_package(D.CRITICAL["torch"], None, today=TODAY)

    assert f.level == D.MISSING
    assert f.failed is False


# --------------------------------------------------------------------------- #
# Whole-environment runs
# --------------------------------------------------------------------------- #
def test_the_incident_environment_fails_on_both_counts():
    findings = D.check_all(
        version_lookup=env(**{"yt-dlp": "2025.10.14", "numpy": "2.0.2",
                              "torch": "2.8.0", "ultralytics": "8.4.67"}),
        today=TODAY,
        version_info=(3, 9, 6),
    )
    bad = {f.name for f in D.failures(findings)}

    # The interpreter is the cause; yt-dlp, numpy and torch are all symptoms of
    # it, and every one of them installed "successfully" at the time.
    assert "python" in bad
    assert "yt-dlp" in bad
    assert "numpy" in bad
    assert "torch" in bad


def test_a_healthy_313_environment_has_no_failures():
    fresh = (TODAY - dt.timedelta(days=5)).strftime("%Y.%m.%d")
    findings = D.check_all(
        version_lookup=env(**{"yt-dlp": fresh, "numpy": "2.5.2",
                              "torch": "2.9.1", "ultralytics": "8.4.67"}),
        today=TODAY,
        version_info=(3, 13, 13),
    )

    assert D.failures(findings) == []


def test_a_bare_ci_environment_passes_because_extras_are_only_missing():
    findings = D.check_all(
        version_lookup=env(),          # nothing installed at all
        today=TODAY,
        version_info=(3, 13, 13),
    )

    assert D.failures(findings) == []
    assert all(f.level == D.MISSING for f in findings if f.name != "python")


# --------------------------------------------------------------------------- #
# Reporting — it has to be visible, and it has to fail the exit code
# --------------------------------------------------------------------------- #
def test_the_report_marks_failures_visibly():
    findings = D.check_all(
        version_lookup=env(**{"yt-dlp": "2025.10.14"}),
        today=TODAY,
        version_info=(3, 9, 6),
    )
    text = D.format_report(findings)

    assert "STALE" in text
    assert "FAIL" in text
    assert "problem(s)" in text


def test_a_clean_report_says_nothing_alarming():
    text = D.format_report(D.check_all(
        version_lookup=env(), today=TODAY, version_info=(3, 13, 13)))

    assert "STALE" not in text
    assert "problem(s)" not in text


def test_main_exits_nonzero_when_something_is_stale(monkeypatch):
    monkeypatch.setattr(D, "check_all", lambda: [D.Finding("x", D.STALE, "old")])

    assert D.main([]) == 1


def test_warn_only_still_prints_but_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(D, "check_all", lambda: [D.Finding("x", D.STALE, "old")])

    assert D.main(["--warn-only"]) == 0
    assert "STALE" in capsys.readouterr().out


def test_main_exits_zero_on_a_clean_environment(monkeypatch):
    monkeypatch.setattr(D, "check_all", lambda: [D.Finding("x", D.OK, "fine")])

    assert D.main([]) == 0


# --------------------------------------------------------------------------- #
# The online path — exercised with an injected fetch, never a real request
# --------------------------------------------------------------------------- #
def test_behind_the_published_release_is_stale(monkeypatch):
    monkeypatch.setattr(D, "installed_version", lambda dist: "2025.10.14")

    findings = D.check_against_pypi(
        packages={"yt-dlp": D.CRITICAL["yt-dlp"]},
        fetch=lambda dist: "2026.08.01",
    )

    assert findings[0].level == D.STALE
    assert "2026.08.01" in findings[0].message


def test_an_unreachable_pypi_does_not_fail_the_check(monkeypatch):
    """A flaky network must not be able to invent a dependency problem."""
    monkeypatch.setattr(D, "installed_version", lambda dist: "2025.10.14")

    findings = D.check_against_pypi(
        packages={"yt-dlp": D.CRITICAL["yt-dlp"]},
        fetch=lambda dist: None,
    )

    assert findings[0].level == D.OK
    assert "unreachable" in findings[0].message
