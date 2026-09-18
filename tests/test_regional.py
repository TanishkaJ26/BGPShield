"""RQ4 regional comparison tests (plan Sections 11 Phase 6, and 12).

Hand-built. AS numbers come from the documentation range (RFC 5398).
"""

from __future__ import annotations

import polars as pl
import pytest

from hijax.analysis.regional import compare_regions, largest_transit, slice_region, summary

#: Four networks in India, two elsewhere in the APNIC region, two outside it.
AS_META = pl.DataFrame(
    {
        "asn": [64496, 64497, 64498, 64499, 64500, 64501, 64510, 64511],
        "country": ["IN", "IN", "IN", "IN", "SG", "JP", "US", "DE"],
        "rir": ["apnic"] * 6 + ["arin", "ripencc"],
        "cone_size": [500, 120, 30, None, 900, 40, 5000, 70],
        "rank": [10, 40, 90, None, 5, 80, 1, 60],
    }
)

PUBLISHERS = {64496, 64498, 64500, 64510}
ROUTED = {64496, 64497, 64498, 64500, 64501, 64510, 64511}


def test_a_region_slice_counts_the_right_networks() -> None:
    india = slice_region("india", AS_META, PUBLISHERS, ROUTED, country="IN")
    assert india.networks == 4
    assert india.aspa_publishers == 2  # 64496 and 64498
    assert india.routed_networks == 3  # 64499 is not routed
    assert india.publishers_that_route == 2


def test_the_share_is_measured_against_routed_networks() -> None:
    """A network that announces nothing cannot meaningfully publish an ASPA record, so the
    denominator is networks actually seen originating routes."""
    india = slice_region("india", AS_META, PUBLISHERS, ROUTED, country="IN")
    assert india.share_of_routed == pytest.approx(2 / 3)


def test_the_apnic_region_is_selected_by_registry_not_geography() -> None:
    """Using the allocating registry avoids having to judge which countries count as being
    in the region."""
    apnic = slice_region("apnic", AS_META, PUBLISHERS, ROUTED, rir="apnic")
    assert apnic.networks == 6
    assert apnic.aspa_publishers == 3  # 64496, 64498, 64500


def test_the_global_slice_takes_everything() -> None:
    world = slice_region("global", AS_META, PUBLISHERS, ROUTED)
    assert world.networks == 8
    assert world.aspa_publishers == 4


def test_compare_regions_puts_the_three_side_by_side() -> None:
    frame = compare_regions(AS_META, PUBLISHERS, ROUTED)
    assert frame["region"].to_list() == ["global", "apnic region", "registered IN"]
    world = frame.row(0, named=True)
    assert world["routed_networks"] == 7
    assert world["publishers_that_route"] == 4


def test_summary_expresses_each_region_against_the_world() -> None:
    result = summary(compare_regions(AS_META, PUBLISHERS, ROUTED))
    assert "relative_to_global" in result["registered IN"]
    assert "relative_to_global" not in result["global"]
    # India: 2 of 3 routed publish. Global: 4 of 7. So India is ahead here.
    assert result["registered IN"]["relative_to_global"] > 1


def test_largest_transit_ranks_by_cone_and_shows_status() -> None:
    frame = largest_transit(
        AS_META, PUBLISHERS, {64496: "valid", 64497: "not_found"}, country="IN", top=5
    )
    assert frame["asn"].to_list() == [64496, 64497, 64498]  # 64499 has no cone
    assert frame["publishes_aspa"].to_list() == [True, False, True]
    assert frame["rov_state_of_its_routes"].to_list() == ["valid", "not_found", "not seen"]


def test_a_network_with_no_cone_is_excluded_from_the_ranking() -> None:
    """No cone means the topology data cannot size it, so it cannot be ranked by size."""
    frame = largest_transit(AS_META, PUBLISHERS, country="IN", top=10)
    assert 64499 not in frame["asn"].to_list()


def test_a_country_with_nothing_in_it() -> None:
    empty = slice_region("nowhere", AS_META, PUBLISHERS, ROUTED, country="ZZ")
    assert empty.networks == 0
    assert empty.share_of_routed == 0.0
