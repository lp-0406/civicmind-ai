# Milestone 6B — Multi-Source Dataset Selection and Integration Readiness

Status: research and data-selection plan only.
Repository baseline used for this plan:
- Branch: `main`
- HEAD: `7bf8275c0282a395f6132f9d60c36948c9fb830f`
- Working tree: clean
- Verified this session via `git rev-parse HEAD`, `git branch --show-current`,
  `git status --short`, and `git ls-remote origin refs/heads/main`.

Nothing in this document modifies code, tests, documentation, or the canonical
metadata CSV. No dataset was downloaded, and no network API was called during
this planning task.

---

## 1. Inventory gap summary

### 1.1 What is already catalogued

The canonical inventory in `configs/datasets/canonical_metadata.csv` contains
21 dataset IDs:

- Traffic/Mobility: `TRF-001` … `TRF-005`
- Waste Management: `WST-001` … `WST-003`
- Water: `WTR-001` … `WTR-005`
- Environment: `ENV-001` … `ENV-004`
- Citizen Services: `CIT-001` … `CIT-004`

Current canonical metadata is strongest for:
- publisher portal URLs
- research_status and source_reliability narratives
- qualitative coverage notes and conflict register entries

Current canonical metadata is weakest for:
- local acquisition evidence
- verified licences
- concrete schemas and join keys
- measured sizes and record counts for many IDs

### 1.2 Artifacts versus metadata only

Local repository state is metadata only for every ID.

Evidence:
- `configs/datasets/canonical_metadata.csv` records TRF-001 as
  `license_verified=false`, `record_count=UNKNOWN`, `file_size=UNKNOWN`, and an
  empty `download_url`.
- The audit document explicitly states that no acquired artefact exists in this
  workspace and that repository-local axis 2 for all 21 IDs is `METADATA_ONLY`.
- The repository still contains only `.gitkeep` placeholders under `data/`.

Historical acquisition claims exist for some IDs, but those are documented
history, not local evidence.

### 1.3 Datasets with unresolved licence or source issues

- TRF-001 and TRF-002: GODL-India vs portal-generic licence wording is unresolved
  (conflict C-07). `license_verified=false`.
- WST-001: Conditional on dataset eligibility axis, with source replacement recorded
  separately. PDF-centric, not CSV-first.
- WST-002: Rejected; bot-detection and low decision value noted.
- WTR-001: Superseded planning record (`REPLACE` → WTR-005). Not a download target.
- WTR-002: Rejected; CSV resources broken at source.
- WTR-004: Conditional; no accessible path found in prior passes.
- WST-001/WTR-004/ENV-001 family: access or format blockers remain.
- CIT-004: Subscription-dependent; rejected.
- ENV-001: Blocked until a real data.gov.in API call succeeds.

### 1.4 Complementary coverage already present

The strongest complement opportunities in the existing inventory are:

- Bengaluru traffic domain:
  - TRF-004 (road crashes, station-wise, 2007-2025)
  - TRF-005 (traffic violations, multi-resource)
- Bengaluru civic-services domain:
  - CIT-001 (BBMP grievances, ward-level, 2020-2025)
- Pune civic-services / waste domain:
  - WST-003 (Pune solid waste, ward/zone-wise, 2018-2022)
  - CIT-003 (Pune property tax, ward-wise, FY 2018-19)

### 1.5 Constraints that must be preserved

- No dataset is acquired in this task.
- TRF-001 remains a candidate with `license_verified=false`.
- Licence status is updated only when supported by authoritative evidence.
- Public download links do not constitute licence permission.
- Local state advances only on measured evidence, not on source claims.
- The canonical metadata CSV is not changed here.

---

## 2. Candidate dataset comparison table

All candidate assessments below are planning-level and evidence-bounded. Where
the authoritative source documentation is not yet consulted, the field is marked
`UNVERIFIED` or `TBD`, and the gap is stated explicitly.

### 2.1 Existing inventory candidates under consideration

#### TRF-004 — Bengaluru Road Crashes Data (station-wise, 2007-2025)

- Dataset and publisher: Bengaluru Road Crashes Data; Bengaluru Traffic Police
  (via OpenCity).
- Official source: dataset page `https://data.opencity.in/dataset/bengaluru-road-crashes-data`
  and publisher portal `https://btp.gov.in` as recorded in the canonical CSV.
- Data access: CSV per canonical metadata; exact resource URL not re-captured.
- Licence: `Other (Public Domain) / Open Data` in canonical CSV; `license_verified=false`.
- Geography: Bengaluru.
- Time coverage: 2007-2025.
- Schema: station-wise crash records expected; exact columns not confirmed in repo.
- Integration value: primary traffic-injury/fatality signal for a Bengaluru
  road-safety vertical; complements TRF-005 violations and CIT-001 complaints.
- Limitations: download URL not re-captured; schema not confirmed; station
  geography may require a station-to-location mapping that is not currently in
  the repository.
- Acquisition readiness: `NEEDS HUMAN DECISION` — only after the resource URL is
  re-captured and licence/source terms are assessed.

#### TRF-005 — Bengaluru Traffic Violations Data

- Dataset and publisher: Bengaluru Traffic Violations Data; Bengaluru Traffic
  Police (via OpenCity; also btp.gov.in).
- Official source: dataset page `https://data.opencity.in/dataset/bwssb-data`
  as recorded in the canonical CSV; publisher portal `https://btp.gov.in`.
- Data access: CSV, multi-resource.
- Licence: `Other (Public Domain) / Open Data`; `license_verified=false`.
- Geography: Bengaluru.
- Time coverage: `2011-2025 (Resource 1); 2016-18; 2018-2025` per canonical CSV.
- Schema: multi-resource; exact fields not confirmed in repo.
- Integration value: enforcement-signal complement to crash data; potential
  temporal correlation with road crashes and complaints.
- Limitations: city-wide aggregate caveat from earlier CONDITIONAL review still
  matters; multi-resource handling adds complexity; licence unverified.
- Acquisition readiness: `NEEDS HUMAN DECISION`.

#### CIT-001 — BBMP Grievances Data (ward-level, 2020-2025)

- Dataset and publisher: BBMP Grievances Data; BBMP (via OpenCity).
- Official source: publisher portal `https://bbmp.gov.in` and OpenCity dataset
  page referenced in canonical metadata; exact source URL recorded as `Unknown BBMP source`.
- Data access: CSV, ward-level, multiple years.
- Licence: `Other (Public Domain) / Open Data`; `license_verified=false`.
- Geography: Bengaluru wards.
- Time coverage: 2020-2025.
- Schema: yearly CSVs expected; exact columns not confirmed in repo; prior note
  says one of 6 yearly CSVs was fetched but truncated in another sandbox.
- Integration value: municipal service-demand signal at ward level; joins with
  ward geometry/metadata and complements traffic/complaints analysis.
- Limitations: exact source URL not re-captured; schema needs confirmation;
  historical acquisition is not local evidence.
- Acquisition readiness: `NEEDS HUMAN DECISION`.

#### WST-003 — Pune Solid Waste Management Data (ward/zone-wise, 2018-2022)

- Dataset and publisher: Pune Solid Waste Management Data; Pune Municipal
  Corporation (via OpenCity + PMC portal).
- Official source: dataset page `https://data.opencity.in/dataset/pune-solid-waste-management-data`
  and publisher portal `https://pmc.gov.in` per canonical CSV.
- Data access: CSV, ward/zone-wise.
- Licence: `Other (Public Domain) / Open Data`; `license_verified=false`.
- Geography: Pune.
- Time coverage: 2018-2022.
- Schema: segregation and related waste-management figures expected; exact columns
  not confirmed in repo.
- Integration value: service-operation signal for a Pune vertical; could pair with
  property tax and ward metadata.
- Limitations: exact download URL not re-captured; schema not confirmed;
  historical acquisition is not local evidence.
- Acquisition readiness: `NEEDS HUMAN DECISION`.

#### CIT-003 — Pune Property Tax Collections (ward-wise, FY 2018-19)

- Dataset and publisher: Pune Property Tax Collections; Pune Municipal Corporation
  (via OpenCity).
- Official source: publisher portal `https://pmc.gov.in` per canonical CSV; exact
  source recorded as `Unknown PMC source`.
- Data access: CSV, ward-wise.
- Licence: `Other (Public Domain) / Open Data`; `license_verified=false`.
- Geography: Pune wards.
- Time coverage: FY 2018-19.
- Schema: documented notes mention residential property count, Annual Rateable
  Value, original demand, penalty amount, increased demand, amount collected, and
  percentage collection efficiency per ward/Sampark office.
- Integration value: fiscal-capacity and service-correlation signal for Pune;
  good complement to waste-management and ward-based analysis.
- Limitations: exact source URL not re-captured; single fiscal year limits trend
  analysis; schema should be confirmed against the actual file.
- Acquisition readiness: `NEEDS HUMAN DECISION`.

### 2.2 New candidate domains worth researching before selection

These are not yet in the canonical inventory, so they should be researched
against authoritative publisher documentation before any commitment.

#### Bengaluru ward geometry / ward metadata

Likely value:
- enables ward-level joins across BBMP grievances, traffic, and civic services
- reduces the hardest integration risk in a Bengaluru vertical

What must be confirmed:
- authoritative publisher and page
- coverage, granularity, file format
- licence terms and link
- stable identifiers usable as join keys

Acquisition readiness:
- `UNVERIFIED` until source is confirmed.

#### Bengaluru traffic / road-safety supplementary sources

Possible complementary sources:
- traffic police notices or open data portals
- CMIS / Smart Cities Mission related datasets
- other Bengaluru mobility datasets already catalogued or discoverable

What must be confirmed:
- publisher and licence
- temporal and geographic alignment with crash/violations data
- whether records are station-level, ward-level, or city-level

Acquisition readiness:
- `UNVERIFIED` until source is confirmed.

#### CPCB air-quality historical datasets

Possible complementary sources:
- CPCB NAMP historical data
- CAAQMS open data where available
- state-level environmental portals

What must be confirmed:
- publisher and licence
- station geography
- temporal resolution and coverage
- whether it supports the chosen decision question or adds scope creep

Acquisition readiness:
- `BLOCKED` or `NEEDS HUMAN DECISION` depending on access path and licence.

### 2.3 Candidates to avoid for the first integration experiment

- Rejected IDs: WST-002, WTR-002, CIT-004.
- Superseded/blocked planning records: WTR-001, WTR-004.
- Conditional-with-hard-blockers: ENV-001, WST-001.
- Large/heavy tier IDs for a first vertical slice unless the question explicitly
  needs them: TRF-003, ENV-003, ENV-004, CIT-001 in full scale without chunking.

---

## 3. Recommended first integration experiment

### 3.1 Recommendation

Recommended set for the first vertical slice:
1. TRF-004 — Bengaluru Road Crashes Data
2. TRF-005 — Bengaluru Traffic Violations Data
3. CIT-001 — BBMP Grievances Data

Rationale:
- all three are Bengaluru-focused
- all three touch a coherent public-safety / civic-experience story
- crash data gives the outcome measure
- violations give an enforcement-signal complement
- grievances give a citizen-reported service-incident complement
- ward-level geography from CIT-001 can anchor the integration if crash/violations
  records can be mapped to ward or station contexts

If ward-level joins prove infeasible without reliable ward mapping, fall back to:
- TRF-004 + TRF-005 only, analyzed at station/city level
- or Pune vertical: WST-003 + CIT-003 with ward metadata

### 3.2 Decision question

Primary question:
- In Bengaluru, where do reported road crashes concentrate, and how does that
  concentration relate to observed traffic-violation patterns and citizen-reported
  grievances, given only the evidence each source actually supports?

This is deliberately scoped to evidence-supported comparison, not causal claim.

Sub-questions that can remain evidence-bounded:
- Which stations/areas show the highest crash counts in the available data?
- Which time windows show the strongest crash concentration?
- Do violation trends and complaint trends show similar temporal spikes?
- Which geographic aggregates are supportable from each source?

### 3.3 Required fields and join keys

Minimum required fields:
- Crash side: date, location identifier, crash count or record, severity/class if
  present
- Violations side: date, location or zone identifier, violation type, count if
  aggregated
- Grievances side: date, ward or location identifier, complaint category, status
  if present

Useful join keys:
- ward identifier, if all sources can be mapped to wards
- station/zone identifier for crash and violation data
- date or month for temporal alignment

Critical caveat:
- if TRF-004 is station-wise and CIT-001 is ward-wise, a station-to-ward mapping
  is a prerequisite for direct spatial joins. Without that mapping, integration
  should stay at a documented, explicitly coarser level.

### 3.4 Spatial and temporal alignment strategy

Temporal alignment:
- aggregate to a common period (month or year) depending on source granularity
- report the aggregation level explicitly
- avoid false precision when one source is annual and another is daily

Spatial alignment:
- prefer ward-level if a reliable ward mapping is available
- otherwise use the finest geography each source actually supports and keep the
  geography explicit in the report
- never infer ward membership from dataset titles or notes alone

### 3.5 Missing-data and duplicate handling

- Missing data: preserve unknowns as unknowns; never impute without stating the
  method and limiting the claim
- Duplicates: profile each source for duplicate rows and report them as evidence,
  not silently deduplicate
- Structural anomalies: treat ragged rows, parse errors, and empty fields as
  quality issues and carry them in the evidence trail

### 3.6 Provenance and confidence tracking

For every integrated figure:
- cite the source dataset ID, publisher, and acquisition record
- record byte size, SHA-256, acquisition timestamp, and validation state for any
  used artifact
- record profiling state and scope for any statistic
- attach a confidence note explaining what is measured, what is inferred, and what
  is still unknown

Confidence levels should be explicit, for example:
- measured and validated
- measured but not yet validated
- inferred from incomplete schema
- unknown

### 3.7 Baseline analysis that can be evaluated without an LLM

A non-LLM baseline can already evaluate:
- per-station or per-ward crash counts
- temporal histograms of crashes, violations, and complaints
- simple co-occurrence checks between spike periods
- descriptive comparison tables with provenance footnotes
- data-quality summary: missing percentages, duplicate counts, parse warnings

This baseline is useful because it establishes what the data actually supports
before any retrieval or reasoning layer is added.

### 3.8 How CivicMind's RAG or reasoning component could use the integrated evidence later

Later, a retrieval/reasoning layer could:
- retrieve the exact artifact and evidence record behind each figure
- surface the validation and profiling state alongside the answer
- attach citations to source pages, acquisition events, and quality issues
- restrict generated recommendations to claims supported by measured evidence
- flag when an answer relies on inferred or unknown fields

This should be framed as an evidence-fabrication-risk reduction layer, not as an
authority override.

---

## 4. Research novelty and evaluation plan

### 4.1 Where the contribution can be novel

The novelty is not "we joined three CSVs." The more publishable angle is:

- provenance-aware municipal evidence integration
- data-quality-aware evidence selection
- explicit handling of incomplete, conflicting, or geographically mismatched records
- recommendations that carry a machine-readable evidence trail

Concrete angles:
- Representing municipal integration as an evidence graph rather than a single
  merged table
- Making licence, validation, and profiling status first-class inputs to whether a
  claim is usable
- Quantifying how much a recommendation changes when weak evidence is removed
- Showing that reproducible civic conclusions depend on acquisition evidence, not
  just dataset titles

### 4.2 Measurable evaluation metrics

Proposed metrics:
- provenance recall: fraction of answer claims traceable to a recorded artifact/
  evidence record
- licence/compliance coverage: fraction of used sources with recorded licence state
- validation coverage: fraction of used statistics backed by validated artifacts
- data-quality sensitivity: how much a result changes when duplicate/missing/
  parse-warning records are excluded
- geographic-alignment correctness: whether joins use an explicit, verified mapping
  rather than assumed geography
- baseline vs enhanced gap: improvement from retrieval/reasoning over the non-LLM
  baseline on the same evidence

Suggested baseline comparison:
- baseline = deterministic descriptive analysis over validated artifacts only
- enhanced = retrieval/reasoning layer over the same evidence
- compare on factual grounding, citation completeness, and overclaim rate, not on
  appearance of sophistication

### 4.3 Evaluation caveats

- Do not claim superiority on municipal truth; claim better evidence traceability
  and lower overclaim risk.
- Evaluation must use real, locally validated artifacts, not dataset descriptions.
- If TRF-001 or other candidate licences remain unverified, those datasets should
  not be used as if redistribution or publication were approved.

---

## 5. Acquisition-readiness assessment for each candidate

### 5.1 Candidates already in the canonical inventory

| Candidate | Readiness | Reason |
|---|---|---|
| TRF-004 | NEEDS HUMAN DECISION | Source recorded; URL not re-captured; licence unverified |
| TRF-005 | NEEDS HUMAN DECISION | Multi-resource; licence unverified; city-wide aggregate caveat |
| CIT-001 | NEEDS HUMAN DECISION | Ward-level; source URL not re-captured; licence unverified |
| WST-003 | NEEDS HUMAN DECISION | Pune; URL not re-captured; licence unverified |
| CIT-003 | NEEDS HUMAN DECISION | Single FY; source URL not re-captured; licence unverified |
| TRF-001 | NEEDS HUMAN DECISION | Candidate only; licence unverified; not to be acquired here |
| WTR-001 | BLOCKED | Superseded planning record; not a download target |
| WTR-002 | BLOCKED | Rejected; CSV broken at source |
| WST-002 | BLOCKED | Rejected; bot-detection and low decision value |
| CIT-004 | BLOCKED | Subscription-dependent |
| WST-001 | BLOCKED/CONDITIONAL | PDF-centric; dataset-level conditional; source replacement recorded |
| WTR-004 | BLOCKED/CONDITIONAL | No accessible path found previously |
| ENV-001 | BLOCKED | Requires real data.gov.in API access |

### 5.2 New candidates

| Candidate | Readiness | Reason |
|---|---|---|
| Bengaluru ward geometry/metadata | UNVERIFIED | Not yet in inventory; must confirm publisher, licence, coverage, format |
| Additional Bengaluru traffic sources | UNVERIFIED | Must confirm publisher, licence, alignment, granularity |
| CPCB air-quality historical sources | BLOCKED/UNVERIFIED | Depends on access path, station geography, and licence |

---

## 6. Proposal: schema mapping and integration flow

### 6.1 Canonical integration model

Do not merge everything into one wide table by default. Use a layered model:

1. raw layer
   - each source keeps its own file and schema
   - provenance attached at acquisition time
2. validated layer
   - only artifacts that pass the repository's validation gate are used for claims
3. profiled layer
   - descriptive statistics with explicit scope and measurement basis
4. integrated evidence layer
   - explicit join mapping, geography, time aggregation, and confidence notes
   - every integrated row traces back to source artifact + evidence record

### 6.2 Example schema mapping for the recommended Bengaluru set

Mapping is illustrative, not asserted from real files:

| Integrated concept | TRF-004 role | TRF-005 role | CIT-001 role |
|---|---|---|---|
| location | station identifier | station/zone identifier | ward identifier |
| time | date of crash record | date of violation record | date of complaint |
| event count | crash count/record | violation count/type | complaint category/count |
| geography | Bengaluru station-level | Bengaluru station/zone-level | Bengaluru ward-level |
| join key | station + date | station/zone + date | ward + date |

If station-to-ward mapping is unavailable:
- keep crash and violation analysis at station/zone level
- keep grievance analysis at ward level
- relate them only through documented common geography or time aggregates, with an
  explicit limitation note

### 6.3 Integration flow

1. Acquire only after authorization and licence/source assessment.
2. Validate each artifact; record validation state and scope.
3. Profile each artifact; record measured statistics and warnings.
4. Normalize identifiers only with a verified mapping document.
5. Aggregate temporally to a stated common period.
6. Join spatially only where the join key is supported by evidence.
7. Produce an integrated evidence table with per-row provenance and confidence.
8. Release a non-LLM baseline summary first.
9. Add retrieval/reasoning later, with citation and evidence-state display.

---

## 7. Exact next steps, prioritized by dependency

### 7.1 Immediate, before any acquisition

1. Decide the first vertical slice owner and the decision question formally.
2. Re-capture exact resource URLs and publisher pages for the chosen candidate set.
3. Read authoritative licence/source pages for each candidate.
4. Confirm whether a station-to-ward or other geography mapping exists and is
   authoritative.
5. Record licence verification status only when supported by evidence; otherwise
   keep `license_verified=false`.

### 7.2 After source confirmation, before integration

6. For each chosen dataset, define the required fields and validation expectations.
7. Implement or extend handlers only for authorized, licence-assessed sources.
8. Acquire with explicit authorization and provenance capture.
9. Validate and profile; record measured facts and quality issues.

### 7.3 Integration and evaluation

10. Build the integrated evidence layer with explicit joins and confidence notes.
11. Produce the non-LLM baseline analysis.
12. Define the evaluation metrics and baseline comparison.
13. Only then consider retrieval/reasoning hooks for cited, evidence-bounded output.

### 7.4 Explicit out-of-scope for this task

- downloading or acquiring any dataset
- implementing handlers, joins, or retrieval
- modifying canonical metadata, code, tests, or documentation
- treating public links as licence approval
- claiming verified licence status for TRF-001 or any other unverified source

---

## Final recommendation

For the first CivicMind integration experiment, plan around a Bengaluru public-safety
vertical using TRF-004 plus TRF-005 and, if ward-level join evidence exists,
CIT-001. Treat this as an evidence-bounded municipal comparison, not a causal study.
Defer any acquisition until each source has an authoritative licence/source assessment
and explicit human authorization, and keep TRF-001 as an unverified candidate until
its licence verification is supported by evidence.
