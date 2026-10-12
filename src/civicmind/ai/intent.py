"""Explicit, testable routing from a municipal question to a supported task.

The router is deliberately rule-based, not model-driven: intent and dataset
selection must be deterministic and inspectable, because it decides which
numeric computation runs. A question that no rule supports returns an
unsupported match with a reason, rather than being handed to a language model to
guess at.

Adding a domain later means adding one rule and one analytics function; the
:class:`IntentMatch` contract does not change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from civicmind.ai.datasets import find_column, load_dataset, normalize_column_name

#: Supported intent names.
SUPPORTED_INTENTS: tuple[str, ...] = (
    "join_assessment",
    "dataset_quality_report",
    "state_share",
    "junction_injury_totals",
    "blackspot_ranking",
    "overspeeding_ranking",
    "ward_water_consumption",
    "water_connection_summary",
    "state_accident_ranking",
)

#: The dataset each intent is answered from.
INTENT_DATASETS: dict[str, str] = {
    "join_assessment": "RA2019_A49",
    "dataset_quality_report": "RA2019_A2",
    "state_share": "RA2019_A2",
    "state_accident_ranking": "RA2019_A2",
    "junction_injury_totals": "RA2019_A49",
    "blackspot_ranking": "RA2019_A52",
    "overspeeding_ranking": "RA2019_A47",
    "ward_water_consumption": "BWSSB_WATER",
    "water_connection_summary": "BWSSB_WATER",
}

_VALID_YEARS = (2016, 2017, 2018, 2019)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
#: Labels shorter than this are not matched at all, guarding against a one- or
#: two-character label matching almost anything. The shortest real state label is
#: "Goa" (three characters), so it must be reachable.
_MIN_STATE_LABEL_LENGTH = 3


def mentions_label(haystack: str, label: str) -> bool:
    """Return True when ``label`` appears as a whole token in a normalised ``haystack``.

    Matching on token boundaries rather than a minimum length is what lets a
    short but real name such as "Goa" be queried while "goal" still does not
    match it.
    """
    pattern = rf"(?<![a-z0-9]){re.escape(normalize_column_name(label))}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


#: Additional, programmatically registered routing rules (one entry per intent).
#
#: This is the domain-extension hook: a new domain (for example waste or
#: environment) is added by calling :func:`register_domain_rule` with keyword
#: patterns and a dataset id, plus ``civicmind.ai.engine.register_domain`` with
#: the analytics function. The router and the decision engine then support it
#: without any change to the existing rule list or to built-in behaviour.
@dataclass(frozen=True)
class DomainRule:
    """A routing rule contributed by a domain extension."""

    intent: str
    dataset_id: str
    patterns: tuple[str, ...]
    confidence: float = 0.7


DOMAIN_RULES: dict[str, DomainRule] = {}


def register_domain_rule(
    intent: str,
    *,
    dataset_id: str,
    patterns: tuple[str, ...],
    confidence: float = 0.7,
) -> DomainRule:
    """Register an extra routing rule without touching built-in intents.

    ``patterns`` are matched against the normalised question text (see
    :func:`normalize_column_name`-style normalisation used by the router).
    Registering an intent that already exists overrides its rule, which keeps
    re-registration idempotent.
    """
    if not intent.strip():
        raise RoutingError("intent must be non-empty")
    if not dataset_id.strip():
        raise RoutingError("dataset_id must be non-empty")
    if not patterns:
        raise RoutingError("at least one pattern is required")
    rule = DomainRule(
        intent=intent,
        dataset_id=dataset_id,
        patterns=tuple(patterns),
        confidence=confidence,
    )
    DOMAIN_RULES[intent] = rule
    return rule


def unregister_domain_rule(intent: str) -> None:
    """Remove a previously registered domain rule (no-op when absent)."""
    DOMAIN_RULES.pop(intent, None)


class RoutingError(RuntimeError):
    """Raised when routing cannot proceed (for example, a required dataset is missing)."""


@dataclass(frozen=True)
class IntentMatch:
    """The result of routing one question."""

    intent: str | None
    dataset_id: str | None
    params: dict[str, Any] = field(default_factory=dict)
    supported: bool = False
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "intent": self.intent,
            "dataset_id": self.dataset_id,
            "params": dict(self.params),
            "supported": self.supported,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def extract_year(question: str, *, default: int = 2019) -> int:
    """Extract a 2016-2019 year from the question, defaulting when absent."""
    for match in _YEAR_RE.finditer(question):
        year = int(match.group(1))
        if year in _VALID_YEARS:
            return year
    return default


def _contains(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


class QuestionRouter:
    """Routes a municipal question to a supported intent and dataset."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._state_labels: tuple[str, ...] | None = None

    # -- state vocabulary --------------------------------------------------
    def state_labels(self) -> tuple[str, ...]:
        """Return the state/UT labels available in RA2019_A2 (cached, lazily loaded)."""
        if self._state_labels is None:
            loaded = load_dataset(self.settings, "RA2019_A2")
            column = find_column(loaded.dataframe, loaded.spec.id_column)
            labels = [
                str(value)
                for value in loaded.dataframe[column].tolist()
                if normalize_column_name(str(value)) != "total"
            ]
            self._state_labels = tuple(labels)
        return self._state_labels

    def find_state(self, question: str) -> str | None:
        """Return the state label mentioned in the question, or ``None``."""
        normalized = normalize_column_name(question)
        candidates = [
            label
            for label in self.state_labels()
            if len(label) >= _MIN_STATE_LABEL_LENGTH and mentions_label(normalized, label)
        ]
        if not candidates:
            return None
        # Prefer the longest match so "Andhra Pradesh" beats a shorter substring.
        return max(candidates, key=len)

    # -- routing -----------------------------------------------------------
    def route(self, question: str) -> IntentMatch:
        """Route ``question`` to an intent, or report it as unsupported."""
        text = normalize_column_name(question)
        if not text.strip():
            return IntentMatch(None, None, supported=False, reason="the question is empty")
        return self._route(text, question)

    def _route(self, text: str, question: str) -> IntentMatch:
        # Order matters: the most specific signal wins.

        # Honest refusals come first: a question the supplied data cannot answer
        # must never be silently mapped onto a different grain or period.
        if "ward" in text and _contains(
            text, "accident", "road", "crash", "fatality", "fatalities"
        ):
            return IntentMatch(
                None,
                None,
                supported=False,
                reason=(
                    "the roads datasets are state- and city-level and carry no ward grain, so "
                    "ward-level road-accident questions cannot be answered from the supplied data"
                ),
            )

        mentioned_years = [int(match.group(1)) for match in _YEAR_RE.finditer(question)]
        if (
            _contains(text, "accident", "road")
            and mentioned_years
            and any(year not in _VALID_YEARS for year in mentioned_years)
        ):
            years = ", ".join(str(year) for year in sorted(set(mentioned_years)))
            return IntentMatch(
                None,
                None,
                supported=False,
                reason=(
                    f"the roads datasets cover 2016-2019 only; {years} is outside that period, "
                    "and no projection or forecast is produced"
                ),
            )

        if _contains(text, "join", "combine the", "combine these", "link the datasets"):
            return self._match("join_assessment", params={}, confidence=0.9)

        if _contains(text, "data quality", "missing value", "how many rows", "duplicate"):
            dataset_id = self._quality_dataset(text)
            return self._match(
                "dataset_quality_report", params={"dataset_id": dataset_id}, confidence=0.8
            )

        if "share" in text:
            state = self.find_state(question)
            if state is not None:
                return self._match(
                    "state_share",
                    params={"state": state, "year": extract_year(question)},
                    confidence=0.9,
                )
            return IntentMatch(
                None,
                None,
                supported=False,
                reason=(
                    "a 'share' question was detected but no state/UT name was recognised; "
                    "name a state present in RA2019_A2"
                ),
            )

        if "junction" in text:
            return self._match("junction_injury_totals", params={}, confidence=0.9)

        if _contains(
            text,
            "blackspot",
            "black spot",
            "black-spot",
            "accident prone",
            "accident-prone",
            "high accident",
        ):
            return self._match("blackspot_ranking", params={}, confidence=0.85)

        if _contains(
            text, "over speeding", "over-speeding", "overspeeding", "speeding", "violation"
        ):
            return self._match("overspeeding_ranking", params={}, confidence=0.85)

        if _contains(text, "water", "bwssb", "consumption", "ward"):
            if "connection" in text:
                return self._match("water_connection_summary", params={}, confidence=0.9)
            return self._match("ward_water_consumption", params={}, confidence=0.9)

        if _contains(text, "accident", "road") and _contains(
            text, "state", "highest", "top", "rank"
        ):
            return self._match(
                "state_accident_ranking", params={"year": extract_year(question)}, confidence=0.85
            )

        # Domain extensions last, so they can never shadow a built-in intent.
        for rule in DOMAIN_RULES.values():
            if _contains(text, *rule.patterns):
                return self._domain_match(rule)

        return IntentMatch(
            None,
            None,
            supported=False,
            reason=(
                "no supported intent matched this question; supported topics: state/UT road "
                "accident totals and shares, junction-type injuries, over-speeding, blackspots, "
                "ward-level water consumption/connections, dataset quality, and dataset joins"
            ),
        )

    def _quality_dataset(self, text: str) -> str:
        """Pick the dataset a quality question refers to (defaults to RA2019_A2)."""
        if _contains(text, "water", "bwssb", "ward"):
            return "BWSSB_WATER"
        if _contains(text, "junction"):
            return "RA2019_A49"
        if _contains(text, "speeding", "violation"):
            return "RA2019_A47"
        if _contains(text, "blackspot", "accident prone"):
            return "RA2019_A52"
        return "RA2019_A2"

    def _match(self, intent: str, *, params: dict[str, Any], confidence: float) -> IntentMatch:
        return IntentMatch(
            intent=intent,
            dataset_id=INTENT_DATASETS[intent],
            params=params,
            supported=True,
            confidence=confidence,
            reason=f"matched intent {intent!r}",
        )

    def _domain_match(self, rule: DomainRule) -> IntentMatch:
        return IntentMatch(
            intent=rule.intent,
            dataset_id=rule.dataset_id,
            params={},
            supported=True,
            confidence=rule.confidence,
            reason=f"matched registered domain intent {rule.intent!r}",
        )


__all__ = [
    "DOMAIN_RULES",
    "INTENT_DATASETS",
    "SUPPORTED_INTENTS",
    "DomainRule",
    "IntentMatch",
    "QuestionRouter",
    "RoutingError",
    "extract_year",
    "mentions_label",
    "register_domain_rule",
    "unregister_domain_rule",
]
