"""Load canonical dataset records from a version-controlled CSV source.

This module is the canonical, version-controlled source of record for the
*catalog* of municipal datasets CivicMind knows about. It is intentionally
separate from:

* :class:`CanonicalDatasetRecord` and its four-axis status model
  (:mod:`civicmind.ingestion.metadata`): the CSV describes the dataset's
  identity and planning metadata; the local four-axis status is set by evidence
  recorded in the registry/ingestion layer, not by the CSV.
* Dataset acquisition, validation, and profiling: those begin only when
  explicitly authorized and are evidenced locally under ``data/raw/<id>/``.

Data rules
----------
* Fields that are unknown in the source stay ``UNKNOWN``/empty/``null``:
  no URL, licence, size, temporal coverage, or acquisition state is invented.
* Historical acquisition claims (``research_status = ACQUIRED``) are recorded
  only on the ``research_status`` field, **never** carried into the local
  ``acquisition_state`` axis, which starts at ``METADATA_ONLY``.
* ``canonical_metadata.csv`` lists exactly 21 rows, one per canonical id;
  ``TRF-006`` (an unresolved reference) is **not** a row in this file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from civicmind.ingestion.catalog import DatasetRegistry
from civicmind.ingestion.metadata import (
    CANONICAL_DATASET_IDS,
    CanonicalDatasetRecord,
    ResearchStatus,
    SourceReliability,
)
from civicmind.ingestion.sources.csv_metadata import (
    CANONICAL_COLUMNS,
    CSV_PATH,
    CanonicalCSVError,
    iter_canonical_csv_rows,
)

#: Default source file, re-exported so callers do not need the parser module.
DEFAULT_CSV_PATH = CSV_PATH

#: Expected column names in ``canonical_metadata.csv``. Re-exported from the strict
#: CSV parser so the expected schema has exactly one definition.
EXPECTED_COLUMNS = CANONICAL_COLUMNS

#: Rows that are known to be missing from the source — kept explicit so the
#: gap is visible rather than silently filled with placeholders.
MISSING_IDS: frozenset[str] = frozenset()


class CanonicalMetadataError(Exception):
    """Base class for canonical-metadata-source problems."""


class CanonicalDataError(CanonicalMetadataError):
    """Raised when the canonical source contains invalid or inconsistent data."""


class CanonicalMetadataMissingError(CanonicalMetadataError):
    """Raised when a requested canonical dataset id is absent from the source."""


def load_canonical_metadata(
    csv_path: Path | str | None = None,
    *,
    require_all_ids: bool = True,
) -> tuple[CanonicalDatasetRecord, ...]:
    """Load the canonical dataset catalog from ``canonical_metadata.csv``.

    The raw file is read and validated through
    :func:`civicmind.ingestion.sources.csv_metadata.iter_canonical_csv_rows`, so
    malformed quoting, column shifts, duplicate IDs, and out-of-vocabulary enum
    values are rejected before any record is built.

    Parameters
    ----------
    csv_path:
        Path to the canonical metadata CSV. ``None`` selects the
        version-controlled default at
        :data:`civicmind.ingestion.sources.csv_metadata.CSV_PATH`.
    require_all_ids:
        When true, raises :class:`CanonicalDataError` if any canonical id is
        missing from the file.

    Returns
    -------
    tuple[CanonicalDatasetRecord, ...]
        One canonical record per row, sorted by dataset_id.

    Raises
    ------
    CanonicalMetadataError
        For missing file, invalid CSV, invalid rows, or incomplete id coverage.
    """
    path = Path(csv_path) if csv_path is not None else DEFAULT_CSV_PATH
    if not path.is_file():
        raise CanonicalMetadataError(f"canonical metadata CSV not found: {path}")

    try:
        raw_rows = list(iter_canonical_csv_rows(path))
    except CanonicalCSVError as err:
        raise CanonicalDataError(str(err)) from err

    records = [_row_to_record(row._asdict()) for row in raw_rows]

    if require_all_ids:
        present = {r.dataset_id for r in records}
        absent = sorted(CANONICAL_DATASET_IDS - present)
        if absent:
            raise CanonicalDataError(
                f"canonical metadata CSV is missing rows for: {', '.join(absent)}"
            )

    records.sort(key=lambda r: r.dataset_id)
    return tuple(records)


def iter_canonical_metadata(
    csv_path: Path | str | None = None,
) -> Iterator[CanonicalDatasetRecord]:
    """Stream canonical dataset records from ``canonical_metadata.csv``, unsorted.

    Uses the same strict CSV contract as :func:`load_canonical_metadata` but
    yields records as they are parsed. Canonical id coverage is not checked here;
    use :func:`load_canonical_metadata` when it matters. ``None`` selects the
    version-controlled default path.
    """
    path = Path(csv_path) if csv_path is not None else DEFAULT_CSV_PATH
    try:
        for raw_row in iter_canonical_csv_rows(path):
            yield _row_to_record(raw_row._asdict())
    except CanonicalCSVError as err:
        raise CanonicalDataError(str(err)) from err


def load_canonical_registry(
    csv_path: Path | str | None = None,
    *,
    require_all_ids: bool = True,
) -> DatasetRegistry:
    """Build a :class:`DatasetRegistry` from the canonical metadata CSV.

    This is the explicit CSV -> registry construction path: it loads the
    version-controlled metadata, converts every row to a
    :class:`CanonicalDatasetRecord`, and registers it under its canonical
    dataset id.

    Loading metadata is **not** local evidence of anything. Every registered
    record keeps the conservative defaults from :class:`CanonicalDatasetRecord`:
    the four local axes stay ``METADATA_ONLY`` / ``NOT_VALIDATED`` /
    ``NOT_PROFILED``, and no artifact, validation event, profiling event, or
    acquisition is created. ``research_status`` reflects only the documented
    historical vocabulary carried by the CSV.

    Nothing is downloaded and no network access occurs.

    Parameters
    ----------
    csv_path:
        Path to the canonical metadata CSV; ``None`` selects the
        version-controlled default.
    require_all_ids:
        When true, every canonical dataset id must be present.

    Returns
    -------
    DatasetRegistry
        A new registry holding one record per canonical dataset.

    Raises
    ------
    CanonicalMetadataError
        For a missing/malformed CSV or incomplete id coverage.
    """
    registry = DatasetRegistry()
    for record in load_canonical_metadata(csv_path, require_all_ids=require_all_ids):
        registry.register(record)
    return registry


def _row_to_record(row: dict[str, str]) -> CanonicalDatasetRecord:
    """Build one :class:`CanonicalDatasetRecord` from a canonical CSV row.

    Unknown / empty cells remain unknown; no value is invented to fill a gap.
    """
    dataset_id = (row.get("dataset_id") or "").strip()
    if not dataset_id:
        raise CanonicalDataError("canonical metadata row missing dataset_id")
    if not _is_canonical_id(dataset_id):
        raise CanonicalDataError(
            f"canonical metadata row has non-canonical dataset_id: {dataset_id!r}"
        )

    title = (row.get("title") or "").strip()
    if not title:
        raise CanonicalDataError(f"canonical metadata row {dataset_id!r} missing title")

    short_title = (row.get("short_title") or "").strip() or ""
    domain = (row.get("domain") or "").strip() or ""
    publisher = (row.get("publisher") or "").strip() or ""
    subdomain = (row.get("subdomain") or "").strip() or ""
    publisher_url = (row.get("publisher_url") or "").strip() or ""
    dataset_url = (row.get("dataset_url") or "").strip() or ""
    download_url = (row.get("download_url") or "").strip() or ""
    license_ = (row.get("license") or "UNKNOWN").strip() or "UNKNOWN"
    license_verified = _truthy_or_false(row.get("license_verified"))
    format_ = (row.get("format") or "").strip() or ""
    temporal_coverage = (row.get("temporal_coverage") or "UNKNOWN").strip() or "UNKNOWN"
    spatial_coverage = (row.get("spatial_coverage") or "").strip() or ""
    geographic_granularity = (row.get("geographic_granularity") or "").strip() or ""
    raw_record_count = (row.get("record_count") or "").strip()
    if raw_record_count and raw_record_count != "UNKNOWN":
        record_count = _int_or_none(raw_record_count)
        if record_count is None:
            raise CanonicalDataError(
                f"canonical metadata row {dataset_id!r}: record_count is not an integer or UNKNOWN"
            )
    else:
        record_count = None
    file_size = _size_or_none(row.get("file_size"))
    source_replaced_from = (row.get("source_replaced_from") or "").strip() or ""
    notes = (row.get("notes") or "").strip() or ""

    research_status = _research_status(row.get("research_status"))
    source_reliability = _source_reliability(row.get("source_reliability"))

    raw_sr_notes = (row.get("source_reliability_notes") or "").strip()
    source_reliability_notes = raw_sr_notes or ""

    publisher_aliases = _publisher_aliases(row.get("publisher_aliases"))

    return CanonicalDatasetRecord(
        dataset_id=dataset_id,
        title=title,
        domain=domain,
        publisher=publisher,
        short_title=short_title,
        subdomain=subdomain or None,
        publisher_aliases=publisher_aliases,
        publisher_url=publisher_url or None,
        dataset_url=dataset_url or None,
        download_url=download_url or None,
        license=license_,
        license_verified=license_verified,
        format=format_,
        temporal_coverage=temporal_coverage,
        spatial_coverage=spatial_coverage or None,
        geographic_granularity=geographic_granularity or None,
        record_count=record_count,
        file_size=file_size,
        research_status=research_status,
        source_reliability=source_reliability,
        source_reliability_notes=source_reliability_notes,
        source_replaced_from=source_replaced_from or None,
        acquisition_notes=notes,
    )


#: Multi-valued cells in ``canonical_metadata.csv`` are semicolon-separated:
#: every populated ``publisher_aliases`` cell uses ``;`` (for example
#: ``'CPCB; NWIC; Ministry of Jal Shakti'``) and no cell uses a comma.
_ALIAS_DELIMITER = ";"


def _publisher_aliases(value: str | None) -> tuple[str, ...]:
    """Split one ``publisher_aliases`` cell into distinct alias entries.

    The cell is semicolon-separated; a single alias carries no delimiter. Empty
    or missing cells yield ``()``. Surrounding whitespace is trimmed and blank
    fragments are dropped, so a stray separator never yields an empty alias.
    """
    text = (value or "").strip()
    if not text:
        return ()
    return tuple(alias.strip() for alias in text.split(_ALIAS_DELIMITER) if alias.strip())


def _is_canonical_id(value: str) -> bool:
    return value in CANONICAL_DATASET_IDS


def _research_status(value: str | None) -> ResearchStatus | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return ResearchStatus(v)
    except ValueError as err:
        raise CanonicalDataError(f"invalid research_status value: {v!r}") from err


def _source_reliability(value: str | None) -> SourceReliability | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return SourceReliability(v)
    except ValueError as err:
        raise CanonicalDataError(f"invalid source_reliability value: {v!r}") from err


def _truthy_or_false(value: str | None) -> bool:
    v = (value or "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no", ""):
        return False
    raise CanonicalDataError(f"invalid boolean-ish value for license_verified: {value!r}")


def _int_or_none(value: str | None) -> int | None:
    v = (value or "").strip()
    if v == "UNKNOWN":
        return None
    if not v:
        return None
    try:
        n = int(v)
    except ValueError:
        raise CanonicalDataError(
            f"canonical metadata value is not an integer or UNKNOWN: {value!r}"
        ) from None
    if n < 0:
        raise CanonicalDataError(f"invalid negative integer value: {value!r}")
    return n


def _size_or_none(value: str | None) -> int | str | None:
    """Return an integer byte size when the cell is an integer, otherwise keep the
    documented size marker verbatim. ``UNKNOWN``/empty becomes ``None``.

    Unknown cells must be treated as ``None`` on the model, never as a string size
    marker, because :class:`CanonicalDatasetRecord.file_size` is typed ``int | None``
    and is compared numerically in ``__post_init__``. Any non-empty, non-UNKNOWN
    numeric value must resolve to a non-negative integer; a documented size marker
    that is not a plain integer is rejected so that :class:`CanonicalDatasetRecord`
    is never handed a non-integer file_size.
    """
    raw = (value or "").strip()
    if raw == "UNKNOWN":
        return None
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        raise CanonicalDataError(
            f"canonical metadata file_size is neither an integer nor UNKNOWN: {value!r}"
        ) from None
    if n < 0:
        raise CanonicalDataError(f"invalid negative integer value: {value!r}")
    return n
