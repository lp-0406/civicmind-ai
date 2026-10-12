"""The decision engine: question -> routed intent -> analytics -> grounded answer.

This is the single orchestration entry point. It is intentionally a plain
pipeline, not an autonomous agent: each stage is a named, testable function, and
the engine only ever phrases a result the deterministic engine already computed.

Unsupported questions are answered with an explicit explanation of what is not
supported, so the system never fabricates a recommendation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from civicmind.ai import analytics
from civicmind.ai.analytics import AnalyticsError, AnalyticsResult
from civicmind.ai.config import AISettings
from civicmind.ai.datasets import UnavailableDatasetError
from civicmind.ai.evidence import Evidence
from civicmind.ai.intent import (
    IntentMatch,
    QuestionRouter,
    register_domain_rule,
    unregister_domain_rule,
)
from civicmind.ai.providers import (
    AnswerProvider,
    DeterministicProvider,
    GenerationRequest,
    ProviderError,
    build_provider,
    missing_grounding,
    provider_fallback_reason,
    render_deterministic_answer,
)

#: Dispatch table: intent -> analytics function.
_DISPATCH: dict[str, Callable[..., AnalyticsResult]] = {
    "state_accident_ranking": analytics.state_accident_ranking,
    "state_share": analytics.state_share,
    "junction_injury_totals": analytics.junction_injury_totals,
    "overspeeding_ranking": analytics.overspeeding_ranking,
    "blackspot_ranking": analytics.blackspot_ranking,
    "ward_water_consumption": analytics.ward_water_consumption,
    "water_connection_summary": analytics.water_connection_summary,
    "dataset_quality_report": analytics.dataset_quality_report,
    "join_assessment": analytics.join_assessment,
}


@dataclass(frozen=True)
class Answer:
    """A complete, grounded response to a municipal question."""

    question: str
    supported: bool
    explanation: str
    execution_mode: str
    provider: str
    intent: str | None = None
    dataset_id: str | None = None
    result: Any = None
    evidence: tuple[Evidence, ...] = ()
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    model: str | None = None
    fallback_reason: str | None = None
    routing: IntentMatch | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def sources(self) -> tuple[str, ...]:
        """Return the cited source files."""
        return tuple(item.citation() for item in self.evidence)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the answer."""
        return {
            "question": self.question,
            "supported": self.supported,
            "intent": self.intent,
            "dataset_id": self.dataset_id,
            "result": self.result,
            "explanation": self.explanation,
            "sources": list(self.sources),
            "evidence": [item.to_dict() for item in self.evidence],
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "model": self.model,
            "fallback_reason": self.fallback_reason,
        }


class DecisionEngine:
    """Orchestrates routing, deterministic analytics, evidence and answer generation."""

    def __init__(
        self,
        settings: Any,
        *,
        ai_settings: AISettings | None = None,
        provider: AnswerProvider | None = None,
        router: QuestionRouter | None = None,
    ) -> None:
        self.settings = settings
        self.ai_settings = ai_settings or AISettings.from_env()
        self.provider = provider or build_provider(self.ai_settings)
        self.router = router or QuestionRouter(settings)

    @classmethod
    def from_env(cls, settings: Any) -> DecisionEngine:
        """Build an engine from the process environment."""
        return cls(settings, ai_settings=AISettings.from_env())

    # -- public API --------------------------------------------------------
    def ask(self, question: str) -> Answer:
        """Answer a municipal question end to end."""
        routing = self.router.route(question)
        if not routing.supported or routing.intent is None:
            return self._unsupported(question, routing)

        operation = _DISPATCH.get(routing.intent)
        if operation is None:  # pragma: no cover - router and dispatch stay in sync
            return self._unsupported(question, routing)

        try:
            analytics_result = operation(self.settings, **(routing.params or {}))
        except UnavailableDatasetError as exc:
            return self._blocked(question, routing, str(exc), kind="missing-dataset")
        except (AnalyticsError, KeyError, ValueError, TypeError, IndexError) as exc:
            # Contain every analytical failure as a clean refusal. A missing or
            # malformed value must never escape as an unhandled error (which
            # would surface as an HTTP 500) or be silently answered.
            return self._blocked(question, routing, str(exc), kind="analytics-error")

        return self._phrase(question, routing, analytics_result)

    # -- internals ---------------------------------------------------------
    def _phrase(self, question: str, routing: IntentMatch, result: AnalyticsResult) -> Answer:
        request = GenerationRequest(
            question=question,
            summary=result.summary,
            evidence=(result.evidence,),
            limitations=result.evidence.limitations,
            datasets=(result.dataset_id,),
        )
        fallback_reason = provider_fallback_reason(self.ai_settings, self.provider)
        try:
            generation = self.provider.generate(request)
            explanation = generation.text
            mode = generation.mode
            model = generation.model
            fallback_reason = generation.fallback_reason or fallback_reason
        except (ProviderError, Exception) as exc:  # noqa: BLE001 - never fail an answer that exists
            explanation = render_deterministic_answer(request)
            mode = "deterministic"
            model = None
            fallback_reason = (
                f"provider {self.provider.name!r} failed ({exc}); used deterministic fallback"
            )
        else:
            # A model-generated answer must preserve every computed figure and
            # disclose the limitations. If it does not, it is discarded in favour
            # of the deterministic rendering rather than returned as-is.
            if mode != "deterministic":
                missing = missing_grounding(
                    explanation, result.summary, result.evidence.limitations
                )
                if missing:
                    explanation = render_deterministic_answer(request)
                    mode = "deterministic"
                    model = None
                    shown = "; ".join(missing[:3])
                    fallback_reason = (
                        f"the generated answer dropped required grounding ({shown}); "
                        "used the deterministic fallback"
                    )

        return Answer(
            question=question,
            supported=True,
            intent=routing.intent,
            dataset_id=result.dataset_id,
            result=result.value,
            evidence=(result.evidence,),
            explanation=explanation,
            limitations=result.evidence.limitations,
            warnings=result.warnings,
            execution_mode=mode,
            provider=self.provider.name,
            model=model,
            fallback_reason=fallback_reason,
            routing=routing,
        )

    def _unsupported(self, question: str, routing: IntentMatch) -> Answer:
        return Answer(
            question=question,
            supported=False,
            intent=None,
            dataset_id=None,
            result=None,
            evidence=(),
            explanation=(
                "This question is not supported by the currently available datasets. "
                f"{routing.reason}"
            ),
            limitations=(
                "Only questions answerable from the five supplied CSVs are supported.",
                "No recommendation is fabricated for unsupported questions.",
            ),
            execution_mode="deterministic",
            provider=DeterministicProvider.name,
            routing=routing,
        )

    def _blocked(self, question: str, routing: IntentMatch, reason: str, *, kind: str) -> Answer:
        return Answer(
            question=question,
            supported=False,
            intent=routing.intent,
            dataset_id=routing.dataset_id,
            result=None,
            evidence=(),
            explanation=(
                f"The question routed to intent {routing.intent!r}, but it could not be "
                f"answered: {reason}"
            ),
            limitations=(
                "The requested computation was refused rather than approximated.",
                "Place the required raw CSV under data/raw and retry.",
            ),
            execution_mode="deterministic",
            provider=DeterministicProvider.name,
            routing=routing,
            extra={"blocked_kind": kind},
        )


def register_domain(
    intent: str,
    *,
    dataset_id: str,
    operation: Callable[..., AnalyticsResult],
    patterns: tuple[str, ...],
    confidence: float = 0.7,
) -> None:
    """Register a new domain without modifying the decision engine.

    A new domain (waste, environment, ...) is added by supplying its routing
    patterns, its dataset id and its analytics function. The router and the
    dispatch table are updated together, so no existing built-in behaviour
    changes and the engine never needs to be rewritten.

    See :func:`civicmind.ai.intent.register_domain_rule` for the routing half.
    """
    register_domain_rule(intent, dataset_id=dataset_id, patterns=patterns, confidence=confidence)
    _DISPATCH[intent] = operation


def unregister_domain(intent: str) -> None:
    """Remove a previously registered domain (no-op when absent)."""
    unregister_domain_rule(intent)
    _DISPATCH.pop(intent, None)


__all__ = ["Answer", "DecisionEngine", "register_domain", "unregister_domain"]
