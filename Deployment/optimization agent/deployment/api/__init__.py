"""FastAPI surface for the production dashboard path: network telemetry, integrations,
agent, approvals, alerts, audit, ops, and SSE streams."""
from .app import create_app


__all__ = ["create_app"]
