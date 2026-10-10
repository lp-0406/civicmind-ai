"""Parse and validate the canonical dataset metadata CSV.

Provides a small, explicit loader for ``configs/datasets/canonical_metadata.csv``
that exposes a clear contract for tests and for the canonical ingestion sources
module: row length is enforced strictly, and corrupt/malformed rows are rejected
with a descriptive error instead of being silently shifted into the wrong columns.

Design notes
------------
* The CSV is authoritative for historical/planning metadata (titles, publishers,
  portal URLs, research_status, source_reliability, notes, source_replaced_from),
  not for local acquisition evidence. Local evidence lives in
  :class:`CanonicalDatasetRecord` instances and is recorded through the four-axis
  model in :mod:`civicmind.ingestion.metadata`.
* ``UNKNOWN`` is the canonical marker for "not yet known / not yet measured";
  empty strings are treated as unknown as well so that both representations mean
  the same thing to callers.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

#: Default location of the version-controlled metadata file: ``<repo>/configs/datasets/``.
#: ``parents[0]`` is this module's directory (``sources/``), so four more levels up is
#: the repository root for the standard ``src/`` layout.
CSV_PATH = Path(__file__).resolve().parents[4] / "configs" / "datasets" / "canonical_metadata.csv"

#: Column names in the order they appear in the canonical metadata CSV.
CANONICAL_COLUMNS = (
    "dataset_id",
    "title",
    "domain",
    "publisher",
    "short_title",
    "subdomain",
    "publisher_aliases",
    "publisher_url",
    "dataset_url",
    "download_url",
    "license",
    "license_verified",
    "format",
    "temporal_coverage",
    "spatial_coverage",
    "geographic_granularity",
    "record_count",
    "file_size",
    "research_status",
    "source_reliability",
    "source_reliability_notes",
    "source_replaced_from",
    "notes",
)

#: Values that mean "unknown / not yet measured" for the purposes of integrity checks.
_UNKNOWN_VALUES = frozenset({"UNKNOWN", ""})


class CanonicalCSVRow(NamedTuple):
    """One validated row from the canonical metadata CSV, keyed by column name."""

    dataset_id: str
    title: str
    domain: str
    publisher: str
    short_title: str
    subdomain: str
    publisher_aliases: str
    publisher_url: str
    dataset_url: str
    download_url: str
    license: str
    license_verified: str
    format: str
    temporal_coverage: str
    spatial_coverage: str
    geographic_granularity: str
    record_count: str
    file_size: str
    research_status: str
    source_reliability: str
    source_reliability_notes: str
    source_replaced_from: str
    notes: str


class CanonicalCSVError(Exception):
    """Raised when the canonical metadata CSV is malformed or fails validation."""


def _is_unknown(value: str) -> bool:
    """Return True for values that represent unknown/measured-out data."""
    return value in _UNKNOWN_VALUES


def iter_canonical_csv_rows(path: Path = CSV_PATH) -> Iterator[CanonicalCSVRow]:
    """Strictly parse and validate the CSV, yielding one row per data record.

    This is the single implementation of the canonical CSV contract. The header
    must match :data:`CANONICAL_COLUMNS` exactly, every data row must have the
    same number of fields as the header, dataset IDs must be present and unique,
    and enum-like fields must hold a recognised value. A malformed row raises
    instead of being shifted silently into the wrong columns.

    Raises
    ------
    CanonicalCSVError
        When the file is missing/empty, the header does not match, a row has the
        wrong number of fields, a dataset ID is missing or duplicated, or an
        enum-like field contains an unexpected value.
    """
    if not path.exists():
        raise CanonicalCSVError(f"canonical metadata CSV not found at {path}")

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise CanonicalCSVError(f"canonical metadata CSV at {path} is empty") from None

        if header != list(CANONICAL_COLUMNS):
            raise CanonicalCSVError(
                f"canonical metadata CSV header mismatch.\n"
                f"expected: {list(CANONICAL_COLUMNS)}\n"
                f"got:      {header}"
            )

        seen_ids: set[str] = set()

        for line_no, row in enumerate(reader, start=2):
            if len(row) != len(CANONICAL_COLUMNS):
                raise CanonicalCSVError(
                    f"canonical metadata CSV row {line_no} has {len(row)} fields; "
                    f"expected {len(CANONICAL_COLUMNS)}. Malformed quoting/column shift "
                    f"detected — do not attempt to interpret shifted values.\n"
                    f"row: {row}"
                )

            record = CanonicalCSVRow(*[str(v) for v in row])
            if not record.dataset_id.strip():
                raise CanonicalCSVError(
                    f"canonical metadata CSV row {line_no}: missing dataset_id"
                )

            if record.dataset_id in seen_ids:
                raise CanonicalCSVError(
                    f"canonical metadata CSV row {line_no}: duplicate dataset_id "
                    f"{record.dataset_id!r}"
                )
            seen_ids.add(record.dataset_id)

            _validate_row(record, line_no)
            yield record


def parse_canonical_metadata_csv(path: Path = CSV_PATH) -> list[CanonicalCSVRow]:
    """Parse and validate the canonical metadata CSV, in file order.

    Eager wrapper over :func:`iter_canonical_csv_rows`; see that function for
    the validation contract it enforces.
    """
    return list(iter_canonical_csv_rows(path))


def _validate_row(record: CanonicalCSVRow, line_no: int) -> None:
    """Validate enum-like and required fields on a single parsed row."""
    if not record.title.strip():
        raise CanonicalCSVError(
            f"canonical metadata CSV row {line_no} ({record.dataset_id}): title must be non-empty"
        )

    if record.research_status not in _VALID_RESEARCH_STATUS:
        raise CanonicalCSVError(
            f"canonical metadata CSV row {line_no} ({record.dataset_id}): "
            f"invalid research_status {record.research_status!r}; "
            f"expected one of {_VALID_RESEARCH_STATUS}"
        )

    if record.source_reliability not in _VALID_SOURCE_RELIABILITY:
        raise CanonicalCSVError(
            f"canonical metadata CSV row {line_no} ({record.dataset_id}): "
            f"invalid source_reliability {record.source_reliability!r}; "
            f"expected one of {_VALID_SOURCE_RELIABILITY}"
        )

    if record.license_verified not in _VALID_BOOLEAN_TEXT:
        raise CanonicalCSVError(
            _format_license_verified_error(line_no, record.dataset_id, record.license_verified)
        )

    if not _is_unknown(record.record_count) and not _looks_like_unknown_or_int(
        record.record_count
    ):
        raise CanonicalCSVError(
            _format_record_count_error(line_no, record.dataset_id, record.record_count)
        )

    if not _is_unknown(record.file_size) and not _looks_like_unknown_or_int(record.file_size):
        raise CanonicalCSVError(
            _format_file_size_error(line_no, record.dataset_id, record.file_size)
        )


def _format_license_verified_error(line_no: int, dataset_id: str, value: str) -> str:
    return (
        f"canonical metadata CSV row {line_no} ({dataset_id}): "
        f"invalid license_verified {value!r}; expected one of {_VALID_BOOLEAN_TEXT}"
    )


def _format_record_count_error(line_no: int, dataset_id: str, value: str) -> str:
    return (
        f"canonical metadata CSV row {line_no} ({dataset_id}): "
        f"record_count {value!r} is neither UNKNOWN/empty nor an integer-like value"
    )


def _format_file_size_error(line_no: int, dataset_id: str, value: str) -> str:
    return (
        f"canonical metadata CSV row {line_no} ({dataset_id}): "
        f"file_size {value!r} is neither UNKNOWN/empty nor a non-negative integer "
        f"(CanonicalDatasetRecord.file_size is int | None; documented size prose "
        f"belongs in source_reliability_notes or notes)"
    )


def _looks_like_unknown_or_int(value: str) -> bool:
    """Return True when *value* is unknown, empty, or a non-negative integer.

    Used for both ``record_count`` and ``file_size``: the model types both as
    ``int | None``, so a documented value that is not a plain non-negative
    integer (for example ``'42.3 MiB (approx.)'``) is not representable and is
    rejected here rather than silently handed to the model. Documented size prose
    belongs in ``notes``/``source_reliability_notes``.
    """
    if _is_unknown(value):
        return True
    stripped = value.strip()
    if not stripped:
        return True
    try:
        return int(stripped) >= 0
    except ValueError:
        return False


_VALID_RESEARCH_STATUS = frozenset({"ACQUIRED", "VERIFIED", "CANDIDATE", "REJECTED"})
_VALID_SOURCE_RELIABILITY = frozenset({"VERY_HIGH", "HIGH", "MEDIUM"})
_VALID_BOOLEAN_TEXT = frozenset({"true", "false"})
