# CivicMind AI

**Evidence-grounded AI-powered municipal decision-intelligence platform.**

CivicMind AI will ingest authoritative municipal datasets, validate and profile
them, and support analysis whose every claim can be traced back to a real,
licensed source.

> **Current status: engineering foundation (v0.1.0).**
> The repository currently ships the *scaffold* only: configuration, structured
> logging, a health-check CLI, and the ingestion contract + registry.
> **No dataset is downloaded, no AI model is loaded, and no municipal record or
> data profile has been fabricated.** See
> [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for what exists vs what is
> planned.

---

## Purpose and scope

Municipal decisions (budgets, transit, permits, infrastructure) should be
answerable from evidence. CivicMind AI is being built to:

1. **Ingest** public municipal datasets with full provenance (publisher,
   licence, acquisition time, checksum).
2. **Validate and profile** that data, surfacing quality warnings instead of
   hiding them.
3. **Retrieve** evidence for a question — planned.
4. **Assist analysis with AI**, always citing its sources — planned.

Out of scope for this milestone: RAG/embeddings, vector databases, knowledge
graphs, LLM inference, agents, dashboards, and automatic dataset downloads.

## Implementation status

| Area | Status | Where |
| --- | --- | --- |
| Packaging (`pyproject.toml`, `src/` layout, editable install) | ✅ done | [pyproject.toml](pyproject.toml) |
| Environment-based configuration + secret policy | ✅ done | [src/civicmind/config.py](src/civicmind/config.py) |
| Structured logging (text/JSON) | ✅ done | [src/civicmind/logging_config.py](src/civicmind/logging_config.py) |
| Environment/health inspection (optional PyTorch/CUDA detection) | ✅ done | [src/civicmind/environment.py](src/civicmind/environment.py) |
| CLI (`--help`, `--version`, `health`, `config show`, `ingest list`) | ✅ done | [src/civicmind/cli.py](src/civicmind/cli.py) |
| Ingestion contract + registry (no auto-download) | ✅ done | [src/civicmind/ingestion/](src/civicmind/ingestion/__init__.py) |
| Tests (config, CLI, ingestion) | ✅ done | [tests/](tests) |
| Scaffold validation script | ✅ done | [scripts/validate_project.py](scripts/validate_project.py) |
| Preprocessing / profiling / storage | 🚧 planned (packages reserved) | [src/civicmind/preprocessing](src/civicmind/preprocessing/__init__.py) |
| Concrete ingestion handlers, retrieval, AI | 🚧 planned | see [docs/architecture/system_overview.md](docs/architecture/system_overview.md) |

## Repository layout

```text
civicmind-ai/
├── pyproject.toml            # PEP 621 metadata, ruff + pytest config
├── .env.example              # template for local secrets (never commit .env)
├── docs/
│   ├── architecture/system_overview.md
│   ├── datasets/ingestion_strategy.md
│   └── PROJECT_STATUS.md
├── configs/                  # runtime config (planned; no secrets)
├── data/                     # datasets - git-ignored, .gitkeep placeholders
│   ├── raw/  interim/  processed/  external/
├── artifacts/                # generated outputs (git-ignored)
├── logs/                     # log files (git-ignored)
├── scripts/
│   ├── check_environment.py  # environment report
│   └── validate_project.py   # scaffold self-check
├── src/civicmind/
│   ├── config.py             # Settings from env/.env, get_secret()
│   ├── logging_config.py     # text/JSON logging
│   ├── environment.py        # health report, optional torch detection
│   ├── cli.py                # argparse CLI
│   ├── ingestion/            # contract, registry, exceptions
│   ├── preprocessing/        # planned
│   ├── profiling/            # planned
│   └── storage/              # planned
└── tests/                    # pytest suite (offline, CPU-only)
```

## Setup

Requirements: **Python 3.10+** (3.10–3.12 supported), `pip`, and `git`.

### Windows (PowerShell)

```powershell
git clone https://github.com/lp-0406/civicmind-ai.git
cd civicmind-ai

py -3.10 -m venv .venv
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process  # if activation is blocked
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
python scripts/check_environment.py
```

### macOS / Linux

```bash
git clone https://github.com/lp-0406/civicmind-ai.git
cd civicmind-ai

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cp .env.example .env
python scripts/check_environment.py
```

Editable installation (`-e`) means source edits take effect immediately — no
reinstall needed while developing.

### Optional AI/GPU extra

PyTorch is **not** required. Install it only when you need the future AI
stages:

```bash
python -m pip install -e ".[ai]"   # CPU or CUDA build, per your platform
```

`civicmind health` reports whether PyTorch/CUDA are present without importing
them unless installed.

## Tests, linting and formatting

```bash
pytest                      # run the test suite (offline, no GPU, no data)
pytest -q                   # quiet
ruff check .                # lint
ruff format .               # format in place
ruff format --check .       # format check only (CI)
python scripts/validate_project.py   # scaffold self-check
```

## CLI examples

```bash
civicmind --help                     # usage
civicmind --version                  # package version
civicmind health                     # environment report (exit 1 if unusable)
civicmind health --json              # same, machine-readable
civicmind config show                # resolved settings (secrets excluded)
civicmind config show --json
civicmind ingest list                # registered ingestion handlers (empty today)
civicmind ingest list --json
```

Without installing the console script, use the module directly:

```bash
python -m civicmind.cli health
python scripts/check_environment.py
```

## Configuration and secrets

Configuration is resolved from (highest precedence first):

1. process environment variables (`CIVICMIND_*`),
2. a local `.env` file (git-ignored; see [.env.example](.env.example)),
3. built-in defaults.

Supported variables: `CIVICMIND_ENV`, `CIVICMIND_LOG_LEVEL`,
`CIVICMIND_LOG_FORMAT`, `CIVICMIND_DATA_DIR`, `CIVICMIND_LOGS_DIR`,
`CIVICMIND_ARTIFACTS_DIR`, `CIVICMIND_CONFIGS_DIR`,
`CIVICMIND_PROJECT_ROOT`.

**Secret-handling policy**

* Secrets are read only from the environment or `.env` — never hardcoded.
* `.env` is git-ignored; only `.env.example` (with empty placeholders) is
  committed.
* `Settings` contains no secret fields, so secrets cannot leak into logs,
  artifacts or `civicmind config show`.
* Access secrets with `civicmind.config.get_secret("SOME_API_KEY")`; empty
  values fall back to the default instead of being treated as real credentials.

**Dataset policy**

* Raw data is **never** committed: `data/raw`, `data/interim`,
  `data/processed`, `data/external`, `artifacts/` and `logs/` are ignored by
  Git, with `.gitkeep` placeholders preserving the tree.
* Nothing is downloaded during setup, tests or CI.
* Dataset provenance (publisher, licence, acquisition time, checksum) is
  recorded for every acquisition — see
  [docs/datasets/ingestion_strategy.md](docs/datasets/ingestion_strategy.md).
* No synthetic municipal records or invented dataset profiles are ever
  presented as real.

## Ingestion in 10 lines

```python
from pathlib import Path

from civicmind.ingestion import DatasetIngestor, SourceDescriptor

class MySource(DatasetIngestor):
    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id="example.source",
            title="…",            # from the publisher's documentation
            publisher="…",
            license="…",
        )

    def acquire(self, destination: Path): ...      # explicit, may raise AcquisitionError
    def validate(self, result): ...                # returns ValidationReport

outcome = MySource().ingest(Path("data/raw/example.source"))
print(outcome.provenance)
```

Registration stores metadata only — no data moves until `acquire()` runs. See
[docs/datasets/ingestion_strategy.md](docs/datasets/ingestion_strategy.md) for
the full contract.

## Documentation

* [docs/architecture/system_overview.md](docs/architecture/system_overview.md) —
  components, design decisions, implemented vs planned.
* [docs/datasets/ingestion_strategy.md](docs/datasets/ingestion_strategy.md) —
  ingestion contract, governance checklist, safeguards.
* [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) — milestone tracker.

## Licence

No licence file has been published yet; all rights reserved by default. Add a
`LICENSE` before redistributing.
