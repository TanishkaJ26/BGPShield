"""Normalized RPKI records and the helpers that build them (plan Section 9).

Plain English, for the two record types here:

*VRP, a Validated ROA Payload.* A ROA is a signed statement by an address holder saying
"AS number X is allowed to originate this block of addresses, and more specific pieces of
it down to length L". A validator checks the signatures and flattens every ROA into simple
triples called VRPs. Route Origin Validation (RFC 6811) compares a route against them.

*ASPA, an Autonomous System Provider Authorization.* A signed statement by one network
saying "these are my upstream providers". Checking a route's path against these records is
what lets a receiver spot a route leak
(``draft-ietf-sidrops-aspa-verification-28`` Section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# AS numbers are 32-bit (RFC 6793). AS 0 is reserved and must never appear as a route
# origin (RFC 7607), but it is legal inside a ROA ("AS0 ROA", meaning "this space must not
# be routed") and inside an ASPA provider list, where it states "I have no providers".
ASN_MAX = 4_294_967_295


class RecordFormatError(ValueError):
    """A validator's JSON did not look the way Phase 0 verified it looks."""


@dataclass(frozen=True, slots=True)
class Vrp:
    """One Validated ROA Payload. Columns follow plan Section 9."""

    prefix: str
    afi: int
    max_length: int
    asn: int
    ta: str


@dataclass(frozen=True, slots=True)
class Aspa:
    """One Validated ASPA Payload.

    ``provider_asns`` is sorted and deduplicated. A single entry of ``0`` is how a
    customer states that it has no providers at all; the ASPA profile
    (``draft-ietf-sidrops-aspa-profile-29`` Section 3) allows ``PAS`` to be 0.
    """

    customer_asn: int
    provider_asns: tuple[int, ...]
    ta: str | None
    expires: datetime | None


def parse_asn(value: str | int) -> int:
    """Turn ``"AS553"`` or ``553`` into ``553``.

    Routinator writes AS numbers as strings with an ``AS`` prefix; rpki-client writes
    plain integers. Both were confirmed against real files in Phase 0.
    """
    if isinstance(value, int):
        asn = value
    else:
        text = value.strip()
        if text.upper().startswith("AS"):
            text = text[2:]
        try:
            asn = int(text)
        except ValueError as exc:
            raise RecordFormatError(f"not an AS number: {value!r}") from exc
    if not 0 <= asn <= ASN_MAX:
        raise RecordFormatError(f"AS number out of 32-bit range: {asn}")
    return asn


def afi_of_prefix(prefix: str) -> int:
    """Return 4 for an IPv4 prefix and 6 for an IPv6 one.

    "AFI" is the Address Family Identifier from BGP (RFC 4271): 1 means IPv4 and 2 means
    IPv6. This project stores the friendlier 4 and 6, as the plan's Section 9 table does.
    A colon can only appear in an IPv6 address, so that is the whole test.
    """
    if ":" in prefix:
        return 6
    if "." in prefix:
        return 4
    raise RecordFormatError(f"not an IP prefix: {prefix!r}")


def normalize_providers(values: list[str | int]) -> tuple[int, ...]:
    """Sort and deduplicate a provider list, applying the AS 0 rule.

    ``draft-ietf-sidrops-aspa-profile-29`` Section 3 says a provider AS of 0 "can only be
    encoded in the providers field as a single item list", and Section 5.2 says that when
    several of a customer's ASPAs are merged, "if the U-SPAS contains two or more values,
    and one of those values is AS 0, then AS 0 must be removed". So AS 0 survives only when
    it is the whole list, which is the statement "I have no transit providers at all"
    (``draft-ietf-sidrops-aspa-verification-28`` Section 3, the "AS0 ASPA").
    """
    return apply_as0_rule({parse_asn(v) for v in values})


def apply_as0_rule(providers: set[int]) -> tuple[int, ...]:
    """Sort a provider set and drop AS 0 unless it is the only member.

    Kept separate from ``normalize_providers`` because the same rule has to be applied
    again after two of a customer's ASPAs are unioned together (profile Section 5.2).
    """
    if len(providers) > 1:
        providers = providers - {0}
    return tuple(sorted(providers))


def epoch_to_utc(value: int | float | None) -> datetime | None:
    """Convert POSIX seconds to an aware UTC datetime. rpki-client supplies these."""
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)
