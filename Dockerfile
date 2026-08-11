FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY feederss/ ./feederss/
# only the static assets — the html/json in public/ are regenerated on every
# run and are excluded by .dockerignore
COPY public/ ./public/

RUN useradd --create-home --uid 10001 feederss && chown -R feederss:feederss /app
USER feederss

# Container-specific paths and the refresh cadence. Everything else — DB_URL,
# APP_URL, the S3 bucket and credentials — has no sensible default and must be
# supplied at run time. See README.md.
ENV PUBLIC_DIR=/app/public \
    HEARTBEAT_FILE=/tmp/feederss-heartbeat \
    REFRESH_INTERVAL_SECONDS=3600

# start-period covers the first build+publish, which is the slow one (nothing
# in the bucket matches yet, so every object uploads)
HEALTHCHECK --interval=60s --timeout=30s --start-period=300s --retries=3 \
    CMD ["python", "-m", "feederss", "healthcheck"]

CMD ["python", "-m", "feederss", "loop"]
