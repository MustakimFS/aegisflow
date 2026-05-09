FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY libs/aegis_core /app/libs/aegis_core
COPY services/reliability /app/services/reliability
RUN pip install /app/libs/aegis_core /app/services/reliability
EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl -fsS http://localhost:8082/healthz || exit 1
CMD ["uvicorn", "reliability.main:app", "--host", "0.0.0.0", "--port", "8082"]
