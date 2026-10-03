FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --only-group build --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --group build --no-editable --no-build-isolation

CMD ["sh", "-c", "exec uvicorn personal_ai.main:app --host 0.0.0.0 --port ${PORT}"]
