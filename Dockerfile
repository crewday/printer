FROM python:3.14.4-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PRINTER_CONFIG_SECRET_KEY=""

# CUPS daemon configuration (optional).
# Set CUPS_ENABLED=true to start the CUPS daemon inside the container.
# Set CUPS_LPADMIN_PRINTER to an lpadmin-compatible URI to auto-create a printer queue.
# Set CUPS_LPADMIN_NAME / CUPS_LPADMIN_DESC to customise the queue name and description.
# Alternatively, mount your own /etc/cups printers.conf for full control.
ENV CUPS_ENABLED=false
ENV CUPS_LPADMIN_NAME=""
ENV CUPS_LPADMIN_DESC=""
ENV CUPS_LPADMIN_PRINTER=""
ENV CUPS_SERVER=""

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcairo2 libusb-1.0-0 cups cups-client \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
RUN uv sync --group dev

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "python", "-m", "printer_app", "serve", "--host", "0.0.0.0", "--port", "8080"]
