"""Evidence representation for grounded municipal answers.

An :class:`Evidence` object is the boundary between the deterministic analytics
engine and the language-model layer. It carries the *facts*: which dataset was
queried, which columns were used, which records support the result, the units,
the time period and geographic scope, and every known quality issue and
limitation. The generated prose is only ever a rendering of this object.

Rules encoded here:

* A dataset whose canonical mapping is unverified or whose licence is
  unverified says so, in the evidence itself, rather than in a footnote the
  model could drop.
* ``supporting_records`` are the actual source rows, so a reader can re-derive
  every number by hand.
* ``citation()`` produces a stable, quotable string that never claims a
  download, a licence or a canonical identity that was not established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evidence:
    """A single, self-describing piece of analytical evidence.

    Parameters
    ----------
    dataset_id:
        Local dataset key (for example ``RA2019_A2``).
    source_file:
        Repository-relative path of the CSV the result was computed from.
    canonical_id:
        Canonical dataset id when one is defensibly known (``WTR-005`` for the
        water snapshot); ``None`` when the supplied file has no verified
        canonical mapping.
    operation:
        The deterministic operation name that produced the result.
    units:
        Units of the primary figure (for example ``"accidents"``, ``"ML"``).
    time_period:
        The period the figures describe, as stated by the source.
    geographic_scope:
        The geographic grain and coverage of the source.
    record_count:
        Number of source records considered by the operation.
    supporting_records:
        The concrete source records backing the result.
    columns:
        Column names actually used.
    quality_issues:
        Data-quality findings relevant to the result.
    limitations:
        Interpretation limits a reader must respect.
    mapping_status:
        Whether the file's canonical mapping is verified, plausible, or absent.
    license_status:
        Whether licence/attribution evidence has been verified.
    """

    dataset_id: str
    source_file: str
    operation: str
    units: str
    time_period: str
    geographic_scope: str
    record_count: int
    columns: tuple[str, ...] = ()
    supporting_records: tuple[dict[str, Any], ...] = ()
    quality_issues: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    canonical_id: str | None = None
    mapping_status: str = "unverified"
    license_status: str = "unverified"
    extra: dict[str, Any] = field(default_factory=dict)

    def citation(self) -> str:
        """Return a stable, quotable citation for this evidence."""
        identity = f"canonical id {self.canonical_id}" if self.canonical_id else "no canonical id"
        return (
            f"{self.source_file} ({identity}; {self.mapping_status} mapping; "
            f"{self.time_period}; {self.geographic_scope})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the evidence."""
        return {
            "dataset_id": self.dataset_id,
            "source_file": self.source_file,
            "canonical_id": self.canonical_id,
            "operation": self.operation,
            "units": self.units,
            "time_period": self.time_period,
            "geographic_scope": self.geographic_scope,
            "record_count": self.record_count,
            "columns": list(self.columns),
            "supporting_records": [dict(record) for record in self.supporting_records],
            "quality_issues": list(self.quality_issues),
            "limitations": list(self.limitations),
            "mapping_status": self.mapping_status,
            "license_status": self.license_status,
            "citation": self.citation(),
            "extra": dict(self.extra),
        }


__all__ = ["Evidence"]
