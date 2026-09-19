"""Reading the partitioned Parquet tables this project writes.

Every stored table follows the same shape: a directory per snapshot date, and under some of
them a directory per collector.

```
data/processed/rov_results/snapshot_date=2026-09-01/collector=rrc06/rov_results.parquet
data/processed/aspas/snapshot_date=2026-09-01/aspas.parquet
```

The reading helpers were written four times over Phases 6 and 7 - once each in the report
builder, the exporter, the longitudinal analysis and the reproduction script - and had already
started to drift apart. They live here now, for the same reason the relationship protocols were
consolidated into `bgpshield.topology` in Phase 4: four copies of a date parser is four chances for
one of them to disagree about what "the latest snapshot" means.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from bgpshield.config import Config

SNAPSHOT_PREFIX = "snapshot_date="
COLLECTOR_PREFIX = "collector="


MONTH_PREFIX = "month="


def table_root(cfg: Config, name: str) -> Path:
    """Where one table lives, for instance ``routes`` or ``rov_results``."""
    return cfg.paths.processed / name


def date_partition(cfg: Config, name: str, day: date, *, collector: str | None = None) -> Path:
    """The directory holding one date's slice of a table, optionally one collector's.

    ``date_partition(cfg, "routes", day, collector="rrc06")`` is
    ``data/processed/routes/snapshot_date=YYYY-MM-DD/collector=rrc06``.
    """
    base = table_root(cfg, name) / f"{SNAPSHOT_PREFIX}{day:%Y-%m-%d}"
    return base / f"{COLLECTOR_PREFIX}{collector}" if collector else base


def date_table(
    cfg: Config, name: str, day: date, *, collector: str | None = None, leaf: str | None = None
) -> Path:
    """The Parquet file for one date, named after its table unless ``leaf`` says otherwise.

    Every date-partitioned table this project writes keeps its file as ``<name>.parquet``
    inside the partition, so the file name never has to be spelled out at a call site.
    """
    return date_partition(cfg, name, day, collector=collector) / (leaf or f"{name}.parquet")


def month_table(cfg: Config, name: str, month: str, *, leaf: str | None = None) -> Path:
    """The Parquet file for one month of a month-partitioned table such as ``as_rel``.

    ``month`` is ``YYYY-MM``; relationship and metadata tables are monthly because their
    upstream sources are (plan Section 10.4).
    """
    return table_root(cfg, name) / f"{MONTH_PREFIX}{month}" / (leaf or f"{name}.parquet")


def snapshot_dates(root: Path) -> list[date]:
    """Every snapshot date stored under a table, oldest first.

    A directory whose name is not a readable date is skipped rather than raising: a stray
    file in a data directory should not stop an analysis that does not need it.
    """
    if not root.exists():
        return []
    found: list[date] = []
    for child in root.iterdir():
        if not child.name.startswith(SNAPSHOT_PREFIX):
            continue
        try:
            found.append(date.fromisoformat(child.name.removeprefix(SNAPSHOT_PREFIX)))
        except ValueError:
            continue
    return sorted(found)


def latest_snapshot(root: Path) -> date | None:
    """The most recent stored snapshot date, or ``None`` if the table is empty."""
    dates = snapshot_dates(root)
    return dates[-1] if dates else None


def read_partition(
    root: Path,
    day: date,
    leaf: str,
    columns: list[str] | None = None,
    *,
    collector: str | None = None,
) -> pl.DataFrame | None:
    """Read one date's rows, or one collector's slice of them.

    Returns ``None`` when there is nothing readable. That is deliberately distinct from an
    empty frame: "this was never ingested" and "this was ingested and held nothing" are
    different claims, and only the caller knows which one matters. A partition directory can
    exist with no table inside it, for instance after an interrupted ingest, and that counts
    as nothing readable.
    """
    base = root / f"{SNAPSHOT_PREFIX}{day:%Y-%m-%d}"
    if not base.exists():
        return None

    if collector is not None:
        one = base / f"{COLLECTOR_PREFIX}{collector}" / leaf
        return pl.read_parquet(one, columns=columns) if one.exists() else None

    # Tables that are not split by collector keep the file directly under the date.
    direct = base / leaf
    if direct.exists():
        return pl.read_parquet(direct, columns=columns)

    frames = [
        pl.read_parquet(child / leaf, columns=columns)
        for child in sorted(base.iterdir())
        if child.name.startswith(COLLECTOR_PREFIX) and (child / leaf).exists()
    ]
    return pl.concat(frames) if frames else None


def collectors_stored(root: Path, day: date) -> list[str]:
    """Which collectors have data for one date."""
    base = root / f"{SNAPSHOT_PREFIX}{day:%Y-%m-%d}"
    if not base.exists():
        return []
    return sorted(
        child.name.removeprefix(COLLECTOR_PREFIX)
        for child in base.iterdir()
        if child.is_dir() and child.name.startswith(COLLECTOR_PREFIX)
    )


def previous_month(day: date) -> str:
    """The month before a date, as ``YYYY-MM``.

    Relationship data is deliberately taken from the month *before* a snapshot, so the
    topology used to judge a route was not inferred from the routes being judged (plan
    Section 10.4).
    """
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def nearest_snapshot_on_or_before(root: Path, day: date) -> date | None:
    """The newest snapshot at or before a date.

    RPKI snapshots are backfilled weekly while routing tables are ingested per day, so asking
    for "the ASPA records for this routing snapshot" will often miss by a few days. Falling
    back to the most recent earlier snapshot is right here - published records persist until
    they are replaced - but the caller should say which date it actually used.
    """
    candidates = [stored for stored in snapshot_dates(root) if stored <= day]
    return candidates[-1] if candidates else None
