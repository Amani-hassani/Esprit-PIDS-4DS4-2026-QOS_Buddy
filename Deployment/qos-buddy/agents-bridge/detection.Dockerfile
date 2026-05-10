# Override Dockerfile for the existing detection agent backend.
#
# The upstream `detection agent/backend/Dockerfile` works in isolation but its
# requirements.txt drops mlflow even though app/main.py imports it. We rebuild
# the image with mlflow restored so the agent boots cleanly inside the
# qos-buddy compose network. Compose mounts the model dir read-only at runtime
# so the same .keras / .pkl artifacts the data scientist trained get served.

FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy upstream requirements then layer in the missing mlflow dep.
# JSON-array COPY form is required because the source path has a space.
COPY ["detection agent/backend/requirements.txt", "/tmp/requirements.txt"]
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && pip install --no-cache-dir mlflow==2.10.0

# Copy the agent source verbatim — we want to run the operator's real code.
COPY ["detection agent/backend/", "/app/"]

# Inject the custom Keras subclass that was lost from the runtime so
# `keras.models.load_model(...)` can resolve the registered class name.
COPY ["qos-buddy/agents-bridge/detection_custom_objects.py", "/app/app/core/custom_objects.py"]
# Make sure the class is registered before the model is loaded by importing
# it at the top of the model_loader module.
RUN sed -i '1a from app.core import custom_objects  # noqa: F401' /app/app/core/model_loader.py

# Models and the SQLite db live on a volume so they survive rebuilds.
RUN mkdir -p /app/data /app/models /app/mlruns

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
