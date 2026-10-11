"""Tests for deterministic CSV profiling.

Profiling must measure the artifact rather than assume anything about it, and
must never emit individual cell values.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.profiling.csv_profile import (
    ProfileError,
    infer_type,
    profile_csv,
)

FIXED_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _write(tmp_path: Path, data: bytes, name: str = "artifact.csv") -> Path:
    """Write ``data`` under ``tmp_path`` and return the path."""
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _profile(tmp_path: Path, data: bytes, name: str = "artifact.csv"):
    """Write ``data`` and profile it with a fixed clock."""
    return profile_csv(_write(tmp_path, data, name), clock=lambda: FIXED_TIME)


SAMPLE = (
    b"City,Vehicles,Year,Verified,Observed,Ratio,Note\n"
    b"Ahmedabad,3200000,2016,true,2026-01-02,0.5,first\n"
    b"Bhopal,1100000,2016,false,2026-01-03,0.25,\n"
    b"Indore,1500000,2017,yes,2026-02-04,0.75,third\n"
    b"Indore,1500000,2017,yes,2026-02-04,0.75,third\n"
)


def test_shape_is_measured_not_assumed(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)

    assert profile.header == (
        "City",
        "Vehicles",
        "Year",
        "Verified",
        "Observed",
        "Ratio",
        "Note",
    )
    assert profile.column_count == 7
    assert profile.data_rows == 4
    assert profile.duplicate_rows == 1
    assert profile.ragged_rows == 0
    assert profile.byte_size == len(SAMPLE)
    assert profile.checksum_sha256 == hashlib.sha256(SAMPLE).hexdigest()
    assert profile.encoding == "utf-8-sig"
    assert profile.sampled is False
    assert profile.generated_at == FIXED_TIME


def test_column_types_are_inferred_from_the_values(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)
    types = {column.name: column.inferred_type for column in profile.columns}

    assert types == {
        "City": "text",
        "Vehicles": "integer",
        "Year": "integer",
        "Verified": "boolean",
        "Observed": "date",
        "Ratio": "number",
        "Note": "text",
    }


def test_missing_values_and_percentages_are_measured(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)
    note = next(column for column in profile.columns if column.name == "Note")

    assert note.non_empty == 3
    assert note.empty == 1
    assert note.empty_percentage == 25.0
    assert any("sparse" in warning for warning in profile.warnings) is False


def test_a_mostly_empty_column_is_reported_as_sparse(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b"a,b\n1,\n2,\n3,last\n")

    assert any("'b' is sparse" in warning for warning in profile.warnings)


def test_numeric_statistics_are_produced_for_numeric_columns(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)
    vehicles = next(column for column in profile.columns if column.name == "Vehicles")

    assert vehicles.numeric is not None
    assert vehicles.numeric.count == 4
    assert vehicles.numeric.minimum == 1_100_000
    assert vehicles.numeric.maximum == 3_200_000
    assert vehicles.numeric.mean == pytest.approx(1_825_000)
    assert vehicles.numeric.median == pytest.approx(1_500_000)


def test_text_columns_carry_no_numeric_summary(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)
    city = next(column for column in profile.columns if column.name == "City")

    assert city.numeric is None
    assert city.distinct == 3


def test_distinct_counts_ignore_empty_values(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b"a\nx\ny\n\nx\n")
    column = profile.columns[0]

    assert column.distinct == 2
    assert column.empty == 1


def test_ragged_rows_are_counted_and_warned_about(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b"a,b,c\n1,2,3\n4,5\n6,7,8,9\n")

    assert profile.ragged_rows == 2
    assert any("do not match the header" in warning for warning in profile.warnings)


def test_a_header_only_file_is_flagged_not_failed(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b"a,b\n")

    assert profile.data_rows == 0
    assert any("no data rows" in warning for warning in profile.warnings)


def test_profiling_is_deterministic(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE)

    first = profile_csv(path, clock=lambda: FIXED_TIME).as_dict()
    second = profile_csv(path, clock=lambda: FIXED_TIME).as_dict()

    assert first == second


def test_sampling_is_recorded_and_labelled(tmp_path: Path) -> None:
    profile = _profile(tmp_path, SAMPLE)
    sampled = profile_csv(
        _write(tmp_path, SAMPLE, "sampled.csv"), max_rows=2, clock=lambda: FIXED_TIME
    )

    assert sampled.sampled is True
    assert sampled.max_rows == 2
    assert sampled.data_rows == 2
    assert any("first 2 data row(s) only" in warning for warning in sampled.warnings)
    assert profile.data_rows == 4


def test_profile_never_contains_cell_values(tmp_path: Path) -> None:
    payload = _profile(
        tmp_path, b"City,Secret\nAhmedabad,MARKER-VALUE-9\nBhopal,MARKER-VALUE-8\n"
    ).as_dict()

    rendered = json.dumps(payload)
    assert "MARKER-VALUE-9" not in rendered
    assert "MARKER-VALUE-8" not in rendered
    assert "Ahmedabad" not in rendered
    # Column names are structure, not row values, so they are reported.
    assert payload["shape"]["header"] == ["City", "Secret"]


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="not found"):
        profile_csv(tmp_path / "absent.csv")


def test_an_empty_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="empty"):
        profile_csv(_write(tmp_path, b""))


def test_non_utf8_content_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        profile_csv(_write(tmp_path, b"City,Year\n\xff\xfe\x00\x00\x01\n"))


def test_a_file_with_no_header_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="no header row"):
        profile_csv(_write(tmp_path, b"\n\n"))


def test_a_malformed_record_is_recorded_as_a_parse_error(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b'a,b\n1,2\n3,"unclosed\n')

    assert profile.data_rows == 1
    assert profile.parse_errors
    assert "CSV parse error" in profile.parse_errors[0]


def test_a_utf8_bom_does_not_become_part_of_the_first_column_name(tmp_path: Path) -> None:
    profile = _profile(tmp_path, b"\xef\xbb\xbfCity,Year\nAhmedabad,2016\n")

    assert profile.header == ("City", "Year")
    assert profile.byte_size == len(b"\xef\xbb\xbfCity,Year\nAhmedabad,2016\n")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "2", "3"], "integer"),
        (["1.5", "2"], "number"),
        (["true", "no"], "boolean"),
        (["2016-01-02", "2016-02-03"], "date"),
        (["Ahmedabad", "1"], "text"),
        (["", "  "], "empty"),
    ],
)
def test_type_inference_vocabulary(values: list[str], expected: str) -> None:
    assert infer_type(values) == expected
