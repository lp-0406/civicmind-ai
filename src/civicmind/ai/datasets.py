"""Local dataset specifications and an encoding-safe CSV loader.

The five supplied CSVs are described here declaratively - identity, grain,
coverage, encodings, the identifier column, known quality issues and mapping
status - so every downstream module reads the same facts instead of
re-discovering them.

Loading rules:

* Original source files are never modified; loading is read-only.
* Original column names are preserved verbatim (including the trailing space in
  the water file's ``Ward number `` column). Lookups go through
  :func:`find_column`, which normalises for *matching only*.
* Encoding is resolved by trying the dataset's declared candidates in order, so
  ``RA2019_A52.csv`` (which is not valid UTF-8) loads via cp1252 without any
  ad-hoc special case at the call site.
* ``NA`` and empty strings load as missing values, never as zero.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civicmind.ai.evidence import Evidence

try:  # pandas is an analytics dependency; import failure is reported lazily.
    import pandas as pd
except ImportError as exc:  # pragma: no cover - pandas is a declared dependency
    raise ImportError(
        "pandas is required for the analytics engine; install with 'pip install pandas'"
    ) from exc

#: Row labels that are aggregates rather than observations.
TOTAL_ROW_LABELS: frozenset[str] = frozenset({"total"})

_UTF8_CANDIDATES: tuple[str, ...] = ("utf-8-sig", "utf-8")


class UnavailableDatasetError(FileNotFoundError):
    """Raised when a dataset's source file is not present under ``data/raw``."""


class MalformedDatasetError(ValueError):
    """Raised when a source file has rows that do not match its header width.

    A short row would otherwise be silently padded with missing values by the
    parser, which can quietly drop a figure from a total or shift a column. The
    loader refuses such a file rather than computing from shifted data.
    """


@dataclass(frozen=True)
class LocalDatasetSpec:
    """Declarative description of one supplied local dataset."""

    dataset_id: str
    filename: str
    title: str
    description: str
    canonical_id: str | None
    mapping_status: str
    license_status: str
    geographic_scope: str
    geographic_granularity: str
    time_period: str
    id_column: str
    encodings: tuple[str, ...]
    known_issues: tuple[str, ...]
    default_limitations: tuple[str, ...]

    def quality_issues(self) -> tuple[str, ...]:
        """Return the declared quality issues for this dataset."""
        return self.known_issues


# ---------------------------------------------------------------------------
# The five supplied datasets.
# ---------------------------------------------------------------------------

_RA_NA_LIMITATION = (
    "Rank columns contain 'NA' for non-ranked rows; 'NA' is treated as missing, never zero."
)

DATASET_SPECS: dict[str, LocalDatasetSpec] = {
    "RA2019_A2": LocalDatasetSpec(
        dataset_id="RA2019_A2",
        filename="RA2019_A2.csv",
        title="State/UT-wise total road accidents in India, 2016-2019",
        description=(
            "State and Union-Territory road-accident totals for 2016-2019, with published "
            "rank and share columns. The final row is a national 'Total' aggregate."
        ),
        canonical_id=None,
        mapping_status="unverified",
        license_status="unverified",
        geographic_scope="India (states and union territories)",
        geographic_granularity="State/UT",
        time_period="2016-2019 (stated in column headers)",
        id_column="States/UTs",
        encodings=_UTF8_CANDIDATES,
        known_issues=(
            "The final 'Total ' row is a national aggregate, not a state observation.",
            "Shares are already on a 0-100 scale; the national share row sums to 100.",
            _RA_NA_LIMITATION,
        ),
        default_limitations=(
            "Counts are as reported by the source; reporting coverage varies by state.",
            "No causal inference is drawn from these descriptive totals.",
        ),
    ),
    "RA2019_A47": LocalDatasetSpec(
        dataset_id="RA2019_A47",
        filename="RA2019_A47.csv",
        title="City/UT-wise road accidents by violation type, 2019",
        description=(
            "City-level accident, killed and injured counts broken down by driving "
            "violation (over-speeding, drunken driving, wrong side, red light, mobile phone, "
            "others). The final row is an aggregate."
        ),
        canonical_id=None,
        mapping_status="unverified",
        license_status="unverified",
        geographic_scope="India (reporting cities and UTs)",
        geographic_granularity="City/UT",
        time_period="2019 (single-year snapshot)",
        id_column="States/UTs",
        encodings=_UTF8_CANDIDATES,
        known_issues=(
            "The final 'Total' row is an aggregate, not a city observation.",
            "The identifier column is named 'States/UTs' but holds city names.",
            _RA_NA_LIMITATION,
        ),
        default_limitations=(
            "Descriptive violation counts are not evidence of causation.",
            "City coverage and reporting practice are not uniform.",
        ),
    ),
    "RA2019_A49": LocalDatasetSpec(
        dataset_id="RA2019_A49",
        filename="RA2019_A49.csv",
        title="City/UT-wise road accidents by junction type, 2019",
        description=(
            "City-level accident, killed and injured counts broken down by junction "
            "category (T-, Y-, four-arm, staggered, roundabout, others). The final row is "
            "an aggregate."
        ),
        canonical_id=None,
        mapping_status="unverified",
        license_status="unverified",
        geographic_scope="India (reporting cities and UTs)",
        geographic_granularity="City/UT",
        time_period="2019 (single-year snapshot)",
        id_column="States/UTs",
        encodings=_UTF8_CANDIDATES,
        known_issues=(
            "The final 'Total' row is an aggregate, not a city observation.",
            "The identifier column is named 'States/UTs' but holds city names.",
            _RA_NA_LIMITATION,
        ),
        default_limitations=(
            "Junction categories are source classifications, not causal findings.",
            "City coverage and reporting practice are not uniform.",
        ),
    ),
    "RA2019_A52": LocalDatasetSpec(
        dataset_id="RA2019_A52",
        filename="RA2019_A52.csv",
        title="High-accident-prone locations (blackspots), 2016-2018",
        description=(
            "Station-level list of high-accident-prone locations with 2016-2018 accident and "
            "fatality counts. Geographic detail is police-station/location, not a city "
            "aggregate."
        ),
        canonical_id=None,
        mapping_status="unverified",
        license_status="unverified",
        geographic_scope="India (multiple states), station/location level",
        geographic_granularity="Police station / location",
        time_period="2016-2018 (stated in column headers)",
        id_column="Name of Location Place",
        encodings=("cp1252", "latin-1", *_UTF8_CANDIDATES),
        known_issues=(
            "The file is not valid UTF-8; it is decoded as Windows-1252 (cp1252).",
            "Records are station/location level and must not be treated as a city or state "
            "aggregate.",
            "This is a national blackspot list, not Bengaluru station-wise crash data.",
        ),
        default_limitations=(
            "Blackspot membership reflects the source's selection, not an independent risk model.",
            "Not joinable as a numeric key to the city/state accident tables.",
        ),
    ),
    "BWSSB_WATER": LocalDatasetSpec(
        dataset_id="BWSSB_WATER",
        filename="BWSSB_Water_Consumption_August_2025.csv",
        title="BWSSB ward-wise water connections and consumption, August 2025",
        description=(
            "Bengaluru ward-level water connection counts and consumption for a single month "
            "(August 2025). Registered locally as a WTR-005 candidate."
        ),
        canonical_id="WTR-005",
        mapping_status="plausible but unverified",
        license_status="unverified (cited source claim only)",
        geographic_scope="Bengaluru wards",
        geographic_granularity="Ward",
        time_period="August 2025 (single-month snapshot)",
        id_column="Ward Name",
        encodings=_UTF8_CANDIDATES,
        known_issues=(
            "Ward number and ward name are not 1:1 in this snapshot (for example ward 85 and "
            "ward 149 are both named 'Varthur').",
            "Ward identifiers are preserved verbatim; no crosswalk is invented.",
            "The value is consumption, not demand.",
            "The 'Ward number ' column name carries a trailing space in the source.",
        ),
        default_limitations=(
            "A single August 2025 month; this is not current or annual consumption.",
            "Consumption is not demand and implies nothing about unmet supply.",
        ),
    ),
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedDataset:
    """A loaded dataset together with the facts needed to cite it."""

    spec: LocalDatasetSpec
    path: Path
    dataframe: pd.DataFrame
    encoding: str
    byte_size: int

    @property
    def dataset_id(self) -> str:
        """Return the local dataset key."""
        return self.spec.dataset_id

    @property
    def source_file(self) -> str:
        """Return the repository-relative source path."""
        return f"data/raw/{self.spec.filename}"

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the original column names, verbatim."""
        return tuple(str(column) for column in self.dataframe.columns)


def normalize_column_name(name: str) -> str:
    """Normalise a column name for *matching only* (case/whitespace-insensitive)."""
    return " ".join(str(name).replace("\ufeff", "").split()).casefold()


def find_column(dataframe: pd.DataFrame, name: str) -> str:
    """Return the actual column matching ``name``, or raise ``KeyError``.

    Matching ignores case, surrounding whitespace and internal whitespace runs,
    which is how the water file's ``Ward number `` column is found without
    renaming the original.
    """
    wanted = normalize_column_name(name)
    for column in dataframe.columns:
        if normalize_column_name(column) == wanted:
            return str(column)
    available = ", ".join(str(column) for column in dataframe.columns)
    raise KeyError(f"no column matching {name!r}; available columns: {available}")


def find_columns_containing(dataframe: pd.DataFrame, *needles: str) -> list[str]:
    """Return columns whose normalised name contains every normalised needle."""
    wanted = [normalize_column_name(needle) for needle in needles]
    matches: list[str] = []
    for column in dataframe.columns:
        normalized = normalize_column_name(column)
        if all(needle in normalized for needle in wanted):
            matches.append(str(column))
    return matches


def read_text_with_fallback(path: Path, encodings: tuple[str, ...]) -> tuple[str, str]:
    """Decode ``path`` using the first encoding that succeeds.

    Returns ``(text, encoding)``. Raises :class:`UnicodeDecodeError` when every
    candidate fails, so an unreadable file is reported rather than guessed at.
    """
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    assert last_error is not None  # encodings is non-empty by construction
    raise last_error


def load_raw_text(settings: Any, dataset_id: str) -> tuple[str, str, Path]:
    """Return ``(text, encoding, path)`` for a dataset without pandas parsing."""
    spec = get_spec(dataset_id)
    path = dataset_path(settings, dataset_id)
    text, encoding = read_text_with_fallback(path, spec.encodings)
    return text, encoding, path


def get_spec(dataset_id: str) -> LocalDatasetSpec:
    """Return the spec for ``dataset_id`` (accepting the water canonical alias)."""
    if dataset_id in DATASET_SPECS:
        return DATASET_SPECS[dataset_id]
    normalized = dataset_id.strip().casefold().replace("-", "_")
    if normalized in {"wtr_005", "bwssb", "water", "bwssb_water"}:
        return DATASET_SPECS["BWSSB_WATER"]
    known = ", ".join(sorted(DATASET_SPECS))
    raise KeyError(f"unknown dataset {dataset_id!r}; known datasets: {known}")


def dataset_path(settings: Any, dataset_id: str) -> Path:
    """Return the absolute path of a dataset's CSV under the configured raw dir."""
    spec = get_spec(dataset_id)
    return Path(settings.raw_data_dir) / spec.filename


def list_dataset_specs() -> tuple[LocalDatasetSpec, ...]:
    """Return every declared dataset spec, in declaration order."""
    return tuple(DATASET_SPECS.values())


def available_datasets(settings: Any) -> tuple[LocalDatasetSpec, ...]:
    """Return the specs whose source files exist under the configured raw dir."""
    return tuple(
        spec for spec in list_dataset_specs() if dataset_path(settings, spec.dataset_id).is_file()
    )


def load_dataset(settings: Any, dataset_id: str) -> LoadedDataset:
    """Load a dataset as a DataFrame, preserving original column names.

    ``NA`` and empty fields become missing values (``NaN``), never zero. Callers
    convert to numeric explicitly with :func:`numeric_series`.
    """
    spec = get_spec(dataset_id)
    path = dataset_path(settings, dataset_id)
    if not path.is_file():
        raise UnavailableDatasetError(
            f"dataset {spec.dataset_id!r} is not present at {path}; "
            f"place the raw CSV under the configured data/raw directory"
        )
    text, encoding = read_text_with_fallback(path, spec.encodings)
    _assert_consistent_rows(text, spec, path)
    dataframe = pd.read_csv(
        io.StringIO(text),
        dtype=str,
        keep_default_na=False,
        na_values=["", "NA", "N/A", "na"],
    )
    return LoadedDataset(
        spec=spec,
        path=path,
        dataframe=dataframe,
        encoding=encoding,
        byte_size=path.stat().st_size,
    )


def numeric_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
    """Return ``column`` coerced to numeric, with unparsable/``NA`` values as NaN.

    Missing values stay missing. They are never silently coerced to zero.
    """
    actual = find_column(dataframe, column)
    return pd.to_numeric(dataframe[actual], errors="coerce")


def is_total_row(label: Any) -> bool:
    """Return True when a row label denotes an aggregate 'Total' row."""
    if label is None:
        return False
    return normalize_column_name(str(label)) in TOTAL_ROW_LABELS


def observations_only(loaded: LoadedDataset) -> pd.DataFrame:
    """Return the dataset's rows with aggregate 'Total' rows removed."""
    dataframe = loaded.dataframe
    id_column = find_column(dataframe, loaded.spec.id_column)
    mask = ~dataframe[id_column].map(is_total_row)
    return dataframe[mask].copy()


def build_evidence(
    loaded: LoadedDataset,
    *,
    operation: str,
    units: str,
    record_count: int,
    columns: tuple[str, ...] = (),
    supporting_records: tuple[dict[str, Any], ...] = (),
    quality_issues: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    time_period: str | None = None,
    geographic_scope: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Evidence:
    """Assemble an :class:`Evidence` object from a loaded dataset and findings."""
    spec = loaded.spec
    return Evidence(
        dataset_id=spec.dataset_id,
        source_file=loaded.source_file,
        canonical_id=spec.canonical_id,
        operation=operation,
        units=units,
        time_period=time_period or spec.time_period,
        geographic_scope=geographic_scope or spec.geographic_scope,
        record_count=record_count,
        columns=columns,
        supporting_records=supporting_records,
        quality_issues=tuple(quality_issues) or spec.known_issues,
        limitations=tuple(limitations) or spec.default_limitations,
        mapping_status=spec.mapping_status,
        license_status=spec.license_status,
        extra=extra or {},
    )


def _assert_consistent_rows(text: str, spec: LocalDatasetSpec, path: Path) -> None:
    """Raise :class:`MalformedDatasetError` when any row's width differs from the header's.

    Blank lines are ignored; a quoted field containing a newline is handled by
    the CSV reader and does not count as a mismatch.
    """
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise MalformedDatasetError(f"{path} is empty") from None
    width = len(header)
    offenders = [
        line_no for line_no, row in enumerate(reader, start=2) if row and len(row) != width
    ]
    if offenders:
        shown = ", ".join(str(line) for line in offenders[:5])
        raise MalformedDatasetError(
            f"{spec.filename} has {len(offenders)} row(s) that do not match the "
            f"{width}-field header (lines: {shown}); refusing to parse shifted rows"
        )


__all__ = [
    "DATASET_SPECS",
    "TOTAL_ROW_LABELS",
    "LoadedDataset",
    "LocalDatasetSpec",
    "MalformedDatasetError",
    "UnavailableDatasetError",
    "available_datasets",
    "build_evidence",
    "dataset_path",
    "find_column",
    "find_columns_containing",
    "get_spec",
    "is_total_row",
    "list_dataset_specs",
    "load_dataset",
    "load_raw_text",
    "normalize_column_name",
    "numeric_series",
    "observations_only",
    "read_text_with_fallback",
]
