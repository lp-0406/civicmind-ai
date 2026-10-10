"""Dataset preprocessing (PLANNED - not implemented).

Reserved for deterministic, documented transformations that turn validated raw
datasets into analysis-ready tables: schema normalisation, municipal identifier
reconciliation, geocoding of administrative units, and unit/type coercion.

Design rule for future work: every transformation must be reproducible from
recorded provenance, must never fabricate records, and must emit quality
warnings rather than silently dropping rows.
"""

from __future__ import annotations

__all__: list[str] = []
