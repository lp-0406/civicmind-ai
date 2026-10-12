"""Tests for the deterministic analytics engine.

Expected values were recomputed independently with the standard library
(``csv``) against the same raw files, so a regression in the pandas engine is
caught rather than mirrored.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from civicmind.ai.analytics import (
    AnalyticsError,
    UnsupportedOperationError,
    blackspot_ranking,
    dataset_quality_report,
    join_assessment,
    junction_injury_totals,
    overspeeding_ranking,
    state_accident_ranking,
    state_share,
    ward_water_consumption,
    water_connection_summary,
)
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS, RAW_DIR

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


def _stdlib_rows(name: str, encoding: str) -> list[dict[str, str]]:
    with (RAW_DIR / name).open(encoding=encoding, newline="") as handle:
        return list(csv.DictReader(handle))


# -- state accidents (RA2019_A2) ------------------------------------------


def test_state_accident_ranking_matches_an_independent_recomputation(
    raw_settings: Settings,
) -> None:
    result = state_accident_ranking(raw_settings, year=2019, limit=10)

    assert [item["state"] for item in result.value["top_states"]][:3] == [
        "Tamil Nadu",
        "Madhya Pradesh",
        "Uttar Pradesh",
    ]
    assert result.value["top_states"][0]["accidents"] == 57228
    assert result.value["reported_total"] == 449002
    assert result.value["states_considered"] == 36

    rows = _stdlib_rows("RA2019_A2.csv", "utf-8-sig")
    count_column = next(
        column for column in rows[0] if "Road Accidents during 2019 - Numbers" in column
    )
    observations = [row for row in rows if row["States/UTs"].strip().lower() != "total"]
    assert sum(int(row[count_column]) for row in observations) == result.value["reported_total"]


def test_state_accident_ranking_excludes_the_total_row(raw_settings: Settings) -> None:
    result = state_accident_ranking(raw_settings, year=2019, limit=50)
    states = [item["state"] for item in result.value["top_states"]]
    assert "Total" not in states
    assert not any(state.strip().lower() == "total" for state in states)


def test_state_ranking_supports_every_declared_year(raw_settings: Settings) -> None:
    for year in (2016, 2017, 2018, 2019):
        result = state_accident_ranking(raw_settings, year=year, limit=1)
        assert result.value["year"] == year
        assert result.value["top_states"][0]["accidents"] > 0


def test_state_ranking_rejects_an_unsupported_year(raw_settings: Settings) -> None:
    with pytest.raises(UnsupportedOperationError):
        state_accident_ranking(raw_settings, year=2024)


def test_state_share_matches_the_published_value(raw_settings: Settings) -> None:
    result = state_share(raw_settings, state="Telangana", year=2019)

    assert result.value["state"] == "Telangana"
    assert result.value["accidents"] == 21570
    assert result.value["rank"] == 9
    assert result.value["share_percent"] == pytest.approx(4.80398751, rel=1e-6)

    rows = _stdlib_rows("RA2019_A2.csv", "utf-8-sig")
    share_column = next(
        column for column in rows[0] if column.startswith("Share") and column.endswith("2019")
    )
    telangana = next(row for row in rows if row["States/UTs"] == "Telangana")
    assert float(telangana[share_column]) == pytest.approx(result.value["share_percent"])


def test_state_share_is_case_insensitive(raw_settings: Settings) -> None:
    assert state_share(raw_settings, state="telangana").value["share_percent"] == pytest.approx(
        4.80398751, rel=1e-6
    )


def test_state_share_rejects_an_unknown_state(raw_settings: Settings) -> None:
    with pytest.raises(AnalyticsError):
        state_share(raw_settings, state="Atlantis")


# -- junction injuries (RA2019_A49) ---------------------------------------


def test_junction_injury_totals_match_an_independent_recomputation(
    raw_settings: Settings,
) -> None:
    result = junction_injury_totals(raw_settings)

    totals = {item["category"]: item["total_injured"] for item in result.value["categories"]}
    assert totals == {
        "T-Junction": 10271,
        "Y-Junction": 4831,
        "Four arm Junction": 7330,
        "Staggered Junction": 6076,
        "Round about Junction": 3619,
        "Others": 41993,
    }
    assert result.value["cities_considered"] == 50

    # Independent recomputation from the raw file.
    rows = _stdlib_rows("RA2019_A49.csv", "utf-8-sig")
    cities = [row for row in rows if row["States/UTs"].strip().lower() != "total"]
    for category, expected in totals.items():
        column = next(c for c in rows[0] if c.startswith(category) and "Total Injured" in c)
        assert sum(int(row[column] or 0) for row in cities) == expected


def test_junction_totals_are_sorted_descending(raw_settings: Settings) -> None:
    categories = junction_injury_totals(raw_settings).value["categories"]
    values = [item["total_injured"] for item in categories]
    assert values == sorted(values, reverse=True)


# -- over-speeding and blackspots -----------------------------------------


def test_overspeeding_ranking_is_computed_from_the_source(raw_settings: Settings) -> None:
    result = overspeeding_ranking(raw_settings, limit=5)
    assert len(result.value["top_cities"]) == 5
    assert result.value["cities_considered"] == 50
    top = result.value["top_cities"][0]
    assert top["over_speeding_accidents"] >= top["persons_killed"]

    rows = _stdlib_rows("RA2019_A47.csv", "utf-8-sig")
    column = next(
        c for c in rows[0] if c.startswith("Over-Speeding") and "Number of Accidents" in c
    )
    cities = [row for row in rows if row["States/UTs"].strip().lower() != "total"]
    best = max(int(row[column]) for row in cities)
    assert top["over_speeding_accidents"] == best


def test_blackspot_ranking_totals_the_three_year_window(raw_settings: Settings) -> None:
    result = blackspot_ranking(raw_settings, limit=5)
    assert result.value["locations_considered"] == 273
    for item in result.value["top_locations"]:
        assert item["accidents_2016_2018"] >= item["fatalities_2016_2018"]

    rows = _stdlib_rows("RA2019_A52.csv", "cp1252")
    column = "Numbers of Accidents - Total of all three years"
    best = max(int(row[column]) for row in rows)
    assert result.value["top_locations"][0]["accidents_2016_2018"] == best


# -- water (BWSSB) ---------------------------------------------------------


def test_ward_water_consumption_matches_an_independent_recomputation(
    raw_settings: Settings,
) -> None:
    result = ward_water_consumption(raw_settings, limit=3)
    top = result.value["top_wards"]

    assert top[0]["ward_name"] == "HSR Layout"
    assert top[0]["ward_number"] == "174"
    assert top[0]["consumption_ml"] == pytest.approx(605.66)
    assert result.value["wards_considered"] == 202
    assert result.value["total_consumption_ml"] == pytest.approx(30580.05, rel=1e-9)

    rows = _stdlib_rows("BWSSB_Water_Consumption_August_2025.csv", "utf-8-sig")
    assert round(sum(float(row["Consumption in ML"]) for row in rows), 2) == pytest.approx(
        result.value["total_consumption_ml"], rel=1e-6
    )


def test_water_connection_summary_totals_connections(raw_settings: Settings) -> None:
    result = water_connection_summary(raw_settings)
    rows = _stdlib_rows("BWSSB_Water_Consumption_August_2025.csv", "utf-8-sig")
    expected_total = sum(int(row["Number of Connections"]) for row in rows)
    assert result.value["total_connections"] == expected_total
    assert result.value["wards_considered"] == 202


# -- quality and joins -----------------------------------------------------


def test_dataset_quality_report_counts_rows_and_missing(raw_settings: Settings) -> None:
    result = dataset_quality_report(raw_settings, dataset_id="RA2019_A47")
    assert result.value["rows"] == 51
    assert result.value["columns"] == 33
    assert result.value["encoding"] == "utf-8-sig"
    assert result.value["duplicate_rows"] == 0
    assert sum(result.value["missing_by_column"].values()) > 0


def test_join_assessment_reports_a_defensible_traffic_join(raw_settings: Settings) -> None:
    result = join_assessment(raw_settings)
    assert result.value["water_joinable"] is False
    pairs = {(pair["left"], pair["right"]): pair for pair in result.value["pairs"]}
    assert pairs[("RA2019_A47", "RA2019_A49")]["reliable"] is True
    assert pairs[("RA2019_A47", "RA2019_A49")]["shared_labels"] == 50
    assert pairs[("RA2019_A2", "RA2019_A47")]["reliable"] is False
    assert pairs[("RA2019_A52", "RA2019_A2/A47/A49")]["reliable"] is False


def test_every_result_carries_evidence_and_limitations(raw_settings: Settings) -> None:
    for result in (
        state_accident_ranking(raw_settings),
        state_share(raw_settings, state="Kerala"),
        junction_injury_totals(raw_settings),
        ward_water_consumption(raw_settings),
    ):
        evidence = result.evidence
        assert evidence.source_file.startswith("data/raw/")
        assert evidence.limitations
        assert evidence.operation == result.operation
        assert evidence.citation()


def test_invalid_limit_is_rejected(raw_settings: Settings) -> None:
    with pytest.raises(AnalyticsError):
        state_accident_ranking(raw_settings, limit=0)


def test_analytics_result_is_json_serialisable(raw_settings: Settings) -> None:
    import json

    payload = json.dumps(state_accident_ranking(raw_settings, limit=3).to_dict())
    assert "Tamil Nadu" in payload


def test_results_use_the_real_source_paths(raw_settings: Settings) -> None:
    result = ward_water_consumption(raw_settings, limit=1)
    assert Path(result.evidence.source_file).name == "BWSSB_Water_Consumption_August_2025.csv"
    assert result.evidence.canonical_id == "WTR-005"
    assert result.evidence.mapping_status == "plausible but unverified"
