"""Reproducible evaluation harness for the CivicMind AI pipeline.

This module defines a fixed benchmark of municipal questions and measures the
pipeline against it. Expected values are the independently verified figures from
the analytics tests (recomputed with the standard-library ``csv`` module against
the same raw files), not the pipeline's own output.

Metric definitions (each is a fraction in ``[0, 1]`` unless noted):

``numerical_accuracy``
    Over cases that declare ``expected_values`` and expect a supported answer:
    the fraction where every declared value matches the answer's structured
    result. Floats compare with ``rel_tol=1e-6``; everything else by equality.
``attribution_accuracy``
    Over expected-supported cases that declare ``expected_source_file``: the
    fraction where that source file appears in the answer's evidence citations.
    (A case fails if evidence is empty, so an unattributed answer cannot pass.)
``unsupported_rejection_rate``
    Over cases that expect an unsupported answer: the fraction the pipeline
    correctly refused instead of fabricating a result.
``intent_accuracy``
    Over all cases: the fraction whose routed intent equals the expected intent
    (``None`` for questions that must be refused).
``mean_latency_seconds`` / ``p95_latency_seconds`` / ``max_latency_seconds``
    Wall-clock latency of one ``DecisionEngine.ask`` call per case, measured
    with ``time.perf_counter``. These are descriptive, not a performance claim.

No network, model, GPU or API key is required: the harness runs the
deterministic provider.
"""

from __future__ import annotations

import json
import math
import statistics
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from civicmind.ai.config import AISettings
from civicmind.ai.engine import DecisionEngine
from civicmind.config import Settings


@dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark question and its independently verified expectation."""

    case_id: str
    category: str
    question: str
    expected_supported: bool
    expected_intent: str | None
    expected_dataset: str | None = None
    expected_source_file: str | None = None
    expected_values: dict[str, Any] = field(default_factory=dict)
    expects_missing_data: bool = False
    notes: str = ""


#: The fixed benchmark. Values were verified independently with the standard
#: library before being recorded here (see ``tests/test_ai_analytics.py``).
DEFAULT_BENCHMARK: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="roads-state-ranking",
        category="ranking",
        question="Which states had the highest reported road accidents in 2019?",
        expected_supported=True,
        expected_intent="state_accident_ranking",
        expected_dataset="RA2019_A2",
        expected_source_file="data/raw/RA2019_A2.csv",
        expected_values={
            "top_states.0.state": "Tamil Nadu",
            "top_states.0.accidents": 57228,
            "top_states.1.state": "Madhya Pradesh",
            "reported_total": 449002,
            "states_considered": 36,
        },
        notes="Aggregate 'Total ' row must be excluded and reported separately.",
    ),
    BenchmarkCase(
        case_id="roads-published-share",
        category="share",
        question="What published share did Telangana have in 2019?",
        expected_supported=True,
        expected_intent="state_share",
        expected_dataset="RA2019_A2",
        expected_source_file="data/raw/RA2019_A2.csv",
        expected_values={
            "state": "Telangana",
            "accidents": 21570,
            "rank": 9,
            "share_percent": 4.80398751,
        },
        notes="Published share is already on a 0-100 scale and must not be re-derived.",
    ),
    BenchmarkCase(
        case_id="roads-junction-injuries",
        category="junction",
        question="Which reported junction categories have the highest injured totals?",
        expected_supported=True,
        expected_intent="junction_injury_totals",
        expected_dataset="RA2019_A49",
        expected_source_file="data/raw/RA2019_A49.csv",
        expected_values={
            "categories.0.category": "Others",
            "categories.0.total_injured": 41993,
            "categories.1.category": "T-Junction",
            "cities_considered": 50,
        },
    ),
    BenchmarkCase(
        case_id="roads-over-speeding",
        category="violation",
        question="Which cities have the most over-speeding violations?",
        expected_supported=True,
        expected_intent="overspeeding_ranking",
        expected_dataset="RA2019_A47",
        expected_source_file="data/raw/RA2019_A47.csv",
        expected_values={
            "top_cities.0.city": "Bengaluru",
            "top_cities.0.over_speeding_accidents": 4143,
            "cities_considered": 50,
        },
    ),
    BenchmarkCase(
        case_id="water-consumption",
        category="water",
        question=(
            "What are the highest recorded ward-level water consumption values for August 2025?"
        ),
        expected_supported=True,
        expected_intent="ward_water_consumption",
        expected_dataset="BWSSB_WATER",
        expected_source_file="data/raw/BWSSB_Water_Consumption_August_2025.csv",
        expected_values={
            "top_wards.0.ward_name": "HSR Layout",
            "top_wards.0.ward_number": "174",
            "top_wards.0.consumption_ml": 605.66,
            "wards_considered": 202,
            "total_consumption_ml": 30580.05,
        },
    ),
    BenchmarkCase(
        case_id="water-connections",
        category="connections",
        question="How many water connections are there per ward?",
        expected_supported=True,
        expected_intent="water_connection_summary",
        expected_dataset="BWSSB_WATER",
        expected_source_file="data/raw/BWSSB_Water_Consumption_August_2025.csv",
        expected_values={"wards_considered": 202, "total_connections": 1047734},
    ),
    BenchmarkCase(
        case_id="unsupported-off-topic",
        category="unsupported",
        question="What is the best cricket team in the world?",
        expected_supported=False,
        expected_intent=None,
    ),
    BenchmarkCase(
        case_id="unsupported-missing-data",
        category="unavailable",
        question="Which states had the highest reported road accidents in 2019?",
        expected_supported=False,
        expected_intent="state_accident_ranking",
        expects_missing_data=True,
        notes="Runs with an empty data/raw tree: the pipeline must refuse, not fabricate.",
    ),
    BenchmarkCase(
        case_id="granularity-ward-roads",
        category="granularity",
        question="Which ward had the highest number of road accidents in 2019?",
        expected_supported=False,
        expected_intent=None,
        notes="Roads data has no ward grain; the question must be refused, not mis-routed.",
    ),
    BenchmarkCase(
        case_id="granularity-join",
        category="granularity",
        question="Can these datasets be joined reliably, and what evidence supports the answer?",
        expected_supported=True,
        expected_intent="join_assessment",
        expected_dataset="RA2019_A49",
        expected_source_file="data/raw/RA2019_A49.csv",
        expected_values={
            "water_joinable": False,
            "pairs.2.left": "RA2019_A47",
            "pairs.2.reliable": True,
            "pairs.2.shared_labels": 50,
        },
    ),
    BenchmarkCase(
        case_id="temporal-out-of-range",
        category="temporal",
        question="What will the road accidents be in 2030?",
        expected_supported=False,
        expected_intent=None,
        notes="Roads data covers 2016-2019; no projection is produced.",
    ),
)


@dataclass(frozen=True)
class CaseOutcome:
    """The measured outcome of running one benchmark case."""

    case_id: str
    category: str
    question: str
    expected_supported: bool
    actual_supported: bool
    expected_intent: str | None
    actual_intent: str | None
    expected_source_file: str | None
    evidence_sources: tuple[str, ...]
    elapsed_seconds: float
    intent_ok: bool
    unsupported_ok: bool | None
    numerical_ok: bool | None
    attribution_ok: bool | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "case_id": self.case_id,
            "category": self.category,
            "question": self.question,
            "expected_supported": self.expected_supported,
            "actual_supported": self.actual_supported,
            "expected_intent": self.expected_intent,
            "actual_intent": self.actual_intent,
            "expected_source_file": self.expected_source_file,
            "evidence_sources": list(self.evidence_sources),
            "elapsed_seconds": self.elapsed_seconds,
            "intent_ok": self.intent_ok,
            "unsupported_ok": self.unsupported_ok,
            "numerical_ok": self.numerical_ok,
            "attribution_ok": self.attribution_ok,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregate metrics plus per-case outcomes."""

    outcomes: tuple[CaseOutcome, ...]
    metrics: dict[str, float]
    benchmark_size: int
    execution_mode: str
    provider: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the whole report."""
        return {
            "benchmark_size": self.benchmark_size,
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "metrics": dict(self.metrics),
            "cases": [outcome.to_dict() for outcome in self.outcomes],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Render the report as JSON text."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary_lines(self) -> list[str]:
        """Render the metrics as human-readable lines."""
        order = (
            "numerical_accuracy",
            "attribution_accuracy",
            "unsupported_rejection_rate",
            "intent_accuracy",
            "mean_latency_seconds",
            "p95_latency_seconds",
            "max_latency_seconds",
        )
        lines = [f"benchmark cases: {self.benchmark_size}", f"provider: {self.provider}"]
        for key in order:
            value = self.metrics.get(key)
            if value is None:
                continue
            if key.endswith("_seconds"):
                lines.append(f"{key:<28} {value:.4f}")
            else:
                lines.append(f"{key:<28} {value:.3f}")
        return lines


def _resolve(value: Any, path: str) -> Any:
    """Resolve a dotted path (with integer list indices) against a result."""
    current = value
    for part in path.split("."):
        current = current[int(part)] if isinstance(current, (list, tuple)) else current[part]
    return current


def _values_match(actual: Any, expected: Any) -> bool:
    """Compare a computed value with an expected one (numeric tolerance for floats)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-9)
    return actual == expected


def _compare_values(result: Any, expected_values: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return ``(all_matched, mismatches)`` for a case's declared values."""
    mismatches: list[str] = []
    for path, expected in expected_values.items():
        try:
            actual = _resolve(result, path)
        except (KeyError, IndexError, TypeError):
            mismatches.append(f"{path}: missing (expected {expected!r})")
            continue
        if not _values_match(actual, expected):
            mismatches.append(f"{path}: got {actual!r}, expected {expected!r}")
    return (not mismatches), mismatches


def _percentile(values: list[float], fraction: float) -> float:
    """Return a simple nearest-rank percentile of ``values``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


class EvaluationHarness:
    """Runs the fixed benchmark against the real CSVs and computes metrics."""

    def __init__(
        self,
        settings: Settings,
        *,
        ai_settings: AISettings | None = None,
        cases: tuple[BenchmarkCase, ...] | None = None,
    ) -> None:
        self.settings = settings
        self.ai_settings = ai_settings or AISettings(provider="deterministic")
        self.cases = cases if cases is not None else DEFAULT_BENCHMARK

    def _engine_for(self, case: BenchmarkCase) -> DecisionEngine:
        if case.expects_missing_data:
            # A real settings object pointed at an empty raw tree, so the
            # missing-data path is genuinely exercised rather than mocked.
            empty_root = Path(tempfile.mkdtemp(prefix="civicmind-eval-empty-"))
            (empty_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
            isolated = replace(
                self.settings,
                project_root=empty_root,
                data_dir=empty_root / "data",
            )
            return DecisionEngine(isolated, ai_settings=self.ai_settings)
        return DecisionEngine(self.settings, ai_settings=self.ai_settings)

    def run_case(self, case: BenchmarkCase) -> CaseOutcome:
        """Run one case and measure it."""
        engine = self._engine_for(case)
        started = time.perf_counter()
        answer = engine.ask(case.question)
        elapsed = time.perf_counter() - started

        intent_ok = answer.intent == case.expected_intent
        unsupported_ok: bool | None = None
        numerical_ok: bool | None = None
        attribution_ok: bool | None = None
        detail = ""

        if not case.expected_supported:
            unsupported_ok = answer.supported is False
            if not unsupported_ok:
                detail = "expected a refusal but the pipeline answered"
            elif case.expects_missing_data:
                kind = answer.extra.get("blocked_kind")
                if kind != "missing-dataset":
                    unsupported_ok = False
                    detail = f"refused for the wrong reason: blocked_kind={kind!r}"
        else:
            if case.expected_values:
                numerical_ok, mismatches = _compare_values(answer.result, case.expected_values)
                if mismatches:
                    detail = "; ".join(mismatches)
            if case.expected_source_file:
                sources = tuple(item.source_file for item in answer.evidence)
                attribution_ok = case.expected_source_file in sources
                if not attribution_ok:
                    detail = (detail + "; " if detail else "") + (
                        f"evidence did not cite {case.expected_source_file}"
                    )

        return CaseOutcome(
            case_id=case.case_id,
            category=case.category,
            question=case.question,
            expected_supported=case.expected_supported,
            actual_supported=answer.supported,
            expected_intent=case.expected_intent,
            actual_intent=answer.intent,
            expected_source_file=case.expected_source_file,
            evidence_sources=tuple(item.source_file for item in answer.evidence),
            elapsed_seconds=elapsed,
            intent_ok=intent_ok,
            unsupported_ok=unsupported_ok,
            numerical_ok=numerical_ok,
            attribution_ok=attribution_ok,
            detail=detail,
        )

    def run(self) -> EvaluationReport:
        """Run every case and compute the metrics."""
        outcomes = tuple(self.run_case(case) for case in self.cases)
        metrics = self._metrics(outcomes)
        first = self._engine_for(self.cases[0]) if self.cases else None
        return EvaluationReport(
            outcomes=outcomes,
            metrics=metrics,
            benchmark_size=len(outcomes),
            execution_mode="deterministic",
            provider=first.provider.name if first else "deterministic",
        )

    @staticmethod
    def _metrics(outcomes: tuple[CaseOutcome, ...]) -> dict[str, float]:
        def _rate(values: list[bool]) -> float:
            return (sum(values) / len(values)) if values else 0.0

        supported_cases = [o for o in outcomes if o.expected_supported]
        unsupported_cases = [o for o in outcomes if not o.expected_supported]
        latencies = [o.elapsed_seconds for o in outcomes]

        return {
            "numerical_accuracy": _rate(
                [o.numerical_ok for o in supported_cases if o.numerical_ok is not None]
            ),
            "attribution_accuracy": _rate(
                [o.attribution_ok for o in supported_cases if o.attribution_ok is not None]
            ),
            "unsupported_rejection_rate": _rate(
                [bool(o.unsupported_ok) for o in unsupported_cases if o.unsupported_ok is not None]
            ),
            "intent_accuracy": _rate([o.intent_ok for o in outcomes]),
            "supported_case_count": float(len(supported_cases)),
            "unsupported_case_count": float(len(unsupported_cases)),
            "mean_latency_seconds": statistics.fmean(latencies) if latencies else 0.0,
            "p95_latency_seconds": _percentile(latencies, 0.95),
            "max_latency_seconds": max(latencies) if latencies else 0.0,
        }

    def benchmark_payload(self) -> list[dict[str, Any]]:
        """Return the benchmark definition as a JSON-serialisable list."""
        return [
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
                "expected_supported": case.expected_supported,
                "expected_intent": case.expected_intent,
                "expected_dataset": case.expected_dataset,
                "expected_source_file": case.expected_source_file,
                "expected_values": case.expected_values,
                "expects_missing_data": case.expects_missing_data,
                "notes": case.notes,
            }
            for case in self.cases
        ]


__all__ = [
    "DEFAULT_BENCHMARK",
    "BenchmarkCase",
    "CaseOutcome",
    "EvaluationHarness",
    "EvaluationReport",
]
