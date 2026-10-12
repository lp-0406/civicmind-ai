# First AI Pipeline — Implementation Notes

**Repository:** CivicMind AI · **Branch:** `main`
**Scope:** the first end-to-end, evidence-grounded decision-support vertical slice.
**Status:** implemented and tested on CPU-only hardware with the deterministic
fallback. Local-model and GPU execution paths are implemented but have **not**
been run on CUDA hardware in this environment.

---

## 1. What this delivers

A municipal question flows through one pipeline:

```
question
  → intent + dataset selection          (civicmind.ai.intent)
  → deterministic analytics over CSVs   (civicmind.ai.analytics)
  → evidence + citations                (civicmind.ai.evidence)
  → grounded answer generation          (civicmind.ai.providers)
  → orchestration + response            (civicmind.ai.engine)
  → CLI / FastAPI                       (civicmind.cli, civicmind.ai.api)
```

The pipeline answers questions from the five supplied CSVs, always cites the
source file, relevant columns, method, units, time period and limitations, and
never fabricates a statistic. Numerical answers come **only** from deterministic
pandas computations; the language model is a phraser, not a calculator.

## 2. Module responsibilities

| Module | Responsibility |
| --- | --- |
| `civicmind/ai/config.py` | `AISettings` — env-driven provider/model/device selection; never stores the API key; secret-free `summary()`. |
| `civicmind/ai/evaluation.py` | Fixed benchmark + reproducible metrics (numerical accuracy, attribution accuracy, unsupported rejection, latency). |
| `civicmind/ai/gpu_check.py` | Environment/readiness/GPU detection and the smoke-test runner behind `scripts/gpu_smoke_test.py`. |
| `civicmind/ai/datasets.py` | The five `LocalDatasetSpec` declarations, encoding-fallback loading (cp1252 for `RA2019_A52`), original column-name preservation, `NA` → missing, `Total`-row handling, evidence assembly. |
| `civicmind/ai/evidence.py` | `Evidence` — the fact boundary between analytics and the model: source file, columns, records, units, period, scope, quality issues, limitations, mapping/licence status. |
| `civicmind/ai/analytics.py` | Deterministic operations: state accident ranking, published share lookup, junction-injury totals, over-speeding ranking, blackspot ranking, ward water consumption/connections, quality report, join assessment. |
| `civicmind/ai/intent.py` | Explicit, testable rule-based routing (no model-driven numeric selection). |
| `civicmind/ai/providers.py` | `AnswerProvider` contract + deterministic, local (transformers) and OpenAI-compatible API backends; device resolution with CUDA fallback. |
| `civicmind/ai/engine.py` | `DecisionEngine.ask()` — ties the stages together and returns a structured `Answer`. |
| `civicmind/ai/api.py` | FastAPI factory: `/health`, `/ask`, `/datasets`, `/datasets/{id}`. |
| `civicmind/cli.py` | `civicmind ask`, `civicmind ai datasets`, `civicmind ai serve` (imported lazily). |

## 3. Data flow and safeguards

* **Loading** is read-only; the raw CSVs are never modified. Encoding is resolved
  by trying each dataset's declared candidates in order, so `RA2019_A52.csv`
  (not valid UTF-8) loads via cp1252 with no call-site special case.
* **Column names are preserved verbatim** (including the water file's
  `Ward number ` trailing space). Matching goes through `find_column`, which
  normalises for matching only.
* **`NA` is missing, never zero.** `numeric_series` coerces with
  `errors="coerce"`, so unparsable/`NA` values become `NaN`.
* **Aggregate `Total` rows are excluded** from per-entity rankings and reported
  separately (the national total is still available as context).
* **Published shares keep their 0–100 scale**; they are not re-derived.
* **Operations refuse rather than guess.** An unsupported year or an
  unresolvable column raises `UnsupportedOperationError`; it is never
  approximated.
* **No cross-grain joins.** The only join assessed as defensible is
  `RA2019_A47` ⋈ `RA2019_A49` (same 2019 city grain, 50/50 shared labels, and
  only on a verified city name). The water dataset is never joined.

## 4. Running in deterministic mode (no GPU, no model, no network)

```bash
civicmind ask "Which states had the highest reported road accidents in 2019?"
civicmind ask --json "What published share did Telangana have in 2019?"
civicmind ai datasets
```

`civicmind ask` exits `0` for a supported answer and `2` for an unsupported
question (so scripts can branch) while still printing a clear explanation.

Force deterministic explicitly with `CIVICMIND_AI_PROVIDER=deterministic`; it is
also the automatic fallback whenever no model is configured or available.

## 5. Configuring an API model (optional)

Set an OpenAI-compatible endpoint and a key **in the environment only**:

```bash
export CIVICMIND_AI_PROVIDER=api
export CIVICMIND_AI_API_BASE_URL=https://api.example.com/v1
export CIVICMIND_AI_MODEL_ID=gpt-4o-mini
export CIVICMIND_AI_API_KEY=...        # never committed, never logged
```

No key is required to run the CLI, the tests or the deterministic answer. Keys
are read on demand through `AISettings.api_key` and never appear in
`AISettings.summary()`.

## 6. Configuring a local model

```bash
pip install "civicmind-ai[ai]"          # adds torch + transformers
export CIVICMIND_AI_PROVIDER=local
export CIVICMIND_AI_MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct   # HF id or local dir
export CIVICMIND_AI_DEVICE=auto         # auto | cpu | cuda | cuda:0
```

The model is loaded lazily on the first question — never at import time — so
importing the package touches no model and downloads nothing.

## 7. Running on the CUDA college machine

This machine has no GPU; nothing below was executed here. On the GPU host:

```bash
# 1. Install the CUDA build of PyTorch that matches the driver, then transformers.
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install "civicmind-ai[ai]"

# 2. Confirm the device is visible.
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 3. Point the pipeline at a local (optionally quantized) model and CUDA.
export CIVICMIND_AI_PROVIDER=local
export CIVICMIND_AI_MODEL_ID=/models/Qwen2.5-7B-Instruct
export CIVICMIND_AI_DEVICE=cuda:0

civicmind ask "Which reported junction categories have the highest injured totals?"
```

`resolve_device` selects CUDA when available and falls back to CPU with an
explicit, actionable warning when a CUDA device is requested but unavailable, so
a misconfigured GPU host reports the downgrade instead of silently running on
CPU. Model identifiers are configuration, never hardcoded machine paths.

The package ships a smoke test that reports the environment, checks readiness
and (only when asked) runs one real question through the decision engine. Run it
first on the target machine — it loads no model unless `--load-model` is passed:

```bash
python scripts/gpu_smoke_test.py                 # environment + readiness, no model load
python scripts/gpu_smoke_test.py --load-model    # real inference with the configured model
python scripts/gpu_smoke_test.py --json          # machine-readable result
python scripts/gpu_smoke_test.py --device cuda:0 # override the device for one run
```

Exit codes: `0` ready, `2` environment not ready, `3` model load/inference
failed. See §12 for what each check means.

## 8. Serving the API

```bash
pip install "civicmind-ai[api]"
civicmind ai serve --host 127.0.0.1 --port 8000
# equivalent:
uvicorn --factory civicmind.ai.api:create_app --host 127.0.0.1 --port 8000
```

```bash
curl -s localhost:8000/health
curl -s localhost:8000/datasets
curl -s -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"What are the highest recorded ward-level water consumption values for August 2025?"}'
```

Response shape (`POST /ask`):

```json
{
  "question": "...",
  "supported": true,
  "intent": "ward_water_consumption",
  "dataset_id": "BWSSB_WATER",
  "result": { "top_wards": [ { "ward_number": "174", "ward_name": "HSR Layout",
                               "connections": 14147, "consumption_ml": 605.66 } ],
              "wards_considered": 202, "total_consumption_ml": 30580.05 },
  "explanation": "...",
  "sources": ["data/raw/BWSSB_Water_Consumption_August_2025.csv (canonical id WTR-005; plausible but unverified mapping; ...)"],
  "limitations": ["..."],
  "warnings": [],
  "execution_mode": "deterministic",
  "provider": "deterministic",
  "model": null,
  "fallback_reason": null
}
```

## 9. Worked examples (actual output)

**Q: Which states had the highest reported road accidents in 2019?**

> Based on `data/raw/RA2019_A2.csv`, the states/UTs with the highest reported
> road accidents in 2019 are: Tamil Nadu (57,228); Madhya Pradesh (50,669);
> Uttar Pradesh (42,572); Kerala (41,111); Karnataka (40,658); … These 10
> states/UTs account for 349,251 of the 449,002 reported accidents across the 36
> reporting states/UTs in 2019.

**Q: What published share did Telangana have in 2019?**

> Telangana had a published share of 4.80399% of all reported road accidents in
> 2019, with 21,570 reported accidents (2019 rank 9).

**Q: Which reported junction categories have the highest injured totals?**

> Across the 50 reporting cities in `data/raw/RA2019_A49.csv`, total persons
> injured by junction category: Others (41,993); T-Junction (10,271); Four arm
> Junction (7,330); Staggered Junction (6,076); Y-Junction (4,831); Round about
> Junction (3,619).

**Q: Can these datasets be joined reliably…?**

> None of the traffic datasets should be joined to the water dataset. Among the
> traffic files, `RA2019_A47` and `RA2019_A49` share 50 of 50 city labels at the
> same 2019 city grain and can be joined on a verified city name; the other pairs
> differ in grain or scope and should not be joined.

Every figure was independently recomputed with the standard-library `csv` module
against the same raw files; the two agree exactly (see the analytics tests).

## 10. Test commands and actual results

Run from the repository root (`civicmind-ai/`):

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **566 passed, 2 skipped** |
| `python -m ruff check src tests scripts` | **All checks passed** |
| `python -m ruff format --check src tests scripts` | **69 files already formatted** |
| `python scripts/validate_project.py` | **36 passed, 0 failed** |
| `civicmind ai evaluate --out docs/ai/evaluation_results.json` | **exit 0**; see §11 |
| `python scripts/gpu_smoke_test.py` | **exit 0** (ready, deterministic mode) |

Test modules: `tests/test_ai_datasets.py`, `test_ai_analytics.py`,
`test_ai_intent.py`, `test_ai_providers.py`, `test_ai_engine.py`,
`test_ai_api.py`, `test_ai_cli.py`, `test_ai_evaluation.py`,
`test_ai_gpu_check.py`, `test_ai_extensibility.py`, `test_ai_audit_regressions.py`.
They cover encoding fallback,
`NA` handling, schema compatibility, numerically verified computations, missing
values and invalid inputs, routing, evidence/citation construction,
fabricated-answer prevention, unsupported questions, deterministic fallback,
missing model configuration, grounding enforcement, API validation/error
handling, CPU execution, CUDA-unavailable graceful handling, benchmark metrics
and extension wiring. No test needs the network, a model download, an API key or
a GPU.

The two skips are deliberate and self-describing: the real-model inference
integration test is opt-in (`CIVICMIND_AI_RUN_INTEGRATION=1` + a configured
`CIVICMIND_AI_MODEL_ID`), and the missing-`transformers` path cannot be exercised
because `transformers` is installed on this machine.

## 11. Evaluation harness and measured results

The benchmark and the metrics are code, not prose: `civicmind/ai/evaluation.py`
defines a fixed set of questions, and `civicmind.ai.evaluation` computes each
metric from the actual run. Expected values were independently verified with the
standard-library `csv` module against the same raw files (the same figures as
the analytics tests), so the harness does not merely mirror the pipeline. The
stored artifacts are `docs/ai/evaluation_results.json`
(`{"benchmark": [...], "report": {...}}`) and the benchmark payload is emitted
with no raw dataset rows.

**Metric definitions.** `numerical_accuracy` = over cases with declared expected
values, the fraction where every value matched the structured result
(floats within `rel_tol=1e-6`). `attribution_accuracy` = over expected-supported
cases, the fraction whose evidence cites the expected source file
(non-empty evidence required). `unsupported_rejection_rate` = over cases that
must be refused, the fraction the pipeline refused. `intent_accuracy` = over all
cases, the fraction whose routed intent matched the expectation (including the
`None` expectation of refused questions). Latencies are wall-clock
`time.perf_counter` measurements of one `ask` call per case.

Measured on this machine (CPU, deterministic provider), 11 cases:

| Category | Cases |
| --- | --- |
| ranking, share, junction, violation | 4 supported roads cases |
| water, connections | 2 supported water cases |
| granularity | 1 supported join case + 1 refused ward/roads case |
| unsupported, unavailable, temporal | 3 refused cases |

| Metric | Value |
| --- | --- |
| `numerical_accuracy` | **1.000** |
| `attribution_accuracy` | **1.000** |
| `unsupported_rejection_rate` | **1.000** |
| `intent_accuracy` | **1.000** |
| `mean_latency_seconds` | **0.0111** |
| `p95_latency_seconds` | **0.0329** |
| `max_latency_seconds` | **0.0329** |

Latency is descriptive and varies run to run (a later run on the same machine
measured `mean_latency_seconds` 0.0120 / `p95` 0.0354); the four accuracy and
rejection metrics are stable. The values above are those stored in
`docs/ai/evaluation_results.json`.

The harness ships tests proving the metrics are **not vacuous**: a deliberately
wrong expected value, a wrong expected intent and a mislabelled unsupported case
are each detected (`tests/test_ai_evaluation.py`). The `unavailable` case is
exercised for real by pointing a settings object at an empty `data/raw` tree, so
the missing-data refusal is measured, not mocked.

```bash
civicmind ai evaluate                                   # human-readable metrics
civicmind ai evaluate --json                            # full report as JSON
civicmind ai evaluate --out docs/ai/evaluation_results.json
```

## 12. College GPU smoke test

`scripts/gpu_smoke_test.py` (logic in `civicmind/ai/gpu_check.py`) is the single
command to run first on the target machine. It:

1. reports Python, platform, torch, transformers, CUDA availability, GPU name,
   and total/free VRAM where accessible;
2. verifies the configured model id/path and device, and the API key when an API
   provider is selected;
3. loads the model **only** when `--load-model` is passed;
4. runs one municipal question through the existing `DecisionEngine`;
5. records model, device, `cuda_used`, execution mode, elapsed time, the source
   evidence and any error;
6. fails readiness with an actionable message (for example
   `install the matching CUDA PyTorch build or set CIVICMIND_AI_DEVICE=cpu`)
   instead of silently reporting success.

Verified behaviour on this CPU-only machine:

| Invocation | Outcome |
| --- | --- |
| `python scripts/gpu_smoke_test.py` | `RESULT: ready`, exit `0`, deterministic mode, evidence `data/raw/RA2019_A2.csv` |
| `python scripts/gpu_smoke_test.py --device cuda:0` | cuda check FAILS, `RESULT: environment not ready`, exit `2` |
| `python scripts/gpu_smoke_test.py --provider local` | model_configured check FAILS, exit `2` |

No model weights were downloaded and no CUDA execution occurred; the GPU path
remains unverified until it is run on the college machine.

## 13. Local-model provider and grounding enforcement

`LocalModelProvider` loads a lazily-constructed Hugging Face `text-generation`
pipeline (CPU or `cuda:N`, `torch_dtype="auto"` on GPU) and never at import time.
Load and inference failures are converted to an actionable `ProviderError`:
missing `transformers`/`torch`, an unavailable model, CUDA errors and
out-of-memory (classified by class name or message, so torch need not be
imported to detect it). Each message names the fix, and a device downgrade is
reported rather than hidden.

Because a language model must not be trusted with the numbers, the engine
enforces grounding: after any non-deterministic generation,
`missing_grounding` checks that **every whole numeric token in the computed
summary appears in the generated text** and that each limitation's opening
fragment is disclosed. If anything is missing, the model's answer is discarded
and the deterministic rendering is returned, with `fallback_reason` naming what
was dropped. Matching is by exact numeric token (so `157228` does not satisfy
`57228`, `57228.9` does not satisfy `57228`, and `-57228` does not satisfy
`57228`), and limitation text is compared with punctuation removed.

**This is a string-level guard, not semantic verification.** It establishes that
the figures are present and the caveats are disclosed; it does **not** establish
that a figure is used in the correct context (a valid number attributed to the
wrong entity or column still passes). It is a regression guard against a model
altering or dropping computed values, not a correctness proof.

## 14. Adding a new domain (waste, environment, …)

The decision engine does not need to be rewritten. A new domain is one call:

```python
from civicmind.ai.engine import register_domain

register_domain(
    "waste_quantity",
    dataset_id="WST-001",
    operation=waste_quantity_summary,   # a function like the existing analytics ones
    patterns=("solid waste", "waste generated"),
)
```

This updates routing and dispatch together; built-in intents keep priority, so
existing behaviour cannot be shadowed. `unregister_domain` reverses it.
`tests/test_ai_extensibility.py` proves a registered domain routes, dispatches
and produces real evidence, that built-in intents are unaffected, and that
unregistering removes it. **No waste or environmental dataset is created or
implied** — the demonstration operation reuses a real computation over a real
supplied file, and only the intent label is illustrative.

## 15. Known limitations and unimplemented capabilities

* **Local-model and CUDA inference were not executed here.** torch is a CPU
  build (`2.3.0+cpu`) and no CUDA device is present. The provider, device
  resolution, grounding guard, error handling and smoke test are unit tested,
  but real end-to-end inference on the college GPU is unverified until run
  there.
* **The evaluation is a small fixed benchmark** (11 cases) over the supplied
  files; the metrics describe this benchmark, not general question-answering
  quality.
* **Semantic/embedding retrieval is not wired in.** Dataset selection is
  schema- and metadata-driven; the provider interface is modular but no vector
  index ships yet.
* **The five CSVs are not formally registered** through the ingestion evidence
  store by this pipeline. It reads them read-only and cites them honestly,
  including the unverified WTR-005 mapping and the unverified licence status.
* **No cross-grain joins** are offered (by design); the ward crosswalk needed to
  join water data to any other geography does not exist.
* **Intent routing is rule-based and English-only.**
* **No agentic/autonomous orchestration** is implemented — deliberately. The
  decision engine is a fixed, inspectable pipeline that can be extended.
