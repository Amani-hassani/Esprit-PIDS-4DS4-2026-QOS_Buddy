# Override Dockerfile for the prediction agent.
#
# Mirrors the upstream `prediction_agent/prediction_agent/backend.dockerfile`
# but built relative to the prediction_agent root so qos-buddy compose can
# point its build context at the existing folder unchanged.

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs models/saved rag/chroma_db mlflow-data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.api_enhanced:app", "--host", "0.0.0.0", "--port", "8000"]
