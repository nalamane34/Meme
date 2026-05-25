FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install .


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 -m bot

COPY --from=builder /install /usr/local

COPY --chown=bot:bot app ./app
COPY --chown=bot:bot migrations ./migrations
COPY --chown=bot:bot alembic.ini ./alembic.ini
COPY --chown=bot:bot scripts ./scripts

RUN chmod +x ./scripts/entrypoint.sh

USER bot
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "./scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
