# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN mkdir -p bot && touch bot/__init__.py \
 && pip install --upgrade pip \
 && pip install -e .

COPY bot/ ./bot/

RUN mkdir -p /app/secrets

EXPOSE 8080

CMD ["python", "-m", "bot.main"]
