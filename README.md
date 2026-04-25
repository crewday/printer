# Crewday Thermal Printer

Docker-hosted Python service for printing configured worker task lists from `../crewday` to a thermal receipt printer.

The first slice is a containerized ESC/POS probe that can dry-run render a sample receipt or send it to a network printer.

Printer profiles live in `src/printer_app/profiles/*.yaml`. A profile declares preset columns, cut behavior, supported code pages, image/logo support, and whether density/speed ESC/POS commands should be sent. Add a printer preset by dropping another YAML file in that folder.

## Commands

Build the image:

```sh
docker compose build
```

Render without printing:

```sh
docker compose run --rm printer uv run python -m printer_app print-test --dry-run --config /config/printer.yaml
```

Render a text preview:

```sh
docker compose run --rm printer uv run python -m printer_app preview --config /config/printer.yaml
```

Print to the configured printer:

```sh
docker compose run --rm printer uv run python -m printer_app print-test --config /config/printer.yaml
```

Calibrate printer darkness and speed:

```sh
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 6 --config /config/printer.yaml
```

See [docs/PRINTER_CALIBRATION.md](docs/PRINTER_CALIBRATION.md) for the full procedure.

All runtime, uv, test, calibration, and printer commands are intended to run inside Docker. Do not run the Python application or project toolchain directly on the host.

Run the authenticated setup UI:

```sh
PRINTER_UI_PASSWORD=change-me docker compose up dev
```

Then open <http://127.0.0.1:8087>.

Run tests, linting, and formatting through uv inside Docker:

```sh
docker compose run --rm printer uv run --group dev pytest
docker compose run --rm printer uv run --group dev ruff check .
docker compose run --rm printer uv run --group dev ruff format .
```
