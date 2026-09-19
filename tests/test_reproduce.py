"""Tests for the reproduction check (plan Sections 11 Phase 7, and 12).

The comparison is the thing worth pinning down: it is what tells an outsider whether the
numbers in the write-up are real, so it has to notice a difference and refuse to be quiet
about one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hijax.reproduce import EXACT_KEYS, compare, fixture_path, load_fixture, write_fixture

BASELINE: dict[str, Any] = {
    "routes": 100,
    "peers": 4,
    "prefixes": 50,
    "dump_bytes": 1234,
    "rov_valid": 60,
    "rov_invalid": 2,
    "rov_not_found": 38,
    "aspa_valid": 10,
    "aspa_invalid": 1,
    "aspa_unknown": 89,
    "vrps": 500,
    "aspa_records": 7,
    "flag_rates": {"loop": 0.000334, "as_set": 0.000153},
}


def test_an_identical_run_matches() -> None:
    assert compare(dict(BASELINE), dict(BASELINE)).matches


def test_a_changed_count_is_reported_with_the_difference() -> None:
    fresh = dict(BASELINE, routes=99)
    result = compare(fresh, dict(BASELINE))
    assert not result.matches
    assert any("routes" in line and "-1" in line for line in result.problems)


def test_a_missing_number_is_not_quietly_passed() -> None:
    """A rerun that produced nothing for a key must fail, not skip the comparison."""
    fresh = {k: v for k, v in BASELINE.items() if k != "vrps"}
    result = compare(fresh, dict(BASELINE))
    assert not result.matches
    assert any("vrps" in line for line in result.problems)


def test_a_drifting_drop_rate_is_caught() -> None:
    """The normalization drop rates are a Phase 2 deliverable and would otherwise drift
    silently when the path parser changes."""
    fresh = dict(BASELINE, flag_rates={"loop": 0.000999, "as_set": 0.000153})
    result = compare(fresh, dict(BASELINE))
    assert not result.matches
    assert any("flag_rate[loop]" in line for line in result.problems)


def test_a_new_flag_appearing_is_caught() -> None:
    fresh = dict(BASELINE, flag_rates={**BASELINE["flag_rates"], "private_asn": 0.001})
    result = compare(fresh, dict(BASELINE))
    assert not result.matches
    assert any("private_asn" in line for line in result.problems)


def test_every_exact_key_is_actually_compared() -> None:
    """A number recorded but never checked looks like evidence and is not. `dump_bytes` sat
    at 0 in the fixture for exactly this reason before it was added to the comparison."""
    for key in EXACT_KEYS:
        fresh = dict(BASELINE)
        fresh[key] = BASELINE[key] + 1
        result = compare(fresh, dict(BASELINE))
        assert not result.matches, f"{key} is in EXACT_KEYS but a change to it went unnoticed"


def test_a_fixture_round_trips(tmp_path: Path) -> None:
    written = write_fixture(tmp_path, dict(BASELINE))
    assert written == fixture_path(tmp_path)
    assert json.loads(written.read_text(encoding="utf-8")) == BASELINE
    assert load_fixture(tmp_path) == BASELINE


def test_a_missing_fixture_reads_as_none(tmp_path: Path) -> None:
    assert load_fixture(tmp_path) is None
