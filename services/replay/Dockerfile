FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY libs/aegis_core /app/libs/aegis_core
COPY services/replay /app/services/replay
RUN pip install /app/libs/aegis_core /app/services/replay
EXPOSE 8085
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl -fsS http://localhost:8085/healthz || exit 1
CMD ["uvicorn", "replay.main:app", "--host", "0.0.0.0", "--port", "8085"]
