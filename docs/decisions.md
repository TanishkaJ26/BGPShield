# Design decisions (dated log)

Newest first. Each entry: what was decided, why, and what it affects.

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
