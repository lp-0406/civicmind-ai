# Dataset ingestion strategy

Status: **contract implemented, handlers planned**. This document defines how
datasets will be acquired and governed. It deliberately names *no* concrete
dataset, API, schema or record contents: those decisions belong to a later,
reviewed step and must be based on real publisher documentation.

## Principles

1. **Provenance before volume.** A dataset is only usable if we can state where
   it came from, under which licence, when it was obtained and exactly what was
   obtained (checksum, size).
2. **Nothing is fabricated.** Unknown values stay `None`. Record counts,
   profiles and statistics are computed from real data only, never invented to
   fill a report.
3. **Explicit acquisition.** Registering a handler never downloads anything.
   Fetching happens only when an operator calls `acquire()` / `ingest()`.
4. **Raw data is immutable and uncommitted.** Acquired files land in
   `data/raw/`, which Git ignores. Transformed copies go to `data/interim/` and
   `data/processed/`.
5. **Licence compliance.** A source without a stated licence is recorded as
   `unspecified` and blocked from downstream use until reviewed.
6. **Failures are loud.** Acquisition problems raise `AcquisitionError`;
   validation problems raise `DatasetValidationError`; silent degradation is
   not allowed.

## The ingestion contract

Implement `civicmind.ingestion.DatasetIngestor`:

| Step | Method | Returns | Notes |
| --- | --- | --- | --- |
| Identify | `describe()` | `SourceDescriptor` | Static, verifiable metadata: `source_id`, `title`, `publisher`, `license`, optional `uri`, cadence, scope, tags |
| Acquire | `acquire(destination)` | `AcquisitionResult` | Reads/retrieves data into `destination`; records timestamp, method, path, byte size, SHA-256 checksum; leaves `record_count=None` unless genuinely known |
| Validate | `validate(result)` | `ValidationReport` | Emits `QualityIssue`s (`info` / `warning` / `error`) and a `passed` verdict |
| Provenance | `build_provenance(result)` | `ProvenanceRecord` | Default implementation composes descriptor + result + handler class path and versions |

`ingest(destination)` runs all four steps, raising on validation errors unless
`enforce_validation=False`.

## Registration

```python
from civicmind.ingestion import IngestionRegistry, DEFAULT_REGISTRY

registry = IngestionRegistry()          # isolated registry (tests, pipelines)
registry.register(my_handler)           # metadata only - no network I/O
handler = registry.get("some.source.id")
```

* Duplicate ids raise `SourceRegistrationError` (use `overwrite=True` to replace).
* Unknown ids raise `UnknownSourceError` listing the known ids.
* `DEFAULT_REGISTRY` backs `civicmind ingest list`; it starts empty on purpose.

## Planned acquisition workflow

1. **Discover** a source and read its publisher documentation (licence, cadence,
   update policy, contact point).
2. **Describe** it in a handler's `SourceDescriptor`; review before merging.
3. **Acquire** explicitly into `data/raw/<source_id>/`, capturing checksum and
   size in the acquisition result.
4. **Validate** structure and expectations (readable, non-empty, expected
   columns present, encoding sane); record warnings for later profiling.
5. **Record provenance** so any later claim can be traced back to an exact
   file and acquisition time.
6. **Profile** (planned) to compute real descriptive statistics from the file.
7. **Transform** (planned) into `data/interim/` then `data/processed/`, keeping
   the raw file untouched.

## Governance checklist for a new source

- [ ] Publisher identified and documented (URL in `SourceDescriptor.uri`).
- [ ] Licence recorded and redistribution terms understood.
- [ ] Update cadence and snapshot policy understood.
- [ ] Acquisition is reproducible (a second `acquire()` yields the same bytes,
      or the difference is explained by a documented revision).
- [ ] No personal or sensitive data beyond what the publisher already makes
      public.
- [ ] Validation expectations written down before ingestion runs in CI.

## Explicit non-goals (this milestone)

* No automatic downloads during setup, tests or CI.
* No speculative scraping, parsing or transformation of unnamed sources.
* No synthetic "example" municipal records presented as real data.
