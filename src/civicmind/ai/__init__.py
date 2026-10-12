"""Evidence-grounded AI decision-support pipeline.

This package implements the first end-to-end CivicMind AI vertical slice:

    municipal question
        -> intent + dataset selection      (:mod:`civicmind.ai.intent`)
        -> deterministic analytics         (:mod:`civicmind.ai.analytics`)
        -> evidence + citations            (:mod:`civicmind.ai.evidence`)
        -> grounded answer generation      (:mod:`civicmind.ai.providers`)
        -> orchestration                   (:mod:`civicmind.ai.engine`)

Design rules:

* Numerical answers come from deterministic computations against the real
  ``data/raw`` CSVs, never from a language model.
* The language model only *phrases* results it is handed; it must not invent
  statistics, citations, or provenance.
* No model, GPU, network connection, or API key is required to answer: a
  deterministic template provider is always available as the fallback.
* Heavyweight ML dependencies (torch/transformers) are imported lazily, never
  at package import time.
"""

from __future__ import annotations

from civicmind.ai.analytics import (
    AnalyticsError,
    AnalyticsResult,
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
from civicmind.ai.config import AISettings, AISettingsError
from civicmind.ai.datasets import (
    DATASET_SPECS,
    LoadedDataset,
    LocalDatasetSpec,
    UnavailableDatasetError,
    available_datasets,
    dataset_path,
    list_dataset_specs,
    load_dataset,
    load_raw_text,
)
from civicmind.ai.engine import Answer, DecisionEngine, register_domain, unregister_domain
from civicmind.ai.evaluation import (
    DEFAULT_BENCHMARK,
    BenchmarkCase,
    EvaluationHarness,
    EvaluationReport,
)
from civicmind.ai.evidence import Evidence
from civicmind.ai.intent import IntentMatch, QuestionRouter, RoutingError

__all__ = [
    "DATASET_SPECS",
    "DEFAULT_BENCHMARK",
    "AISettings",
    "AISettingsError",
    "AnalyticsError",
    "AnalyticsResult",
    "Answer",
    "BenchmarkCase",
    "DecisionEngine",
    "EvaluationHarness",
    "EvaluationReport",
    "Evidence",
    "IntentMatch",
    "LoadedDataset",
    "LocalDatasetSpec",
    "QuestionRouter",
    "RoutingError",
    "register_domain",
    "unregister_domain",
    "UnavailableDatasetError",
    "UnsupportedOperationError",
    "available_datasets",
    "blackspot_ranking",
    "dataset_path",
    "dataset_quality_report",
    "join_assessment",
    "junction_injury_totals",
    "list_dataset_specs",
    "load_dataset",
    "load_raw_text",
    "overspeeding_ranking",
    "state_accident_ranking",
    "state_share",
    "ward_water_consumption",
    "water_connection_summary",
]
