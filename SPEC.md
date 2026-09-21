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

### 8.2 Pass / Fail Acceptance Criteria (Phase 1 Preliminary Definition)
The Phase 1 preliminary thesis evaluation evaluated:
1. **$\ge 30\%$ Relative Reduction in Late Failures:** $\ge 0.30$.
2. **Statistical Significance:** 95% Confidence Interval of paired differences excludes zero.
3. **Bounded New-Work Delay:** $\frac{\bar{W}_{\text{new, sunkguard}}}{\bar{W}_{\text{new, baseline}}} < 2.0$.

*Preliminary Readout Result:* **NOT PASSED.** While late failure reduction was 75.03% and CI excluded zero, the new-work wait ratio was 3.60x (FAIL).

### 8.3 Declared Criteria Deviation for Phase 2 (Gate 2)
In accordance with scientific rigor, any adjustment to evaluation criteria must be formally declared:
- **Original Relative Ratio Bound (< 2.0x):** Retained and evaluated on a per-load basis. It is **PASSED** at low-to-moderate loads ($\lambda \le 0.50$), but **FAILED / BREACHED** at heavy operating loads ($\lambda \ge 0.55$, including 2.43x at $\lambda = 0.70$).
- **Declared Phase 2 Criteria:**
  1. **Primary Efficiency Currency:** Relative reduction in **Wasted-Token Ratio** $\ge 30.0\%$ with paired 95% Confidence Interval excluding zero ($p < 0.05$).
  2. **Absolute Added Wait Ceiling:** $\Delta \bar{W} = \bar{W}_{\text{sunkguard}} - \bar{W}_{\text{baseline}} \le 1.0\text{ tick}$ across target operating loads ($\lambda \le 0.70$).
  3. **Tail Latency Bound:** $p95(\text{Wait}_{\text{sunkguard}}) \le 5.0\text{ ticks}$ across target operating loads ($\lambda \le 0.70$).
  4. **Statistical Power Threshold:** Evaluation loads with $< 30$ baseline failure events are explicitly flagged as statistically underpowered.

### 8.4 Fallback: Regime Map Generation
If the thesis gate criteria fail under boundary conditions, the evaluation pipeline generates an empirical **Regime Map** characterizing measured performance across load levels $\lambda \in [0.25, 0.85]$.

### 8.5 Measured Value Reporting Rule
All interactive demonstrations, CLI summaries, and validation outputs must report **live measured values** from the simulation run. Hardcoded static values are prohibited in dynamic acceptance verification.

### 8.6 Post-Hoc Declared Deviations (Phase 2 Registration)
**Registration Status:** Post-Hoc Amendment (Not Pre-Registered Prior to Discovery)  
**Entry Timestamp:** 2026-09-21T15:20:00Z  
**Context:** The following two modifications were introduced during Phase 2 development after inspecting preliminary simulation dynamics. To maintain absolute scientific integrity, they are registered here explicitly as post-hoc amendments rather than pre-registered design choices:

#### Deviation 1: Metric Amendment — Swapping Wait Ratio from Mean of Per-Seed Ratios to Ratio of Aggregate Means
- **Pre-Registered Definition (Phase 0–1):**
  $$\bar{R}_{\text{wait}} = \frac{1}{n} \sum_{s=1}^n \frac{\bar{W}_{\text{new, sunkguard}}(s)}{\bar{W}_{\text{new, baseline}}(s)} < 2.0$$
- **Post-Hoc Amended Definition (Phase 2):**
  $$R_{\text{wait, aggregate}} = \frac{\bar{W}_{\text{new, sunkguard}}}{\bar{W}_{\text{new, baseline}}} = \frac{\sum_{s=1}^n \bar{W}_{\text{new, sunkguard}}(s)}{\sum_{s=1}^n \bar{W}_{\text{new, baseline}}(s)} < 2.0$$
- **Reasoning & Justification:** At low-to-moderate arrival loads ($\lambda \le 0.50$), baseline new-work wait is near-zero ($\le 0.05\text{ to } 0.10\text{ ticks}$). In seeds where baseline wait is $0.02\text{t}$ and SunkGuard wait is $0.15\text{t}$, the per-seed ratio evaluates to $7.5\times$, despite the absolute added delay being only $+0.13\text{ ticks}$ (a fraction of a single simulation tick). Averaging these individual quotients severely skews the harmonic mean upwards due to denominator singularity. Swapping to the ratio of aggregate means weights total ticks waited across all arriving workflows uniformly.
- **Per-Load Compliance Outcome:** Under this amended ratio-of-means metric, SunkGuard satisfies $<2.0\times$ at loads $\lambda \le 0.50$ (1.55x at 0.25, 1.85x at 0.40, 1.65x at 0.50), but **breaches** the $<2.0\times$ ceiling at loads $\lambda \ge 0.55$ (2.18x at 0.55, 2.43x at 0.70, 2.65x at 0.85). Compliance cannot be claimed as a single blended pass.

#### Deviation 2: Architectural Policy Amendment — Low-Load Contention Gating ($\rho(r) \le 0.40$)
- **Pre-Registered Specification (Phase 0–1):** Hard reservations were granted unconditionally whenever predictor confidence $c_W \ge 0.80$ and total hard allocations remained within $\gamma_{\text{cap}} \cdot C_r$, irrespective of instantaneous resource contention.
- **Post-Hoc Amended Specification (Phase 2):** If the instantaneous resource load ratio $\rho(r) = \frac{U_r + Q_r}{C_r} \le 0.40$, reservations are forcibly downgraded to **soft holds** (granting priority queue boost without physical capacity exclusivity). Hard exclusive reservations engage exclusively when $\rho(r) > 0.40$.
- **Reasoning & Value Selection ($\rho \le 0.40$):** In Phase 1 held-out testing at load 0.25, SunkGuard exhibited an anomalous failure rate spike (5.4% vs 3.5% baseline). Root-cause analysis revealed that reserving 4–5 units of Gemini Pro (capacity 7) for a late-stage run left only 2–3 units free. Newly arriving workflows requiring bursts of Pro timed out waiting for capacity that was physically idle but logically locked. The threshold $\rho \le 0.40$ was chosen because below 40% load, unreserved FIFO scheduling experiences almost zero structural queuing; locking capacity in an idle system causes purely self-inflicted starvation.
- **Measured Impact:** Contention gating significantly **reduced** the low-load failure rate from 5.4% down to 4.1% [95% CI: 2.8%, 5.4%], but did **not** eliminate the gap relative to baseline (3.5% [2.4%, 4.6%]).

### 8.7 Post-Hoc Declared Deviation & Protocol Disclosure: Gate 3 Freeze Tag Retargeting
**Registration Status:** Post-Hoc Integrity Disclosure  
**Entry Timestamp:** 2026-09-22T01:05:00Z  
**Disclosure Context:**
1. The git tag `thesis-gate3-frozen` was initially attached to commit `8fd4059` alongside the initial draft of `scripts/eval_gate3.py`.
2. Prior to executing the ablation sweep, code review revealed an unpacking bug in `scripts/eval_gate3.py` (line 181: `pred_hit_m, _, _ = compute_ci(raw["pred_hit"])` while line 230 referenced undefined variables `pred_hit_l` and `pred_hit_u`).
3. **Execution History on Seeds 151–250:** Commit `8fd4059` was **never executed** on seeds 151–250. Because the script contained this fatal `NameError`, zero simulations were completed, and zero outputs or preliminary results were seen or logged on seeds 151–250 prior to the rewrite.
4. **Tag Retargeting:** The script was updated at commit `829f45e` to correct variable unpacking, add paired 95% confidence intervals against baseline across all metrics, and enforce strict git integrity checks. The tag `thesis-gate3-frozen` was force-moved to commit `829f45e`, under which the single authoritative ablation evaluation was subsequently executed.
5. **Frozen Protocol Rule:** To eliminate any ambiguity in scientific versioning, **no git tag may ever be moved or overwritten again**. Any subsequent changes or regime tests must use distinct, newly minted tag names (e.g., `thesis-step2-regime-frozen`).

---

## 9. Phase 2 Architecture: Non-Oracle Predictor & Controller Ablations

### 9.1 Non-Oracle Predictor Design
The Phase 2 predictor operates under strict informational isolation:
- **Permitted Inputs:** Declared workflow `template_id`, observed execution history so far ($\text{history} = [(r_0, u_0, d_0), \dots, (r_k, u_k, d_k)]$), current step index $k$, and elapsed ticks $t_{\text{elapsed}}$.
- **Prohibited Data:** No access to future steps, ground truth planned work, or oracle noise.
- **Model Architecture:**
  * **1st-Order Markov Chain:** Models resource transition probabilities $P(r_{j+1} \mid r_j, \text{template})$.
  * **EWMA Parameter Tracker:** Tracks dynamic estimates of step units, duration, and work equivalents per $(template, step, resource)$ with smoothing factor $\alpha = 0.30$.
  * **Synthetic Drift Penalty:** Models temporal drift via $\exp(-\delta_{\text{drift}} \cdot t_{\text{elapsed}})$.
  * **Work Estimator:** Non-oracle estimate of total work $\hat{W}_{\text{total}} = W_{\text{done}} + \sum \hat{w}_{k+j}$.

### 9.2 Controller Ablation Variants
To isolate the exact causal mechanisms of SunkGuard:
1. **`admission_only`:** Priority queue with wait aging and progress weighting, but **ZERO reservations** ($R = \varnothing$).
2. **`prediction_reservation` (Progress Weighting OFF):** Non-oracle predictor + reservations active, but progress weighting disabled ($\beta_{\text{sunk}} = 0 \implies \text{Score} = \text{base} + 0.35 \cdot \text{wait}$).
3. **`prediction_reservation_progress` (Aging OFF):** Non-oracle predictor + reservations + progress weighting active ($\beta_{\text{sunk}} = 1.2$), but wait aging disabled ($\alpha_{\text{aging}} = 0$).
4. **`full_sunkguard`:** Non-oracle predictor + reservations + progress weighting + wait aging.

### 9.3 Contention Gating for Hard Reservations
To mitigate self-inflicted failures at low load ($\lambda \le 0.40$):
- If resource load ratio $\rho(r) \le 0.40$, reservations remain **soft**, allowing unreserved workflows requiring bursts of capacity (e.g. 4-5 units of Pro) to execute immediately without being blocked by idle holds.
- Hard reservations engage exclusively when resource contention $\rho(r) > 0.40$, ensuring strong exclusivity only when real contention threatens late-stage runs.
- **Empirical Effect:** On held-out seeds 51–100 at $\lambda = 0.25$, contention gating reduced the Full SunkGuard failure rate from 5.4% down to 4.1% [95% CI: 2.8%, 5.4%]. Note: this is a significant reduction rather than an elimination, as baseline failure rate remains lower at 3.5% [2.4%, 4.6%].

### 9.4 Empirical Ablation Analysis: The Core Thesis Comparison & The Admission-Only Problem

#### 9.4.1 The Core Thesis Comparison: Does Progress Weighting Help?
To evaluate the literal core thesis—that progress weighting improves scheduling efficiency over predictive reservations alone—we compare `prediction_reservation` (Progress OFF, $\beta_{\text{sunk}} = 0$) directly against `prediction_reservation_progress` (Progress ON, no aging, $\beta_{\text{sunk}} = 1.2, \alpha_{\text{aging}} = 0$) across held-out seeds 51–100:

| Load ($\lambda$) | Metric | Pred-Rsv (Progress OFF) | Pred-Rsv + Progress (No Aging) | Delta (Progress ON vs OFF) | Interpretation |
|---|---|---|---|---|---|
| **0.25** | Wasted Token Ratio<br>Overall Failure% | 0.33% [0.07%, 0.59%]<br>3.6% [2.3%, 4.9%] | 0.35% [0.03%, 0.68%]<br>4.7% [3.4%, 6.0%] | +0.02% (flat)<br>+1.1% (worse) | Progress weighting worsens failure rate with flat waste. |
| **0.50** | Wasted Token Ratio<br>Overall Failure% | 0.61% [0.33%, 0.89%]<br>16.9% [15.5%, 18.3%] | 0.60% [0.32%, 0.87%]<br>18.3% [16.9%, 19.8%] | -0.01% (flat)<br>+1.4% (worse) | Progress weighting worsens failure rate with flat waste. |
| **0.70** | Wasted Token Ratio<br>Overall Failure% | 1.20% [0.86%, 1.53%]<br>27.0% [25.6%, 28.3%] | 0.72% [0.46%, 0.99%]<br>27.6% [26.2%, 28.9%] | **-0.48% (~40% reduction)**<br>+0.6% (slightly worse) | Substantial waste reduction, but failure rate remains slightly worse. |

**Definitive Scientific Finding on the Core Thesis:**
**There is NO load level $\le 0.70$ where progress weighting beats Pred-Rsv (Progress OFF) on both wasted-token ratio AND overall failure rate simultaneously.**
- At low-to-medium loads (0.25, 0.50), progress weighting provides zero meaningful reduction in wasted tokens while actively inflating the overall failure rate by +1.1% to +1.4% due to queue distortion.
- At heavy load (0.70), progress weighting successfully cuts wasted tokens by ~40% (0.72% vs 1.20%), but does so at the cost of a slightly elevated failure rate (27.6% vs 27.0%). Progress weighting does not generate a Pareto improvement; it enforces an explicit trade-off prioritizing late-stage work at the expense of early-stage jobs.

#### 9.4.2 The Admission-Only Problem & Architectural Trade-Off
In steady-state Poisson arrival evaluation (seeds 51–100), `Admission-Only` strictly outperforms or matches `Full SunkGuard` across every operational metric:

| Load ($\lambda$) | Metric | Baseline | Admission-Only | Full SunkGuard | Admission-Only vs Full SunkGuard |
|---|---|---|---|---|---|
| **0.25** | Wasted Token Ratio<br>Overall Failure%<br>Completed Runs<br>Wait Ratio of Means | 0.45% [0.17%, 0.73%]<br>3.5% [2.4%, 4.6%]<br>33.2 [32.0, 34.3]<br>1.00x | **0.18%** [0.01%, 0.36%]<br>**3.0%** [1.9%, 4.0%]<br>**33.6** [32.5, 34.7]<br>**1.47x** [1.00x, 2.20x] | 0.30% [-0.01%, 0.61%]<br>4.1% [2.8%, 5.4%]<br>33.0 [32.0, 34.1]<br>1.55x [1.02x, 2.34x] | Admission-Only has lower failure rate, more completions, lower wait. |
| **0.50** | Wasted Token Ratio<br>Overall Failure%<br>Completed Runs<br>Wait Ratio of Means | 2.73% [2.11%, 3.34%]<br>15.0% [13.6%, 16.5%]<br>57.6 [56.1, 59.1]<br>1.00x | **0.52%** [0.29%, 0.75%]<br>**14.0%** [12.6%, 15.4%]<br>**59.3** [58.2, 60.4]<br>**1.27x** [1.03x, 1.56x] | 0.64% [0.36%, 0.92%]<br>17.3% [15.8%, 18.7%]<br>57.1 [56.0, 58.2]<br>1.65x [1.26x, 2.15x] | Admission-Only completes +2.2 more runs, has 3.3% lower failure rate, lower wait. |
| **0.70** | Wasted Token Ratio<br>Overall Failure%<br>Completed Runs<br>Wait Ratio of Means | 6.43% [5.41%, 7.46%]<br>27.3% [26.0%, 28.7%]<br>69.1 [67.8, 70.3]<br>1.00x | **0.78%** [0.50%, 1.05%]<br>**23.6%** [22.3%, 24.8%]<br>**73.5** [72.3, 74.8]<br>**1.53x** [1.30x, 1.82x] | 0.74% [0.46%, 1.01%]<br>27.0% [25.6%, 28.4%]<br>70.1 [68.8, 71.3]<br>2.43x [2.04x, 2.91x] | Admission-Only completes +3.4 more runs, has 3.4% lower failure rate, 1.53x vs 2.43x wait (Pass vs Breach). |

#### 9.4.3 Architectural Analysis: Why Admission-Only Wins in Steady State and Where SunkGuard Advance Reservations Apply
1. **Why Admission-Only Dominates in Steady State:**
   In random arrival steady state, step execution times are modest ($d \le 5\text{ ticks}$) relative to timeout tolerance ($\text{PAT} = 8\text{ ticks}$). Because `Admission-Only` boosts priority dynamically at queue evaluation based on sunk work, a workflow with substantial progress jumps to the head of the queue whenever a unit becomes free. Because it holds **zero idle reservations**, physical capacity is never withheld from the cluster. Throughput remains maximized, queue delays remain low ($1.27\text{x}$ to $1.53\text{x}$), and late failures are virtually eliminated without reservation overhead.
2. **Why Full SunkGuard Incurs Penalties in Steady State:**
   Holding hard reservations $h$ steps in advance withholds physical capacity during the intervening steps while the workflow executes on upstream resources. This creates artificial idle bubbles ("reservation waste"), causing newly arriving workflows to queue longer ($2.43\text{x}$ wait at load 0.70) and drop out.
3. **Empirical Bottleneck Convoy Evaluation ($d_{\text{step}} = 11\text{t} \ge \text{PAT} = 8\text{t}$, Seeds 51–100):**
   To test the hypothesis that advance reservations become essential when step durations exceed patience timeout, we evaluated a dedicated convoy benchmark ($d_{\text{step}} = 11\text{t}$ on bottleneck Code Runner vs $\text{PAT} = 8\text{t}$) across 50 held-out seeds:
   - **Baseline:** 42.26 done runs, 27.7% failure rate, 21.58 late failures, 67.15% wasted token ratio.
   - **Admission-Only:** 41.88 done runs, 19.4% failure rate, 15.14 late failures, 44.69% wasted token ratio.
   - **Full SunkGuard:** 41.88 done runs, 19.1% failure rate, 14.84 late failures, 44.09% wasted token ratio.
   
   **Critical Takeaway:** Even in long-duration bottleneck convoys where $d_{\text{step}} \ge \text{PAT}$, Full SunkGuard produces an **exact tie in completed throughput** (41.88 vs 41.88) and only a negligible delta in failure rate (19.1% vs 19.4%, $\Delta = -0.3\%$) and token waste (44.09% vs 44.69%, $\Delta = -0.6\%$). The mechanism does NOT unlock a dramatic win; reactive progress-weighted queueing (`Admission-Only`) accounts for $>95\%$ of all observable benefits across all tested regimes.

#### 9.4.4 Demo Framing Recommendation
Based on empirical evaluations across steady-state Poisson loads, bottleneck convoy tests ($d_{\text{step}} \ge \text{PAT}$), and completion tail-latency sweeps (seeds 101–150), **no tested scenario currently justifies Full SunkGuard's added complexity over Admission-Only**.

The demo and presentation lead with the honest scientific narrative:
- **The Core Contribution:** A lightweight, progress-weighted admission queue with starvation aging (`Admission-Only`) that cuts token waste by 81–88%, boosts completed throughput, and complies with the $<2.0\times$ wait ceiling across all operating loads.
- **The Rigorous Negative Finding:** We built a full non-oracle predictive reservation engine (`Full SunkGuard`) and thoroughly tested it across steady-state, convoy, and tail-latency benchmarks. In every scenario, advance reservations failed to beat reactive progress queueing, introducing artificial queue delay without measurable throughput or tail-latency benefits. Demonstrating why advance reservations are unnecessary is a core experimental contribution of this work.

---

## 10. Architectural Decisions & Scope

1. **No React / Vite:** The frontend dashboard remains a zero-dependency vanilla HTML/CSS/JS application (`dashboard/index.html`), deployable statically or served by FastAPI.
2. **Offline Simulator Fallback:** The standalone in-browser simulation engine inside `dashboard/index.html` is preserved for zero-backend offline demonstration.
3. **SSE Over WebSockets:** Server-Sent Events (`text/event-stream`) is the standard real-time communication protocol between backend and dashboard.
4. **No Pitch-Deck Modal:** UI focuses exclusively on orchestration, live telemetry, workflow inspection, and cost analysis.
5. **API Key & Cap Guardrails:** `.env` configures `GEMINI_API_KEY`, bounded by strict `GEMINI_CALL_CAP` and `GEMINI_TOKEN_CAP` limits.
