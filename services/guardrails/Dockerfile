FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY libs/aegis_core /app/libs/aegis_core
COPY services/guardrails /app/services/guardrails
RUN pip install /app/libs/aegis_core /app/services/guardrails
EXPOSE 8083
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl -fsS http://localhost:8083/healthz || exit 1
CMD ["uvicorn", "guardrails.main:app", "--host", "0.0.0.0", "--port", "8083"]
