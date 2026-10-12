"""Deterministic analytics over the five supplied municipal CSVs.

Every number returned by this module is computed from the raw source file with
pandas. No language model participates in any calculation. Operations preserve
the source's own scales (published shares stay on a 0-100 scale), keep ``NA`` as
missing, exclude aggregate ``Total`` rows from per-entity rankings, and refuse
unsupported operations instead of inventing a result.

Each operation returns an :class:`AnalyticsResult`, which bundles the structured
value, a deterministic prose summary and a fully populated
:class:`~civicmind.ai.evidence.Evidence` object.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from civicmind.ai.datasets import (
    LoadedDataset,
    build_evidence,
    find_column,
    find_columns_containing,
    load_dataset,
    normalize_column_name,
    numeric_series,
    observations_only,
)
from civicmind.ai.evidence import Evidence


class AnalyticsError(RuntimeError):
    """Raised when an analytics operation cannot be computed truthfully."""


class UnsupportedOperationError(AnalyticsError):
    """Raised when a requested operation is not supported by the data."""


@dataclass(frozen=True)
class AnalyticsResult:
    """The outcome of one deterministic analytics operation."""

    intent: str
    dataset_id: str
    operation: str
    summary: str
    value: Any
    evidence: Evidence
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the result."""
        return {
            "intent": self.intent,
            "dataset_id": self.dataset_id,
            "operation": self.operation,
            "summary": self.summary,
            "value": self.value,
            "warnings": list(self.warnings),
            "evidence": self.evidence.to_dict(),
        }


# ---------------------------------------------------------------------------
# Column selection helpers (kept explicit; the source headers are irregular)
# ---------------------------------------------------------------------------

_A2_ACCIDENT_YEARS = (2016, 2017, 2018, 2019)


def _a2_number_column(dataframe: Any, year: int) -> str:
    """Return the RA2019_A2 accident-count column for ``year``."""
    if year not in _A2_ACCIDENT_YEARS:
        raise UnsupportedOperationError(
            f"RA2019_A2 covers {_A2_ACCIDENT_YEARS[0]}-{_A2_ACCIDENT_YEARS[-1]}; "
            f"{year} is unsupported"
        )
    candidates = [
        column
        for column in find_columns_containing(dataframe, "road accidents", f"during {year}")
        if "rank" not in normalize_column_name(column)
    ]
    # The 2019 count column appends '- Numbers'; the earlier years do not.
    numbered = [c for c in candidates if "numbers" in normalize_column_name(c)]
    chosen = numbered or candidates
    if len(chosen) != 1:
        raise UnsupportedOperationError(
            f"could not uniquely resolve the {year} accident-count column in RA2019_A2"
        )
    return chosen[0]


def _a2_share_column(dataframe: Any, year: int) -> str:
    """Return the RA2019_A2 published-share column for ``year``."""
    candidates = find_columns_containing(dataframe, "share of states", str(year))
    if len(candidates) != 1:
        raise UnsupportedOperationError(
            f"could not uniquely resolve the {year} share column in RA2019_A2"
        )
    return candidates[0]


def _a2_rank_column(dataframe: Any) -> str:
    """Return the RA2019_A2 2019 rank column."""
    candidates = [
        column
        for column in find_columns_containing(dataframe, "during 2019")
        if "rank" in normalize_column_name(column)
    ]
    if len(candidates) != 1:
        raise UnsupportedOperationError("could not uniquely resolve the 2019 rank column")
    return candidates[0]


_JUNCTION_CATEGORIES: tuple[str, ...] = (
    "T-Junction",
    "Y-Junction",
    "Four arm Junction",
    "Staggered Junction",
    "Round about Junction",
    "Others",
)


def _junction_injured_column(dataframe: Any, category: str) -> str:
    """Return the total-injured column for a junction category, excluding the grand total."""
    candidates = [
        column
        for column in find_columns_containing(dataframe, category, "total injured")
        if not normalize_column_name(column).startswith("total -")
    ]
    if len(candidates) != 1:
        raise UnsupportedOperationError(
            f"could not uniquely resolve the injured column for junction category {category!r}"
        )
    return candidates[0]


def _single(dataframe: Any, *needles: str, exclude: tuple[str, ...] = ()) -> str:
    """Return the single column containing every needle (and no excluded term), or raise."""
    candidates = [
        column
        for column in find_columns_containing(dataframe, *needles)
        if not any(term in normalize_column_name(column) for term in exclude)
    ]
    if len(candidates) != 1:
        raise UnsupportedOperationError(
            f"could not uniquely resolve a column for {needles!r} "
            f"(found {len(candidates)}: {candidates})"
        )
    return candidates[0]


def _int_or_none(value: Any) -> int | None:
    number = _optional_float(value)
    return None if number is None else int(number)


def _optional_float(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is missing or non-finite."""
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) or math.isinf(number) else number


def _records(frame: Any, columns: list[str]) -> tuple[dict[str, Any], ...]:
    """Convert a DataFrame slice into JSON-safe source records."""
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        record: dict[str, Any] = {}
        for column in columns:
            value = row[column]
            if value != value:  # NaN
                record[str(column)] = None
            elif hasattr(value, "item"):
                record[str(column)] = value.item()
            else:
                record[str(column)] = value
        records.append(record)
    return tuple(records)


def _label_column(loaded: LoadedDataset) -> str:
    """Return the identifier/label column for a dataset."""
    return find_column(loaded.dataframe, loaded.spec.id_column)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def state_accident_ranking(
    settings: Any,
    *,
    year: int = 2019,
    limit: int = 10,
) -> AnalyticsResult:
    """Rank states/UTs by reported road accidents for a year (RA2019_A2)."""
    if limit <= 0:
        raise AnalyticsError("limit must be positive")
    loaded = load_dataset(settings, "RA2019_A2")
    label_column = _label_column(loaded)
    count_column = _a2_number_column(loaded.dataframe, year)

    frame = observations_only(loaded)
    counts = numeric_series(frame, count_column)
    missing_labels = [str(value) for value in frame.loc[counts.isna(), label_column]]
    frame = frame.assign(_count=counts).dropna(subset=["_count"])
    # ``kind="stable"`` keeps equal counts in source order so a ranking with ties
    # is reproducible instead of depending on the sort implementation.
    ranked = frame.sort_values("_count", ascending=False, kind="stable").head(limit)

    total = int(numeric_series(observations_only(loaded), count_column).sum())
    top = [
        {"state": str(row[label_column]), "accidents": _int_or_none(row["_count"])}
        for _, row in ranked.iterrows()
    ]

    summary = (
        f"Based on {loaded.source_file}, the states/UTs with the highest reported road "
        f"accidents in {year} are: "
        + "; ".join(f"{item['state']} ({item['accidents']:,})" for item in top)
        + f". These {len(top)} states/UTs account for "
        f"{sum(item['accidents'] or 0 for item in top):,} of the "
        f"{total:,} reported accidents across the {len(frame)} reporting states/UTs in {year}."
    )

    evidence = build_evidence(
        loaded,
        operation="state_accident_ranking",
        units="road accidents",
        record_count=len(frame),
        columns=(label_column, count_column),
        supporting_records=_records(ranked, [label_column, count_column]),
        time_period=str(year),
        limitations=(
            "Counts are as reported by the source; reporting coverage and definitions "
            "vary by state.",
            "The national 'Total ' row is excluded from the ranking and reported separately.",
            "No causal inference is drawn from these descriptive totals.",
        ),
        extra={"year": year, "limit": limit, "reported_total": total},
    )
    warnings: tuple[str, ...] = ()
    if missing_labels:
        warnings = (
            f"{len(missing_labels)} state(s)/UT(s) were excluded from the ranking because the "
            f"source records 'NA' for {year}: {', '.join(missing_labels)}. 'NA' is treated as "
            "missing, not zero, so these states are absent from the reported total.",
        )
    return AnalyticsResult(
        intent="state_accident_ranking",
        dataset_id="RA2019_A2",
        operation="state_accident_ranking",
        summary=summary,
        value={
            "year": year,
            "top_states": top,
            "reported_total": total,
            "states_considered": len(frame),
        },
        evidence=evidence,
        warnings=warnings,
    )


def state_share(settings: Any, *, state: str, year: int = 2019) -> AnalyticsResult:
    """Return a state's published accident share (0-100 scale) and its count."""
    if year not in _A2_ACCIDENT_YEARS:
        raise UnsupportedOperationError(f"RA2019_A2 covers 2016-2019; {year} is unsupported")
    loaded = load_dataset(settings, "RA2019_A2")
    label_column = _label_column(loaded)
    frame = observations_only(loaded)
    share_column = _a2_share_column(frame, year)
    count_column = _a2_number_column(frame, year)

    wanted = normalize_column_name(state)
    labels = frame[label_column].map(lambda value: normalize_column_name(str(value)))
    exact = frame[labels == wanted]
    if exact.empty:
        matched = frame[labels.str.contains(wanted, regex=False)]
        if len(matched) != 1:
            known = ", ".join(sorted(str(v) for v in frame[label_column]))
            raise AnalyticsError(f"no unique state/UT matching {state!r}; known entries: {known}")
        row = matched.iloc[0]
    else:
        row = exact.iloc[0]

    share = _optional_float(numeric_series(frame, share_column).loc[row.name])
    count = _int_or_none(numeric_series(frame, count_column).loc[row.name])
    label = str(row[label_column])
    rank: int | None = None
    if year == 2019:
        rank_series = numeric_series(observations_only(loaded), _a2_rank_column(loaded.dataframe))
        rank = _int_or_none(rank_series.loc[row.name])

    # A source 'NA' is missing, never zero: report the gap instead of formatting
    # a missing value (which previously raised and could not be answered).
    warnings: tuple[str, ...] = ()
    if share is None or count is None:
        unavailable = " and ".join(
            name
            for name, present in (
                ("published share", share is not None),
                ("accident count", count is not None),
            )
            if not present
        )
        warnings = (
            f"The source records 'NA' for {label}'s {unavailable} in {year}; 'NA' is treated "
            "as missing, not zero, so no figure is inferred for it.",
        )

    if share is None and count is None:
        summary = (
            f"{label} has no published share or accident count recorded for {year} in "
            f"{loaded.source_file}; the source marks both values as unavailable."
        )
    elif share is None:
        summary = (
            f"{label} recorded {count:,} reported road accidents in {year}, but the source "
            "marks its published share as unavailable."
        )
    elif count is None:
        summary = (
            f"{label} had a published share of {share:.6g}% of all reported road accidents "
            f"in {year}; the source marks its accident count as unavailable."
        )
    else:
        summary = (
            f"{label} had a published share of {share:.6g}% of all reported road "
            f"accidents in {year}, with {count:,} reported accidents"
            + (f" (2019 rank {rank})." if rank is not None else ".")
        )

    evidence = build_evidence(
        loaded,
        operation="state_share",
        units="percent share (0-100 scale as published)",
        record_count=1,
        columns=(label_column, share_column, count_column),
        supporting_records=(dict(row.to_dict()),),
        time_period=str(year),
        limitations=(
            "The share is the source's own published percentage, already on a 0-100 scale.",
            "The national 'Total ' row reports 100% and is not a state observation.",
        ),
        extra={
            "year": year,
            "state": label,
            "share_percent": share,
            "rank": rank,
        },
    )
    return AnalyticsResult(
        intent="state_share",
        dataset_id="RA2019_A2",
        operation="state_share",
        summary=summary,
        value={
            "state": str(row[label_column]),
            "year": year,
            "share_percent": share,
            "accidents": count,
            "rank": rank,
        },
        evidence=evidence,
        warnings=warnings,
    )


def junction_injury_totals(settings: Any) -> AnalyticsResult:
    """Sum total injuries by junction category across reporting cities (RA2019_A49)."""
    loaded = load_dataset(settings, "RA2019_A49")
    frame = observations_only(loaded)

    totals: list[dict[str, Any]] = []
    columns: list[str] = []
    for category in _JUNCTION_CATEGORIES:
        column = _junction_injured_column(frame, category)
        columns.append(column)
        value = numeric_series(frame, column).sum()
        totals.append(
            {
                "category": category,
                "column": column,
                "total_injured": _int_or_none(value),
            }
        )
    # ``list.sort`` is already stable, so tied categories keep source order.
    totals.sort(key=lambda item: item["total_injured"] or 0, reverse=True)

    summary = (
        f"Across the {len(frame)} reporting cities in {loaded.source_file}, total persons "
        "injured by junction category (summed, highest first): "
        + "; ".join(f"{item['category']} ({item['total_injured']:,})" for item in totals)
        + "."
    )

    evidence = build_evidence(
        loaded,
        operation="junction_injury_totals",
        units="persons injured (summed across reporting cities)",
        record_count=len(frame),
        columns=tuple(columns),
        supporting_records=tuple(totals),
        time_period="2019",
        limitations=(
            "Category totals are summed across reporting cities, not a national census.",
            "Junction categories are source classifications; they are not causal findings.",
        ),
        extra={"cities_considered": len(frame)},
    )
    return AnalyticsResult(
        intent="junction_injury_totals",
        dataset_id="RA2019_A49",
        operation="junction_injury_totals",
        summary=summary,
        value={"categories": totals, "cities_considered": len(frame)},
        evidence=evidence,
    )


def overspeeding_ranking(settings: Any, *, limit: int = 10) -> AnalyticsResult:
    """Rank reporting cities/UTs by over-speeding accidents (RA2019_A47)."""
    if limit <= 0:
        raise AnalyticsError("limit must be positive")
    loaded = load_dataset(settings, "RA2019_A47")
    label_column = _label_column(loaded)
    frame = observations_only(loaded)
    accidents_column = _single(frame, "over-speeding", "number of accidents", exclude=("rank",))
    killed_column = _single(frame, "over-speeding", "persons killed", "number", exclude=("rank",))
    injured_column = _single(frame, "over-speeding", "persons injured", "total injured")

    frame = frame.assign(_accidents=numeric_series(frame, accidents_column))
    ranked = frame.sort_values("_accidents", ascending=False, kind="stable").head(limit)

    top = [
        {
            "city": str(row[label_column]),
            "over_speeding_accidents": _int_or_none(row["_accidents"]),
            "persons_killed": _int_or_none(numeric_series(frame, killed_column).loc[row.name]),
            "persons_injured": _int_or_none(numeric_series(frame, injured_column).loc[row.name]),
        }
        for _, row in ranked.iterrows()
    ]

    summary = (
        f"From {loaded.source_file}, the reporting cities/UTs with the highest over-speeding "
        "accident counts in 2019 are: "
        + "; ".join(
            f"{item['city']} ({item['over_speeding_accidents']:,} accidents, "
            f"{item['persons_killed']:,} killed)"
            for item in top
        )
        + "."
    )

    evidence = build_evidence(
        loaded,
        operation="overspeeding_ranking",
        units="over-speeding accidents; persons killed/injured",
        record_count=len(frame),
        columns=(label_column, accidents_column, killed_column, injured_column),
        supporting_records=_records(
            ranked, [label_column, accidents_column, killed_column, injured_column]
        ),
        time_period="2019",
        limitations=(
            "Violation counts are descriptive and are not evidence of causation.",
            "City coverage and enforcement/reporting practice are not uniform.",
        ),
        extra={"limit": limit},
    )
    return AnalyticsResult(
        intent="overspeeding_ranking",
        dataset_id="RA2019_A47",
        operation="overspeeding_ranking",
        summary=summary,
        value={"top_cities": top, "cities_considered": len(frame)},
        evidence=evidence,
    )


def blackspot_ranking(settings: Any, *, limit: int = 10) -> AnalyticsResult:
    """Rank high-accident-prone locations by 2016-2018 accidents (RA2019_A52)."""
    if limit <= 0:
        raise AnalyticsError("limit must be positive")
    loaded = load_dataset(settings, "RA2019_A52")
    dataframe = loaded.dataframe
    location_column = find_column(dataframe, "Name of Location Place")
    state_column = find_column(dataframe, "State")
    district_column = find_column(dataframe, "Name of District (Traffic unit)")
    total_column = find_column(dataframe, "Numbers of Accidents - Total of all three years")
    fatalities_column = find_column(dataframe, "Numbers of Fatalities - Total of all three years")

    frame = dataframe.assign(_total=numeric_series(dataframe, total_column))
    ranked = frame.sort_values("_total", ascending=False, kind="stable").head(limit)

    top = [
        {
            "state": str(row[state_column]),
            "district": str(row[district_column]),
            "location": str(row[location_column]),
            "accidents_2016_2018": _int_or_none(row["_total"]),
            "fatalities_2016_2018": _int_or_none(
                numeric_series(frame, fatalities_column).loc[row.name]
            ),
        }
        for _, row in ranked.iterrows()
    ]

    summary = (
        f"From {loaded.source_file}, the highest-accident blackspot locations over the "
        "three-year window 2016-2018 are: "
        + "; ".join(
            f"{item['location']} ({item['district']}, {item['state']}: "
            f"{item['accidents_2016_2018']:,} accidents, "
            f"{item['fatalities_2016_2018']:,} fatalities)"
            for item in top
        )
        + "."
    )

    evidence = build_evidence(
        loaded,
        operation="blackspot_ranking",
        units="accidents and fatalities, 2016-2018 total",
        record_count=len(frame),
        columns=(
            state_column,
            district_column,
            location_column,
            total_column,
            fatalities_column,
        ),
        supporting_records=_records(
            ranked,
            [state_column, district_column, location_column, total_column, fatalities_column],
        ),
        time_period="2016-2018",
        geographic_scope="India (station/location level, multiple states)",
        limitations=(
            "Records are police-station/location level; this is not a city or state aggregate.",
            "Blackspot membership reflects the source's own selection criteria.",
            "Not joinable as a numeric key to the city/state accident tables.",
        ),
        extra={"limit": limit, "locations_considered": len(frame)},
    )
    return AnalyticsResult(
        intent="blackspot_ranking",
        dataset_id="RA2019_A52",
        operation="blackspot_ranking",
        summary=summary,
        value={"top_locations": top, "locations_considered": len(frame)},
        evidence=evidence,
    )


def ward_water_consumption(settings: Any, *, limit: int = 10) -> AnalyticsResult:
    """Rank Bengaluru wards by recorded water consumption for August 2025 (BWSSB)."""
    if limit <= 0:
        raise AnalyticsError("limit must be positive")
    loaded = load_dataset(settings, "BWSSB_WATER")
    dataframe = loaded.dataframe
    number_column = find_column(dataframe, "Ward number")
    name_column = find_column(dataframe, "Ward Name")
    connections_column = find_column(dataframe, "Number of Connections")
    consumption_column = find_column(dataframe, "Consumption in ML")

    frame = dataframe.assign(_consumption=numeric_series(dataframe, consumption_column))
    ranked = frame.sort_values("_consumption", ascending=False, kind="stable").head(limit)

    top = [
        {
            "ward_number": str(row[number_column]).strip(),
            "ward_name": str(row[name_column]),
            "connections": _int_or_none(numeric_series(frame, connections_column).loc[row.name]),
            "consumption_ml": row["_consumption"],
        }
        for _, row in ranked.iterrows()
    ]

    total_ml = float(numeric_series(frame, consumption_column).sum())
    summary = (
        f"From {loaded.source_file}, the wards with the highest recorded water consumption "
        "in August 2025 are: "
        + "; ".join(
            f"{item['ward_name']} (ward {item['ward_number']}: {item['consumption_ml']:.2f} ML)"
            for item in top
        )
        + f". Across the {len(frame)} wards the recorded total is {total_ml:,.2f} ML."
    )

    evidence = build_evidence(
        loaded,
        operation="ward_water_consumption",
        units="megalitres (ML) recorded consumption",
        record_count=len(frame),
        columns=(number_column, name_column, connections_column, consumption_column),
        supporting_records=_records(
            ranked, [number_column, name_column, connections_column, consumption_column]
        ),
        time_period="August 2025 (single-month snapshot)",
        geographic_scope="Bengaluru wards",
        limitations=(
            "A single August 2025 month; this is not current or annual consumption.",
            "Recorded consumption is not demand and implies nothing about unmet supply.",
            "Ward number and ward name are not 1:1 in this snapshot; identifiers are shown "
            "verbatim.",
        ),
        extra={"limit": limit, "wards_considered": len(frame), "total_consumption_ml": total_ml},
    )
    return AnalyticsResult(
        intent="ward_water_consumption",
        dataset_id="BWSSB_WATER",
        operation="ward_water_consumption",
        summary=summary,
        value={
            "top_wards": top,
            "wards_considered": len(frame),
            "total_consumption_ml": total_ml,
        },
        evidence=evidence,
    )


def water_connection_summary(settings: Any) -> AnalyticsResult:
    """Summarise recorded water connections per ward (BWSSB, August 2025)."""
    loaded = load_dataset(settings, "BWSSB_WATER")
    dataframe = loaded.dataframe
    number_column = find_column(dataframe, "Ward number")
    name_column = find_column(dataframe, "Ward Name")
    connections_column = find_column(dataframe, "Number of Connections")
    consumption_column = find_column(dataframe, "Consumption in ML")

    frame = dataframe.assign(_connections=numeric_series(dataframe, connections_column))
    total = float(frame["_connections"].sum())
    mean = float(frame["_connections"].mean())
    ranked = frame.sort_values("_connections", ascending=False, kind="stable").head(5)
    top = [
        {
            "ward_number": str(row[number_column]).strip(),
            "ward_name": str(row[name_column]),
            "connections": _int_or_none(row["_connections"]),
        }
        for _, row in ranked.iterrows()
    ]

    summary = (
        f"From {loaded.source_file}, the {len(frame)} wards in the August 2025 snapshot record "
        f"{total:,.0f} water connections in total (mean {mean:,.1f} per ward). The largest are: "
        + "; ".join(f"{item['ward_name']} ({item['connections']:,})" for item in top)
        + "."
    )

    evidence = build_evidence(
        loaded,
        operation="water_connection_summary",
        units="water connections",
        record_count=len(frame),
        columns=(number_column, name_column, connections_column, consumption_column),
        supporting_records=_records(ranked, [number_column, name_column, connections_column]),
        time_period="August 2025 (single-month snapshot)",
        geographic_scope="Bengaluru wards",
        limitations=(
            "A single August 2025 month; not an annual or current connection count.",
            "Ward number and ward name are not 1:1; identifiers are shown verbatim.",
        ),
        extra={
            "wards_considered": len(frame),
            "total_connections": total,
            "mean_connections": mean,
        },
    )
    return AnalyticsResult(
        intent="water_connection_summary",
        dataset_id="BWSSB_WATER",
        operation="water_connection_summary",
        summary=summary,
        value={
            "total_connections": total,
            "mean_connections": mean,
            "top_wards": top,
            "wards_considered": len(frame),
        },
        evidence=evidence,
    )


def dataset_quality_report(settings: Any, *, dataset_id: str) -> AnalyticsResult:
    """Return a structural/quality summary for one dataset."""
    loaded = load_dataset(settings, dataset_id)
    dataframe = loaded.dataframe
    missing = {str(column): int(dataframe[column].isna().sum()) for column in dataframe.columns}
    duplicate_rows = int(dataframe.duplicated().sum())
    rows = len(dataframe)
    columns = len(dataframe.columns)
    record_count = rows

    summary = (
        f"{loaded.source_file} loads with {rows} row(s) and {columns} column(s) using "
        f"{loaded.encoding}; {duplicate_rows} duplicate row(s) and "
        f"{sum(missing.values())} missing value(s) across all columns."
    )

    evidence = build_evidence(
        loaded,
        operation="dataset_quality_report",
        units="rows/columns/missing counts",
        record_count=record_count,
        columns=tuple(str(column) for column in dataframe.columns),
        supporting_records=(),
        limitations=(
            "Structural checks only; they are not domain-level analytical validation.",
            "Missing counts treat 'NA' and empty fields as missing, not zero.",
        ),
        extra={
            "rows": rows,
            "columns": columns,
            "duplicate_rows": duplicate_rows,
            "missing_by_column": missing,
            "encoding": loaded.encoding,
        },
    )
    return AnalyticsResult(
        intent="dataset_quality_report",
        dataset_id=loaded.dataset_id,
        operation="dataset_quality_report",
        summary=summary,
        value={
            "rows": rows,
            "columns": columns,
            "duplicate_rows": duplicate_rows,
            "missing_by_column": missing,
            "encoding": loaded.encoding,
        },
        evidence=evidence,
    )


def _label_set(loaded: LoadedDataset) -> set[str]:
    column = _label_column(loaded)
    return {
        normalize_column_name(str(value))
        for value in loaded.dataframe[column].tolist()
        if normalize_column_name(str(value)) != "total"
    }


def join_assessment(settings: Any) -> AnalyticsResult:
    """Assess whether the supplied traffic datasets can be joined reliably."""
    a2 = load_dataset(settings, "RA2019_A2")
    a47 = load_dataset(settings, "RA2019_A47")
    a49 = load_dataset(settings, "RA2019_A49")
    a52 = load_dataset(settings, "RA2019_A52")

    a2_labels = _label_set(a2)
    a47_labels = _label_set(a47)
    a49_labels = _label_set(a49)

    a47_a49 = a47_labels & a49_labels
    a2_a47 = a2_labels & a47_labels
    a2_a49 = a2_labels & a49_labels

    pairs = [
        {
            "left": "RA2019_A2",
            "right": "RA2019_A47",
            "shared_labels": len(a2_a47),
            "left_labels": len(a2_labels),
            "right_labels": len(a47_labels),
            "grain_match": False,
            "reliable": False,
            "reason": "A2 is state/UT-level; A47 is city-level. Different geographic grain.",
        },
        {
            "left": "RA2019_A2",
            "right": "RA2019_A49",
            "shared_labels": len(a2_a49),
            "left_labels": len(a2_labels),
            "right_labels": len(a49_labels),
            "grain_match": False,
            "reliable": False,
            "reason": "A2 is state/UT-level; A49 is city-level. Different geographic grain.",
        },
        {
            "left": "RA2019_A47",
            "right": "RA2019_A49",
            "shared_labels": len(a47_a49),
            "left_labels": len(a47_labels),
            "right_labels": len(a49_labels),
            "grain_match": True,
            "reliable": True,
            "reason": (
                "Same 2019 city-level grain and near-identical city coverage; a join on the "
                "city label is defensible provided spelling is verified."
            ),
        },
        {
            "left": "RA2019_A52",
            "right": "RA2019_A2/A47/A49",
            "shared_labels": 0,
            "left_labels": len(a52.dataframe),
            "right_labels": len(a2_labels | a47_labels | a49_labels),
            "grain_match": False,
            "reliable": False,
            "reason": (
                "A52 is station/location-level blackspot data for 2016-2018; no shared numeric "
                "key and incompatible grain."
            ),
        },
    ]

    summary = (
        "None of the traffic datasets should be joined to the water dataset: their geographies "
        "(states/cities vs Bengaluru wards) do not share a defensible key. Among the traffic "
        f"files, RA2019_A47 and RA2019_A49 share {len(a47_a49)} of {len(a49_labels)} city labels "
        "at the same 2019 city grain and can be joined on a verified city name; the other pairs "
        "differ in grain or scope and should not be joined."
    )

    evidence = build_evidence(
        a49,
        operation="join_assessment",
        units="shared identifier labels",
        record_count=len(a47_a49),
        columns=tuple(
            {
                _label_column(a2),
                _label_column(a47),
                _label_column(a49),
            }
        ),
        supporting_records=tuple(pairs),
        time_period="2019 (A47/A49); 2016-2019 (A2); 2016-2018 (A52)",
        geographic_scope="India (mixed state, city and station grains)",
        limitations=(
            "Label overlap is not proof of identity: spelling variants and administrative "
            "renames are not resolved here.",
            "No ward crosswalk exists; the water dataset is never joined.",
            "Shared labels must be verified before any operational join is trusted.",
        ),
        extra={
            "shared_city_labels_a47_a49": sorted(a47_a49),
            "a47_cities": len(a47_labels),
            "a49_cities": len(a49_labels),
        },
    )
    return AnalyticsResult(
        intent="join_assessment",
        dataset_id="RA2019_A49",
        operation="join_assessment",
        summary=summary,
        value={
            "pairs": pairs,
            "shared_city_labels_a47_a49": sorted(a47_a49),
            "water_joinable": False,
        },
        evidence=evidence,
    )


def fuzzy_label_overlap(
    left: set[str], right: set[str], *, threshold: float = 0.9
) -> list[tuple[str, str, float]]:
    """Return near-matching label pairs above ``threshold`` (diagnostic helper)."""
    matches: list[tuple[str, str, float]] = []
    for a in sorted(left):
        for b in sorted(right):
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= threshold and a != b:
                matches.append((a, b, ratio))
    return matches


__all__ = [
    "AnalyticsError",
    "AnalyticsResult",
    "UnsupportedOperationError",
    "blackspot_ranking",
    "dataset_quality_report",
    "fuzzy_label_overlap",
    "join_assessment",
    "junction_injury_totals",
    "overspeeding_ranking",
    "state_accident_ranking",
    "state_share",
    "ward_water_consumption",
    "water_connection_summary",
]
