"""Registry-guided ingestion integration.

This module connects the canonical dataset catalog (:mod:`civicmind.ingestion.catalog`)
and the eligibility policy (:mod:`civicmind.ingestion.policy`) to the existing
:class:`DatasetIngestor` contract (:mod:`civicmind.ingestion.base`).

The integration itself performs **no acquisition**. Its job is to resolve the
canonical dataset record and assert eligibility *before* any acquisition is
attempted, then hand the resolved record and an authorized ingestor to the
existing contract. Actual acquisition, validation, provenance, and artifact
versioning happen through the existing :class:`CanonicalDatasetRecord` methods
and :mod:`civicmind.ingestion.metadata`.

Design rules
------------
* No acquisition happens here. This module resolves state and authorizes only.
* Eligibility is authoritative from the registry's canonical record's
  :attr:`CanonicalDatasetRecord.research_decision`. Local axes 2/3/4 are
  independent and never override eligibility.
* ``REJECT`` and ``REPLACE`` must not begin a new acquisition.
* ``CONDITIONAL`` datasets require an explicit :class:`ConditionalAuthorization`;
  there is no silent approval.
* A successful acquisition records the real artifact and provenance through the
  existing :class:`CanonicalDatasetRecord` methods; no status is inferred from
  a source URL or a registry entry.
"""

from __future__ import annotations

from civicmind.ingestion.base import DatasetIngestor
from civicmind.ingestion.catalog import (
    DatasetRegistry,
    UnknownDatasetError,
)
from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.metadata import CanonicalDatasetRecord
from civicmind.ingestion.policy import (
    ConditionalApprovalRequiredError,
    ConditionalAuthorization,
    RejectedDatasetError,
    ReplacedDatasetError,
    resolve_conditional,
)


class RegistryIntegrationError(IngestionError):
    """Base class for registry integration failures."""


class DatasetNotRegisteredError(RegistryIntegrationError):
    """Raised when a dataset id is not registered in the catalog."""


def resolve_dataset_for_ingestion(
    registry: DatasetRegistry,
    dataset_id: str,
    *,
    authorization: ConditionalAuthorization | None = None,
) -> CanonicalDatasetRecord:
    """Resolve a canonical dataset record and assert eligibility to begin acquisition.

    This is the single entry point for "can we start ingesting this canonical
    dataset right now?":

    * Unknown id → :class:`DatasetNotRegisteredError` (wraps :class:`UnknownDatasetError`).
    * ``REJECT`` research decision → must not begin acquisition.
    * ``REPLACE`` research decision → must not begin a new acquisition.
    * ``CONDITIONAL`` research decision → requires an explicit
      :class:`ConditionalAuthorization`, otherwise raises
      :class:`ConditionalApprovalRequiredError`.

    Returns the canonical record. It does **not** change any status axis.

    Parameters
    ----------
    registry:
        Catalog to look the dataset up in.
    dataset_id:
        Canonical dataset id to resolve.
    authorization:
        Required when the dataset is ``CONDITIONAL``. Optional for eligible
        (``KEEP``, ``KEEP_WITH_CHUNKING``) datasets; supplied anyway when the
        caller wants an explicit authorization trail.

    Returns
    -------
    CanonicalDatasetRecord
        The resolved canonical record, eligible for this ingestion operation.

    Raises
    ------
    DatasetNotRegisteredError
        When the id is not in the catalog.
    RejectedDatasetError
        When the dataset is research-decided ``REJECT``.
    ReplacedDatasetError
        When the dataset is research-decided ``REPLACE``.
    ConditionalApprovalRequiredError
        When the dataset is ``CONDITIONAL`` and no authorization is provided.
    """
    try:
        record = resolve_conditional(registry, dataset_id, authorization=authorization)
    except UnknownDatasetError as exc:
        raise DatasetNotRegisteredError(str(exc)) from exc
    except (RejectedDatasetError, ReplacedDatasetError, ConditionalApprovalRequiredError):
        raise
    else:
        return record


def prepare_ingestion(
    registry: DatasetRegistry,
    ingestor: DatasetIngestor,
    *,
    authorization: ConditionalAuthorization | None = None,
) -> CanonicalDatasetRecord:
    """Prepare a registry-guided ingestion between a canonical record and an ingestor.

    This is the integration point used by callers that already have a concrete
    :class:`DatasetIngestor` bound to a canonical dataset id. It resolves the
    canonical record, asserts eligibility, and verifies the ingestor's
    ``source_id`` matches the canonical dataset id before any acquisition is
    attempted.

    The ingestor itself is **not** run here. Run :meth:`DatasetIngestor.acquire`
    (or :meth:`DatasetIngestor.ingest`) on the returned ingestor afterward, then
    record the actual result through the canonical record's existing methods.

    Parameters
    ----------
    registry:
        Catalog this dataset lives in.
    ingestor:
        Concrete :class:`DatasetIngestor` bound to the canonical dataset id.
    authorization:
        Required when the canonical dataset is ``CONDITIONAL``.

    Returns
    -------
    CanonicalDatasetRecord
        The resolved, eligible canonical record.

    Raises
    ------
    RegistryIntegrationError
        For eligibility or registration problems, including an ingestor whose
        ``source_id`` does not match the canonical dataset id.
    """
    record = resolve_dataset_for_ingestion(
        registry, ingestor.source_id, authorization=authorization
    )
    if record.dataset_id != ingestor.source_id:
        raise RegistryIntegrationError(
            f"Ingestor source_id {ingestor.source_id!r} does not match resolved canonical "
            f"dataset id {record.dataset_id!r}"
        )
    return record
