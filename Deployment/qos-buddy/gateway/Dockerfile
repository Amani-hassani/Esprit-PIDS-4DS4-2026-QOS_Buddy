FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime deps. We ship contracts/, bus/, gateway/ as the package set.
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
      "pydantic>=2.6" \
      "redis>=5.0" \
      "fastapi>=0.110" \
      "uvicorn[standard]>=0.27" \
      "python-socketio>=5.11" \
      "httpx>=0.27" \
      "orjson>=3.9" \
      "structlog>=24.1" \
      "python-jose[cryptography]>=3.3" \
      "tenacity>=8.2" \
      "opentelemetry-api>=1.27" \
      "opentelemetry-sdk>=1.27" \
      "opentelemetry-exporter-otlp-proto-grpc>=1.27"

COPY contracts/ /app/contracts/
COPY bus/ /app/bus/
COPY gateway/ /app/gateway/

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "gateway.main:asgi", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
