"""Deterministic CSV profiling.

Profiling answers *what do the bytes contain* — a different question from
validation (*did the bytes pass our checks*) and from acquisition (*do we hold
the bytes*). The four-axis model keeps those axes independent, so this module
never sets a validation state and never reads one.

Guarantees
----------
* **Measured, not assumed.** Every number is computed from the file, and the
  file's byte size and SHA-256 are recorded with the profile so the
  measurements can be tied to one exact artifact version.
* **Deterministic.** No sampling randomness, no wall-clock dependence in the
  numbers themselves: the same bytes produce the same profile.
* **No row values.** Only column names, counts, types and statistics are
  emitted. Individual cell values are never recorded, logged or returned, so a
  profile can be reviewed or shared without leaking record contents.
* **Bounded.** At most ``max_rows`` data rows are examined; a truncated
  examination is labelled as such rather than presented as complete.
"""

from __future__ import annotations

import csv
import hashlib
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Bytes read per chunk while hashing the artifact.
HASH_CHUNK_SIZE = 64 * 1024
#: Upper bound on distinct values tracked per column, to keep memory bounded.
DISTINCT_TRACKING_LIMIT = 50_000
#: Recognised boolean literals.
_BOOLEAN_LITERALS = frozenset({"true", "false", "yes", "no"})
#: Date formats attempted, in order, for type inference.
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S")
#: A column above this empty share is reported as sparse.
_SPARSE_THRESHOLD = 50.0


class ProfileError(RuntimeError):
    """Raised when an artifact cannot be profiled at all."""


@dataclass(frozen=True)
class NumericSummary:
    """Descriptive statistics for a column inferred as numeric."""

    count: int
    minimum: float
    maximum: float
    mean: float
    median: float

    def as_dict(self) -> dict[str, float | int]:
        """Return a JSON-safe description."""
        return {
            "count": self.count,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "mean": self.mean,
            "median": self.median,
        }


@dataclass(frozen=True)
class ColumnProfile:
    """Per-column measurements. Contains no cell values."""

    name: str
    index: int
    inferred_type: str
    non_empty: int
    empty: int
    empty_percentage: float
    distinct: int
    distinct_capped: bool
    numeric: NumericSummary | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe description."""
        return {
            "name": self.name,
            "index": self.index,
            "inferred_type": self.inferred_type,
            "non_empty": self.non_empty,
            "empty": self.empty,
            "empty_percentage": self.empty_percentage,
            "distinct": self.distinct,
            "distinct_capped": self.distinct_capped,
            "numeric": None if self.numeric is None else self.numeric.as_dict(),
        }


@dataclass(frozen=True)
class CsvProfile:
    """One reproducible profile of one artifact."""

    path: str
    byte_size: int
    checksum_sha256: str
    encoding: str
    header: tuple[str, ...]
    column_count: int
    data_rows: int
    duplicate_rows: int
    ragged_rows: int
    columns: tuple[ColumnProfile, ...] = field(default_factory=tuple)
    parse_errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    sampled: bool = False
    max_rows: int | None = None
    generated_at: datetime | None = None

    @property
    def schema_version(self) -> int:
        """Profile document schema version, recorded in the output file."""
        return 1

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe profile document."""
        return {
            "schema_version": self.schema_version,
            "kind": "csv_profile",
            "generated_at": None if self.generated_at is None else self.generated_at.isoformat(),
            "artifact": {
                "path": self.path,
                "byte_size": self.byte_size,
                "checksum_sha256": self.checksum_sha256,
                "encoding": self.encoding,
            },
            "shape": {
                "header": list(self.header),
                "column_count": self.column_count,
                "data_rows": self.data_rows,
                "duplicate_rows": self.duplicate_rows,
                "ragged_rows": self.ragged_rows,
            },
            "columns": [column.as_dict() for column in self.columns],
            "parse_errors": list(self.parse_errors),
            "warnings": list(self.warnings),
            "sampled": self.sampled,
            "max_rows": self.max_rows,
        }


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_type(values: list[str]) -> str:
    """Infer a column type from the non-empty values it contains.

    The vocabulary is deliberately small and documented: ``empty`` (no
    non-empty values), ``integer``, ``number``, ``boolean``, ``date`` and
    ``text``. Mixed content falls back to ``text``.
    """
    candidates = [value.strip() for value in values if value.strip()]
    if not candidates:
        return "empty"
    if all(_is_integer(value) for value in candidates):
        return "integer"
    if all(_is_number(value) for value in candidates):
        return "number"
    if all(value.lower() in _BOOLEAN_LITERALS for value in candidates):
        return "boolean"
    if all(_is_date(value) for value in candidates):
        return "date"
    return "text"


def _is_integer(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _is_date(value: str) -> bool:
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
        except ValueError:
            continue
        return True
    return False


def _numeric_summary(values: list[str]) -> NumericSummary | None:
    """Return descriptive statistics for numeric values, or ``None`` when empty."""
    numbers: list[float] = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        try:
            numbers.append(float(stripped))
        except ValueError:
            continue
    if not numbers:
        return None
    return NumericSummary(
        count=len(numbers),
        minimum=min(numbers),
        maximum=max(numbers),
        mean=statistics.fmean(numbers),
        median=statistics.median(numbers),
    )


def profile_csv(
    path: Path,
    *,
    max_rows: int | None = None,
    clock: Any = _utc_now,
) -> CsvProfile:
    """Profile a CSV artifact and return measured, reproducible facts.

    Parameters
    ----------
    path:
        The artifact to measure.
    max_rows:
        When set, examine at most this many data rows and record the profile as
        ``sampled``. ``None`` examines every row.
    clock:
        Injectable clock for the profile timestamp.

    Raises
    ------
    ProfileError
        When the file is missing, empty, not valid UTF-8, or cannot be parsed
        as CSV at all.
    """
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"artifact not found: {path}")
    byte_size = path.stat().st_size
    if byte_size == 0:
        raise ProfileError(f"artifact is empty: {path}")

    warnings: list[str] = []
    parse_errors: list[str] = []
    columns_values: dict[int, list[str]] = {}
    distinct: dict[int, set[str]] = {}
    distinct_capped: dict[int, bool] = {}
    seen_rows: set[tuple[str, ...]] = set()
    duplicate_rows = 0
    ragged_rows = 0
    data_rows = 0
    header: tuple[str, ...] = ()
    sampled = False

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ProfileError(f"could not read {path}: {exc}") from exc

    with handle:
        # The standard library's real CSV reader, in strict mode: a malformed
        # record is reported rather than silently merged into its neighbour.
        reader = csv.reader(handle, strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration:
            raise ProfileError(f"artifact has no rows: {path}") from None
        except UnicodeDecodeError as exc:
            raise ProfileError(f"artifact is not valid UTF-8: {path}: {exc}") from exc
        except csv.Error as exc:
            raise ProfileError(f"artifact is not parseable as CSV: {path}: {exc}") from exc
        if not header:
            raise ProfileError(f"artifact has no header row: {path}")

        for index in range(len(header)):
            columns_values[index] = []
            distinct[index] = set()
            distinct_capped[index] = False

        try:
            for row in reader:
                if max_rows is not None and data_rows >= max_rows:
                    sampled = True
                    break
                data_rows += 1
                if len(row) != len(header):
                    ragged_rows += 1
                key = tuple(row)
                if key in seen_rows:
                    duplicate_rows += 1
                else:
                    seen_rows.add(key)
                for index in range(len(header)):
                    value = row[index] if index < len(row) else ""
                    columns_values[index].append(value)
                    if value.strip() and not distinct_capped[index]:
                        if len(distinct[index]) >= DISTINCT_TRACKING_LIMIT:
                            distinct_capped[index] = True
                        else:
                            distinct[index].add(value.strip())
        except csv.Error as exc:
            parse_errors.append(f"CSV parse error after {data_rows} data rows: {exc}")
        except UnicodeDecodeError as exc:
            parse_errors.append(f"decode error after {data_rows} data rows: {exc}")

    if data_rows == 0:
        warnings.append("no data rows after the header")
    if ragged_rows:
        warnings.append(f"{ragged_rows} row(s) do not match the header's {len(header)} field(s)")
    if duplicate_rows:
        warnings.append(f"{duplicate_rows} duplicate row(s) detected")
    if sampled:
        warnings.append(f"profile covers the first {max_rows} data row(s) only")

    columns: list[ColumnProfile] = []
    for index, name in enumerate(header):
        values = columns_values.get(index, [])
        non_empty = sum(1 for value in values if value.strip())
        empty = len(values) - non_empty
        inspected = len(values) or 1
        empty_percentage = round(empty * 100.0 / inspected, 4)
        inferred = infer_type(values)
        summary = _numeric_summary(values) if inferred in {"integer", "number"} else None
        if empty_percentage > _SPARSE_THRESHOLD:
            warnings.append(f"column {name!r} is sparse: {empty_percentage}% empty")
        columns.append(
            ColumnProfile(
                name=name,
                index=index,
                inferred_type=inferred,
                non_empty=non_empty,
                empty=empty,
                empty_percentage=empty_percentage,
                distinct=len(distinct.get(index, set())),
                distinct_capped=distinct_capped.get(index, False),
                numeric=summary,
            )
        )

    return CsvProfile(
        path=str(path),
        byte_size=byte_size,
        checksum_sha256=sha256_file(path),
        encoding="utf-8-sig",
        header=header,
        column_count=len(header),
        data_rows=data_rows,
        duplicate_rows=duplicate_rows,
        ragged_rows=ragged_rows,
        columns=tuple(columns),
        parse_errors=tuple(parse_errors),
        warnings=tuple(warnings),
        sampled=sampled,
        max_rows=max_rows,
        generated_at=clock(),
    )
