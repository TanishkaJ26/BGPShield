# Methodology

This file grows into the paper's method section. Every number reported in the paper must be
reproducible from a CLI command recorded next to it here (plan Section 13).

## Phase 0 (2026-09-17): ground truth for the data sources

- Data source verification: see `docs/data-sources.md`.
- Earliest ASPA record in the RIPE NCC RPKI archive: **2023-10-11** (RIPE TA, 1 record,
  customer AS15562). Per TA: ARIN 2023-11-01, APNIC 2023-12-01, LACNIC 2024-03-01, AFRINIC none
  through 2026-09-01. Command: `uv run python scripts/phase0_ripe_archive_sweep.py` →
  `data/interim/phase0/ripe_archive_aspa_counts.csv` (monthly, first of month).
- ASPA records on 2026-09-01 in that archive: 2,822 total (RIPE NCC 1,872, ARIN 597,
  APNIC 221, LACNIC 132, AFRINIC 0).
- Three-way cross-check of ASPA counts on 2026-09-16, per trust anchor:

  | TA | RIPE NCC archive (Routinator, 04:35Z) | rpkiviews (rpki-client, 00:06Z) | Hurricane Electric report (13:16 PDT) |
  | --- | --- | --- | --- |
  | RIPE NCC | 1,979 | 1,980 | 1,987 |
  | ARIN | (2026-09-01: 597) | 630 | 632 |
  | APNIC | (2026-09-01: 221) | 338 | 354 |
  | LACNIC | (2026-09-01: 132) | 140 | 138 |
  | AFRINIC | 0 | 0 | not listed |

  The RIPE-TA numbers agree within 0.5 %. The other TAs were only sampled on 2026-09-01 in the
  archive sweep, so the Phase 1 acceptance test must compare same-day values. Tolerance is set
  to ±5 % per TA until the sources of difference (snapshot time, validator, objects one
  validator rejects, e.g. 2 APNIC ASPAs "failed parse" in rpki-client) are understood.
  Commands: `uv run python scripts/phase0_ripe_archive_sweep.py`; rpkiviews numbers from
  `data/raw/samples/rpkiviews/rpki-20260916T000605Z/output/rpki-client.metrics`.

## Phase 1 (2026-09-18): RPKI ingestion and the adoption baseline

### How a number gets made

One command ingests the published RPKI records for a day into two Parquet tables, and a
second reads those tables and reports. Nothing in the analysis touches the network.

```bash
uv run hijax ingest-rpki --date 2026-09-16
uv run hijax adoption --export web/public/data/aspa_adoption.json
```

Source: the RIPE NCC RPKI archive, one Routinator JSON file per trust anchor per day
(`docs/data-sources.md` section 3). Downloads are cached under `data/raw/`, carry a contact
address in the User-Agent, and retry a dropped transfer without ever caching a partial file.

### Acceptance check: does our ASPA count match a public reference?

Plan Section 11 asks for agreement with a public reference within a stated tolerance. The
tolerance was set at ±5 % per trust anchor in Phase 0. Snapshot date 2026-09-16:

| Trust anchor | Hijax | rpki-client on rpkiviews, same day | Hurricane Electric report | Hijax vs HE |
| --- | --- | --- | --- | --- |
| ripe | 1,979 | 1,980 | 1,987 | −0.4 % |
| arin | 630 | 630 | 632 | −0.3 % |
| apnic | 338 | 338 | 354 | −4.5 % |
| lacnic | 141 | 140 | 138 | +2.2 % |
| afrinic | 0 | 0 | not listed | — |
| **total** | **3,088** | **3,088** | **3,111** | **−0.7 %** |

Every trust anchor is inside the tolerance, and the total agrees exactly with a second,
independent validator. The APNIC gap is the largest; two APNIC ASPA objects failed to parse
in the rpkiviews run of the same day, which is the most likely explanation and is worth
re-checking in Phase 4.

Hurricane Electric figures: <https://bgp.he.net/report/rpki_and_aspa>, "Updated 16 Sep 2026
13:16 PDT". rpki-client figures from the per-trust-anchor metrics in the rpkiviews snapshot,
`rpki-20260916T000605Z/output/rpki-client.metrics`.

### Volume for one day, 2026-09-16

| Quantity | Value |
| --- | --- |
| VRPs after deduplication | 1,005,186 |
| ASPA records | 3,088 |
| IPv4 VRPs | 771,842 |
| IPv6 VRPs | 233,344 |
| Providers listed per publisher, median | 2 |
| Providers listed per publisher, maximum | 226 |

### Finding: two published ASPA records contradict themselves

`draft-ietf-sidrops-aspa-profile-29` Section 3 says a provider AS of 0 "can only be encoded
in the providers field as a single item list", because an AS0 ASPA is the statement "I have
no transit providers at all". Section 5.2 adds that if a merged provider set holds two or
more values and one is AS 0, "then AS 0 must be removed".

On 2026-09-16, 63 records are genuine AS0 ASPAs, and **two list AS 0 alongside real
providers**: AS58899 with `[0, 9885]` and AS59182 with `[0, 9885, 55824]`. Both are under
APNIC and both are registered in India. The ingester applies the Section 5.2 rule and counts
how often it fires, so the count is available as a data-quality signal for RQ2.

```bash
uv run hijax ingest-rpki --date 2026-09-16 --force   # prints as0dropped=2
```

### Regional snapshot for RQ4, 2026-09-16

| Group | ASPA publishers |
| --- | --- |
| Registered in India | 72 |
| APNIC region | 338 |
| Worldwide | 3,088 |

Country here is the country of *registration* taken from the RIR delegated-stats files, not
where the network operates (plan Sections 8 and 15). Phase 1 uses each registry's current
file rather than the file from the snapshot date, a second approximation recorded as D-013.
Every one of the 3,088 publishers matched a registry entry, so no publisher is unattributed.

The top countries by publisher count on that date are the United States (593), Germany (302),
the United Kingdom (190), France (149) and Brazil (146).

### The weekly backfill

Weekly snapshots from the first ASPA record ever published to the present:

```bash
uv run hijax ingest-rpki --from 2023-10-11 --to 2026-09-18 --every 7d
```

| Quantity | Value |
| --- | --- |
| Weekly snapshot dates ingested | 154 |
| Date range | 2023-10-11 to 2026-09-16 |
| Trust-anchor files missing from the archive | 0 |
| Dates needing a retry | 2 |
| Stored Parquet | 404 MB |
| Cached raw downloads | 1.4 GB |
| Exported dashboard JSON | 83 KB |

Both retries were local DNS failures on this laptop, not archive problems, and both
succeeded on a second run. No trust anchor was missing on any of the 154 dates, so the
series has no gaps.

ASPA growth over the whole period, worldwide:

| Date | ASPA records |
| --- | --- |
| 2023-10-11 | 1 |
| 2024-09-25 | 86 |
| 2025-12-10 | 351 |
| 2026-02-04 | 911 |
| 2026-09-16 | 3,088 |

### What is not yet satisfied

Plan Section 11 also requires that "the daily job has run 7 days in a row". The workflow is
committed, registered on GitHub and schedules itself for 06:20 UTC daily, but seven
consecutive runs take seven days. That criterion is pending, not met, and nothing should be
reported as though it were.

## Phase 2 (2026-09-18): BGP ingestion and path normalization

### Commands

```bash
uv run hijax ingest-bgp --date 2026-09-01 --jobs 3
uv run hijax ingest-meta --month 2026-08
```

The relationship month is deliberately the month *before* the snapshot, because plan
Section 10.4 requires relationships that were not inferred from the very event being studied.

### Acceptance measurement, one day across all six collectors

Measured with `scripts/phase2_measure_ingest.ps1`, which samples memory across the whole
process tree because collectors run in separate processes.

| Measure | Result | Criterion |
| --- | --- | --- |
| Wall clock | **60.2 minutes** | under 1 hour |
| Peak memory | **1.10 GB** | under 8 GB |
| Routes stored | 99,447,753 | — |
| Parquet written | 748 MB | — |

Memory passes with roughly seven times the headroom. **Time misses the bar, by twelve
seconds.** That is reported as a miss rather than rounded down.

The binding constraint is this laptop's link to the archives, not the code. Downloading one
43 MB dump measured 227 KB/s, and parsing the same dump from local disk runs at 38,263 routes
per second, so the 99.4 million routes here represent about 43 minutes of pure parsing spread
across three processes, against roughly 800 MB of transfer. Two levers would bring it under
the hour without touching correctness: raise `--jobs` from 3 to 6 so every collector
downloads at once, or run it on a faster connection. Neither has been measured yet, so
neither is claimed.

### Routes per collector, and what each normalization rule flagged

Snapshot 2026-09-01, dump nearest 00:00 UTC.

| Collector | Routes | Peers | Prefixes | Loop | Private AS | Reserved AS | Peer mismatch | AS_SET |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rrc00 | 38,765,726 | 63 | 956,502 | 0.04% | 0.01% | 0.00% | 0.09% | 0.02% |
| route-views.sg | 20,932,054 | 58 | 1,006,727 | 0.04% | 0.00% | 0.00% | 1.49% | 0.02% |
| route-views.sydney | 13,767,262 | 52 | 1,358,794 | 0.04% | 0.00% | 0.00% | 2.82% | 0.01% |
| route-views2 | 11,193,285 | 21 | 662,530 | 0.04% | 0.00% | — | — | 0.02% |
| rrc23 | 8,037,503 | 32 | 980,901 | 0.04% | 0.00% | 0.00% | — | 0.01% |
| rrc06 | 6,751,923 | 21 | 1,355,629 | 0.03% | 0.00% | 0.00% | 2.16% | 0.02% |

Reading these:

- **Loops, private and reserved AS numbers are rare**, together well under one route in a
  thousand. Routes carrying them are flagged and excluded from relationship analysis but
  still counted, so nothing disappears silently.
- **AS_SET is rare and always terminal.** In rrc00, 6,166 routes contain an AS_SET and the
  same 6,166 have no origin, meaning every set sat at the end of the path. Those routes
  keep a null origin rather than a guessed one (D-018).
- **Peer mismatch varies by collector and is a route-server signal, not corruption.** It is
  near zero at rrc00, a multihop collector, and highest at the IXP collectors. At the Jakarta
  IXP collector used for the earlier probe, two peers account for every mismatch and every
  other peer matches on every route, which is how a transparent route server behaves
  (RFC 7947 Section 2.2.2). See D-019.

### Direction check on real data

The stored `as_path` is origin first. Spot-checking rrc00: a route with raw path
`44393 64073 174` is stored as `[174, 64073, 44393]` with `peer_asn` 44393, so the last
element is the collector's peer and the first is the origin, as plan Section 10.1 requires.

### Relationship and metadata tables, month 2026-08

```bash
uv run hijax ingest-meta --month 2026-08
```

| Table | Rows |
| --- | --- |
| Relationships (`as_rel`) | 677,904 |
| Organisations | 121,988 |
| Ranked networks (`as_rank`) | 121,200 |
| Combined `as_meta` | 124,732 |

`as_meta` holds more rows than any single source, because an AS number known to only one of
the three keeps its row with nulls elsewhere rather than being dropped. Country and registry
cover 122,469 of them, organisation 121,988, and cone and rank 121,200.

Two sanity checks, neither of which the code could pass by accident:

- The relationship counts match the raw CAIDA file measured independently in Phase 0:
  166,426 provider-to-customer and 511,478 peer links.
- The networks with no providers and thousands of customers are the ones that should be.
  Level 3 has 0 providers, 74 peers and 6,489 customers; Cogent has 0, 83 and 6,514. The
  five largest customer cones are Level 3, Telia, GTT, Cogent and NTT, in that order.

### Largest Indian transit networks by customer cone, for RQ4

| AS | Customer cone | Global rank |
| --- | --- | --- |
| 9498 | 3,965 | 20 |
| 4755 | 2,477 | 35 |
| 9583 | 592 | 97 |
| 55836 | 445 | 130 |
| 55410 | 383 | 146 |

Cross-referencing these against the ASPA publishers from Phase 1 is RQ4's central question,
and is now possible from stored tables alone.

## Phase 3 (2026-09-18): the validators

### Commands

```bash
uv run hijax validate --date 2026-09-01 --collectors rrc06
uv run python scripts/phase3_trace_invalid.py --date 2026-09-01 --collector rrc06
```

Relationships default to the month before the snapshot, because plan Section 10.4 wants a
graph that was not inferred from the events being studied.

### Conformance: every worked example from the specification passes

The verification draft does not carry its examples inline. Section 6.1 points to a separate
document maintained by three of its authors: "ASPA-based AS Path Verification Examples",
Sriram, Borchert and Matejka, August 2025, at
<https://github.com/ksriram25/IETF/blob/main/ASPA_path_verification_examples.pdf>.

All 23 examples are implemented as tests: 9 upstream, 10 downstream, and 4 on a topology with
complex relationships. Each test pins the four ramp lengths the document states, not only the
final verdict, so an answer that came out right through two cancelling mistakes still fails.

### Origin validation sanity check

Plan Section 11 (Phase 3) asks for the Invalid share to be compared with public statistics.
Snapshot 2026-09-01, collector rrc06, 996,912 VRPs in force:

| Measure | Per route | Per distinct prefix |
| --- | --- | --- |
| Valid | 71.28% | 71.09% |
| Invalid | 0.05% | 0.16% |
| NotFound | 28.67% | 28.75% |
| RPKI coverage, Valid plus Invalid | 71.33% | 71.25% |

Public reference: the Hurricane Electric report at <https://bgp.he.net/report/rpki_and_aspa>,
updated 17 Sep 2026, states "Global Prefix RPKI Coverage: 68.48%", from 1,112,451 covered of
1,624,413 routed prefixes.

Ours is 71.25% against their 68.48%. Two differences explain the direction without excusing
it. This is one collector in Tokyo with 21 peers, seeing 1,355,629 prefixes against their
1,624,413, and the prefixes a smaller vantage point misses are disproportionately the
long-tail ones least likely to be signed. The dates also differ by sixteen days. Close enough
to say the validator is not systematically wrong, not close enough to claim more.

Invalid at 0.05% of routes sits at the low end of what public monitors usually report. Worth
rechecking against a second collector in Phase 4 before anything is drawn from it.

### ASPA verification on real routes

Same snapshot and collector, with 2,822 ASPA records in force:

| Outcome | Share of routes |
| --- | --- |
| Unknown | 82.70% |
| Valid | 17.04% |
| Invalid | 0.26% |

The Unknown share is the story of ASPA today, and path coverage explains it exactly:

| Where an ASPA publisher sits on the path | Share of routes |
| --- | --- |
| Anywhere on the path | 37.01% |
| At the origin | 3.02% |
| Somewhere in transit | 21.60% |
| At the collector's peer | 19.49% |
| Two publishers adjacent to each other | 1.40% |
| Every hop covered | 18 routes, under 0.001% |

A hop can only be positively confirmed when the network below it has published. Only 1.40% of
routes contain two adjacent publishers, and 18 routes out of 6.75 million have every hop
covered. ASPA can currently contradict a path far more often than it can confirm one, so
Unknown is the honest answer for four routes in five.

Procedure selection: 69.6% of routes were checked with the downstream procedure and 29.9%
with the upstream one. For 0.5% there was no inferred relationship between the collector's
peer and the network before it, so both procedures ran and the stricter answer was kept.

### Tracing three Invalid routes by hand

The acceptance criterion asks that a reviewer be able to trace three randomly sampled
ASPA-Invalid routes. `scripts/phase3_trace_invalid.py` prints, for each sample, the stored
path, what every network on it published, the authorization outcome at each hop, the four
ramp lengths, the procedure chosen and why, and the arithmetic behind the verdict. The sample
is seeded, so the same three routes return on every run.

The three samples were then checked against the CAIDA relationship graph, which knows nothing
about ASPA, using the valley-free rule (Gao-Rexford, plan Section 3):

| Sample | Path | Relationship steps | Independent verdict |
| --- | --- | --- | --- |
| 1 | AS7195 AS174 AS2497 AS25152 | up, down, across | valley, a genuine leak signature |
| 2 | AS174 AS18041 AS59105 | down, across | valley, a genuine leak signature |
| 3 | AS29256 AS29386 AS6866 AS3257 AS2497 | up, up, up, across | valley-free |

Two of the three are corroborated by an independent method. **The third is a likely false
positive, and the trace shows why**: AS29386 published its providers as AS3491, AS6453,
AS6762 and AS8452, while CAIDA infers AS6866 is also its provider. The path is legitimate and
the published record is incomplete. That is exactly the effect RQ2 exists to measure, and
Phase 4 will quantify how much of the 0.26% it accounts for.

### Where the contradictions concentrate

Of 17,865 Invalid routes, 1,030 are Invalid because the path carries an AS_SET, which the
draft rejects outright (Section 5.5 step 3). The rest trace to 240 distinct contradicted
hops, and the largest all place some network above a tier-1 that published an AS0 ASPA:

| Contradicted hop | Routes |
| --- | --- |
| AS174, with AS2497 claimed above it | 5,712 |
| AS1299, with AS2497 claimed above it | 2,676 |
| AS174, with AS18041 claimed above it | 2,076 |
| AS3257, with AS2497 claimed above it | 1,576 |

AS174, AS1299, AS3257 and AS7018 each published an AS0 ASPA, which is correct for a network
that buys transit from nobody, and which makes any path placing someone above them a
contradiction.

### Performance

6,751,923 routes validated in 95.8 seconds on the laptop. Both validators are memoised on
their inputs, which matters because collector tables repeat heavily: those routes reduce to
1,362,911 distinct prefix-and-origin pairs and 787,130 distinct paths.
