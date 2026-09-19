"""Unit tests for the record helpers (plan Section 12).

Every example here is hand-built. None of it came from a downloaded file.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bgpshield.models import (
    RecordFormatError,
    afi_of_prefix,
    epoch_to_utc,
    normalize_providers,
    parse_asn,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AS553", 553),
        ("as553", 553),
        ("553", 553),
        (553, 553),
        ("AS0", 0),  # legal in an AS0 ROA (RFC 7607) and in an ASPA provider list
        ("AS4294967295", 4_294_967_295),  # last 32-bit ASN (RFC 7300 reserves it)
        ("AS65536", 65_536),  # a 4-byte ASN, the common case since RFC 6793
    ],
)
def test_parse_asn_accepts_both_validator_spellings(value: str | int, expected: int) -> None:
    assert parse_asn(value) == expected


@pytest.mark.parametrize("value", ["", "AS", "ASfoo", "-1", "AS4294967296", -5])
def test_parse_asn_rejects_nonsense(value: str | int) -> None:
    with pytest.raises(RecordFormatError):
        parse_asn(value)


@pytest.mark.parametrize(
    ("prefix", "afi"),
    [
        ("203.0.113.0/24", 4),
        ("0.0.0.0/0", 4),
        ("2001:db8::/32", 6),
        ("::/0", 6),
    ],
)
def test_afi_of_prefix(prefix: str, afi: int) -> None:
    assert afi_of_prefix(prefix) == afi


def test_afi_of_prefix_rejects_non_prefix() -> None:
    with pytest.raises(RecordFormatError):
        afi_of_prefix("not-a-prefix")


def test_normalize_providers_sorts_and_deduplicates() -> None:
    assert normalize_providers(["AS3356", "AS174", "AS3356", 6939]) == (174, 3356, 6939)


def test_normalize_providers_keeps_as0() -> None:
    """A lone AS 0 means "I have no providers" and must survive normalization."""
    assert normalize_providers([0]) == (0,)


def test_normalize_providers_on_empty_list() -> None:
    assert normalize_providers([]) == ()


def test_epoch_to_utc() -> None:
    assert epoch_to_utc(1789657200) == datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
    assert epoch_to_utc(None) is None


def test_as0_is_dropped_when_real_providers_are_also_listed() -> None:
    """draft-ietf-sidrops-aspa-profile-29 Section 3: a provider AS of 0 "can only be
    encoded in the providers field as a single item list", and Section 5.2: if a merged
    provider set "contains two or more values, and one of those values is AS 0, then AS 0
    must be removed". Two real records in the 2026-09-16 snapshot break this rule."""
    assert normalize_providers([0, 9885]) == (9885,)
    assert normalize_providers(["AS0", "AS9885", "AS55824"]) == (9885, 55824)


def test_as0_survives_when_it_is_the_whole_list() -> None:
    """An AS0 ASPA states "I have no transit providers"
    (draft-ietf-sidrops-aspa-verification-28 Section 3), so it must not be stripped."""
    assert normalize_providers([0]) == (0,)
    assert normalize_providers(["AS0", "AS0"]) == (0,)


def test_apply_as0_rule_directly() -> None:
    from bgpshield.models import apply_as0_rule

    assert apply_as0_rule({0}) == (0,)
    assert apply_as0_rule({0, 1}) == (1,)
    assert apply_as0_rule(set()) == ()
