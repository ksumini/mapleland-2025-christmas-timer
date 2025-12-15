FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# system deps (필요시 추가)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# poetry 설치
RUN pip install --no-cache-dir poetry

# 의존성 먼저 설치 (캐시 효율)
COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-interaction --no-ansi --only main

# 소스 복사
COPY . /app

# Koyeb는 PORT 환경변수로 포트 제공
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
