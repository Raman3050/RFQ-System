# syntax=docker/dockerfile:1.7
# Targets:
#   dev  — editable install + test tooling, used by docker-compose.yml (hot reload)
#   prod — runtime deps only, non-root, used by docker-compose.prod.yml

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser


# ---------------------------------------------------------------- dev
FROM base AS dev
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install ".[dev]" \
    && rm -rf app
COPY . .
RUN pip install --no-deps -e . && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------- prod deps
FROM base AS prod-deps
COPY pyproject.toml ./
# Runtime dependencies only (no pytest/ruff/mypy), installed into an isolated prefix.
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --prefix=/install -r requirements.txt


# ---------------------------------------------------------------- prod
FROM base AS prod
COPY --from=prod-deps /install /usr/local
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live').status==200 else 1)"
# --proxy-headers: trust X-Forwarded-For from Nginx so rate limits see real client IPs.
# --timeout-keep-alive 75 > Nginx's upstream keepalive_timeout (60s): Nginx always retires
# an idle connection first, so it never reuses one the API just closed (→ 502).
# Several workers are safe: WebSocket fan-out goes through Redis, not process memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", \
     "--timeout-keep-alive", "75", "--workers", "2"]
