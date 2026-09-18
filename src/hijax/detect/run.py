"""Run leak detection over a day of stored routes (plan Sections 10.4 and 11, Phase 5)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from hijax.config import Config
from hijax.detect.leaks import (
    LeakFinding,
    LeakObservation,
    collect_findings,
    detect_in_path,
)
from hijax.topology import RelSource, SiblingSource

LEAKS_SCHEMA: dict[str, pl.DataType] = {
    "snapshot_date": pl.Date(),
    "prefix": pl.Utf8(),
    "leaker_asn": pl.Int64(),
    "leak_type": pl.Utf8(),
    "observations": pl.Int64(),
    "distinct_peers": pl.Int64(),
    "distinct_collectors": pl.Int64(),
    "corroborated": pl.Boolean(),
    "example_path": pl.List(pl.Int64()),
}


@dataclass(slots=True)
class DetectionSummary:
    """Raw and filtered counts, both of which plan Section 10.4 requires to be reported."""

    snapshot_date: date
    routes_examined: int = 0
    observations: int = 0
    findings: int = 0
    corroborated: int = 0
    by_type: Counter[str] = field(default_factory=Counter)


def routes_for(cfg: Config, collector: str, day: date) -> Path:
    return (
        cfg.paths.processed
        / "routes"
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={collector}"
        / "routes.parquet"
    )


def detect_day(
    cfg: Config,
    collectors: list[str],
    day: date,
    relationships: RelSource,
    siblings: SiblingSource | None = None,
    *,
    min_peers: int = 2,
    write: bool = True,
) -> tuple[DetectionSummary, list[LeakFinding]]:
    """Scan every stored route for leaks and apply the multi-vantage guard.

    Paths repeat heavily across peers and prefixes, so the direction analysis is memoised on
    the path itself, as in Phase 3.
    """
    summary = DetectionSummary(snapshot_date=day)
    observations: list[LeakObservation] = []
    cache: dict[tuple[int, ...], bool] = {}

    for collector in collectors:
        source = routes_for(cfg, collector, day)
        if not source.exists():
            continue
        frame = pl.read_parquet(source, columns=["peer_ip", "prefix", "as_path"])
        summary.routes_examined += frame.height
        for peer_ip, prefix, as_path in frame.iter_rows():
            path = tuple(as_path)
            if len(path) < 3:
                continue
            if cache.get(path) is False:
                continue
            found = detect_in_path(collector, peer_ip, prefix, path, relationships, siblings)
            if not found:
                cache[path] = False
                continue
            cache[path] = True
            observations.extend(found)

    summary.observations = len(observations)
    findings = collect_findings(observations, min_peers=min_peers)
    summary.findings = len(findings)
    summary.corroborated = sum(1 for f in findings if f.corroborated)
    for finding in findings:
        summary.by_type[str(finding.leak_type)] += 1

    if write and findings:
        out = cfg.paths.processed / "leaks" / f"snapshot_date={day:%Y-%m-%d}"
        out.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            {
                "snapshot_date": [day] * len(findings),
                "prefix": [f.prefix for f in findings],
                "leaker_asn": [f.leaker_asn for f in findings],
                "leak_type": [str(f.leak_type) for f in findings],
                "observations": [f.observations for f in findings],
                "distinct_peers": [f.distinct_peers for f in findings],
                "distinct_collectors": [f.distinct_collectors for f in findings],
                "corroborated": [f.corroborated for f in findings],
                "example_path": [list(f.paths[0]) for f in findings],
            },
            schema=LEAKS_SCHEMA,
        ).write_parquet(out / "leaks.parquet")

    return summary, findings
