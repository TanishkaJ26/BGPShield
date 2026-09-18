# Design decisions (dated log)

Newest first. Each entry: what was decided, why, and what it affects.

## 2026-09-18 - Closing out the Phase 1 and Phase 2 acceptance misses

### D-050: MRT dumps are downloaded and verified before parsing, never streamed from a URL
Trying to bring the Phase 2 ingest under its one-hour bar by running the six collectors at
once produced **silently truncated data**, which is the most serious kind of bug this project
can have.

Ingestion used to hand a URL straight to the MRT parser, which read the dump over HTTP inside
the parser. When a connection dropped part way through - which is what six concurrent
transfers on a saturated domestic link provoke - the iteration simply ended. Python saw an
ordinary end of loop. The partial dump was written out as a finished table with a stats file
beside it, and the command reported success.

The measurements, same collector and same date:

| rrc06, 2026-09-01 | rows | peers | prefixes | seconds |
| --- | ---: | ---: | ---: | ---: |
| `--jobs 6` (streamed from URL) | 733,116 | 8 | 145,946 | 21.0 |
| `--jobs 1` (serial) | 6,751,923 | 21 | 1,355,629 | 180.7 |

The parallel run captured **11% of the rows and 1 in 9 prefixes, and said it had finished**.
A 42.9 MB dump cannot be fetched in 21 seconds on a link measured at 237 KB/s, and a full
table is about 1.36 million prefixes, not 146 thousand. Both signals were there to be read;
neither was checked.

Ingestion now fetches each dump through `hijax.net.download` - which compares what arrived
against `Content-Length`, retries a short read and raises rather than returning a truncated
file - and parses the verified local copy. The earlier atomic-rename fix was necessary but
addressed a different failure: it stopped a half-*written* Parquet file being mistaken for a
complete one, and could say nothing about a half-*read* source.

Three things fall out of this:

* The bug was never parallelism. It was an unverified stream. With the byte count checked,
  running collectors concurrently is safe again.
* Dumps are now cached under `data/raw/mrt`, so re-runs cost nothing and the archives are
  spared repeat traffic (plan Section 16). One day across six collectors is about 818 MB.
* The sweep's download budget can now be measured exactly rather than inferred from
  `Content-Length` headers alone.

`tests/test_ingest_bgp.py` carries the regression: a short read must raise, and must leave
nothing behind that a later run could mistake for a cached result.

**Were the earlier ingests sound?** The truncation only appeared under concurrency, and
earlier runs were serial, but "probably fine" is not a standard. There is a cheap check:
elapsed time multiplied by the measured link rate should come out near the dump's size.
The serially ingested route-views2 dump for 2023-10-11 read 104 MB in 538 seconds, implying
193 KB/s against a link measured at 237 KB/s - consistent with a complete download. The
truncated rrc06 run implied 2,043 KB/s, about nine times the link rate, which is the tell.
`CollectorResult` now records `dump_bytes` so this check can be made from the stored stats
rather than reconstructed. The main analysis date, 2026-09-01, has been re-ingested on the
verified path.

**The same hole existed on the update-file path**, which is the one Phase 5's incident recall
reads. `_open_with_retry` retried on exceptions, but a stream that drops mid-file raises
nothing - it just returns a short list of elements - so the retry never fired. That path now
fetches and verifies the same way. The consequence for Phase 5 has to be stated rather than
assumed: **the published recall numbers were produced with the vulnerable code path**, and a
quietly half-read window is indistinguishable from an incident the detector could not see.
The incident check should be re-run on the fixed path before those numbers are relied on.

### D-051: The seven-day acceptance bar is checked, not remembered
Plan Section 11 Phase 1 accepts only once the daily job "has run 7 days in a row". That is a
property of the published series, so `hijax adoption` and the workflow both compute it from
`web/public/data/aspa_adoption.json` and print it. Weekly backfill snapshots sit seven days
apart and correctly score a streak of one, which is the case the unit tests pin down: against
the real published file, 154 snapshots give a streak of 1.

The workflow step never fails the build. A broken streak is information, not an error, and
failing there would stop the day being published and make the next streak worse.

## 2026-09-18 - Phase 6

### D-042: Adoption share is measured against routed networks, not all registered ones
A network that announces no routes cannot meaningfully publish an ASPA record about its
providers, and the registries hold tens of thousands of allocations that never appear in a
routing table. Including them would deflate every share for no reason and would make regions
look different simply because they hold more dormant allocations. The denominator is therefore
networks seen originating at least one route at the collectors, and the figure says so.

### D-043: The APNIC region is selected by allocating registry, not by a list of countries
Deciding which countries count as "the APNIC region" would be a geographic judgement this
project has no basis to make. Selecting on the registry that allocated the AS number is a
property already in the data and needs no judgement of its own.

### D-044: Country of registration is stated everywhere it is used, not just once
The country attached to an AS number is where it was registered, not where the network
operates, and the difference matters for exactly the large multinational operators that
dominate the Indian ranking. Rather than note it once in a document nobody reads next to the
number, it is repeated in the module docstring, the CLI help text and the subtitle of the
figure itself, so a number cannot travel without its caveat.

### D-045: Operator names are resolved from the data, never from memory
The first draft of the regional write-up named Bharti Airtel, Tata and Jio against their AS
numbers from memory. They happened to be right, but that is the kind of claim CLAUDE.md rule 2
exists to prevent, and a wrong operator name in a paper is worse than no name. All twelve names
are now resolved from CAIDA's `as-org2info` file and the release used is cited. Doing so also
surfaced something the numbers alone hid: the twelve AS numbers belong to about nine
organisations, because Bharti Airtel holds two and Tata entities hold three.

### D-046: Path coverage is reported next to adoption share, never on its own
Adoption share answers how many networks publish; it does not answer what publishing buys. An
ASPA record only does work when the network beside it on the path also has one. On real routes
40.0% touch a publisher somewhere but only 5.4% contain an adjacent pair and 0.04% are covered
end to end. Quoting 40% alone would badly overstate what is deployable today, so the two
numbers are always presented together, including in the figure.

### D-047: The longitudinal BGP series is quarterly and single-collector, and says so
A weekly BGP sweep across the three years of ASPA data is about 150 table dumps, which is not
proportionate to what the series is for. The sweep takes one table dump per quarter from
route-views2, the vantage point Phases 4 and 5 already used, so the series is comparable with
them. The RPKI half of the series is unaffected and remains weekly across all 155 snapshots.
This is a sampling reduction, recorded as one, not a claim of full coverage.

### D-048: The sweep enforces the download budget, and measures the right bytes
CLAUDE.md rule 8 says to ask the owner before downloading more than 5 GB, so the sweep driver
enforces that in code rather than relying on my arithmetic.

The first version of the guard was wrong in a way worth recording. It watched `data/raw` grow,
which is where this project caches its downloads, but bgpkit streams each routing-table dump
straight from the archive URL and never writes it to disk at all. The guard would therefore
have measured the CAIDA files and essentially nothing else, and could never have fired no
matter how much was pulled over the network. It now asks each dump's URL for its
`Content-Length` before ingesting and accumulates that, and a dump whose size cannot be read is
charged 150 MB rather than treated as free.

Measuring properly also showed the concern was smaller than assumed: a route-views2 dump runs
104 MB in 2023 down to 76 MB in 2026, so the full thirteen-date sweep is about **1.17 GB**,
well under the threshold. The guard stays because the estimate should not be the thing standing
between the project and the rule.

### D-049: `hijax report` draws only what the stored data supports
A figure whose inputs are missing is named and skipped, and the command reports how many were
skipped. The alternative, drawing a plausible-looking chart from whatever partial data is to
hand, is the failure mode most likely to put a wrong number in the paper.

## 2026-09-18 - Phase 5 completion

### D-036: The incident list records what kind of event each one was
Three of the seven curated incidents are not route leaks. An origin hijack can travel an
ordinary path and an RPKI misuse incident had correct routing, so neither is something a
path-based detector could find. Recall is computed only over the route leaks, and the others
are reported as not applicable. Two entries also needed their framing corrected against their
own sources, which describe mis-origination in events widely called leaks.

### D-037: An incident can have several legitimate culprits
The 2019 Verizon and DQE leak was first scored as a miss because the curated entry named
AS33154, which is what the post-mortem blames, while the detector named AS396531, which is
the network that actually turned the path around. Both are correct about different things,
and only the second is visible in an AS_PATH. Incidents now carry `expected_leaker_asns` and
the recall check accepts any of them.

### D-038: An invisible leak is not a miss, and visibility is tested by rate
The Cloudflare Miami leak was IPv6 and confined to one city; the collector examined recorded
only IPv4 routes through Cloudflare and never saw the victim network at all. Calling that a
detector failure would blame the software for where the collectors happen to be. The tool now
compares the rate of routes relayed through the culprit during the incident with the rate
either side, and reports `not_visible` without a clear elevation. A rate comparison rather
than a threshold on the raw count matters: a network that legitimately carries a trickle of
transit will always show a few relayed routes, and one of those must not be read as evidence
that a leak was visible.

### D-039: The organisation dataset needs a fallback in both format and date
CAIDA's AS-to-organisation data was quarterly until 2024 and only became monthly afterwards,
and the JSON Lines form exists only for some releases. Ingesting 2017-07 or 2019-05 failed on
both counts. The ingester now reads the original pipe-delimited text as well, and walks back
up to twelve months to the newest release on or before the month requested, which is what
plan Section 5 specifies. The month actually used is reported rather than silently
substituted.

### D-040: One unreachable update file must not discard a whole incident window
A single transient download failure aborted the 2017 incident after most of a 4.6-hour window
had been fetched. Each file is now retried and then skipped if it still fails, and the result
reports how many files were unreachable, so a window with holes is never mistaken for a
complete one.

### D-041: Recall of 100% is reported as two out of two
The denominator is two, and a percentage invites being quoted without it. The write-up gives
the count first and says plainly that the sample is too small to support a claim. Raising the
denominator means using more collectors, which is Phase 6 work.

## 2026-09-18 - Phase 5

### D-031: The relationship protocols live in one module
``RelSource`` had been defined twice and ``TopologySource`` once more, in three packages.
They are now in `hijax/topology.py` and imported from there. Structural typing keeps the
validators, detectors and counterfactual from importing the ingestion package just to say
what shape of object they need.

### D-032: A synthetic record for a network with no providers is an AS0 record
The first version of the scenario builder skipped any network for which the topology inferred
no providers. That silently excluded every tier-1, which are precisely the networks whose
records are most informative: an AS0 record contradicts any claim that somebody sits above
them. Under the old behaviour S3 failed to block the fixture leak at all. Networks absent from
the topology altogether still get no record, because "no providers inferred" and "never heard
of this network" are different statements and only the first justifies the assertion.

### D-033: Precision is reported as 46%, and the dominant error mode is named
A random sample of 50 corroborated candidates found that 54% name a very large transit
network as the leaker, always as a peer-to-peer leak, and 26 of the 50 name a single network.
The likeliest explanation is one or more transit links inferred as peering, which turns
ordinary transit into an apparent leak across thousands of prefixes.

The number is reported as it is. The alternative, quietly filtering large-cone leakers before
counting, would have produced a much better-looking precision figure that hides the actual
problem. The filter is proposed for Phase 6 as a hypothesis to be measured.

### D-034: The hijack detector is written but not run
It needs a 30-day baseline and only one day of routes exists. Plan Section 10.5 calls this
detector context rather than a contribution, so the baseline is deferred to Phase 6, whose
longitudinal run produces the days anyway. The module and its tests are complete.

### D-035: Phase 5 is not complete, and recall is not reported
Curating the incident list requires verifying each incident against primary post-mortems.
Inventing or half-remembering dates, AS numbers and prefixes would corrupt every recall number
computed from them, which rule 3 forbids. The stub in `config/incidents.yaml` still carries
`verified: false` on every entry and no dates. Recall is therefore not reported at all rather
than reported from an unverified list.

## 2026-09-18 - Phase 4

### D-027: Part of Section 10.4 was needed early
Phase 4 asks how many ASPA-Invalid routes are "not leaks according to 10.4", but plan Section
11 puts Section 10.4 in Phase 5. The direction classification and the valley-free test are
therefore implemented now in `detect/leaks.py`, because Phase 4 cannot be done without them.

What is deliberately **not** implemented yet, and stays in Phase 5: the RFC 7908 leak typing,
the requirement that a candidate be seen from two or more collector peers, and matching
against the curated incident list. Nothing produced in Phase 4 should be read as a confirmed
leak, and the module says so.

### D-028: A correct AS0 record is corroboration, not missing evidence
The first version of the completeness summary counted every publisher with no inferred
providers as "cannot judge". That conflated two opposite situations. A network that published
an AS0 record, meaning "I have no providers", and for which the inference also sees none, has
been *confirmed* by the inference. Only a network claiming providers that the inference has
never seen is genuinely unjudgeable. Splitting them moved 58 tier-1 records from the
unjudgeable column into the corroborated one, and it matters because those same networks
account for 76% of all contradicted routes.

### D-029: The false-positive rate is estimated two ways on purpose
Path shape and record quality are different evidence, and they give 17.7% and 20.1%. Both are
reported. They are not fully independent, since both use the same inferred relationship
graph, and the write-up says so rather than presenting the agreement as stronger than it is.

### D-030: Disagreements in the two directions are never summed
A record that omits an inferred provider can cause a legitimate route to be discarded. A
record that lists a provider the inference has not seen usually just means CAIDA never
observed that link, because it only sees what appears in public routing data. The first is a
risk and the second mostly is not, so they are counted separately and never added together
into one "inaccurate records" figure.

## 2026-09-18 - Phase 3

### D-022: The draft's worked examples are the conformance suite
The verification draft does not contain its examples inline; Section 6.1 points to a separate
PDF maintained by three of its authors. All 23 are now tests, each pinning the four ramp
lengths as well as the verdict. That document numbers the draft's sections 6.1 to 6.3 while
draft-28 has them at 5.4 to 5.6, because the numbering shifted between versions. The
algorithms are the same.

### D-023: Two steps the plan's pseudocode omitted
Implementing from the draft rather than from the plan's summary added two checks that plan
Section 10.3 leaves out, both of which change results:

1. **The neighbour check.** Both procedures return Invalid when the most recently added AS
   does not match the neighbour that sent the route (Sections 5.5 and 5.6, step 2).
2. **The route-server exemption.** The upstream procedure skips that check for an RS-client,
   because a transparent route server does not insert itself into the path (RFC 7947). This is
   the case Phase 2 found at the Jakarta exchange collector, where two peers accounted for
   every apparent neighbour mismatch.

### D-024: An unknown relationship runs both procedures and keeps the stricter answer
Plan Section 10.3 says to run both when CAIDA infers nothing about the pair, and to report
those routes separately. The combined state is the more severe of the two, so an ambiguous
route is never presented as clean, and a procedure recorded as "both" marks it for separate
reporting. On rrc06 this was 0.5% of routes.

### D-025: Validation results are memoised, not recomputed per route
A collector table repeats the same prefix, origin and path combinations many times: 6.75
million routes at rrc06 reduce to 1.36 million distinct prefix-and-origin pairs and 787
thousand distinct paths. Both validators are pure functions of those keys, so each distinct
key is evaluated once. That is what makes a full day validate in 96 seconds instead of about
an hour.

### D-026: The hand-trace is a script, not a notebook
Plan Section 11 says a reviewer should be able to trace three sampled Invalid routes "in a
notebook". `scripts/phase3_trace_invalid.py` does it as a seeded script instead: the same
reasoning, printed, rerunnable identically, and covered by the linters and the type checker
like the rest of the code. `notebooks/` stays for exploration, as plan Section 7 intends.

## 2026-09-18 — Phase 2

### D-017: Confederation segments cannot be told apart, so they are not dropped
Plan Section 10.1 step 1 says to drop AS_CONFED_SEQUENCE and AS_CONFED_SET segments and log
how many routes had them. That is **not possible through pybgpkit's API**. It hands back the
AS_PATH as a string, and the parser's own formatting code writes a confederation sequence
exactly like an ordinary sequence, and a confederation set exactly like an AS_SET:

```rust
AsPathSegment::AsSequence(v) | AsPathSegment::ConfedSequence(v) => { /* bare numbers */ }
AsPathSegment::AsSet(v) | AsPathSegment::ConfedSet(v) => { /* {a,b} */ }
```

**Decision:** parse confederation sequences as ordinary sequences and confederation sets as
AS_SETs, and say so wherever it matters. The practical cost is small. Confederation AS
numbers are meant never to leave the confederation (RFC 5065 Section 4.2), and when they do
leak they are usually from the private range, which the normalizer already flags and
excludes. What is lost is the ability to *count* them separately.

If Phase 5 needs the real segment types, the options are to parse MRT with a library that
exposes them, or to ask BGPKIT for a structured accessor, which would be a useful upstream
contribution (plan Section 18).

### D-018: pybgpkit's ``origin_asn`` is not used
For a path ending in an AS_SET, pybgpkit reports a member of the set as the origin, for
example ``"32787 10100 {10100}"`` gives ``origin_asn = 10100``. Plan Section 10.1 step 2 says
the origin must be **null** in that case, because no single member of a set is the origin.
The normalizer computes the origin itself and leaves it null there. A test pins this so an
upgrade of the library cannot quietly change the answer.

### D-019: A peer mismatch is a route-server signal, not corruption
2.2 % of routes at rrc06 and 86 % at the Jakarta IXP collector have a leftmost AS that is not
the peer the collector recorded. Breaking the Jakarta figure down by peer shows it is not
noise: two peers account for every single mismatch and every other peer matches on every
route. That is exactly how a transparent IXP route server behaves, since it must not insert
its own AS into the path (RFC 7947 Section 2.2.2).

**Decision:** keep the flag, do not treat it as making a route unusable, and carry it into
Phase 3, where the ASPA verification draft needs the same distinction: its neighbour check
has an explicit exception for routes received from a transparent route server, and the
upstream procedure applies to an RS-client (draft Sections 5.1 and 5.5).

### D-020: Route Parquet is written atomically
An early Phase 2 run had one collector fail, which tore down the worker pool and left short
Parquet files for the others: 740,666 routes from a 427 MB dump that should hold tens of
millions. A truncated Parquet file is still a valid Parquet file, so the next run treated it
as a complete cached result. Routes now stream to a temporary file that is renamed only after
the whole dump has been read, and any interruption deletes it. Tested by simulating the
interruption.

### D-021: Ingestion statistics live in a sidecar, not in the routes table
The normalization flags are not part of the Section 9 ``routes`` schema, and recomputing them
means re-reading every row. Each run writes ``stats.json`` next to its Parquet with the row,
peer and prefix counts and the per-flag rates, which is what the Phase 2 report needs.

## 2026-09-18 — Phase 1

### D-015: Phase 1 stores an `asn_registry` table, separate from Section 9's `as_meta`
Phase 1 needs only AS number to country and RIR. The plan's `as_meta` table also carries
`org_id`, `cone_size` and `rank`, which come from CAIDA datasets that belong to Phase 2.
Rather than write a half-empty `as_meta`, Phase 1 writes
`data/processed/asn_registry/asn_registry.parquet` with `asn, country, rir, status`.
Phase 2 builds the full `as_meta` and may join against this.

### D-014: The daily job merges into the published aggregate
`data/` is never committed (rule 5), so a GitHub Actions run holds only the single snapshot
it just fetched. If the export simply overwrote `web/public/data/aspa_adoption.json`, every
run would replace the whole time series with one point. `hijax adoption --export` therefore
merges: rows are keyed by snapshot date, so a re-run corrects a day instead of duplicating
it. Tested in `tests/test_adoption.py`.

The daily commit is made by `github-actions[bot]`, not by the owner's identity. That is
ordinary CI practice and keeps automated commits clearly distinguishable from the owner's.

### D-013: Phase 1 uses the *current* RIR delegated files for country, not dated ones
The adoption breakdown by country needs an AS number to country mapping. Dated per-day files
exist at all five RIRs, but each uses a different path, compression and naming, and LACNIC's
recent files sit in a flat directory with older ones under `archive/` (patterns recorded in
`docs/data-sources.md` section 8). Wiring up five historical fetchers is metadata ingestion,
which plan Section 7 places in `ingest/meta.py` in Phase 2.

**Decision:** Phase 1 labels every publisher with the country it is registered in *today*,
and says so in the exported JSON and in every figure. Registration country already differs
from operating country (plan Section 15), so this adds a second, smaller approximation:
an AS transferred between registries would be labelled with its current registry on older
snapshot dates. Phase 2 should replace this with the dated files and the difference should
be measured, not assumed negligible.

### D-016: Trust-anchor counts come from the file the record arrived in
rpki-client does not label ASPA records with a trust anchor, and the RIPE archive serves one
file per trust anchor. The ingester therefore passes the requested trust anchor as a
fallback, so per-RIR counts work for both formats. For a combined rpkiviews snapshot, which
mixes all five, ASPA records have no trust anchor and only the total is meaningful.

## 2026-09-18 — project rename

### D-010: Commit straight to `main`
The owner asked for commits and pushes to go directly into the repository rather than sitting on a
branch. Phase 0 was fast-forwarded from `phase-0` onto `main` (no history rewritten, `fa632eb..1a43937`)
and `CLAUDE.md` was updated to match. The earlier "never commit to `main`" convention no longer
applies. The `phase-0` branch is kept for now and can be deleted once the owner is happy.
Each commit still has to pass ruff, ruff format, mypy and pytest first.


### D-011: Everything is named `hijax`
The owner chose the name, which also answers open question 3 in `implementation.md` Section 19.
The Python package moved from `src/aspawatch/` to `src/hijax/`, the console command is now `hijax`,
and the project name, description and User-Agent follow. The plan document was retitled and its
Section 7 layout and Section 17 CLI examples were updated, with a note at the top recording the
two former names. One thing was deliberately **not** rewritten: `docs/data-sources.md` still
records that the Phase 0 downloads were made with the `aspa-watch-phase0/0.1` User-Agent, because
that is what archive operators actually saw. Rewriting it would falsify the record (rule 3).

### D-012: Build tools installed, but `pytricia` is out anyway; ROV will use `py-radix`
The owner approved the Microsoft C++ Build Tools and they installed cleanly: Visual Studio Build
Tools 2022, version 17.14, with the VC++ x64 toolset and Windows SDK 10.0.26100.

`pytricia` 1.3.0 **still does not build**, and this is not an environment problem. The compiler
ran and compiled `patricia.c` with only warnings; the build then failed in `pytricia.c` line 927
with `error C2065: 'ssize_t': undeclared identifier`. `ssize_t` is a POSIX type that MSVC does not
define. This is a known upstream bug: jsommers/pytricia issue **#48, "Fails to build on Windows"**,
open since 2026-06-02. No amount of local setup fixes it.

**Decision:** Phase 3 builds the ROV prefix lookup on **`py-radix` 1.1.0**, which ships wheels for
CPython 3.9 to 3.14 including `win_amd64`, so it needs no compiler at all. Verified on this
machine: `search_covering("203.0.113.5/32")` returns `['203.0.113.0/24', '203.0.0.0/16']`, which is
exactly the "find every VRP whose prefix covers P" step of RFC 6811 (plan Section 10.2, step 1).
IPv6 works and a miss returns `None`.

**Windows gotcha to remember in Phase 3:** `import socket` before touching `radix`, otherwise the
first `add()` raises `ValueError: Either the application has not called WSAStartup`. Python's
`socket` module initialises Winsock, which the extension assumes has happened. Wrap this in the
module that owns the trie so no caller has to know.

The dependency is **not** in `pyproject.toml` yet, because nothing imports it until Phase 3
(rule 1: one phase at a time). The build tools stay installed and are still useful for any other
source-only package. Fixing `pytricia` #48 is a genuine candidate for the open-source contribution
in plan Section 18, since the fix is small: use `Py_ssize_t` instead of `ssize_t`.

### D-009: Repository made public; Phase 0 acceptance met
The owner made `TanishkaJ26/Hijax` public on 2026-09-18 (verified through the GitHub API:
`"private": false`). This removes the mismatch with the plan, which assumes a public repo for the
free GitHub Actions cron (Section 6) and for GitHub Pages hosting (Section 7, Phase 7). Both are
now available on the free plan.

CI run 35303470401 on commit `3eb7adf` is **green**: install from the locked lockfile, ruff lint,
ruff format check, mypy and pytest all passed on `ubuntu-latest` in 18 seconds. With every `VERIFY`
item in `docs/data-sources.md` either resolved or recorded as a blocker, **Phase 0's acceptance
criteria (plan Section 11) are met.**

Public-repo note: the owner's contact email appears in `pyproject.toml`, `config/default.yaml`,
the two Phase 0 scripts and `docs/data-sources.md`. That is deliberate (plan Section 16 requires a
descriptive User-Agent with a contact address for archive operators), but it is now
world-readable, as is the commit author address. Switching to a GitHub `noreply` address or a
dedicated research alias is an option if the owner prefers.


### D-008: The project is now "Hijax" (was "Disha")
The owner renamed the project and the GitHub repository from `Disha` to `Hijax`
(`https://github.com/TanishkaJ26/Hijax.git`). The Phase 0 working tree was moved to
`C:\Users\tanis\Desktop\Hijax`, including the gitignored `data/` samples, so nothing has to be
downloaded again. The package and CLI were left as `aspawatch` at the time, pending the owner's
decision. **Superseded the same day by D-011 below: everything is now named `hijax`.**

### D-001 (resolved): git identity confirmed
The owner confirmed on 2026-09-18 that `Tanishka Jangir <tanishkajangir26@gmail.com>` and the
remote `https://github.com/TanishkaJ26/Hijax.git` are theirs, and asked that only their GitHub
account be used here. Git Credential Manager (system `gitconfig`) supplies the GitHub credential;
no `GITHUB_TOKEN`/`GH_TOKEN` is set in the environment and the `gh` CLI is not installed, so pushes
authenticate as the owner. The Claude session account (a different address) is never used for git.

## 2026-09-17 — Phase 0

### D-007: Prefix-matching library: custom radix trie, not `pytricia`
`pytricia` 1.3.0 is source-only on PyPI and needs "Microsoft Visual C++ 14.0 or greater" to
build on this Windows laptop (verified: `uv add pytricia` fails). Installing the MSVC Build
Tools is a system package, which needs the owner's approval (rule 8). `py-radix` 1.1.0 ships
`cp312-win_amd64` wheels and is a drop-in fallback. **Decision:** Phase 3 implements ROV with a
small pure-Python binary trie (the plan already allows "a custom radix trie"), with tests, and
may switch to `py-radix` if speed matters. The owner may instead approve the Build Tools.
**Superseded by D-012:** the Build Tools were installed and `pytricia` still fails to compile, for
a reason inside its own source. `py-radix` is the choice.

### D-006: Historical RPKI source: RIPE NCC archive first, rpkiviews for cross-checks
Both sources were verified (see `docs/data-sources.md`). The RIPE NCC archive
`https://ftp.ripe.net/rpki/<ta>.tal/YYYY/MM/DD/output.json.xz` covers all five trust anchors,
is Routinator JSON with an `aspas` list, is about 1 to 2 MB per TA per day, and has had ASPA
enabled since 2023-10-10. rpkiviews full snapshots are about 586 MB each (2026-09) and are
rpki-client output; the useful part is a 105 MB `output/rpki-client.json` inside the tarball,
which cannot be fetched without downloading the whole archive. **Decision:** Phase 1 ingests the
RIPE archive daily files (Routinator adapter) and uses one rpkiviews snapshot per month as an
independent cross-check of the ASPA count (rpki-client adapter). The plan's "rpkiviews primary"
wording (Sections 6 and 8) should be updated. Caveat for the paper: the two validators disagree
slightly (see `docs/methodology.md`), so the cross-check tolerance must allow for that.

### D-005: ASPA JSON formats: two adapters (Routinator, rpki-client), both AFI-agnostic
The profile draft (-29) has no AFI field, and none of the 180 archived Routinator JSON files
scanned (2023-10-11 to 2026-09-01, five TAs) contains an `afi` key in any `aspas` entry, even
though the Routinator docs page still shows one in its example. The rpki-client JSON in the
rpkiviews snapshot (2026-09-16) is also AFI-agnostic but differs in shape:

| | Routinator (RIPE archive) | rpki-client (rpkiviews) |
| --- | --- | --- |
| entry | `{"customer": "AS553", "providers": ["AS559", …], "ta": "ripencc"}` | `{"customer_asid": 43, "expires": 1789657200, "providers": [293]}` |
| ASN type | string with `AS` prefix | integer |
| trust anchor | per entry (`ripencc`) | **absent** on ASPA entries (present on ROAs as `ripe`) |
| expiry | absent | POSIX seconds |
| AS 0 as provider | not seen | seen (`"providers": [0]`, meaning "no providers"; profile allows PAS 0) |

**Decision:** `ingest/rpki.py` gets one adapter per validator, normalising to the plan's `aspas`
table (`customer_asn` int, `provider_asns` sorted unique ints, `ta` nullable, `expires`
nullable). Trust-anchor names are normalised to `afrinic, apnic, arin, lacnic, ripencc`
(rpki-client says `ripe`). The "union of per-AFI lists" rule from plan Section 9 is not needed
for either format but stays documented here in case an older per-AFI JSON turns up.

### D-004: Collector short-list (provisional, plan Section 8 "Collector selection")
From the BGPKIT Broker collector list (76 active on 2026-09-17) and RIB sizes at 2026-09-01T00:00Z:

| Collector | Project | Why | RIB size 2026-09-01 |
| --- | --- | --- | --- |
| `rrc00` | RIS | multihop, global peers (required) | 427 MB gz |
| `route-views2` | RouteViews | main RouteViews collector (required) | 82 MB bz2 |
| `rrc23` | RIS | Singapore IXP, APAC | 83 MB gz |
| `route-views.sg` | RouteViews | Singapore, APAC, large feed | 118 MB bz2 |
| `rrc06` | RIS | Otemachi (Tokyo), APAC | 43 MB gz |
| `route-views.sydney` | RouteViews | Sydney, APAC | 64 MB bz2 |

No collector is located in India. Candidates to add for RQ4 if their peer sets prove useful:
`route-views.bdix` (Dhaka, tiny), `hkix.hkg` (Hong Kong, since 2025-10), `getafix.mnl` (Manila),
`kinx.icn` (Seoul), `iix.cgk` (Jakarta), `route-views.bknix` (Bangkok). The final choice is made
in Phase 2 after inspecting the peer ASNs per collector. This answers open question 1
provisionally.

### D-003: BGPKIT Broker collector listing via REST
`bgpkit.Broker().collectors()` in pybgpkit 0.8.0 raises `TypeError: CollectorItem.__init__() got
an unexpected keyword argument 'data_url'` because the API now returns `data_url` and no `id`.
**Decision:** call `GET https://api.bgpkit.com/v3/broker/collectors` directly with `requests`
until upstream is fixed, and file an upstream issue or PR (candidate open-source contribution,
plan Section 18). No existing issue was found on the pybgpkit tracker on 2026-09-17.

### D-002: Tooling on Windows
`uv` was installed with `pip install --user uv` (no system package). Python 3.12.14 is a
uv-managed interpreter (`uv python install 3.12`); the system Python is 3.14. CI runs on
`ubuntu-latest` with `uv sync --locked`.

### D-001: No commits until the owner confirms the git identity
The owner asked to see `git config user.name`, `git config user.email` and `git remote -v` and to
confirm before any commit. Phase 0 work sat on branch `phase-0`, uncommitted, until then.
**Resolved 2026-09-18** — see D-008 above.
