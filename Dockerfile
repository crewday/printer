FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PRINTER_CONFIG_SECRET_KEY=""

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libusb-1.0-0 cups-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
RUN uv sync --group dev

CMD ["uv", "run", "python", "-m", "printer_app", "--help"]
