"""Regression tests for defects found in the adversarial audit.

Each test reproduces a specific defect that was demonstrated against the code
before it was fixed, so a future regression fails here rather than silently
shipping.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from civicmind.ai.analytics import AnalyticsError, state_accident_ranking, state_share
from civicmind.ai.config import AISettings
from civicmind.ai.datasets import MalformedDatasetError, load_dataset
from civicmind.ai.engine import DecisionEngine, register_domain, unregister_domain
from civicmind.ai.intent import QuestionRouter, mentions_label
from civicmind.ai.providers import missing_grounding
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)

_A2_HEADER = (
    "States/UTs,State/UT-Wise Total Number of Road Accidents during 2019 - Numbers,"
    "State/UT-Wise Total Number of Road Accidents during 2019 - Rank,"
    "Share of States/UTs in Total Number of Road Accidents - 2019\n"
)


@pytest.fixture
def raw_tree(tmp_path: Path) -> Settings:
    """A settings object whose data/raw holds files this test controls."""
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    return replace(Settings.from_env({}), project_root=tmp_path, data_dir=data)


def _write(settings: Settings, name: str, text: str) -> Path:
    path = Path(settings.data_dir) / "raw" / name
    path.write_text(text, encoding="utf-8")
    return path


# -- FIX 1: grounding guard matched figures as substrings -------------------


def test_grounding_rejects_a_figure_embedded_in_a_larger_number() -> None:
    summary = "Tamil Nadu reported 57,228 accidents."
    assert missing_grounding("Tamil Nadu reported 57228 accidents.", summary, ()) == ()
    assert missing_grounding("Tamil Nadu reported 157228 accidents.", summary, ())
    assert missing_grounding("Tamil Nadu reported 572280 accidents.", summary, ())


def test_grounding_rejects_an_altered_decimal_precision() -> None:
    summary = "The share was 4.80399%."
    assert missing_grounding("The share was 4.80399%.", summary, ()) == ()
    assert missing_grounding("The share was 4.803991%.", summary, ())
    assert missing_grounding("The share was 14.80399%.", summary, ())


def test_grounding_rejects_a_sign_flip() -> None:
    summary = "Tamil Nadu reported 57,228 accidents."
    assert missing_grounding("Tamil Nadu reported -57228 accidents.", summary, ())


def test_grounding_still_accepts_a_faithful_answer() -> None:
    summary = "Tamil Nadu reported 57,228 accidents; the total was 449,002."
    limitations = ("The national 'Total' row is excluded from the ranking.",)
    answer = (
        "Tamil Nadu reported 57228 accidents, a total of 449002. "
        "The national Total row is excluded from the ranking."
    )
    assert missing_grounding(answer, summary, limitations) == ()


def test_grounding_tolerates_punctuation_differences_in_limitations() -> None:
    summary = "Kerala reported 41,111 accidents."
    limitations = ("The national 'Total' row is excluded from the ranking.",)
    # The limitation carries quotes in the source; an answer that drops or adds
    # them must still be accepted (this previously caused a needless fallback).
    for tail in (
        "The national 'Total' row is excluded from the ranking.",
        "The national Total row is excluded from the ranking.",
        "the national total row is excluded from the ranking",
    ):
        assert (
            missing_grounding(f"Kerala reported 41111 accidents. {tail}", summary, limitations)
            == ()
        )


def test_grounding_is_string_level_only_and_does_not_verify_context() -> None:
    # Documented limitation: the guard checks that figures are present, not that
    # they are used correctly. Identical numbers in a wrong context still pass.
    summary = "Tamil Nadu reported 57,228 accidents and 449,002 injuries."
    answer = "Tamil Nadu reported 449002 accidents and 57228 injuries."
    assert missing_grounding(answer, summary, ()) == ()


# -- FIX 2: a missing value escaped the engine as an unhandled TypeError -----


def test_state_share_handles_a_missing_count_instead_of_raising(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nGujarat,NA,2,9.0\nTotal ,100,NA,100\n",
    )
    result = state_share(raw_tree, state="Gujarat")

    assert result.value["accidents"] is None
    assert result.value["share_percent"] == pytest.approx(9.0)
    assert result.warnings
    assert "unavailable" in result.summary


def test_state_share_handles_both_values_missing(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nGujarat,NA,NA,NA\nTotal ,100,NA,100\n",
    )
    result = state_share(raw_tree, state="Gujarat")

    assert result.value["accidents"] is None
    assert result.value["share_percent"] is None
    assert result.warnings
    assert "unavailable" in result.summary


def test_engine_refuses_when_a_missing_value_is_requested(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nGujarat,NA,NA,NA\nTotal ,100,NA,100\n",
    )
    engine = DecisionEngine(raw_tree, ai_settings=AISettings(provider="deterministic"))
    # Must not raise: previously this raised TypeError out of ask().
    answer = engine.ask("What published share did Gujarat have in 2019?")
    assert answer.supported is True
    assert "unavailable" in answer.explanation.lower()


def test_engine_contains_an_unexpected_analytics_exception(raw_settings: Settings) -> None:
    def exploding(settings: Settings, **kwargs: object):  # noqa: ANN202 - test stub
        raise TypeError("unsupported format string passed to NoneType.__format__")

    register_domain(
        "audit_boom", dataset_id="RA2019_A2", operation=exploding, patterns=("audit boom probe",)
    )
    try:
        engine = DecisionEngine(raw_settings, ai_settings=AISettings(provider="deterministic"))
        answer = engine.ask("run the audit boom probe")
        assert answer.supported is False
        assert answer.result is None
        assert answer.extra.get("blocked_kind") == "analytics-error"
    finally:
        unregister_domain("audit_boom")


def test_api_returns_a_clean_response_for_an_exploding_operation(
    raw_settings: Settings,
) -> None:
    from fastapi.testclient import TestClient

    from civicmind.ai.api import create_app

    def exploding(settings: Settings, **kwargs: object):  # noqa: ANN202 - test stub
        raise TypeError("unsupported format string passed to NoneType.__format__")

    register_domain(
        "audit_boom_api",
        dataset_id="RA2019_A2",
        operation=exploding,
        patterns=("audit boom api probe",),
    )
    try:
        ai_settings = AISettings(provider="deterministic")
        app = create_app(
            raw_settings,
            ai_settings=ai_settings,
            engine=DecisionEngine(raw_settings, ai_settings=ai_settings),
        )
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/ask", json={"question": "run the audit boom api probe"})
        assert response.status_code == 200
        assert response.json()["supported"] is False
    finally:
        unregister_domain("audit_boom_api")


# -- FIX 3: a real but short state name ("Goa") was unqueryable -------------


def test_short_real_state_name_is_queryable(raw_settings: Settings) -> None:
    router = QuestionRouter(raw_settings)
    assert router.find_state("What published share did Goa have in 2019?") == "Goa"

    engine = DecisionEngine(raw_settings, ai_settings=AISettings(provider="deterministic"))
    answer = engine.ask("What published share did Goa have in 2019?")
    assert answer.supported is True
    assert answer.intent == "state_share"
    assert answer.result["state"] == "Goa"


def test_boundary_matching_does_not_match_inside_a_word() -> None:
    assert mentions_label("what is the goal for 2019", "Goa") is False
    assert mentions_label("share of goa in 2019", "Goa") is True
    # Punctuation and multi-word labels still match as whole tokens.
    assert mentions_label("share of jammu & kashmir in 2019", "Jammu & Kashmir") is True


def test_unknown_state_is_still_refused(raw_settings: Settings) -> None:
    router = QuestionRouter(raw_settings)
    assert router.find_state("share of atlantis in 2019") is None


# -- FIX 4: missing counts silently shrank the ranking denominator ----------


def test_state_ranking_warns_when_rows_are_dropped_for_na(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nGoa,NA,2,9.0\nTotal ,100,NA,100\n",
    )
    result = state_accident_ranking(raw_tree, year=2019)

    assert result.value["reported_total"] == 100
    assert result.value["states_considered"] == 1
    assert result.warnings
    assert "Goa" in result.warnings[0]
    assert "missing, not zero" in result.warnings[0]


def test_state_ranking_has_no_warning_on_clean_data(raw_settings: Settings) -> None:
    assert state_accident_ranking(raw_settings, year=2019).warnings == ()


# -- FIX 5: ranking order for tied values was unspecified -------------------


def test_tied_rankings_keep_source_order(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Alpha,100,1,5.0\nBeta,100,1,5.0\nGamma,100,3,5.0\nTotal ,300,NA,100\n",
    )
    first = state_accident_ranking(raw_tree, year=2019, limit=3).value["top_states"]
    second = state_accident_ranking(raw_tree, year=2019, limit=3).value["top_states"]
    assert [item["state"] for item in first] == ["Alpha", "Beta", "Gamma"]
    assert first == second


# -- FIX 6: a malformed (ragged) row was silently padded --------------------


def test_ragged_row_is_rejected_instead_of_silently_padded(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nBroken,200\nTotal ,300,NA,100\n",
    )
    with pytest.raises(MalformedDatasetError, match="do not match the 4-field header"):
        load_dataset(raw_tree, "RA2019_A2")


def test_ragged_row_is_refused_by_the_engine(raw_tree: Settings) -> None:
    _write(
        raw_tree,
        "RA2019_A2.csv",
        _A2_HEADER + "Kerala,100,1,5.0\nBroken,200\nTotal ,300,NA,100\n",
    )
    engine = DecisionEngine(raw_tree, ai_settings=AISettings(provider="deterministic"))
    answer = engine.ask("Which states had the highest reported road accidents in 2019?")
    assert answer.supported is False
    assert answer.extra.get("blocked_kind") == "analytics-error"


def test_all_five_real_files_have_consistent_row_widths(raw_settings: Settings) -> None:
    # The strict width check must not reject any shipped dataset.
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "RA2019_A52", "BWSSB_WATER"):
        assert load_dataset(raw_settings, dataset_id).dataframe is not None


def test_renamed_columns_are_refused_not_silently_accepted(raw_tree: Settings) -> None:
    _write(raw_tree, "RA2019_A2.csv", "Region,Crashes in 2019\nKerala,12345\n")
    with pytest.raises(KeyError):
        state_accident_ranking(raw_tree, year=2019)


def test_unsupported_year_still_raises(raw_settings: Settings) -> None:
    with pytest.raises(AnalyticsError):
        state_accident_ranking(raw_settings, year=2024)
