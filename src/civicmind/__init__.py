"""CivicMind AI: evidence-grounded municipal decision intelligence.

The package currently provides the engineering foundation only: configuration,
structured logging, environment inspection and the ingestion contract/registry.
Ingestion handlers, preprocessing, profiling, storage and the AI components are
planned and intentionally not implemented yet.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

_FALLBACK_VERSION = "0.1.0"

try:
    __version__ = version("civicmind-ai")
except PackageNotFoundError:  # pragma: no cover - only when run from source w/o install
    __version__ = _FALLBACK_VERSION
