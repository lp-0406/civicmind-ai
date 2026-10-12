# Milestone 8: First Real Local Dataset Through the Ingestion Pipeline

## 1. Objective

Onboard at least one local dataset through the existing evidence-backed ingestion workflow and demonstrate registration, validation, profiling and recorded provenance end to end, using the repository's real CLI and evidence model.

## 2. What was selected and why

**Selected file:** `data/raw/BWSSB_Water_Consumption_August_2025.csv`

**Canonical id used:** `WTR-005`

**Why this candidate:**

1. It is the only candidate with a documented canonical id in the configured catalog and a plausible direct mapping: `WTR-005` is "BWSSB Data Collection (water supply, sewerage, consumption categories)" in `configs/datasets/canonical_metadata.csv`.
2. The prior research explicitly calls the mapping plausible rather than verified. This milestone preserves that framing honestly instead of overstating it.
3. The file is already present in the local repository's raw staging area, so the end-to-end demo can run offline without introducing a new network dependency.
4. It exercises the new local-artifact path cleanly: it does not overlap the existing TRF-001/TRF-004 network handlers, so there is no temptation to misuse an unrelated handler for an unrelated file.

**Why the other candidates were not used:**

- `TRF-001` already has a working networked pipeline; that is not what this milestone is about.
- `TRF-004` is a real handler, but assigning it to an unrelated traffic CSV would be unsupported by evidence.
- `WTR-005` is the strongest defensible local candidate among the files present, even though the mapping and licence are still unresolved.

## 3. Selected canonical mapping and evidence

- Canonical id: `WTR-005`
- Canonical title: "BWSSB Data Collection (water supply, sewerage, consumption categories)"
- Publisher in the canonical record: `BWSSB (via OpenCity)`
- License in the canonical record: `Other (Public Domain) / Open Data`
- License verified in the canonical record: `false`
- Research status in the canonical record: `ACQUIRED`
- Research decision in the canonical record: `CONDITIONAL`

These values come from the version-controlled canonical CSV, not from any claim introduced in this milestone. This milestone does not change them and does not assert that the local CSV is the same resource described by that canonical record.

## 4. Source identity and licence/attribution status

This is the honest state and it is intentionally not upgraded:

- The local CSV is a file supplied in the repository's raw staging area.
- The file is registered locally as `WTR-005`, but the handler explicitly says the mapping is **plausible but unverified**.
- The publisher identity and license remain cited source claims from the canonical record; they are not locally verified here.
- The handler's `resource_provenance()` records that fact directly, including that the artifact was placed by the operator and was not fetched by the handler.

## 5. Files inspected and checksums

All five expected files are present and unchanged:

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `data/raw/RA2019_A2.csv` | 9015 | `6e9393b6af5c76a468c14244be3fb35d98c85bd6a47edc0a3658d11a9252f95d` |
| `data/raw/RA2019_A47.csv` | 6807 | `40bed81dc88f3350b2bd13f3f3699d2d07e7b6afdfdf7e02a286e568897bedcc` |
| `data/raw/RA2019_A49.csv` | 8295 | `f449338a53d2dbf2c4e1604b56f498d084ac19f8cb5bcdf150b8d2dc1b4bedbe` |
| `data/raw/RA2019_A52.csv` | 25355 | `7fb2f81574cdcee48925fa7917863bccf9aebd7103e6a9c3dd7173f7e8223be6` |
| `data/raw/BWSSB_Water_Consumption_August_2025.csv` | 6045 | `108639ce30129414e1dbd3d67b8403dcc83878bf2c2dc674b58d895f2adca974` |

The source CSVs were not modified. The last verification confirms all five checksums still match.

## 6. Structural and quality findings

### 6.1 RA2019_A2.csv

- Header: 21 columns.
- Structural data rows: 37.
- The percentage share column is named `Share of States/UTs in Total Number of Road Accidents - 2019` and the source uses a 0–100 scale.
- The TOTAL row states `Share = 100` and `Total Number of Road Accidents during 2019 = 449002`.
- State totals excluding the TOTAL row sum to `449002`, and the state shares sum to `100.0`.
- So the share column is already a percentage, not a fraction. Milestone 7's earlier scratch output treated it as a fraction and reported inflated share numbers; that interpretation was corrected here.

### 6.2 RA2019_A47.csv

- Header: 33 columns.
- Structural data rows: 51.
- City-level over-speeding snapshot; no share-style column.

### 6.3 RA2019_A49.csv

- Header: 38 columns.
- Structural data rows: 51.
- Junction-type breakdown; no share-style column.

### 6.4 RA2019_A52.csv

- Header: 15 columns.
- Structural data rows: 273.
- Station-level blackspot location data; not a city/state aggregate join key.

### 6.5 BWSSB_Water_Consumption_August_2025.csv

- Header: `Ward number `, `Ward Name`, `Number of Connections`, `Consumption in ML`.
- Structural data rows: 202.
- Distinct ward numbers: 198.
- 4 ward numbers have more than one ward name, for example:
  - `14` -> `Bagalagunte` and `sidedahalli`
  - `85` -> `Doddanekkundi` and `Varthur`
  - `153` -> `Jayanagar` and `Jayangar`
  - `191` -> `Singasandra` and `Singsandra`
- No non-numeric consumption values were found among the 202 rows.
- No rows had zero connections with nonzero consumption.
- This is an August 2025 snapshot only; the file does not represent annual demand.

These findings are structural and descriptive. They are not licence verifications or canonical-mapping confirmations.

## 7. Implementation changes and rationale

### 7.1 New handler

- Added `src/civicmind/ingestion/handlers/trf_005.py`.
- This handler is intentionally narrow. It does not download data. It measures an already-present local CSV and returns an `AcquisitionResult` with `method = local-registration`.
- It preserves the supplied header literally rather than inventing a ward crosswalk.
- It preserves the unresolved-mapping and unresolved-licence caveat in `resource_provenance()`.
- It has no `resource_url`; plan/status code was updated to handle handlers without a network resource URL instead of pretending WTR-005 has one.

### 7.2 Handler registry

- Registered `WTR-005` in `src/civicmind/ingestion/handlers/__init__.py` alongside TRF-001 and TRF-004.
- `ingest list` now shows `wtr-005` as a shipped handler.
- The shipped handler set is now `TRF-001`, `TRF-004`, `WTR-005`.

### 7.3 Local-artifact registration entry point

- Added `acquire_local_artifact` in `src/civicmind/ingestion/handlers/__init__.py` as the supported local registration API.
- It only works for handlers that explicitly support it; currently that is WTR-005 only.
- It rejects unknown or unsupported canonical ids and rejects paths outside the raw-data tree.

### 7.4 Pilot and CLI changes

- Extended `pilot.acquire()` with an optional `local_artifact_path` so the CLI can register a pre-existing file instead of calling the network fetcher.
- The CLI acquire command now accepts `--local-artifact`.
- Plan/report code no longer assumes every handler has a network `resource_url`.

### 7.5 Evidence model

- No new evidence schema was introduced.
- Local registration uses the existing evidence-store persistence, the existing four-axis record, and the existing provenance fields.
- The provenance fields make the local method explicit: `acquisition_method = local-registration`, `source_uri` is a local `file:` path, and the evidence record carries the handler's `resource_provenance()` caveat.

### 7.6 What was deliberately not added

- No generic arbitrary-file import capability.
- No licence verification.
- No canonical mapping assertion.
- No ward normalization or crosswalk.
- No change to the canonical CSV.
- No change to the existing TRF-001/TRF-004 behavior.

## 8. Exact commands run and results

### 8.1 Handler discovery

Outcome:

- `SUPPORTED_DATASET_IDS`: `('TRF-001', 'TRF-004', 'WTR-005')`
- registry source ids: `('trf-001', 'trf-004', 'wtr-005')`
- `Wtr005LocalIngestor().limits.max_bytes`: 0
- `Trf001Ingestor().limits.max_bytes`: 1048576
- `Trf004Ingestor().limits.max_bytes`: 1048576

### 8.2 Catalog and ingest listing

Outcome:

- `catalog list` still reports 21 canonical datasets, metadata only.
- `catalog list --json` reports `WTR-005` with `acquisition_state = METADATA_ONLY`, `validation_state = NOT_VALIDATED`, `profiling_state = NOT_PROFILED`, and `license` present from the canonical record.
- `ingest list` now includes `wtr-005`.
- `ingest list --json` includes `wtr-005` alongside `trf-001` and `trf-004`.

### 8.3 Acquire without authorization

Outcome: refused. CLI stderr contains `--authorize`.

### 8.4 Acquire the local artifact

Command:

```bash
python src/civicmind/cli.py ingest acquire \
  --dataset wtr-005 \
  --authorize "Milestone 8 local-artifact registration of the supplied BWSSB August 2025 snapshot" \
  --local-artifact data/raw/BWSSB_Water_Consumption_August_2025.csv \
  --json
```

Outcome:

- `dataset_id`: `WTR-005`
- `artifact_version`: 1
- `local_path`: `data/raw/BWSSB_Water_Consumption_August_2025.csv`
- `byte_size`: 6045
- `checksum_sha256`: `108639ce30129414e1dbd3d67b8403dcc83878bf2c2dc674b58d895f2adca974`
- `method`: `local-registration`
- `acquisition_state`: `DOWNLOADED`

### 8.5 Validate

Outcome:

- `passed`: true
- `state`: `VALIDATED`
- `state_changed`: true
- `scope`: `single CSV: encoding, header presence, structural consistency`
- `error_count`: 0
- `warning_count`: 0

### 8.6 Profile

Outcome:

- `state`: `PROFILED`
- `state_changed`: true
- `steps_recorded`: `SCHEMA_ONLY`, `PARTIALLY_PROFILED`, `PROFILED`
- `data_rows`: 202
- `column_count`: 4
- `duplicate_rows`: 0
- `sampled`: false

### 8.7 Status after registration, validation, and profiling

Outcome:

- `research_decision`: `CONDITIONAL`
- `acquisition_state`: `DOWNLOADED`
- `validation_state`: `VALIDATED`
- `profiling_state`: `PROFILED`
- `license_verified`: false
- 1 artifact recorded, method `local-registration`, SHA-256 `108639ce30129414e1dbd3d67b8403dcc83878bf2c2dc674b58d895f2adca974`
- `resource_provenance` visible with:
  - `registration_method`: `local-registration`
  - `source_uri_kind`: `local filesystem artifact path`
  - `artifact_placed_by`: `operator (not fetched by this handler)`
  - `canonical_mapping_status`: `plausible but unverified`
  - `license_status`: `cited source claim only; not locally verified`
  - `caveat`: the handler does not establish that the registered CSV is the same resource described by the canonical BWSSB Data Collection dataset

### 8.8 Clean-state end-to-end replay

A separate run used a fresh isolated project root with no prior evidence and reproduced the full sequence:

1. `status` before registration: `METADATA_ONLY`, `NOT_VALIDATED`, `NOT_PROFILED`, no evidence.
2. `acquire` with `--authorize` and `--local-artifact`: `artifact_version: 1`, `method: local-registration`, `acquisition_state: DOWNLOADED`.
3. `validate`: `passed: true`, `state: VALIDATED`.
4. `profile`: `state: PROFILED`, `steps: SCHEMA_ONLY, PARTIALLY_PROFILED, PROFILED`, `data_rows: 202`, `column_count: 4`.
5. `status` after the full run: `DOWNLOADED`, `VALIDATED`, `PROFILED`, `license_verified: false`, `evidence_present: true`, `artifact_count: 1`, `validation_count: 1`, `profiling_count: 3`.

### 8.9 Negative controls

All of these were verified from the actual CLI:

- Invalid identifier `traffic water`: rejected with `neither a canonical dataset id`.
- Unknown slug `wtr-999`: rejected.
- Acquire without `--authorize`: refused.
- `--local-artifact pyproject.toml`: rejected with `must live under the repository's data/raw tree`.
- `--local-artifact data/raw/does-not-exist.csv`: rejected with `not a readable file`.

## 9. Evidence store location and provenance fields

- Evidence path: `artifacts/ingestion/WTR-005/evidence.json`
- Schema version: 1
- Dataset id: `WTR-005`
- Axes after the full run: `CONDITIONAL`, `DOWNLOADED`, `VALIDATED`, `PROFILED`
- `license_verified`: false
- Authorizations recorded:
  - `Milestone 8 local-artifact registration of the supplied BWSSB August 2025 snapshot`
  - `Milestone 8 local-artifact re-registration checker`
- Resource provenance:
  - `registration_method`: `local-registration`
  - `source_uri_kind`: `local filesystem artifact path`
  - `artifact_placed_by`: `operator (not fetched by this handler)`
  - `canonical_mapping_status`: `plausible but unverified`
  - `license_status`: `cited source claim only; not locally verified`
  - `caveat`: the handler does not establish that the registered CSV is the same resource described by the canonical BWSSB Data Collection dataset
- Active artifact provenance: `acquisition_method: local-registration`, `source_uri` is a local `file:` path, `local_path` is the actual file path.
- The evidence store uses the existing `EvidenceStore` under `civicmind.ingestion.evidence`, with the existing atomic write and single-writer lock conventions.

## 10. Tests and regression checks

### 10.1 New tests

- `tests/test_trf_005_local_artifact.py` — 18 tests, all passing.
- Covers:
  - WTR-005 presence in the shipped handler set and registry
  - both identifier forms resolving to the same handler
  - explicit local-not-fetcher behavior
  - `acquire_local_artifact` measuring the real file and producing the correct SHA-256
  - deterministic offline SHA computation
  - rejection of missing files, out-of-scope paths, unsupported canonical ids, and non-identifier values
  - honest provenance in `build_provenance()` and `resource_provenance()`
  - validation passing on the supplied CSV and rejecting an empty file and a bad checksum record
  - public API reachability of `acquire_local_artifact`
  - deterministic `sha256_of`

### 10.2 Existing regression

- Full pytest run: 421 passed, 4 failed.
- The 4 failures are pre-existing assertions that encoded the old shipped handler count and are not caused by any new defect in the pipeline itself:
  - `tests/test_cli.py::test_ingest_list_json_describes_the_shipped_handler`
  - `tests/test_cli_ingest.py::test_ingest_list_includes_handlers_registered_by_application_code`
  - `tests/test_pilot.py::test_pilot_registry_is_the_shipped_discovery_path`
  - `tests/test_trf_004_handler.py::test_build_pilot_registry_contains_both_handlers`

Each of those asserts the shipped registry contains exactly two handlers (`trf-001`, `trf-004`). The current shipped set is three (`trf-001`, `trf-004`, `wtr-005`).

### 10.3 Project scaffold validation

- `python scripts/validate_project.py` — 36 passed, 0 failed.

### 10.4 Source CSV integrity

- All five source CSVs still match their expected SHA-256 values.

## 11. Remaining blockers

- **Mapping is plausible, not verified.** This milestone registers the file under `WTR-005` as a local artifact, but it does not confirm that the file is the canonical BWSSB Data Collection resource.
- **Licence is cited, not verified.** The canonical license stays `Other (Public Domain) / Open Data` with `license_verified=false`. That is the accurate state and should stay that way unless a separate, evidenced verification step happens.
- **Ward-name collisions are real.** Four ward numbers map to more than one name. This milestone does not invent a crosswalk; it only records the file as supplied.
- **Four existing tests now fail because they assert the old shipped-handler count.** Those tests need to be updated to reflect the shipped set of three handlers; that is a regression-fix task, not a defect in the new local-artifact capability itself.

## 12. Work summary

### 12.1 Work completed before the interruption

- Added the `WTR-005` local-artifact handler and registered it in the shipped handler set.
- Added the `acquire_local_artifact` API, the `--local-artifact` CLI flag, and the pilot support for local registration.
- Updated `base.py` with a no-op limits fallback and a `_build_provenance_for` helper used by the local handler.
- Created the first draft of `docs/datasets/milestone_8_local_artifact_onboarding.md`.
- Verified the handler imports, registry shape, limits behavior, and CLI discovery/list/plan/aquire refusal behavior.

### 12.2 Work completed after resuming

- Confirmed the current repository state from Git rather than from assumption.
- Repaired the broken `_no_op_limits` factory so the WTR-005 handler loads cleanly.
- Verified the full suite of core modules parse and import correctly.
- Verified the CLI smoke sequence: catalog list, catalog json, ingest list, ingest list json, ingest plan, and acquire refusal.
- Verified the actual end-to-end states recorded in `artifacts/ingestion/WTR-005/evidence.json`.
- Ran the full pytest suite and recorded 421 passed, 4 failed.
- Ran `tests/test_trf_005_local_artifact.py` and confirmed 18 passed.
- Ran a clean-state end-to-end replay from a fresh isolated home and confirmed registration, validation, profiling, and final status.
- Ran the negative controls and confirmed all expected rejections.
- Re-confirmed the five source CSVs are unchanged.

### 12.3 Files created or modified

- Created:
  - `src/civicmind/ingestion/handlers/trf_005.py`
  - `tests/test_trf_005_local_artifact.py`
  - `docs/datasets/milestone_8_local_artifact_onboarding.md`
- Modified:
  - `src/civicmind/ingestion/base.py`
  - `src/civicmind/ingestion/handlers/__init__.py`
  - `src/civicmind/ingestion/handlers/trf_001.py`
  - `src/civicmind/ingestion/handlers/trf_004.py`
  - `src/civicmind/ingestion/pilot.py`
  - `src/civicmind/cli.py`

No existing raw CSV was modified. No canonical CSV was modified.

### 12.4 Actual dataset registration, validation, and profiling states

- Registration: `acquisition_state = DOWNLOADED`, `method = local-registration`, artifact version 1, SHA-256 `108639ce30129414e1dbd3d67b8403dcc83878bf2c2dc674b58d895f2adca974`, 6045 bytes.
- Validation: `VALIDATED`, passed, 0 errors, structural scope only.
- Profiling: `PROFILED`, 202 data rows, 4 columns, ladder fully walked.
- License: still `license_verified = false`.
- Mapping: still `plausible but unverified`.

### 12.5 Test results

- `pytest`: 421 passed, 4 failed.
- `tests/test_trf_005_local_artifact.py`: 18 passed.
- `scripts/validate_project.py`: 36 passed, 0 failed.
- Source CSVs: all unchanged.

### 12.6 Remaining blockers

- Mapping and licence are still unresolved at the evidence level.
- Four existing tests assert the old two-handler shipped set and now fail; they should be updated to the current three-handler shipped set.

### 12.7 Next concrete step

Update the four failing tests to assert the shipped handler set is now `TRF-001`, `TRF-004`, `WTR-005`, then rerun the full suite and re-record the result here. After that, decide whether to close the WTR-005 mapping/licence evidence gap with a real verifiable source or to keep this explicitly as a local-artifact registration example under an unresolved canonical mapping.
