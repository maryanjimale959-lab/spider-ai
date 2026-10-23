# =============================================================================
# SPIDER AI - one image, one process: the API and the built interface
#
#   docker build -t spider-ai .
#   docker run -p 8000:8000 -v spider-data:/data spider-ai
#   http://localhost:8000
#
# Everything the product stores - the database and the uploaded documents - lives
# under /data, so a host volume (or a Railway volume mounted at /data) is the only
# persistence it needs.
# =============================================================================

# ---------------------------------------------------------------- 1. interface
FROM node:22-slim AS interface
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# -------------------------------------------------------------- 2. application
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPIDER_ENVIRONMENT=production \
    SPIDER_DATABASE_URL=sqlite:////data/spider_ai.db \
    SPIDER_STORAGE_DIR=/data/storage \
    SPIDER_RENDERED_DIR=/data/storage/rendered

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=interface /build/dist ./frontend/dist

RUN mkdir -p /data/storage/rendered
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir backend"]
