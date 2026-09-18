"""Trace randomly sampled ASPA-Invalid routes, hop by hop, so a reviewer can check them.

Plan Section 11 (Phase 3) accepts the phase when "a reviewer can trace three randomly
sampled ASPA-Invalid routes by hand". This prints everything needed to do that without
trusting any of the code: the stored path, what each network published, the outcome of the
authorization function at every hop, the four ramp numbers, which procedure was chosen and
why, and the verdict that follows.

Run:

    uv run python scripts/phase3_trace_invalid.py --date 2026-09-01 --collector rrc06

The sample is seeded, so the same three routes come back every time and a reviewer and the
author can discuss the same examples.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime
from pathlib import Path

import polars as pl

from hijax.config import load_config
from hijax.ingest.meta import RelationshipLookup
from hijax.validate.aspa import Authorized, procedure_for, ramp_bounds, verify_at_collector
from hijax.validate.run import load_aspa_registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-01")
    parser.add_argument("--collector", default="rrc06")
    parser.add_argument("--month", default=None, help="Relationship month, default the previous")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args()

    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    month = (
        args.month
        or f"{day.year if day.month > 1 else day.year - 1:04d}-{(day.month - 1) or 12:02d}"
    )
    cfg = load_config(Path("config/default.yaml"))

    registry = load_aspa_registry(cfg, day)
    relationships = RelationshipLookup.from_frame(
        pl.read_parquet(cfg.paths.processed / "as_rel" / f"month={month}" / "as_rel.parquet")
    )

    results = pl.read_parquet(
        cfg.paths.processed
        / "aspa_results"
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={args.collector}"
        / "aspa_results.parquet"
    ).filter(pl.col("aspa_state") == "invalid")

    routes = pl.read_parquet(
        cfg.paths.processed
        / "routes"
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={args.collector}"
        / "routes.parquet",
        columns=["peer_ip", "peer_asn", "prefix", "as_path", "as_path_raw", "has_as_set"],
    )

    joined = results.join(routes, on=["peer_ip", "prefix"], how="inner")
    print(f"ASPA-Invalid routes at {args.collector} on {day}: {results.height:,}")
    print(f"ASPA records in force that day: {len(registry):,}")
    print(f"Relationship month: {month}\n")

    rng = random.Random(args.seed)
    picks = rng.sample(range(joined.height), min(args.samples, joined.height))

    for number, index in enumerate(picks, 1):
        row = joined.row(index, named=True)
        trace(number, row, registry, relationships)


def trace(number: int, row: dict[str, object], registry: object, relationships: object) -> None:
    path = tuple(int(a) for a in row["as_path"])  # type: ignore[call-overload]
    has_as_set = bool(row["has_as_set"])
    print("=" * 78)
    print(f"SAMPLE {number}")
    print("=" * 78)
    print(f"  prefix           : {row['prefix']}")
    print(f"  collector peer   : AS{row['peer_asn']} at {row['peer_ip']}")
    print(f"  AS_PATH as heard : {row['as_path_raw']}")
    print(f"  normalised       : {' '.join(str(a) for a in path)}   (origin first)")
    print(f"  contains AS_SET  : {has_as_set}")

    if has_as_set:
        print("\n  The path carries an AS_SET. RFC 9774 deprecates AS_SET, and the")
        print("  verification draft (Section 5.5 step 3) makes such a path Invalid")
        print("  outright, before any ramp is computed. Nothing further to trace.\n")
        return

    receiver, neighbour = path[-1], path[-2] if len(path) > 1 else None
    relation = relationships.rel(receiver, neighbour) if neighbour else None  # type: ignore[attr-defined]
    chosen = procedure_for(relation)
    print(f"\n  The collector peer AS{receiver} received this from AS{neighbour}.")
    print(
        f"  CAIDA says AS{neighbour} is {relation or 'UNKNOWN'} to AS{receiver}"
        f"  ->  {chosen.value if chosen else 'run both procedures'}"
    )

    received = path[:-1]
    print(f"\n  Path as AS{receiver} received it: {' '.join(str(a) for a in received)}")
    print("\n  Hop by hop, away from the origin (draft Section 5.3):")
    print(f"    {'hop':<22} {'question':<44} verdict")
    for i in range(1, len(received)):
        x, y = received[i - 1], received[i]
        verdict = registry.authorized(x, y)  # type: ignore[attr-defined]
        published = registry.providers_of(x)  # type: ignore[attr-defined]
        shown = "nothing published" if not published else sorted(published)
        print(
            f"    AS{x} -> AS{y:<14} is AS{y} a provider of AS{x}? {str(shown):<12} {verdict.value}"
        )
        if verdict is Authorized.NOT_PROVIDER_PLUS:
            print(f"      ^ AS{x} published a list and AS{y} is not on it: a contradiction.")

    bounds = ramp_bounds(received, registry)  # type: ignore[arg-type]
    n = len(received)
    print(f"\n  Ramp lengths (draft Section 5.4), path length N = {n}:")
    print(f"    max_up_ramp   = {bounds.max_up}   min_up_ramp   = {bounds.min_up}")
    print(f"    max_down_ramp = {bounds.max_down}   min_down_ramp = {bounds.min_down}")

    verdict = verify_at_collector(path, registry, relationships, has_as_set=has_as_set)  # type: ignore[arg-type]
    detail = verdict.upstream or verdict.downstream
    print(f"\n  Procedure applied : {verdict.procedure}")
    if detail is not None:
        print(f"  Reason            : {detail.reason}")
        if detail.first_bad_hop:
            print(
                f"  First bad hop     : AS{detail.first_bad_hop[0]} -> AS{detail.first_bad_hop[1]}"
            )
    print(f"  VERDICT           : {verdict.state.value.upper()}")
    if verdict.procedure == "upstream":
        print(f"\n  Check by hand: max_up_ramp ({bounds.max_up}) < N ({n}) means the climb")
        print("  cannot reach the receiver, so the path is Invalid (draft Section 5.5 step 4).")
    elif verdict.procedure == "downstream":
        total = bounds.max_up + bounds.max_down
        print(f"\n  Check by hand: max_up + max_down = {total} < N ({n}) means the two ramps")
        print("  cannot span the path, so it is Invalid (draft Section 5.6 step 4).")
    print()


if __name__ == "__main__":
    main()
