"""RQ2 correctness tests (plan Sections 11 Phase 4, and 12).

Hand-built throughout. The fixture world is the plan's Section 12 topology, so a publisher's
"true" provider set is known and a deliberately incomplete record can be checked against it.
"""

from __future__ import annotations

import polars as pl
import pytest

from hijax.analysis.correctness import (
    blame_by_as,
    compare_providers,
    completeness_summary,
    estimate_false_positives,
)
from hijax.ingest.meta import RelationshipLookup, parse_as_rel
from hijax.ingest.rpki import ASPAS_SCHEMA

AS1, AS2, AS3, AS4, AS5, AS6, AS7 = 1, 2, 3, 4, 5, 6, 7

FIXTURE_AS_REL = """\
2|1|-1
3|2|-1
7|2|-1
3|4|0|bgp
4|5|-1
5|6|-1
"""


@pytest.fixture
def world() -> RelationshipLookup:
    return RelationshipLookup(parse_as_rel(FIXTURE_AS_REL.splitlines()))


def aspas(records: dict[int, list[int]]) -> pl.DataFrame:
    from datetime import date

    return pl.DataFrame(
        {
            "customer_asn": list(records),
            "provider_asns": list(records.values()),
            "ta": ["ripe"] * len(records),
            "expires": [None] * len(records),
            "snapshot_date": [date(2026, 9, 1)] * len(records),
        },
        schema=ASPAS_SCHEMA,
    )


# ---------------------------------------------------------------------------------------
# Comparing published records with inferred topology
# ---------------------------------------------------------------------------------------


def test_a_complete_record_agrees(world: RelationshipLookup) -> None:
    """AS2 really does buy from AS3 and AS7, and its record says so."""
    frame = compare_providers(aspas({AS2: [AS3, AS7]}), world)
    row = frame.row(0, named=True)
    assert row["missing"] == []
    assert row["extra"] == []
    assert row["agrees"] is True


def test_an_incomplete_record_shows_the_missing_provider(world: RelationshipLookup) -> None:
    """AS2 lists only AS3, so AS7 is a candidate omission. This is the exact shape of the
    real case found in Phase 3."""
    frame = compare_providers(aspas({AS2: [AS3]}), world)
    row = frame.row(0, named=True)
    assert row["missing"] == [AS7]
    assert row["extra"] == []
    assert row["agrees"] is False


def test_a_provider_the_inference_has_not_seen_is_reported_separately(
    world: RelationshipLookup,
) -> None:
    """The other direction usually means CAIDA has not observed the link, not that the
    operator invented it, so it is counted apart from omissions."""
    frame = compare_providers(aspas({AS2: [AS3, AS7, AS6]}), world)
    row = frame.row(0, named=True)
    assert row["missing"] == []
    assert row["extra"] == [AS6]


def test_an_as0_record_contradicted_by_the_topology(world: RelationshipLookup) -> None:
    """AS2 declaring "I have no providers" while CAIDA infers two is the strongest kind of
    disagreement, so the effective published set is empty and both count as missing."""
    frame = compare_providers(aspas({AS2: [0]}), world)
    row = frame.row(0, named=True)
    assert row["is_as0"] is True
    assert row["published"] == []
    assert row["missing"] == [AS3, AS7]


def test_a_correct_as0_record_for_a_tier_one(world: RelationshipLookup) -> None:
    """AS3 genuinely has no providers in the fixture world, so its AS0 record agrees."""
    frame = compare_providers(aspas({AS3: [0]}), world)
    row = frame.row(0, named=True)
    assert row["is_as0"] is True
    assert row["missing"] == []
    assert row["agrees"] is True


def test_summary_counts(world: RelationshipLookup) -> None:
    frame = compare_providers(
        aspas(
            {
                AS2: [AS3],  # missing AS7
                AS3: [0],  # correct AS0
                AS1: [AS2],  # correct
                AS5: [0],  # AS0 but AS4 is inferred: contradicted
            }
        ),
        world,
    )
    summary = completeness_summary(frame)
    assert summary["publishers"] == 4
    assert summary["agree_exactly"] == 2
    assert summary["missing_at_least_one"] == 2
    assert summary["missing_share"] == pytest.approx(0.5)
    assert summary["as0_records"] == 2
    assert summary["as0_contradicted"] == 1


def test_a_publisher_with_no_inference_cannot_be_judged(world: RelationshipLookup) -> None:
    """A network claiming a provider that CAIDA has never seen cannot be judged either way."""
    frame = compare_providers(aspas({999: [AS3]}), world)
    summary = completeness_summary(frame)
    assert summary["cannot_judge"] == 1
    assert summary["as0_corroborated"] == 0


def test_a_correct_as0_record_is_corroboration_not_a_gap(world: RelationshipLookup) -> None:
    """AS3 is a tier-1: it says it has no providers and the inference sees none. Both agree,
    so this must count as corroboration rather than as missing evidence."""
    frame = compare_providers(aspas({AS3: [0]}), world)
    summary = completeness_summary(frame)
    assert summary["as0_corroborated"] == 1
    assert summary["cannot_judge"] == 0
    assert summary["agree_exactly"] == 1


def test_empty_input() -> None:
    assert completeness_summary(compare_providers(aspas({}), RelationshipLookup([]))) == {
        "publishers": 0
    }


# ---------------------------------------------------------------------------------------
# Estimating how many Invalid routes are actually false positives
# ---------------------------------------------------------------------------------------


def invalid_routes(paths: list[tuple[list[int], bool]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "as_path": [p for p, _ in paths],
            "has_as_set": [s for _, s in paths],
        }
    )


def test_a_genuinely_leaked_path_is_not_a_false_positive(world: RelationshipLookup) -> None:
    """AS2 hands a provider-learned route to its other provider: ASPA and the shape test
    agree, so this Invalid verdict is corroborated."""
    frame = invalid_routes([([AS6, AS5, AS4, AS3, AS2, AS7], False)])
    estimate = estimate_false_positives(frame, world)
    assert estimate.valley == 1
    assert estimate.valley_free == 0
    assert estimate.likely_false_positive_share == 0.0


def test_a_well_shaped_path_marked_invalid_is_a_likely_false_positive(
    world: RelationshipLookup,
) -> None:
    """The path climbs properly, so if ASPA called it Invalid the record is the suspect."""
    frame = invalid_routes([([AS1, AS2, AS3], False)])
    estimate = estimate_false_positives(frame, world)
    assert estimate.valley_free == 1
    assert estimate.likely_false_positive_share == 1.0


def test_as_set_routes_are_counted_apart(world: RelationshipLookup) -> None:
    """An AS_SET path is Invalid for a reason unrelated to record quality, so it must not
    land in either bucket."""
    frame = invalid_routes([([AS1, AS2, AS3], True)])
    estimate = estimate_false_positives(frame, world)
    assert estimate.as_set == 1
    assert estimate.valley == 0
    assert estimate.valley_free == 0
    assert estimate.likely_false_positive_share == 0.0


def test_undetermined_paths_are_excluded_from_the_share(world: RelationshipLookup) -> None:
    """A path with a missing relationship cannot be judged, so it neither supports nor
    undermines the Invalid verdict, and must not dilute the ratio."""
    frame = invalid_routes(
        [
            ([AS6, AS5, AS4, AS3, AS2, AS7], False),  # valley
            ([AS1, AS2, AS3], False),  # valley free
            ([AS1, 999, AS3], False),  # unknown relationships
        ]
    )
    estimate = estimate_false_positives(frame, world)
    assert estimate.invalid_routes == 3
    assert estimate.undetermined == 1
    assert estimate.likely_false_positive_share == pytest.approx(0.5)


# ---------------------------------------------------------------------------------------
# Which networks' records are behind the most Invalid routes
# ---------------------------------------------------------------------------------------


def test_blame_is_attributed_to_the_publisher_not_the_claimed_provider() -> None:
    """The contradicting record belongs to the customer side of the hop."""
    frame = pl.DataFrame(
        {
            "first_bad_hop_from": [AS2, AS2, AS2, AS5, None],
            "first_bad_hop_to": [AS7, AS7, AS6, AS3, None],
            "prefix": ["a", "b", "c", "d", "e"],
        }
    )
    ranked = blame_by_as(frame)
    top = ranked.row(0, named=True)
    assert top["asn"] == AS2
    assert top["invalid_routes"] == 3
    assert top["distinct_claimed_providers"] == 2
    assert top["distinct_prefixes"] == 3
    # the row with no contradicted hop is excluded rather than blamed on anyone
    assert ranked.height == 2
