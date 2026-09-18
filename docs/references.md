# Pinned references

Every spec this project implements against, pinned to the exact version that was read.
Verified on **2026-09-17** against rfc-editor.org (`/rfc/rfcNNNN.json`) and the IETF
datatracker API (`/api/v1/doc/document/<name>/`). Local copies of the two ASPA drafts
are kept (gitignored) under `data/raw/specs/`.

## ASPA (the key specs)

| Document | Pinned version | Date | Status on 2026-09-17 | Used for |
| --- | --- | --- | --- | --- |
| `draft-ietf-sidrops-aspa-verification` | **-28** | 2026-08-24 | Internet-Draft, intended Proposed Standard, **not yet an RFC** (expires 2027-02-25) | `validate/aspa.py`, plan Section 10.3 |
| `draft-ietf-sidrops-aspa-profile` | **-29** | 2026-07-29 (datatracker last updated 2026-08-03) | Internet-Draft, intended Proposed Standard, **not yet an RFC** | ASPA object format, `aspas` table |

Text: <https://www.ietf.org/archive/id/draft-ietf-sidrops-aspa-verification-28.txt> and
<https://www.ietf.org/archive/id/draft-ietf-sidrops-aspa-profile-29.txt>.

Notes from reading `draft-ietf-sidrops-aspa-verification-28`:

- §5.2 defines `COMPRESSED_AS_PATH {AS(N) … AS(1)}` with **AS(1) = origin** and **AS(N) = the
  neighbour that sent the route**; AS(N+1) is the verifying AS and does not appear in the path.
  This is the origin-first indexing the plan adopts in Section 10.1.
- §5.3 `authorized(AS x, AS y)` returns "No Attestation" / "Provider+" / "Not Provider+"
  (the plan's `hop()` function). If a customer AS has several valid ASPAs, the provider set is
  the **union** (U-SPAS).
- §5.4 defines `max_up_ramp`, `min_up_ramp`, `max_down_ramp`, `min_down_ramp` exactly as in
  the plan's pseudocode.
- §5.5 (upstream: received from customer, peer, RS or RS-client) and §5.6 (downstream: received
  from provider). Steps: (1) empty path → Invalid, (2) neighbour-ASN mismatch → Invalid
  (upstream: unless the receiver is an RS-client), (3) **AS_SET → Invalid**, (4) ramp bound →
  Invalid, (5) → Unknown, (6) → Valid. Step 2 is an addition relative to the plan's pseudocode.
- §5.1: RFC 9774 requires treat-as-withdraw for AS_SET; if ASPA runs without that check, AS_SET
  paths evaluate as Invalid. This resolves the `VERIFY` in plan Section 10.1.
- §6.1 says worked examples are published online as `[aspa-examples]` (informative reference).
  The exact URL must be looked up in Phase 3 when those examples become test cases.
- §6.2: apply only to AFI/SAFI {1,1} and {2,1} (IPv4 and IPv6 unicast).

Notes from `draft-ietf-sidrops-aspa-profile-29`: the ASN.1 is
`ASProviderAttestation ::= SEQUENCE { version [0] INTEGER DEFAULT 0, customerASID CAS,
providers ProviderASSet }` with `ProviderASSet ::= SEQUENCE (SIZE(1..MAX)) OF PAS`. There is
**no per-address-family field**; provider lists are AFI-agnostic in this version.

## RFCs

| RFC | Title | Published | Status | Notes |
| --- | --- | --- | --- | --- |
| RFC 4271 | A Border Gateway Protocol 4 (BGP-4) | 2006-01 | Draft Standard | AS_PATH semantics (§4.3, §6.3) |
| RFC 6396 | Multi-Threaded Routing Toolkit (MRT) Routing Information Export Format | 2011-11 | Proposed Standard | file format of RIB dumps and updates |
| RFC 6480 | An Infrastructure to Support Secure Internet Routing | 2012-02 | Informational | RPKI architecture |
| RFC 6793 | BGP Support for Four-Octet AS Number Space | 2012-12 | Proposed Standard | AS4_PATH reconstruction; AS 23456 = AS_TRANS |
| RFC 6811 | BGP Prefix Origin Validation | 2013-01 | Proposed Standard (updated by RFC 8481, RFC 8893) | ROV algorithm (`validate/rov.py`) |
| RFC 6996 | AS Reservation for Private Use | 2013-07 | BCP | private ASNs 64512–65534 and 4200000000–4294967294 |
| RFC 7300 | Reservation of Last AS Numbers | 2014-07 | BCP | 65535 and 4294967295 reserved |
| RFC 5398 | AS Number Reservation for Documentation Use | 2008-12 | Informational | 64496–64511 and 65536–65551 |
| RFC 7606 | Revised Error Handling for BGP UPDATE Messages | 2015-08 | Proposed Standard | treat-as-withdraw |
| RFC 7607 | Codification of AS 0 Processing | 2015-08 | Proposed Standard | AS 0 handling |
| RFC 7908 | Problem Definition and Classification of BGP Route Leaks | 2016-06 | Informational | leak taxonomy (`detect/leaks.py`) |
| RFC 8182 | The RPKI Repository Delta Protocol (RRDP) | 2017-07 | Proposed Standard (updated by RFC 9674, RFC 9697) | how validators fetch data |
| RFC 8210 | RPKI to Router Protocol, Version 1 | 2017-09 | Proposed Standard | context only |
| RFC 9234 | Route Leak Prevention and Detection Using Roles in UPDATE and OPEN Messages | 2022-05 | Proposed Standard | OTC attribute; pybgpkit exposes it as `only_to_customer` |
| RFC 9319 | The Use of maxLength in the RPKI | 2022-10 | BCP | maxLength recommendation |
| RFC 9582 | A Profile for Route Origin Authorizations (ROAs) | 2024-05 | Proposed Standard | current ROA profile |
| RFC 9774 | Deprecation of AS_SET and AS_CONFED_SET in BGP | 2025-05 | Proposed Standard | why AS_SET paths are Invalid |

## Other references used in Phase 0

- Routinator 0.15.2 manual page: `--enable-aspa` / config `enable-aspa`; ASPA is **off by default**.
  <https://routinator.docs.nlnetlabs.nl/en/stable/manual-page.html>
- Routinator JSON output format: <https://routinator.docs.nlnetlabs.nl/en/stable/output-formats.html>
- rpki-client(8) manual: <https://man.openbsd.org/rpki-client.8> (`-j` writes a `json` file; `-A` excludes ASPA)
- RIPE NCC RPKI archive description and changelog:
  <https://github.com/RIPE-NCC/internet-dataset-descriptions/blob/main/rpki-repo-archive.md>
- RIR statistics exchange format (delegated files):
  <https://www.apnic.net/about-apnic/corporate-documents/documents/resource-guidelines/rir-statistics-exchange-format/>
- CAIDA AS Relationships (serial-2) README and AUA: <https://publicdata.caida.org/datasets/as-relationships/serial-2/README.txt>
- CAIDA AS-to-Organization README: <https://publicdata.caida.org/datasets/as-organizations/README.txt>
- CAIDA AS Rank API v2 (GraphQL): <https://api.asrank.caida.org/v2/docs>
- BGPKIT Broker REST API: <https://api.bgpkit.com/v3/broker/>; pybgpkit on PyPI: <https://pypi.org/project/pybgpkit/>
- Hurricane Electric "RPKI & ASPA Adoption Report": <https://bgp.he.net/report/rpki_and_aspa>
