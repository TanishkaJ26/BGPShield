"""Curated incidents and recall against them (plan Sections 11 Phase 5, and 14).

## What recall can and cannot mean here

The curated list holds three different kinds of event, and only one of them is something a
path-based leak detector could ever find:

* a **route leak** has a mis-shaped path, so ``hijax detect`` should flag it;
* an **origin hijack** may travel a perfectly ordinary path, so only origin validation
  applies;
* an **RPKI misuse** incident had correct routing and forged records, so neither applies.

Recall is therefore measured only over the ``route_leak`` entries. Counting the others would
either flatter the detector or punish it for missing something it was never built to see.

Even within that subset, a miss has several innocent explanations that have to be separated
from a genuine failure: the archive may not have kept the update files, the culprit may never
appear in any collector's view, or the leak may simply never have reached the collectors at
all. That last case is the important one and the easiest to get wrong. A leak confined to one
city, lasting twenty-five minutes, can be entirely invisible to a collector on another
continent while that collector happily records hundreds of thousands of other announcements.
Calling that a detector failure would blame the software for the shape of the measurement
infrastructure, so it is reported as its own outcome.

Visibility is tested by asking whether anything resembling the leak, meaning routes relayed
*through* the culprit rather than originated by it, appears during the incident itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class IncidentKind(StrEnum):
    ROUTE_LEAK = "route_leak"
    ORIGIN_HIJACK = "origin_hijack"
    RPKI_MISUSE = "rpki_misuse"


@dataclass(frozen=True, slots=True)
class Incident:
    """One curated incident, exactly as verified from its primary source."""

    id: str
    kind: IncidentKind
    verified: bool
    description: str
    window_start: datetime | None
    window_end: datetime | None
    culprit_asn: int | None
    """The leaking or hijacking AS, whichever applies. ``None`` for RPKI misuse."""
    sources: tuple[str, ...]
    expected_leaker_asns: tuple[int, ...] = ()
    """Every AS that a path-based detector could legitimately name for this incident.

    The network that *caused* a leak and the network that *performed* it are not always the
    same. A faulty optimizer at one network can make a different network turn the path
    around, and only the second one is visible in an AS_PATH. Post-mortems usually name the
    first. Listing both stops a correct detection being scored as a miss."""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def detectable_by_leak_detector(self) -> bool:
        return self.kind is IncidentKind.ROUTE_LEAK

    @property
    def has_window(self) -> bool:
        return self.window_start is not None and self.window_end is not None


class Outcome(StrEnum):
    """Why an incident did or did not turn up in the detector's output."""

    DETECTED = "detected"
    """The culprit was flagged as the leaker somewhere in the window."""
    MISSED = "missed"
    """Routes were examined but the culprit was never flagged. A genuine miss."""
    CULPRIT_ABSENT = "culprit_absent"
    """The culprit never appeared on any path the collectors recorded, so there was
    nothing to detect. Not a detector failure."""
    NOT_VISIBLE = "not_visible"
    """The culprit appears on ordinary paths, but nothing resembling the leak reaches these
    collectors during the incident itself. The leak was real and the vantage points simply
    could not see it, which plan Section 15 lists as collector visibility bias. Counting this
    as a miss would blame the detector for the shape of the measurement infrastructure."""
    NO_DATA = "no_data"
    """No update files could be fetched for the window."""
    NOT_APPLICABLE = "not_applicable"
    """This kind of incident is not something a path-based detector can see."""


@dataclass(slots=True)
class IncidentResult:
    """What happened when the detector was pointed at one incident."""

    incident_id: str
    kind: IncidentKind
    outcome: Outcome
    routes_examined: int = 0
    paths_with_culprit: int = 0
    candidates_found: int = 0
    culprit_flagged: int = 0
    note: str = ""


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def load_incidents(path: Path) -> list[Incident]:
    """Read and validate ``config/incidents.yaml``.

    An entry marked ``verified: false`` is loaded but flagged, so a caller can refuse to
    compute anything from it. Section 0 rule 3 forbids treating unverified entries as data.
    """
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    entries = document.get("incidents") or []

    out: list[Incident] = []
    for entry in entries:
        culprit = entry.get("leaker_asn") or entry.get("hijacker_asn")
        out.append(
            Incident(
                id=str(entry["id"]),
                kind=IncidentKind(str(entry.get("kind", "route_leak"))),
                verified=bool(entry.get("verified", False)),
                description=str(entry.get("description", "")).strip(),
                window_start=_parse_time(entry.get("window_start_utc")),
                window_end=_parse_time(entry.get("window_end_utc")),
                culprit_asn=int(culprit) if culprit else None,
                expected_leaker_asns=tuple(int(a) for a in entry.get("expected_leaker_asns", ()))
                or ((int(culprit),) if culprit else ()),
                sources=tuple(entry.get("sources", ())),
                raw=dict(entry),
            )
        )
    return out


def recall(results: list[IncidentResult]) -> dict[str, Any]:
    """Recall over the incidents the detector could in principle have found.

    The denominator is the number of route leaks where routes were actually examined and the
    culprit appeared on at least one path. Incidents with no data, or where the culprit never
    showed up in any collector's view, are reported separately rather than counted as misses,
    because neither says anything about the detector.
    """
    leaks = [r for r in results if r.kind is IncidentKind.ROUTE_LEAK]
    judged = [r for r in leaks if r.outcome in (Outcome.DETECTED, Outcome.MISSED)]
    detected = [r for r in judged if r.outcome is Outcome.DETECTED]
    return {
        "curated_incidents": len(results),
        "route_leaks": len(leaks),
        "judged": len(judged),
        "detected": len(detected),
        "missed": len(judged) - len(detected),
        "recall": len(detected) / len(judged) if judged else None,
        "no_data": sum(1 for r in leaks if r.outcome is Outcome.NO_DATA),
        "culprit_absent": sum(1 for r in leaks if r.outcome is Outcome.CULPRIT_ABSENT),
        "not_visible": sum(1 for r in leaks if r.outcome is Outcome.NOT_VISIBLE),
        "not_applicable": sum(1 for r in results if r.outcome is Outcome.NOT_APPLICABLE),
    }
