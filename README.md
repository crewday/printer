# Crewday Thermal Printer

![Printer console UI](docs/assets/printer-console.png)

Docker-hosted Python service for printing enabled Crewday workers' task lists to a thermal receipt printer.

Pre-built images are published to [ghcr.io/crewday/printer](https://github.com/crewday/printer/pkgs/container/printer). Pull with:

```sh
docker pull ghcr.io/crewday/printer:latest
```

The first slice is a containerized ESC/POS probe that can dry-run render a sample receipt or send it to a printer. Three transport backends are supported:

| Type | Config `type` | Connection |
|---|---|---|
| Network (TCP) | `network_escpos` | Raw TCP socket to `host:port` |
| USB | `usb_escpos` | Direct USB via vendor/product ID |
| CUPS | `cups_escpos` | Raw ESC/POS through the CUPS `lp` command |

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

If neither `PRINTER_UI_PASSWORD` nor a YAML password hash is configured, the UI is unprotected.

Print all enabled workers through the REST API:

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

## Printer Configuration

Each printer in `config/printer.yaml` has a `type` field that selects the transport backend. Common fields like `profile`, `paper_columns`, and `code_page` are shared across all types.

### Network printer (`network_escpos`)

```yaml
printers:
  - name: Network
    type: network_escpos
    host: 192.168.20.15
    port: 9100
    timeout_seconds: 5
    profile: epson_tm_t20ii
    paper_columns: 48
    code_page: cp1252
    cut: true
```

### USB printer (`usb_escpos`)

```yaml
printers:
  - name: USB
    type: usb_escpos
    usb_vendor_id: 0x04b8
    usb_product_id: 0x0e15
    profile: epson_tm_t20ii
    paper_columns: 48
    code_page: cp1252
    cut: true
```

Use `lsusb` on the host to discover vendor and product IDs. For Docker, pass the USB bus with `--device /dev/bus/usb` or add `devices: ["/dev/bus/usb:/dev/bus/usb"]` in docker-compose.

### CUPS printer (`cups_escpos`)

```yaml
printers:
  - name: CUPS
    type: cups_escpos
    cups_printer_name: TM-T20II
    timeout_seconds: 10
    profile: epson_tm_t20ii
    paper_columns: 48
    code_page: cp1252
    cut: true
```

The printer must be configured as a raw queue in CUPS. There are two ways to provide CUPS to the container:

#### Option A: Use the host's CUPS daemon

Mount the CUPS socket and point the container client at it:

```sh
docker compose run --rm -v /var/run/cups/cups.sock:/var/run/cups/cups.sock \
  -e CUPS_SERVER=/var/run/cups/cups.sock printer uv run python -m printer_app print-test --config /config/printer.yaml
```

#### Option B: Run CUPS inside the container

Set `CUPS_ENABLED=true` to start the CUPS daemon automatically on container startup. Use `CUPS_LPADMIN_*` variables to auto-configure a printer queue, or mount a custom `/etc/cups` for full control.

```sh
CUPS_ENABLED=true \
CUPS_LPADMIN_NAME=TM-T20II \
CUPS_LPADMIN_PRINTER="socket://192.168.20.15:9100" \
docker compose up dev
```

| Variable | Default | Purpose |
|---|---|---|
| `CUPS_ENABLED` | `false` | Start the CUPS daemon inside the container |
| `CUPS_LPADMIN_NAME` | _(empty)_ | Queue name passed to `lpadmin -p` |
| `CUPS_LPADMIN_DESC` | _(empty)_ | Queue description passed to `lpadmin -D` |
| `CUPS_LPADMIN_PRINTER` | _(empty)_ | Device URI passed to `lpadmin -v` (e.g. `socket://host:port`, `usb://Vendor/Model`) |
| `CUPS_SERVER` | _(empty)_ | Override the CUPS server address for the `lp` / `lpstat` client commands |

To persist CUPS configuration across container restarts, mount a named volume at `/etc/cups`:

```yaml
volumes:
  - cups-config:/etc/cups
```
