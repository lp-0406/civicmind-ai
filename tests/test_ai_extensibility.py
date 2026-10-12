"""Tests that new domains (waste, environment, ...) need no engine rewrite.

No waste or environmental dataset is created or implied here. The demonstration
operation reuses a *real* computation over a *real* supplied file, so the
evidence it produces is genuine; only the intent label is illustrative.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from civicmind.ai.analytics import AnalyticsResult, dataset_quality_report
from civicmind.ai.config import AISettings
from civicmind.ai.engine import DecisionEngine, register_domain, unregister_domain
from civicmind.ai.intent import DOMAIN_RULES, QuestionRouter, RoutingError, register_domain_rule
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)

INTENT = "waste_demonstration"


def _demonstration_operation(settings: Settings, **kwargs: object) -> AnalyticsResult:
    """A stand-in new-domain operation built from a real file.

    This is what a future ``waste`` or ``environment`` analytics function would
    look like: it loads a dataset, computes something and returns an
    ``AnalyticsResult``. It deliberately reuses the real water snapshot instead
    of inventing a waste dataset.
    """
    result = dataset_quality_report(settings, dataset_id="BWSSB_WATER")
    return replace(result, intent=INTENT, operation=INTENT)


@pytest.fixture
def registered_domain():
    """Register the demonstration domain and always unregister it afterwards."""
    register_domain(
        INTENT,
        dataset_id="BWSSB_WATER",
        operation=_demonstration_operation,
        patterns=("waste demonstration", "solid waste"),
        confidence=0.6,
    )
    try:
        yield INTENT
    finally:
        unregister_domain(INTENT)


def test_router_has_no_registered_domains_by_default() -> None:
    assert DOMAIN_RULES == {}


def test_registered_domain_routes_and_dispatches(
    raw_settings: Settings, registered_domain
) -> None:
    engine = DecisionEngine(raw_settings, ai_settings=AISettings(provider="deterministic"))
    answer = engine.ask("Give me a solid waste summary please.")

    assert answer.supported is True
    assert answer.intent == INTENT
    assert answer.dataset_id == "BWSSB_WATER"
    # The evidence is real: it cites the actual supplied CSV.
    assert answer.evidence[0].source_file.endswith("BWSSB_Water_Consumption_August_2025.csv")
    assert answer.execution_mode == "deterministic"


def test_builtin_intents_are_not_shadowed_by_a_new_domain(
    raw_settings: Settings, registered_domain
) -> None:
    engine = DecisionEngine(raw_settings, ai_settings=AISettings(provider="deterministic"))
    answer = engine.ask("Which states had the highest reported road accidents in 2019?")
    assert answer.intent == "state_accident_ranking"


def test_unregistering_removes_the_domain(raw_settings: Settings) -> None:
    register_domain(
        INTENT,
        dataset_id="BWSSB_WATER",
        operation=_demonstration_operation,
        patterns=("solid waste",),
    )
    engine = DecisionEngine(raw_settings, ai_settings=AISettings(provider="deterministic"))
    assert engine.ask("Give me a solid waste summary.").intent == INTENT

    unregister_domain(INTENT)

    after = engine.ask("Give me a solid waste summary.")
    assert after.supported is False
    assert after.intent is None
    assert INTENT not in DOMAIN_RULES


def test_router_only_needs_a_pattern_to_support_a_new_domain(raw_settings: Settings) -> None:
    register_domain_rule(
        "env_demo", dataset_id="RA2019_A2", patterns=("air quality demonstration",)
    )
    try:
        router = QuestionRouter(raw_settings)
        match = router.route("Show me the air quality demonstration.")
        assert match.supported is True
        assert match.intent == "env_demo"
        assert match.dataset_id == "RA2019_A2"
    finally:
        unregister_domain("env_demo")


def test_register_domain_rule_rejects_incomplete_registrations() -> None:
    with pytest.raises(RoutingError):
        register_domain_rule("x", dataset_id="RA2019_A2", patterns=())
    with pytest.raises(RoutingError):
        register_domain_rule("", dataset_id="RA2019_A2", patterns=("x",))
    with pytest.raises(RoutingError):
        register_domain_rule("x", dataset_id="", patterns=("x",))


def test_existing_domains_keep_their_declared_routes(raw_settings: Settings) -> None:
    # Roads and water routing is intact and independent of any extension.
    router = QuestionRouter(raw_settings)
    states_route = router.route("Which states had the highest accidents in 2018?")
    assert states_route.dataset_id == "RA2019_A2"
    assert (
        router.route("How many water connections are there per ward?").dataset_id == "BWSSB_WATER"
    )
