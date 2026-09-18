"""RQ1, the adoption baseline: who publishes ASPA records, and how that changes over time.

Plain English. An ASPA record is one network's signed statement listing its upstream
providers (``draft-ietf-sidrops-aspa-profile-29``). Counting them over time answers the
first research question: is anyone actually deploying this, and where? Everything here
reads the Parquet tables written by ``hijax ingest-rpki``; nothing downloads.

Three breakdowns, as plan Section 11 asks for: per day, per trust anchor, and per country
of registration. The country caveat from ``hijax.ingest.meta`` applies to the third one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from hijax.config import Config


def aspas_glob(cfg: Config) -> str:
    """Every ingested snapshot, as a Hive-partitioned glob polars can scan lazily."""
    return str(cfg.paths.processed / "aspas" / "snapshot_date=*" / "aspas.parquet")


def load_aspas(cfg: Config) -> pl.DataFrame:
    """Read every ingested ASPA snapshot into one frame."""
    pattern = aspas_glob(cfg)
    frame = pl.read_parquet(pattern)
    if "snapshot_date" not in frame.columns:
        raise ValueError(f"no snapshot_date column in {pattern}")
    return frame


def counts_by_day(aspas: pl.DataFrame) -> pl.DataFrame:
    """Total ASPA records per snapshot date, plus how many distinct ASes published one.

    These differ when one AS publishes under more than one trust anchor, which is rare but
    possible, so both numbers are reported rather than assumed equal.
    """
    return (
        aspas.group_by("snapshot_date")
        .agg(
            pl.len().alias("aspas"),
            pl.col("customer_asn").n_unique().alias("customer_asns"),
        )
        .sort("snapshot_date")
    )


def counts_by_ta(aspas: pl.DataFrame) -> pl.DataFrame:
    """ASPA records per snapshot date and trust anchor (one per RIR)."""
    return (
        aspas.group_by(["snapshot_date", "ta"])
        .agg(pl.len().alias("aspas"))
        .sort(["snapshot_date", "ta"])
    )


def counts_by_country(aspas: pl.DataFrame, registry: pl.DataFrame) -> pl.DataFrame:
    """ASPA records per snapshot date and registration country.

    Publishers whose AS number is not in the registry files come back as ``country = "??"``
    rather than being dropped, so the totals still add up.
    """
    joined = aspas.join(
        registry.select(["asn", "country"]), left_on="customer_asn", right_on="asn", how="left"
    )
    return (
        joined.with_columns(pl.col("country").fill_null("??"))
        .group_by(["snapshot_date", "country"])
        .agg(pl.len().alias("aspas"))
        .sort(["snapshot_date", "aspas"], descending=[False, True])
    )


def provider_list_sizes(aspas: pl.DataFrame) -> pl.DataFrame:
    """How many providers each publisher lists, summarised per snapshot date.

    A record listing only AS 0 is the way to say "I have no providers at all", so those are
    counted separately instead of being averaged in as a list of length one.
    """
    sized = aspas.with_columns(
        pl.col("provider_asns").list.len().alias("n_providers"),
        (pl.col("provider_asns").list.len() == 1)
        .and_(pl.col("provider_asns").list.first() == 0)
        .alias("is_as0"),
    )
    return (
        sized.group_by("snapshot_date")
        .agg(
            pl.col("n_providers").filter(~pl.col("is_as0")).median().alias("median_providers"),
            pl.col("n_providers").filter(~pl.col("is_as0")).max().alias("max_providers"),
            pl.col("is_as0").sum().alias("as0_records"),
        )
        .sort("snapshot_date")
    )


@dataclass(slots=True)
class AdoptionTables:
    """The four small tables behind RQ1."""

    by_day: pl.DataFrame
    by_ta: pl.DataFrame
    by_country: pl.DataFrame
    provider_sizes: pl.DataFrame


def build(cfg: Config, registry: pl.DataFrame) -> AdoptionTables:
    """Compute every adoption table from the ingested snapshots."""
    aspas = load_aspas(cfg)
    return AdoptionTables(
        by_day=counts_by_day(aspas),
        by_ta=counts_by_ta(aspas),
        by_country=counts_by_country(aspas, registry),
        provider_sizes=provider_list_sizes(aspas),
    )


def _rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in frame.iter_rows(named=True):
        clean = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}
        out.append(clean)
    return out


def to_json(tables: AdoptionTables, *, top_countries: int = 25) -> dict[str, Any]:
    """Shape the tables into the small JSON the dashboard reads (plan Section 11).

    Kept deliberately small: the country breakdown is limited to the busiest publishers on
    the most recent snapshot, because the whole dashboard payload has a 5 MB budget
    (plan Section 11, Phase 7).
    """
    by_day = tables.by_day
    newest = by_day["snapshot_date"].max() if by_day.height else None
    # polars types a column max as a broad union, so narrow it to a real date.
    latest: date | None = newest if isinstance(newest, date) else None
    latest_country = (
        tables.by_country.filter(pl.col("snapshot_date") == latest).head(top_countries)
        if latest is not None
        else tables.by_country.head(0)
    )
    return {
        "generated_from": "hijax ingest-rpki (RIPE NCC RPKI archive, Routinator JSON)",
        "caveat_country": (
            "Country is where the AS number is registered, not where the network operates."
        ),
        "snapshots": by_day.height,
        "latest_snapshot": latest.isoformat() if latest is not None else None,
        "by_day": _rows(by_day),
        "by_trust_anchor": _rows(tables.by_ta),
        "latest_by_country": _rows(latest_country),
        "provider_list_sizes": _rows(tables.provider_sizes),
    }


def write_json(tables: AdoptionTables, destination: Path, *, top_countries: int = 25) -> Path:
    """Write the dashboard JSON. Small aggregates like this may be committed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json(tables, top_countries=top_countries)
    destination.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return destination


def _merge_rows(
    old: list[dict[str, Any]], new: list[dict[str, Any]], keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Merge two row lists on ``keys``, with the new rows winning, sorted by key."""
    index: dict[tuple[Any, ...], dict[str, Any]] = {tuple(r[k] for k in keys): r for r in old}
    for row in new:
        index[tuple(row[k] for k in keys)] = row
    return [index[k] for k in sorted(index, key=lambda t: tuple(str(x) for x in t))]


def merge_payload(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Fold a newly computed payload into the series already published.

    The daily GitHub Action only ever ingests one snapshot, because the Parquet tables live
    under ``data/`` and are never committed. Without this merge each run would replace the
    whole time series with a single point. Rows are keyed by snapshot date, so re-running a
    day corrects it rather than duplicating it.
    """
    merged = dict(new)
    merged["by_day"] = _merge_rows(old.get("by_day", []), new.get("by_day", []), ("snapshot_date",))
    merged["by_trust_anchor"] = _merge_rows(
        old.get("by_trust_anchor", []), new.get("by_trust_anchor", []), ("snapshot_date", "ta")
    )
    merged["provider_list_sizes"] = _merge_rows(
        old.get("provider_list_sizes", []),
        new.get("provider_list_sizes", []),
        ("snapshot_date",),
    )
    merged["snapshots"] = len(merged["by_day"])
    dates = [r["snapshot_date"] for r in merged["by_day"]]
    merged["latest_snapshot"] = max(dates) if dates else None
    # The country table only ever describes one snapshot, so keep whichever is newer.
    if not new.get("latest_by_country") and old.get("latest_by_country"):
        merged["latest_by_country"] = old["latest_by_country"]
    return merged


def update_json(tables: AdoptionTables, destination: Path, *, top_countries: int = 25) -> Path:
    """Write the dashboard JSON, merging into whatever is already published there."""
    payload = to_json(tables, top_countries=top_countries)
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload = merge_payload(existing, payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return destination
