# Proposed ingestion plan (Dataset V1)

Status: **plan only.** No dataset has been downloaded, no handler implemented,
no dependency installed. This document converts the audited inventory
([dataset_inventory_audit.md](dataset_inventory_audit.md)) into a staged,
evidence-first ingestion plan.

## 1. Governing rules

1. **Evidence or it did not happen.** A dataset's state advances only when an
   artefact exists under `data/raw/<source_id>/` with a recorded SHA-256,
   byte size and acquisition timestamp. Claims carried over from the research
   passes are recorded as *history*, never as local fact.
2. **No downloads in this phase.** Everything below is sequenced and costed;
   execution requires explicit authorisation.
3. **Rejected/conditional ≠ downloadable.** WST-002, WTR-002, CIT-004
   (REJECT), WTR-001 (REPLACE/superseded) and WTR-004, WST-001 (CONDITIONAL)
   are catalogued and retained, but are **not** download candidates until their
   blockers are cleared.
4. **Original values are never overwritten.** Every superseded value stays in
   the audit's conflict register with its source.
5. **Unknown stays unknown.** 12 of 21 datasets have unmeasured sizes;
   `UNKNOWN` is never replaced by an estimate without a measurement.

## 2. Canonical metadata model (proposal — not yet implemented)

Maps 1:1 onto the existing `civicmind.ingestion` contract; `SourceDescriptor`
gains fields, the contract itself is unchanged.

| Canonical field | Authority | Notes |
| --- | --- | --- |
| `dataset_id` | all sources (21 IDs) | immutable; WTR-005 retained |
| `title` / `short_title` | Master/Verified long form / Freeze-FDR short form | C-14 |
| `domain`, `subdomain` | identical across sources | no conflict |
| `publisher`, `publisher_aliases` | manifest (latest correction) | C-08: WTR-003 = DPCC, WTR-004 = CPCB + NWIC |
| `publisher_url` / `dataset_url` / `download_url` | manifest | C-11: three distinct fields, never merged |
| `license`, `license_verified` | manifest where "CONFIRMED", else master + `false` | C-07 |
| `format` | manifest | C-09: WTR-002 = "PDF working; CSV broken" |
| `temporal_coverage`, `spatial_coverage`, `geographic_granularity` | manifest (most specific) | C-10 open for WTR-001 |
| `record_count`, `file_size` | manifest; `null`/`UNKNOWN` when unknown | never invented |
| `acquired_at` | Verified sheet `download_date` | only 4 IDs carry a real date (2026-09-16: TRF-003, WST-003, CIT-001, WTR-005); all others `UNKNOWN` |
| `research_status` | Freeze Verification sheet | {ACQUIRED, VERIFIED, CANDIDATE, REJECTED} — evidence maturity, **not** an axis |
| `research_decision` (axis 1) | Freeze Final Dataset Recommendation `recommendation` | KEEP / KEEP_WITH_CHUNKING / CONDITIONAL / REPLACE / REJECT; `REPLACE` records `replacement_target`, never sets axis 2 |
| `acquisition_state` (axis 2) | manifest `acquisition_status`, **repository-local evidence only** | METADATA_ONLY / DOWNLOADED / BLOCKED / SUPERSEDED; `SUPERSEDED` records `superseded_by`, never implies axis 1 |
| `validation_state` (axis 3) | new — measured locally | NOT_VALIDATED / VALIDATION_FAILED / VALIDATED; `VALIDATED` needs size + SHA-256 + timestamp + provenance + passing report |
| `profiling_state` (axis 4) | manifest `profiling_status` | NOT_PROFILED / SCHEMA_ONLY / PARTIALLY_PROFILED / PROFILED; statistics only — **never implies `VALIDATED`** |
| `source_replaced_from` | Verified/Freeze notes (C-01 approved) | source replacement, recorded **independently** of eligibility |
| `source_reliability`, `source_reliability_notes` | 45-col workbooks | C-12: merge the two parallel fields (enum + prose) |
| resource plan | `resource_requirements.csv` | download/extracted/working MB, RAM, strategy, size_class |
| `data_quality_issues`, `acquisition_notes` | manifest + Freeze notes | travel with the dataset forever |

### 2.1 Proposed status model (design — not implemented)

#### Why the model grows from three axes to four

The sources mix several questions into overlapping fields. The first draft
kept **three** axes: research decision, acquisition state, and a combined
"validation/profile state". Review found that third axis conflated two
distinct questions that must not be collapsed:

* **validation** — did the bytes pass the checks we defined? (integrity,
  schema conformance, expected columns, referential checks)
* **profiling** — what do the bytes actually contain? (row/column counts,
  missingness, distributions)

They diverge in both directions: statistics can be computed over data that
fails — or merely warns on — a conformance check (WST-003's "households
segregating = total households" flag is exactly that case), and data can pass
validation while remaining barely profiled. **`PROFILED` therefore never means
`VALIDATED`.** Axes 1 and 2 are unchanged; old axis 3 becomes axes 3 and 4.

#### The four axes

| Axis | Field | Values | Authority |
| --- | --- | --- | --- |
| 1. Research decision | `research_decision` | `KEEP`, `KEEP_WITH_CHUNKING`, `CONDITIONAL`, `REPLACE`, `REJECT` | Freeze Final Dataset Recommendation |
| 2. Acquisition state | `acquisition_state` | `METADATA_ONLY`, `DOWNLOADED`, `BLOCKED`, `SUPERSEDED` | **repository-local evidence only** |
| 3. Validation state | `validation_state` | `NOT_VALIDATED`, `VALIDATION_FAILED`, `VALIDATED` | a recorded `ValidationReport` |
| 4. Profiling state | `profiling_state` | `NOT_PROFILED`, `SCHEMA_ONLY`, `PARTIALLY_PROFILED`, `PROFILED` | measurement, or clearly-labelled documentation |

**Permitted transitions**

*Axis 1 — research decision.* `CONDITIONAL` → `KEEP` / `KEEP_WITH_CHUNKING` /
`REJECT`; `KEEP` ⇄ `KEEP_WITH_CHUNKING` (processing refinement only);
`REJECT` → `CONDITIONAL` only with new evidence. `REPLACE` is a planning
decision that records `replacement_target=<id>`; it is terminal **for the
record's eligibility**, never for its bytes. **Every change requires a
documented review pass — no silent moves.**

*Axis 2 — acquisition state.* `METADATA_ONLY` → `DOWNLOADED` (requires an
artefact under `data/raw/<id>/` **with recorded byte size, SHA-256 and
acquisition timestamp**); `METADATA_ONLY` ⇄ `BLOCKED` (blocker hit / cleared);
any → `SUPERSEDED` (records `superseded_by`). `DOWNLOADED` → `METADATA_ONLY`
only on proven artefact loss, with a recorded reason. Re-downloads append a
new acquisition event; they do not regress state.

*Axis 3 — validation state.* `NOT_VALIDATED` → `VALIDATED` requires **all** of:
an artefact on disk, recorded byte size, recorded SHA-256, acquisition
timestamp, a provenance record, and a passing `ValidationReport`. **File
existence alone is never sufficient.** `NOT_VALIDATED` → `VALIDATION_FAILED`
when any error-severity issue is reported. `VALIDATION_FAILED` → `VALIDATED`
only after a **new** recorded run. `VALIDATED` → `NOT_VALIDATED` whenever the
artifact changes (see re-validation below). Every result carries a
`validation_scope` (which resources / rows / checks were covered).

*Axis 4 — profiling state.* `NOT_PROFILED` → `SCHEMA_ONLY` (schema known from
documentation only — always labelled as such); `SCHEMA_ONLY` →
`PARTIALLY_PROFILED` → `PROFILED` as real statistics are computed over an
increasing share of the dataset's resources. Advancing past `SCHEMA_ONLY`
requires axis 2 = `DOWNLOADED`. `PROFILED` says nothing about validity.

#### The validity gate

A downloaded artifact is **not** valid merely because its file exists. Moving
to `VALIDATED` requires the complete evidence set — recorded byte size,
recorded SHA-256, acquisition timestamp, provenance record, and a passing
validation result. Missing any one of the five leaves the record at
`NOT_VALIDATED`.

#### Representing the three tricky cases

| Case | Representation |
| --- | --- |
| **Failed validation** | axis 2 stays `DOWNLOADED` (the bytes exist); axis 3 = `VALIDATION_FAILED` with the failing `QualityIssue`s retained verbatim; axis 4 keeps whatever profiling already ran — statistics are not deleted because a check failed. Disposition (re-fetch, quarantine, reject) is a separate **axis-1** decision recorded in a review pass. |
| **Partial profiling** | axis 4 = `PARTIALLY_PROFILED` with a scope note (e.g. "3 of 7 resources"). Axis 3 is scoped independently: those 3 resources may be `VALIDATED` while the dataset as a whole stays `NOT_VALIDATED` for the unmeasured remainder — the `validation_scope` field keeps the two from being confused. |
| **Re-validation after a changed source artifact** | a new acquisition event (different SHA-256 or a newer revision) **invalidates** the previous result: axis 3 returns to `NOT_VALIDATED` for the new artifact, and the prior `VALIDATED` result is kept in history as a superseded validation event, not deleted. Axis 4 likewise drops to `PARTIALLY_PROFILED`/`NOT_PROFILED` for the new bytes unless statistics are recomputed. |

#### `REPLACE` (axis 1) vs `SUPERSEDED` (axis 2) — related, never interchangeable

* `research_decision=REPLACE` is a **planning statement about a record**: "do
  not build on this ID; `<replacement_target>` supersedes it." Set by a review
  pass; says nothing about bytes.
* `acquisition_state=SUPERSEDED` is a **fact about bytes/provenance**: the
  local artifact (or source revision) has been replaced by a newer one and
  must not be used. Set only when that replacement actually exists.
* They do **not** imply each other. **WTR-001** is `REPLACE` → WTR-005 yet was
  never acquired, so its axis 2 is `BLOCKED`/`METADATA_ONLY`, **not**
  `SUPERSEDED`. Conversely, a newer ENV-003 snapshot replacing an older KMZ
  would move axis 2 to `SUPERSEDED` while axis 1 stays `KEEP`.
* The link is recorded explicitly in both directions (`replacement_target` on
  axis 1, `superseded_by` on axis 2) so neither is ever inferred from the other.

#### Cross-axis rules

1. Axis 3 (`VALIDATED`) requires axis 2 = `DOWNLOADED` **and** the full
   five-part validity gate above.
2. Axis 4 past `SCHEMA_ONLY` requires axis 2 = `DOWNLOADED`. Statistics
   computed on bytes that are `NOT_VALIDATED`/`VALIDATION_FAILED` must be
   labelled **provisional**.
3. Axis 1 never implies axes 2, 3 or 4 — `KEEP` is intent, not availability.
4. `PROFILED` never implies `VALIDATED`, and `VALIDATED` never implies
   `PROFILED`; axes 3 and 4 advance independently.
5. Historical acquisition claims (from the research passes) are stored as
   history and never as current state. **Repository-local axis 2 for all 21
   IDs is `METADATA_ONLY` today** (audit Finding A-01) until an artifact is
   acquired and verified here.
6. A blocked axis-1-`KEEP` dataset (ENV-001) stays `BLOCKED` until access is
   configured **and tested** with a real successful call. No credential is
   requested, stored or written to documentation by this plan.

Status: **proposed design** for the future metadata record. Nothing in
`civicmind.ingestion` implements it yet; the existing contract is unchanged.

## 3. Resource review (from `resource_requirements.csv`, before any download)

| Tier | IDs | Measured cost | Handling |
| --- | --- | --- | --- |
| Trivial (SMALL, ≤ ~150 KB, 512 MB RAM floor) | TRF-001, TRF-002*, TRF-004, TRF-005, WST-003, WTR-003*, WTR-005, CIT-003 | ~67.2 MB total measured download across all 9 measured datasets | plain Pandas |
| Small-medium | CIT-002 (7.9 MiB), ENV-003 (16.8 MiB KMZ) | measured | Pandas; ENV-003 needs geopandas/fiona |
| Large / chunked | TRF-003 (42.3 MiB → 194.9 MiB, ~1.3 GB RAM measured for the two biggest tables, 4 GB recommended), ENV-004 (~4.09M rows, unmeasured bytes), CIT-001 (6-year union, estimate only) | partially measured | DuckDB/Polars or chunked Pandas |
| Streaming | ENV-001 (API, hourly polling → self-built history) | no live response obtained | DuckDB/SQLite accumulator |
| Excluded from V1 downloads | WST-001, WST-002, WTR-001, WTR-002, WTR-004, CIT-004 | unknown/blocked | not pursued |

`*` = size inferred by analogy or per-file assumption in the source notes, not
independently measured — verify at download time.

Only TRF-003's RAM figure is a real measurement; CIT-001/CIT-002 RAM figures
are explicitly labelled estimates in the source and must stay labelled.

## 4. Recommended pilot: **TRF-001** (Traffic Accidents in India, Smart Cities)

Seven IDs carry a **direct resource-level download URL** in the manifest
(TRF-001, TRF-003, TRF-005, WST-001, ENV-003, CIT-001, CIT-002); WST-003 and
ENV-001 carry only a dataset page / API endpoint, and the remaining 12 have
`UNKNOWN` or `N/A`. Of those seven, TRF-001 is the only one that is
simultaneously measured-tiny, single-file, government-origin, and free of
PDF/GIS/chunking tooling — so it exercises the *entire* contract with the
fewest unknowns:

* **Direct, resource-level CSV URL** captured in the manifest (see the fact
  box below). It was captured in an earlier pass and **has not been re-called
  or re-verified since** — URL stability is an explicit pilot risk.
* **Measured size** 2.6 KiB (2,662 bytes approx., from CKAN resource
  metadata — the file itself was never opened) → checksum validation is
  meaningful and cost is nil.
* **Government provenance** (Smart Cities Mission via the OpenCity mirror),
  CSV, 1 file, not compressed, no extraction tooling required.
* **Honest gaps to prove out the pipeline**: schema only partially confirmed
  ("at least 3 columns"), record count unknown — the pilot's job is to
  *measure* these, converting UNKNOWN → real values with provenance.

#### TRF-001 fact box (quoted from the inventory; the URL was **not** called)

| Field | Value as recorded in `acquisition_manifest.csv` / Master |
| --- | --- |
| Dataset page | `https://data.opencity.in/dataset/traffic-accidents-in-india` |
| Download URL | `https://data.opencity.in/dataset/ffd84c06-bc22-4716-9765-0a458d4f7571/resource/d43dcdc6-f35d-454d-8aaf-504a499f56a5/download/a224b81b-9d1c-46dc-9bbd-71adfedfddac.csv` (UUID path; captured earlier, unverified) |
| Access type | Direct CSV download (CKAN); `api_available: No` |
| Publisher | Smart Cities Mission, Ministry of Housing & Urban Affairs — **mirrored via OpenCity/Oorvani** (OpenCity is a re-publisher, not the primary portal) |
| Licence evidence | manifest: `Other (Public Domain) / Open Data`; Master: `Government Open Data License - India`. **No licence page was fetched → `license_verified=false`** (conflict C-07) |
| Format | CSV, `num_files: 1`, not compressed, extracted = same as download |
| Size | `2.6 KiB (2,662 bytes approx.)` — MEASURED from CKAN metadata |
| Coverage | temporal 2016-2018 · spatial "8 Indian cities" · granularity City · static, not actively updated |
| Known columns | "At least 3 confirmed (City, Total Registered Motor Vehicles as of 2016, Year)" — partial data dictionary only |
| **Uncertainties** | file never downloaded/opened · `num_rows: UNKNOWN` (the "likely <50 rows" note is an *inference*, not a measurement) · full column count, data types, missing %, duplicate count, primary key all `UNKNOWN` · download URL not re-verified · licence unresolved (C-07) · multi-city, not municipal/ward level |

Repository-local vs historical evidence: the manifest records TRF-001 as
`METADATA_ONLY`, and **no TRF-001 artefact exists in this repository**
(`data/raw/` holds only `.gitkeep`). Its state advances to `downloaded` only
when a checksummed file lands under `data/raw/trf-001/` here.

Pilot acceptance criteria (all must pass before promotion):
1. `data/raw/trf-001/` holds the CSV with SHA-256 + byte size recorded.
2. `AcquisitionResult` fields populated from measurement, not assumption.
3. `ValidationReport` passes (readable, non-empty, header present).
4. Real profiling numbers recorded (rows, columns, missingness) — upgrading
   `profiling_status` NOT_PROFILED → PROFILED with evidence.
5. Provenance record links back to this audit and to `resource_requirements.csv`.

**Second target: TRF-005** — same tier, but 3 resources with one unmeasured,
so it exercises multi-resource handling and the "unmeasured resource" warning
path. **CIT-003 and WST-003** (the research passes' own favourites) are deferred
only because their exact download URLs were not re-captured and must be
re-resolved first.

## 5. Staged plan

| Stage | Scope | Exit criterion |
| --- | --- | --- |
| **S0 · Canonicalise (now)** | Load the 21-row canonical inventory described in the audit into the future storage layer; keep every source value | 21 IDs, no unresolved field silently filled |
| **S1 · Pilot** | TRF-001 full cycle | pilot acceptance criteria above |
| **S2 · Multi-resource** | TRF-005 (3 resources), TRF-004 (7 resources) | every resource measured; unmeasured ones flagged |
| **S3 · Small measured set** | WST-003, CIT-003, WTR-005, CIT-002 | all SMALL tier ingested; WST-003's segregation-column quality flag carried through |
| **S4 · Blocker clearance** | ENV-001 (needs user data.gov.in key), WST-001 (CPCB PDF + extraction), TRF-002 (size unverified) | each blocker either cleared with evidence or dataset stays excluded |
| **S5 · Heavy tier design** | TRF-003 re-import, ENV-004, CIT-001, ENV-003 | chunked/GIS processing paths specified and costed |
| **S6 · Crosswalk work** | Pune 76-vs-77 ward crosswalk; Bengaluru ward-name→ID lookup | joins unblocked (integration work, not ingestion) |

Explicitly out of scope until later phases: RAG, embeddings, vector stores,
knowledge graphs, LLM inference, agents, dashboards.

## 6. Blocker and decision register

Decisions marked **APPROVED** are settled (audit §6); items marked **OPEN**
still need action or evidence.

1. **ENV-001 — OPEN, remains `BLOCKED`.** A registered data.gov.in API key is
   required and 3 real attempts timed out. Nothing can be downloaded until
   access is configured *and a real call succeeds*. No credential is requested
   or stored here.
2. **WST-002, WTR-004 — OPEN.** No accessible path found after multiple
   research passes; keep excluded rather than retrying blindly.
3. **WTR-002 — OPEN.** CSV resources broken at source; only PDF works.
4. **TRF-006 — APPROVED (C-13).** Retained as an unresolved reference; no
   dataset record invented. Catalogue only if real evidence appears.
5. **Re-acquisition — APPROVED (A-01/C-02), execution OPEN.** TRF-003,
   WST-003, CIT-001, WTR-005 carry historical `ACQUIRED` claims but have **no
   local artefacts**. Local `acquisition_state` stays `METADATA_ONLY` until a
   re-fetch lands a SHA-256 + byte size + timestamp under `data/raw/<id>/`.
6. **Licence verification — OPEN (C-07).** TRF-001/TRF-002 (GODL-India vs
   portal-generic) and WST-002 (unknown) stay `license_verified=false` until
   an authoritative statement is read from the publisher. Blocks
   redistribution, not local acquisition.
7. **WST-001 source replacement — APPROVED (C-01).** Recorded as
   `source_replaced_from=Dataful.in` alongside `recommendation=CONDITIONAL`;
   the two dimensions stay separate.
8. **WTR-001 coverage — APPROVED (C-10).** Canonical `temporal_coverage=UNKNOWN`;
   the original claim is preserved in the audit as history.

## 7. Next implementation steps (when you authorise implementation)

1. Extend `SourceDescriptor` (or add a sibling canonical-record dataclass) with
   the §2 fields — additive only, existing contract signatures unchanged.
2. Add a loader that materialises the canonical 21-row inventory as real
   metadata objects, with a unit test asserting: 21 IDs present including
   WTR-005, no field silently defaulted over an `UNKNOWN`, and every
   `recommendation`/`acquisition_status` value drawn from the allowed
   vocabularies.
3. Implement the TRF-001 handler against the existing `DatasetIngestor`
   contract (`describe` → `acquire` → `validate` → provenance), writing only to
   `data/raw/trf-001/`.
4. Add checksum + size assertions to the validation step.
5. Only then re-run the resource review and request authorisation for S2.
