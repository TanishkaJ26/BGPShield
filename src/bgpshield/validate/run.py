"""Run both validators over a day of stored routes (plan Sections 9 and 11, Phase 3).

Produces the two results tables from plan Section 9, ``rov_results`` and ``aspa_results``,
keyed by the route they describe.

## Why this is fast enough to run on a laptop

A day across six collectors is about a hundred million routes, but they are enormously
repetitive: the same prefix is announced by the same origin to dozens of peers, and the same
AS_PATH carries thousands of prefixes. Both validators are pure functions of a small key, so
each distinct key is evaluated once and the answer reused. On real data that turns tens of
millions of evaluations into hundreds of thousands.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from bgpshield.config import Config
from bgpshield.topology import RelSource
from bgpshield.validate.aspa import (
    AspaRegistry,
    AspaState,
    CollectorVerification,
    verify_at_collector,
)
from bgpshield.validate.rov import RovResult, RovState, VrpIndex

ROV_RESULTS_SCHEMA: dict[str, pl.DataType] = {
    "collector": pl.Utf8(),
    "peer_ip": pl.Utf8(),
    "prefix": pl.Utf8(),
    "origin_asn": pl.Int64(),
    "rov_state": pl.Utf8(),
    "reason": pl.Utf8(),
    "snapshot_date": pl.Date(),
}

ASPA_RESULTS_SCHEMA: dict[str, pl.DataType] = {
    "collector": pl.Utf8(),
    "peer_ip": pl.Utf8(),
    "prefix": pl.Utf8(),
    "procedure": pl.Utf8(),
    "aspa_state": pl.Utf8(),
    "first_bad_hop_from": pl.Int64(),
    "first_bad_hop_to": pl.Int64(),
    "snapshot_date": pl.Date(),
}


@dataclass(slots=True)
class ValidationSummary:
    """Counts for one collector, which is what the Phase 3 sanity check reports."""

    collector: str
    snapshot_date: date
    routes: int = 0
    distinct_origins: int = 0
    distinct_paths: int = 0
    rov: Counter[str] = field(default_factory=Counter)
    rov_reasons: Counter[str] = field(default_factory=Counter)
    aspa: Counter[str] = field(default_factory=Counter)
    aspa_procedures: Counter[str] = field(default_factory=Counter)
    seconds: float = 0.0

    def rov_share(self, state: RovState) -> float:
        return self.rov.get(str(state), 0) / self.routes if self.routes else 0.0

    def aspa_share(self, state: AspaState) -> float:
        return self.aspa.get(str(state), 0) / self.routes if self.routes else 0.0


def routes_path(cfg: Config, collector: str, day: date) -> Path:
    return (
        cfg.paths.processed
        / "routes"
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={collector}"
        / "routes.parquet"
    )


def results_path(cfg: Config, table: str, collector: str, day: date) -> Path:
    return (
        cfg.paths.processed
        / table
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={collector}"
        / f"{table}.parquet"
    )


def load_vrp_index(cfg: Config, day: date) -> VrpIndex:
    """Build the prefix tree from the VRPs ingested for that day."""
    path = cfg.paths.processed / "vrps" / f"snapshot_date={day:%Y-%m-%d}" / "vrps.parquet"
    if not path.exists():
        raise FileNotFoundError(f"no VRPs ingested for {day}; run 'bgpshield ingest-rpki' first")
    return VrpIndex.from_frame(pl.read_parquet(path))


def load_aspa_registry(cfg: Config, day: date) -> AspaRegistry:
    """Build the U-SPAS table from the ASPA records ingested for that day."""
    path = cfg.paths.processed / "aspas" / f"snapshot_date={day:%Y-%m-%d}" / "aspas.parquet"
    if not path.exists():
        raise FileNotFoundError(f"no ASPAs ingested for {day}; run 'bgpshield ingest-rpki' first")
    frame = pl.read_parquet(path)
    # A snapshot holds one row per (customer, trust anchor), so a customer publishing under
    # two anchors appears twice. The effective provider set is the union over all of a
    # customer's valid ASPAs (``draft-ietf-sidrops-aspa-verification-28`` Section 5.3);
    # keeping only the last row would drop real providers and report legitimate hops as
    # Invalid. No customer does this in the snapshots ingested so far, which is exactly why
    # it has to be handled here rather than noticed later.
    merged: dict[int, frozenset[int]] = {}
    for customer, providers in zip(frame["customer_asn"], frame["provider_asns"], strict=True):
        asn = int(customer)
        merged[asn] = merged.get(asn, frozenset()) | frozenset(int(p) for p in providers)
    return AspaRegistry(merged)


def validate_collector(
    cfg: Config,
    collector: str,
    day: date,
    vrps: VrpIndex,
    registry: AspaRegistry,
    relationships: RelSource,
    *,
    write: bool = True,
) -> ValidationSummary:
    """Validate every route one collector recorded that day.

    Both validators are memoised on their inputs, because collector tables repeat the same
    prefix, origin and path combinations many times over.
    """
    started = datetime.now(tz=UTC)
    summary = ValidationSummary(collector=collector, snapshot_date=day)

    source = routes_path(cfg, collector, day)
    if not source.exists():
        raise FileNotFoundError(f"no routes stored for {collector} on {day}")

    frame = pl.read_parquet(
        source, columns=["peer_ip", "prefix", "as_path", "has_as_set", "origin_asn"]
    )
    summary.routes = frame.height

    rov_cache: dict[tuple[str, int | None], RovResult] = {}
    aspa_cache: dict[tuple[tuple[int, ...], bool], CollectorVerification] = {}

    rov_states: list[str] = []
    rov_reasons: list[str] = []
    aspa_states: list[str] = []
    procedures: list[str] = []
    bad_from: list[int | None] = []
    bad_to: list[int | None] = []

    for peer_ip, prefix, as_path, has_as_set, origin_asn in frame.iter_rows():
        del peer_ip  # carried through from the frame when writing, not needed here
        rov_key = (prefix, origin_asn)
        rov = rov_cache.get(rov_key)
        if rov is None:
            rov = vrps.validate(prefix, origin_asn)
            rov_cache[rov_key] = rov
        rov_states.append(str(rov.state))
        rov_reasons.append(str(rov.reason))
        summary.rov[str(rov.state)] += 1
        if rov.reason:
            summary.rov_reasons[str(rov.reason)] += 1

        path = tuple(as_path)
        aspa_key = (path, bool(has_as_set))
        verdict = aspa_cache.get(aspa_key)
        if verdict is None:
            verdict = verify_at_collector(
                path, registry, relationships, has_as_set=bool(has_as_set)
            )
            aspa_cache[aspa_key] = verdict
        aspa_states.append(str(verdict.state))
        procedures.append(verdict.procedure)
        summary.aspa[str(verdict.state)] += 1
        summary.aspa_procedures[verdict.procedure] += 1

        hop = None
        for candidate in (verdict.upstream, verdict.downstream):
            if candidate is not None and candidate.first_bad_hop is not None:
                hop = candidate.first_bad_hop
                break
        bad_from.append(hop[0] if hop else None)
        bad_to.append(hop[1] if hop else None)

    # The cache is keyed on (prefix, origin), so its length is a count of prefix-origin
    # pairs and is about two orders of magnitude larger than the number of origins. Count
    # the origins themselves; a sanity figure that is wrong is worse than no figure.
    summary.distinct_origins = len({origin for _, origin in rov_cache if origin is not None})
    summary.distinct_paths = len(aspa_cache)

    if write:
        _write_results(
            cfg,
            collector,
            day,
            frame,
            rov_states,
            rov_reasons,
            aspa_states,
            procedures,
            bad_from,
            bad_to,
        )

    summary.seconds = (datetime.now(tz=UTC) - started).total_seconds()
    return summary


def _write_results(
    cfg: Config,
    collector: str,
    day: date,
    frame: pl.DataFrame,
    rov_states: list[str],
    rov_reasons: list[str],
    aspa_states: list[str],
    procedures: list[str],
    bad_from: list[int | None],
    bad_to: list[int | None],
) -> None:
    rov_out = results_path(cfg, "rov_results", collector, day)
    aspa_out = results_path(cfg, "aspa_results", collector, day)
    rov_out.parent.mkdir(parents=True, exist_ok=True)
    aspa_out.parent.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "collector": [collector] * frame.height,
            "peer_ip": frame["peer_ip"],
            "prefix": frame["prefix"],
            "origin_asn": frame["origin_asn"],
            "rov_state": rov_states,
            "reason": rov_reasons,
            "snapshot_date": [day] * frame.height,
        },
        schema=ROV_RESULTS_SCHEMA,
    ).write_parquet(rov_out)

    pl.DataFrame(
        {
            "collector": [collector] * frame.height,
            "peer_ip": frame["peer_ip"],
            "prefix": frame["prefix"],
            "procedure": procedures,
            "aspa_state": aspa_states,
            "first_bad_hop_from": bad_from,
            "first_bad_hop_to": bad_to,
            "snapshot_date": [day] * frame.height,
        },
        schema=ASPA_RESULTS_SCHEMA,
    ).write_parquet(aspa_out)
