# Artifact Policy

This repository intentionally includes selected generated assets because the project is an academic demo and portfolio artifact. We want reviewers to inspect the trained system without having to retrain every model or regenerate every figure.

## Included Intentionally

- Trained model artifacts used by the detection, prediction, diagnostic, and optimization agents.
- CSV samples used for local replay, validation, and demo scenarios.
- Jupyter notebooks that document modeling and evaluation work.
- Generated HTML figures and PDF reports that support model interpretation.
- `.env.example` files with placeholders for local setup.

## Excluded From Git

Runtime-only files should remain local:

- Real `.env` files.
- Private API keys, Jira tokens, and credentials.
- Docker runtime volumes.
- Logs and local process IDs.
- Local SQLite, PostgreSQL, ChromaDB, and MLflow runtime state.
- Python, Node, and test caches.
- Frontend build outputs that can be regenerated.

## Reviewer Notes

The committed artifacts are not production secrets. Demo credentials are documented only for the local Keycloak demo. Any real deployment must replace placeholder values and keep secrets outside Git.

## Maintenance Rule

When adding new data or model outputs, we should either keep them small and documented or add regeneration instructions. Large private datasets, raw operational logs, and real customer data should not be committed.
