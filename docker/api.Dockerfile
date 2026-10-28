# API + Celery worker image: CPU only, no PyTorch (bundles serve tree models).
FROM python:3.13-slim

# OMP_WAIT_POLICY=PASSIVE: XGBoost's OpenMP threads sleep between calls instead of spinning. With two
# uvicorn workers and the Celery processes in one container, spinning threads fought over the CPUs:
# one flow took 24 ms (p95 51 ms) instead of 11 ms (p95 16 ms), and a 10k batch 392 ms instead of 226 ms.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    OMP_WAIT_POLICY=PASSIVE

WORKDIR /app

# OpenMP runtime for XGBoost
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/api.txt requirements/api.txt
RUN pip install -r requirements/api.txt

COPY src/ src/
COPY scripts/ scripts/
COPY alembic/ alembic/
COPY alembic.ini .

RUN useradd --create-home --uid 1000 ids \
    && mkdir -p /data \
    && chown ids /data
USER ids

EXPOSE 8000
# uvicorn takes its process count from WEB_CONCURRENCY (Compose: IDS_API_WORKERS)
ENV WEB_CONCURRENCY=2
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
