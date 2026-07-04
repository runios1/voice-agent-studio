# syntax=docker/dockerfile:1
# One image, one service: build the React frontend, then serve it FROM the Python
# backend so /api, the live WebSockets, and the static app are all same-origin.

# --- stage 1: build the frontend (two entries: index.html + dashboard.html) ---
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The app defaults to mock fixtures unless this is exactly "false" (src/main.tsx).
ENV VITE_USE_MOCK=false
RUN npm run build                       # -> /app/frontend/dist

# --- stage 2: python backend that also serves the built frontend ---
FROM python:3.13-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./backend/
COPY contracts/ ./contracts/
COPY pytest.ini ./
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist
# Render injects $PORT; default 8000 for a plain `docker run`.
CMD ["sh", "-c", "uvicorn backend.integrated_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
