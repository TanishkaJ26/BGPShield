"""Phase 7 acceptance: the small reproduction someone else can run.

Plan Section 11 Phase 7 accepts when somebody can clone the repository, run
``make reproduce-small`` for one date and one collector in under thirty minutes, and get the
same numbers as the committed fixtures.

This is the claim the whole project rests on. Every figure and every percentage in the
write-up is only worth what an independent rerun says it is, so this script runs the real
pipeline against the real archives and compares what comes out against numbers recorded from
an earlier run.

**Why rrc06 and 2026-09-01.** rrc06 is the smallest of the configured collectors at about
43 MB, so the download fits comfortably in the time budget, and archive files for a past date
never change, so the answer is stable. The date is the one the rest of the analysis uses.

Run it with ``--update-fixture`` to record a fresh baseline. That is deliberately a separate,
explicit action: a comparison that silently rewrites what it is comparing against proves
nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

REPO = Path(__file__).resolve().parent.parent
HIJAX = REPO / ".venv" / "Scripts" / "hijax.exe"
FIXTURE = REPO / "tests" / "fixtures" / "reproduce_small.json"

DAY = date(2026, 9, 1)
COLLECTOR = "rrc06"
META_MONTH = "2026-08"
TIME_BUDGET_MINUTES = 30

#: Counts that must match exactly. These are derived from immutable archive files, so an
#: honest rerun reproduces them to the row; anything else means something has changed and
#: should be looked at rather than tolerated.
EXACT_KEYS = (
    "routes",
    "peers",
    "prefixes",
    "rov_valid",
    "rov_invalid",
    "rov_not_found",
    "aspa_valid",
    "aspa_invalid",
    "aspa_unknown",
    "vrps",
    "aspa_records",
)


def run(args: list[str], label: str) -> bool:
    started = time.time()
    proc = subprocess.run(
        [str(HIJAX), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ok = proc.returncode == 0
    print(f"  {label}: {'ok' if ok else 'FAILED'} in {time.time() - started:.0f}s", flush=True)
    if not ok:
        print((proc.stdout or "")[-1500:], flush=True)
        print((proc.stderr or "")[-1500:], flush=True)
    return ok


def _partition(name: str, leaf: str, columns: list[str]) -> pl.DataFrame | None:
    """Read this collector's slice of a partitioned table, or the whole date if unpartitioned."""
    base = REPO / "data" / "processed" / name / f"snapshot_date={DAY:%Y-%m-%d}"
    by_collector = base / f"collector={COLLECTOR}" / leaf
    if by_collector.exists():
        return pl.read_parquet(by_collector, columns=columns)
    whole = base / leaf
    if whole.exists():
        return pl.read_parquet(whole, columns=columns)
    return None


def collect_numbers() -> dict[str, Any]:
    """The numbers a rerun has to reproduce."""
    numbers: dict[str, Any] = {
        "date": str(DAY),
        "collector": COLLECTOR,
        "metadata_month": META_MONTH,
    }

    stats_path = (
        REPO
        / "data"
        / "processed"
        / "routes"
        / f"snapshot_date={DAY:%Y-%m-%d}"
        / f"collector={COLLECTOR}"
        / "stats.json"
    )
    if stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        numbers["routes"] = stats["rows"]
        numbers["peers"] = stats["peers"]
        numbers["prefixes"] = stats["prefixes"]
        numbers["dump_bytes"] = stats.get("dump_bytes", 0)
        numbers["flag_rates"] = stats.get("flag_rates", {})

    rov = _partition("rov_results", "rov_results.parquet", ["rov_state"])
    if rov is not None:
        counts = {str(r["rov_state"]): r["len"] for r in rov.group_by("rov_state").len().to_dicts()}
        for state in ("valid", "invalid", "not_found"):
            numbers[f"rov_{state}"] = counts.get(state, 0)

    aspa = _partition("aspa_results", "aspa_results.parquet", ["aspa_state"])
    if aspa is not None:
        counts = {
            str(r["aspa_state"]): r["len"] for r in aspa.group_by("aspa_state").len().to_dicts()
        }
        for state in ("valid", "invalid", "unknown"):
            numbers[f"aspa_{state}"] = counts.get(state, 0)

    vrps = _partition("vrps", "vrps.parquet", ["prefix"])
    if vrps is not None:
        numbers["vrps"] = vrps.height
    aspas = _partition("aspas", "aspas.parquet", ["customer_asn"])
    if aspas is not None:
        numbers["aspa_records"] = aspas.height

    leaks = _partition("leaks", "leaks.parquet", ["leaker_asn"])
    if leaks is not None:
        numbers["leak_findings"] = leaks.height
        numbers["leak_leakers"] = leaks["leaker_asn"].n_unique()

    return numbers


def compare(fresh: dict[str, Any], fixture: dict[str, Any]) -> list[str]:
    """Differences that matter, as readable lines."""
    problems: list[str] = []
    for key in EXACT_KEYS:
        if key not in fixture:
            continue
        if key not in fresh:
            problems.append(f"{key}: missing from this run, fixture says {fixture[key]:,}")
            continue
        if fresh[key] != fixture[key]:
            problems.append(
                f"{key}: got {fresh[key]:,}, fixture says {fixture[key]:,} "
                f"(difference {fresh[key] - fixture[key]:+,})"
            )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-fixture", action="store_true", help="Record a fresh baseline instead of checking."
    )
    parser.add_argument(
        "--skip-pipeline", action="store_true", help="Compare what is already stored."
    )
    args = parser.parse_args()

    started = time.time()
    iso = str(DAY)

    if not args.skip_pipeline:
        print(f"reproducing {iso} on {COLLECTOR}\n", flush=True)
        steps = [
            (["ingest-rpki", "--date", iso], "RPKI snapshot"),
            (["ingest-meta", "--month", META_MONTH], f"topology {META_MONTH}"),
            (["ingest-bgp", "--date", iso, "--collectors", COLLECTOR], "routing table"),
            (["validate", "--date", iso, "--collectors", COLLECTOR], "validate"),
            (["detect", "--date", iso, "--collectors", COLLECTOR], "detect leaks"),
        ]
        for argv, label in steps:
            if not run(argv, label):
                print(f"\nFAILED at: {label}")
                sys.exit(1)

    elapsed = (time.time() - started) / 60
    fresh = collect_numbers()

    if args.update_fixture:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nrecorded baseline -> {FIXTURE}")
        for key in EXACT_KEYS:
            if key in fresh:
                print(f"  {key:<16} {fresh[key]:>12,}")
        return

    if not FIXTURE.exists():
        print(f"\nno fixture at {FIXTURE}; run with --update-fixture first")
        sys.exit(1)

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    problems = compare(fresh, fixture)

    print("\n=== PHASE 7, REPRODUCE-SMALL ===")
    print(f"date            : {iso}, collector {COLLECTOR}")
    print(f"wall clock      : {elapsed:.1f} minutes (budget {TIME_BUDGET_MINUTES})")
    for key in EXACT_KEYS:
        if key in fixture:
            got = fresh.get(key)
            mark = "ok" if got == fixture[key] else "DIFFERS"
            shown = f"{got:,}" if isinstance(got, int) else str(got)
            print(f"  {key:<16} {shown:>14}  {mark}")

    time_ok = elapsed < TIME_BUDGET_MINUTES or args.skip_pipeline
    print(f"\nnumbers         : {'MATCH' if not problems else 'DIFFER'}")
    print(f"time            : {'PASS' if time_ok else 'MISS'}")
    if problems:
        print("\ndifferences:")
        for line in problems:
            print(f"  {line}")
        sys.exit(1)
    if not time_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
