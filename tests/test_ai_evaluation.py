"""Tests for the evaluation harness.

These tests prove three things: the benchmark passes on the real data, the
metrics can *fail* (they are not vacuous), and the report is reproducible JSON.
"""

from __future__ import annotations

import json

import pytest

from civicmind.ai.config import AISettings
from civicmind.ai.evaluation import (
    DEFAULT_BENCHMARK,
    BenchmarkCase,
    EvaluationHarness,
)
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


def _harness(settings: Settings) -> EvaluationHarness:
    return EvaluationHarness(settings, ai_settings=AISettings(provider="deterministic"))


@pytest.fixture(scope="module")
def report():
    """Run the fixed benchmark once for the whole module."""
    from civicmind.config import Settings as _Settings

    harness = _harness(_Settings.from_env({}))
    return harness.run()


def test_all_declared_metrics_are_perfect(report) -> None:
    assert report.metrics["numerical_accuracy"] == pytest.approx(1.0)
    assert report.metrics["attribution_accuracy"] == pytest.approx(1.0)
    assert report.metrics["unsupported_rejection_rate"] == pytest.approx(1.0)
    assert report.metrics["intent_accuracy"] == pytest.approx(1.0)


def test_benchmark_covers_every_required_category() -> None:
    categories = {case.category for case in DEFAULT_BENCHMARK}
    required = {
        "ranking",
        "share",
        "junction",
        "violation",
        "water",
        "connections",
        "unsupported",
        "unavailable",
        "granularity",
        "temporal",
    }
    assert required <= categories


def test_supported_cases_cite_their_expected_source(report) -> None:
    supported = [outcome for outcome in report.outcomes if outcome.expected_supported]
    assert supported
    for outcome in supported:
        assert outcome.attribution_ok is True, outcome.case_id
        assert outcome.actual_supported is True, outcome.case_id
        assert outcome.evidence_sources, outcome.case_id


def test_unsupported_cases_are_refused(report) -> None:
    unsupported = [outcome for outcome in report.outcomes if not outcome.expected_supported]
    assert unsupported
    for outcome in unsupported:
        assert outcome.unsupported_ok is True, outcome.case_id
        assert outcome.actual_supported is False, outcome.case_id


def test_missing_data_case_refuses_for_the_missing_data_reason(report) -> None:
    outcome = next(o for o in report.outcomes if o.case_id == "unsupported-missing-data")
    assert outcome.unsupported_ok is True
    assert outcome.actual_intent == "state_accident_ranking"


def test_metrics_are_not_vacuous_a_wrong_expectation_is_detected(
    raw_settings: Settings,
) -> None:
    wrong = BenchmarkCase(
        case_id="deliberately-wrong",
        category="ranking",
        question="Which states had the highest reported road accidents in 2019?",
        expected_supported=True,
        expected_intent="state_accident_ranking",
        expected_source_file="data/raw/RA2019_A2.csv",
        expected_values={"top_states.0.accidents": 999999999},
    )
    harness = EvaluationHarness(
        raw_settings, ai_settings=AISettings(provider="deterministic"), cases=(wrong,)
    )
    report = harness.run()

    assert report.outcomes[0].numerical_ok is False
    assert report.metrics["numerical_accuracy"] == pytest.approx(0.0)
    assert "top_states.0.accidents" in report.outcomes[0].detail


def test_metrics_are_not_vacuous_a_wrong_intent_is_detected(raw_settings: Settings) -> None:
    wrong = BenchmarkCase(
        case_id="deliberately-wrong-intent",
        category="ranking",
        question="Which states had the highest reported road accidents in 2019?",
        expected_supported=True,
        expected_intent="join_assessment",
    )
    report = EvaluationHarness(
        raw_settings, ai_settings=AISettings(provider="deterministic"), cases=(wrong,)
    ).run()

    assert report.outcomes[0].intent_ok is False
    assert report.metrics["intent_accuracy"] == pytest.approx(0.0)


def test_fabrication_is_caught_when_an_unsupported_case_is_answered(
    raw_settings: Settings,
) -> None:
    # A supported question labelled as unsupported must fail the rejection metric.
    mislabelled = BenchmarkCase(
        case_id="mislabelled",
        category="unsupported",
        question="Which states had the highest reported road accidents in 2019?",
        expected_supported=False,
        expected_intent=None,
    )
    report = EvaluationHarness(
        raw_settings, ai_settings=AISettings(provider="deterministic"), cases=(mislabelled,)
    ).run()

    assert report.outcomes[0].unsupported_ok is False
    assert report.metrics["unsupported_rejection_rate"] == pytest.approx(0.0)


def test_report_is_json_serialisable_and_latency_is_non_negative(report) -> None:
    payload = json.loads(report.to_json())
    assert payload["benchmark_size"] == len(DEFAULT_BENCHMARK)
    assert payload["provider"] == "deterministic"
    for case in payload["cases"]:
        assert case["elapsed_seconds"] >= 0.0
    assert report.metrics["mean_latency_seconds"] >= 0.0
    assert report.metrics["p95_latency_seconds"] >= report.metrics["mean_latency_seconds"] / 2


def test_benchmark_payload_contains_no_raw_dataset_rows(raw_settings: Settings) -> None:
    payload = _harness(raw_settings).benchmark_payload()
    assert len(payload) == len(DEFAULT_BENCHMARK)
    for entry in payload:
        # Only the question and its expectations are stored, never source rows.
        assert "dataframe" not in entry
        assert "columns" not in entry
        assert set(entry) == {
            "case_id",
            "category",
            "question",
            "expected_supported",
            "expected_intent",
            "expected_dataset",
            "expected_source_file",
            "expected_values",
            "expects_missing_data",
            "notes",
        }


def test_cli_ai_evaluate_exits_zero_and_prints_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pathlib import Path

    from civicmind.cli import main

    repo_root = Path(__file__).resolve().parents[1]
    exit_code = main(["ai", "evaluate"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "numerical_accuracy" in output
    assert "attribution_accuracy" in output
    # Sanity: the command ran against the repository's own raw tree.
    assert (repo_root / "data" / "raw" / "RA2019_A2.csv").is_file()
