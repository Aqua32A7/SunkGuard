# SunkGuard: Predictive Admission Controller for Compound Agent Workflows

[![Deterministic Simulation](https://img.shields.io/badge/Simulation-Deterministic%20Bit--Identical-blue)](SPEC.md)
[![Status](https://img.shields.io/badge/Phase%200--1-Complete-green)](SPEC.md)

**SunkGuard** is a predictive admission controller and resource reservation engine designed to eliminate **late-stage cascading failures** in multi-step compound AI systems (e.g., chains of LLM calls, vector DB lookups, tool executions, and external API requests).

Under naive or FIFO scheduling, workflows that have already completed 70–90% of their steps often fail due to sudden downstream contention, destroying all previously invested compute, tokens, and latency. SunkGuard estimates the **marginal failure probability reduction** ($\Delta P_{\text{failure}}$) and prioritizes high-investment workflows with **hard and soft resource reservations** while protecting new workflows against starvation via an **aging queue**.

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
- **Starvation:** Dropped in the admission queue before step 0 begins execution ($W_{\text{done}} = 0$).

### 4. Dynamic Priority Function with Aging
$$\text{Score}(W, t) = \text{base}_W + \alpha_{\text{aging}} \cdot \text{wait}(W, t) + \beta_{\text{sunk}} \cdot \left(\frac{W_{\text{done}}(W)}{1000}\right)$$
The aging term ($\alpha_{\text{aging}} = 0.35$) steadily raises priority for waiting jobs, mathematically bounding waiting time and preventing starvation.

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
├── SPEC.md                  # Comprehensive architectural and mathematical specification
├── Makefile                 # Standard automation targets (demo, test, compare, thesis-eval)
├── README.md                # Project documentation and quickstart
├── .env.example             # Template for Gemini API key, call cap, and token cap
├── .env                     # Local environment configuration
├── cli.py                   # Executable CLI interface
├── core/
│   ├── __init__.py          # Core package definition
│   ├── rng.py               # Deterministic isolated seeded PRNG wrapper
│   ├── resources.py         # Resource specifications, pool state, reservations
│   ├── workflow.py          # Workflow step model, SWU conversion, failure classification
│   ├── controller.py        # Baseline and SunkGuard controllers, DeltaP estimator
│   ├── sim.py               # Synchronous discrete event simulation engine
│   └── metrics.py           # Metric collector, Jain fairness, thesis evaluation, regime map
├── dashboard/
│   └── index.html           # Zero-dependency vanilla HTML/CSS/JS dashboard (offline simulator fallback)
└── tests/
    ├── test_bit_identical.py    # Bit-identical determinism verification
    ├── test_deltap_estimator.py # Mathematical properties of DeltaP estimator
    ├── test_late_failure.py     # >=50% late failure classification tests
    ├── test_work_units.py       # SWU token and cost-equivalence tests
    ├── test_aging_queue.py      # Starvation prevention & priority aging tests
    ├── test_metrics.py          # Metric calculations (p95, Jain index, etc.)
    └── test_resources.py        # Resource capacity limits & reservation constraints
```

---

## Architectural Cuts & Design Decisions
1. **No React / Vite:** Dashboard is zero-dependency vanilla HTML/CSS/JS (`dashboard/index.html`), deployable statically with offline simulator intact.
2. **SSE Over WebSocket:** Server-Sent Events is the standard protocol for real-time streaming to frontend clients.
3. **No Pitch-Deck Modal:** UI focuses cleanly on telemetry, resource allocation, and workflow inspection.
4. **API Key & Cap Guardrails:** Strict call cap (`GEMINI_CALL_CAP=100`) and token cap (`GEMINI_TOKEN_CAP=500000`) in `.env`.
