# Optimization Agent Model Benchmark

## Overview
This directory contains the comprehensive benchmark and defense analysis for the optimization agent system. The notebook evaluates four policy variants:

- **M5**: Offline LightGBM classifier with oracle reward rules (baseline, warm-start)
- **M6 (LinUCB)**: Online contextual bandit with ridge regression, per-root-cause isolation
- **M7 (LinUCB+LLM)**: Online LinUCB augmented with Qwen2.5-3B LLM as escalation layer
- **EpsilonGreedy**: Decay-rate baseline for isolation of exploration-exploitation value

## Key Files

### `optimization_agent_model_benchmark.ipynb`
Complete end-to-end analysis including:

1. **Data Ingestion & Setup** (Sections 1-3)
   - Load incidents, QoS timeseries, and diagnostic signals
   - Define 9 root-cause types and action catalogs per root cause
   - Initialize episode streaming protocol

2. **Baseline Model (M5)** (Sections 4-7)
   - LightGBM pipeline on calibrated root-cause predictions
   - PolicyGate with 7-criterion truth table
   - Offline evaluation on held-out test split

3. **Online Bandits** (Sections 8-11)
   - LinUCB core algorithm and M6/M7 variants
   - Per-RC bandit isolation (9 separate learners)
   - M7 LLM integration via Qwen2.5-3B on Ollama

4. **Evaluation Framework** (Sections 12-14)
   - 50-seed sweeps for M6 and EpsilonGreedy
   - 10-seed ablation for M7 (limited by LLM compute)
   - Bootstrap 95% CI from 1000 resamples
   - Permutation tests (10K iterations, two-sided)

5. **Visualizations & Interpretation** (Sections 15-18)
   - Reward-latency trade-offs (scatter plots)
   - Seed-level distributions (box plots)
   - Regret-reward coupling analysis
   - Multi-dimensional radar comparison
   - Normalized reward summary (0=random baseline, 1=oracle ceiling)

6. **Robustness Testing** (Section 17)
   - Policy evaluation under 4 reward regimes:
     - Oracle (ground truth)
     - Noisy (±0.1 Gaussian)
     - Adversarial (1 - reward flip)
     - KPI-perturbed (input noise, recomputed rewards)

## Execution Summary

### Performance Rankings (Normalized Reward, 0–1 scale)

| Policy | Online Reward | Frozen Reward | Latency | Status |
|--------|---------------|---------------|---------|--------|
| EpsilonGreedy | 0.956 ± 0.046 | 0.936 | 0.10 ms | Baseline (no cold-start) |
| M5 LightGBM | N/A (offline) | 0.939 | 27.3 ms | Warm-start ceiling |
| M6 LinUCB | 0.905 ± 0.050 | 0.852 | 0.10 ms | **Production candidate** |
| M7 LinUCB+LLM | 0.847 ± 0.024 | 0.850 | 11,497 ms | Escalation layer |

### Key Insights

1. **Warmth vs. Cold-Start**: M5 and EpsilonGreedy (warm) outpace M6 and M7 (cold). This 5–10% gap reflects the cost of learning θ from scratch.

2. **LLM Does Not Compound**: M7's 11.5s latency yields no reward premium over M6; LLM contributes only 2–3% on sampled root causes and is offset by exploration penalty.

3. **Production Architecture**: Deploy M6 as always-on policy (fast, competitive, 50-seed validated). Reserve M7 for PENDING_APPROVAL escalations where response time is fungible and human oversight is required.

4. **Robustness**: All policies maintain rank order across oracle, noisy, adversarial, and KPI-perturbed regimes. No cliff-edge failure modes detected.

5. **Statistical Significance**: Bootstrap CIs overlap within 3–4 percentage points; permutation tests confirm M5 > EpsilonGreedy > M6 > M7 are not due to chance (p < 0.05 for major pairwise differences).

## Configuration

- **Python Version**: 3.11+
- **ML Libraries**: scikit-learn, LightGBM, pandas, numpy
- **LLM Backend**: Ollama with Qwen2.5-3B Q4_K_M quantization (~2 GB VRAM)
- **Visualization**: Plotly with custom theme

### Required Environment Variables

```bash
OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen2.5:3b
LLM_TIMEOUT_S=30
```

## Recommendations for Practitioners

1. **Immediate Deployment**: M6 LinUCB with 0.10 ms latency and 0.905 normalized reward.
2. **Escalation Path**: M7 (LLM) for PENDING_APPROVAL when human ticket review is queued.
3. **Monitoring**: Track online reward drift; retrain M5 if baseline shifts > 2%.
4. **A/B Testing**: Randomize 10–20% of high-confidence incidents to M7 to gather fresh LLM data.

## Model Checkpoint Storage

Pre-trained models and LLM cache:
- `data/models/m5_lightgbm_best.pkl` (LightGBM pipeline)
- `data/models/qwen_cache_full.json` (Ollama prior decisions)

## Changelog

- **2026-04-19**: Added interpretation cells, fixed latency extraction, comprehensive visualization suite (Figures 21–25).
- Description: Complete agent benchmark with parametric policies (M5/M6/M7/EG), bootstrap CIs, permutation tests, and production deployment guidance. Removed legacy notebooks; consolidated to single authoritative assessment.

---

*For questions or issues, contact the Optimization Agent team.*
