"""Path shape and leak-candidate tests (plan Sections 10.4 and 12).

Uses the fixture world from plan Section 12, so the same topology carries through from the
relationship tests to ASPA verification to here:

    AS1 --c2p--> AS2 --c2p--> AS3 (tier-1)
    AS3 --p2p-- AS4 (tier-1)
    AS4 --p2c--> AS5 --p2c--> AS6
    AS2 --c2p--> AS7 (second provider of AS2)

Paths are origin first, as everywhere in this project.
"""

from __future__ import annotations

import pytest

from hijax.detect.leaks import (
    Direction,
    Shape,
    classify_shape,
    find_leakers,
    path_directions,
)
from hijax.ingest.meta import RelationshipLookup, SiblingLookup, parse_as2org_jsonl, parse_as_rel

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


# ---------------------------------------------------------------------------------------
# Direction classification
# ---------------------------------------------------------------------------------------


def test_directions_along_the_valid_path(world: RelationshipLookup) -> None:
    """The plan's valid example: climb to the tier-1s, cross once, descend."""
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    assert path_directions(path, world) == [
        Direction.UP,
        Direction.UP,
        Direction.FLAT,
        Direction.DOWN,
        Direction.DOWN,
    ]


def test_unknown_pairs_are_marked_not_guessed(world: RelationshipLookup) -> None:
    assert path_directions((AS1, AS6), world) == [Direction.UNKNOWN]


# ---------------------------------------------------------------------------------------
# The valley-free rule
# ---------------------------------------------------------------------------------------


def test_the_valid_path_is_valley_free(world: RelationshipLookup) -> None:
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    assert classify_shape(path_directions(path, world)) is Shape.VALLEY_FREE


def test_a_leak_is_a_valley(world: RelationshipLookup) -> None:
    """AS2 takes a route from its provider AS3 and hands it to its other provider AS7:
    down then up, which is the shape RFC 7908 calls a leak."""
    path = (AS6, AS5, AS4, AS3, AS2, AS7)
    assert classify_shape(path_directions(path, world)) is Shape.VALLEY


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([], Shape.VALLEY_FREE),
        ([Direction.UP], Shape.VALLEY_FREE),
        ([Direction.UP, Direction.UP], Shape.VALLEY_FREE),
        ([Direction.DOWN, Direction.DOWN], Shape.VALLEY_FREE),
        ([Direction.UP, Direction.FLAT, Direction.DOWN], Shape.VALLEY_FREE),
        ([Direction.FLAT], Shape.VALLEY_FREE),
        # a second crossing is not allowed
        ([Direction.FLAT, Direction.FLAT], Shape.VALLEY),
        # climbing after crossing
        ([Direction.FLAT, Direction.UP], Shape.VALLEY),
        # climbing after descending
        ([Direction.DOWN, Direction.UP], Shape.VALLEY),
        # crossing after descending
        ([Direction.DOWN, Direction.FLAT], Shape.VALLEY),
    ],
)
def test_shape_rule(steps: list[Direction], expected: Shape) -> None:
    """The rule is up any number of times, across at most once, then down any number."""
    assert classify_shape(steps) is expected


def test_an_unknown_step_makes_the_verdict_undetermined() -> None:
    """Without the relationship there is no way to know, so no claim is made."""
    assert classify_shape([Direction.UP, Direction.UNKNOWN, Direction.DOWN]) is Shape.UNDETERMINED


def test_a_known_valley_stands_despite_an_unknown_elsewhere() -> None:
    """If the steps we do know already form a valley, a gap somewhere else cannot undo it."""
    steps = [Direction.DOWN, Direction.UP, Direction.UNKNOWN]
    assert classify_shape(steps) is Shape.VALLEY


def test_siblings_are_transparent() -> None:
    """Two AS numbers of one organisation are one network, so the hop between them says
    nothing about the hierarchy and must not create a false valley."""
    steps = [Direction.UP, Direction.SIBLING, Direction.UP]
    assert classify_shape(steps) is Shape.VALLEY_FREE


def test_sibling_detection_uses_the_organisation_mapping(world: RelationshipLookup) -> None:
    import json

    records = [
        {"type": "Organization", "organizationId": "ORG-A", "name": "A", "country": "IN"},
        {"type": "ASN", "asn": "1", "organizationId": "ORG-A", "name": "AS1"},
        {"type": "ASN", "asn": "6", "organizationId": "ORG-A", "name": "AS6"},
    ]
    siblings = SiblingLookup(parse_as2org_jsonl(json.dumps(r) for r in records))
    # AS1 and AS6 have no inferred relationship, but they are one organisation
    assert path_directions((AS1, AS6), world) == [Direction.UNKNOWN]
    assert path_directions((AS1, AS6), world, siblings) == [Direction.SIBLING]


# ---------------------------------------------------------------------------------------
# Who turned the path around
# ---------------------------------------------------------------------------------------


def test_the_leaker_is_identified(world: RelationshipLookup) -> None:
    path = (AS6, AS5, AS4, AS3, AS2, AS7)
    directions = path_directions(path, world)
    leakers = find_leakers(path, directions)
    assert len(leakers) == 1
    assert leakers[0].leaker_asn == AS2
    assert leakers[0].incoming is Direction.DOWN
    assert leakers[0].outgoing is Direction.UP


def test_no_leaker_on_a_valid_path(world: RelationshipLookup) -> None:
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    assert find_leakers(path, path_directions(path, world)) == []


def test_the_origin_and_the_last_network_cannot_be_leakers() -> None:
    """Each has only one step, so neither can have turned a route around."""
    path = (10, 20, 30)
    directions = [Direction.DOWN, Direction.UP]
    leakers = find_leakers(path, directions)
    assert [candidate.leaker_asn for candidate in leakers] == [20]


def test_a_peer_to_peer_leak_is_caught() -> None:
    """Taking a route from one peer and handing it to another is also a leak."""
    path = (10, 20, 30)
    leakers = find_leakers(path, [Direction.FLAT, Direction.FLAT])
    assert len(leakers) == 1
    assert leakers[0].leaker_asn == 20
