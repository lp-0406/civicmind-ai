"""The single mapping boundary between canonical dataset ids and source slugs.

Two identifier namespaces exist in this project and both are load-bearing:

* **Canonical dataset id** — ``TRF-001``. The identity of a dataset in
  ``configs/datasets/canonical_metadata.csv``, in the eligibility policy, in
  :class:`~civicmind.ingestion.metadata.CanonicalDatasetRecord`, in the four
  status axes, in the evidence document, in artifact directories, and in every
  CLI report. It is stable and is never rewritten.
* **Source slug** — ``trf-001``. What
  :class:`~civicmind.ingestion.base.SourceDescriptor` requires (a lowercase
  slug), what :class:`~civicmind.ingestion.registry.IngestionRegistry` keys
  handlers on, and what is safe in a filesystem path.

Why this module exists
----------------------
The two forms are *mutually exclusive* as raw values: a valid slug is not a
valid canonical id, and vice versa. Code that compared them with exact
equality could therefore never bind a real handler to a real canonical record
— ``prepare_ingestion`` could not accept the TRF-001 handler, because
``"trf-001" != "TRF-001"``. The previous workaround was to compare the two by
hand in whichever place needed it, which is exactly the scattered
``.lower()`` / ``.upper()`` this boundary is meant to prevent.

Rules
-----
* Matching, never inference: a value is only converted when it already has
  one of the two recognised shapes. An unrecognised identifier raises
  :class:`IdentifierError` rather than being guessed at.
* Case folding happens **only** here.
* The canonical id always survives: conversion to a slug is lossless in the
  direction that matters, because every canonical id lowercases into a valid
  slug, and the canonical form is recovered from the slug on demand.
* Nothing in this module performs I/O, resolves a registry, or mutates state.
"""

from __future__ import annotations

import re

from civicmind.ingestion.exceptions import IngestionError

#: Canonical dataset id: three uppercase letters, a hyphen, three digits.
#: Deliberately identical to :data:`civicmind.ingestion.metadata.DATASET_ID_PATTERN`.
CANONICAL_DATASET_ID_PATTERN = re.compile(r"^[A-Z]{3}-\d{3}$")

#: Ingestion-registry slug: lowercase letters, digits, '.', '_' and '-', as
#: required by :class:`civicmind.ingestion.base.SourceDescriptor`.
SOURCE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class IdentifierError(IngestionError):
    """Raised when a value is neither a canonical dataset id nor a source slug."""


def canonical_dataset_id(value: str) -> str:
    """Return the canonical dataset id for ``value``.

    Accepts either form — ``"TRF-001"`` or ``"trf-001"`` — and returns the
    canonical id, so callers can normalise once at their entry point and then
    treat the canonical id as the only identity that exists.

    Raises
    ------
    IdentifierError
        When ``value`` matches neither recognised shape.
    """
    candidate = (value or "").strip()
    if CANONICAL_DATASET_ID_PATTERN.match(candidate):
        return candidate
    folded = candidate.upper()
    if CANONICAL_DATASET_ID_PATTERN.match(folded):
        return folded
    raise IdentifierError(
        f"{value!r} is neither a canonical dataset id like 'TRF-001' "
        f"nor a source slug like 'trf-001'"
    )


def canonical_dataset_id_or_none(value: str) -> str | None:
    """Return the canonical id for ``value``, or ``None`` when it is not one.

    For listings and reports, where a caller-registered handler may legitimately
    use a slug that is not a canonical id and must still be displayed.
    """
    try:
        return canonical_dataset_id(value)
    except IdentifierError:
        return None


def source_slug(dataset_id: str) -> str:
    """Return the filesystem-safe ingestion-registry slug for ``dataset_id``.

    Accepts either form and always returns the lowercase slug. Every canonical
    id lowercases into a valid slug, so this cannot fail for a valid id; it
    raises for anything that is not a dataset identifier at all.
    """
    canonical = canonical_dataset_id(dataset_id)
    return canonical.lower()


__all__ = [
    "CANONICAL_DATASET_ID_PATTERN",
    "IdentifierError",
    "SOURCE_SLUG_PATTERN",
    "canonical_dataset_id",
    "canonical_dataset_id_or_none",
    "source_slug",
]
