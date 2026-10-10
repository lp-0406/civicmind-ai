"""Canonical dataset registry.

A non-global, evidence-first catalog of :class:`CanonicalDatasetRecord` objects.

Responsibilities
---------------
* Knows which datasets are registered in the project (registration status).
* Knows which datasets are eligible to begin acquisition, and which are
  explicitly ineligible or unresolved (research decision + policy).
* Does **not** know whether a bytes artifact has been acquired, validated or
  profiled — that is the :class:`CanonicalDatasetRecord`'s own concern, driven
  by local evidence through :mod:`civicmind.ingestion.metadata`.
* Does **not** touch the network and never initiates acquisition.

The registry is intentionally separate from :class:`IngestionRegistry`
(:mod:`civicmind.ingestion.registry`): the ingestion registry maps a
``source_id`` to a :class:`DatasetIngestor` handler and is the place where a
concrete handler is bound; this catalog maps a canonical dataset id to the
canonical metadata record that describes it.

Design rules
------------
* Always deterministic: listing and filtering return sorted tuples.
* No mutable internals published. Callers cannot mutate the catalog through
  public accessors.
* Registration is additive and explicit: duplicate ids are rejected unless an
  explicit update path is used.
* Lookup by canonical dataset id is the primary access pattern.
"""

from __future__ import annotations

from civicmind.ingestion.metadata import CANONICAL_DATASET_IDS, CanonicalDatasetRecord

_ID_PATTERN = CANONICAL_DATASET_IDS.__class__(CANONICAL_DATASET_IDS)  # type: ignore[attr-defined]


class DatasetRegistrationError(Exception):
    """Raised when a dataset cannot be registered in the catalog."""


class DatasetCatalogError(Exception):
    """Base class for catalog lookup/operation failures."""


class UnknownDatasetError(DatasetCatalogError):
    """Raised when a requested dataset id is not registered."""


class DuplicateDatasetError(DatasetRegistrationError):
    """Raised when a dataset id is already registered."""


class InvalidDatasetRecordError(DatasetRegistrationError):
    """Raised when a submitted record is not a valid canonical dataset record."""


class DatasetRegistry:
    """A catalog of canonical dataset records keyed by dataset id.

    Not global, not network-bound, and not a source of acquisition evidence.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, CanonicalDatasetRecord] = {}

    # -- primary access -----------------------------------------------------
    def get(self, dataset_id: str) -> CanonicalDatasetRecord:
        """Return the registered record for ``dataset_id``.

        Raises :class:`UnknownDatasetError` when the id is not registered, and
        includes the known ids so typos are easy to spot.
        """
        try:
            return self._by_id[dataset_id]
        except KeyError:
            known = ", ".join(sorted(self._by_id)) or "<none>"
            raise UnknownDatasetError(
                f"No dataset registered under {dataset_id!r}. Known ids: {known}"
            ) from None

    def __contains__(self, dataset_id: object) -> bool:
        return dataset_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    # -- listing -----------------------------------------------------------
    def ids(self) -> tuple[str, ...]:
        """Return every registered canonical dataset id, sorted."""
        return tuple(sorted(self._by_id))

    def list_records(self) -> tuple[CanonicalDatasetRecord, ...]:
        """Return every registered record, sorted by dataset_id."""
        return tuple(self._by_id[id_] for id_ in sorted(self._by_id))

    # -- filtering ---------------------------------------------------------
    def filter_by(
        self,
        *,
        research_decision: str | None = None,
        acquisition_state: str | None = None,
    ) -> tuple[CanonicalDatasetRecord, ...]:
        """Return registered records matching the given axis values, sorted.

        Parameters
        ----------
        research_decision:
            If non-``None``, restrict to records whose
            :attr:`CanonicalDatasetRecord.research_decision` has this value.
        acquisition_state:
            If non-``None``, restrict to records whose
            :attr:`CanonicalDatasetRecord.acquisition_state` has this value.
        """
        matches: list[CanonicalDatasetRecord] = []
        for record in self._by_id.values():
            if (
                research_decision is not None
                and record.research_decision.value != research_decision
            ):
                continue
            if (
                acquisition_state is not None
                and record.acquisition_state.value != acquisition_state
            ):
                continue
            matches.append(record)
        matches.sort(key=lambda r: r.dataset_id)
        return tuple(matches)

    # -- mutation ----------------------------------------------------------
    def register(
        self, record: CanonicalDatasetRecord, *, allow_update: bool = False
    ) -> CanonicalDatasetRecord:
        """Register a canonical dataset record.

        Raises
        ------
        InvalidDatasetRecordError
            If ``record`` is not a :class:`CanonicalDatasetRecord`.
        DuplicateDatasetError
            If ``record.dataset_id`` is already registered and
            ``allow_update`` is false.
        """
        if not isinstance(record, CanonicalDatasetRecord):
            raise InvalidDatasetRecordError(
                f"Expected a CanonicalDatasetRecord, got {type(record).__name__!r}"
            )
        dataset_id = record.dataset_id
        if dataset_id in self._by_id and not allow_update:
            raise DuplicateDatasetError(_format_duplicate_error(dataset_id))
        self._by_id[dataset_id] = record
        return record

    def unregister(self, dataset_id: str) -> CanonicalDatasetRecord:
        """Remove a registered record and return it.

        Raises :class:`UnknownDatasetError` when ``dataset_id`` is not registered.
        """
        record = self.get(dataset_id)
        del self._by_id[dataset_id]
        return record


def _format_duplicate_error(dataset_id: str) -> str:
    return f"Dataset {dataset_id!r} is already registered; pass allow_update=True to replace it"
