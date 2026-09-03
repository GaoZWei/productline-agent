FROM ghcr.io/astral-sh/uv:0.12.0 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service
COPY --from=uv /uv /uvx /bin/
COPY agent-service/pyproject.toml agent-service/uv.lock agent-service/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agent-service/app ./app
COPY agent-service/migrations ./migrations
COPY agent-service/alembic.ini ./alembic.ini
COPY knowledge-base /knowledge-base

EXPOSE 8000
CMD ["/service/.venv/bin/python", "-m", "app.main"]
