"""Tests for the canonical-id / source-slug mapping boundary.

The boundary is the only place either identifier form is converted into the
other, so these tests pin the conversion rules and, above all, the refusal to
guess at anything else.
"""

from __future__ import annotations

import pytest

from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.identifiers import (
    CANONICAL_DATASET_ID_PATTERN,
    SOURCE_SLUG_PATTERN,
    IdentifierError,
    canonical_dataset_id,
    canonical_dataset_id_or_none,
    source_slug,
)
from civicmind.ingestion.metadata import CANONICAL_DATASET_IDS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TRF-001", "TRF-001"),
        ("trf-001", "TRF-001"),
        (" Trf-001 ", "TRF-001"),
        ("trf-001 ", "TRF-001"),
        ("WTR-005", "WTR-005"),
        ("wtr-005", "WTR-005"),
    ],
)
def test_canonical_dataset_id_accepts_both_forms(value: str, expected: str) -> None:
    assert canonical_dataset_id(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "   ", "TRF", "TRF-1", "TRF-0012", "trf001", "traffic accidents", "TRF_001", "TRF-01"],
)
def test_canonical_dataset_id_refuses_to_guess(value: str) -> None:
    with pytest.raises(IdentifierError):
        canonical_dataset_id(value)


def test_identifier_error_is_an_ingestion_error() -> None:
    """The CLI reports :class:`IngestionError` cleanly, so the boundary must be one."""
    assert issubclass(IdentifierError, IngestionError)


def test_canonical_dataset_id_or_none_is_tolerant() -> None:
    assert canonical_dataset_id_or_none("trf-001") == "TRF-001"
    assert canonical_dataset_id_or_none("my-custom-handler") is None
    assert canonical_dataset_id_or_none("") is None


@pytest.mark.parametrize("dataset_id", sorted(CANONICAL_DATASET_IDS))
def test_every_canonical_id_has_a_filesystem_safe_slug(dataset_id: str) -> None:
    slug = source_slug(dataset_id)

    assert CANONICAL_DATASET_ID_PATTERN.match(dataset_id)
    assert SOURCE_SLUG_PATTERN.match(slug)
    assert slug.islower()
    assert "/" not in slug and "\\" not in slug
    assert canonical_dataset_id(slug) == dataset_id


def test_source_slug_accepts_either_form() -> None:
    assert source_slug("TRF-001") == "trf-001"
    assert source_slug("trf-001") == "trf-001"


def test_source_slug_refuses_non_identifiers() -> None:
    with pytest.raises(IdentifierError):
        source_slug("Solid Waste: State-wise Quantity")


def test_conversion_rather_than_comparison_separates_the_namespaces() -> None:
    """The two patterns can never match the same value, so equality cannot work."""
    assert CANONICAL_DATASET_ID_PATTERN.match("TRF-001")
    assert not CANONICAL_DATASET_ID_PATTERN.match("trf-001")
    assert SOURCE_SLUG_PATTERN.match("trf-001")
    assert not SOURCE_SLUG_PATTERN.match("TRF-001")


def test_every_site_that_identifies_a_dataset_uses_the_boundary() -> None:
    """Identity is normalised in one place, not re-derived at each call site."""
    for path in (
        "src/civicmind/ingestion/pilot.py",
        "src/civicmind/ingestion/integration.py",
        "src/civicmind/ingestion/handlers/trf_001.py",
        "src/civicmind/cli.py",
    ):
        source = _read(path)
        assert "civicmind.ingestion.identifiers" in source, (
            f"{path} must import the mapping boundary rather than compare ids itself"
        )


def _read(relative_path: str) -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    return (root / relative_path).read_text(encoding="utf-8")
