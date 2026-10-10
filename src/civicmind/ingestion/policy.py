"""Eligibility policy for canonical datasets.

Decides whether a registered canonical dataset may begin acquisition right now,
and why not. This is the explicit, documented gate between "we know about the
dataset" and "we will begin acquisition".

Policy is deliberately, transparently conservative:

* Unknown eligibility is not a free pass.
* A planning-rejected or replaced dataset must not start a new acquisition.
* Conditional datasets require **explicit authorization** with a rationale;
  there is no silent approval.
* Research decision is the authority for eligibility. Local axes 2/3/4 remain
  independent, and a record's local state never overrides its research decision.

This module introduces a small, project-consistent exception hierarchy for
eligibility failures, separate from the generic :mod:`civicmind.ingestion.exceptions`
hierarchy, so callers can distinguish "dataset not registered" from "registered
but not eligible" without catching broad exceptions.
"""

from __future__ import annotations

from civicmind.ingestion.catalog import DatasetRegistry
from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.metadata import CanonicalDatasetRecord, ResearchDecision


class EligibilityError(IngestionError):
    """Base class for eligibility decisions that prevent acquisition."""


class UnknownDatasetError(EligibilityError):
    """Raised when no canonical dataset is registered under ``dataset_id``."""


class DatasetNotEligibleError(EligibilityError):
    """Raised when a registered canonical dataset is not eligible to begin acquisition."""


class DuplicateRegistrationError(EligibilityError):
    """Raised when an operation would register a dataset that is already catalogued."""


class ConditionalApprovalRequiredError(DatasetNotEligibleError):
    """Raised when a ``CONDITIONAL`` dataset must be explicitly authorized before acquisition."""


class RejectedDatasetError(DatasetNotEligibleError):
    """Raised when a ``REJECT`` dataset must not begin acquisition."""


class ReplacedDatasetError(DatasetNotEligibleError):
    """Raised when a ``REPLACE`` dataset must not begin a new acquisition.


    A ``REPLACE`` dataset is a planning statement: the record itself is the one
    that is superseded; the candidate dataset id ``replacement_target`` stays
    separate and is recorded on the ``REPLACE`` review. This exception means
    *this* canonical record (the one under its own dataset id) is not a valid
    starting point for acquisition.
    """


def resolve_for_ingestion(registry: DatasetRegistry, dataset_id: str) -> CanonicalDatasetRecord:
    """Resolve a canonical dataset record and assert it is eligible to begin acquisition.

    Parameters
    ----------
    registry:
        Catalog to look the dataset up in.
    dataset_id:
        The canonical dataset id to resolve.

    Returns
    -------
    CanonicalDatasetRecord
        The canonical record for ``dataset_id``, ready for the existing ingestion
        contract.

    Raises
    ------
    UnknownDatasetError
        When ``dataset_id`` is not registered.
    RejectedDatasetError
        When the dataset's research decision is ``REJECT``, so it must not begin
        acquisition.
    ReplacedDatasetError
        When the dataset's research decision is ``REPLACE``, so *this* record
        must not begin a new acquisition.
    ConditionalApprovalRequiredError
        When the dataset's research decision is ``CONDITIONAL`` and no explicit
        eligibility authorization is present.
    """
    record = registry.get(dataset_id)
    decision = record.research_decision

    if decision is ResearchDecision.REJECT:
        raise RejectedDatasetError(
            f"Dataset {dataset_id!r} is research-decided REJECT and must not begin acquisition"
        )

    if decision is ResearchDecision.REPLACE:
        raise ReplacedDatasetError(_format_replaced_error(dataset_id, record.replacement_target))

    if decision is ResearchDecision.CONDITIONAL:
        raise ConditionalApprovalRequiredError(_format_conditional_error(dataset_id))

    return record


def _format_replaced_error(dataset_id: str, replacement_target: str | None) -> str:
    return (
        f"Dataset {dataset_id!r} is research-decided REPLACE and must not begin a new "
        f"acquisition (replacement_target={replacement_target!r})"
    )


def _format_conditional_error(dataset_id: str) -> str:
    return (
        f"Dataset {dataset_id!r} is research-decided CONDITIONAL and requires explicit "
        "eligibility authorization"
    )


class ConditionalAuthorization:
    """Explicit, documented authorization that a ``CONDITIONAL`` dataset may begin acquisition.

    A ``CONDITIONAL`` dataset is not silently eligible. This object is the explicit
    authorization that lifts it into the eligible set for one ingestion operation,
    with a recorded rationale.

    Example
    -------
    >>> policy.authorize_conditional(registry, "WST-001", rationale="...")
    """

    def __init__(self, rationale: str) -> None:
        if not rationale.strip():
            raise ValueError(
                "rationale must be non-empty; every conditional authorization is documented"
            )
        self._rationale = rationale.strip()

    @property
    def rationale(self) -> str:
        """The documented reason this conditional dataset is authorized for this operation."""
        return self._rationale


def resolve_conditional(
    registry: DatasetRegistry,
    dataset_id: str,
    *,
    authorization: ConditionalAuthorization | None = None,
) -> CanonicalDatasetRecord:
    """Resolve a ``CONDITIONAL`` canonical dataset for acquisition with explicit authorization.

    Parameters
    ----------
    registry:
        Catalog to look the dataset up in.
    dataset_id:
        The canonical dataset id to resolve.
    authorization:
        An explicit :class:`ConditionalAuthorization`. Omitting this when the
        dataset is ``CONDITIONAL`` raises :class:`ConditionalApprovalRequiredError`.

    Returns
    -------
    CanonicalDatasetRecord
        The canonical record, authorized for this ingestion operation.

    Raises
    ------
    UnknownDatasetError
        When ``dataset_id`` is not registered.
    ConditionalApprovalRequiredError
        When the dataset is ``CONDITIONAL`` and no authorization is provided.
    RejectedDatasetError, ReplacedDatasetError
        For the same eligibility reasons as :func:`resolve_for_ingestion`.
    """
    record = registry.get(dataset_id)
    decision = record.research_decision

    if decision is ResearchDecision.REJECT:
        raise RejectedDatasetError(
            f"Dataset {dataset_id!r} is research-decided REJECT and must not begin acquisition"
        )
    if decision is ResearchDecision.REPLACE:
        raise ReplacedDatasetError(_format_replaced_error(dataset_id, record.replacement_target))
    if decision is not ResearchDecision.CONDITIONAL:
        return record

    if authorization is None:
        raise ConditionalApprovalRequiredError(_format_conditional_error(dataset_id))

    return record
