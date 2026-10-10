"""Canonical four-axis status model for dataset records.

The axes are defined in ``docs/datasets/ingestion_plan.md`` §2.1 and are
**independent**: none implies another.

1. ``research_decision`` - planning intent; changed only by a documented review.
2. ``acquisition_state`` - what bytes we hold locally (repository-local evidence).
3. ``validation_state``  - whether those bytes passed our checks.
4. ``profiling_state``   - what the bytes contain (statistics).

Two consequences are load-bearing and easy to get wrong:

* ``PROFILED`` never means ``VALIDATED`` - profiling records statistics,
  validation records the outcome of a check.
* ``research_decision=REPLACE`` never implies ``acquisition_state=SUPERSEDED``
  - the first is a planning statement about a record, the second a fact about
  bytes.

This module defines the vocabularies and the permitted transitions only;
enforcement lives in :mod:`civicmind.ingestion.metadata`.
"""

from __future__ import annotations

from enum import Enum

from civicmind.ingestion.exceptions import InvalidTransitionError


class ResearchDecision(str, Enum):
    """Axis 1 - planning intent for a dataset record."""

    KEEP = "KEEP"
    KEEP_WITH_CHUNKING = "KEEP_WITH_CHUNKING"
    CONDITIONAL = "CONDITIONAL"
    REPLACE = "REPLACE"
    REJECT = "REJECT"


class AcquisitionState(str, Enum):
    """Axis 2 - what bytes this repository actually holds."""

    METADATA_ONLY = "METADATA_ONLY"
    DOWNLOADED = "DOWNLOADED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


class ValidationState(str, Enum):
    """Axis 3 - whether the current artifact passed our checks."""

    NOT_VALIDATED = "NOT_VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATED = "VALIDATED"


class ProfilingState(str, Enum):
    """Axis 4 - how much of the dataset's content has been measured."""

    NOT_PROFILED = "NOT_PROFILED"
    SCHEMA_ONLY = "SCHEMA_ONLY"
    PARTIALLY_PROFILED = "PARTIALLY_PROFILED"
    PROFILED = "PROFILED"


#: Axis 1 transitions. ``REPLACE`` is terminal for eligibility - it is entered
#: only from ``CONDITIONAL`` (the undecided state) by a documented review that
#: names a ``replacement_target``, and cannot be left. ``REJECT`` may only
#: return via a new review with fresh evidence.
RESEARCH_DECISION_TRANSITIONS: dict[ResearchDecision, frozenset[ResearchDecision]] = {
    ResearchDecision.CONDITIONAL: frozenset(
        {
            ResearchDecision.KEEP,
            ResearchDecision.KEEP_WITH_CHUNKING,
            ResearchDecision.REPLACE,
            ResearchDecision.REJECT,
        }
    ),
    ResearchDecision.KEEP: frozenset({ResearchDecision.KEEP_WITH_CHUNKING}),
    ResearchDecision.KEEP_WITH_CHUNKING: frozenset({ResearchDecision.KEEP}),
    ResearchDecision.REJECT: frozenset({ResearchDecision.CONDITIONAL}),
    ResearchDecision.REPLACE: frozenset(),
}

#: Axis 2 transitions. ``SUPERSEDED`` is terminal; ``DOWNLOADED`` may only fall
#: back to ``METADATA_ONLY`` on proven artefact loss (see the record).
ACQUISITION_STATE_TRANSITIONS: dict[AcquisitionState, frozenset[AcquisitionState]] = {
    AcquisitionState.METADATA_ONLY: frozenset(
        {AcquisitionState.DOWNLOADED, AcquisitionState.BLOCKED, AcquisitionState.SUPERSEDED}
    ),
    AcquisitionState.BLOCKED: frozenset(
        {AcquisitionState.METADATA_ONLY, AcquisitionState.DOWNLOADED, AcquisitionState.SUPERSEDED}
    ),
    AcquisitionState.DOWNLOADED: frozenset(
        {AcquisitionState.METADATA_ONLY, AcquisitionState.SUPERSEDED}
    ),
    AcquisitionState.SUPERSEDED: frozenset(),
}

#: Axis 3 transitions. ``VALIDATED -> NOT_VALIDATED`` happens when the artifact
#: changes; ``VALIDATED -> VALIDATION_FAILED`` records a failed re-run against
#: the same artifact (implemented addition - see the plan's implementation notes).
VALIDATION_STATE_TRANSITIONS: dict[ValidationState, frozenset[ValidationState]] = {
    ValidationState.NOT_VALIDATED: frozenset(
        {ValidationState.VALIDATED, ValidationState.VALIDATION_FAILED}
    ),
    ValidationState.VALIDATION_FAILED: frozenset({ValidationState.VALIDATED}),
    ValidationState.VALIDATED: frozenset(
        {ValidationState.NOT_VALIDATED, ValidationState.VALIDATION_FAILED}
    ),
}

#: Axis 4 transitions. Strict forward ladder; regression happens only when the
#: artifact changes (handled by the record, not this table).
PROFILING_STATE_TRANSITIONS: dict[ProfilingState, frozenset[ProfilingState]] = {
    ProfilingState.NOT_PROFILED: frozenset({ProfilingState.SCHEMA_ONLY}),
    ProfilingState.SCHEMA_ONLY: frozenset({ProfilingState.PARTIALLY_PROFILED}),
    ProfilingState.PARTIALLY_PROFILED: frozenset(
        {ProfilingState.PARTIALLY_PROFILED, ProfilingState.PROFILED}
    ),
    ProfilingState.PROFILED: frozenset(),
}

#: Every axis, keyed by a human-readable name, for generic enforcement.
TRANSITIONS: dict[str, dict[Enum, frozenset[Enum]]] = {
    "research_decision": RESEARCH_DECISION_TRANSITIONS,
    "acquisition_state": ACQUISITION_STATE_TRANSITIONS,
    "validation_state": VALIDATION_STATE_TRANSITIONS,
    "profiling_state": PROFILING_STATE_TRANSITIONS,
}


def ensure_transition(axis: str, current: Enum, target: Enum) -> None:
    """Raise :class:`InvalidTransitionError` unless ``current -> target`` is allowed.

    Parameters
    ----------
    axis:
        One of the keys of :data:`TRANSITIONS`.
    current, target:
        The state being left and the state being entered.
    """
    if current is target:
        raise InvalidTransitionError(
            f"{axis}: {current.name} -> {target.name} is a no-op; record an event instead"
        )
    allowed = TRANSITIONS[axis][current]
    if target not in allowed:
        options = ", ".join(sorted(state.name for state in allowed)) or "<terminal>"
        raise InvalidTransitionError(
            f"{axis}: {current.name} -> {target.name} is not permitted; "
            f"allowed from {current.name}: {options}"
        )
