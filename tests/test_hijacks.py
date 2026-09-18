"""Hijack candidate tests (plan Sections 10.5 and 12).

Hand-built throughout, using documentation address space (RFC 5737, RFC 3849) and
documentation AS numbers (RFC 5398).

The plan is explicit that this detector stays simple and that everything it produces is a
candidate, not a conclusion.
"""

from __future__ import annotations

import json

from hijax.detect.hijacks import CandidateType, find_candidates
from hijax.ingest.meta import SiblingLookup, parse_as2org_jsonl

HOLDER = 64496
SIBLING = 64497
STRANGER = 64510


def siblings() -> SiblingLookup:
    records = [
        {"type": "Organization", "organizationId": "ORG-A", "name": "A", "country": "IN"},
        {"type": "ASN", "asn": str(HOLDER), "organizationId": "ORG-A", "name": "one"},
        {"type": "ASN", "asn": str(SIBLING), "organizationId": "ORG-A", "name": "two"},
    ]
    return SiblingLookup(parse_as2org_jsonl(json.dumps(r) for r in records))


def test_a_stable_prefix_produces_nothing() -> None:
    current = {"203.0.113.0/24": {HOLDER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline) == []


def test_a_new_origin_is_flagged() -> None:
    current = {"203.0.113.0/24": {STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    found = find_candidates(current, baseline)
    assert len(found) == 1
    assert found[0].candidate_type is CandidateType.ORIGIN_CHANGE
    assert found[0].origin_asn == STRANGER
    assert found[0].baseline_origins == (HOLDER,)


def test_a_sibling_taking_over_is_not_flagged_once_siblings_are_known() -> None:
    """Two AS numbers of one organisation swapping which announces a prefix is routine.

    Without the organisation mapping the detector cannot know they are related, so it does
    flag it. That is the correct behaviour: the suppression comes from evidence, not from a
    guess, which is why the organisation data is worth loading."""
    current = {"203.0.113.0/24": {SIBLING}}
    baseline = {"203.0.113.0/24": {HOLDER}}

    without = find_candidates(current, baseline)
    assert len(without) == 1
    assert without[0].candidate_type is CandidateType.ORIGIN_CHANGE

    assert find_candidates(current, baseline, siblings=siblings()) == []


def test_a_more_specific_from_a_stranger_is_flagged() -> None:
    """A longer prefix carved out of somebody else's block, announced by another network."""
    current = {"203.0.113.128/25": {STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    found = find_candidates(current, baseline)
    assert len(found) == 1
    assert found[0].candidate_type is CandidateType.MORE_SPECIFIC
    assert found[0].covering_prefix == "203.0.113.0/24"


def test_a_more_specific_from_the_holder_is_not_flagged() -> None:
    """Announcing a longer piece of your own block is ordinary traffic engineering."""
    current = {"203.0.113.128/25": {HOLDER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline) == []


def test_a_more_specific_from_a_sibling_is_not_flagged() -> None:
    current = {"203.0.113.128/25": {SIBLING}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline, siblings=siblings()) == []


def test_the_most_specific_covering_prefix_is_used() -> None:
    current = {"203.0.113.128/25": {STRANGER}}
    baseline = {"203.0.0.0/16": {64498}, "203.0.113.0/24": {HOLDER}}
    found = find_candidates(current, baseline)
    assert found[0].covering_prefix == "203.0.113.0/24"
    assert found[0].baseline_origins == (HOLDER,)


def test_two_origins_at_once_are_flagged() -> None:
    """Multiple origins for one prefix. Often legitimate, which is why it is a candidate."""
    current = {"203.0.113.0/24": {HOLDER, STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    found = find_candidates(current, baseline)
    kinds = {c.candidate_type for c in found}
    assert CandidateType.MULTIPLE_ORIGINS in kinds
    moas = [c for c in found if c.candidate_type is CandidateType.MULTIPLE_ORIGINS]
    assert {c.origin_asn for c in moas} == {HOLDER, STRANGER}


def test_siblings_announcing_together_are_not_a_moas_candidate() -> None:
    """Anycast or a shared block run by one organisation is not worth reporting."""
    current = {"203.0.113.0/24": {HOLDER, SIBLING}}
    baseline = {"203.0.113.0/24": {HOLDER, SIBLING}}
    assert find_candidates(current, baseline, siblings=siblings()) == []


def test_a_brand_new_prefix_is_not_a_candidate() -> None:
    """Nothing to compare it with, so no claim can be made. New is not hijacked."""
    current = {"198.51.100.0/24": {STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline) == []


def test_ipv6() -> None:
    current = {"2001:db8:1::/48": {STRANGER}}
    baseline = {"2001:db8::/32": {HOLDER}}
    found = find_candidates(current, baseline)
    assert len(found) == 1
    assert found[0].candidate_type is CandidateType.MORE_SPECIFIC


def test_address_families_do_not_mix() -> None:
    current = {"2001:db8:1::/48": {STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline) == []


def test_the_origin_validation_state_is_carried_through() -> None:
    """Plan Section 10.5 asks for each candidate to be tagged with its ROV state, because a
    candidate that is also RPKI-Invalid is far more interesting."""
    current = {"203.0.113.0/24": {STRANGER}}
    baseline = {"203.0.113.0/24": {HOLDER}}
    found = find_candidates(current, baseline, rov_states={("203.0.113.0/24", STRANGER): "invalid"})
    assert found[0].rov_state == "invalid"


def test_malformed_prefixes_are_skipped_not_fatal() -> None:
    current = {"not-a-prefix": {STRANGER}}
    baseline = {"also-not": {HOLDER}, "203.0.113.0/24": {HOLDER}}
    assert find_candidates(current, baseline) == []
