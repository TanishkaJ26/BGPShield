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

from bgpshield.detect.leaks import (
    Direction,
    LeakObservation,
    LeakType,
    Shape,
    classify_shape,
    collect_findings,
    detect_in_path,
    find_leakers,
    leak_type,
    path_directions,
)
from bgpshield.ingest.meta import (
    RelationshipLookup,
    SiblingLookup,
    parse_as2org_jsonl,
    parse_as_rel,
)

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


# ---------------------------------------------------------------------------------------
# RFC 7908 typing
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("incoming", "outgoing", "expected"),
    [
        # Type 1: took it from one provider, gave it to another
        (Direction.DOWN, Direction.UP, LeakType.HAIRPIN),
        # Type 2: took it from one peer, gave it to another peer
        (Direction.FLAT, Direction.FLAT, LeakType.LATERAL),
        # Type 3: took it from a provider, gave it to a peer
        (Direction.DOWN, Direction.FLAT, LeakType.PROVIDER_TO_PEER),
        # Type 4: took it from a peer, gave it to a provider
        (Direction.FLAT, Direction.UP, LeakType.PEER_TO_PROVIDER),
    ],
)
def test_rfc_7908_types(incoming: Direction, outgoing: Direction, expected: LeakType) -> None:
    """RFC 7908 Section 3 names these by where the route came from and where it went."""
    assert leak_type(incoming, outgoing) == expected


def test_legitimate_turns_have_no_type() -> None:
    """Taking a route from a customer and passing it anywhere is what transit is."""
    assert leak_type(Direction.UP, Direction.UP) is None
    assert leak_type(Direction.UP, Direction.DOWN) is None
    assert leak_type(Direction.DOWN, Direction.DOWN) is None


# ---------------------------------------------------------------------------------------
# Detecting in a path, and the precision guard
# ---------------------------------------------------------------------------------------


def test_detect_in_path_finds_the_leak(world: RelationshipLookup) -> None:
    path = (AS6, AS5, AS4, AS3, AS2, AS7)
    found = detect_in_path("rrc00", "10.0.0.1", "203.0.113.0/24", path, world)
    assert len(found) == 1
    assert found[0].leaker_asn == AS2
    assert found[0].leak_type is LeakType.HAIRPIN  # from provider AS3 to provider AS7


def test_detect_in_path_ignores_a_valid_path(world: RelationshipLookup) -> None:
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    assert detect_in_path("rrc00", "10.0.0.1", "203.0.113.0/24", path, world) == []


def test_an_undetermined_path_yields_nothing(world: RelationshipLookup) -> None:
    """Plan Section 10.4: a missing relationship next to the suspected turn means
    undetermined, not a leak."""
    path = (AS1, 999, AS2, AS7)
    assert detect_in_path("rrc00", "10.0.0.1", "203.0.113.0/24", path, world) == []


def observation(peer: str, prefix: str = "203.0.113.0/24", collector: str = "rrc00") -> object:
    return LeakObservation(
        collector=collector,
        peer_ip=peer,
        prefix=prefix,
        leaker_asn=AS2,
        leak_type=LeakType.HAIRPIN,
        position=5,
        path=(AS6, AS5, AS4, AS3, AS2, AS7),
    )


def test_one_peer_is_not_enough() -> None:
    """A single vantage point seeing an odd path is as likely to be an error in the inferred
    topology as a real event, so it is kept but marked uncorroborated."""
    findings = collect_findings([observation("10.0.0.1")])  # type: ignore[list-item]
    assert len(findings) == 1
    assert findings[0].distinct_peers == 1
    assert findings[0].corroborated is False


def test_two_peers_corroborate() -> None:
    findings = collect_findings(
        [observation("10.0.0.1"), observation("10.0.0.2")]  # type: ignore[list-item]
    )
    assert findings[0].distinct_peers == 2
    assert findings[0].corroborated is True


def test_the_same_peer_twice_is_still_one_vantage_point() -> None:
    """Seeing the same leak from the same peer twice adds no independent evidence."""
    findings = collect_findings(
        [observation("10.0.0.1"), observation("10.0.0.1")]  # type: ignore[list-item]
    )
    assert findings[0].observations == 2
    assert findings[0].distinct_peers == 1
    assert findings[0].corroborated is False


def test_one_event_seen_widely_is_still_one_finding() -> None:
    """Twenty peers seeing one leak is one event, not twenty."""
    findings = collect_findings(
        [observation(f"10.0.0.{n}") for n in range(1, 21)]  # type: ignore[list-item]
    )
    assert len(findings) == 1
    assert findings[0].observations == 20
    assert findings[0].distinct_peers == 20


def test_different_prefixes_are_different_findings() -> None:
    findings = collect_findings(
        [  # type: ignore[list-item]
            observation("10.0.0.1", "203.0.113.0/24"),
            observation("10.0.0.2", "203.0.113.0/24"),
            observation("10.0.0.1", "198.51.100.0/24"),
        ]
    )
    assert len(findings) == 2
    corroborated = [f for f in findings if f.corroborated]
    assert len(corroborated) == 1
    assert corroborated[0].prefix == "203.0.113.0/24"


def test_collectors_are_counted_too() -> None:
    findings = collect_findings(
        [  # type: ignore[list-item]
            observation("10.0.0.1", collector="rrc00"),
            observation("10.0.0.2", collector="route-views2"),
        ]
    )
    assert findings[0].distinct_collectors == 2
