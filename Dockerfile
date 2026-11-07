FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home radar
COPY radar/ ./radar/
COPY migrations/ ./migrations/
COPY alembic.ini providers.py scan_latest.py universities.csv ./
COPY --from=frontend /build/dist ./frontend/dist
RUN mkdir -p /app/data && chown -R radar:radar /app
USER radar
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn radar.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1"]
