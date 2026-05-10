"""Uvicorn entry point. Run with:

    uvicorn deployment.main:app --reload --port 8000
"""
from __future__ import annotations

from .api import create_app


app = create_app()
