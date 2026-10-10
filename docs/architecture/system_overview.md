# System overview

Status: **foundation only**. This document describes what exists today and the
architecture later stages will build on. Anything marked *planned* is
intentionally not implemented yet.

## Purpose

CivicMind AI aims to be an evidence-grounded decision-intelligence platform for
municipal questions: ingest authoritative public datasets, validate and profile
them, and only then (in later phases) support retrieval and AI-assisted
analysis that cites its sources.

The current milestone deliberately stops before any AI component: a wrong
foundation is expensive, so the ingestion contract, configuration and quality
gates come first.

## Component map

```text
                        +----------------------+
   operator / CI  --->  |  CLI (civicmind)     |  --help, --version, health,
                        +----------------------+  config show, ingest list
                                   |
             +---------------------+---------------------+
             |                     |                     |
      +------v-------+     +-------v--------+    +-------v--------+
      |  config.py   |     | logging_config |    | environment.py |
      | Settings,    |     | text / JSON    |    | Python, dirs,  |
      | secrets      |     | structured logs|    | optional torch |
      +--------------+     +----------------+    +----------------+
                                   |
                        +----------v-----------+
                        | ingestion/           |   IMPLEMENTED (contract)
                        |  base.py  (ABC +     |
                        |           value objs)|
                        |  registry.py         |
                        |  exceptions.py       |
                        +----------------------+
                                   |
      +----------------------------+----------------------------+
      | (planned)                  | (planned)                  | (planned)
+-----v------+             +-------v-------+            +-------v-------+
| ingestion  |             | preprocessing |            | profiling     |
| handlers   |             | normalisation |            | statistics    |
| (per source)|            +---------------+            +---------------+
+-----+------+                      |                          |
      |                             +------------+-------------+
      |                                          |
      +----------------> +v----------------------v+
                         | storage/  (planned): catalogue, provenance
                         |           store, retrieval layer
                         +------------------------+
```

## Implemented today

| Module | Responsibility |
| --- | --- |
| `civicmind.config` | Environment-driven `Settings`, project-root discovery, `.env` loading, secret access via `get_secret()` |
| `civicmind.logging_config` | `text` / `json` structured logging, optional UTF-8 log file |
| `civicmind.environment` | Health report: Python version, writable root, optional deps, PyTorch/CUDA detection |
| `civicmind.cli` | `civicmind --version`, `health`, `config show`, `ingest list` |
| `civicmind.ingestion` | Ingestion contract (`DatasetIngestor`), value objects, exception hierarchy, `IngestionRegistry` |
| `scripts/` | `check_environment.py`, `validate_project.py` |
| `tests/` | Configuration, CLI and registry/contract tests (no data, no GPU) |

## Planned (not implemented)

* Concrete ingestion handlers for specific municipal sources.
* Preprocessing: schema normalisation, identifier reconciliation, geocoding.
* Profiling: real descriptive statistics and quality warnings.
* Storage: dataset catalogue keyed by provenance, retrieval layer.
* Evidence-grounded AI: retrieval, citations, evaluation. **Out of scope for
  this milestone.**

## Key design decisions

1. **`src/` layout + PEP 621 `pyproject.toml`.** Guarantees the tests exercise
   the installed package, not the working directory, and keeps packaging
   metadata in one standards-based file.
2. **Minimum Python 3.10.** The foundation uses only stable standard-library
   features (`X | None` unions, `dataclasses`) that work on 3.10+, so the
   project runs on the interpreters most CI images and municipal machines
   already ship. Nothing requires 3.11+ or 3.13.
3. **Contract-first ingestion.** Handlers implement an abstract base class
   (`describe` -> `acquire` -> `validate` -> provenance). Registering a handler
   stores metadata only; data is fetched exclusively by an explicit
   `acquire()` / `ingest()` call.
4. **Optional GPU stack.** PyTorch is an optional extra (`.[ai]`). Availability
   is detected with `importlib.util.find_spec`, and the module is imported only
   when installed, so CPU-only machines pay no cost.
5. **Secrets never enter the codebase.** Values come from the process
   environment or a git-ignored `.env`; `Settings` carries no secret fields, so
   nothing secret can leak into logs or artifacts.
6. **Explicit, typed errors.** `ConfigurationError`, `IngestionError` and its
   subclasses let callers distinguish failure classes without bare `except`.
7. **Small dependency surface.** Core runtime dependency: `python-dotenv` only.
   CLI uses `argparse`; logging uses the standard library.

## Data flow (foundation stage)

```text
operator
  -> civicmind health                 (verify environment, no network)
  -> register handler(s)              (metadata only, no download)
  -> handler.ingest(destination)      -> AcquisitionResult
                                       -> ValidationReport (errors raise)
                                       -> ProvenanceRecord
  -> data/raw/... (git-ignored)       -> later: interim -> processed
```

## Quality gates

* `pytest` must pass without network access, datasets or a GPU.
* `ruff check` / `ruff format --check` must pass.
* `python scripts/validate_project.py` verifies the scaffold (structure,
  `.gitkeep` placeholders, clean data directories, `.env` ignored by Git).
