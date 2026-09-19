"""RQ4: how India and the APNIC region compare with the world.

## What this answers and what it cannot

The plan asks for India, the APNIC region and the global picture side by side, plus the
standing of the largest Indian transit networks. Everything here is computed from tables
already stored, so it adds no downloads.

**The country attached to an AS number is where it was registered, not where the network
operates.** That is how the registry files work, and plan Sections 8 and 15 both say to state
it plainly rather than let a reader assume otherwise. A network registered in one country can
carry most of its traffic in another, and large operators register numbers in several places.
So "India" here means "registered with a country code of IN", and every figure built from it
inherits that.

A second limit is where the measurement stands. The collectors this project uses are in
Amsterdam, Oregon, Singapore, Tokyo and Sydney, and **none is in India**. The Indian view is
therefore assembled from how Indian networks appear elsewhere, which is not the same as
watching from inside the country.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

#: The APNIC service region, taken from the registry that allocated the AS number rather
#: than from a list of countries, so it needs no geographic judgement of its own.
APNIC_RIR = "apnic"


@dataclass(frozen=True, slots=True)
class RegionSlice:
    """One region's standing on a single snapshot date."""

    name: str
    networks: int
    """AS numbers registered in this region that the topology data knows about."""
    aspa_publishers: int
    routed_networks: int
    """AS numbers seen originating at least one route at the collectors."""
    publishers_that_route: int
    """Publishers that were also seen originating a route, which is the population the
    adoption share should really be measured against."""

    @property
    def share_of_routed(self) -> float:
        return self.publishers_that_route / self.routed_networks if self.routed_networks else 0.0


def slice_region(
    name: str,
    as_meta: pl.DataFrame,
    publishers: set[int],
    routed: set[int],
    *,
    country: str | None = None,
    rir: str | None = None,
) -> RegionSlice:
    """Count networks, publishers and routed networks for one region.

    ``country`` selects by registration country and ``rir`` by allocating registry. Passing
    neither gives the global slice.
    """
    frame = as_meta
    if country is not None:
        frame = frame.filter(pl.col("country") == country)
    if rir is not None:
        frame = frame.filter(pl.col("rir") == rir)

    members = {int(a) for a in frame["asn"]}
    member_publishers = members & publishers
    member_routed = members & routed
    return RegionSlice(
        name=name,
        networks=len(members),
        aspa_publishers=len(member_publishers),
        routed_networks=len(member_routed),
        publishers_that_route=len(member_publishers & member_routed),
    )


def compare_regions(
    as_meta: pl.DataFrame, publishers: set[int], routed: set[int], *, country: str = "IN"
) -> pl.DataFrame:
    """India, the APNIC region and the world, side by side (plan Section 11, Phase 6)."""
    slices = [
        slice_region("global", as_meta, publishers, routed),
        slice_region("apnic region", as_meta, publishers, routed, rir=APNIC_RIR),
        slice_region(f"registered {country}", as_meta, publishers, routed, country=country),
    ]
    return pl.DataFrame(
        {
            "region": [s.name for s in slices],
            "networks": [s.networks for s in slices],
            "routed_networks": [s.routed_networks for s in slices],
            "aspa_publishers": [s.aspa_publishers for s in slices],
            "publishers_that_route": [s.publishers_that_route for s in slices],
            "share_of_routed": [s.share_of_routed for s in slices],
        }
    )


def largest_transit(
    as_meta: pl.DataFrame,
    publishers: set[int],
    rov_by_origin: dict[int, str] | None = None,
    *,
    country: str = "IN",
    top: int = 15,
) -> pl.DataFrame:
    """The largest networks in one country by customer cone, and where each one stands.

    Plan Section 11 asks specifically for the largest Indian transit networks and their ASPA
    and origin-validation status, because those are the networks whose adoption would matter
    most to everyone behind them.
    """
    ranked = (
        as_meta.filter(
            (pl.col("country") == country)
            & pl.col("cone_size").is_not_null()
            & (pl.col("cone_size") > 0)
        )
        .sort("cone_size", descending=True)
        .head(top)
        .select(["asn", "cone_size", "rank"])
    )
    states = rov_by_origin or {}
    return ranked.with_columns(
        pl.col("asn").is_in(list(publishers)).alias("publishes_aspa"),
        pl.col("asn")
        .replace_strict(states, default="not seen", return_dtype=pl.Utf8)
        .alias("rov_state_of_its_routes"),
    )


def summary(comparison: pl.DataFrame) -> dict[str, Any]:
    """Headline numbers for the regional section of the paper."""
    rows = {row["region"]: row for row in comparison.iter_rows(named=True)}
    out: dict[str, Any] = {}
    for name, row in rows.items():
        out[name] = {
            "routed_networks": row["routed_networks"],
            "publishers_that_route": row["publishers_that_route"],
            "share_of_routed": row["share_of_routed"],
        }
    world = rows.get("global")
    if world and world["share_of_routed"]:
        for name, row in rows.items():
            if name == "global":
                continue
            out[name]["relative_to_global"] = row["share_of_routed"] / world["share_of_routed"]
    return out
