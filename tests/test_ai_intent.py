"""Tests for the rule-based question router."""

from __future__ import annotations

import pytest

from civicmind.ai.intent import (
    INTENT_DATASETS,
    SUPPORTED_INTENTS,
    QuestionRouter,
    extract_year,
)
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)

DEMO_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("Which states had the highest reported road accidents in 2019?", "state_accident_ranking"),
    ("What published share did Telangana have in 2019?", "state_share"),
    (
        "Which reported junction categories have the highest injured totals?",
        "junction_injury_totals",
    ),
    (
        "What are the highest recorded ward-level water consumption values for August 2025?",
        "ward_water_consumption",
    ),
    (
        "Can these datasets be joined reliably, and what evidence supports the answer?",
        "join_assessment",
    ),
)


@pytest.mark.parametrize(("question", "intent"), DEMO_QUESTIONS)
def test_demo_questions_route_to_their_intent(
    raw_settings: Settings, question: str, intent: str
) -> None:
    match = QuestionRouter(raw_settings).route(question)
    assert match.supported is True
    assert match.intent == intent
    assert match.dataset_id == INTENT_DATASETS[intent]


def test_every_supported_intent_has_a_dataset() -> None:
    assert set(SUPPORTED_INTENTS) == set(INTENT_DATASETS)


def test_share_question_extracts_the_state(raw_settings: Settings) -> None:
    match = QuestionRouter(raw_settings).route("What published share did Telangana have in 2019?")
    assert match.params["state"] == "Telangana"
    assert match.params["year"] == 2019


def test_share_question_without_a_state_is_unsupported(raw_settings: Settings) -> None:
    match = QuestionRouter(raw_settings).route("What was the share of accidents?")
    assert match.supported is False
    assert "state" in match.reason.lower()


def test_water_connection_question_routes_to_the_connection_summary(
    raw_settings: Settings,
) -> None:
    match = QuestionRouter(raw_settings).route("How many water connections are there per ward?")
    assert match.intent == "water_connection_summary"


def test_blackspot_question_routes_to_the_blackspot_ranking(raw_settings: Settings) -> None:
    match = QuestionRouter(raw_settings).route("Which locations are the worst blackspots?")
    assert match.intent == "blackspot_ranking"


def test_overspeeding_question_routes_to_the_overspeeding_ranking(raw_settings: Settings) -> None:
    match = QuestionRouter(raw_settings).route(
        "Which cities have the most over-speeding violations?"
    )
    assert match.intent == "overspeeding_ranking"


def test_quality_question_picks_the_right_dataset(raw_settings: Settings) -> None:
    router = QuestionRouter(raw_settings)
    assert (
        router.route("How many rows does the water data quality report show?").params["dataset_id"]
        == "BWSSB_WATER"
    )
    assert (
        router.route("Show missing values in the junction data.").params["dataset_id"]
        == "RA2019_A49"
    )


def test_unrelated_question_is_unsupported(raw_settings: Settings) -> None:
    match = QuestionRouter(raw_settings).route("What is the best cricket team in the world?")
    assert match.supported is False
    assert match.intent is None
    assert match.dataset_id is None
    assert "not supported" in match.reason.lower() or "no supported intent" in match.reason.lower()


def test_empty_question_is_unsupported(raw_settings: Settings) -> None:
    assert QuestionRouter(raw_settings).route("   ").supported is False


def test_extract_year_defaults_and_bounds() -> None:
    assert extract_year("accidents in 2017") == 2017
    assert extract_year("accidents in 2024") == 2019
    assert extract_year("accidents recently") == 2019


def test_find_state_prefers_the_longest_match(raw_settings: Settings) -> None:
    router = QuestionRouter(raw_settings)
    assert router.find_state("share of Andhra Pradesh in 2019") == "Andhra Pradesh"
    assert router.find_state("no state named here") is None
