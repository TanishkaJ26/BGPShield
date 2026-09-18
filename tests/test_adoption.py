"""Unit tests for the RQ1 adoption tables (plan Sections 11 and 12).

All input here is hand-built. Two snapshot dates, four publishers, two trust anchors, one
record that lists only AS 0, and one publisher missing from the registry, so every branch
of the aggregation is exercised.
"""

from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest

from hijax.analysis.adoption import (
    AdoptionTables,
    counts_by_country,
    counts_by_day,
    counts_by_ta,
    provider_list_sizes,
    to_json,
    write_json,
)
from hijax.ingest.rpki import ASPAS_SCHEMA

DAY1 = date(2026, 9, 1)
DAY2 = date(2026, 9, 8)

ASPAS = pl.DataFrame(
    {
        "customer_asn": [64496, 64497, 64496, 64497, 64498, 64499],
        "provider_asns": [[64510], [64510, 64511], [64510], [64510, 64511], [0], [64510]],
        "ta": ["ripe", "ripe", "ripe", "ripe", "apnic", "apnic"],
        "expires": [None] * 6,
        "snapshot_date": [DAY1, DAY1, DAY2, DAY2, DAY2, DAY2],
    },
    schema=ASPAS_SCHEMA,
)

REGISTRY = pl.DataFrame(
    {
        "asn": [64496, 64497, 64498],
        "country": ["IN", "IN", "SG"],
        "rir": ["apnic", "apnic", "apnic"],
        "status": ["allocated"] * 3,
    }
)


def test_counts_by_day() -> None:
    result = counts_by_day(ASPAS).to_dicts()
    assert result == [
        {"snapshot_date": DAY1, "aspas": 2, "customer_asns": 2},
        {"snapshot_date": DAY2, "aspas": 4, "customer_asns": 4},
    ]


def test_counts_by_trust_anchor() -> None:
    result = counts_by_ta(ASPAS).to_dicts()
    assert result == [
        {"snapshot_date": DAY1, "ta": "ripe", "aspas": 2},
        {"snapshot_date": DAY2, "ta": "apnic", "aspas": 2},
        {"snapshot_date": DAY2, "ta": "ripe", "aspas": 2},
    ]


def test_counts_by_country_marks_unknown_publishers_rather_than_dropping_them() -> None:
    """AS 64499 is deliberately absent from the registry fixture."""
    day2 = counts_by_country(ASPAS, REGISTRY).filter(pl.col("snapshot_date") == DAY2)
    assert dict(zip(day2["country"], day2["aspas"], strict=True)) == {"IN": 2, "SG": 1, "??": 1}
    # nothing is lost: the country split still sums to the daily total
    assert day2["aspas"].sum() == 4


def test_provider_list_sizes_separates_the_as0_records() -> None:
    """A record whose only provider is AS 0 means "I have no providers" and must not be
    averaged in as though the publisher listed one real upstream."""
    result = provider_list_sizes(ASPAS).to_dicts()
    day2 = next(r for r in result if r["snapshot_date"] == DAY2)
    assert day2["as0_records"] == 1
    assert day2["median_providers"] == 1.0  # from [1, 2, 1], the AS0 row excluded
    assert day2["max_providers"] == 2


def _tables() -> AdoptionTables:
    return AdoptionTables(
        by_day=counts_by_day(ASPAS),
        by_ta=counts_by_ta(ASPAS),
        by_country=counts_by_country(ASPAS, REGISTRY),
        provider_sizes=provider_list_sizes(ASPAS),
    )


def test_to_json_is_serialisable_and_dates_become_strings() -> None:
    payload = to_json(_tables())
    text = json.dumps(payload)  # would raise if a date object survived
    assert payload["latest_snapshot"] == "2026-09-08"
    assert payload["snapshots"] == 2
    assert payload["by_day"][0]["snapshot_date"] == "2026-09-01"
    assert "registered" in payload["caveat_country"]
    assert "2026-09-08" in text


def test_to_json_country_table_covers_only_the_latest_snapshot() -> None:
    payload = to_json(_tables())
    assert {row["snapshot_date"] for row in payload["latest_by_country"]} == {"2026-09-08"}


def test_write_json_round_trips(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    out = write_json(_tables(), tmp_path / "nested" / "aspa_adoption.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["by_trust_anchor"][0]["ta"] == "ripe"


def test_merge_payload_builds_a_series_from_single_day_runs() -> None:
    """The daily CI job ingests one snapshot at a time, so each run must extend the
    published series rather than replace it."""
    from hijax.analysis.adoption import merge_payload

    old = {
        "by_day": [{"snapshot_date": "2026-09-01", "aspas": 2, "customer_asns": 2}],
        "by_trust_anchor": [{"snapshot_date": "2026-09-01", "ta": "ripe", "aspas": 2}],
        "provider_list_sizes": [{"snapshot_date": "2026-09-01", "as0_records": 0}],
        "latest_by_country": [{"snapshot_date": "2026-09-01", "country": "IN", "aspas": 2}],
    }
    new = {
        "by_day": [{"snapshot_date": "2026-09-08", "aspas": 4, "customer_asns": 4}],
        "by_trust_anchor": [{"snapshot_date": "2026-09-08", "ta": "ripe", "aspas": 2}],
        "provider_list_sizes": [{"snapshot_date": "2026-09-08", "as0_records": 1}],
        "latest_by_country": [{"snapshot_date": "2026-09-08", "country": "SG", "aspas": 1}],
    }
    merged = merge_payload(old, new)
    assert [r["snapshot_date"] for r in merged["by_day"]] == ["2026-09-01", "2026-09-08"]
    assert merged["snapshots"] == 2
    assert merged["latest_snapshot"] == "2026-09-08"
    assert merged["latest_by_country"][0]["country"] == "SG"


def test_merge_payload_corrects_a_rerun_day_instead_of_duplicating_it() -> None:
    from hijax.analysis.adoption import merge_payload

    old = {"by_day": [{"snapshot_date": "2026-09-01", "aspas": 2, "customer_asns": 2}]}
    new = {"by_day": [{"snapshot_date": "2026-09-01", "aspas": 3, "customer_asns": 3}]}
    merged = merge_payload(old, new)
    assert merged["by_day"] == [{"snapshot_date": "2026-09-01", "aspas": 3, "customer_asns": 3}]


def test_update_json_appends_across_runs(tmp_path: object) -> None:
    from pathlib import Path

    from hijax.analysis.adoption import update_json

    assert isinstance(tmp_path, Path)
    out = tmp_path / "aspa_adoption.json"
    day1 = ASPAS.filter(pl.col("snapshot_date") == DAY1)
    day2 = ASPAS.filter(pl.col("snapshot_date") == DAY2)
    for frame in (day1, day2):
        update_json(
            AdoptionTables(
                by_day=counts_by_day(frame),
                by_ta=counts_by_ta(frame),
                by_country=counts_by_country(frame, REGISTRY),
                provider_sizes=provider_list_sizes(frame),
            ),
            out,
        )
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert [r["snapshot_date"] for r in loaded["by_day"]] == ["2026-09-01", "2026-09-08"]


def test_aspa_coverage_by_position() -> None:
    """Where a publisher sits on the path decides what it can do, so the shares are split
    by position rather than reported as one number."""
    from hijax.analysis.adoption import aspa_coverage_by_position

    routes = pl.DataFrame(
        {
            "as_path": [
                [1, 2, 3],  # publisher at the origin only
                [4, 5, 6],  # publisher in the middle only
                [7, 8, 9],  # publisher at the neighbour only
                [1, 2, 9],  # two publishers, not adjacent
                [1, 5, 9],  # adjacent pair at 1-5, and 5-9
                [10, 11, 12],  # no publishers at all
            ]
        }
    )
    publishers = {1, 5, 9}
    result = aspa_coverage_by_position(routes, publishers)

    assert result["routes"] == 6
    counts = result["counts"]
    assert counts["any"] == 5  # every route except the last
    assert counts["origin"] == 3  # paths starting 1, 1, 1
    assert counts["neighbour"] == 3  # paths ending 9, 9, 9
    assert counts["transit"] == 2  # the 5 in the middle of two paths
    assert counts["adjacent_pair"] == 1  # only [1, 5, 9] has two side by side
    assert counts["all_hops"] == 1
    assert result["shares"]["any"] == pytest.approx(5 / 6)


def test_aspa_coverage_with_no_publishers() -> None:
    from hijax.analysis.adoption import aspa_coverage_by_position

    routes = pl.DataFrame({"as_path": [[1, 2, 3]]})
    result = aspa_coverage_by_position(routes, set())
    assert result["counts"]["any"] == 0
    assert result["shares"]["any"] == 0.0
