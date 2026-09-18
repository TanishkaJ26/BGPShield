"""RQ1 over time: ROV, ASPA and leak aggregates across the quarterly sweep.

Plan Section 11 Phase 6 asks for snapshots across the whole period turned into aggregates over
time. The RPKI half of that series is weekly and complete from Phase 1. The BGP half is
sampled quarterly from one collector, because a weekly sweep across three years is about 150
routing-table dumps; `scripts/phase6_longitudinal.py` does the fetching and
`docs/decisions.md` D-047 records the reduction.

Everything here reads tables already on disk and downloads nothing, so a series can be rebuilt
at any time without touching the network.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from hijax.config import Config


def _dates_with(root: Path) -> list[date]:
    """Snapshot dates stored under a partitioned table, oldest first."""
    if not root.exists():
        return []
    found = []
    for child in root.iterdir():
        name = child.name
        if name.startswith("snapshot_date="):
            try:
                found.append(date.fromisoformat(name.split("=", 1)[1]))
            except ValueError:
                continue
    return sorted(found)


def _read_partition(root: Path, day: date, leaf: str, columns: list[str]) -> pl.DataFrame | None:
    """Read one date's rows, concatenating whatever collectors are stored under it."""
    base = root / f"snapshot_date={day:%Y-%m-%d}"
    if not base.exists():
        return None
    direct = base / leaf
    if direct.exists():
        return pl.read_parquet(direct, columns=columns)
    frames = [
        pl.read_parquet(child / leaf, columns=columns)
        for child in sorted(base.iterdir())
        if (child / leaf).exists()
    ]
    return pl.concat(frames) if frames else None


def _shares(frame: pl.DataFrame, column: str) -> dict[str, float]:
    """Each state's share of the rows, as a fraction."""
    total = frame.height
    if not total:
        return {}
    counted = frame.group_by(column).len()
    return {str(row[column]): row["len"] / total for row in counted.iter_rows(named=True)}


def build_series(cfg: Config) -> pl.DataFrame:
    """One row per snapshot date that has validation results stored.

    Columns are the share of routes in each ROV state and each ASPA state, plus the number of
    leak findings. A date missing one of the three inputs still appears, with nulls for the
    part that is absent, so a gap in the sweep is visible rather than silently skipped.
    """
    processed = cfg.paths.processed
    rov_root, aspa_root, leak_root = (
        processed / "rov_results",
        processed / "aspa_results",
        processed / "leaks",
    )

    days = sorted(set(_dates_with(rov_root)) | set(_dates_with(aspa_root)))
    rows: list[dict[str, object]] = []

    for day in days:
        row: dict[str, object] = {"snapshot_date": day}

        rov = _read_partition(rov_root, day, "rov_results.parquet", ["rov_state"])
        if rov is not None:
            row["routes"] = rov.height
            for state, share in _shares(rov, "rov_state").items():
                row[f"rov_{state}"] = share

        aspa = _read_partition(aspa_root, day, "aspa_results.parquet", ["aspa_state"])
        if aspa is not None:
            row["aspa_rows"] = aspa.height
            for state, share in _shares(aspa, "aspa_state").items():
                row[f"aspa_{state}"] = share

        leaks = _read_partition(leak_root, day, "leaks.parquet", ["leaker_asn", "corroborated"])
        if leaks is not None:
            row["leak_findings"] = leaks.height
            row["leak_leakers"] = leaks["leaker_asn"].n_unique()
            row["leak_corroborated"] = int(leaks.filter(pl.col("corroborated")).height)

        rows.append(row)

    if not rows:
        return pl.DataFrame({"snapshot_date": []}, schema={"snapshot_date": pl.Date})

    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return pl.DataFrame([{key: row.get(key) for key in keys} for row in rows]).sort("snapshot_date")


def publisher_series(cfg: Config) -> pl.DataFrame:
    """ASPA publishers per weekly snapshot, the complete half of the longitudinal picture."""
    root = cfg.paths.processed / "aspas"
    rows = []
    for day in _dates_with(root):
        frame = _read_partition(root, day, "aspas.parquet", ["customer_asn"])
        if frame is not None:
            rows.append({"snapshot_date": day, "publishers": frame["customer_asn"].n_unique()})
    return pl.DataFrame(rows) if rows else pl.DataFrame({"snapshot_date": [], "publishers": []})
