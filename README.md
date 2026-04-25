# Crewday Thermal Printer

Docker-hosted Python service for printing configured worker task lists from `../crewday` to a thermal receipt printer.

The first slice is a containerized ESC/POS probe that can dry-run render a sample receipt or send it to a network printer.

Printer profiles live in `src/printer_app/profiles/*.yaml`. A profile declares preset columns, cut behavior, supported code pages, image/logo support, and whether density/speed ESC/POS commands should be sent. Add a printer preset by dropping another YAML file in that folder.

## Receipt Templates

Receipts use a YAML `receipt_template` section. Existing configs without this section keep the built-in default layout. The default is equivalent to the current receipt: logo, worker/date heading, printed timestamp, separator, task list, separator, footer logo, and a final blank line.

Template text values use Jinja variables such as `brand`, `worker_name`, `display_date`, `display_datetime`, `source_label`, and `task_count`.

```yaml
receipt_template:
  sections:
    - type: text
      value: "{{ worker_name }} - {{ display_date }}"
      align: center
      font: b
      width: 2
      height: 2
      bold: true
    - type: separator
    - type: tasks
    - type: blank
```

Supported section types are `logo`, `text`, `separator`, `tasks`, and `blank`. Open the password-protected web UI's Composer pane to drag blocks onto the receipt and persist the result back to YAML. The `tasks` section keeps the standard compact task rendering with metadata and checklist items.

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

Print all configured workers through the REST API:

```sh
curl -u admin:admin -X POST http://127.0.0.1:8087/api/receipts/print
```

Print selected workers:

```sh
curl -u admin:admin \
  -H 'Content-Type: application/json' \
  -d '{"workers":["Vincent"]}' \
  http://127.0.0.1:8087/api/receipts/print
```

Run tests, linting, and formatting through uv inside Docker:

```sh
docker compose run --rm printer uv run --group dev pytest
docker compose run --rm printer uv run --group dev ruff check .
docker compose run --rm printer uv run --group dev ruff format .
```
