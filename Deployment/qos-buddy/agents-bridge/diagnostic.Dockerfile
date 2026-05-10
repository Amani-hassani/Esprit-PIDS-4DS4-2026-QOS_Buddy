# Override Dockerfile for the existing diagnostic agent.
#
# The upstream `Diagnostic agent/.../deploy/Dockerfile` already works in
# isolation. We replicate it here so qos-buddy can build with
# `context: ../Diagnostic agent/Diagnostic agent notebooks+report` from compose.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QOS_ARTIFACT_DIR=/app/outputs_8rc

WORKDIR /app

COPY deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY deploy/app /app/app
COPY outputs_8rc /app/outputs_8rc

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
