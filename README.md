# Crewday Thermal Printer

Docker-hosted Python service for printing configured worker task lists from `../crewday` to a thermal receipt printer.

The first slice is a containerized ESC/POS probe that can dry-run render a sample receipt or send it to a network printer.

## Commands

Build the image:

```sh
docker compose build
```

Render without printing:

```sh
docker compose run --rm printer python -m printer_app print-test --dry-run --config /config/printer.yaml
```

Print to the configured printer:

```sh
docker compose run --rm printer python -m printer_app print-test --config /config/printer.yaml
```

Calibrate printer darkness and speed:

```sh
docker compose run --rm printer python -m printer_app black-test --density 8 --speed 6 --config /config/printer.yaml
```

See [docs/PRINTER_CALIBRATION.md](docs/PRINTER_CALIBRATION.md) for the full procedure.

All runtime, test, calibration, and printer commands are intended to run inside Docker. Do not run the Python application directly on the host.

Development watch mode placeholder:

```sh
docker compose up dev
```
