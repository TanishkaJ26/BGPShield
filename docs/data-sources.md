# Verified data sources (Phase 0 output)

Everything below was checked on **2026-09-17** by downloading a real sample (kept, gitignored,
under `data/raw/samples/`) or by reading the live documentation. Nothing here is from memory.
`VERIFY` items from `implementation.md` are cross-referenced by section. All downloads used
`User-Agent: aspa-watch-phase0/0.1 (research; tanishkajangir26@gmail.com)`, the name the
project carried at the time. It was renamed to Hijax on 2026-09-18 and the scripts now send
`hijax-phase0/0.1 (research; tanishkajangir26@gmail.com)`.

Sample sizes and record counts are for the specific files named; they change daily.

---

## 1. BGP RIB dumps and updates (RIPE RIS, RouteViews) — plan §8 row 1

Plain English: a *route collector* is a passive BGP router that peers with many networks and
writes everything it hears to disk in MRT format (RFC 6396). A *RIB dump* is a full table
snapshot; an *updates* file holds the messages received in a short window.

### RIPE RIS

- Docs: <https://ris.ripe.net/docs/mrt/> (the bare `https://data.ris.ripe.net/` redirects there).
- URL pattern (verified by download): `https://data.ris.ripe.net/rrcXX/YYYY.MM/bview.YYYYMMDD.HHmm.gz`
  and `.../updates.YYYYMMDD.HHmm.gz`. Directory listings exist per collector back to `1999.09` for `rrc00`.
- **Cadence (resolves `VERIFY`): RIB dumps every 8 h (00:00, 08:00, 16:00 UTC); updates every 5 min.**
  Verified from the listing `rrc00/2026.09/` and the docs ("dumps are created every 8 hours",
  "updates are created every 5 minutes").
- Note: the docs page says the update files are named `update.*`; the live listing uses `updates.*`.
  Use the Broker URLs rather than building names by hand.
- Collectors (docs page, 23 active): multihop `rrc00` (Amsterdam), `rrc24` (Montevideo), `rrc25`
  (Amsterdam); APAC IXP collectors `rrc06` (Otemachi, JP) and `rrc23` (Singapore).
- Sample: `data/raw/samples/mrt/updates.20260901.0000.gz` (6,043,608 bytes) → 370,141 elements
  (349,085 announcements, 21,056 withdrawals) from 98 peers.
- RIB size reference: `rrc00/2026.09/bview.20260901.0000.gz` is 426,985,784 bytes (not downloaded).

### RouteViews

- Archive: <https://archive.routeviews.org/> (an HTML page listing every collector).
- URL pattern (verified): `https://archive.routeviews.org/<collector>/bgpdata/YYYY.MM/RIBS/rib.YYYYMMDD.HHmm.bz2`
  and `.../UPDATES/updates.YYYYMMDD.HHmm.bz2`. `route-views2` uses the same path form.
- **Cadence (resolves `VERIFY`): RIBs every 2 h; updates every 15 min.** Verified from the listing
  `route-views2/bgpdata/2026.09/RIBS/` (0000, 0200, …) and `UPDATES/` (0000, 0015, 0030, …).
- Samples:
  - `updates.20260901.0000.bz2` (route-views2, 1,530,226 bytes) → 256,742 elements (243,994 A, 12,748 W), 21 peers.
  - `rib.iix.cgk.20260901.0000.bz2` (Jakarta IXP collector, 378,420 bytes) → 63,406 routes, 16 peers.
  - `rib.route-views.bdix.20260901.0000.bz2` (Dhaka, 103,209 bytes) → 19,960 routes, 12 peers.
- RIB size reference: `route-views2` RIB at 2026-09-01T00:00 is 81,974,680 bytes; `route-views.sg` 118,957,602.

### First parsed element (pybgpkit, RouteViews updates sample)

```json
{"timestamp":1788220818.433596,"elem_type":"A","peer_ip":"37.139.139.17","peer_asn":57866,
 "peer_bgp_id":null,"prefix":"5.42.164.0/22","next_hop":"37.139.139.17",
 "as_path":"57866 5511 57976","origin_asns":[57976],"origin":"IGP","local_pref":0,"med":0,
 "communities":["1302:65023","5511:666", "..."],"atomic":"NAG","aggr_asn":null,"aggr_ip":null,
 "only_to_customer":null}
```

`as_path` is a **space-separated string, neighbour first, origin last** (raw BGP order); AS_SETs
appear as `{a,b}` in bgpkit's string form (to be confirmed on a path containing one in Phase 2).
Prepending is preserved (see the RIS sample: `... 147094 147094 147094 147094 ...`).

---

## 2. BGPKIT Broker and `pybgpkit` — plan §6 rows "MRT parsing" and "Collector file discovery"

- `pybgpkit` **0.8.0** (PyPI, 2026-07-02), pure-Python wheel; it depends on `pybgpkit-parser`
  **0.18.0**, which ships a `cp39-abi3-win_amd64` wheel (also macOS and manylinux). No C
  toolchain needed on Windows. Installed via `uv`.
- Verified API (script: `scripts/phase0_verify_pybgpkit.py`):
  - `bgpkit.Parser(url=<path or URL>)` iterates elements with the fields shown above; `.bz2`
    and `.gz` files are handled transparently, RIB and updates alike.
  - `filters={...}` works with keys `peer_asn`, `prefix`, `ip_version` (verified); other keys
    exposed by `bgpkit.Filter` are `peer_ip`, `origin_asn`, `as_path` (not yet exercised).
  - `bgpkit.Broker().query(ts_start=..., ts_end=..., collector_id=..., data_type="rib"|"updates")`
    returns `BrokerItem(ts_start, ts_end, collector_id, data_type, url, rough_size, exact_size)`.
    Example for `rrc00` at 2026-09-01T00:00Z:
    `url='https://data.ris.ripe.net/rrc00/2026.09/bview.20260901.0000.gz', rough_size=426770432`.
  - **Bug:** `Broker().collectors()` raises `TypeError: CollectorItem.__init__() got an unexpected
    keyword argument 'data_url'`. Workaround: `GET https://api.bgpkit.com/v3/broker/collectors`
    returns `{"data":[{name, project, data_url, activated_on, deactivated_on, country}, ...]}`
    (82 collectors, 76 active: 53 RouteViews, 23 RIS). Saved to `data/interim/phase0/broker_collectors.json`.
- Collector short-list and APAC candidates: `docs/decisions.md` D-004.

---

## 3. Historical RPKI: RIPE NCC archive (Routinator JSON) — plan §8 row 3

Plain English: a *validator* (Routinator, rpki-client) downloads the whole RPKI, checks every
signature, and emits the payloads routers need: VRPs (prefix, maxLength, origin AS) from ROAs and
ASPA records (customer AS, provider ASes). This archive stores one validator run per trust anchor
per day.

- Base: <https://ftp.ripe.net/rpki/>. Description and changelog:
  <https://github.com/RIPE-NCC/internet-dataset-descriptions/blob/main/rpki-repo-archive.md>.
- **URL pattern (verified for all five TAs): `https://ftp.ripe.net/rpki/<ta>.tal/YYYY/MM/DD/output.json.xz`**
  with `<ta>` ∈ `afrinic, apnic, arin, lacnic, ripencc`. Each day directory also has
  `roas.csv.xz`, `repo.tar.xz`, `routinator.log`, and `.md5`/`.sha256` files.
- Validator: Routinator (0.13.1 since 2024-01-25 per changelog). **ASPA enabled 2023-10-10;
  JSON output added 2023-10-11.** Earlier days have no ASPA data.
- Format (`output.json`, Routinator JSON): top-level keys `metadata`, `roas`, `routerKeys`, `aspas`.
  - `metadata`: `{"generated": 1789533333, "generatedTime": "2026-09-16T04:35:33Z"}`
  - `roas[i]`: `{"asn": "AS12975", "prefix": "1.178.112.0/20", "maxLength": 24, "ta": "ripencc"}`
  - `aspas[i]`: `{"customer": "AS553", "providers": ["AS559","AS680","AS1299","AS2914","AS3320"], "ta": "ripencc"}`
  - ASNs are strings with an `AS` prefix. **No `afi` field** in any of the 180 files scanned
    (2023-10-11 → 2026-09-01, all TAs), although the Routinator docs example still shows one
    (`docs/decisions.md` D-005). No duplicate `customer` values within one TA file on 2026-09-01.
- First 5 `aspas` records, RIPE TA, 2026-09-01:
  ```json
  {"customer": "AS553",  "providers": ["AS559", "AS680", "AS1299", "AS2914", "AS3320"], "ta": "ripencc"}
  {"customer": "AS559",  "providers": ["AS174", "AS513", "AS553", "AS1299", "AS3257", "AS3356", "AS20965", "AS21320"], "ta": "ripencc"}
  {"customer": "AS680",  "providers": ["AS1299", "AS2914", "AS3320", "AS3356", "AS20965", "AS21320"], "ta": "ripencc"}
  {"customer": "AS1199", "providers": ["AS1103"], "ta": "ripencc"}
  {"customer": "AS1200", "providers": ["AS1103", "AS4455", "AS6830", "AS12859"], "ta": "ripencc"}
  ```
- `roas.csv` header: `URI,ASN,IP Prefix,Max Length,Not Before,Not After` (one row per VRP, with
  the ROA object URI). Sample row:
  `rsync://rpki.ripe.net/repository/DEFAULT/5d/09cea0-.../_OICBSukGvCLBbc9uyxx5OyhMb4.roa,AS12975,1.178.112.0/20,24,2026-07-12 10:34:43,2027-07-01 00:00:00`
- Sizes (2026-09-16, RIPE TA): `output.json.xz` 1,659,904 bytes (362,961 ROAs, 2 router keys,
  1,979 ASPAs); `roas.csv.xz` 4,579,488 bytes.
- **Earliest ASPA date (resolves `VERIFY` in §8 "Sampling"): 2023-10-11**, RIPE TA, one record
  (`customer AS15562`, providers `AS2914, AS8283, AS51088, AS206238`). First non-zero per TA:
  ARIN 2023-11-01 (2), APNIC 2023-12-01 (12), LACNIC 2024-03-01 (1), AFRINIC none through
  2026-09-01. Monthly counts in `data/interim/phase0/ripe_archive_aspa_counts.csv`
  (`scripts/phase0_ripe_archive_sweep.py`); the totals grew from 1 (2023-10) to 137 (2025-11) to
  2,822 (2026-09-01: RIPE 1,872, ARIN 597, APNIC 221, LACNIC 132).
- Caveats from the changelog: gaps on 2023-06-24 and 2023-07-14…17; before 2021-10 the data came
  from rpki-validator-2 and `roa.csv` is often missing. Not relevant for ASPA (post-2023-10).

---

## 4. Historical RPKI: rpkiviews (rpki-client full snapshots) — plan §6 and §8 row 2

- Site: <https://www.rpkiviews.org/> (operated by Job Snijders). Two archive forms: **full
  snapshots** (a `.tgz` of the validator's complete validated cache after each run) and the newer
  **rpkispool** format (`draft-snijders-rpkispool-format`).
- Mirrors listed on the site with `https://<host>/rpkidata/` and `rsync://<host>/rpki/`:
  `josephine.sobornost.net`, `dango.attn.jp`, `rpkiviews.kerfuffle.net`, `amber.massars.net`.
  `dango.attn.jp` timed out from this network on 2026-09-17; `josephine` worked.
- **Layout (verified on josephine): `https://josephine.sobornost.net/rpkidata/YYYY/MM/DD/rpki-YYYYMMDDTHHMMSSZ.tgz`**,
  roughly every 20 minutes; a root `index.txt` lists `path mtime size` for every file.
- **Coverage:** josephine starts 2020-12-06 (first file `rpki-20201206T163723Z.tgz`, 121,339,458 bytes).
  Current snapshots are **586,436,881 bytes** (2026-09-16T00:06:05Z). One full snapshot was
  downloaded for format verification: see §4a below.
- Consequence: a daily backfill from rpkiviews would be about 0.6 GB/day (over 100 GB for the
  ASPA era). The RIPE NCC archive (§3) is about 5 MB/day for all TAs. See `docs/decisions.md` D-006.

### 4a. Snapshot contents (`rpki-20260916T000605Z.tgz`, josephine, 586,436,881 bytes, 655 s to download)

- Tarball layout: `rpki-<stamp>/data/<repository host>/…` (the raw fetched objects: `.cer`,
  `.mft`, `.crl`, `.roa`, `.asa` from 75 repository hosts) and `rpki-<stamp>/output/` with
  **`rpki-client.json` (104,709,272 bytes), `rpki-client.csv` (44,039,207 bytes) and
  `rpki-client.metrics` (OpenMetrics)**. The JSON cannot be fetched on its own; the whole
  tarball must be downloaded.
- `rpki-client.json` top-level keys: `metadata, roas, bgpsec_keys, nonfunc_cas, aspas, signedprefixlists`.
  - `metadata` includes `buildtime` ("2026-09-16T00:06:05Z"), object counts (`roas` 388168,
    `aspas` 3088, `failedaspas` 2, `vrps` 1014875, `uniquevrps` 1005140, `vaps` 3086,
    `uniquevaps` 3085), `talfiles` (afrinic, apnic, arin, lacnic, **ripe**) and CCR hashes.
  - `roas[i]`: `{"asn": 13335, "prefix": "1.0.0.0/24", "maxLength": 24, "ta": "apnic", "expires": 1790000255}`
    (1,005,140 entries: ripe 362,954; apnic 296,483; arin 269,279; lacnic 44,836; afrinic 31,588).
  - **`aspas[i]`: `{"customer_asid": 43, "expires": 1789657200, "providers": [293]}`** (3,085 entries).
    Integer ASNs, **no `ta` field**, `expires` in POSIX seconds, `providers` sorted and unique
    (verified for every record; max 226 providers). **63 records list provider AS 0**
    (e.g. `{"customer_asid": 174, "expires": 1789657200, "providers": [0]}`): the profile allows
    `PAS 0`, used to state "this AS has no providers". First five:
    ```json
    {"customer_asid": 43, "expires": 1789657200, "providers": [293]}
    {"customer_asid": 68, "expires": 1789657200, "providers": [293]}
    {"customer_asid": 79, "expires": 1789657200, "providers": [293]}
    {"customer_asid": 80, "expires": 1789689600, "providers": [3356, 6461]}
    {"customer_asid": 174, "expires": 1789657200, "providers": [0]}
    ```
- `rpki-client.csv` header: `ASN,IP Prefix,Max Length,Trust Anchor,Expires`
  (row: `AS13335,1.0.0.0/24,24,apnic,1790000255`). VRPs only, no ASPA.
- `rpki-client.metrics` gives **per-TA ASPA counts**, which the JSON does not:
  `rpki_client_ta_objects{type="aspa",state="valid",name=…}`: ripe 1,980; arin 630; apnic 338
  (+2 "failed parse"); lacnic 140; afrinic 0; total valid 3,088.
- Trust-anchor naming differs between validators: rpki-client `ripe`, Routinator archive `ripencc`.
- Format-version note (plan §9 `VERIFY`): this rpki-client output is AFI-agnostic. Older
  rpki-client releases (before the AFI-agnostic profile) are expected to differ; when a monthly
  cross-check reaches back into 2023–24 the adapter must be re-verified on that snapshot.

---

## 5. Live RPKI fallback: Routinator / rpki-client — plan §8 row 4

- Routinator 0.15.2: ASPA is **disabled by default**; enable with `--enable-aspa` or
  `enable-aspa = true` in the config (resolves `VERIFY flag`). Manual:
  <https://routinator.docs.nlnetlabs.nl/en/stable/manual-page.html>.
- rpki-client(8): `-j` writes a `json` file in the output directory; `-A` excludes the ASPA set;
  `-0` includes AS0 TALs. <https://man.openbsd.org/rpki-client.8>.
- Neither was run locally in Phase 0 (both need a system package and a long sync). Not needed
  while the archives above work.

---

## 6. CAIDA AS relationships (serial-2) — plan §8 row 5

Plain English: CAIDA infers, from public BGP paths, which network pays which (customer→provider)
and which pairs exchange traffic for free (peers). This is *inferred*, not declared, so it has
errors (plan §15).

- Listing: <https://publicdata.caida.org/datasets/as-relationships/serial-2/>, monthly files
  **`YYYYMM01.as-rel2.txt.bz2`** from `20151201` to `20260901` (verified; `20200201`/`20200301`
  withheld by CAIDA). README: `README.txt` in the same directory.
- **Format (resolves `VERIFY`):** `<provider-as>|<customer-as>|-1` and `<peer-as>|<peer-as>|0|<source>`.
  So `-1` = the first AS is the provider of the second; `0` = peers. Comment lines start with `#`
  (`# source:topology|BGP|20260801|routeviews|eqix`, …). The 4th column (`bgp`, `mlp`, …) is the
  inference source and appears on **both** kinds of rows in the 2026-08 file.
- Sample `20260801.as-rel2.txt.bz2` (2,076,745 bytes): 166,426 p2c rows, 511,478 p2p rows. First rows:
  ```
  1|11537|0|bgp
  1|54043|-1|bgp
  2|29091|0|bgp
  2|37280|-1|bgp
  3|293|0|bgp
  ```
- README notes: Ark-traceroute-derived links discontinued from 2018-09; multilateral-peering
  inferences missing 2023-01 to 2023-11. Citation required by the AUA:
  "The CAIDA AS Relationships Dataset, <date range>, https://www.caida.org/catalog/datasets/as-relationships/".

---

## 7. CAIDA AS Rank (customer cone, rank) — plan §8 row 6

- API v2: GraphQL at **`https://api.asrank.caida.org/v2/graphql`** (GraphiQL at `/v2/graphiql`,
  docs at `/v2/docs`). Also a RESTful interface per the docs.
- Fields for `asn(asn:"3356")`: `asn, asnName, rank, organization{orgId,orgName},
  asnDegree{transit,customer,peer,sibling}, cone{numberAsns,numberPrefixes,numberAddresses},
  source, cliqueMember`. Example query from the docs:
  ```graphql
  {asn(asn:"3356"){asn,asnName,rank,organization{orgId,orgName},asnDegree{transit},cone{numberAsns}}}
  ```
- Not yet exercised with a live query (Phase 2 `ingest/meta.py` will, with a paginated `asns` query
  and a snapshot date; the docs are the source of truth for pagination).

---

## 8. RIR delegated-extended statistics (AS → country, AS → RIR) — plan §8 row 7

Plain English: each RIR publishes a daily text file of every IP block and AS number it has handed
out, with the *registration* country. That is where the number was registered, not where the
network runs traffic (plan §8 and §15).

- **URLs (resolves `VERIFY URLs`), all verified by download on 2026-09-17:**
  | RIR | URL | Size (bytes) | ASN rows |
  | --- | --- | --- | --- |
  | AFRINIC | `https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-extended-latest` | 995,665 | 4,350 |
  | APNIC | `https://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest` | 9,239,567 | 14,747 |
  | ARIN | `https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest` | 12,783,068 | 32,959 |
  | LACNIC | `https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest` | 4,563,615 | 16,496 |
  | RIPE NCC | `https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest` | 18,063,739 | 48,682 |
  `https://ftp.apnic.net/stats/` also mirrors the other RIRs' directories (plus `iana/`).
- Format (RIR statistics exchange format, APNIC docs): version line
  `version|registry|serial|records|startdate|enddate|UTCoffset`; summary lines
  `registry|*|type|*|count|summary`; records
  `registry|cc|type|start|value|date|status|opaque-id` (extended format adds `opaque-id`).
  `type ∈ {asn, ipv4, ipv6}`. Observed `status` values on ASN rows: `allocated`, `assigned`
  (ARIN only), `reserved`, `available`. The APNIC file starts with a `#` comment block; version
  lines differ (`2|afrinic|…`, `2.3|apnic|…`, `2|ripencc|…`).
- **Dated (historical) files, verified 2026-09-18.** The "latest" files above are a moving
  target; every RIR also keeps per-day files, each with its own layout. Checked with a HEAD
  request for 2026-09-01:
  | RIR | Pattern | Status |
  | --- | --- | --- |
  | RIPE NCC | `https://ftp.ripe.net/pub/stats/ripencc/{YYYY}/delegated-ripencc-extended-{YYYYMMDD}.bz2` | 200 |
  | APNIC | `https://ftp.apnic.net/stats/apnic/{YYYY}/delegated-apnic-extended-{YYYYMMDD}.gz` | 200 |
  | ARIN | `https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-{YYYYMMDD}` | 200, no year directory, uncompressed |
  | AFRINIC | `https://ftp.afrinic.net/pub/stats/afrinic/{YYYY}/delegated-afrinic-extended-{YYYYMMDD}` | 200 |
  | LACNIC | `https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-{YYYYMMDD}` | recent days only, flat directory; older days under `archive/`. Note the name has no `extended` and there is no year directory. |
  Phase 1 deliberately does not use these; see `docs/decisions.md` D-013.

- First rows (APNIC ASN records): `apnic|JP|asn|173|1|20020801|allocated|A91A4B1A`,
  `apnic|NZ|asn|681|1|20020801|allocated|A91127C1`. India: 1,327 ASN rows with `cc=IN` in the APNIC file.

---

## 9. CAIDA AS-to-Organization (siblings) — plan §8 row 8

- Listing: <https://publicdata.caida.org/datasets/as-organizations/>. Files
  **`YYYYMMDD.as-org2info.txt.gz`** and **`.jsonl.gz`**; quarterly until 2024-07, **monthly**
  (`YYYYMM01`) since 2024-09, latest `20260901`. README: `README.txt` there. DOI
  `10.21986/CAIDA.DATA.AS-TO-ORG-MAPPING`.
- Text format: two sections separated by `# format:` lines:
  `# format:org_id|changed|org_name|country|source` then
  `# format:aut|changed|aut_name|org_id|opaque_id|source`.
- JSONL format (preferred): one object per line with `type` = `Organization`
  (`organizationId, name, country, changed, source`) or `ASN`
  (`asn, name, organizationId, opaqueId, changed, source`). Samples from `20260901`:
  ```json
  {"changed":"20171130","country":"US","name":"1-800 Contacts, Inc.","organizationId":"1800CO-2-ARIN","source":"ARIN","type":"Organization"}
  {"asn":"1","changed":"20240618","name":"LVLT-1","opaqueId":"e5e3b9c13678dfc483fb1f819d70883c_ARIN","organizationId":"LPL-141-ARIN","source":"ARIN","type":"ASN"}
  ```
- Text first AS rows: `1|20240618|LVLT-1|LPL-141-ARIN|e5e3b9c13678dfc483fb1f819d70883c_ARIN|ARIN`,
  `2|20231108|UDEL-DCN|UNIVER-19-Z-ARIN|…|ARIN`. Sample sizes: txt 4,012,353 bytes; jsonl 4,617,872 bytes.
- The `opaque_id` matches the last column of the delegated-extended files, which links AS → org → RIR record.

---

## 10. Public reference numbers for cross-checks — plan §11 Phase 1 and Phase 3 `VERIFY`

- **ASPA count reference (Phase 1 acceptance):** Hurricane Electric "RPKI & ASPA Adoption Report",
  <https://bgp.he.net/report/rpki_and_aspa>, "Updated 16 Sep 2026 13:16 PDT": Total ASPA
  Records 3,111; Routed ASNs Covered by ASPA 2,786; per RIR ripencc 1,987, arin 632, apnic 354,
  lacnic 138. Compare: RIPE NCC archive on 2026-09-16 has 1,979 for the RIPE TA.
- **ROV monitors (Phase 3 sanity check), reachable on 2026-09-17:** NIST RPKI Monitor
  <https://rpki-monitor.antd.nist.gov/> (200), Cloudflare <https://rpki.cloudflare.com/> and
  <https://isbgpsafeyet.com/> (200), APNIC Labs <https://stats.labs.apnic.net/rpki> (200),
  rpki-client console <https://console.rpki-client.org/> (200; its JSON endpoints timed out).
  `rov.rpki.net` did not respond. Which numbers they expose is left to Phase 3.

---

## 11. Prefix-matching library — plan §6 row "Prefix matching"

- `pytricia` 1.3.0 (PyPI 2025-09-15): **source distribution only**; on this Windows machine
  `uv add pytricia` fails with "Microsoft Visual C++ 14.0 or greater is required".
  **Blocker unless the owner approves installing the MSVC Build Tools** (system package).
- `py-radix` 1.1.0 (PyPI 2025-12-04): prebuilt wheels for CPython 3.9–3.14 on Windows
  (`win_amd64`), macOS and Linux. Works as the fallback named in the plan.
- Decision: `docs/decisions.md` D-007.

---

## Not covered in Phase 0 (by design)

- Curated incidents (plan §14): every item still `VERIFY`; `config/incidents.yaml` holds the list
  with `verified: false` and no dates or ASNs filled in (Phase 5).
- ASPA monotonicity property (plan §10.3): to be tested against the -28 text in Phase 3.
- `[aspa-examples]` URL from the verification draft: Phase 3.
