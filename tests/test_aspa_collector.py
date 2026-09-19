"""Applying ASPA to route-collector data (plan Sections 10.3 and 12).

These use the tiny fixture world the plan defines in Section 12, and cover the four cases it
lists there: the valid path, a leak via AS2, an incomplete ASPA record turning a legitimate
path Invalid, and no ASPA records at all giving Unknown.

    AS1 --c2p--> AS2 --c2p--> AS3 (tier-1)
    AS3 --p2p-- AS4 (tier-1)
    AS4 --p2c--> AS5 --p2c--> AS6
    AS2 --c2p--> AS7 (second provider of AS2)
"""

from __future__ import annotations

import pytest

from bgpshield.ingest.meta import RelationshipLookup, parse_as_rel
from bgpshield.validate.aspa import (
    AspaRegistry,
    AspaState,
    Procedure,
    first_block_point,
    procedure_for,
    verify_at_collector,
    verify_upstream,
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

#: Complete and correct ASPAs for the fixture world. The two tier-1 networks publish AS0
#: ASPAs, which state "I have no providers".
COMPLETE = AspaRegistry(
    {
        AS1: {AS2},
        AS2: {AS3, AS7},
        AS3: {0},
        AS4: {0},
        AS5: {AS4},
        AS6: {AS5},
    }
)

#: The same world, except AS2 forgot to list AS7 as a provider.
INCOMPLETE = AspaRegistry(
    {
        AS1: {AS2},
        AS2: {AS3},
        AS3: {0},
        AS4: {0},
        AS5: {AS4},
        AS6: {AS5},
    }
)

EMPTY = AspaRegistry({})


@pytest.fixture
def world() -> RelationshipLookup:
    return RelationshipLookup(parse_as_rel(FIXTURE_AS_REL.splitlines()))


# ---------------------------------------------------------------------------------------
# Choosing the procedure
# ---------------------------------------------------------------------------------------


def test_procedure_follows_the_relationship_to_the_neighbour() -> None:
    """A route from a customer or a lateral peer must be a pure climb, so it takes the
    upstream procedure. A route from a provider may climb then descend, so downstream."""
    assert procedure_for("p2c") is Procedure.UPSTREAM  # neighbour is my customer
    assert procedure_for("p2p") is Procedure.UPSTREAM  # neighbour is a lateral peer
    assert procedure_for("c2p") is Procedure.DOWNSTREAM  # neighbour is my provider
    assert procedure_for(None) is None  # unknown: the caller runs both


# ---------------------------------------------------------------------------------------
# The four cases the plan names in Section 12
# ---------------------------------------------------------------------------------------


def test_the_valid_path_is_valid(world: RelationshipLookup) -> None:
    """A prefix from AS1 reaching AS6 climbs to the tier-1s, crosses once, and descends.
    The collector peers with AS6, so what is checked is the path AS6 received from AS5."""
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    result = verify_at_collector(path, COMPLETE, world)
    assert result.procedure == "downstream"  # AS5 is AS6's provider
    assert result.state is AspaState.VALID


def test_a_leak_via_as2_is_invalid(world: RelationshipLookup) -> None:
    """AS2 learns a route from its provider AS3 and passes it to its other provider AS7.
    That is a valley, and RFC 7908 calls it a route leak. The collector peers with AS7."""
    path = (AS6, AS5, AS4, AS3, AS2, AS7)
    result = verify_at_collector(path, COMPLETE, world)
    assert result.procedure == "upstream"  # AS2 is AS7's customer
    assert result.state is AspaState.INVALID
    assert result.upstream is not None
    # AS4 published an AS0 ASPA, so naming AS3 as its provider is a positive contradiction
    assert result.upstream.first_bad_hop == (AS4, AS3)


def test_an_incomplete_aspa_turns_a_legitimate_path_invalid() -> None:
    """The false-positive risk that RQ2 is about. AS7 really is a provider of AS2, but AS2's
    published record omits it, so a perfectly legitimate route via AS7 is contradicted."""
    legitimate = (AS1, AS2, AS7)
    assert verify_upstream(legitimate, COMPLETE).state is AspaState.VALID

    result = verify_upstream(legitimate, INCOMPLETE)
    assert result.state is AspaState.INVALID
    assert result.first_bad_hop == (AS2, AS7)


def test_no_aspa_records_anywhere_gives_unknown() -> None:
    """With nothing published, nothing is confirmed and nothing is contradicted. Reporting
    Valid here would claim support the data does not provide."""
    assert verify_upstream((AS1, AS2, AS3), EMPTY).state is AspaState.UNKNOWN


# ---------------------------------------------------------------------------------------
# Unknown relationships, which must be reported separately
# ---------------------------------------------------------------------------------------


def test_an_unknown_relationship_runs_both_procedures() -> None:
    """CAIDA infers nothing about some pairs. The plan (Section 10.3) says to run both and
    report those routes separately rather than guessing."""

    class NoRelationships:
        def rel(self, x: int, y: int) -> str | None:
            return None

    path = (AS6, AS5, AS4, AS3, AS2, AS7)
    result = verify_at_collector(path, COMPLETE, NoRelationships())
    assert result.procedure == "both"
    assert not result.relationship_known
    assert result.upstream is not None and result.downstream is not None


def test_the_more_severe_of_the_two_is_reported() -> None:
    """When the two procedures disagree, the combined state is the stricter one, so an
    ambiguous route is never presented as clean."""

    class NoRelationships:
        def rel(self, x: int, y: int) -> str | None:
            return None

    # Upstream says Invalid here, downstream says Valid, because the path climbs and descends.
    path = (AS1, AS2, AS3, AS4, AS5, AS6)
    result = verify_at_collector(path, COMPLETE, NoRelationships())
    assert result.upstream is not None and result.upstream.state is AspaState.INVALID
    assert result.downstream is not None and result.downstream.state is AspaState.VALID
    assert result.state is AspaState.INVALID


def test_a_path_too_short_to_have_been_relayed() -> None:
    """With only the peer itself on the path, there is no earlier hop whose check could be
    reconstructed."""
    result = verify_at_collector((AS6,), COMPLETE, RelationshipLookup([]))
    assert result.state is AspaState.UNKNOWN
    assert result.procedure == "both"


# ---------------------------------------------------------------------------------------
# Hop by hop: where would the route have been stopped?
# ---------------------------------------------------------------------------------------


def test_the_leak_is_stopped_at_the_first_network_that_checks(
    world: RelationshipLookup,
) -> None:
    """The counterfactual question from plan Section 10.6: if these networks filtered on
    ASPA, where would this leaked route have died?

    The answer is AS7, the network the leaker handed it to, and the reason is worth
    following. Every earlier network along the path sees something legitimate:

    * AS4 receives AS6 AS5, a clean climb from the origin.
    * AS3 receives AS6 AS5 AS4 from its lateral peer AS4, still a clean climb.
    * AS2 receives AS6 AS5 AS4 AS3 from its provider AS3, so the downstream procedure
      applies and the climb plus the one-hop descent span the path.

    Only when AS2 passes it up to its other provider AS7 does the path have to be read as a
    pure climb again, and AS4's AS0 ASPA contradicts it. A leak is invisible until it
    arrives somewhere it should never have gone."""
    leak = (AS6, AS5, AS4, AS3, AS2, AS7)
    block = first_block_point(leak, COMPLETE, world)
    assert block is not None
    assert block.blocking_asn == AS7
    assert block.position == 6
    assert block.relative_position(len(leak)) == pytest.approx(1.0)
    assert block.result.first_bad_hop == (AS4, AS3)


def test_a_valid_path_is_never_blocked(world: RelationshipLookup) -> None:
    assert first_block_point((AS1, AS2, AS3), COMPLETE, world) is None


def test_only_filtering_networks_can_block(world: RelationshipLookup) -> None:
    """Scenario F-topN: most networks do not filter, so the route survives until it reaches
    one that does."""
    leak = (AS6, AS5, AS4, AS3, AS2, AS7)
    # Nobody filters, so the leak propagates the whole way.
    assert first_block_point(leak, COMPLETE, world, filtering=set()) is None
    # AS3 filters, but what AS3 sees is legitimate, so it still does not stop.
    assert first_block_point(leak, COMPLETE, world, filtering={AS3}) is None
    # AS7 is the one network positioned to see the valley.
    stopped = first_block_point(leak, COMPLETE, world, filtering={AS7})
    assert stopped is not None
    assert stopped.blocking_asn == AS7


def test_nothing_blocks_when_no_records_exist(world: RelationshipLookup) -> None:
    """Without ASPA records every hop is Unknown, and Unknown does not get dropped
    (draft Section 5.7 says treat Unknown like Valid)."""
    leak = (AS6, AS5, AS4, AS3, AS2, AS7)
    assert first_block_point(leak, EMPTY, world) is None
