# Backend only. Build from repository root; never copy the legacy Express app.
FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_MODE=production APP_ENV=production PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 planner && useradd --uid 10001 --gid planner --no-create-home planner
COPY backend-python/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=planner:planner backend-python/app/ ./app/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.production:create_production_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--timeout-graceful-shutdown", "30"]
