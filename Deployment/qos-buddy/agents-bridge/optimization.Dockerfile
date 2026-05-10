# Dockerfile for the optimization agent.
#
# The upstream `optimization agent/` ships with pyproject.toml but no
# Dockerfile, so qos-buddy supplies one and uses the agent's directory as
# build context. The package installs from pyproject and the FastAPI app is
# `deployment.main:app`.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QOS_RUNTIME_MODE=demo

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc git \
    && rm -rf /var/lib/apt/lists/*

# Copy whole optimization agent dir so MLflow runs, artifacts, and notebooks
# are available — operator's existing `mlruns/` is reused as-is.
COPY . /app/

# Install the project itself (pyproject-driven). pip resolves the dep tree.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "deployment.main:app", "--host", "0.0.0.0", "--port", "8000"]
