FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m pip install --upgrade pip setuptools wheel

COPY . .

RUN python -m pip install -e ".[dev]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
