FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install --upgrade pip && \
    pip install \
      "pydantic>=2.6" \
      "redis>=5.0" \
      "orjson>=3.9" \
      "tenacity>=8.2" \
      "httpx>=0.27" \
      "opentelemetry-api>=1.27" \
      "opentelemetry-sdk>=1.27" \
      "opentelemetry-exporter-otlp-proto-grpc>=1.27"

COPY contracts/ /app/contracts/
COPY bus/ /app/bus/

ENV PYTHONPATH=/app

CMD ["python", "-m", "bus.monitoring_bridge"]
