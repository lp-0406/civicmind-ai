#!/usr/bin/env python
"""College GPU smoke test (thin wrapper around :mod:`civicmind.ai.gpu_check`).

Typical use on the GPU machine::

    # 1. See the environment and the readiness checks (loads no model).
    python scripts/gpu_smoke_test.py

    # 2. Point at a local model and actually run inference.
    export CIVICMIND_AI_PROVIDER=local
    export CIVICMIND_AI_MODEL_ID=/models/Qwen2.5-7B-Instruct
    export CIVICMIND_AI_DEVICE=cuda:0
    python scripts/gpu_smoke_test.py --load-model

Exit codes: 0 ready, 2 environment not ready, 3 model load/inference failed.
"""

from __future__ import annotations

import sys

from civicmind.ai.gpu_check import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
