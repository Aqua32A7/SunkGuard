import os
import sys
import json
from typing import List, Dict, Any

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.controller import POLICIES
from core.metrics import collect_metrics
from core.predictor import NonOraclePredictor
from core.resources import ResourceSpec
from core.seeds import DEV_SEEDS, PHASE2_HELD_OUT_SEEDS
from core.sim import SimulationConfig, SimulationEngine
from core.workflow import WorkflowTemplate

# Resource specs: Code sandbox has capacity 2. PAT is 8 ticks.
# Step duration on Code is 11 ticks (d_step >= PAT).
CONVOY_SPECS = [
    ResourceSpec(id="pro", name="Gemini Pro", short="Pro", kind="Model", cap=7, swu_per_unit=1600),
    ResourceSpec(id="flash", name="Gemini Flash", short="Flash", kind="Model", cap=14, swu_per_unit=700),
    ResourceSpec(id="search", name="Search", short="Search", kind="Tool", cap=4, swu_per_unit=400),
    ResourceSpec(id="code", name="Code Runner", short="Code", kind="Tool", cap=2, swu_per_unit=300), # Bottleneck
    ResourceSpec(id="vdb", name="Vector DB", short="VDB", kind="Service", cap=5, swu_per_unit=300),
    ResourceSpec(id="crm", name="CRM", short="CRM", kind="Service", cap=3, swu_per_unit=300),
]

CONVOY_TEMPLATES = [
    WorkflowTemplate(
        id="heavy_pipeline",
        name="Deep Analytical Pipeline",
        short="DeepPipeline",
        description="Executes heavy reasoning then long sandbox execution",
        raw_steps=[
            ("search", 2, 2),
            ("pro", 4, 3),    # builds up 6,400 tokens + SWU
            ("pro", 3, 3),    # builds up another 4,800 tokens -> >50% done!
            ("code", 2, 11),  # BOTTLENECK: duration 11 > PAT 8
            ("flash", 2, 2),
        ],
    ),
    WorkflowTemplate(
        id="adhoc_task",
        name="Adhoc Code Execution",
        short="AdhocCode",
        description="Competes directly for the code runner",
        raw_steps=[
            ("code", 2, 11),  # Direct contention on code bottleneck
            ("flash", 1, 2),
        ],
    ),
    WorkflowTemplate(
        id="light_support",
        name="Light Support",
        short="LightSupport",
        description="Background light queries",
        raw_steps=[
            ("vdb", 2, 2),
            ("flash", 2, 2),
        ],
    ),
]

def train_predictor_for_templates(dev_seeds: List[int]):
    traces: List[Dict[str, Any]] = []
    for s in dev_seeds:
        cfg = SimulationConfig(
            seed=s,
            total_ticks=100,
            load_factor=0.60,
            is_sunkguard=False,
            resource_specs=CONVOY_SPECS,
            templates=CONVOY_TEMPLATES,
        )
        engine = SimulationEngine(cfg)
        engine.run()
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
    predictor = NonOraclePredictor(ewma_alpha=0.30, drift_rate=0.05)
    predictor.train(traces)
    return predictor

def sweep_convoy():
    seeds = PHASE2_HELD_OUT_SEEDS # 51-100
    predictor = train_predictor_for_templates(DEV_SEEDS)

    for load in [0.40, 0.60, 0.75]:
        print(f"\n=======================================================")
        print(f"       CONVOY SCENARIO (d_step=11t, PAT=8t) - LOAD {load}      ")
        print(f"=======================================================")
        for vname, vkey, is_sg in [
            ("Baseline", "uncoordinated", False),
            ("Admission-Only", "admission_only", True),
            ("Full SunkGuard", "full_sunkguard", True),
        ]:
            dones, fails, lates, wastes, waits = [], [], [], [], []
            for s in seeds:
                cfg = SimulationConfig(
                    seed=s,
                    total_ticks=150,
                    load_factor=load,
                    is_sunkguard=is_sg,
                    variant=vkey,
                    predictor=predictor,
                    resource_specs=CONVOY_SPECS,
                    templates=CONVOY_TEMPLATES,
                )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)
                dones.append(m.done_count)
                fails.append(m.failure_rate)
                lates.append(m.late_failed_count)
                wastes.append(m.wasted_token_ratio)
                waits.append(m.mean_new_work_wait)
            n = len(seeds)
            print(
                f"{vname:25} | Done: {sum(dones)/n:5.2f} | Fail%: {sum(fails)/n*100:4.1f}% | "
                f"LateFails: {sum(lates)/n:5.2f} | WastedTokRatio: {sum(wastes)/n*100:5.2f}% | "
                f"Wait: {sum(waits)/n:4.2f}t"
            )

if __name__ == "__main__":
    sweep_convoy()
