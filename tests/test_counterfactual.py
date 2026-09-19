"""Counterfactual tests for RQ3 (plan Sections 10.6 and 12).

Uses the plan's Section 12 fixture world, with the leak it defines: AS2 takes a route from
its provider AS3 and hands it to its other provider AS7.

    AS1 --c2p--> AS2 --c2p--> AS3 (tier-1)
    AS3 --p2p-- AS4 (tier-1)
    AS4 --p2c--> AS5 --p2c--> AS6
    AS2 --c2p--> AS7 (second provider of AS2)
"""

from __future__ import annotations

import polars as pl
import pytest

from bgpshield.counterfactual import (
    Filtering,
    Outcome,
    Publication,
    build_scenario,
    evaluate_route,
    filtering_set,
    summarise,
    top_by_cone,
)
from bgpshield.ingest.meta import RelationshipLookup, parse_as_rel

AS1, AS2, AS3, AS4, AS5, AS6, AS7 = 1, 2, 3, 4, 5, 6, 7

FIXTURE_AS_REL = """\
2|1|-1
3|2|-1
7|2|-1
3|4|0|bgp
4|5|-1
5|6|-1
"""

#: The leaked route from plan Section 12, origin first.
LEAK = (AS6, AS5, AS4, AS3, AS2, AS7)

#: Customer cones, largest first: the two tier-1 networks, then AS5, then the rest.
AS_META = pl.DataFrame(
    {
        "asn": [AS3, AS4, AS5, AS2, AS7, AS1, AS6],
        "cone_size": [500, 400, 50, 10, 8, 1, 1],
    }
)


@pytest.fixture
def world() -> RelationshipLookup:
    return RelationshipLookup(parse_as_rel(FIXTURE_AS_REL.splitlines()))


# ---------------------------------------------------------------------------------------
# Choosing the largest networks
# ---------------------------------------------------------------------------------------


def test_top_by_cone_orders_by_customer_cone() -> None:
    assert top_by_cone(AS_META, 3) == [AS3, AS4, AS5]


def test_networks_without_a_cone_are_excluded() -> None:
    frame = pl.DataFrame({"asn": [1, 2, 3], "cone_size": [None, 0, 5]})
    assert top_by_cone(frame, 10) == [3]


def test_filtering_sets() -> None:
    """F-all means everyone filters, which is expressed as no restriction at all."""
    assert filtering_set(Filtering.F_ALL, AS_META) is None
    assert filtering_set(Filtering.F_TOP20, AS_META) == {AS3, AS4, AS5, AS2, AS7, AS1, AS6}


# ---------------------------------------------------------------------------------------
# Building the publication scenarios
# ---------------------------------------------------------------------------------------


def test_s0_uses_only_real_records(world: RelationshipLookup) -> None:
    real = {AS1: frozenset({AS2})}
    scenario = build_scenario(Publication.S0, real, world, AS_META)
    assert scenario.real_records == 1
    assert scenario.synthetic_records == 0
    assert scenario.synthetic_share == 0.0
    assert not scenario.is_upper_bound


def test_s3_invents_a_record_for_every_known_network(world: RelationshipLookup) -> None:
    """All seven networks are in the topology, so all seven get a record. The four with
    inferred providers get those; the three at the top get an AS0 record saying they have
    none, which is what a real tier-1 publishes."""
    scenario = build_scenario(Publication.S3, {}, world, AS_META)
    assert scenario.synthetic_records == 7
    assert scenario.registry.providers_of(AS2) == frozenset({AS3, AS7})
    assert scenario.registry.providers_of(AS3) == frozenset({0})
    assert scenario.registry.providers_of(AS4) == frozenset({0})


def test_a_network_absent_from_the_topology_gets_no_record(
    world: RelationshipLookup,
) -> None:
    """ "No providers inferred" and "never heard of it" are different statements, and only
    the first justifies asserting that a network has no providers."""
    scenario = build_scenario(Publication.S3, {}, world, AS_META)
    assert 999 not in scenario.registry


def test_a_real_record_is_never_overwritten_by_a_synthetic_one(
    world: RelationshipLookup,
) -> None:
    """An operator's own statement wins, even when the inference disagrees. Otherwise the
    scenarios would quietly erase the real data they are supposed to extend."""
    real = {AS2: frozenset({AS3})}  # deliberately incomplete: AS7 is missing
    scenario = build_scenario(Publication.S3, real, world, AS_META)
    assert scenario.registry.providers_of(AS2) == frozenset({AS3})


def test_s1_only_reaches_the_largest_networks(world: RelationshipLookup) -> None:
    """With a top-100 cut and only seven networks in the fixture, S1 and S3 coincide here;
    what matters is that the selection goes through the cone ranking."""
    s1 = build_scenario(Publication.S1, {}, world, AS_META)
    assert s1.synthetic_records == 7


def test_s3_is_flagged_as_an_upper_bound(world: RelationshipLookup) -> None:
    """Plan Section 10.6 requires the circularity caveat to travel with the result."""
    assert build_scenario(Publication.S3, {}, world, AS_META).is_upper_bound
    assert not build_scenario(Publication.S0, {}, world, AS_META).is_upper_bound


# ---------------------------------------------------------------------------------------
# Evaluating the leak
# ---------------------------------------------------------------------------------------


def test_with_no_records_published_nothing_blocks_the_leak(world: RelationshipLookup) -> None:
    """The honest baseline: today, most networks have published nothing, and an Unknown
    verdict is not dropped (draft Section 5.7)."""
    scenario = build_scenario(Publication.S0, {}, world, AS_META)
    outcomes = evaluate_route(LEAK, [scenario], [Filtering.F_ALL], world, AS_META)
    assert len(outcomes) == 1
    assert outcomes[0].blocked is False


def test_with_everybody_publishing_the_leak_is_blocked(world: RelationshipLookup) -> None:
    """S3, the upper bound. AS7 is where the valley becomes visible, as Phase 3 established:
    every earlier network on the path sees something legitimate."""
    scenario = build_scenario(Publication.S3, {}, world, AS_META)
    outcomes = evaluate_route(LEAK, [scenario], [Filtering.F_ALL], world, AS_META)
    assert outcomes[0].blocked is True
    assert outcomes[0].blocking_asn == AS7
    assert outcomes[0].blocking_position == 6
    assert outcomes[0].upper_bound_only is True


def test_the_upper_bound_flag_survives_into_the_result(world: RelationshipLookup) -> None:
    """A results table must not be able to lose the caveat."""
    s0 = build_scenario(Publication.S0, {}, world, AS_META)
    s3 = build_scenario(Publication.S3, {}, world, AS_META)
    outcomes = evaluate_route(LEAK, [s0, s3], [Filtering.F_ALL], world, AS_META)
    flags = {o.publication: o.upper_bound_only for o in outcomes}
    assert flags[Publication.S0] is False
    assert flags[Publication.S3] is True


def test_filtering_decides_whether_publication_helps(world: RelationshipLookup) -> None:
    """Publishing protects other people; dropping Invalid routes is what stops the leak.
    With records everywhere but nobody acting on them, the leak still propagates."""
    scenario = build_scenario(Publication.S3, {}, world, AS_META)
    nobody = pl.DataFrame({"asn": [999], "cone_size": [1]})
    outcomes = evaluate_route(LEAK, [scenario], [Filtering.F_TOP20], world, nobody)
    assert outcomes[0].blocked is False


def test_every_combination_is_evaluated(world: RelationshipLookup) -> None:
    scenarios = [
        build_scenario(p, {}, world, AS_META)
        for p in (Publication.S0, Publication.S1, Publication.S2, Publication.S3)
    ]
    filterings = [Filtering.F_ALL, Filtering.F_TOP20, Filtering.F_TOP100]
    outcomes = evaluate_route(LEAK, scenarios, filterings, world, AS_META)
    assert len(outcomes) == 12
    assert {(o.publication, o.filtering) for o in outcomes} == {
        (p, f) for p in Publication for f in filterings
    }


def test_a_legitimate_route_is_never_blocked(world: RelationshipLookup) -> None:
    """The counterfactual must not claim to stop traffic that should flow."""
    good = (AS1, AS2, AS3, AS4, AS5, AS6)
    scenario = build_scenario(Publication.S3, {}, world, AS_META)
    outcomes = evaluate_route(good, [scenario], [Filtering.F_ALL], world, AS_META)
    assert outcomes[0].blocked is False


# ---------------------------------------------------------------------------------------
# Summarising
# ---------------------------------------------------------------------------------------


def test_summary_reports_share_and_position() -> None:
    outcomes = [
        Outcome(Publication.S3, Filtering.F_ALL, True, AS7, 6, 1.0, True),
        Outcome(Publication.S3, Filtering.F_ALL, True, AS7, 3, 0.5, True),
        Outcome(Publication.S3, Filtering.F_ALL, False, None, None, None, True),
        Outcome(Publication.S0, Filtering.F_ALL, False, None, None, None, False),
    ]
    frame = summarise(outcomes)
    s3 = frame.filter(pl.col("publication") == "S3").row(0, named=True)
    assert s3["routes"] == 3
    assert s3["blocked"] == 2
    assert s3["blocked_share"] == pytest.approx(2 / 3)
    assert s3["upper_bound_only"] is True
    s0 = frame.filter(pl.col("publication") == "S0").row(0, named=True)
    assert s0["blocked_share"] == 0.0
    assert s0["median_blocking_position"] is None
