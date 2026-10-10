# Project status

Last updated: 2026-10-10 (repository foundation milestone).

Legend: **done** = implemented and covered by tests · **planned** = designed but
intentionally not implemented · **blocked** = waiting on a prerequisite.

## Milestone 1 — engineering foundation: DONE

| Item | Status | Evidence |
| --- | --- | --- |
| PEP 621 `pyproject.toml`, `src/` layout, editable install | done | `pip install -e ".[dev]"` |
| Environment-based configuration (`.env`, defaults, validation) | done | `civicmind.config`, `tests/test_config.py` |
| Secrets policy: env-only, never committed | done | `.env.example`, `.gitignore`, `get_secret()` |
| Structured logging (text + JSON, optional log file) | done | `civicmind.logging_config` |
| CLI with `--help`, `--version`, health check | done | `civicmind.cli`, `tests/test_cli.py` |
| Optional PyTorch/CUDA detection (CPU-safe) | done | `civicmind.environment.detect_pytorch` |
| Ingestion contract + registry (no auto-download) | done | `civicmind.ingestion`, `tests/test_ingestion.py` |
| Scaffold validation script | done | `python scripts/validate_project.py` |
| Ruff lint/format + pytest configuration | done | `pyproject.toml` |

## Milestone 2 — ingestion handlers: PLANNED

| Item | Status |
| --- | --- |
| First concrete handler for an approved municipal source | planned |
| Provenance store (catalogue of acquisitions) | planned |
| Checksum/regression tests against pinned snapshots | planned |

## Milestone 3 — quality & profiling: PLANNED

| Item | Status |
| --- | --- |
| Dataset profiling (real descriptive statistics) | planned |
| Quality-warning surface in validation reports | planned |
| Schema/identifier normalisation (preprocessing) | planned |

## Milestone 4 — retrieval & AI: PLANNED (out of scope now)

| Item | Status |
| --- | --- |
| Retrieval layer over processed data | planned |
| Evidence-grounded answers with citations | planned |
| Evaluation harness | planned |

## Known limitations

* The ingestion registry is empty: no real sources are wired up yet.
* `data/*` directories exist only as Git placeholders; nothing is stored there.
* No dataset has been downloaded, and no dataset profile exists.
* Tests run offline with no GPU; they use test-local dummy handlers, which are
  test fixtures, not production implementations.
