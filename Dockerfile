# Runtime-only packaging image for jung-api.
# Uses uv for locked, non-editable installs.

FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

# ============================================
# Runtime: production install without tests/tools
# ============================================
FROM base AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --locked --no-dev --no-editable \
    && python -c "import jung" \
    && python -c "from importlib.resources import files; assert files('jung.persistence').joinpath('schema.sql').is_file()" \
    && python -c "from jung.styles import load_styles; assert load_styles()" \
    && test -x /app/.venv/bin/jung-api

RUN mkdir -p /app/data
VOLUME /app/data

CMD ["jung-api"]
