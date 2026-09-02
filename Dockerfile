# ─── Builder stage ───
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir gunicorn asyncpg && \
    pip freeze > /installed.txt

# ─── Runtime stage ───
FROM python:3.12-slim

# runtime deps (postgresql-client for pg_isready in healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY . .

RUN mkdir -p /data/artifacts && \
    # non-root user
    groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appuser /app /data

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown appuser:appuser /entrypoint.sh

USER appuser

EXPOSE 8777

ENTRYPOINT ["/entrypoint.sh"]

HEALTHCHECK --interval=15s --timeout=10s --start-period=90s --retries=10 \
    CMD curl -sf http://localhost:8777/health/live || exit 1

STOPSIGNAL SIGTERM

CMD ["gunicorn", "aios.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8777", \
     "--workers", "2", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--forwarded-allow-ips", "*"]
