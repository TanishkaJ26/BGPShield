"""Tests for the curated incident list and the recall calculation (plan Sections 11, 14).

The real list at ``config/incidents.yaml`` is loaded too, because an error in it would
silently corrupt every recall number computed from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bgpshield.incidents import (
    IncidentKind,
    IncidentResult,
    Outcome,
    load_incidents,
    recall,
)

REAL_LIST = Path("config/incidents.yaml")


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "incidents.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_the_fields_that_matter(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
incidents:
  - id: test-leak
    kind: route_leak
    verified: true
    description: a leak
    window_start_utc: "2026-01-01T00:00:00Z"
    window_end_utc: "2026-01-01T04:00:00Z"
    leaker_asn: 64496
    sources: [https://example.invalid/post-mortem]
""",
    )
    incident = load_incidents(path)[0]
    assert incident.id == "test-leak"
    assert incident.kind is IncidentKind.ROUTE_LEAK
    assert incident.verified
    assert incident.culprit_asn == 64496
    assert incident.expected_leaker_asns == (64496,)
    assert incident.has_window
    assert incident.detectable_by_leak_detector


def test_a_hijacker_is_read_as_the_culprit_too(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
incidents:
  - id: test-hijack
    kind: origin_hijack
    verified: true
    description: a hijack
    hijacker_asn: 64510
    sources: []
""",
    )
    incident = load_incidents(path)[0]
    assert incident.culprit_asn == 64510
    assert not incident.detectable_by_leak_detector


def test_expected_leakers_can_differ_from_the_blamed_network(tmp_path: Path) -> None:
    """The network a post-mortem blames and the network that turned the path around are not
    always the same. Both must be accepted or a correct detection scores as a miss."""
    path = write(
        tmp_path,
        """
incidents:
  - id: test
    kind: route_leak
    verified: true
    description: x
    leaker_asn: 64496
    expected_leaker_asns: [64497, 64496]
    sources: []
""",
    )
    incident = load_incidents(path)[0]
    assert incident.culprit_asn == 64496
    assert set(incident.expected_leaker_asns) == {64496, 64497}


def test_an_unverified_entry_is_loaded_but_flagged(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
incidents:
  - id: rumour
    kind: route_leak
    verified: false
    description: heard about this somewhere
    sources: []
""",
    )
    incident = load_incidents(path)[0]
    assert not incident.verified


# ---------------------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------------------


def result(kind: IncidentKind, outcome: Outcome, name: str = "x") -> IncidentResult:
    return IncidentResult(incident_id=name, kind=kind, outcome=outcome)


def test_only_route_leaks_count_towards_recall() -> None:
    """An origin hijack travels an ordinary path and an RPKI misuse incident had correct
    routing. Counting either as a miss would punish the detector for something it was never
    built to see."""
    summary = recall(
        [
            result(IncidentKind.ROUTE_LEAK, Outcome.DETECTED),
            result(IncidentKind.ORIGIN_HIJACK, Outcome.NOT_APPLICABLE),
            result(IncidentKind.RPKI_MISUSE, Outcome.NOT_APPLICABLE),
        ]
    )
    assert summary["curated_incidents"] == 3
    assert summary["route_leaks"] == 1
    assert summary["not_applicable"] == 2
    assert summary["judged"] == 1
    assert summary["recall"] == 1.0


def test_an_invisible_leak_is_not_a_miss() -> None:
    """If nothing resembling the leak reached the collectors, there was nothing to detect.
    This is collector visibility bias, which plan Section 15 lists as a threat."""
    summary = recall(
        [
            result(IncidentKind.ROUTE_LEAK, Outcome.DETECTED),
            result(IncidentKind.ROUTE_LEAK, Outcome.NOT_VISIBLE),
        ]
    )
    assert summary["judged"] == 1
    assert summary["not_visible"] == 1
    assert summary["missed"] == 0
    assert summary["recall"] == 1.0


def test_a_real_miss_counts_against_recall() -> None:
    summary = recall(
        [
            result(IncidentKind.ROUTE_LEAK, Outcome.DETECTED),
            result(IncidentKind.ROUTE_LEAK, Outcome.MISSED),
        ]
    )
    assert summary["judged"] == 2
    assert summary["detected"] == 1
    assert summary["missed"] == 1
    assert summary["recall"] == 0.5


def test_recall_is_none_when_nothing_could_be_judged() -> None:
    """Reporting 0 percent, or 100 percent, from an empty denominator would be a lie."""
    summary = recall([result(IncidentKind.ROUTE_LEAK, Outcome.NO_DATA)])
    assert summary["recall"] is None


def test_empty_input() -> None:
    assert recall([])["recall"] is None


# ---------------------------------------------------------------------------------------
# The real curated list
# ---------------------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_LIST.exists(), reason="curated list not present")
def test_the_real_list_is_well_formed() -> None:
    curated = load_incidents(REAL_LIST)
    assert len(curated) >= 5
    for incident in curated:
        assert incident.description, f"{incident.id} has no description"
        assert incident.sources, f"{incident.id} cites no source"
        if incident.verified and incident.kind is not IncidentKind.RPKI_MISUSE:
            assert incident.culprit_asn, f"{incident.id} names no culprit"
        if incident.detectable_by_leak_detector and incident.verified:
            assert incident.has_window, f"{incident.id} has no analysis window"


@pytest.mark.skipif(not REAL_LIST.exists(), reason="curated list not present")
def test_every_entry_in_the_real_list_is_verified() -> None:
    """Rule 3 forbids computing anything from an unverified entry, so none should remain."""
    unverified = [i.id for i in load_incidents(REAL_LIST) if not i.verified]
    assert unverified == []


@pytest.mark.skipif(not REAL_LIST.exists(), reason="curated list not present")
def test_windows_bracket_the_incident() -> None:
    """Plan Section 8 asks for the incident plus two hours either side."""
    for incident in load_incidents(REAL_LIST):
        if not incident.has_window:
            continue
        assert incident.window_start is not None and incident.window_end is not None
        assert incident.window_start < incident.window_end, incident.id
        start = incident.raw.get("start_utc")
        if start:
            from datetime import datetime

            core = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            assert incident.window_start <= core, incident.id
