# Optimization Agent Benchmark Notebook

This notebook documents the benchmark and evaluation work for the QoS Buddy Optimization Agent. It evaluates how well the agent recommends safe network remediation actions from diagnostic contracts, KPI evidence, confidence values, and action constraints.

## Objective

We use this notebook to test whether the Optimization Agent can make stable, policy-aware recommendations across representative QoS incidents. The evaluation focuses on decision quality, robustness, reproducibility, and operational readiness.

## What The Notebook Covers

- Data ingestion and incident interval alignment.
- Data quality filtering and feature engineering.
- Root-cause and action catalog definitions.
- Reward design and validation.
- Chronological train and holdout split.
- Baseline policies and learned policy comparisons.
- Contextual bandit and LLM-guided decision approaches.
- Robustness checks under diagnosis uncertainty.
- Visual analysis of regret, reward, action coverage, and policy behavior.
- Exported artifacts for deployment review.

## Viewing

GitHub can render the notebook directly, but interactive Plotly charts are easier to inspect in Jupyter or nbviewer.

Recommended options:

1. Open the notebook locally with JupyterLab.
2. Use nbviewer for interactive figures.
3. Use the generated HTML figures committed under the deployment optimization reports folder.

## Reproducibility

The evaluation uses a fixed random seed and explicit artifact outputs. The notebook is intended as evidence for the modeling process, not as the primary way to run the production demo.
