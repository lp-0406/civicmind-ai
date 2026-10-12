"""Tests for the AI-layer dataset loader (encoding, columns, missing values)."""

from __future__ import annotations

from pathlib import Path

import pytest

from civicmind.ai.datasets import (
    DATASET_SPECS,
    UnavailableDatasetError,
    available_datasets,
    dataset_path,
    find_column,
    find_columns_containing,
    get_spec,
    is_total_row,
    list_dataset_specs,
    load_dataset,
    numeric_series,
    observations_only,
    read_text_with_fallback,
)
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS, RAW_DIR

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


def test_all_five_declared_datasets_are_available(raw_settings: Settings) -> None:
    available = {spec.dataset_id for spec in available_datasets(raw_settings)}
    assert available == {
        "RA2019_A2",
        "RA2019_A47",
        "RA2019_A49",
        "RA2019_A52",
        "BWSSB_WATER",
    }
    assert len(list_dataset_specs()) == 5


def test_dataset_paths_live_under_the_configured_raw_dir(raw_settings: Settings) -> None:
    for spec in list_dataset_specs():
        path = dataset_path(raw_settings, spec.dataset_id)
        assert path.parent == raw_settings.raw_data_dir
        assert path.name == spec.filename


def test_original_column_names_are_preserved(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "BWSSB_WATER")
    # The source header genuinely carries a trailing space; it is not rewritten.
    assert "Ward number " in loaded.columns
    assert "Consumption in ML" in loaded.columns


def test_find_column_matches_ignoring_whitespace_and_case(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "BWSSB_WATER")
    assert find_column(loaded.dataframe, "ward number") == "Ward number "
    with pytest.raises(KeyError):
        find_column(loaded.dataframe, "nonexistent column")


def test_windows_1252_encoding_is_used_for_the_blackspot_file(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "RA2019_A52")
    assert loaded.encoding == "cp1252"
    # Decoding succeeded and the state column is intact.
    assert "Tripura" in set(loaded.dataframe[find_column(loaded.dataframe, "State")])


def test_utf8_encoding_is_used_for_the_other_files(raw_settings: Settings) -> None:
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "BWSSB_WATER"):
        assert load_dataset(raw_settings, dataset_id).encoding == "utf-8-sig"


def test_read_text_with_fallback_reports_the_encoding() -> None:
    text, encoding = read_text_with_fallback(RAW_DIR / "RA2019_A52.csv", ("utf-8", "cp1252"))
    assert encoding == "cp1252"
    assert "State" in text


def test_read_text_with_fallback_raises_when_no_encoding_works(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"\xff\xfe\x00\x00not decodable")
    with pytest.raises(UnicodeDecodeError):
        read_text_with_fallback(bad, ("utf-8", "ascii"))


def test_na_loads_as_missing_not_zero(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "RA2019_A47")
    rank_column = find_column(loaded.dataframe, "Over-Speeding - Number of Accidents - Rank")
    ranks = numeric_series(loaded.dataframe, rank_column)
    # The aggregate 'Total' row has an 'NA' rank; it must be missing, not 0.
    assert ranks.isna().any()
    assert not (ranks.dropna() == 0).any()


def test_observations_only_excludes_aggregate_total_rows(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "RA2019_A2")
    assert len(loaded.dataframe) == 37
    filtered = observations_only(loaded)
    assert len(filtered) == 36
    label_column = find_column(filtered, "States/UTs")
    assert not any(is_total_row(value) for value in filtered[label_column])


def test_is_total_row_handles_the_trailing_space_label() -> None:
    assert is_total_row("Total ")
    assert is_total_row("total")
    assert not is_total_row("Telangana")


def test_missing_dataset_raises_unavailable_error(pilot_settings: Settings) -> None:
    with pytest.raises(UnavailableDatasetError):
        load_dataset(pilot_settings, "RA2019_A2")


def test_get_spec_accepts_the_water_canonical_alias() -> None:
    assert get_spec("WTR-005").dataset_id == "BWSSB_WATER"
    with pytest.raises(KeyError):
        get_spec("NOPE-999")


def test_find_columns_containing_matches_all_needles(raw_settings: Settings) -> None:
    loaded = load_dataset(raw_settings, "RA2019_A49")
    matches = find_columns_containing(loaded.dataframe, "t-junction", "total injured")
    assert matches == ["T-Junction - Persons Injured - Total Injured"]


def test_specs_record_mapping_and_license_status() -> None:
    water = DATASET_SPECS["BWSSB_WATER"]
    assert water.canonical_id == "WTR-005"
    assert water.mapping_status == "plausible but unverified"
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "RA2019_A52"):
        assert DATASET_SPECS[dataset_id].canonical_id is None
