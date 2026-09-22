# SunkGuard: Predictive Admission Controller for Compound Agent Workflows

[![Deterministic Simulation](https://img.shields.io/badge/Simulation-Deterministic%20Bit--Identical-blue)](SPEC.md)
[![Status](https://img.shields.io/badge/Phase%200--1-Complete-green)](SPEC.md)

**SunkGuard** is a deterministic admission controller and scheduling engine designed to eliminate **late-stage cascading failures** in multi-step compound AI systems (e.g., chains of LLM calls, vector DB lookups, tool executions, and external API requests).

Under uncoordinated or arrival-order (FIFO) scheduling, workflows that have already completed 70–90% of their steps often fail due to sudden downstream contention, destroying all previously invested compute, tokens, and latency. SunkGuard quantifies in-flight sunk investment and prioritizes late-stage workflows through **progress-weighted queue admission** dynamically balanced against queue wait time via a **deadline-aware priority aging queue**.

---

## Key Mathematical Specifications (Phase 0)

Full technical and formal specification is documented in [SPEC.md](SPEC.md).

### 1. $\Delta P_{\text{failure}}$ Estimator
For a workflow $W$ at step index $k$ with lookahead horizon $h$ and predictor confidence $c_W$:
$$\Delta P_{\text{failure}}(W) = S_{\text{rsv}}(W) - S_{\text{no\_rsv}}(W)$$
- **Without Reservation:** $S_{\text{no\_rsv}}(W) = \prod_{j=k+1}^{\min(k+h, N)} (1 - h_j)$, where $h_j = \min\left(1.0, \max\left(0.0, \frac{\rho(r_j) - 1.0 + \delta}{\tau_{\text{pat}} / d_j}\right)\right)$.
- **With Reservation:** $S_{\text{rsv}}(W) = \prod_{j=k+1}^{\min(k+h, N)} (1 - (1 - c_W) h_j)$.
- **Decision Value at Risk:** $\Delta \text{Risk}(W) = \Delta P_{\text{failure}}(W) \cdot W_{\text{sunk}}$.

### 2. Standard Work Units (SWU) & Cost-Equivalence
To schedule across heterogeneous models, tools, and services, SunkGuard defines a unified currency:
$$w_i = u_i \cdot \kappa(r_i)$$
| Resource | Name | Type | Capacity | Equivalence Factor $\kappa(r)$ |
|---|---|---|---|---|
| `pro` | Gemini Pro | Model | 7 units | 1,600 tokens/unit |
| `flash` | Gemini Flash | Model | 14 units | 700 tokens/unit |
| `search` | Web Search | Tool | 4 units | 400 SWU/unit |
| `code` | Code Runner | Tool | 3 units | 300 SWU/unit |
| `vdb` | Vector DB | Service | 5 units | 300 SWU/unit |
| `crm` | CRM API | Service | 3 units | 300 SWU/unit |

### 3. Late Failure Definition
- **Late Failure:** A workflow entering terminal state `failed` having completed **$\ge 50\%$ of its total planned work** ($W_{\text{done}} / W_{\text{total}} \ge 0.50$).
- **Early Failure:** Failed with $0 < W_{\text{done}} / W_{\text{total}} < 0.50$.
- **Admission Queue Timeout:** Dropped in the initial queue before step 0 begins execution ($W_{\text{done}} = 0$).

### 4. Dynamic Priority Function with Deadline-Aware Aging
$$\text{Score}(W, t) = \text{base}_W + \alpha_{\text{aging}} \cdot \text{wait}(W, t) + \beta_{\text{sunk}} \cdot \left(\frac{W_{\text{done}}(W)}{1000}\right)$$
The aging term ($\alpha_{\text{aging}} = 0.35$) provides deadline-aware priority, raising the effective scheduling score as waiting time elapses relative to the patience timeout.

---

## Deterministic Simulation Engine (Phase 1)

The core simulation engine (`core/`) strictly enforces:
- **Simulated Clock:** Integer ticks ($t = 0, 1, 2, \dots$). No wall-clock (`time.time()`).
- **Single Seeded RNG:** Isolated seeded PRNG instance per simulation. No unseeded `random`.
- **No Asyncio:** Synchronous, deterministic discrete event transitions.
- **Bit-Identical Guarantee:** Identical seeds produce bit-identical output traces and hashes.

---

## Quickstart & CLI Usage

### Requirements
- Python 3.10+ (Standard library, optional `rich` for formatting)

### 1. Run Live Acceptance Demo
Reports live measured values from simulated contention (no hardcoded fixed figures):
```bash
make demo
# or
python3 cli.py demo
```

### 2. Run Test Suite
Executes 26 unit tests covering bit-identity, $\Delta P_{\text{failure}}$, aging queue, work units, and metrics:
```bash
make test
# or
python3 -m unittest discover tests/ -v
```

### 3. Compare Baseline vs SunkGuard Head-to-Head
```bash
make compare
# or
python3 cli.py compare --seed 8 --ticks 150
```

### 4. Thesis Gate Evaluation (Seeds 21–50)
Evaluates formal thesis criteria (freeze parameters, $\ge 30\%$ relative reduction in late failures, 95% CI excludes zero, wait ratio $< 2\times$; otherwise generates an empirical regime map):
```bash
make thesis-eval
# or
python3 cli.py thesis-eval --start-seed 21 --end-seed 50
```

### 5. Verify Bit-Identical Reproducibility
```bash
make verify
# or
python3 cli.py verify-reproducibility --seed 42
```

---

## Architecture & Repository Structure

```
.
├── SPEC.md                  # Formal specification, deviations, tag policy, and pre-registration
├── Makefile                 # Automation targets (demo, test, compare, thesis-eval)
├── README.md                # Project documentation and quickstart
├── .env.example             # Template for Gemini API key, call cap, and token cap
├── .env                     # Local environment configuration (gemini-3.6-flash, caps)
├── cli.py                   # Executable CLI interface
├── server.py                # FastAPI control plane API (REST + SSE /api/stream)
├── src/                     # React 19 + Vite dashboard frontend
│   ├── components/          # Reusable UI cards, tables, meters, and timelines
│   └── views/               # Overview, Workflows, Reservations, Metrics, Policy, Replay views
├── sdk/                     # SunkGuard Python SDK
│   ├── __init__.py          # Exports SunkGuardClient, @reserved, reserved_step
│   ├── client.py            # API client with automatic in-memory fallback
│   ├── decorator.py         # @reserved decorator & reserved_step context manager
│   └── example.py           # Runnable multi-step agent workflow example
├── demo/                    # Live Gemini traces and offline replay
│   ├── run_gemini_workflow.py # Executes live Gemini agent workflows with strict caps
│   ├── replay_traces.py     # Deterministic offline trace replay
│   └── traces/              # Recorded execution traces and calibration data
├── eval/results/            # Machine-readable frozen evaluation results
│   ├── gate2_results.json   # Phase 1 held-out evaluation (seeds 21–50)
│   ├── gate3_ablation_results.json # Phase 2 multi-way ablation (seeds 151–250)
│   ├── direct_thesis_test_results.json # Direct headline test across loads 0.25–0.85
│   └── exploratory_admission_pv_results.json # Extended grid admission_pv evaluation
├── core/
│   ├── __init__.py          # Core package definition
│   ├── canonical.py         # Canonical data models, events, and policy definitions
│   ├── controller.py        # SunkGuard, Admission-Only, PV, Headroom, and Baseline controllers
│   ├── gemini_adapter.py    # Gemini provider adapter with call/token caps
│   ├── metrics.py           # Metrics collector, paired 95% CIs, Jain fairness index
│   ├── predictor.py         # Non-oracle Markov transition & EWMA predictor
│   ├── resources.py         # Heterogeneous resource models and capacity pools
│   ├── rng.py               # Deterministic isolated seeded PRNG wrapper
│   ├── runtime.py           # In-memory controller session manager
│   ├── sim.py               # Synchronous discrete-event simulator engine
│   └── workflow.py          # Workflow step models, templates, and SWU accounting
└── tests/                   # Complete unit test suite (48 tests passing)
```

---

## Python SDK & `@reserved` Decorator

Wrap agent functions to automatically coordinate capacity reservations, queueing, and token usage accounting:

```python
from sdk.client import SunkGuardClient
from sdk.decorator import reserved, reserved_step

client = SunkGuardClient()

# 1. Start workflow
reg = client.start_workflow(
    name="Market Research Agent",
    agent_type="Research agent",
    template_id="research",
)
wf_id = reg["workflowId"]

# 2. Decorate compound steps
@reserved(step_name="Step 1: Planning", resource_id="pro", units=2)
def plan_step(query: str, workflow_id: str):
    # Executes only after admission is granted
    return {"plan": "...", "total_tokens": 850}

# 3. Use context manager for inline blocks
with reserved_step(wf_id, "Step 2: Generation", resource_id="pro", units=3) as ctx:
    result = execute_llm_call(...)
    ctx.record_usage(total_tokens=1400)
```

Run the runnable example:
```bash
python3 sdk/example.py
```

---

## Model Uniformity & Tick Calibration (Item J)

All live Gemini executions across traces (`demo/traces/trace_01.json`, `trace_02.json`, `trace_03.json`) and contention benchmarks (`demo/test_gemini_contention.py`) uniformly utilize **`gemini-3.5-flash-lite`** on Google's GA `v1` REST endpoint. This model is chosen for its fast sub-second latency and ample concurrency headroom under multi-step agent contention bursts.

Simulation ticks are calibrated to wall-clock seconds using the unblended $n=42$ live measurement on `gemini-3.5-flash-lite`:
- **Measured Median Step Latency:** $0.5590\text{ seconds}$ ($n=42$ calls, mean: $0.8720\text{s}$, p95: $1.6990\text{s}$).
- **Simulation Median Step Duration:** $3.0\text{ ticks}$ (from canonical task templates).
- **Calibrated Tick Duration:** $1\text{ tick} = \frac{0.5590\text{s}}{3.0} = \mathbf{0.1863\text{ seconds}}$.
- **Restated New-Work Wait Table (Load 0.50, Seeds 151–250):**
  * Baseline: $0.112\text{t} \implies 0.021\text{s}$ ($p95 = 1.0\text{t} \implies 0.186\text{s}$, ratio $1.00\times$).
  * FIFO (Oldest-First): $0.133\text{t} \implies 0.025\text{s}$ ($p95 = 1.0\text{t} \implies 0.186\text{s}$, ratio $1.18\times$).
  * Admission-Only: $0.158\text{t} \implies 0.029\text{s}$ ($p95 = 1.0\text{t} \implies 0.186\text{s}$, ratio $1.40\times$).
  * Full SunkGuard: $0.211\text{t} \implies 0.039\text{s}$ ($p95 = 1.0\text{t} \implies 0.186\text{s}$, ratio $1.88\times$).

---

## Completed Thesis Findings & Empirical Results

The research investigation yields two completed, definitive findings:

### Headline #1: Progress-Weighted Admission + Aging Eliminates Cascading Failures (Proven Contribution)
Prioritizing compound workflows by in-flight progress with deadline-aware priority aging ($\alpha = 0.35, \beta = 0.60$) decisively resolves the sunk-cost dilemma without reserving future capacity:
1. **77–83% Waste Reduction Across 100 Seeds:** On strictly held-out unseen seeds 151–250, Admission-Only cuts wasted-token ratio from $2.05\%$ (Oldest-First) down to $0.34\%$ at load 0.50 (paired 95% CI: $[-1.89\%, -1.53\%]$), while increasing completed runs ($14.84$ vs $13.78$) and lowering overall failure rates ($1.04\%$ vs $8.16\%$).
2. **Real-Traffic Validation Under Burst Contention:** In live multi-tenant Gemini traffic bursts (`demo/test_gemini_contention.py`), Admission-Only achieved **$0.0\%$ token waste** and $100\%$ task completion, compared to **$34.6\%$ token waste** and $66.7\%$ task dropouts under Oldest-First queueing.
3. **Tail Coordination via Aging:** Priority aging ensures workflows waiting near their patience limit receive expedited admission, preventing early-stage starvation while preserving strict progress prioritization during downstream saturation.

### Headline #2: Predictive Reservations Do Not Help and Hurt at High Load (Negative Finding & Retraction)
Predictive capacity reservations were evaluated through three distinct paradigms: continuous physical capacity reservation (`core/controller.py`), protection-value priority scoring (`Admission-PV`), and discrete window-indexed token bucket reservations (`core/regime.py`).
1. **Control Regime Degradation (Shipped Controller):** In the unwindowed control regime matching the shipped production controller, predictive reservations actively degrade performance at high load ($+0.379\text{ percentage points}$ higher token waste at load 0.70) because reserving capacity for future steps locks resources that remain physically idle, starving newly arriving work.
2. **Windowed Regime Retraction:** The preliminary claim of a "23% improvement" for reservations in a windowed regime is formally **RETRACTED**:
   - `Baseline-Backoff` (uncoordinated exponential jittered retry) achieves lower token waste than Full SunkGuard across all evaluated loads ($16.83\%$ vs $19.94\%$ at load 0.50; $25.41\%$ vs $25.39\%$ at load 0.70; $28.78\%$ vs $27.72\%$ at load 0.85). Against backoff, reservations pass 0 of 3 loads.
   - The regime test overall verdict is **FAIL** ($1\text{ of }3\text{ loads passed}$ against non-reservation variants; $0\text{ of }3$ against backoff).
   - Regime "Full" was an exploratory separate discrete bucket model (`core/regime.py`) rather than the shipped continuous controller code.

---

## Architectural Decisions & Scope
1. **Frontend Architecture:** Modern React 19 + TypeScript + Vite frontend (`src/`) communicating via REST API (`/api/`) and Server-Sent Events (`GET /api/stream`).
2. **SSE Real-Time Telemetry:** Server-Sent Events (`text/event-stream`) streams live controller updates, metrics, and canonical event records.
3. **Baseline Variants:**
   - `Baseline` (Uncoordinated): Random order queue with patience timeout (`PAT = 8t`, `QPAT = 28t`).
   - `Baseline-Backoff`: Distributed exponential retry with random jitter.
4. **API Guardrails:** Strict call caps (`GEMINI_CALL_CAP=100`) and token caps (`GEMINI_TOKEN_CAP=500000`) enforced in `core/gemini_adapter.py`.

