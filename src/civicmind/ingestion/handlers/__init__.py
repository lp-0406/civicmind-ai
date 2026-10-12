"""Concrete ingestion handlers.

One handler per canonical dataset, each implementing the existing
:class:`~civicmind.ingestion.base.DatasetIngestor` contract. Handlers are built
explicitly through :func:`build_pilot_handler`, or all at once through
:func:`build_pilot_registry`; nothing here downloads anything at import time.

Identifiers
-----------
Handlers are looked up by canonical dataset id — either form is accepted
(``TRF-001`` or ``trf-001``), normalised once by
:mod:`civicmind.ingestion.identifiers` — and are registered under the slug
that :class:`~civicmind.ingestion.base.SourceDescriptor` requires. The
canonical id is what every downstream axis records.
"""

from __future__ import annotations

from pathlib import Path

from civicmind.ingestion.base import AcquisitionResult
from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.handlers.trf_001 import DATASET_ID as TRF_001_DATASET_ID
from civicmind.ingestion.handlers.trf_001 import SOURCE_ID as TRF_001_SOURCE_ID
from civicmind.ingestion.handlers.trf_001 import Trf001Ingestor
from civicmind.ingestion.handlers.trf_004 import DATASET_ID as TRF_004_DATASET_ID
from civicmind.ingestion.handlers.trf_004 import SOURCE_ID as TRF_004_SOURCE_ID
from civicmind.ingestion.handlers.trf_004 import Trf004Ingestor
from civicmind.ingestion.handlers.trf_005 import DATASET_ID as TRF_005_DATASET_ID
from civicmind.ingestion.handlers.trf_005 import SOURCE_ID as TRF_005_SOURCE_ID
from civicmind.ingestion.handlers.trf_005 import Wtr005LocalIngestor
from civicmind.ingestion.identifiers import canonical_dataset_id
from civicmind.ingestion.registry import IngestionRegistry
from civicmind.ingestion.transfer import TransferLimits

#: Canonical dataset ids that currently have a concrete handler.
SUPPORTED_DATASET_IDS: tuple[str, ...] = (
    TRF_001_DATASET_ID,
    TRF_004_DATASET_ID,
    TRF_005_DATASET_ID,
)


class UnsupportedDatasetError(IngestionError):
    """Raised when a dataset has no implemented ingestion handler."""


def build_pilot_handler(
    dataset_id: str,
    *,
    resource_url: str | None = None,
    limits: TransferLimits | None = None,
    clock: object = None,
    sleep: object = None,
) -> Trf001Ingestor | Trf004Ingestor | Wtr005LocalIngestor:
    """Return the handler for ``dataset_id``.

    ``dataset_id`` may be the canonical id or the source slug; both resolve to
    the same handler, so callers never have to know which namespace a caller
    site uses.

    ``resource_url`` exists so tests and future revisions can point the handler
    at a different endpoint without editing the module; production callers omit
    it and get the URL cited from the dataset preparation documentation.
    """
    canonical = canonical_dataset_id(dataset_id)
    if canonical == TRF_001_DATASET_ID:
        return Trf001Ingestor(resource_url=resource_url, limits=limits, clock=clock, sleep=sleep)
    if canonical == TRF_004_DATASET_ID:
        return Trf004Ingestor(resource_url=resource_url, limits=limits, clock=clock, sleep=sleep)
    if canonical == TRF_005_DATASET_ID:
        return Wtr005LocalIngestor()
    supported = ", ".join(SUPPORTED_DATASET_IDS)
    raise UnsupportedDatasetError(
        f"no ingestion handler is implemented for {dataset_id!r}; supported: {supported}"
    )


def build_pilot_registry() -> IngestionRegistry:
    """Return a fresh registry holding every handler this project ships.

    This is the explicit discovery path behind ``civicmind ingest list``. It
    builds new handler instances on each call and performs no I/O whatsoever:
    constructing a handler does not touch the network, and nothing here
    acquires, validates, profiles, or records state. Registration records
    metadata only, exactly as
    :meth:`civicmind.ingestion.registry.IngestionRegistry.register` documents.

    The WTR-005 handler is a local-artifact handler: listing it advertises that a
    local registration path exists, not that any bytes have been acquired.
    """
    registry = IngestionRegistry()
    for dataset_id in SUPPORTED_DATASET_IDS:
        registry.register(build_pilot_handler(dataset_id))
    return registry


def acquire_local_artifact(
    dataset_id: str,
    artifact_path: Path,
) -> AcquisitionResult:
    """Register an already-present local artifact under a supported canonical id.

    This is the small backward-compatible extension for Milestone 8: it measures
    the existing file and returns an ``AcquisitionResult`` shaped for the rest of
    the pilot, without inventing a download, a fetch URL, or a verified licence.

    ``artifact_path`` must name an existing regular file. This helper does not
    create or move any file; it only measures what is already there.

    Raises
    ------
    UnsupportedDatasetError
        When ``dataset_id`` has no local-artifact-capable handler.
    ValueError
        When ``artifact_path`` is not a readable file.
    """
    handler = build_pilot_handler(dataset_id)
    if not hasattr(handler, "acquire_local_artifact"):
        raise UnsupportedDatasetError(
            f"no local-artifact registration path for {dataset_id!r}; "
            f"supported local-artifact handlers: WTR-005 (wtr-005)"
        )
    return handler.acquire_local_artifact(artifact_path)


__all__ = [
    "SUPPORTED_DATASET_IDS",
    "TRF_001_DATASET_ID",
    "TRF_001_SOURCE_ID",
    "TRF_004_DATASET_ID",
    "TRF_004_SOURCE_ID",
    "TRF_005_DATASET_ID",
    "TRF_005_SOURCE_ID",
    "Trf001Ingestor",
    "Trf004Ingestor",
    "Wtr005LocalIngestor",
    "UnsupportedDatasetError",
    "build_pilot_handler",
    "build_pilot_registry",
    "acquire_local_artifact",
]
