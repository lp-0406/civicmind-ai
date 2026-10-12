"""FastAPI interface for the CivicMind AI pipeline.

Exposes the health, question/answer and dataset-information endpoints over the
same :class:`~civicmind.ai.engine.DecisionEngine` the CLI uses, so there is one
implementation of the pipeline and two interfaces to it.

The app is built by a factory (:func:`create_app`) rather than at import time,
so importing this module never reads configuration, touches the filesystem or
loads a model. Run it with uvicorn's factory mode::

    uvicorn --factory civicmind.ai.api:create_app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from civicmind.ai.config import AISettings
from civicmind.ai.datasets import (
    available_datasets,
    dataset_path,
    list_dataset_specs,
    load_dataset,
)
from civicmind.ai.engine import DecisionEngine
from civicmind.config import Settings


class AskRequest(BaseModel):
    """Request body for ``POST /ask``."""

    question: str = Field(..., min_length=1, max_length=2000, description="Municipal question")


class AskResponse(BaseModel):
    """Response body for ``POST /ask``."""

    question: str
    supported: bool
    intent: str | None
    dataset_id: str | None
    result: Any
    explanation: str
    sources: list[str]
    limitations: list[str]
    warnings: list[str]
    execution_mode: str
    provider: str
    model: str | None
    fallback_reason: str | None


class DatasetInfo(BaseModel):
    """A dataset descriptor as returned by ``GET /datasets``."""

    dataset_id: str
    filename: str
    title: str
    canonical_id: str | None
    mapping_status: str
    license_status: str
    geographic_scope: str
    geographic_granularity: str
    time_period: str
    available: bool


class HealthResponse(BaseModel):
    """Response body for ``GET /health``."""

    status: str
    environment: str
    datasets_available: int
    datasets_expected: int
    provider: str
    provider_mode: str
    ready: bool


def create_app(
    settings: Settings | None = None,
    *,
    ai_settings: AISettings | None = None,
    engine: DecisionEngine | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Parameters
    ----------
    settings:
        Core settings; resolved from the environment when omitted.
    ai_settings:
        AI settings; resolved from the environment when omitted.
    engine:
        A pre-built engine (used by tests); one is constructed otherwise.
    """
    resolved_settings = settings or Settings.from_env()
    resolved_ai = ai_settings or AISettings.from_env()
    decision_engine = engine or DecisionEngine(resolved_settings, ai_settings=resolved_ai)

    app = FastAPI(
        title="CivicMind AI",
        version="0.1.0",
        description=(
            "Evidence-grounded municipal decision intelligence. Numerical answers are computed "
            "deterministically from the supplied CSVs; the language model only phrases results."
        ),
    )
    app.state.settings = resolved_settings
    app.state.ai_settings = resolved_ai
    app.state.engine = decision_engine

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Report liveness, configured provider and dataset availability."""
        specs = list_dataset_specs()
        available = available_datasets(resolved_settings)
        return HealthResponse(
            status="ok",
            environment=resolved_settings.environment,
            datasets_available=len(available),
            datasets_expected=len(specs),
            provider=decision_engine.provider.name,
            provider_mode=decision_engine.provider.mode,
            ready=len(available) > 0,
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(payload: AskRequest) -> AskResponse:
        """Answer a municipal question."""
        answer = decision_engine.ask(payload.question)
        payload_dict = answer.to_dict()
        return AskResponse(**{key: payload_dict[key] for key in AskResponse.model_fields})

    @app.get("/datasets", response_model=list[DatasetInfo])
    def datasets() -> list[DatasetInfo]:
        """List the declared datasets and whether each is present on disk."""
        available = {spec.dataset_id for spec in available_datasets(resolved_settings)}
        return [
            DatasetInfo(
                dataset_id=spec.dataset_id,
                filename=spec.filename,
                title=spec.title,
                canonical_id=spec.canonical_id,
                mapping_status=spec.mapping_status,
                license_status=spec.license_status,
                geographic_scope=spec.geographic_scope,
                geographic_granularity=spec.geographic_granularity,
                time_period=spec.time_period,
                available=spec.dataset_id in available,
            )
            for spec in list_dataset_specs()
        ]

    @app.get("/datasets/{dataset_id}")
    def dataset_detail(dataset_id: str) -> dict[str, Any]:
        """Return a descriptor plus a structural quality summary for one dataset."""
        try:
            loaded = load_dataset(resolved_settings, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        dataframe = loaded.dataframe
        return {
            "spec": asdict(loaded.spec),
            "path": str(dataset_path(resolved_settings, loaded.dataset_id)),
            "encoding": loaded.encoding,
            "byte_size": loaded.byte_size,
            "rows": int(len(dataframe)),
            "columns": [str(column) for column in dataframe.columns],
            "duplicate_rows": int(dataframe.duplicated().sum()),
            "missing_by_column": {
                str(column): int(dataframe[column].isna().sum()) for column in dataframe.columns
            },
            "known_issues": list(loaded.spec.known_issues),
        }

    return app


__all__ = [
    "AskRequest",
    "AskResponse",
    "DatasetInfo",
    "HealthResponse",
    "create_app",
]
