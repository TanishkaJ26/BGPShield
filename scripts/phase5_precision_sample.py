"""Draw a random sample of detected leaks and print the evidence for labelling each one.

Plan Section 11 (Phase 5) accepts the phase when precision has been measured on "a manually
labelled random sample of 50 detected leaks". This prints, for each sampled candidate,
everything needed to judge it: the path, the relationship at every step, who the leaker is
and how big it is, how many vantage points saw it, and whether the two networks either side
of the turn look like a plausible pair.

The sample is seeded so the labels can be discussed and re-checked against the same rows.

Run:

    uv run python scripts/phase5_precision_sample.py --date 2026-09-01 --samples 50
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime
from pathlib import Path

import polars as pl

from bgpshield.config import load_config
from bgpshield.detect.leaks import Direction, find_leakers, path_directions
from bgpshield.ingest.meta import RelationshipLookup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-01")
    parser.add_argument("--month", default=None)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument(
        "--corroborated-only",
        action="store_true",
        default=True,
        help="Sample only candidates seen from two or more vantage points.",
    )
    args = parser.parse_args()

    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    month = args.month or (
        f"{day.year if day.month > 1 else day.year - 1:04d}-{(day.month - 1) or 12:02d}"
    )
    cfg = load_config(Path("config/default.yaml"))

    relationships = RelationshipLookup.from_frame(
        pl.read_parquet(cfg.paths.processed / "as_rel" / f"month={month}" / "as_rel.parquet")
    )
    as_meta = pl.read_parquet(
        cfg.paths.processed / "as_meta" / f"month={month}" / "as_meta.parquet"
    )
    cones = {
        int(a): int(c)
        for a, c in zip(as_meta["asn"], as_meta["cone_size"], strict=True)
        if c is not None
    }
    countries = {
        int(a): str(c)
        for a, c in zip(as_meta["asn"], as_meta["country"], strict=True)
        if c is not None
    }

    leaks = pl.read_parquet(
        cfg.paths.processed / "leaks" / f"snapshot_date={day:%Y-%m-%d}" / "leaks.parquet"
    )
    if args.corroborated_only:
        leaks = leaks.filter(pl.col("corroborated"))

    print(f"Detected leak candidates available for sampling: {leaks.height:,}")
    print(f"Sampling {args.samples} with seed {args.seed}\n")

    rng = random.Random(args.seed)
    picks = rng.sample(range(leaks.height), min(args.samples, leaks.height))

    for number, index in enumerate(sorted(picks), 1):
        row = leaks.row(index, named=True)
        show(number, row, relationships, cones, countries)


def describe(asn: int, cones: dict[int, int], countries: dict[int, str]) -> str:
    cone = cones.get(asn)
    country = countries.get(asn, "??")
    size = "no cone" if cone is None else f"cone {cone:,}"
    return f"AS{asn} [{country}, {size}]"


def show(
    number: int,
    row: dict[str, object],
    relationships: RelationshipLookup,
    cones: dict[int, int],
    countries: dict[int, str],
) -> None:
    path = [int(a) for a in row["example_path"]]  # type: ignore[call-overload]
    directions = path_directions(path, relationships)
    leakers = find_leakers(path, directions)

    print("-" * 78)
    print(
        f"#{number:<3} {row['prefix']}   type={row['leak_type']}   "
        f"peers={row['distinct_peers']}   sightings={row['observations']}"
    )
    print(f"     path (origin first): {' '.join(str(a) for a in path)}")
    print("     steps:")
    for i, step in enumerate(directions):
        left, right = path[i], path[i + 1]
        marker = ""
        if any(candidate.position == i + 2 for candidate in leakers):
            marker = "   <-- turn here"
        print(
            f"       {describe(left, cones, countries):<28} -> "
            f"{describe(right, cones, countries):<28} {step.value}{marker}"
        )

    for candidate in leakers:
        leaker = candidate.leaker_asn
        print(
            f"     leaker {describe(leaker, cones, countries)}: "
            f"took it {candidate.incoming.value}, passed it {candidate.outgoing.value}"
        )
        print(
            f"       CAIDA sees for this network: "
            f"{len(relationships.providers(leaker))} providers, "
            f"{len(relationships.peers(leaker))} peers"
        )
        if candidate.incoming is Direction.UNKNOWN or candidate.outgoing is Direction.UNKNOWN:
            print("       one side of the turn has no inferred relationship")
    print()


if __name__ == "__main__":
    main()
