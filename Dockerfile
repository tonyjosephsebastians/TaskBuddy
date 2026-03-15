FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY app.py ./
COPY scripts ./scripts
COPY docs ./docs
COPY README.md ./
COPY tests ./tests
COPY --from=frontend-build /app/backend/static ./backend/static

EXPOSE 8000

CMD ["python", "app.py"]
