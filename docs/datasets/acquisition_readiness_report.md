# Milestone 6C — Source Verification and Acquisition Readiness

Status: planning/report only. No dataset was downloaded, no API was called for
data transfer, no raw dataset file was saved, and no code, test, dependency,
canonical metadata, licence flag, or research decision was modified.

Repository baseline used for this report:
- Branch: `main`
- HEAD: `7bf8275c0282a395f6132f9d60c36948c9fb830f`
- Remote `origin/main`: `7bf8275c0282a395f6132f9d60c36948c9fb830f`
- Working tree: one untracked planning file from Milestone 6B
  (`docs/datasets/integration_selection_plan.md`); nothing staged, committed, or
  pushed.
- Verified this session via `git rev-parse HEAD`, `git branch --show-current`,
  `git status --short`, and `git ls-remote origin refs/heads/main`.

This report extends `docs/datasets/integration_selection_plan.md`; it does not
overwrite that document.

---

## 1. Executive decision

Fastest scientifically defensible first experiment: **TRF-004 + TRF-005 as a
Bengaluru public-safety descriptive comparison, analyzed at the finest geography
each source actually supports.**

Recommended primary path:
- TRF-004 as the crash/injury outcome signal
- TRF-005 as the enforcement-signal complement
- comparison framed as descriptive co-occurrence and trend alignment, **not** as
  causal attribution or as a station-to-ward integration unless a verified
  station-to-ward mapping is later produced

Do **not** start from CIT-001 as a join anchor unless a credible ward identifier
and mapping path are verified first. The reported CIT-001 schema uses `Ward Name`,
not a stable ward code, and the existing repository does not contain a verified
ward mapping. Using ward name as a join key would be an assumption, not evidence.

TRF-001 remains a fallback candidate only. Its source identity and licence
situation are still unresolved for the intended use, so it is not the fastest
route and should not be acquired first.

Single most important blocker for the recommended path:
- **Licence/intended-use verification for the BTP datasets**, because the
  OpenCity "Other (Public Domain)" label is mirror metadata, not verified
  publisher permission for the intended research and any downstream use.

---

## 2. Current repository and candidate status

### 2.1 Repository facts

- Canonical inventory: 21 dataset IDs in
  `configs/datasets/canonical_metadata.csv`.
- Repository-local state for every ID: metadata only. No acquired artifact exists
  under `data/raw/`; only `.gitkeep` placeholders exist.
- This matches Milestone 5 and the previous Milestone 6B report.

### 2.2 Candidate status from the repository

#### TRF-004 — Bengaluru Road Crashes Data
- Canonical title: Bengaluru Road Crashes Data (station-wise, 2007-2025)
- Domain: Traffic/Mobility
- Publisher in canonical CSV: Bengaluru Traffic Police (via OpenCity)
- Publisher aliases: Bengaluru Traffic Police; Bengaluru Traffic Department
- Publisher URL: `https://btp.gov.in`
- Dataset URL: `https://data.opencity.in/dataset/bengaluru-road-crashes-data`
- Download URL: `Unknown CSV`
- License: `Other (Public Domain) / Open Data`
- `license_verified`: `false`
- Format: CSV
- Temporal coverage: 2007-2025
- Spatial coverage: Bengaluru
- Geographic granularity: City
- Record count: UNKNOWN
- File size: UNKNOWN
- Research status: VERIFIED
- Source reliability: MEDIUM
- Notes: Download URL not re-captured.
- Research decision in canonical CSV: not set there; the canonical CSV row does
  not carry a research_decision field directly. The four-axis record starts
  `CONDITIONAL` until a review says otherwise.
- Local axes: all start at conservative defaults until evidence is recorded
  (`METADATA_ONLY`, `NOT_VALIDATED`, `NOT_PROFILED`).

#### TRF-005 — Bengaluru Traffic Violations Data
- Canonical title: Bengaluru Traffic Violations Data
- Domain: Traffic/Mobility
- Publisher in canonical CSV: Bengaluru Traffic Police (via OpenCity; also btp.gov.in)
- Publisher aliases: Bengaluru Traffic Police; Bengaluru Traffic Department; btm.gov.in
- Publisher URL: `https://btp.gov.in`
- Dataset URL: `https://data.opencity.in/dataset/bwssb-data`
- Download URL: `Unknown CSV`
- License: `Other (Public Domain) / Open Data`
- `license_verified`: `false`
- Format: CSV
- Temporal coverage: `2011-2025 (Resource 1); 2016-18; 2018-2025`
- Spatial coverage: Bengaluru
- Geographic granularity: City
- Record count: UNKNOWN
- File size: UNKNOWN
- Research status: VERIFIED
- Source reliability: HIGH
- Notes: Conditional to KEEP upgrade (C-04): city-wide aggregate only; multi-resource dataset.
- Conflict C-04 is directly relevant: the earlier CONDITIONAL review said keep only
  if enforcement-trend correlation with TRF-004 is a defined use case.

#### CIT-001 — BBMP Grievances Data
- Canonical title: BBMP Grievances Data (ward-level, 2020-2025)
- Domain: Citizen Services
- Publisher in canonical CSV: BBMP (via OpenCity)
- Publisher aliases: BBMP; Bengaluru Bruins
- Publisher URL: `https://bbmp.gov.in`
- Dataset URL: `Unknown BBMP source`
- Download URL: `Unknown CSV`
- License: `Other (Public Domain) / Open Data`
- `license_verified`: `false`
- Format: CSV
- Temporal coverage: 2020-2025
- Spatial coverage: Bengaluru
- Geographic granularity: Ward
- Record count: UNKNOWN
- File size: UNKNOWN
- Research status: ACQUIRED
- Source reliability: HIGH
- Notes: One of 6 yearly CSVs fetched, truncated by tool output (C-02).
- Important: historical ACQUIRED claim is not local evidence. Repository-local
  axis 2 is still metadata only.

#### TRF-001 — Traffic Accidents in India (Smart Cities)
- Canonical title: Traffic Accidents in India (Smart Cities)
- Domain: Traffic/Mobility
- Publisher in canonical CSV: Smart Cities Mission (via OpenCity)
- Publisher aliases: Smart Cities Mission; Ministry of Housing & Urban Affairs
- Publisher URL: `https://mohua.gov.in`
- Dataset URL: `https://data.opencity.in/dataset/traffic-accidents-in-india`
- Download URL: empty
- License: `Other (Public Domain) / Open Data`
- `license_verified`: `false`
- Format: CSV
- Temporal coverage: 2016-2018
- Spatial coverage: 8 Indian cities
- Geographic granularity: City
- Record count: UNKNOWN
- File size: UNKNOWN
- Research status: VERIFIED
- Source reliability: MEDIUM
- Notes: GODL-India vs portal-generic licence unresolved (C-07).
- Existing handler: `Trf001Ingestor` exists, but licence remains unverified and
  the resource URL provenance explicitly says endpoint reachability is not proof
  of intended dataset identity.

### 2.3 Contradictions and cautions between documents

- The canonical CSV says TRF-005 dataset URL is `bwssb-data`, which is a Bengaluru
  Water Supply and Sewerage Board-themed path, even though the publisher and title
  are Bengaluru Traffic Police. This is a recorded inconsistency worth treating as
  a provenance flag, not something to silently reinterpret.
- CIT-001 `dataset_url` is `Unknown BBMP source` in the canonical CSV, so the
  canonical record does not yet carry a verified BBMP dataset page URL.
- The repository already separates source claims from local evidence, and the
  licence flag is explicitly `false` for all four candidates.

---

## 3. Official source verification table

Evidence standard:
- **Documented** = stated on a page inspected for this report.
- **Secondary** = stated by a re-publisher or analysis source, not by the publisher itself.
- **UNVERIFIED / NOT DOCUMENTED** = not established by the sources inspected.

### 3.1 TRF-004 — Bengaluru Road Crashes Data

| Field | Evidence | Source level |
|---|---|---|
| Dataset title | Bengaluru Road Crashes Data | Secondary (OpenCity) |
| Publisher | Bengaluru Traffic Police (BTP) | Secondary (OpenCity) |
| Official publisher page | `https://btp.karnataka.gov.in/en` and Accident Statistics page `https://btp.karnataka.gov.in/231/accident-statistics/en` | Documented (publisher site) |
| Dataset page | `https://data.opencity.in/dataset/bengaluru-road-crashes-data` | Secondary (OpenCity) |
| Download access | OpenCity lists CSV resources, including station-wise files for 2018–20, 2020–22, 2023; city totals for 2024; a 2007–25 total series; and station-wise 2025 totals. One resource page describes a station-wise crashes/fatalities CSV | Secondary (OpenCity), not downloaded here |
| Licence stated on resource page | Resource metadata labels CSV "Other (Public Domain)" / "Public Domain" | Secondary (OpenCity metadata) |
| Publisher reuse terms | BTP site copyright policy says republishing information requires prior permission from CeG or the content-owning authority and attribution | Documented (publisher site copyright policy) |
| Geography | Bengaluru | Documented (OpenCity + BTP) |
| Spatial granularity | Mixed: some resources station-wise, some city totals | Documented (OpenCity resource descriptions) |
| Time coverage | OpenCity: station-wise 2018–20, 2020–22, 2023; city totals 2024; city total series 2007–25; station-wise 2025 totals. BTP official: historic annual series from 1976; monthly station-jurisdiction analytics from Jan 2018 | Documented (OpenCity + BTP) |
| Schema | No field-level dictionary on the OpenCity resource page inspected. BTP official annual tables show Year, Total Accidents, Fatal, Killed, Non Fatal, Injured | Partially documented; CSV columns NOT DOCUMENTED here |
| Stable station identifier | Not documented in the resource documentation reviewed | NOT DOCUMENTED |
| Update frequency | Not clearly documented as a single release cadence; multiple yearly resources exist | TBD |

Key limitation: "station-wise" is a description of grouping, not proof of a stable
machine-readable station key in the CSV.

### 3.2 TRF-005 — Bengaluru Traffic Violations Data

| Field | Evidence | Source level |
|---|---|---|
| Dataset title | Bengaluru Traffic Violations Data | Secondary (OpenCity) |
| Publisher | Bengaluru Traffic Police (BTP) | Secondary (OpenCity) |
| Official publisher page | Enforcement Statistics page `https://btp.karnataka.gov.in/152/statistics/en` | Documented (publisher site) |
| Dataset page | `https://data.opencity.in/dataset/bengaluru-traffic-violations-data` | Secondary (OpenCity) |
| Download access | OpenCity lists CSV resources; principal resource titled "BTP - Cases and fines collected under various acts (2011-2025)" with a CSV link; also drink-and-drive and M.V. Act resources | Secondary (OpenCity), not downloaded here |
| Licence stated on resource page | Resource metadata labels CSV "Other (Public Domain)" | Secondary (OpenCity metadata) |
| Publisher reuse terms | BTP site copyright policy requires prior permission for republishing information and attribution | Documented (publisher site copyright policy) |
| Geography | Bengaluru | Documented (OpenCity + BTP) |
| Spatial granularity | Principal CSV described as cases/fines by year, i.e. aggregate by year, not location-level event data in the described principal resource | Documented (OpenCity resource description) |
| Time coverage | Principal resource 2011–2025; other resources 2016–18 and 2018–25; BTP official annual figures 2019 onward; station analytics from Jan 2020 | Documented (OpenCity + BTP) |
| Schema | No field-level dictionary on the OpenCity resource page inspected. BTP official tables show categories such as year, cases by act, total cases, fines by act, total fine amount | Partially documented; CSV columns NOT DOCUMENTED here |
| Stable station identifier | Not documented for the principal annual CSV | NOT DOCUMENTED |
| Update frequency | Annual series likely; exact cadence not documented here | TBD |

Key limitation: the principal described resource is a year-level cases/fines series.
If that is the file used, cross-source joins to station-level crashes become weaker
and the integration design must match that granularity.

### 3.3 CIT-001 — BBMP Grievances Data

| Field | Evidence | Source level |
|---|---|---|
| Dataset title | BBMP Grievances Data | Secondary (OpenCity) |
| Publisher | BBMP | Secondary (OpenCity) |
| Official publisher page | `bbmp.gov.in` and `site.bbmp.gov.in` timed out during review; BBMP-hosted public bulk download portal NOT DOCUMENTED here | UNVERIFIED |
| Dataset page | `https://data.opencity.in/dataset/bbmp-grievances-data` | Secondary (OpenCity) |
| Download access | OpenCity lists yearly CSV resources; 2025 resource has a CSV link; 2024 resource also documents CSV access | Secondary (OpenCity), not downloaded here |
| Licence stated on resource page | Resource metadata labels CSV "Other (Public Domain)" / "Public Domain" | Secondary (OpenCity metadata) |
| Publisher reuse terms | BBMP-specific data reuse terms NOT DOCUMENTED here; Karnataka app-store Sahaaya page has general portal copyright-policy language requiring permission for republication | UNVERIFIED / secondary |
| Geography | Bengaluru | Documented (OpenCity) |
| Spatial granularity | Described as ward-level grievances; 2025 preview shows individual complaint records with a Ward Name field | Documented (OpenCity preview) |
| Time coverage | 2020 (from 8 Feb 2020), 2021, 2022, 2023, 2024, 2025 through 19 Jun 2025 | Documented (OpenCity) |
| Schema | 2025 preview documents: `_id`, Complaint ID, Category, Sub Category, Grievance Date, Ward Name, Grievance Status, Staff Remarks, Staff Name, colspacer | Documented for 2025 preview only |
| Stable ward identifier | Ward Name shown; no ward code or stable ward ID documented | NOT DOCUMENTED |
| Privacy-sensitive fields | 2025 preview includes Complaint ID, Staff Remarks, Staff Name | Documented for 2025 preview only |

Key limitation: ward is represented by name in the preview. If later files vary,
ward name alone is a weak join key and should not be assumed stable without evidence.

### 3.4 TRF-001 — Traffic Accidents in India (Smart Cities)

| Field | Evidence | Source level |
|---|---|---|
| Dataset title | Traffic Accidents in India (Smart Cities) | Secondary (OpenCity) |
| Publisher | Smart Cities Mission / Ministry of Housing & Urban Affairs, via OpenCity mirror | Secondary (OpenCity) |
| Dataset page | `https://data.opencity.in/dataset/traffic-accidents-in-india` | Secondary (OpenCity) |
| Download access | OpenCity resource path exists; repository’s existing handler cites a specific resource URL and recorded a bounded endpoint check on 2026-10-11 | Secondary + repository endpoint check only |
| Licence stated on resource page | OpenCity metadata label "Other (Public Domain) / Open Data" | Secondary (OpenCity metadata) |
| Publisher reuse terms for this dataset | Not verified here; conflict C-07 remains unresolved | UNVERIFIED |
| Geography | 8 Indian cities | Documented (OpenCity) |
| Time coverage | 2016-2018 | Documented (OpenCity) |
| Schema | Partial data dictionary only | NOT DOCUMENTED fully |
| Stable join key | Not applicable for the intended Bengaluru station/ward comparison | N/A |

Key limitation: TRF-001 is 8-city and 2016–2018, so it is not a strong match for a
Bengaluru station/ward comparison with TRF-004/TRF-005 unless the research question
is widened to multi-city city-level comparison, which is a different experiment.

---

## 4. Licence and intended-use assessment

### 4.1 Current licence flag for every candidate

- TRF-004: `license_verified=false`
- TRF-005: `license_verified=false`
- CIT-001: `license_verified=false`
- TRF-001: `license_verified=false`

### 4.2 Authoritative evidence available for licence assessment

For all four candidates, the only licence evidence inspected here is the re-publisher
metadata label "Other (Public Domain)" / "Public Domain" on OpenCity resource pages.

For TRF-004 and TRF-005, the publisher site (BTP) shows a copyright policy that
requires prior permission for republishing information and asks for attribution.

For CIT-001, BBMP-specific reuse terms were not documented in the sources inspected.

### 4.3 Intended-use assessment

Intended use for the first experiment:
- internal research and pipeline development
- structural validation and profiling
- descriptive comparison and evidence-bounded analysis
- recording provenance for every used artifact and statistic
- not republishing raw source data unless permission is established

Assessment:
- The intended research/analysis use is plausible for publicly available government
  statistics, but the repository’s own evidence standard is stricter than "it was
  reachable and labelled public domain by a mirror."
- For TRF-004 and TRF-005, reuse permission is **unresolved** between the OpenCity
  label and the BTP copyright policy. The decisive question is whether the intended
  use — especially any downstream sharing, publication, or redistribution of derived
  outputs that rest on the raw data — requires explicit BTP permission or clarification.
- For CIT-001, reuse permission is **unresolved** because no BBMP licence was documented.
- For TRF-001, reuse permission is **unresolved** because conflict C-07 is still open
  and the mirror label is not publisher confirmation.

### 4.4 Attribution and redistribution

- Attribution is likely expected for all three Bengaluru candidates under normal
  government statistics reuse practice, and BTP explicitly mentions acknowledgment.
- Redistribution or publication of raw data is not established by the sources reviewed.
- Any project decision to share outputs publicly should be made after the responsible
  decision-maker reviews the publisher terms and the intended output form.

### 4.5 Status of licence for this milestone

Because no authoritative publisher licence statement was verified here:
- TRF-004: licence unresolved
- TRF-005: licence unresolved
- CIT-001: licence unresolved
- TRF-001: licence unresolved

The licence flag remains `license_verified=false` for all four, and this report does
not change that.

---

## 5. Geography, time coverage, and schema compatibility

### 5.1 Common geography

- TRF-004 and TRF-005: Bengaluru, but with mixed granularity.
- CIT-001: Bengaluru ward-level.
- TRF-001: 8 Indian cities, city-level.

Compatibility assessment:
- TRF-004 and TRF-005 are the best geographic match for each other because both are
  Bengaluru traffic police sources.
- However, the open question is whether the usable TRF-004 resource and the usable
  TRF-005 resource share a comparable spatial unit. That is not yet evidenced.
- CIT-001 is ward-level and uses ward name in the previewed schema, so it does not
  automatically join to station-wise data without a verified mapping.

### 5.2 Time coverage compatibility

- TRF-004: strong multi-year coverage, including station-wise recent years and a
  long city-level series.
- TRF-005: long coverage for the principal annual series, plus separate resource windows.
- CIT-001: 2020–2025, which overlaps with recent TRF-004/TRF-005 windows.
- TRF-001: 2016–2018 only, which limits overlap with current Bengaluru station-level work.

Best temporal overlap for the recommended experiment:
- TRF-004 + TRF-005, using the years/resources where both are available and comparable.

### 5.3 Schema compatibility

- TRF-004: expected crash/fatality/injury data; exact CSV schema not confirmed here.
- TRF-005: expected cases/fines by year and offence category; exact CSV schema not
  confirmed here; principal resource is likely aggregate by year.
- CIT-001: grievance records with category, sub-category, date, ward name, status, and
  possible privacy-sensitive fields in the 2025 preview.
- TRF-001: partial dictionary; only some columns measurable.

Most defensible schema story for the recommended path:
- TRF-004 gives an outcome measure with some location/time breakdown.
- TRF-005 gives an enforcement measure, likely by year and offence category.
- Their shared analysis axis is likely **time**, and possibly **Bengaluru-level or
  station/jurisdiction-level** if the actual files support it.
- Ward-level integration with CIT-001 is not yet defensible because the join key is
  not verified.

### 5.4 Missing values, duplicates, and data-quality risks

Expected risks before seeing the files:
- Mixed granularity across resources can create apparent trends that are really
  aggregation changes.
- Station/jurisdiction labels can change or be spelled inconsistently.
- Ward name in grievance data may be unstable or informal.
- CIT-001 preview includes fields that may be privacy-sensitive (staff remarks, staff
  name, complaint ID), so the integration design and any later sharing must be reviewed.
- Duplicate rows, ragged rows, parse errors, and missing values are all plausible and
  must be treated as evidence, not silently cleaned.

---

## 6. Primary research question and minimum viable dataset combination

### 6.1 Recommended minimum viable combination

Primary combination:
- TRF-004 + TRF-005

Reason:
- Both are Bengaluru traffic police sources.
- They can support a descriptive comparison of crash outcomes and enforcement signals.
- They avoid the weakest link in the larger three-dataset design: an unverified
  ward-level join key.

### 6.2 Primary research question

Primary question:
- In Bengaluru, how do reported road crashes and traffic-violation enforcement
  patterns compare over time and across the geography each source actually supports,
  using only the evidence in the acquired and validated artifacts?

This is deliberately descriptive and evidence-bounded. It does not claim that
enforcement causes crashes, reduces crashes, or explains grievances.

Sub-questions that remain defensible if the data supports them:
- Which years or months show the highest crash counts in TRF-004?
- Which years show the highest cases/fines in TRF-005?
- Do crash and enforcement series show similar temporal direction over overlapping years?
- What geographic unit is actually usable from each file: station, jurisdiction, zone, or city?

### 6.3 What is supported and what is not

Supported, if the files confirm expectations:
- descriptive comparison of time series
- comparison of geographic aggregation levels actually present
- data-quality profiling and validation as first-class outputs

Not supported without additional evidence:
- causal claims about enforcement impact
- station-to-ward integration without a verified mapping
- ward-level join using ward name as if it were a stable key
- city-level generalization from a single resource with unknown internal geography

---

## 7. Integration schema map and data flow

### 7.1 Minimum schema map

This map is proposed, not asserted from actual files.

| Source dataset | Source field (expected) | Canonical concept | Data type | Transformation / normalization | Geographic key | Temporal key | Missing-value policy | Validation rule | Provenance requirement |
|---|---|---|---|---|---|---|---|---|---|
| TRF-004 | date or year | event time | date/year | normalize to one calendar grain before comparison | station/jurisdiction/city as present | date or year | keep unknown as unknown; report | date parseable; grain explicit | artifact version, SHA-256, acquired_at, source_uri, validation scope |
| TRF-004 | location label | location | text | preserve verbatim; do not infer ward membership | station/jurisdiction/city as present | — | treat missing/ambiguous as missing | report distinct label count and ragged rows | same |
| TRF-004 | crash count / fatal / injured | outcome measure | integer/unknown | keep raw counts separate from derived rates | depends on file | depends on file | do not impute | validate numeric parse where expected; flag mismatches | same |
| TRF-005 | year | event time | year | align to TRF-004 grain if comparison is intended | year-level unless file has finer geography | year | keep unknown as unknown | year parseable; grain explicit | same |
| TRF-005 | offence category | enforcement category | text | standardize only with documented mapping, else keep original | if present | year | keep original if not mapped | report category coverage and mapping coverage | same |
| TRF-005 | cases / fines | enforcement measure | integer/unknown | keep raw values separate from derived rates | depends on file | year | do not impute | validate numeric parse where expected | same |
| CIT-001 | grievance date | event time | date | normalize to month/year for comparison | ward name as present | date/month/year | keep unknown as unknown | date parseable; grain explicit | same |
| CIT-001 | ward name | location | text | treat as text label, not stable ward ID unless verified | ward name only | — | treat missing/ambiguous as missing | report distinct ward names; flag instability | same |
| CIT-001 | category / sub-category | complaint type | text | keep original unless documented taxonomy exists | — | — | keep original if not mapped | report category coverage | same |
| CIT-001 | grievance status | status | text | keep original unless documented mapping exists | — | — | keep unknown as unknown | report status coverage | same |

Critical rule: no station-to-ward join key is introduced unless a verified mapping
document exists. If none exists, the integration layer must keep TRF-004/TRF-005 and
CIT-001 spatially separate and relate them only through explicitly documented common
geography or time aggregates, with a limitation note.

### 7.2 Proposed data flow

1. Authorization + licence/source assessment
   - explicit human authorization for the intended use
   - license/intended-use reviewed and recorded, or explicitly flagged unresolved
2. Ingestion
   - acquire through the existing `DatasetIngestor` contract
   - use existing stream download, redirect refusal, size/timeout limits, atomic
     promotion, and overwrite protection
3. Structural validation
   - existing handler validation pattern: existence, non-empty, encoding, strict CSV
     parse, header checks, size/checksum mismatch checks where applicable
   - schema is not asserted beyond what is documented; state that explicitly
4. Profiling
   - profile each artifact: row/column counts, missing %, duplicates, parse warnings
   - record profiling state and scope; never imply validation from profiling
5. Normalization
   - normalize only with documented rules
   - keep raw values available; expose normalized values with provenance
6. Integration or comparison
   - join only on evidenced keys
   - otherwise compare at the finest shared geography/time grain each source supports
   - attach per-row/per-figure confidence notes
7. Non-LLM baseline analysis
   - descriptive counts, time series, and coverage tables with provenance footnotes
   - data-quality summary first
8. Evidence store
   - record artifact, validation, and profiling events
   - record authorization rationale and resource provenance
   - keep claims and measurements separated
9. Future RAG/recommendation workflow
   - retrieval over evidence records and provenance
   - citation of source page, acquisition event, validation state, and profiling scope
   - explicit unsupported-claim flagging

This flow reuses the existing project terminology and components: `DatasetIngestor`,
`AcquisitionResult`, `ValidationReport`, `QualityIssue`, `ProvenanceRecord`,
`CanonicalDatasetRecord`, the four-axis model, `EvidenceStore`, and the CLI/`pilot`
pattern where applicable.

---

## 8. Research contribution and evaluation plan

### 8.1 Practical first contribution

The first contribution should be framed as:
- a reproducible, evidence-bounded descriptive integration of two Bengaluru traffic
  police sources
- with explicit handling of mixed granularity, missing data, and unverified join keys
- and with provenance and validation status attached to every used figure

That is more defensible than claiming a large multi-source fusion result.

### 8.2 Measurable metrics that can be assessed now

Metrics available from the repository pattern and the planned analysis:
- artifact validation pass/fail rate
- profiling completeness: how much of each artifact is profiled
- missing-value rate per important field
- duplicate/ragged-row/parse-error rate per artifact
- integration coverage: fraction of records that can be compared under an evidenced
  join or aggregation
- unresolved-key rate: fraction of records that cannot be linked because the key is
  missing or unverified
- provenance completeness: fraction of used figures traceable to an artifact + evidence
  record

### 8.3 Metrics requiring future implementation or labelled data

- evidence-retrieval precision/recall: requires a labelled test set over the evidence layer
- recommendation factual-support rate: requires a defined output format and evaluation rubric
- unsupported-claim/hallucination rate: requires a defined generation/recommendation step
  and human or gold-standard review
- end-to-end latency: requires the retrieval/recommendation components to exist

### 8.4 Baseline comparison

Baseline:
- deterministic descriptive analysis over validated artifacts only
- counts, time series, coverage tables, and data-quality summary

Enhanced version, later:
- retrieval + reasoning over the same evidence
- compare on citation completeness, factual grounding, and unsupported-claim rate,
  not on apparent sophistication

### 8.5 What should not be claimed yet

- do not claim novelty from joining CSVs alone
- do not claim improved municipal truth
- do not claim licence permission from mirror labels or accessibility
- do not claim causal effects from descriptive traffic data

---

## 9. Exact acquisition prerequisites

For each candidate, the prerequisites below must be satisfied before acquisition in
this project. They are ordered by dependency, not by preference.

### 9.1 Shared prerequisites for any candidate

1. Explicit authorization for the intended use.
2. Licence/intended-use assessment recorded, or explicit decision that the unresolved
   state is acceptable for the scoped internal research use only.
3. Exact resource URL verified against the publisher or dataset page before acquisition.
4. Validation expectations documented before ingestion.
5. Evidence capture: byte size, SHA-256, acquisition timestamp, provenance, validation
   state, and profiling scope.

### 9.2 TRF-004 prerequisites

- Confirm the exact resource URL for the intended resource from the OpenCity dataset page.
- Decide which resource is intended: station-wise vs city totals.
- Record BTP source page and the OpenCity dataset page as provenance.
- Record licence as unresolved unless/until publisher terms are reviewed and documented.
- Decide the geographic grain to use before analysis, because the resource set includes
  both station-wise and city-level files.

Acquisition readiness:
- `BLOCKED_BY_SOURCE_IDENTITY` for the exact intended resource URL, until it is re-captured
  from the dataset page.
- `BLOCKED_BY_LICENCE_OR_PERMISSION` for intended reuse/publication, pending BTP/OpenCity
  clarification.
- Decisive blocker for acquisition: source-identity + licence/intended-use resolution.

### 9.3 TRF-005 prerequisites

- Confirm the exact resource URL from the OpenCity dataset page.
- Decide whether the intended comparison uses the annual cases/fines series or a finer
  resource, because the principal described resource is year-level.
- Record BTP source page and OpenCity dataset page as provenance.
- Record licence as unresolved unless publisher terms are reviewed and documented.
- If the comparison depends on geography, confirm whether any TRF-005 resource has a
  usable location field beyond year.

Acquisition readiness:
- `BLOCKED_BY_SOURCE_IDENTITY` for the exact intended resource URL.
- `BLOCKED_BY_DATA_COMPATIBILITY` if the experiment expects station-level geography but
  the usable resource is year-level aggregate.
- `BLOCKED_BY_LICENCE_OR_PERMISSION` for intended reuse/publication.
- Decisive blocker: exact resource + intended grain + licence/intended-use resolution.

### 9.4 CIT-001 prerequisites

- Confirm the exact dataset page and resource URLs from OpenCity.
- Confirm whether BBMP publishes a public bulk download endpoint directly.
- Confirm whether the yearly CSVs share the previewed schema.
- Confirm whether `Ward Name` can be mapped to a stable ward code/boundary source.
- Review privacy-sensitive fields before any use beyond internal research.
- Record licence as unresolved unless BBMP terms are documented.

Acquisition readiness:
- `BLOCKED_BY_SOURCE_IDENTITY` because canonical `dataset_url` is `Unknown BBMP source`.
- `BLOCKED_BY_DATA_COMPATIBILITY` for ward-level integration unless a verified ward mapping
  and stable identifier exist.
- `BLOCKED_BY_LICENCE_OR_PERMISSION` for intended reuse/publication.
- Decisive blocker for CIT-001 integration use: ward identifier/mapping + licence resolution.

### 9.5 TRF-001 prerequisites

- Resolve conflict C-07 with authoritative licence evidence.
- Verify intended dataset identity beyond the endpoint check.
- Decide whether the 8-city, 2016–2018 scope suits the experiment.
- Do not acquire first; it is a fallback only.

Acquisition readiness:
- `BLOCKED_BY_LICENCE_OR_PERMISSION`
- `BLOCKED_BY_SOURCE_IDENTITY` for intended-resource confirmation beyond reachability
- `NEEDS_HUMAN_DECISION` before acquisition

---

## 10. Fallback plan

Fallback order:

1. TRF-004 + TRF-005 at the shared documented level
   - if station-level geography is usable in both, compare at that level
   - if only year-level enforcement data is usable, compare TRF-004 and TRF-005 as
     time series with explicit geography notes
2. Single-dataset analysis
   - if cross-source comparison is not defensible, analyze TRF-004 alone or TRF-005 alone
     with full provenance and profiling
3. Pune alternative
   - only if the Bengaluru candidates cannot support a useful experiment; WST-003 + CIT-003
     with ward metadata is the Pune fallback pair from Milestone 6B
4. TRF-001
   - only after source identity and licence situation are assessed and the experiment is
     redefined around multi-city city-level comparison

The recommended safest fallback for the fastest viable experiment is:
- TRF-004 + TRF-005 descriptive comparison with explicit geography and grain, even if that
  comparison turns out to be Bengaluru-level or year-level rather than station-to-ward.

---

## 11. Prioritized next steps

### 11.1 Before acquisition, in order

1. Decide the intended TRF-004 resource and the intended TRF-005 resource.
2. Re-capture the exact resource URLs from the OpenCity dataset pages and record them as
   provenance candidates.
3. Review BTP publisher terms and any OpenCity licence/audit page relevant to the intended use.
4. Decide whether any downstream sharing/publication is intended; if so, treat licence
   resolution as mandatory before that step.
5. For CIT-001, confirm whether a stable ward identifier/mapping exists before using it as a
   join anchor.
6. Document validation expectations for each chosen resource.
7. Only then scope handler work for the authorized, licence-assessed source(s).

### 11.2 After source/licence confirmation, in order

8. Acquire the first authorized source with full provenance capture.
9. Validate and profile; publish data-quality results before integration.
10. Build the comparison at the evidenced grain.
11. Write the non-LLM baseline before any retrieval/reasoning layer.

### 11.3 Output to produce next

- A short authorized-source list with exact resource URLs and provenance citations.
- A validation/profiling expectation checklist per resource.
- Either a verified ward-mapping decision, or an explicit decision to keep ward data
  separate.

---

## Final recommendation

Use **TRF-004 + TRF-005** as the first CivicMind integration experiment, framed as a
Bengaluru descriptive public-safety comparison at the finest geography and time grain each
source actually supports.

Do not anchor the experiment on CIT-001 unless a stable ward identifier and verified mapping
exist. Do not acquire TRF-001 first; it remains an unresolved-licence fallback.

The fastest next action is not implementation or download: it is **confirming the exact
resource URLs from the OpenCity dataset pages and resolving the licence/intended-use question
for the BTP sources**, because those two items decide whether the experiment is responsibly
ready to acquire at all.

Report path: `docs/datasets/acquisition_readiness_report.md`

Git status after this report:
- branch `main`
- HEAD `7bf8275c0282a395f6132f9d60c36948c9fb830f`
- one new untracked file: `docs/datasets/acquisition_readiness_report.md`
- nothing staged, nothing committed, nothing pushed
