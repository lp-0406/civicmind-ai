"""Registry of ingestion handlers.

The registry maps a ``source_id`` to a :class:`~civicmind.ingestion.base.DatasetIngestor`
instance. Registration stores metadata only: it never touches the network and
never downloads data. Handlers are instantiated by the operator (or by future
configuration) and registered explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator

from civicmind.ingestion.base import DatasetIngestor, SourceDescriptor
from civicmind.ingestion.exceptions import SourceRegistrationError, UnknownSourceError


class IngestionRegistry:
    """A deliberate, side-effect-free collection of ingestion handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, DatasetIngestor] = {}

    # -- mutation ----------------------------------------------------------
    def register(self, ingestor: DatasetIngestor, *, overwrite: bool = False) -> DatasetIngestor:
        """Register ``ingestor`` under its :attr:`source_id`.

        Parameters
        ----------
        ingestor:
            An instance implementing the ingestion contract.
        overwrite:
            Allow replacing an existing handler for the same ``source_id``.

        Raises
        ------
        TypeError
            If ``ingestor`` does not implement the contract.
        SourceRegistrationError
            If the ``source_id`` is already registered and ``overwrite`` is false.
        """
        if not isinstance(ingestor, DatasetIngestor):
            raise TypeError(f"Expected a DatasetIngestor instance, got {type(ingestor).__name__}")
        source_id = ingestor.describe().source_id
        if source_id in self._handlers and not overwrite:
            raise SourceRegistrationError(
                f"Source {source_id!r} is already registered; pass overwrite=True to replace it"
            )
        self._handlers[source_id] = ingestor
        return ingestor

    def unregister(self, source_id: str) -> None:
        """Remove a handler. Raises :class:`UnknownSourceError` if absent."""
        if source_id not in self._handlers:
            raise UnknownSourceError(f"No ingestion handler registered for {source_id!r}")
        del self._handlers[source_id]

    # -- lookup ------------------------------------------------------------
    def get(self, source_id: str) -> DatasetIngestor:
        """Return the handler for ``source_id``.

        Raises :class:`UnknownSourceError` when the source is unknown, listing
        the known ids so typos are easy to spot.
        """
        try:
            return self._handlers[source_id]
        except KeyError:
            known = ", ".join(sorted(self._handlers)) or "<none>"
            raise UnknownSourceError(
                f"No ingestion handler registered for {source_id!r}. Known sources: {known}"
            ) from None

    def describe_all(self) -> tuple[SourceDescriptor, ...]:
        """Return descriptors for every registered source, sorted by id."""
        return tuple(self._handlers[source_id].describe() for source_id in sorted(self._handlers))

    def source_ids(self) -> tuple[str, ...]:
        """Return every registered source id, sorted."""
        return tuple(sorted(self._handlers))

    # -- dunder helpers ----------------------------------------------------
    def __contains__(self, source_id: object) -> bool:
        return source_id in self._handlers

    def __len__(self) -> int:
        return len(self._handlers)

    def __iter__(self) -> Iterator[DatasetIngestor]:
        handlers = [self._handlers[source_id] for source_id in sorted(self._handlers)]
        return iter(handlers)


# Process-wide default registry used by the CLI. Nothing is auto-registered:
# handlers appear here only when application code or configuration adds them.
DEFAULT_REGISTRY = IngestionRegistry()


def register(
    ingestor: DatasetIngestor,
    *,
    registry: IngestionRegistry | None = None,
    overwrite: bool = False,
) -> DatasetIngestor:
    """Register ``ingestor`` in ``registry`` (defaults to :data:`DEFAULT_REGISTRY`)."""
    target = DEFAULT_REGISTRY if registry is None else registry
    return target.register(ingestor, overwrite=overwrite)
