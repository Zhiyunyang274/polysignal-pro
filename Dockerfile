FROM ghcr.io/astral-sh/uv:0.11.11@sha256:798712e57f879c5393777cbda2bb309b29fcdeb0532129d4b1c3125c5385975a AS uv
FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY polysignal ./polysignal

RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 polysignal \
    && useradd --uid 10001 --gid polysignal --no-create-home --home-dir /app \
        --shell /usr/sbin/nologin polysignal \
    && mkdir -p /app/data /app/logs /app/runs \
    && chown -R 10001:10001 /app/data /app/logs /app/runs

COPY --from=builder /opt/venv /opt/venv
COPY polysignal ./polysignal
COPY scripts ./scripts
COPY config ./config

USER 10001:10001

CMD ["python", "-m", "polysignal.main"]
