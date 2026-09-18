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

## Phase 4 (2026-09-18): RQ2, are published ASPA records complete?

### Command

```bash
uv run hijax correctness --date 2026-09-01 --collectors rrc06
```

### Why this matters

An ASPA record only helps if it lists every one of a network's providers. Miss one, and every
legitimate route arriving through that provider looks like a forgery. A network filtering on
ASPA would discard it. So an incomplete record is not a harmless gap in coverage, it is a
self-inflicted outage waiting for somebody to switch on enforcement.

### The caveat attached to every number below

CAIDA's relationships are *inferred* from public routing data, not declared, and carry errors
of their own (plan Section 15). A disagreement between a published record and an inference
means one of the two is wrong, not that the record is. That is why the table below counts
disagreements in both directions and why the largest cases were reviewed by hand.

### Completeness of published records, 2026-09-01

| | Publishers | Share |
| --- | --- | --- |
| Total publishing an ASPA record | 2,822 | |
| Agree with the inferred topology exactly | 1,020 | 36.1% |
| **Miss at least one inferred provider** | **369** | **13.1%** |
| List a provider the inference has not seen | 1,680 | 59.5% |
| No providers inferred, so unjudgeable | 624 | 22.1% |

Of the 60 records that declare "I have no providers at all", 58 are corroborated by the
inference seeing none either, and 2 are contradicted.

The 59.5% listing something the inference misses is not the alarming number it looks like.
CAIDA only sees a link if it appears in public routing data, so a provider used for backup or
for a small part of a network's traffic is routinely invisible to it. The direction that
causes harm is the other one, and that is 13.1%.

### How many Invalid routes are actually false positives

Two independent methods, which is the point.

**Method one, by path shape.** Take every ASPA-Invalid route and ask the valley-free rule,
which knows nothing about ASPA, whether the path is mis-shaped at all. Collector rrc06,
17,865 Invalid routes:

| Classification | Routes | Share |
| --- | --- | --- |
| Mis-shaped path, ASPA corroborated | 13,562 | 75.9% |
| **Well-shaped path, likely false positive** | **2,924** | **16.4%** |
| Shape undetermined, a relationship is missing | 349 | 2.0% |
| Invalid only because the path carries an AS_SET | 1,030 | 5.8% |

Among the routes the shape test can actually judge, **17.7% look legitimate**.

**Method two, by record quality.** Take the 16,835 Invalid routes that name a contradicted
hop and ask whether the contradicting network's own record looks incomplete:

| The contradicting record | Routes | Share |
| --- | --- | --- |
| A correct "I have no providers" record, corroborated | 12,832 | 76.2% |
| **Misses at least one inferred provider** | **3,387** | **20.1%** |
| Agrees with the inference | 511 | 3.0% |
| Unjudgeable | 105 | 0.6% |

The two methods are built on different evidence and land on 17.7% and 20.1%. Treat the
false-positive risk at this vantage point as roughly one Invalid route in five, and note that
both estimates lean on the same inferred topology, so they are not fully independent.

### Manual review of the networks behind the most Invalid routes

Plan Section 11 asks for the top 20 to be reviewed by hand, reading PeeringDB and registry
data only. Names and network types below come from the PeeringDB API, read-only. Three
distinct patterns emerged, and they call for completely different conclusions.

**Pattern 1: correct records, suspicious paths.** This is the largest group by far, 76.2% of
contradicted routes.

| AS | Name | Type | Published | Inferred providers | Invalid routes |
| --- | --- | --- | --- | --- | --- |
| 174 | Cogent Communications | NSP, global | AS0 | 0 | 7,845 |
| 1299 | Arelion (Twelve99) | NSP, global | AS0 | 0 | 2,684 |
| 3257 | GTT Communications | NSP, global | AS0 | 0 | 1,684 |
| 7018 | AT&T | NSP, North America | AS0 | 0 | 280 |
| 3320 | Deutsche Telekom | NSP, global | AS0 | 0 | 259 |

Every one is a global transit network that buys transit from nobody, and CAIDA agrees: Cogent
has 6,514 customers, 83 peers and zero providers. Their records are correct. The paths are
what is odd, each claiming some network sits above one of them. The networks so claimed are
their peers, such as AS2497, AS2914 and AS3356, so these paths cross between peers somewhere
they should not. **These Invalid verdicts are evidence about routing, not about record
quality**, and they belong to RQ3 rather than RQ2.

**Pattern 2: genuinely incomplete records.** Smaller in count, and the real RQ2 finding.

| AS | Name | Published | CAIDA infers | Missing | Invalid routes |
| --- | --- | --- | --- | --- | --- |
| 20764 | RASCOM | 1 provider | 5 | 6939, 12389, 20485, 49558 | 919 |
| 29386 | Syrian Telecom | 4 providers | 7 | 6774, 6866, 8697, 9121 | 773 |

RASCOM is a transit network with 257 customers and 1,945 peers that published exactly one of
its five apparent upstreams. AS29386 is the case Phase 3 found by sampling three Invalid
routes at random: its path was perfectly well shaped and it was flagged anyway.

**Pattern 3: the inference is the likelier suspect.** Worth separating so the table is not
read as a list of operator errors.

AS61625 published 11 providers while CAIDA infers 10, of which 8 are not among the 11. The
missing ones sit in the Brazilian 26xxxx range and this is a Brazilian cable and DSL provider,
so a plausible reading is that CAIDA has misclassified some customer links. AS14789 published
220 providers against 208 inferred, missing 5, which is a very well maintained record for a
network of that shape rather than a negligent one.

### What this means for the paper

The headline for RQ2 is that 13.1% of publishers appear to have an incomplete record, and
that roughly one Invalid route in five at this vantage point is a likely false positive
caused by such a record rather than by anything wrong with the routing. Both numbers rest on
inferred relationships and should be repeated across more collectors and dates in Phase 6
before they go in a paper.

The manual review also produced a finding that was not anticipated: the large majority of
Invalid routes are contradicted by *correct* records at tier-1 networks, not by bad ones.
Reporting the Invalid share on its own would badly misattribute the cause.

## Phase 5 (2026-09-18): leak detection and the counterfactual, RQ3

### Commands

```bash
uv run hijax detect --date 2026-09-01 --collectors rrc06
uv run hijax counterfactual --date 2026-09-01 --limit 3000
uv run python scripts/phase5_precision_sample.py --date 2026-09-01 --samples 50
```

### What the detector found

Collector rrc06, snapshot 2026-09-01, relationships from 2026-08:

| | Count |
| --- | --- |
| Routes examined | 6,751,923 |
| Leak sightings | 439,571 |
| Distinct candidates | 305,856 |
| Corroborated by two or more vantage points | 62,508 (20.4%) |

By RFC 7908 type:

| Type | Candidates |
| --- | --- |
| Type 3, provider to peer | 171,679 |
| Type 2, lateral peer to peer | 109,021 |
| Type 4, peer to provider | 13,824 |
| Type 1, hairpin through two providers | 11,332 |

**305,856 candidates from 6.75 million routes, 4.5% of the table, is not credible as a count
of real route leaks.** Published measurement work puts genuine leaks orders of magnitude
lower. Something in the detector or its inputs is producing false positives at scale, which
is exactly what the precision sample is for.

### Precision on a random sample of 50

Plan Section 11 requires precision to be measured on a manually labelled random sample of 50
detected leaks. The sample was drawn from the 62,508 corroborated candidates with a fixed
seed, and `scripts/phase5_precision_sample.py` printed the full evidence for each: the path,
the relationship at every step, the leaker's size and country, and how many vantage points
saw it.

One pattern dominates the sample:

| Leaker | Count in sample | All of type |
| --- | --- | --- |
| Large transit network, customer cone 1,000 or more | 27 (54%) | lateral, peer to peer |
| Small or mid-size network, cone under 1,000 | 23 (46%) | all four types |

**26 of the 50 name AS6939, Hurricane Electric, as the leaker, always as a peer-to-peer
leak.** Hurricane Electric is both an unusually open peer and a major transit provider. When
the relationship inference labels one of its transit customers as a peer instead, every
ordinary transit route through it reads as a route taken from one peer and handed to another,
which is the textbook signature of a Type 2 leak. One misclassified link produces tens of
thousands of false candidates.

A network of that size leaking systematically across thousands of prefixes, in plain view of
six vantage points, while continuing to operate normally, is far less likely than the
inference being wrong about one link. The same reasoning applies to the other two large-cone
leakers in the sample.

**Estimated precision: 46%, that is 23 of 50.** With a sample of 50 the 95% confidence
interval is roughly 32% to 60%. This is a triage based on stated evidence rather than
confirmation by the operators involved, and it should be read that way.

The label criterion is written down so it can be disagreed with: a candidate is counted as
plausible when the leaker has a customer cone below 1,000, and as a likely inference artifact
when it is at or above that. Every one of the 27 artifacts is a lateral leak, and every one of
the 23 plausible candidates has a leaker small enough for a leak to be an ordinary
misconfiguration.

**Mitigation for Phase 6:** excluding lateral candidates whose leaker has a very large cone
removes the dominant error mode. That is a hypothesis to test, not a change made here, and it
trades recall for precision in a way that has to be measured rather than assumed.

### The counterfactual: would ASPA have stopped these leaks?

Evaluated on 3,000 corroborated candidates, every publication scenario against every filtering
scenario.

| Publication | Records | F-all | F-top100 | F-top20 |
| --- | --- | --- | --- | --- |
| S0, today's real records | 2,822 real | 0.4% | 0.4% | 0.3% |
| S1, plus the top 100 | +86 synthetic | 1.8% | 1.7% | 1.5% |
| S2, plus the top 1000 | +927 synthetic | 44.5% | 44.4% | 43.8% |
| S3, everybody publishes | +121,910 synthetic | 97.9% | 96.4% | 93.7% |

**S3 is an upper bound, not a prediction.** Its synthetic records are copied from the same
inferred topology that was used to detect the leaks, so it substantially asks whether a rule
derived from CAIDA's topology catches violations of CAIDA's topology. Plan Section 10.6
requires this warning to travel with the number, and the results table carries a flag on every
S3 row so it cannot be dropped when the table is copied.

Three things are worth drawing out.

**Today's deployment stops almost nothing.** With only the records operators have really
published, 0.4% of these leaks would have been caught. That is the honest state of ASPA in
September 2026, and it follows directly from the Phase 3 finding that only 1.4% of routes have
two ASPA publishers adjacent on the path.

**The jump happens between the top 100 and the top 1000.** Going from 100 to 1000 synthetic
publishers moves blocking from 1.8% to 44.5%. The largest hundred networks are not where the
leaks pass; the next nine hundred are. That is a concrete and tractable deployment target, and
it is the most useful number in this table.

**Who filters matters much less than who publishes.** Across every scenario, restricting
filtering to the top 20 networks costs only a few points against everybody filtering. The
constraint is publication, not enforcement.

Median blocking position sits at 0.6 to 0.83 of the way along the path, meaning a leak is
usually stopped late, near the network that received it from the leaker rather than close to
the origin. That matches the Phase 3 finding that a leak is invisible until it arrives
somewhere it should never have gone.

### Hijack candidates

`detect/hijacks.py` implements the three simple signals from plan Section 10.5: an origin not
seen in the baseline period, a more-specific prefix from a different network, and multiple
origins at once. Siblings are suppressed using the organisation mapping, and each candidate
carries its origin-validation state.

It has not been run on real data, because it needs a 30-day baseline of daily routing tables
and only one day has been ingested. The plan is explicit that this detector is context for RQ3
rather than a contribution, so building the baseline is left for Phase 6, where the
longitudinal run produces those days anyway.

### What Phase 5 did not deliver

Plan Section 11 accepts Phase 5 when the recall and precision numbers are written down and the
counterfactual runs end to end for all curated incidents. Precision is measured above and the
counterfactual runs end to end. **Recall is not measured, because `config/incidents.yaml` is
still the unverified stub written in Phase 0.**

Curating it means verifying, for each of the incidents in plan Section 14, the exact UTC
window, the leaking or hijacking AS, the affected prefixes and at least one public
post-mortem, then ingesting the update files for each window. Plan Section 14 marks every item
`VERIFY` for good reason: dates and AS numbers reported in news coverage are frequently wrong,
and an incident list assembled from memory would poison every number computed from it.

That work is outstanding and Phase 5 should not be called complete until it is done.

## Phase 5 completion (2026-09-18): curated incidents and recall

The Phase 5 write-up above ended with recall unmeasured because the incident list was an
unverified stub. It is now curated and recall is measured.

### The curated list

Seven incidents, each field taken from the primary post-mortem or analysis linked in the
file, checked on 2026-09-18. `config/incidents.yaml` carries the sources.

| Incident | Kind | Culprit |
| --- | --- | --- |
| 2017-08-25 Google leak affecting Japan | route leak | AS15169 |
| 2018-04-24 Amazon Route 53 hijack | origin hijack | AS10297 |
| 2019-06-24 Verizon and DQE leak | route leak | AS33154, AS396531 |
| 2021-04-17 Vodafone Idea | origin hijack | AS55410 |
| 2024-01-03 Orange España | RPKI misuse | AS12479 affected |
| 2025-05-01 Cox Communications leak | route leak | AS22773 |
| 2026-01-22 Cloudflare Miami leak | route leak | AS13335 |

**The `kind` column is not decoration.** Three of the seven are not route leaks at all. An
origin hijack travels a perfectly ordinary-looking path, so only origin validation can see
it. In the Orange España incident the routing was correct and the signed records were the
attack, so neither detector applies. Counting those three as misses would punish the leak
detector for failing at something it was never built to do, and counting them as successes
would be worse. They are reported as not applicable.

Two entries needed their framing corrected against the sources rather than accepted from
common description. The Vodafone Idea event is widely called a leak, but the primary analysis
says AS55410 "started originating routes that don't belong to them", which is mis-origination
and a different detector's problem. The Cox event is titled a route leak by its source, which
also reports that 4,644 of the routes would be RPKI-invalid, again pointing at
mis-origination; the disagreement is recorded rather than resolved by assumption.

### Recall

```bash
uv run hijax incidents --collectors route-views2
```

| | Count |
| --- | --- |
| Curated incidents | 7 |
| Of which route leaks | 4 |
| Not applicable to a path-based detector | 3 |
| Route leaks not visible to the collector used | 2 |
| **Judged** | **2** |
| **Detected** | **2** |
| Missed | 0 |
| **Recall** | **100%, on a denominator of two** |

Both detections are emphatic rather than marginal. The 2017 Google leak produced 2,740
sightings naming AS15169 across 16,462 distinct paths in 8.9 million announcements. The 2019
Verizon and DQE leak produced 11,186 sightings across 11,291 distinct paths in 12.5 million.

**Two of two is not a recall estimate worth much**, and it is reported as a count rather than
dressed up as a percentage anywhere it might be mistaken for one. The honest reading is that
the detector found both leaks it was in a position to see, and that the sample is far too
small to say more. Widening the collector set is the obvious way to raise the denominator and
is the first thing Phase 6 should do.

### Two findings that changed the method

**A leak has a network that causes it and a network that performs it, and they can differ.**
The 2019 incident was first scored as a miss. The detector had in fact found it, naming
AS396531 (Allegheny Technologies) in 11,186 paths, while the curated entry named AS33154
(DQE), because the post-mortem blames the faulty optimizer at DQE. Both are right about
different things. The optimizer ran at DQE; the network that took routes from one provider
and handed them to another was Allegheny, and that turn is the only thing visible in an
AS_PATH. The topology data agrees: AS396531's providers are exactly AS701 and AS33154. The
incident file now records `expected_leaker_asns` so either is accepted, and the distinction
is worth carrying into the paper because post-mortems reliably name the cause rather than the
mechanism.

**"The detector missed it" and "the collector never saw it" are different claims.** The
Cloudflare Miami leak was first scored as a miss too. Investigating it showed the leak was
IPv6 and confined to Miami, while every route the Oregon collector recorded passing through
Cloudflare during the window was IPv4, and no path anywhere in the window contained both
Cloudflare and Meta, the victim the post-mortem names. The collector was working normally,
recording 239,947 announcements in those 25 minutes. It simply never saw the leak.

Scoring that as a detector failure would have blamed the software for the shape of the
measurement infrastructure, which plan Section 15 already lists as collector visibility bias.
The tool now tests visibility explicitly: it compares the rate of routes *relayed through* the
culprit during the incident against the rate in the quiet hours either side, and reports
`not_visible` unless there is a clear elevation. A single relayed route inside the window is
not evidence that a leak was visible, which is why the test compares rates rather than
counting.

Both the Cloudflare and Cox incidents come out `not_visible` at a single collector. That is a
statement about one vantage point in Oregon, not about the incidents.

### What this says about the project's limits

Of seven real, well-documented incidents, a single-collector path-based detector could be
judged on two. That ratio is itself a result worth reporting: most publicly documented BGP
incidents are either not route leaks, or are invisible from any given vantage point. Any
claim about how often ASPA would help has to be read against that.

## Phase 6 (2026-09-18): longitudinal run and the regional lens

Phase 6 answers RQ1 (how far ASPA has actually spread, and what that buys) and RQ4 (how India
and the APNIC region compare with the world), and turns both into the figures the paper needs.

### RQ4: India against its region and the world

```bash
uv run hijax regional --date 2026-09-01 --country IN --top 12
```

On the 2026-09-01 snapshot, with 86,699 networks seen originating routes:

| Region | Routed networks | Publishing ASPA | Share |
| --- | ---: | ---: | ---: |
| Global | 86,658 | 2,484 | 2.87% |
| APNIC region | 20,169 | 202 | 1.00% |
| Registered IN | 2,931 | 54 | 1.84% |

*(Recomputed on 2026-09-19 against the re-ingested, verified-complete routes. The earlier
figures - 86,547 routed and 2.86% global - came from the ingest that turned out to be short;
the shares barely move, because truncation cost routes rather than origin networks.)*

India is roughly **two-thirds of the global rate but nearly twice the APNIC regional rate**.
The interesting comparison is the second one: India is not lagging its region, it is ahead of
it. The APNIC region as a whole is what lags, at about a third of the global share, and since
the APNIC region holds nearly a quarter of all routed networks that gap is most of why global
adoption is as low as it is.

The denominator is networks *seen originating a route*, not all registered networks. A network
that announces nothing cannot meaningfully publish an ASPA record about its providers, and
including tens of thousands of unrouted allocations would deflate every share for no reason.

**The finding that matters is not the share.** It is this:

| AS | Customer cone | Global rank | Publishes ASPA |
| --- | ---: | ---: | --- |
| AS9498 (Bharti Airtel) | 3,965 | 20 | no |
| AS4755 (Tata Communications) | 2,477 | 35 | no |
| AS9583 (Sify Limited) | 592 | 97 | no |
| AS55836 (Reliance Jio Infocomm) | 445 | 130 | no |
| AS55410 (Vodafone Idea) | 383 | 146 | no |
| AS18229 (Pioneer Elabs) | 308 | 189 | no |
| AS45820 (Tata Teleservices ISP) | 291 | 193 | no |
| AS9730 (Bharti Airtel) | 190 | 264 | no |
| AS17762 (Tata Teleservices Maharashtra) | 181 | 280 | no |
| AS17439 (NTTCINS) | 152 | 331 | no |
| AS45117 (Ishan's Network) | 150 | 337 | no |
| AS133296 (Web Werks India) | 111 | 426 | no |

Operator names are resolved from CAIDA's `20260801.as-org2info.jsonl` rather than asserted
from memory. Note that the twelve AS numbers belong to about nine distinct organisations:
Bharti Airtel holds AS9498 and AS9730, and Tata entities hold AS4755, AS45820 and AS17762.

**None of India's twelve largest transit networks publishes an ASPA record**, including two in
the global top 40 by customer cone. The 54 Indian publishers are all small networks.

The sharpest way to put it: the largest Indian network that *does* publish is AS9885, with a
customer cone of **85** and a global rank of **536**. India's largest network, AS9498, has a
cone of 3,965 and ranks **20th in the world**. The gap between those two lines is the whole
finding.

That is the opposite of the deployment order that would actually help. ASPA validation needs
*adjacent* publishers to confirm a hop, so a record published by a large transit network covers
every hop into and out of it and therefore protects everything in its customer cone. A record
published by a stub network at the edge covers one hop. India's adoption is happening where it
does the least good, and a single record from AS9498 would cover more paths than all 54 current
Indian publishers combined.

AS55410 in that table is the same network named in the 2021 mis-origination incident in
`config/incidents.yaml`. It still publishes nothing.

Two limits travel with every number above, and both are stated in the module docstring, the CLI
help and the figure subtitle rather than left to the reader:

* **Country means country of registration, not where the network operates.** That is what the
  registry files record. A network registered in India may carry most of its traffic elsewhere,
  and large operators register numbers in several countries.
* **None of this project's collectors is in India.** The vantage points are in Amsterdam,
  Oregon, Singapore, Tokyo and Sydney, so the Indian view is assembled from how Indian networks
  appear from outside. The APNIC region is selected by *allocating registry* rather than by a
  hand-written list of countries, so that at least needs no geographic judgement of its own.

### RQ1: where publishers sit on real paths

The adoption share says how many networks publish. It does not say what that buys, because a
record only does work when the network next to it on the path also has one. Measured across the
2026-09-01 routes:

| Position | Share of routes |
| --- | ---: |
| A publisher anywhere on the path | 40.0% |
| A publisher somewhere in transit | 33.2% |
| The collector's own peer publishes | 8.4% |
| The origin publishes | 3.0% |
| **Two adjacent publishers** | **5.4%** |
| **Every hop covered** | **0.04%** |

Two in five routes already touch a publisher, which sounds like meaningful progress. Only
**5.4%** contain an adjacent pair, which is the first point at which ASPA can say anything about
a hop, and **0.04%** are fully covered end to end. The gap between 40% and 5.4% is the whole
story of partial deployment: adoption is scattered, and scattered adoption composes badly,
because value appears only where two publishers happen to land next to each other.

This is also the honest frame for the counterfactual numbers from Phase 5. Claims of the form
"ASPA would have blocked X" are claims about a hypothetical adoption pattern, not today's.

### Longitudinal coverage

The RPKI half of the longitudinal series was already complete from Phase 1: **155 weekly
snapshots** of VRPs and ASPAs from 2023-10-11, the first day ASPA data exists, to 2026-09-16.
The BGP half is far more expensive, so it is sampled rather than complete, via
`scripts/phase6_longitudinal.py`:

* **Quarterly, not weekly.** A weekly BGP sweep across three years is about 150 table dumps.
* **One collector**, route-views2 in Oregon, the same vantage point Phases 4 and 5 used, so the
  series is comparable with them.

The script carries a download budget that stops the sweep before it can reach the 5 GB
threshold CLAUDE.md rule 8 says to ask the owner about, so it cannot quietly cross it. Building
that guard corrected an assumption: bgpkit streams each dump straight from the archive and
never caches it under `data/raw`, so a guard watching disk growth would have measured nothing.
It now reads each dump's `Content-Length` before ingesting. Measured on 2026-09-18, a
route-views2 dump runs 104 MB in 2023 down to 76 MB in 2026, so the whole sweep is about
**1.17 GB** — comfortably inside the limit. D-048 records both the error and the measurement.

`hijax longitudinal` prints the resulting series and `hijax report` draws it as
`validation_over_time.png`. A date missing one of the three inputs still appears in the series
with nulls, so a gap in the sweep is visible rather than silently skipped.

### Figures

`uv run hijax report` regenerates all six figures into `figures/` from stored tables alone. It
downloads nothing, so the same data always produces the same pictures, and a figure whose
inputs are missing is named and skipped rather than drawn from whatever is to hand.

| Figure | Question |
| --- | --- |
| `aspa_adoption_over_time.png` | RQ1: publishers per week since 2023-10 |
| `aspa_adoption_by_registry.png` | RQ1: which registries the growth comes from |
| `rpki_coverage_over_time.png` | RQ1: ROA coverage for context |
| `aspa_path_coverage.png` | RQ1: where publishers sit on real paths |
| `regional_comparison.png` | RQ4: India, APNIC and global |
| `counterfactual_blocking.png` | RQ3: what each adoption scenario would block |


## Closing out the Phase 1 and Phase 2 acceptance misses (2026-09-18)

Two acceptance criteria were still outstanding when Phase 6 finished. Working on them turned
up a bug that mattered considerably more than either.

### Phase 2: what the one-hour bar is actually made of

Phase 2 accepts when one day across all selected collectors ingests on the laptop in under an
hour with under 8 GB of RAM. The original run took 60.2 minutes, missing by twelve seconds.

The obvious remedy was to run the six collectors concurrently instead of one after another.
The link was measured first, and the first measurement was wrong in a way worth recording.

A quick probe fetched the first 6 MB of each of four dumps, serially and then in parallel, and
reported 232 KB/s against 279 KB/s - an apparent 1.2x, suggesting concurrency was nearly
pointless. **That probe under-measured.** Six megabytes is far too short a transfer to escape
TCP slow start, so most of each connection's sample was spent ramping up rather than at
steady state, and splitting a link four ways makes that worse. Sampling the real ingest
instead, over 152 seconds of sustained six-way transfer:

| | aggregate throughput |
| --- | ---: |
| Serial, one connection at a time | 232 KB/s |
| Six connections at once, sustained | **490 KB/s** (338-609 across five 30s intervals) |

So the link does give roughly **2.1x** to concurrency, not 1.2x. The lesson is about
measurement rather than networking: a throughput probe has to run long enough to reach steady
state, or it measures the ramp instead of the road.

One day across the six collectors is 818 MB:

| Collector | Dump size |
| --- | ---: |
| rrc00 | 427.0 MB |
| route-views.sg | 119.0 MB |
| rrc23 | 82.6 MB |
| route-views2 | 82.0 MB |
| route-views.sydney | 64.2 MB |
| rrc06 | 42.9 MB |
| **Total** | **817.6 MB** |

At the serial rate that is **58.7 minutes of pure transfer** before a single route is parsed.
rrc00 alone is 427 MB, more than half the total, so it sets the floor on any run that fetches
it.

### The measured result, on data known to be complete

```bash
powershell -File scripts/phase2_timed_run.ps1 -Day 2026-09-01 -Jobs 6
```

| | Result | Bar | |
| --- | ---: | --- | --- |
| Wall clock | **64.2 min** | under 60 min | **MISS** |
| Peak RAM | **1.80 GB** | under 8 GB | **PASS** |
| Rows ingested | **134,127,599** | | |

**The earlier 60.2-minute figure was measured on incomplete data.** The same six collectors on
the same date now yield 134.1 million rows against the 99.4 million originally reported - the
first run was missing about a quarter of the routes, on the unverified code path. So the
original result was never a twelve-second miss on a complete ingest; it was a faster run over
less data. Every per-collector table now holds a plausible full table, between 1.12 and 1.41
million prefixes, where the truncated parallel attempt held 29 to 146 thousand.

The bar is still missed, and by more than before, for an honest reason: verifying the bytes
costs time. Downloading each dump and then parsing it means the two no longer overlap within a
collector, where streaming had them running together. That is the trade this project should
make - plan Section 0 puts correctness above features, and a four-minute overrun is a far
smaller problem than a quarter of the routes going missing without anyone noticing.

The binding constraint remains the laptop's link, which was measured between 232 KB/s serial
and 490 KB/s across six connections, against 818 MB that has to arrive before the work can
finish.

### The bug that came out of it

Running the six collectors at once produced **silently truncated data**. Ingestion handed a
URL to the MRT parser, and a connection dropping mid-file just ended the iteration, so a
partial dump was written out as a finished table with a stats file beside it.

| rrc06, 2026-09-01 | rows | peers | prefixes | seconds |
| --- | ---: | ---: | ---: | ---: |
| `--jobs 6`, streamed from URL | 733,116 | 8 | 145,946 | 21.0 |
| `--jobs 1`, serial | 6,751,923 | 21 | 1,355,629 | 180.7 |

The parallel run kept 11% of the rows and reported success. Two things should have been
obvious and neither was checked: a 42.9 MB file cannot arrive in 21 seconds on a 237 KB/s
link, and a full routing table holds about 1.36 million prefixes, not 146 thousand.

Ingestion now downloads each dump through the project's own verified downloader, which
compares what arrived against `Content-Length`, retries a short read and raises rather than
returning a truncated file, and then parses the local copy. The update-file path used by the
Phase 5 incident analysis had the same hole and got the same fix. D-050 records it in full,
including the consequence that Phase 5's recall numbers were produced on the vulnerable path
and should be re-run before they are relied on.

The earlier atomic-rename fix was necessary but solved a different problem: it stopped a
half-*written* Parquet file being mistaken for a complete one, and could say nothing about a
half-*read* source.

### Phase 1: separating what can be proved from what needs a calendar

Phase 1 accepts when the ASPA count matches a public reference *and* the daily job has run
seven days in a row. The first half passed. The second half has two parts that were being run
together, and they are worth separating.

What the criterion is really testing is that the job works **repeatedly and idempotently on a
fresh checkout**. Every GitHub Actions run starts from a clean clone with `data/` empty, so a
run holds only the day it just ingested; the published series survives solely because it is
committed and each run *merges* into it. A broken merge would leave the series permanently one
day long, and only a multi-day run would expose it.

`scripts/phase1_seven_day_replay.py` replays exactly that: seven consecutive dates, each
starting from an empty processed directory, each merging into the one JSON that carries over.

The streak itself is now checked rather than remembered. `hijax adoption` and the workflow both
compute the longest run of consecutive days from the published JSON and print it. Against the
real file today that is **154 snapshots, streak of 1** - the backfill is weekly, and seven-day
spacing correctly counts as a streak of one, which is the case the unit tests pin down.

**What cannot be manufactured:** seven calendar days elapsing with the schedule enabled. The
repository was re-initialised on 2026-09-18 and nothing has been pushed, so the workflow has
never fired. That clock starts when it is pushed, and nothing here should be read as a
substitute for it.


## Phase 7 (2026-09-19): dashboard and reproducibility

Phase 7 accepts when somebody else can clone the repository, run `make reproduce-small` for one
date and one collector in under thirty minutes, and get the same numbers as the committed
fixtures. That is the criterion the whole project rests on, because every figure in the
write-up is worth exactly what an independent rerun says it is.

### The reproduction

```bash
make install
make reproduce-small
```

It ingests one RPKI snapshot, one month of topology data and one collector's routing table for
2026-09-01, validates and detects over them, and compares eleven counts against
`tests/fixtures/reproduce_small.json`. rrc06 was chosen because it is the smallest configured
collector at about 43 MB, and archive files for a past date never change, so the answer is
stable.

| | Reproduced | Fixture |
| --- | ---: | ---: |
| routes | 6,751,923 | 6,751,923 |
| peers | 21 | 21 |
| prefixes | 1,355,629 | 1,355,629 |
| ROV valid | 4,812,513 | 4,812,513 |
| ROV invalid | 3,376 | 3,376 |
| ROV not found | 1,936,034 | 1,936,034 |
| ASPA valid | 1,150,451 | 1,150,451 |
| ASPA invalid | 17,865 | 17,865 |
| ASPA unknown | 5,583,607 | 5,583,607 |
| VRPs | 996,912 | 996,912 |
| ASPA records | 2,822 | 2,822 |

All eleven match, in **3.6 minutes** against a thirty-minute budget. The derived tables were
deleted before the run, so the routing table was re-parsed and everything downstream
recomputed from scratch.

**What that run does not prove.** It reused the cached archive files, so it measured the
compute and not the download. A genuine fresh clone also fetches about 66 MB, which at the
link rates measured in Phase 2 adds roughly five minutes. Recording the qualification matters
more than the headline: the number above is the compute time.

Recording a new baseline is a separate, explicit command (`make reproduce-fixture`). A
comparison that quietly rewrites what it compares against proves nothing.

### The dashboard

`hijax export` writes the small JSON files the site reads, from tables already on disk. The
whole payload is **1.14 MB** against the 5 MB the plan allows, which matters because these
files are committed and every clone pays for them. The per-network table is the only large one
and is capped: it keeps every ASPA publisher plus the 2,000 largest networks by customer cone,
and says so on the page rather than implying it is the whole routing table.

Every exported file carries a `notes` field naming the limits that apply to its numbers, and
the pages render those rather than tucking them away. This is deliberate. A number on a web
page is the one most likely to be quoted without its caveats, and the two that matter most
here - country of *registration* rather than operation, and the fact that no collector sits in
India - are exactly the ones a reader would otherwise assume the other way.

The site is a static Next.js export with five pages (Overview, Networks, Incidents, Region,
Methodology), served from `web/out/` with no server at all. A page whose data file is missing
says so and names the command that produces it; it never shows a zero, because a zero reads as
a measurement.

Next.js 15.1.6 was flagged on install for CVE-2025-66478, and the version that fixed it still
pulled a vulnerable `postcss` transitively. The build now uses Next 16.3.5 with React 19.3.0
and audits clean. The practical exposure was near zero - `postcss` runs at build time over CSS
we wrote ourselves, and the output is static - but shipping a dependency with a known advisory
is not worth defending.

### Verifying Phase 5 after the truncation bug

D-050 recorded that the incident analysis had run on the vulnerable code path and that its
recall numbers should be re-run before being relied on. The first re-run reproduced the same
answer, but it had silently reused the incident windows cached by the *original* run, so it
verified nothing. Moving that cache aside and re-fetching everything through the verified path
gives the real comparison:

| Incident | Announcements | Distinct paths | Sightings naming the culprit |
| --- | ---: | ---: | ---: |
| 2017-08-25 Google/Japan | 8,920,488 | 16,462 | 2,740 |
| 2019-06-24 Verizon/DQE | 12,471,644 | 11,291 | 11,186 |

Both match the Phase 5 figures exactly. **The published recall numbers stand.** The truncation
only ever bit under concurrency, and the incident windows had been fetched serially.
