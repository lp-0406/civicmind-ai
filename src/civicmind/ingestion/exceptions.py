"""Ingestion exceptions.

A small, explicit hierarchy so callers can distinguish configuration problems
from acquisition failures and validation failures without catching bare
``Exception``.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for every CivicMind ingestion failure."""


class SourceRegistrationError(IngestionError):
    """Raised when a handler cannot be registered (e.g. duplicate source id)."""


class UnknownSourceError(IngestionError):
    """Raised when a requested source id is not registered."""


class AcquisitionError(IngestionError):
    """Raised when data could not be read or retrieved from its source."""


class DatasetValidationError(IngestionError):
    """Raised when an acquired dataset fails validation and enforcement is on."""
