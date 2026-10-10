# Dataset inventory audit & reconciliation

Status: **read-only audit of the five supplied reference files.** No dataset was
downloaded, no external API was called, no source file was modified, and no
value in this report was invented — every figure is either quoted from a
reference file or marked `UNKNOWN`.

Date of audit: 2026-10-10 · Audit method: programmatic parse of all sheets
(stdlib XLSX reader, no third-party dependencies) plus field-by-field
comparison across sources.

## 1. Source register and assigned authority

| # | File | Sheets | Role (per instruction) |
| --- | --- | --- | --- |
| 1 | `CivicMind_AI_Dataset_V1_Freeze.xlsx` | README, Master Inventory (21×45), Verification & Acquisition (21×10), Resource Requirements (21×10 + totals), Final Dataset Recommendation (21×12), Acquisition Manifest (21×30) | **Primary planning reference** |
| 2 | `acquisition_manifest.csv` | 21 rows × 30 cols | **Detailed acquisition-status reference** |
| 3 | `resource_requirements.csv` | 21 rows × 10 cols | **Resource-planning reference** |
| 4 | `CivicMind_AI_Verified_Dataset_Inventory.xlsx` | README, Verification & Recommendation (21×11), Full Inventory (21×45), Recommended Set (18×7) | Traceability / conflict resolution |
| 5 | `CivicMind_AI_Master_Dataset_Inventory.xlsx` | README, Master Inventory (20×38), Ingestion Readiness (20×5) | Traceability / conflict resolution (earliest baseline) |

### 1.1 Key structural finding: the two CSVs are exports of the Freeze workbook

Verified cell-by-cell after normalisation (case, whitespace, quotes):

* `acquisition_manifest.csv` — headers identical, ID set identical, **0 differing cells** vs the Freeze `Acquisition Manifest` sheet.
* `resource_requirements.csv` — headers identical, ID set identical, **0 differing cells** vs the Freeze `Resource Requirements` sheet (rows 1-21; the sheet additionally carries a `TOTALS` block of 8 narrative rows that the CSV omits).

Consequence: the CSVs are **not independent sources** that can arbitrate a
conflict with the Freeze workbook — they are the same data. Disagreements must
therefore be resolved against the Verified and Master workbooks, which are
genuinely separate passes.

### 1.2 Schema evolution across passes

* Master workbook: **38 columns**, six analysis columns suffixed `(analysis)`.
* Verified and Freeze workbooks: **45 columns** — the six `(analysis)` columns
  renamed without suffix, plus seven added: `research_status`,
  `source_reliability_v3`, `integration_value`, `decision_value`,
  `automation_value`, `final_recommendation`, `acquisition_notes`.

Both 45-column workbooks also carry **two parallel reliability fields** that
disagree on every single row (21/21 in each): `source_reliability` (free text,
e.g. CIT-002 "Medium-High - reputable, long-running civic-tech NGO…") and
`source_reliability_v3` (enum, e.g. CIT-002 "MEDIUM"). See conflict **C-12**.

### 1.3 Workbook-internal consistency (checked, clean)

Within each workbook the Master/Full sheet, the Verification sheet and the
Recommended Set sheet agree on `research_status` and `final_recommendation`
(0 differences). One intra-Freeze divergence exists between the Verification
sheet and the *Final Dataset Recommendation* sheet — see **C-01**.

## 2. ID universe

All **21 canonical IDs are preserved, including WTR-005**:

`TRF-001…005` · `WST-001…003` · `WTR-001…005` · `ENV-001…004` · `CIT-001…004`

| Source | IDs | Missing | Extra |
| --- | --- | --- | --- |
| Freeze (all 4 data sheets) | 21 | — | — |
| `acquisition_manifest.csv` | 21 | — | — |
| `resource_requirements.csv` | 21 | — | — |
| Verified workbook (3 sheets) | 21 | — | — |
| Master workbook (both sheets) | 20 | **WTR-005** | — |
| Verified `Recommended Set` | 18 | WTR-001, WTR-002, CIT-004 | — |

* **WTR-005 is absent from the Master workbook** — it was introduced in the
  Verified pass as the replacement for WTR-001. Master's own README still
  counts 20 datasets (Water = 4). Master is the earliest baseline, so this is
  expected drift, not an error, but Master must not be used as an ID checklist.
* **`Recommended Set` omits exactly the three REPLACE/REJECT IDs**
  (WTR-001 superseded, WTR-002 and CIT-004 rejected). Omission is by design;
  the IDs remain in the inventory.
* **Duplicate IDs: none** in any sheet or CSV (checked all nine data tables).

### 2.1 Dangling reference: `TRF-006`

`TRF-006` ("Traffic Signal Data" / "Bengaluru Traffic Signal Data") is
referenced in free text in **three** places — Verified `Recommended Set`
(TRF-004 and TRF-005 `related_datasets`), Verified `Full Inventory`, and
Master `Master Inventory` — but **exists in no inventory, manifest, or
resource sheet**. Either a dataset was discovered and never catalogued, or the
reference is stale.Recorded as conflict **C-13**; no row was invented for it.

**APPROVED (2026-10-10):** TRF-006 is retained as an **unresolved reference**. No dataset record is invented to satisfy it; it may only be catalogued when real evidence for it exists.

## 3. Canonical inventory proposal

Principle: the **V1 Freeze is the planning authority**, the **acquisition
manifest the acquisition-status authority**, and the **resource CSV the sizing
authority**. The Verified and Master workbooks are retained unchanged as the
provenance trail for every superseded value. Nothing is overwritten — this
table states which source each canonical value comes from, and disputed values
are marked, not decided.

Short forms used below: `MO` = METADATA_ONLY, `BLK` = BLOCKED,
`ACQ` = ACQUIRED; `NP` = NOT_PROFILED, `SO` = SCHEMA_ONLY,
`PP` = PARTIALLY_PROFILED, `PROF` = PROFILED; `KWC` = KEEP_WITH_CHUNKING.

| ID | Canonical title (Master/Verified long form) | Domain | Publisher (canonical) | acq_status (manifest) | profiling (manifest) | research_status (Freeze) | recommendation (Freeze FDR) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TRF-001 | Traffic Accidents in India (Smart Cities) | Traffic/Mobility | Smart Cities Mission (via OpenCity) | MO | NP | VERIFIED | KEEP |
| TRF-002 | Public Transport Data (Smart Cities) | Traffic/Mobility | Smart Cities Mission (via OpenCity) | MO | NP | VERIFIED | KEEP |
| TRF-003 | BMTC GTFS Dataset (Bengaluru bus routes, stops, timetables) | Traffic/Mobility | Community-maintained (Vonter/bmtc-gtfs); BMTC data | ACQ | PROF | ACQUIRED | KWC |
| TRF-004 | Bengaluru Road Crashes Data (station-wise, 2007-2025) | Traffic/Mobility | Bengaluru Traffic Police (via OpenCity) | MO | NP | VERIFIED | KEEP |
| TRF-005 | Bengaluru Traffic Violations Data | Traffic/Mobility | Bengaluru Traffic Police (via OpenCity; also btp.gov.in) | MO | SO | VERIFIED | KEEP ⚠ C-04 |
| WST-001 | Solid Waste: State-wise Quantity Generated, Collected, Treated & Landfilled | Waste Management | CPCB (source replaced: Dataful → CPCB PDF) | MO | NP | CANDIDATE | CONDITIONAL (+ `source_replaced_from=Dataful.in`) — C-01 |
| WST-002 | Swachh Bharat Mission - Urban (SBM-U) 2015-16 to 2020-21 | Waste Management | MoHUA (via OpenBudgetsIndia) | BLK | NP | REJECTED | REJECT |
| WST-003 | Pune Solid Waste Management Data (ward/zone-wise) | Waste Management | Pune Municipal Corporation (via OpenCity + PMC portal) | ACQ | PP | ACQUIRED | KEEP |
| WTR-001 | Water Consumption Data (Ward-wise, Bengaluru) | Water | BWSSB / Karnataka UDD (via data.gov.in) | BLK | NP | REJECTED | REPLACE → WTR-005 (`temporal_coverage=UNKNOWN`, C-10) |
| WTR-002 | Mumbai Water Connections Details | Water | BMC / MCGM (via OpenCity) | BLK | NP | REJECTED | REJECT |
| WTR-003 | Delhi CETP Monthly Water Quality Data (2019-2022 and 2023-2024) | Water | Delhi Pollution Control Committee (DPCC) ⚠ C-08 | MO | SO | VERIFIED | KEEP |
| WTR-004 | CPCB NWMP / India-WRIS Water Quality | Water | CPCB + NWIC (Ministry of Jal Shakti) ⚠ C-08 | BLK | NP | CANDIDATE | CONDITIONAL |
| WTR-005 | BWSSB Data Collection (water supply, sewerage, consumption categories) | Water | BWSSB (via OpenCity) | MO locally (historical claim: ACQUIRED) — C-02 | PP | ACQUIRED (historical) | KEEP |
| ENV-001 | Real Time Air Quality Index from Various Locations | Environment | CPCB via data.gov.in (NDAP) | BLK | SO | VERIFIED | KEEP ⚠ C-03 |
| ENV-002 | CPCB NAMP — Historical Annual Ambient Air Quality Data | Environment | CPCB | MO | NP | VERIFIED | KEEP |
| ENV-003 | Bengaluru Tree Census Data (zone-wise) | Environment | BBMP (via OpenCity; official dashboard login-gated) | MO | NP | VERIFIED | KWC |
| ENV-004 | Pune Tree Census 2019 (ward-wise) | Environment | Pune Municipal Corporation (via OpenCity) | MO | NP | CANDIDATE | KWC |
| CIT-001 | BBMP Grievances Data (ward-level, 2020-2025) | Citizen Services | BBMP (via OpenCity) | ACQ | PP | ACQUIRED | KWC |
| CIT-002 | I Change My City — Complaints Log (2019-2022) | Citizen Services | Janaagraha (via OpenCity) | MO | SO | CANDIDATE | KEEP ⚠ C-05 |
| CIT-003 | Pune Property Tax Collections (ward-wise, FY 2018-19) | Citizen Services | Pune Municipal Corporation (via OpenCity) | MO | SO | CANDIDATE | KEEP |
| CIT-004 | CPGRAMS Monthly/Annual Grievance Redressal Statistics | Citizen Services | DARPG (+ Indiastat, subscription) | MO | NP | CANDIDATE | REJECT |

> **Legend for the `acq_status` column:** these are the *documented historical*
> states recorded in the manifest, **not** repository-local facts. Per Finding
> A-01 below, no acquired artefact exists in this repository, so the local
> state of all 21 IDs is `METADATA_ONLY` until a checksummed download lands in
> `data/raw/`.

Freeze README breakdowns reconcile exactly with the table: acquisition
`ACQUIRED 3 | METADATA_ONLY 13 | BLOCKED 5`; recommendation
`KEEP 11 | KEEP_WITH_CHUNKING 4 | CONDITIONAL 2 | REPLACE 1 | REJECT 3`.

### 3.1 Proposed canonical field mapping

Which source wins for each field, and where the losing values are preserved.
The full model (with target field names for the future metadata record) is in
[ingestion_plan.md](ingestion_plan.md) §2.

| Canonical field | Winning source | Losing values preserved in |
| --- | --- | --- |
| `dataset_id` | all sources (21 IDs, immutable) | — |
| `title` / `short_title` | Master/Verified long form / Freeze-FDR short form | §5 C-14 |
| `domain`, `subdomain` | identical across sources | — |
| `publisher`, `publisher_aliases` | manifest (latest correction) | §5 C-08 |
| `publisher_url` / `dataset_url` / `download_url` | manifest (three distinct fields, never merged) | §5 C-11 |
| `license`, `license_verified` | manifest where "CONFIRMED", else Master | §5 C-07 |
| `format` | manifest | §5 C-09 |
| `temporal_coverage`, `spatial_coverage`, `geographic_granularity` | manifest (most specific) | §5 C-10 |
| `record_count`, `file_size` | manifest; `UNKNOWN` stays `UNKNOWN` | §5 C-15 |
| `acquired_at` | Verified sheet `download_date` (4 real dates only; rest `UNKNOWN`) | §5, Finding A-02 |
| `research_status` | Freeze Verification sheet | {ACQUIRED, VERIFIED, CANDIDATE, REJECTED} — evidence maturity, **not** an axis |
| `research_decision` (axis 1) | Freeze Final Dataset Recommendation `recommendation` | KEEP / KEEP_WITH_CHUNKING / CONDITIONAL / REPLACE / REJECT; `REPLACE` records `replacement_target`, never sets axis 2 |
| `acquisition_state` (axis 2) | manifest `acquisition_status`, **repository-local evidence only** | METADATA_ONLY / DOWNLOADED / BLOCKED / SUPERSEDED; `SUPERSEDED` records `superseded_by`, never implies axis 1 |
| `validation_state` (axis 3) | new — measured locally | NOT_VALIDATED / VALIDATION_FAILED / VALIDATED; `VALIDATED` needs size + SHA-256 + timestamp + provenance + passing report |
| `profiling_state` (axis 4) | manifest `profiling_status` | NOT_PROFILED / SCHEMA_ONLY / PARTIALLY_PROFILED / PROFILED; statistics only — **never implies `VALIDATED`** |
| `source_replaced_from` | Verified/Freeze notes (C-01 approved) | source replacement, recorded **independently** of eligibility |
| `source_reliability`, `source_reliability_notes` | enum + prose merged from both parallel columns | §5 C-12 |
| resource plan | `resource_requirements.csv` | §3 of the ingestion plan |
| `data_quality_issues`, `acquisition_notes` | manifest + Freeze notes | retained verbatim |

## 4. Evidence-based state classification

The instruction "do not claim acquisition or profiling without evidence"
requires separating **documented claims** from **artefacts present in this
workspace**. Four different status vocabularies appear in the sources; the
canonical model folds them into the **four independent axes** defined in
§4.3, and they must not be conflated:

* `research_status` ∈ {ACQUIRED, VERIFIED, CANDIDATE, REJECTED} — a *research*
  axis (how well the source is understood).
* `acquisition_status` ∈ {ACQUIRED, METADATA_ONLY, BLOCKED} — an *acquisition*
  axis (what data was actually obtained).
* `ingestion_status` = `Not started` for all 20 Master rows.
* `profiling_status` ∈ {NOT_PROFILED, SCHEMA_ONLY, PARTIALLY_PROFILED, PROFILED}.

### 4.1 Local artefact verification (performed)

| Check | Result |
| --- | --- |
| `data/raw`, `data/interim`, `data/processed`, `data/external`, `artifacts/` | contain only `.gitkeep` — **no dataset files** |
| Git-tracked dataset files (csv/zip/kmz/kml/pdf) | **0** |
| Downloads folder | contains the five reference files plus unrelated personal files; **no** GTFS zip, BBMP CSV, KMZ or CETP PDF |

**Finding A-01 (critical):** the four datasets marked `ACQUIRED` in the
reference files (TRF-003, WST-003, CIT-001, WTR-005) were acquired in a
*different session/sandbox*. **No acquired artefact exists in this
workspace.** For local, reproducible purposes the true state of all 21 IDs is
`METADATA_ONLY` until a download is performed here and evidenced by a
checksummed file under `data/raw/`. The claims themselves are retained as
documented history, not as local fact.

### 4.2 "ACQUIRED" is overloaded (Finding A-02)

The reference files use `ACQUIRED` for materially different things — this must
be split before it reaches the ingestion layer:

| ID | What "ACQUIRED" actually means in the sources |
| --- | --- |
| TRF-003 | Full download (git clone), extracted, every size/row count/missingness/duplicate figure measured — the only genuinely complete acquisition |
| WST-003 | One of 6+ resources fetched (row-level sample of the 2021 segregation CSV) |
| CIT-001 | One of 6 yearly CSVs fetched, **truncated by tool output limits** — full-file row count and byte size remain unmeasured |
| WTR-005 | One of 7 resources' schema + size confirmed; row-level content **not** opened |

Consequently WTR-005 is simultaneously `research_status=ACQUIRED` and
`acquisition_status=METADATA_ONLY` (conflict **C-02**), and ENV-001 is
`acquisition_status=BLOCKED` while carrying `profiling_status=SCHEMA_ONLY`
(schema cross-confirmed by secondary sources with no live API response — the
manifest documents 3 real timed-out attempts).

### 4.3 Status model (implemented in `civicmind.ingestion`)

> **Update (2026-10-10).** This model is now **implemented** in
> `civicmind.ingestion` (`states.py` + `metadata.py`), covered by
> `tests/test_metadata.py`. One deviation from the original proposal: axis 1
> gained the `CONDITIONAL → REPLACE` edge so the terminal `REPLACE` state is
> reachable (see [ingestion_plan.md](ingestion_plan.md) §2.1). The value sets
> below are unchanged.

The sources mix several different questions into overlapping fields; the
canonical model keeps them separate. Full definition, authority,
permitted transitions and the validity gate live in
[ingestion_plan.md](ingestion_plan.md) §2.1 — the value sets below are
identical to that definition.

The first draft kept **three** axes, but its third axis ("validation/profile
state") conflated *validation* (did the bytes pass our checks?) with
*profiling* (what do the bytes contain?). Those diverge in both directions —
statistics can be computed over data that fails, or merely warns on, a
conformance check (WST-003's "households segregating = total households" flag
is exactly that case), and data can pass validation while barely profiled —
so the model now has **four** axes. Axes 1 and 2 are unchanged.

| Axis | Field | Values |
| --- | --- | --- |
| 1. Research decision | `research_decision` | `KEEP`, `KEEP_WITH_CHUNKING`, `CONDITIONAL`, `REPLACE`, `REJECT` |
| 2. Acquisition state | `acquisition_state` | `METADATA_ONLY`, `DOWNLOADED`, `BLOCKED`, `SUPERSEDED` |
| 3. Validation state | `validation_state` | `NOT_VALIDATED`, `VALIDATION_FAILED`, `VALIDATED` |
| 4. Profiling state | `profiling_state` | `NOT_PROFILED`, `SCHEMA_ONLY`, `PARTIALLY_PROFILED`, `PROFILED` |

**Validation is not profiling.** `PROFILED` never means `VALIDATED`: axis 4
records statistics, axis 3 records the outcome of a recorded
`ValidationReport`. They advance independently, and neither implies the other.

**Validity gate.** A file that merely exists is not valid. `VALIDATED`
requires the complete evidence set — recorded byte size, recorded SHA-256,
acquisition timestamp, provenance record, and a passing validation result.
Any missing piece leaves the record `NOT_VALIDATED`.

**`REPLACE` (axis 1) vs `SUPERSEDED` (axis 2).** `REPLACE` is a planning
decision about a record (`replacement_target=<id>`); `SUPERSEDED` is a fact
about bytes (`superseded_by=…`). They never imply each other: WTR-001 is
`REPLACE` → WTR-005 yet was never acquired, so it is not `SUPERSEDED`; a newer
ENV-003 snapshot would be `SUPERSEDED` while staying `KEEP`.

Transitions in summary (full rules in the plan): axis 1 changes only via a
documented review pass; axis 2 advances only on **local** evidence (byte size
+ SHA-256 + timestamp under `data/raw/<id>/`) with `BLOCKED` reversible when
the blocker clears; axis 3 advances only on a recorded passing report, carries
a `validation_scope`, and reverts to `NOT_VALIDATED` when the artifact changes
**or is superseded** (prior result retained in history); axis 4 advances only on
real measurement, with `SCHEMA_ONLY` always labelled documentation-derived — on
`SUPERSEDED`, measured axis-4 states revert to `NOT_PROFILED` while `SCHEMA_ONLY`
is kept. Failed validation
keeps the bytes (`DOWNLOADED` + `VALIDATION_FAILED`) and retains the failing
issues verbatim; partial profiling is recorded with a scope note so it cannot
be mistaken for whole-dataset validation.

Worked examples from this audit: ENV-001 = `KEEP` + `BLOCKED` +
`NOT_VALIDATED` + `SCHEMA_ONLY`; WTR-005 = `KEEP` + `METADATA_ONLY` (local; the
historical claim is retained separately, per C-02) + `NOT_VALIDATED` +
`PARTIALLY_PROFILED`; WST-001 = `CONDITIONAL` + `METADATA_ONLY` +
`NOT_VALIDATED` + `NOT_PROFILED`, with `source_replaced_from=Dataful.in`
carried on the source axis (per C-01).

This is a **proposed design** for the future metadata record. Nothing in
`civicmind.ingestion` implements it yet.

## 5. Conflict register (original values preserved)

Each conflict lists every source's original value. Nothing was silently
overwritten. Items marked **APPROVED** carry the decision taken on 2026-10-10
(see §6); originals remain beside each decision.

### Recommendation conflicts

**C-01 · WST-001 recommendation — APPROVED (semantic, intra-Freeze)**
* Verified `Verification & Recommendation`: `CONDITIONAL`
* Freeze `Verification & Acquisition`: `REPLACE` ("REPLACE the Dataful source with a direct CPCB PDF-report ingestion pipeline")
* Freeze `Final Dataset Recommendation`: `CONDITIONAL`
* Reading: "REPLACE" here describes the *source* (Dataful → CPCB), while the *dataset* stays CONDITIONAL.
* **APPROVED (2026-10-10):** source replacement and dataset eligibility are **separate dimensions**. Canonical encoding = `source_replaced_from=Dataful.in` (source axis) + `recommendation=CONDITIONAL` (eligibility axis). Both original values above are preserved verbatim; neither is discarded.

**C-02 · WTR-005 acquisition state — APPROVED**
* Verified & Freeze `research_status`: `ACQUIRED`
* Manifest `acquisition_status`: `METADATA_ONLY`
* Freeze README counts WTR-005 inside the 13 METADATA_ONLY.
* **APPROVED (2026-10-10):** historical acquisition claims are recorded **separately** from repository-local acquisition evidence. `research_decision` keeps the historical `ACQUIRED` claim as documented history; the repository-local `acquisition_state` stays `METADATA_ONLY` until an artifact is actually acquired and verified here. Promotion requires a real artifact, not a carried-over claim.

**C-03 · ENV-001 KEEP vs BLOCKED — resolved by evidence, retained**
* Both workbooks: `KEEP`, "highest-value dataset… first dataset acquired once an API key is obtained".
* Manifest: `acquisition_status=BLOCKED` (3 real attempts timed out; API key required).
* No contradiction (recommendation ≠ availability), but the KEEP must not be read as "ready to ingest". Blocked on a user-supplied data.gov.in key.

**C-04 · TRF-005: CONDITIONAL → KEEP**
* Verified: `CONDITIONAL` ("city-wide aggregate only… keep only if enforcement-trend correlation with TRF-004 is a defined use case").
* Freeze: `KEEP` ("strongest-provenance dataset in the Traffic domain… upgraded from CONDITIONAL to KEEP" via btp.gov.in corroboration).
* Freeze wins as the later pass; the earlier CONDITIONAL rationale is preserved here as a usage caveat.

**C-05 · CIT-002: CONDITIONAL → KEEP** — Verified `CONDITIONAL` (NGO provenance, lookup tables missing) vs Freeze `KEEP` (7.9 MiB measured, comfortable to process). Freeze wins; NGO provenance caveat retained.

**C-06 · Nine further Verified→Freeze upgrades (all documented, none disputed):** TRF-001, TRF-002 (CONDITIONAL→KEEP), WST-002 (CONDITIONAL→**REJECT**, blocked by bot-detection + low decision value), WTR-003 (CONDITIONAL→KEEP, schema confirmed), ENV-002, ENV-003 (CONDITIONAL→KEEP/KWC), plus the KEEP→KEEP_WITH_CHUNKING refinements for TRF-003, ENV-003, ENV-004, CIT-001 between the two Freeze sheets.

### Field conflicts

**C-07 · License (12 IDs)** — Master/Verified carry verbose or hedged values where the manifest carries confirmed ones.
**APPROVED (2026-10-10):** the conflicting values are **preserved as-is**, and every disputed licence stays `license_verified=false` until an authoritative licence statement is recorded from the publisher. No variant is silently chosen. Evidence per ID:

| ID | Master/Verified (original) | Manifest (original) | Proposed canonical |
| --- | --- | --- | --- |
| CIT-002 | "Per OpenCity portal norms (verify specific license…)" | "CC BY-SA 2.0 - CONFIRMED via direct resource metadata" | **CC BY-SA 2.0** (manifest, confirmed) |
| TRF-003 | "Open Database License (ODbL) 1.0" | "ODbL 1.0 … confirmed via repo LICENSE file" | **ODbL 1.0** (both agree) |
| WST-002 | "Open Government Data license (per OpenBudgetsIndia norms…)" | `UNKNOWN` | **UNVERIFIED** (C-07) — never accessed; do not assume |
| TRF-001/TRF-002 | "Government Open Data License - India (Public Domain / Open Data)" | "Other (Public Domain) / Open Data" | **UNVERIFIED** (C-07) — GODL-India vs portal-generic; needs licence-page check |
| TRF-004, WTR-002 | "…(OpenCity portal license/norm)" | "Other (Public Domain) / Open Data" | keep both; portal norm, unverified |
| WST-001, ENV-002, WTR-003, WTR-004, CIT-004 | "Government public-domain (verify specific reuse terms…)" | "Government public-domain (CPCB/DPCC/DARPG)…" | same substance; adopt manifest wording + `license_verified=false` |

**C-08 · Publisher (3 IDs)** — later passes corrected the agency:

| ID | Master | Verified/Manifest | Proposed |
| --- | --- | --- | --- |
| WTR-003 | "Government of Delhi" | "Delhi Pollution Control Committee (DPCC)" | **DPCC** (pass-2 correction, DPCC report page confirmed) |
| WTR-004 | "CPCB, MoEFCC" | "CPCB, MoEFCC; and NWIC, Ministry of Jal Shakti" | **CPCB + NWIC** |
| WTR-002 | "BMC" | "BMC / MCGM" | same entity, two names; keep both aliases |

**C-09 · Format (9 IDs)** — mostly specificity, two substantive:
WST-001 `CSV/tabular (via Dataful…)` vs `PDF` (follows the source replacement);
WTR-002 `PDF, CSV` vs `PDF (working); CSV (broken)` — the manifest's version is
correct and must be canonical (CSV resources return `datastore Error`).

**C-10 · Temporal coverage (14 IDs)** — 11 are the same window expressed with
more detail in the manifest. Two genuine disagreements:
*TRF-005* Master `UNKNOWN` vs Verified/manifest `2011-2025 (Resource 1), 2016-18, 2018-2025`;
*WTR-001* Master `UNKNOWN` vs Verified Full Inventory `At least June 2025 onward (monthly resources)` while the manifest keeps `UNKNOWN`.
**APPROVED (2026-10-10):** the canonical representation for this superseded record sets `temporal_coverage=UNKNOWN`; the unsupported claim is preserved above as audit history and is not deleted.

**C-11 · `source_url` semantics (17 IDs)** — Master/Verified record the
*publisher homepage*; the manifest records the *dataset page* (and for WST-001
a specific PDF URL). Not errors, but they must become two distinct canonical
fields (`publisher_url` vs `dataset_url`) rather than being merged. Notable:
WTR-005 `https://bwssb.karnataka.gov.in` vs `https://data.opencity.in/dataset/bwssb-data`.

**C-12 · `source_reliability` vs `source_reliability_v3` (21/21 rows differ)** —
parallel fields in both 45-column workbooks, free-text vs enum, e.g. CIT-002
"Medium-High …" vs `MEDIUM`; WST-002 "High origin (MoHUA) but … intermediary" vs
`MEDIUM`. **Proposal:** keep the enum as `source_reliability`, move the prose to
`source_reliability_notes`. The free text carries information the enum loses —
do not discard it.

**C-13 · Dangling ID TRF-006 — APPROVED: retained as an unresolved reference.** Referenced in 3 sheets, catalogued nowhere; no record invented.

**C-14 · Titles (17 IDs)** — Master/Verified long forms vs shortened
Freeze-FDR/manifest forms (e.g. "BMTC GTFS Dataset (Bengaluru bus routes,
stops, timetables)" vs "BMTC GTFS Dataset"). Proposed: canonical `title` = long
form, plus `short_title` for display. WTR-001 additionally carries status
suffixes ("- SUPERSEDED" / "- REPLACED") that belong in a status field, not the
title.

**C-15 · Record counts / file sizes** — only TRF-005 conflicts (Master
`UNKNOWN` vs Verified resource-level figures). All other values are consistent
and, where unknown, honestly `UNKNOWN`.

## 6. Resolution status (approved 2026-10-10)

Every item keeps its original values verbatim in §5.

| # | Conflict (originals retained in) | Competing values | Resolution / criterion | Status |
| --- | --- | --- | --- | --- |
| 1 | **C-01** WST-001 (§5 C-01) | `REPLACE` (Verified + Freeze Verification) vs `CONDITIONAL` (Freeze Final Recommendation) | **APPROVED:** two separate dimensions — `recommendation=CONDITIONAL` (eligibility) + `source_replaced_from=Dataful.in` (source replacement). Both originals preserved. | **Closed** |
| 2 | **C-02** WTR-005 (§5 C-02) | `research_status=ACQUIRED` vs `acquisition_status=METADATA_ONLY` | **APPROVED:** historical claim recorded separately from local evidence; local `acquisition_state=METADATA_ONLY` until an artifact is acquired and verified here. | **Closed** |
| 3 | **C-07** licences (§5 C-07) | WST-002 `UNKNOWN` vs "Open Government Data license"; TRF-001/TRF-002 "GODL-India" vs "Other (Public Domain) / Open Data" | **APPROVED:** conflicts preserved; every disputed licence stays `license_verified=false` until an authoritative licence statement is read from the publisher. Blocks redistribution, not local acquisition. | **Open — awaiting licence evidence** |
| 4 | **C-10** WTR-001 coverage (§5 C-10) | Master/manifest `UNKNOWN` vs Verified "At least June 2025 onward (monthly resources)" | **APPROVED:** canonical `temporal_coverage=UNKNOWN`; original claim preserved in §5 as history. | **Closed** |
| 5 | **C-13** TRF-006 (§2.1) | Referenced in 3 sheets; catalogued in none | **APPROVED:** retained as an unresolved reference; no dataset record invented. | **Open — no action until evidence exists** |
| 6 | **A-01** local artefacts (§4.1) | 4 IDs documented `ACQUIRED` vs 0 dataset files in `data/` | **APPROVED:** historical claims recorded separately; local acquisition stays `METADATA_ONLY` until an artifact is acquired and verified (SHA-256 + byte size + timestamp under `data/raw/<id>/`). | **Open — re-acquisition required** |

**ENV-001 (C-03)** remains `BLOCKED` on the acquisition axis until access is
configured and a real API call succeeds. No credential is requested, stored or
written to documentation by this audit.

## 7. What this audit deliberately did not do

No download, no API call, no modification of the five reference files, no
invention of sizes/rows/schemas, no merging that discards an original value,
no ingestion handlers, no new dependencies.
