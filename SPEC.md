# SunkGuard Specification: Dynamic Admission & Resource Reservation for Compound Agent Workflows

**Document Version:** 1.0.0  
**Phase:** 0–1 Foundation  
**Status:** Approved Specification  

---

## 1. Executive Summary & Problem Formulation

### 1.1 Sunk Cost Dilemma in Compound Agent Systems
In production compound AI systems (e.g., chains of LLM calls, vector database queries, external API integrations, code execution sandboxes), multi-step agent workflows consume heterogeneous, capacity-constrained resources. Under uncoordinated or naive FIFO scheduling, resource contention creates severe cascading failure modes:
1. **Late-Stage Starvation & Failure:** Workflows that have already successfully executed 70–90% of their steps and consumed substantial compute (thousands of tokens and API calls) encounter transient rate-limits, queue exhaustion, or concurrency caps on downstream resources.
2. **Work Destruction (Sunk Waste):** When an agent workflow times out or fails at step 5 of 6, **all tokens, model FLOPs, tool invocations, and latency invested in steps 1 through 4 are completely lost**.
3. **Queue Inequity & Inefficiency:** A newly arrived 1-step workflow competes on equal footing with an 80%-finished, high-value workflow, causing the high-investment workflow to be preempted or drop out.

**SunkGuard** is a deterministic, predictive admission controller and resource reservation engine that eliminates late-stage workflow failures by:
- Quantifying **sunk work at risk** ($W_{\text{sunk}}$).
- Estimating the **marginal failure probability reduction** ($\Delta P_{\text{failure}}$) afforded by reserving downstream capacity.
- Dynamically holding **hard** and **soft reservations** for late-stage workflows.
- Enforcing an **aging queue** to guarantee that new workflows never suffer unbounded starvation.

---

## 2. Work Units & Cost-Equivalence

### 2.1 Standard Work Units (SWU)
To schedule across heterogeneous resources (LLMs, tools, web searches, vector databases, CRMs), SunkGuard establishes a unified currency: the **Standard Work Unit (SWU)**, normalized to model token equivalents.

For any step $s_i$ requiring resource $r_i$ with allocation units $u_i$ and step duration $d_i$:
$$w_i = u_i \cdot \kappa(r_i)$$
where $\kappa(r)$ is the **Work Equivalence Factor** for resource $r \in \mathcal{R}$.

### 2.2 Conversion & Cost-Equivalence Formulation
The equivalence factor $\kappa(r)$ is derived from the dollar cost of the service step relative to reference token pricing:
$$\kappa(r) = \frac{\text{Direct Cost per Step Unit}}{\text{Reference Cost per Token}}$$

Benchmark reference: Gemini 1.5 Pro input/output blend $\approx \$3.00 \text{ per } 1\text{M tokens} = \$0.000003 \text{ per token}$.

| Resource ID | Resource Name | Resource Kind | Capacity ($C_r$) | Unit Definition | Equivalence $\kappa(r)$ (SWU/unit) |
|---|---|---|---|---|---|
| `pro` | Gemini Pro | Model | 7 concurrent units | Concurrency stream | 1,600 tokens/unit |
| `flash` | Gemini Flash | Model | 14 concurrent units | Concurrency stream | 700 tokens/unit |
| `search` | Web Search API | Tool | 4 concurrent calls | Search query | 400 SWU/unit |
| `code` | Code Runner Sandbox | Tool | 3 concurrent sandboxes | Sandbox runner | 300 SWU/unit |
| `vdb` | Vector DB (RAG) | Service | 5 concurrent queries | Embedding query | 300 SWU/unit |
| `crm` | CRM / External API | Service | 3 concurrent sessions | Record read/write | 300 SWU/unit |

### 2.3 Workflow Investment Metrics
For a workflow $W$ composed of ordered steps $(s_1, s_2, \dots, s_N)$:
- **Total Planned Work:**
  $$W_{\text{total}} = \sum_{i=1}^N w_i = \sum_{i=1}^N u_i \cdot \kappa(r_i)$$
- **Completed Work (Sunk Work) at step index $k$ ($0 \le k \le N$):**
  $$W_{\text{done}}(k) = \sum_{i=1}^{k} w_i \quad (\text{where } W_{\text{done}}(0) = 0)$$
- **Tokens Directly Spent:**
  $$T_{\text{spent}}(k) = \sum_{i=1}^{k} \mathbb{I}(r_i \in \{\text{pro}, \text{flash}\}) \cdot u_i \cdot \kappa(r_i)$$
- **Completion Fraction:**
  $$f_{\text{done}}(k) = \frac{W_{\text{done}}(k)}{W_{\text{total}}} \in [0.0, 1.0]$$

---

## 3. Failure Classification: Late Failure Definition

Workflow execution yields one of four mutually exclusive terminal outcomes:

1. **Success (`done`):** All $N$ steps completed successfully.
2. **Late Failure (`late_failed`):** The workflow entered terminal state `failed` while satisfying:
   $$f_{\text{done}} = \frac{W_{\text{done}}}{W_{\text{total}}} \ge 0.50$$
   *Explicit Definition:* **A late failure occurs when a workflow fails after having completed 50% or more of its total planned work units.**
3. **Early Failure (`early_failed`):** The workflow entered terminal state `failed` with:
   $$0 < f_{\text{done}} < 0.50$$
4. **Queue Starvation (`starved`):** The workflow timed out in the admission queue before step 1 could be scheduled ($f_{\text{done}} = 0$).

---

## 4. $\Delta P_{\text{failure}}$ Estimator

### 4.1 Theoretical Foundation
At time tick $t$, consider an active workflow $W$ at step index $k$ with lookahead horizon $h \ge 1$. The controller evaluates whether allocating a reservation for downstream steps $\{s_{k+1}, \dots, s_{\min(k+h, N)}\}$ is economically justified.

Let:
- $P_{\text{fail}}(W \mid \varnothing)$: Probability of workflow failure before horizon completion **without** reservation.
- $P_{\text{fail}}(W \mid \mathcal{R}_{\text{rsv}})$: Probability of workflow failure **with** reservation granted.

The **marginal failure reduction** is defined as:
$$\Delta P_{\text{failure}}(W) = P_{\text{fail}}(W \mid \varnothing) - P_{\text{fail}}(W \mid \mathcal{R}_{\text{rsv}})$$

The **Sunk Value at Risk Reduction** (decision utility) is:
$$\Delta \text{Risk}(W) = \Delta P_{\text{failure}}(W) \cdot W_{\text{done}}$$

### 4.2 Mathematical Derivation of the Operational Estimator

#### Step Contention Modeling: Online Heuristic vs Data-Driven Estimation
**Methodology Clarification (Phase 0–1 Foundation):**
In Phase 0–1, $S_{\text{rsv}}$ and $S_{\text{no\_rsv}}$ are estimated via an **online closed-loop hazard heuristic** calculated from instantaneous resource state at tick $t$, rather than an offline statistical model fit to historical data. 

Specifically:
- **Heuristic Estimation (Phase 0–1 Implementation):** At runtime, the controller samples the instantaneous load ratio $\rho(r_j) = \frac{U_{r_j} + Q_{r_j}}{C_{r_j}}$. The step hazard rate is estimated via a linearized queue saturation heuristic:
  $$h_j = \min\left(1.0, \; \max\left(0.0, \; \frac{\rho(r_j) - 1.0 + \delta_{\text{buffer}}}{\tau_{\text{pat}} / d_j}\right)\right)$$
  where $\delta_{\text{buffer}} = 0.15$ represents the variance buffer.
- **Data-Driven Transition (Phase 2 Roadmap):** In Phase 2, this heuristic will be augmented/replaced by an empirical survival function $\hat{S}_j(t \mid \text{state})$ learned from historical workflow execution logs on designated training seeds (seeds 1–20), accounting for empirical divergence rates, step duration variance, and non-stationary load patterns.

The cumulative survival probability across the lookahead horizon without reservation under the heuristic is:
$$S_{\text{no\_rsv}}(W) = \prod_{j=k+1}^{\min(k+h, N)} (1 - h_j)$$
giving baseline failure probability:
$$P_{\text{fail}}(W \mid \varnothing) = 1 - S_{\text{no\_rsv}}(W)$$

#### Predictor Confidence & Reservation Survival
Let $c_W \in [0.0, 1.0]$ denote the predictor confidence for workflow $W$'s downstream trajectory.
If a reservation is granted on predicted resource $r_j$:
- With probability $c_W$, the prediction is correct; the step encounters zero contention wait ($h_j^{\text{rsv}} = 0$).
- With probability $(1 - c_W)$, the workflow branches or diverges; the reservation is misallocated, and the step experiences ambient contention ($h_j^{\text{rsv}} = h_j$).

Thus, the effective step hazard with reservation is:
$$h_j^{\text{rsv}} = (1 - c_W) \cdot h_j$$

The cumulative survival probability with reservation is:
$$S_{\text{rsv}}(W) = \prod_{j=k+1}^{\min(k+h, N)} (1 - (1 - c_W) \cdot h_j)$$
giving reserved failure probability:
$$P_{\text{fail}}(W \mid \mathcal{R}_{\text{rsv}}) = 1 - S_{\text{rsv}}(W)$$

#### Closed-Form Estimator
Subtracting the two probabilities yields the operational estimator:
$$\Delta P_{\text{failure}}(W) = S_{\text{rsv}}(W) - S_{\text{no\_rsv}}(W)$$

**Key Properties:**
1. **Contention Sensitivity:** When resources are unconstrained ($\rho \le 1 - \delta_{\text{buffer}}$), $h_j = 0 \implies \Delta P_{\text{failure}} = 0$. No reservations are needed.
2. **Predictor Calibration:** As $c_W \to 1.0$, $S_{\text{rsv}} \to 1.0 \implies \Delta P_{\text{failure}} \to P_{\text{fail}}(W \mid \varnothing)$. Perfect reservations eliminate all failure risk.
3. **Graceful Degradation:** As $c_W \to 0.0$, $S_{\text{rsv}} \to S_{\text{no\_rsv}} \implies \Delta P_{\text{failure}} \to 0$. Inaccurate predictions do not trigger hard reservations.

---

## 5. Comprehensive Metrics Suite

| Metric Name | Symbol | Mathematical Formulation | Target Direction |
|---|---|---|---|
| **Late Failure Rate** | $R_{\text{late}}$ | $\frac{N_{\text{late\_failed}}}{N_{\text{done}} + N_{\text{failed}}}$ | Minimize ($\ge 30\%$ drop) |
| **Overall Failure Rate** | $R_{\text{fail}}$ | $\frac{N_{\text{failed}}}{N_{\text{done}} + N_{\text{failed}} + N_{\text{starved}}}$ | Minimize |
| **Wasted Token Ratio** | $\Omega_{\text{tok}}$ | $\frac{\text{Tokens}_{\text{wasted}}}{\text{Tokens}_{\text{total\_consumed}}}$ | Minimize |
| **Wasted Work Ratio** | $\Omega_{\text{work}}$ | $\frac{\text{Work}_{\text{wasted}}}{\text{Work}_{\text{total\_executed}}}$ | Minimize |
| **p95 Latency** | $L_{\text{p95}}$ | 95th percentile of $(t_{\text{complete}} - t_{\text{arrival}})$ for all successful workflows | Minimize / Stable |
| **Resource Utilization** | $\bar{U}$ | $\frac{1}{T \sum C_r} \sum_{t=1}^T \sum_{r \in \mathcal{R}} \text{Used}_t(r)$ | Maximize ($\ge 65\%$) |
| **Reservation Waste** | $\bar{\Omega}_{\text{rsv}}$ | $\frac{1}{T \sum C_r} \sum_{t=1}^T \sum_{r \in \mathcal{R}} \text{ReservedUnused}_t(r)$ | Minimize ($< 15\%$) |
| **Predictor Hit Rate** | $H_{\text{pred}}$ | $\frac{N_{\text{correct\_step\_predictions}}}{N_{\text{total\_step\_predictions}}}$ | Track ($\ge 80\%$) |
| **Jain's Fairness Index** | $\mathcal{J}$ | $\frac{\left(\sum_{i=1}^M x_i\right)^2}{M \sum_{i=1}^M x_i^2}$, where $x_i = \frac{1}{1 + \text{wait}_i}$ | Maximize ($\ge 0.85$) |
| **New-Work Wait Time** | $\bar{W}_{\text{new}}$ | Mean queue wait time for step 0 before initial execution | Bound ($< 2.0\times$ baseline) |

---

## 6. SunkGuard Controller Mechanics & Policies

### 6.1 Admission Priority Function with Aging
To prevent starvation of newly arriving workflows while prioritizing high-investment runs, the admission priority score for workflow $W$ waiting for resource allocation is:
$$\text{Score}(W, t) = \text{base}_W + \alpha_{\text{aging}} \cdot \text{wait}(W, t) + \beta_{\text{sunk}} \cdot \left(\frac{W_{\text{done}}(W)}{1000}\right)$$
- $\text{base}_W$: Inherent workflow SLA priority ($1.0 \dots 3.0$).
- $\alpha_{\text{aging}}$: Linear aging coefficient ($0.35$). Every tick spent waiting steadily increases score, guaranteeing that any starved job eventually dominates.
- $\beta_{\text{sunk}}$: Sunk work coefficient ($0.6 \dots 2.4$ depending on policy).

### 6.2 Reservation Gating & Types
- **Eligibility Threshold:** A workflow qualifies for reservation evaluation if:
  $$\frac{W_{\text{done}}}{W_{\text{total}}} \ge \theta_{\text{thr}}$$
- **Confidence Tiers:**
  * **Hard Reservation:** Granted if $c_W \ge 0.80$ AND the sum of active hard reservations on resource $r$ does not exceed $\gamma_{\text{cap}} \cdot C_r$ (where $\gamma_{\text{cap}} = 0.80$). Hard reservations block lower-priority workflows from acquiring capacity.
  * **Soft Reservation:** Granted if $0.50 \le c_W < 0.80$, or if hard reservation capacity is saturated. Soft reservations act as high-priority cues without hard exclusivity.
- **Time-to-Live (TTL):** Every reservation has a strict countdown $\text{TTL} = 14$ ticks. If unused, it expires, releasing capacity and placing the workflow on a brief reservation cooldown ($6$ ticks).

### 6.3 Standard Policy Configurations
| Policy | Lookahead Horizon $h$ | Work Threshold $\theta_{\text{thr}}$ | Sunk Weight $\beta_{\text{sunk}}$ | Target Operating Regime |
|---|---|---|---|---|
| **Light** | 1 step | $0.55$ (55% done) | $0.6$ | Low contention, sensitive to new-work latency |
| **Medium (Default)** | 2 steps | $0.30$ (30% done) | $1.2$ | Balanced multi-agent production workloads |
| **Aggressive** | Full chain ($9$) | $0.10$ (10% done) | $2.4$ | Critical, expensive long-chain workflows |

---

## 7. Deterministic Simulation Core Specification

To ensure rigorous scientific reproducibility:
1. **Simulated Clock:** Integer ticks $t \in \mathbb{N}_0$. Wall-clock functions (`time.time()`, `datetime.now()`) are forbidden in simulation logic.
2. **Deterministic RNG:** Single seeded 32-bit PRNG (Mulberry32). Unseeded `random` or module-level global randomness is forbidden.
3. **No Asyncio:** Simulation executes synchronously and sequentially.
4. **Bit-Identical Invariant:** Executing the simulation with identical configuration parameters and seed $S$ must produce **100% bit-identical** output logs, state trajectories, and metric records across all platforms and environments.

---

## 8. Thesis Gate & Evaluation Protocol

### 8.1 Parameter Freeze Protocol
Before running the formal thesis evaluation:
1. All policy parameters ($\alpha_{\text{aging}}, \beta_{\text{sunk}}, \theta_{\text{thr}}, h, \text{TTL}, \gamma_{\text{cap}}$) must be frozen in source code.
2. A clean git commit must be created and tagged: `thesis-params-frozen`.
3. Seeds 1 through 20 are reserved exclusively for development and tuning.
4. Seeds 21 through 50 are evaluated **without any modifications** to frozen parameters.

### 8.2 Pass / Fail Acceptance Criteria
The thesis evaluation passes if and only if all three conditions are met across evaluation seeds 21–50:
1. **$\ge 30\%$ Relative Reduction in Sunk Loss:**
   $$\text{RelativeReduction}(R_{\text{late}}) = \frac{\bar{R}_{\text{late, baseline}} - \bar{R}_{\text{late, sunkguard}}}{\bar{R}_{\text{late, baseline}}} \ge 0.30$$
2. **Statistical Significance:** The 95% Confidence Interval of the paired differences across seeds excludes zero ($p < 0.05$).
3. **Bounded New-Work Delay:**
   $$\frac{\bar{W}_{\text{new, sunkguard}}}{\bar{W}_{\text{new, baseline}}} < 2.0$$

### 8.3 Fallback: Regime Map Generation
If the thesis gate criteria fail under boundary conditions (e.g. extreme saturation $\rho > 1.2$ or low load $\rho < 0.3$), the test suite generates a 2D **Regime Map** over:
- Load factor $\lambda \in [0.2, 0.9]$
- Workflow length / variance
identifying the exact boundaries of SunkGuard superiority.

### 8.4 Measured Value Reporting Rule
All interactive demonstrations, CLI summaries, and validation outputs must report **live measured values** from the simulation run. Hardcoded static values (such as fixed "87% done" or "40k tokens saved") are prohibited in dynamic acceptance verification.

---

## 9. Architectural Decisions & Scope

1. **No React / Vite:** The frontend dashboard remains a zero-dependency vanilla HTML/CSS/JS application (`dashboard/index.html`), deployable statically or served by FastAPI.
2. **Offline Simulator Fallback:** The standalone in-browser simulation engine inside `dashboard/index.html` is preserved for zero-backend offline demonstration.
3. **SSE Over WebSockets:** Server-Sent Events (`text/event-stream`) is the standard real-time communication protocol between backend and dashboard, avoiding duplex WebSocket state overhead.
4. **No Pitch-Deck Modal:** UI focuses exclusively on orchestration, live telemetry, workflow inspection, and cost analysis.
5. **API Key & Cap Guardrails:** `.env` configures `GEMINI_API_KEY`, bounded by strict `GEMINI_CALL_CAP` and `GEMINI_TOKEN_CAP` limits.
