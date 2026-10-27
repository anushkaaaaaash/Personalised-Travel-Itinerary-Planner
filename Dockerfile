# Public UI is built without credentials; runtime remains one Python process.
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /source
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
COPY backend/package.json ./backend/package.json
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/index.html frontend/vite.config.js ./frontend/
COPY frontend/src/ ./frontend/src/
COPY frontend/tools/qaPreviewGuard.mjs ./frontend/tools/qaPreviewGuard.mjs
COPY shared/tripPreferences.mjs ./shared/tripPreferences.mjs
COPY deployment/frontend_config.mjs ./deployment/frontend_config.mjs
ENV APP_ENV=production FRONTEND_SAME_ORIGIN=true VITE_API_BASE_URL=/api
RUN npm run build --workspace=frontend

FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_MODE=production APP_ENV=production PORT=8080 SERVE_FRONTEND=true FRONTEND_DIST=/app/frontend-dist
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 planner && useradd --uid 10001 --gid planner --no-create-home planner
COPY backend-python/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=planner:planner backend-python/app/ ./app/
COPY --from=frontend-build --chown=planner:planner /source/frontend/dist/ ./frontend-dist/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.production:create_production_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--timeout-graceful-shutdown", "30"]
