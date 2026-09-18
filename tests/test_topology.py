"""Unit tests for the relationship and organisation lookups (plan Sections 9 and 12).

These use the tiny fixture world the plan defines in Section 12, so later phases can reuse
exactly the same topology for leak detection and the counterfactual:

    AS1 (origin) --c2p--> AS2 --c2p--> AS3 (tier-1)
    AS3 --p2p-- AS4 (tier-1)
    AS4 --p2c--> AS5 --p2c--> AS6
    AS2 --c2p--> AS7 (second provider of AS2)
"""

from __future__ import annotations

import json

import pytest

from hijax.ingest.meta import (
    AsRelation,
    DelegatedFormatError,
    RelationshipLookup,
    SiblingLookup,
    as_rel_frame,
    parse_as2org_jsonl,
    parse_as_rel,
)

#: The fixture world, written in CAIDA's own format.
#: ``provider|customer|-1`` and ``peer|peer|0|source``.
FIXTURE_AS_REL = """\
# a comment line, as the real files start with
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


def test_parse_as_rel_reads_both_row_types() -> None:
    relations = parse_as_rel(FIXTURE_AS_REL.splitlines())
    assert AsRelation(2, 1, "p2c") in relations
    assert AsRelation(3, 4, "p2p") in relations
    assert len(relations) == 6


def test_parse_as_rel_rejects_an_unknown_code() -> None:
    with pytest.raises(DelegatedFormatError, match="relationship code"):
        parse_as_rel(["1|2|5"])


def test_direction_is_from_x_towards_y(world: RelationshipLookup) -> None:
    """The single most confusable part: rel(x, y) answers "what is y to x?"."""
    assert world.rel(1, 2) == "c2p"  # AS2 is AS1's provider, so the route goes up
    assert world.rel(2, 1) == "p2c"  # and from AS2's side, AS1 is its customer
    assert world.rel(3, 4) == "p2p"  # two tier-1 networks peering
    assert world.rel(4, 3) == "p2p"  # peering is symmetric
    assert world.rel(1, 6) is None  # nothing inferred about this pair


def test_providers_customers_and_peers(world: RelationshipLookup) -> None:
    assert world.providers(2) == {3, 7}  # AS2 buys from both AS3 and AS7
    assert world.customers(3) == {2}
    assert world.peers(3) == {4}
    assert world.providers(1) == {2}
    assert world.peers(1) == set()


def test_valley_free_path_reads_up_across_down(world: RelationshipLookup) -> None:
    """The plan's valid example path, 1-2-3-4-5-6, must read as up, up, across, down, down
    (Gao-Rexford, plan Section 3). The path here is in wire order for readability."""
    path = [1, 2, 3, 4, 5, 6]
    steps = [world.rel(a, b) for a, b in zip(path, path[1:], strict=False)]
    assert steps == ["c2p", "c2p", "p2p", "p2c", "p2c"]


def test_a_leak_has_a_valley(world: RelationshipLookup) -> None:
    """A route AS2 learned from its provider AS3 and passed to its other provider AS7 goes
    down-then-up, which is the valley that defines a route leak (RFC 7908)."""
    path = [3, 2, 7]
    steps = [world.rel(a, b) for a, b in zip(path, path[1:], strict=False)]
    assert steps == ["p2c", "c2p"]  # down then up: a valley


def test_lookup_round_trips_through_a_frame() -> None:
    relations = parse_as_rel(FIXTURE_AS_REL.splitlines())
    frame = as_rel_frame(relations, "2026-08")
    assert frame.columns == ["month", "as_a", "as_b", "rel"]
    assert frame.height == 6
    restored = RelationshipLookup.from_frame(frame)
    assert restored.rel(1, 2) == "c2p"
    assert restored.rel(3, 4) == "p2p"


AS2ORG = "\n".join(
    json.dumps(record)
    for record in [
        {
            "type": "Organization",
            "organizationId": "ORG-A",
            "name": "Example Networks",
            "country": "IN",
        },
        {"type": "Organization", "organizationId": "ORG-B", "name": "Other Ltd", "country": "US"},
        {"type": "ASN", "asn": "64496", "organizationId": "ORG-A", "name": "EX-1"},
        {"type": "ASN", "asn": "64497", "organizationId": "ORG-A", "name": "EX-2"},
        {"type": "ASN", "asn": "64510", "organizationId": "ORG-B", "name": "OTH-1"},
    ]
)


def test_as2org_joins_asns_to_their_organisation() -> None:
    frame = parse_as2org_jsonl(AS2ORG.splitlines())
    assert frame.columns == ["asn", "org_id", "org_name", "org_country"]
    row = frame.filter(frame["asn"] == 64496).to_dicts()[0]
    assert row["org_id"] == "ORG-A"
    assert row["org_name"] == "Example Networks"
    assert row["org_country"] == "IN"


def test_siblings_share_an_organisation() -> None:
    """Two AS numbers run by one organisation are siblings, and traffic passing between
    them is not a leak (plan Section 10.4)."""
    lookup = SiblingLookup(parse_as2org_jsonl(AS2ORG.splitlines()))
    assert lookup.are_siblings(64496, 64497)
    assert not lookup.are_siblings(64496, 64510)
    assert not lookup.are_siblings(64496, 99999)  # unknown AS is not a sibling of anything
    assert lookup.org_of(64510) == "ORG-B"
    assert lookup.org_of(99999) is None


def test_asrank_frame_from_api_shaped_nodes() -> None:
    """Node shape quoted from a live AS Rank response verified in Phase 2."""
    from hijax.ingest.meta import asrank_frame

    nodes = [
        {"asn": "3356", "rank": 1, "cone": {"numberAsns": 54887, "numberPrefixes": 935384}},
        {"asn": "64496", "rank": None, "cone": None},
    ]
    frame = asrank_frame(nodes)
    assert frame.columns == ["asn", "rank", "cone_asns", "cone_prefixes"]
    assert frame.row(0, named=True) == {
        "asn": 3356,
        "rank": 1,
        "cone_asns": 54887,
        "cone_prefixes": 935384,
    }
    # a network with no rank yet must not crash or be dropped
    assert frame.row(1, named=True)["rank"] is None
    assert frame.row(1, named=True)["cone_asns"] == 0


def test_build_as_meta_keeps_as_numbers_known_to_only_one_source() -> None:
    """The three sources disagree about which AS numbers exist. Dropping the difference
    would quietly bias every per-country and per-cone figure, so nulls are kept."""
    import polars as pl

    from hijax.ingest.meta import build_as_meta

    registry = pl.DataFrame(
        {
            "asn": [64496, 64497],
            "country": ["IN", "US"],
            "rir": ["apnic", "arin"],
            "status": ["allocated", "assigned"],
        }
    )
    orgs = pl.DataFrame(
        {
            "asn": [64496, 64510],
            "org_id": ["ORG-A", "ORG-C"],
            "org_name": ["A", "C"],
            "org_country": ["IN", "US"],
        }
    )
    ranks = pl.DataFrame({"asn": [64496], "rank": [7], "cone_asns": [12], "cone_prefixes": [34]})

    frame = build_as_meta("2026-08", registry, orgs, ranks)
    assert frame.columns == ["month", "asn", "country", "rir", "org_id", "cone_size", "rank"]
    by_asn = {row["asn"]: row for row in frame.iter_rows(named=True)}
    assert set(by_asn) == {64496, 64497, 64510}

    assert by_asn[64496]["country"] == "IN"
    assert by_asn[64496]["org_id"] == "ORG-A"
    assert by_asn[64496]["cone_size"] == 12
    assert by_asn[64496]["rank"] == 7

    assert by_asn[64497]["org_id"] is None  # in the registry, not in as2org
    assert by_asn[64510]["country"] is None  # in as2org, not in the registry
    assert all(row["month"] == "2026-08" for row in by_asn.values())


def test_month_first_day_matches_caida_file_naming() -> None:
    from hijax.ingest.meta import month_first_day

    assert month_first_day("2026-08") == "20260801"
    assert month_first_day("2023-1") == "20230101"
