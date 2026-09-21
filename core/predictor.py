"""Non-Oracle Predictor for SunkGuard Phase 2.

Learns step transitions and resource demands strictly from historical workflow traces
(training seeds 1-20). The predictor sees ONLY:
- Declared workflow template ID
- Observed step history so far (completed steps)
- Current step index
- Elapsed ticks / waiting time

Strictly NO access to ground truth future steps, total planned work, or oracle noise.
"""

from collections import defaultdict
import math
from typing import Any, Dict, List, Optional, Tuple

from core.resources import DEFAULT_RESOURCE_SPECS, ResourceSpec


class NonOraclePredictor:
    """Statistical n-gram / Markov transition predictor with EWMA parameter estimation.

    Trained exclusively on workflow execution traces from training seeds (1-20).
    """

    def __init__(self, ewma_alpha: float = 0.30, drift_rate: float = 0.05):
        self.ewma_alpha = ewma_alpha
        self.drift_rate = drift_rate

        # Transition counts: transitions[template_id][step_idx][from_resource][to_resource] -> count
        self.transitions: Dict[str, Dict[int, Dict[str, Dict[str, int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        )

        # Initial step distributions: initial_steps[template_id][resource] -> count
        self.initial_steps: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Expected parameters per (template_id, step_idx, resource_id):
        # stores {"units": float, "duration": float, "work": float, "tokens": float, "count": int}
        self.step_stats: Dict[Tuple[str, int, str], Dict[str, float]] = {}

        # Estimated average template lengths: template_lengths[template_id] -> mean length
        self.template_lengths: Dict[str, float] = {}

        self.is_trained: bool = False

    def train(self, workflow_traces: List[Dict[str, Any]]) -> None:
        """Fit transitions and parameter estimates on historical workflow execution traces.

        Each trace in `workflow_traces` must contain:
        - "template_id": str
        - "steps": List[Dict] with "resource_id", "units", "duration", "work", "tokens"
        """
        template_lens = defaultdict(list)

        for trace in workflow_traces:
            tid = trace["template_id"]
            steps = trace["steps"]
            template_lens[tid].append(len(steps))

            if not steps:
                continue

            first_r = steps[0]["resource_id"]
            self.initial_steps[tid][first_r] += 1

            for i, step in enumerate(steps):
                rid = step["resource_id"]
                key = (tid, i, rid)
                if key not in self.step_stats:
                    self.step_stats[key] = {
                        "units": float(step["units"]),
                        "duration": float(step["duration"]),
                        "work": float(step["work"]),
                        "tokens": float(step["tokens"]),
                        "count": 1.0,
                    }
                else:
                    # Update with EWMA
                    st = self.step_stats[key]
                    st["units"] = (1 - self.ewma_alpha) * st["units"] + self.ewma_alpha * step["units"]
                    st["duration"] = (1 - self.ewma_alpha) * st["duration"] + self.ewma_alpha * step["duration"]
                    st["work"] = (1 - self.ewma_alpha) * st["work"] + self.ewma_alpha * step["work"]
                    st["tokens"] = (1 - self.ewma_alpha) * st["tokens"] + self.ewma_alpha * step["tokens"]
                    st["count"] += 1.0

                if i < len(steps) - 1:
                    next_r = steps[i + 1]["resource_id"]
                    self.transitions[tid][i][rid][next_r] += 1

        for tid, lens in template_lens.items():
            self.template_lengths[tid] = sum(lens) / len(lens)

        self.is_trained = True

    def predict_remaining(
        self,
        template_id: str,
        observed_history: List[Dict[str, Any]],
        current_step_idx: int,
        horizon: int,
        elapsed_ticks: int = 0,
    ) -> Tuple[List[Dict[str, Any]], float, float]:
        """Non-oracle downstream prediction.

        Parameters:
        - template_id: Workflow type identifier
        - observed_history: Sequence of completed step dicts
        - current_step_idx: Current active step index
        - horizon: Lookahead depth (e.g. 1, 2, or 9)
        - elapsed_ticks: Total ticks workflow has been in system

        Returns:
        - predicted_steps: List of predicted step dicts
        - confidence: Predictor confidence in [0.10, 0.95]
        - estimated_total_work: Estimated total planned work for this workflow
        """
        est_len = int(round(self.template_lengths.get(template_id, 4.0)))
        steps_remaining = max(0, est_len - current_step_idx)
        lookahead = min(horizon, steps_remaining)

        predicted_steps: List[Dict[str, Any]] = []
        path_confidence = 1.0

        # Last observed resource
        last_r = observed_history[-1]["resource_id"] if observed_history else None

        for step_offset in range(lookahead):
            target_idx = current_step_idx + step_offset
            trans_map = self.transitions[template_id][target_idx - 1].get(last_r, {}) if last_r else {}

            if trans_map:
                tot_trans = sum(trans_map.values())
                # Pick most probable resource transition
                best_r = max(trans_map.keys(), key=lambda r: trans_map[r])
                step_prob = trans_map[best_r] / tot_trans
            else:
                # Fallback to general template defaults
                best_r = "pro" if target_idx % 2 == 1 else "flash"
                step_prob = 0.50

            # Apply synthetic drift penalty over elapsed ticks
            drift_factor = math.exp(-self.drift_rate * (elapsed_ticks / 50.0))
            path_confidence *= (step_prob * drift_factor)

            # Retrieve expected parameters
            st = self.step_stats.get((template_id, target_idx, best_r))
            if st:
                pred_units = int(round(st["units"]))
                pred_duration = int(round(st["duration"]))
                pred_work = int(round(st["work"]))
                pred_tokens = int(round(st["tokens"]))
            else:
                # Conservative fallback defaults
                pred_units = 2
                pred_duration = 3
                pred_work = 1400
                pred_tokens = 1400 if best_r in ("pro", "flash") else 0

            predicted_steps.append({
                "resource_id": best_r,
                "units": max(1, pred_units),
                "duration": max(1, pred_duration),
                "work": pred_work,
                "tokens": pred_tokens,
            })
            last_r = best_r

        # Predict total workflow work = observed work + predicted remaining work
        observed_work = sum(s["work"] for s in observed_history)
        predicted_remaining_work = sum(s["work"] for s in predicted_steps)
        estimated_total_work = observed_work + predicted_remaining_work

        # Clamp confidence to [0.10, 0.95]
        bounded_confidence = max(0.10, min(0.95, path_confidence))

        return predicted_steps, bounded_confidence, estimated_total_work


def train_predictor_on_dev_seeds(
    dev_seeds: Optional[List[int]] = None,
    ticks: int = 150,
    ewma_alpha: float = 0.30,
    drift_rate: float = 0.05,
) -> NonOraclePredictor:
    """Trains a NonOraclePredictor strictly on training seeds (1-20).

    Collects workflow execution traces and fits the Markov transitions and EWMA stats.
    """
    from core.seeds import DEV_SEEDS
    from core.sim import SimulationConfig, SimulationEngine

    seeds = dev_seeds or DEV_SEEDS
    traces: List[Dict[str, Any]] = []

    for s in seeds:
        cfg = SimulationConfig(seed=s, total_ticks=ticks, is_sunkguard=False)
        engine = SimulationEngine(cfg)
        engine.run()

        # Collect traces from completed and failed workflows
        for wf in engine.completed_workflows + engine.failed_workflows:
            trace_steps = [
                {
                    "resource_id": st.resource_id,
                    "units": st.units,
                    "duration": st.duration,
                    "work": st.work,
                    "tokens": st.tokens,
                }
                for st in wf.steps[: wf.step_index + 1]
            ]
            if trace_steps:
                traces.append({"template_id": wf.template_id, "steps": trace_steps})

    predictor = NonOraclePredictor(ewma_alpha=ewma_alpha, drift_rate=drift_rate)
    predictor.train(traces)
    return predictor

