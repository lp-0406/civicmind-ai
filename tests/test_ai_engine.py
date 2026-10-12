"""End-to-end tests for the decision engine."""

from __future__ import annotations

import json

import pytest

from civicmind.ai.config import AISettings
from civicmind.ai.engine import DecisionEngine
from civicmind.ai.providers import GenerationResult, ProviderError
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


class _FailingProvider:
    """A provider that always fails, to exercise the fallback path."""

    name = "exploding"
    mode = "api"

    def available(self) -> bool:
        return True

    def generate(self, request: object) -> GenerationResult:
        raise ProviderError("boom")


class _UngroundedProvider:
    """A model-like provider that drops the computed figures."""

    name = "ungrounded"
    mode = "local"

    def available(self) -> bool:
        return True

    def generate(self, request: object) -> GenerationResult:
        return GenerationResult(
            text="Several states had many accidents, but the exact numbers are unavailable.",
            mode="local",
            provider=self.name,
            model="fake/model",
        )


def _engine(settings: Settings) -> DecisionEngine:
    return DecisionEngine(
        settings,
        ai_settings=AISettings(provider="deterministic"),
    )


def test_demo_questions_are_answered_with_evidence(raw_settings: Settings) -> None:
    engine = _engine(raw_settings)
    cases = [
        ("Which states had the highest reported road accidents in 2019?", "57,228"),
        ("What published share did Telangana have in 2019?", "21,570"),
        ("Which reported junction categories have the highest injured totals?", "41,993"),
        (
            "What are the highest recorded ward-level water consumption values for August 2025?",
            "605.66",
        ),
    ]
    for question, expected in cases:
        answer = engine.ask(question)
        assert answer.supported is True, question
        assert answer.explanation, question
        assert expected in answer.explanation, question
        assert answer.evidence, question
        assert answer.limitations, question
        assert answer.execution_mode == "deterministic"
        assert answer.sources


def test_state_ranking_answer_is_numerically_correct(raw_settings: Settings) -> None:
    answer = _engine(raw_settings).ask(
        "Which states had the highest reported road accidents in 2019?"
    )
    assert answer.intent == "state_accident_ranking"
    assert answer.result["top_states"][0] == {"state": "Tamil Nadu", "accidents": 57228}
    assert answer.result["reported_total"] == 449002


def test_join_question_answers_with_a_verdict(raw_settings: Settings) -> None:
    answer = _engine(raw_settings).ask(
        "Can these datasets be joined reliably, and what evidence supports the answer?"
    )
    assert answer.supported is True
    assert answer.intent == "join_assessment"
    assert answer.result["water_joinable"] is False
    assert answer.dataset_id == "RA2019_A49"


def test_unsupported_question_is_not_fabricated(raw_settings: Settings) -> None:
    answer = _engine(raw_settings).ask("What is the best cricket team in the world?")
    assert answer.supported is False
    assert answer.result is None
    assert answer.evidence == ()
    assert "not supported" in answer.explanation.lower()


def test_missing_dataset_blocks_rather_than_guesses(pilot_settings: Settings) -> None:
    # pilot_settings points data/raw at an empty tmp tree.
    answer = _engine(pilot_settings).ask(
        "Which states had the highest reported road accidents in 2019?"
    )
    assert answer.supported is False
    assert answer.intent == "state_accident_ranking"
    assert answer.result is None
    assert "could not be answered" in answer.explanation


def test_provider_failure_falls_back_to_the_deterministic_answer(raw_settings: Settings) -> None:
    engine = DecisionEngine(
        raw_settings,
        ai_settings=AISettings(provider="api"),
        provider=_FailingProvider(),
    )
    answer = engine.ask("Which states had the highest reported road accidents in 2019?")
    assert answer.supported is True
    assert answer.execution_mode == "deterministic"
    assert "57,228" in answer.explanation
    assert answer.fallback_reason is not None


def test_answer_serialises_to_json(raw_settings: Settings) -> None:
    payload = json.dumps(
        _engine(raw_settings).ask("What published share did Kerala have in 2019?").to_dict()
    )
    parsed = json.loads(payload)
    assert parsed["supported"] is True
    assert parsed["intent"] == "state_share"
    assert parsed["evidence"][0]["citation"]


def test_evidence_citation_is_honest_about_mapping(raw_settings: Settings) -> None:
    answer = _engine(raw_settings).ask(
        "What are the highest recorded ward-level water consumption values for August 2025?"
    )
    citation = answer.evidence[0].citation()
    assert "WTR-005" in citation
    assert "plausible but unverified" in citation
    assert "download" not in citation.lower()


def test_ungrounded_model_answer_is_discarded_for_the_deterministic_one(
    raw_settings: Settings,
) -> None:
    engine = DecisionEngine(
        raw_settings,
        ai_settings=AISettings(provider="local"),
        provider=_UngroundedProvider(),
    )
    answer = engine.ask("Which states had the highest reported road accidents in 2019?")

    assert answer.supported is True
    assert answer.execution_mode == "deterministic"
    assert answer.model is None
    assert "57,228" in answer.explanation
    assert answer.fallback_reason is not None
    assert "grounding" in answer.fallback_reason


def test_engine_reports_the_deterministic_provider(raw_settings: Settings) -> None:
    answer = _engine(raw_settings).ask("Which cities have the most over-speeding violations?")
    assert answer.provider == "deterministic"
    assert answer.model is None
    assert answer.execution_mode == "deterministic"
