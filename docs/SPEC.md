# Base Specification

## Goal

Build a Docker-hosted Python 3.14 service that periodically prints task lists for configured workers from `../crewday` on a thermal printer.

## Initial Scope

1. Load printer and Crewday roster selection from a bind-mounted config file.
2. Render a readable, attractive ESC/POS receipt containing:
   - simple Crewday logo/header
   - worker name
   - print timestamp
   - task list
3. Send the rendered receipt to a configured network ESC/POS printer.
4. Provide a dry-run mode that renders the receipt bytes without contacting a printer.
5. Run only inside Docker.
6. Provide a password-protected web UI for first-run setup, printer settings, and calibration.
7. Create a YAML config file on first run if none exists.

## Later Scope

- Support cron-like schedules per worker or worker group.
- Run as a long-lived scheduler process with code/config reload in development.
- Add printer profiles for model-specific paper width, cut behavior, code pages, and image/logo support.
- Add health checks and structured logs.
- Add tests for config loading, schedule selection, rendering, and printer transport.
- Add audit-friendly config history or backups before UI writes.

## Configuration Shape

Configuration is YAML. The service reads and writes this file directly. In Docker deployments it should normally live on a bind mount or named volume.

```yaml
ui:
  username: admin
  password_hash: null

printer:
  type: network_escpos
  profile: epson_tm_t20ii
  host: 192.168.20.15
  port: 9100
  timeout_seconds: 5
  paper_columns: 48
  print_density: 8
  print_speed: 6
  cut: true

timezone: Asia/Dubai

workers:
  - name: Vincent
    crewday_user_id: 01HX...
    enabled: true
    schedule: "0 8 * * *"
```

## First Run Behavior

- If the configured YAML file does not exist, the container creates it from defaults.
- Defaults should be usable but conservative:
  - network ESC/POS printer type
  - Epson TM-T20II profile
  - host from `PRINTER_HOST` env var when present, otherwise a placeholder
  - UI username/password from env vars when present
- If no UI password is configured, the local setup UI is unprotected. Set `PRINTER_UI_PASSWORD` or save a YAML password before exposing the container beyond a trusted local network.
- The config path must be configurable, defaulting to `/config/printer.yaml`.

## Docker Requirements

- Image uses Python 3.14.
- Dependencies are installed inside the image.
- Source and config can be bind-mounted for development.
- Compose exposes commands for:
  - dry-run rendering
  - printing a test receipt
  - future scheduler/dev reload mode
- Docker Compose should expose the web UI port.
- All calibration and printer tests documented for users must be run through `docker compose` or inside the running container.

## Printer Requirements

- The first backend is raw TCP ESC/POS over port `9100`.
- The backend must be configurable by host, port, timeout, paper width, and profile.
- ESC/POS profiles are YAML preset files under `src/printer_app/profiles/`.
- Profiles configure default paper columns, cut behavior, code pages, image/logo support, and print density/speed support.
- The active config may override profile defaults after selection.
- The app should fail clearly when the printer is unreachable.
- Real printing requires an explicit command such as `print-test`.

## Web UI Requirements

- The container exposes a small authenticated UI for operational setup.
- Authentication uses username/password configured through environment variables and/or YAML config.
- Environment variables should be preferred for secrets:
  - `PRINTER_UI_USERNAME`
  - `PRINTER_UI_PASSWORD`
- The YAML config may store non-secret UI preferences. If password storage in YAML is needed, store only a password hash, never plaintext.
- The UI allows the user to:
  - view current printer settings
  - edit printer host, port, timeout, paper columns, profile, density, speed, and cut behavior
  - save changes back to the YAML config file
  - create the YAML config file if it does not exist
  - run dry-run rendering
  - run calibration prints
  - run a normal test receipt
  - see recent command results and errors
- Config writes should be atomic:
  - write a temporary YAML file
  - validate it
  - replace the active config
- The UI should keep calibration fast:
  - offer a quick sweep of broad density/speed pairs
  - offer focused density refinement at a fixed speed
  - offer focused speed refinement at a fixed density
  - let users persist the selected values to YAML
- The UI should make clear that large solid black blocks are a worst-case thermal load and may stripe even when normal receipts look good.
