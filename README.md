# SunkGuard

SunkGuard is a deterministic admission controller and scheduling engine for compound AI workflows. It helps prevent late-stage cascade failures in multi-step agent systems by prioritizing work based on progress, risk, and resource contention instead of letting FIFO arrival order create wasted execution.

The repo combines:

- a Python simulation engine and formal policy model
- a FastAPI control-plane API
- a React + Vite dashboard for monitoring and experiments
- a Python SDK for embedding reservation-aware orchestration in real workflows

## Why this project exists

In multi-agent and multi-step workflows, a task can spend most of its budget completing the early stages, only to fail late when downstream capacity is suddenly contended. This creates a high-cost failure mode where prior work is effectively "sunk."

SunkGuard addresses that by:

- estimating the risk of late failure as work progresses
- prioritizing workflows by progress and aging factors
- reserving capacity for near-complete tasks
- providing deterministic simulations so behavior can be reproduced and verified

## Core capabilities

- Deterministic discrete-event simulation with seeded RNG
- Admission-control scoring for progressive workflows
- Resource accounting with SWU-based capacity models
- Real-time API layer for monitoring and orchestration
- Dashboard for workflows, resources, reservations, analytics, and policy modes
- Reproducible evaluation harnesses and thesis gates

## Repository layout

```text
.
├── README.md                  # Project overview and developer setup
├── SPEC.md                    # Formal specification and research notes
├── Makefile                   # Common development and verification commands
├── cli.py                     # CLI for demos, comparisons, and eval runs
├── server.py                  # FastAPI backend / control plane
├── package.json               # Frontend app scripts and dependencies
├── vite.config.ts            # Vite config for the React dashboard
├── index.html                # App entry page
├── .env.example              # Example env configuration
├── core/                     # Deterministic simulation, resource, and policy logic
│   ├── canonical.py
│   ├── controller.py
│   ├── gemini_adapter.py
│   ├── metrics.py
│   ├── predictor.py
│   ├── resources.py
│   ├── rng.py
│   ├── runtime.py
│   ├── sim.py
│   └── workflow.py
├── sdk/                      # Python SDK for integrating SunkGuard
│   ├── __init__.py
│   ├── client.py
│   ├── decorator.py
│   └── example.py
├── demo/                     # Live and replayed workflow traces
│   ├── run_gemini_workflow.py
│   ├── replay_traces.py
│   └── traces/
├── eval/                     # Frozen experiment results and evaluation artifacts
├── src/                      # React + TypeScript frontend
│   ├── App.tsx
│   ├── pages/
│   ├── services/
│   ├── domain/
│   ├── data/
│   └── utils/
├── tests/                    # Unit tests for the Python logic
├── public/                   # Static assets and frontend metadata
├── scripts/                  # Evaluation utilities
└── dist/                     # Built frontend output (when generated)
```

## Architecture overview

### 1. Core engine
The `core/` directory contains the simulation and policies that model workflow admissions, resource contention, predictor behavior, and metrics. This is where SunkGuard decides whether to admit, reserve, or delay work.

### 2. Control plane API
`server.py` exposes the runtime state over FastAPI. It powers:

- workflow registration and step requests
- resource and reservation views
- metrics and events
- policy updates
- demo scenarios and Gemini adapter calls

### 3. Frontend dashboard
The `src/` directory contains a React dashboard for visualizing:

- active workflows
- resource utilization
- reservations
- analytics and experiments
- policy mode selection
- activity/event histories

### 4. SDK
The `sdk/` package offers Python-side orchestration for agent workflows, including decorators and a client abstraction for request-and-reserve patterns.

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Optional: a Gemini API key for live adapter execution

## Quick start

### Clone and install

```bash
git clone https://github.com/Aqua32A7/SunkGuard.git
cd SunkGuard
```

### Run the deterministic demo

```bash
python3 cli.py demo
```

or

```bash
make demo
```

### Run the Python test suite

```bash
python3 -m unittest discover tests/ -v
```

or

```bash
make test
```

### Start the backend

```bash
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

or

```bash
make serve
```

### Start the frontend

```bash
npm install
npm run dev
```

or

```bash
make frontend
```

### Build the frontend

```bash
npm run build
```

or

```bash
make build-frontend
```

## Environment configuration

Copy the sample environment file and adjust values as needed:

```bash
cp .env.example .env
```

The example file includes Gemini settings and caps used by the adapter and demo workflows.

## SDK example

```python
from sdk.client import SunkGuardClient
from sdk.decorator import reserved, reserved_step

client = SunkGuardClient()
reg = client.start_workflow(
    name="Market Research Agent",
    agent_type="Research agent",
    template_id="research",
)
workflow_id = reg["workflowId"]

@reserved(step_name="Planning", resource_id="pro", units=2)
def plan_step(query: str, workflow_id: str):
    return {"plan": "...", "total_tokens": 850}

with reserved_step(workflow_id, "Generation", resource_id="pro", units=3) as ctx:
    result = "generated"
    ctx.record_usage(total_tokens=1400)
```

## Research and evaluation workflow

This repo also includes formal comparisons and evaluation pipelines.

Useful commands:

```bash
make compare
make thesis-eval
make verify
```

These invoke the simulation and compare SunkGuard against baseline and ablation strategies. See `SPEC.md` for the formal model and constraints.

## Development notes

- The simulation engine is intentionally deterministic: no wall-clock timing or unseeded random state.
- The dashboard can run in static demo mode using saved eval and trace data when the backend is not connected.
- The API is designed to support both local simulation and real resource-aware execution flows.

## Contributing

If you are extending the project:

1. keep the simulator deterministic and seed-driven
2. preserve API compatibility where possible
3. validate changes with the Python test suite
4. document any policy or evaluator changes in `SPEC.md`

## License

This project is distributed under the repository's license terms. Check the repo for the exact license file before production use.

## Project status

The repo contains a working control-plane implementation, deterministic simulation engine, and frontend dashboard, with evaluation artifacts and policy documentation included in the project itself.

---

For a deeper treatment of the formal model and policy behavior, see `SPEC.md`.
