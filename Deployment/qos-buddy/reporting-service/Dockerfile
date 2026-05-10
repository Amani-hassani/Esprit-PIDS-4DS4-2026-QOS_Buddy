FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --upgrade pip && \
    pip install \
      "fastapi>=0.111" \
      "uvicorn[standard]>=0.29" \
      "httpx>=0.27" \
      "asyncpg>=0.29" \
      "pydantic>=2.6"

COPY reporting-service/app.py /app/app.py

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=20 --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
