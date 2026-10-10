"""Canonical dataset sources.

Version-controlled canonical metadata sources are loaded from here, separate
from the registry (which only records canonical records) and from the ingestion
contract (which only begins acquisition when explicitly authorized).

Public surface
--------------
* :func:`iter_canonical_csv_rows` / :func:`parse_canonical_metadata_csv` - the
  strict raw-CSV contract (header, field counts, unique IDs, enum vocabulary).
* :func:`load_canonical_metadata` - the same strict contract, converted into
  :class:`~civicmind.ingestion.metadata.CanonicalDatasetRecord` objects.
* :func:`load_canonical_registry` - the explicit CSV -> registry construction
  path used by the runtime entrypoint.

Nothing here is loaded as an import side effect: callers must ask for the
metadata explicitly, so importing the package never reads a file.
"""

from __future__ import annotations

from civicmind.ingestion.sources.canonical import (
    DEFAULT_CSV_PATH,
    EXPECTED_COLUMNS,
    CanonicalDataError,
    CanonicalMetadataError,
    CanonicalMetadataMissingError,
    load_canonical_metadata,
    load_canonical_registry,
)
from civicmind.ingestion.sources.csv_metadata import (
    CANONICAL_COLUMNS,
    CSV_PATH,
    CanonicalCSVError,
    CanonicalCSVRow,
    iter_canonical_csv_rows,
    parse_canonical_metadata_csv,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "CSV_PATH",
    "DEFAULT_CSV_PATH",
    "EXPECTED_COLUMNS",
    "CanonicalCSVError",
    "CanonicalCSVRow",
    "CanonicalDataError",
    "CanonicalMetadataError",
    "CanonicalMetadataMissingError",
    "iter_canonical_csv_rows",
    "load_canonical_metadata",
    "load_canonical_registry",
    "parse_canonical_metadata_csv",
]
