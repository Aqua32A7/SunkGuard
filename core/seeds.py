"""Seed partition configuration for SunkGuard experimental evaluation.

Enforces train / dev / test isolation to prevent data leakage and parameter over-tuning.
"""

from typing import List

# Development & parameter tuning seeds (exclusively used during Phase 1 design)
DEV_SEEDS: List[int] = list(range(1, 21))

# Held-out seeds for Phase 1 preliminary thesis evaluation
THESIS_EVAL_SEEDS: List[int] = list(range(21, 51))

# Strictly held-out seeds for Phase 2 thesis gate
PHASE2_HELD_OUT_SEEDS: List[int] = list(range(51, 101))
