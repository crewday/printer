# Printer Calibration

Thermal printers vary by model, paper, power supply, age, and firmware settings. Calibrate each printer profile before relying on it for daily task receipts.

All calibration commands must run inside the Docker container. Use `docker compose run` as shown below, or use the container's authenticated web UI once implemented.

## Goal

Find the fastest print settings that still produce dark, readable text without excessive striping.

The relevant config values are:

```yaml
printer:
  print_density: 8
  print_speed: 6
```

For Epson ESC/POS printers, density `0` is standard, `1` through `127` request stronger density, and `128` through `255` request paler density. The printer may clamp the effective value internally.

Speed values are model-dependent. For the tested Epson TM-T20II, `1` is slowest and `17` is fastest, with `0` meaning the printer's configured default.

## Quick Sweep

Start with a few broad combinations. Print the black test for each one and write the density/speed on the paper if needed.

```sh
docker compose run --rm printer uv run python -m printer_app black-test --density 4 --speed 12 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 6 --speed 9 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 6 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 10 --speed 4 --config /config/printer.yaml
```

Pick the first setting that looks clearly dark enough. Prefer the faster setting when two settings look similar.

## Refine Density

Keep the chosen speed fixed and test density around the best quick-sweep result.

Example, if speed `6` looked best:

```sh
docker compose run --rm printer uv run python -m printer_app black-test --density 6 --speed 6 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 6 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 10 --speed 6 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 12 --speed 6 --config /config/printer.yaml
```

Stop increasing density when the output no longer gets meaningfully darker.

## Refine Speed

Keep the chosen density fixed and test speed around the best quick-sweep result.

Example, if density `8` looked best:

```sh
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 4 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 6 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 8 --config /config/printer.yaml
docker compose run --rm printer uv run python -m printer_app black-test --density 8 --speed 10 --config /config/printer.yaml
```

Choose the fastest speed that remains readable and dark enough.

## Confirm With A Real Receipt

After choosing settings, update `config/printer.yaml`, then print a normal task receipt:

```sh
docker compose run --rm printer uv run python -m printer_app print-test --config /config/printer.yaml
```

Judge the final receipt by worker name readability, task readability, and whether separators/logos distract from the task list.

The web UI should eventually perform the same steps and persist the selected values directly into the YAML config file.

## Notes

- Large solid black blocks are a worst-case thermal load and may show striping even when normal receipts look good.
- If dense blocks stripe but text is readable, avoid large filled logos and use outline or sparse high-contrast graphics.
- Changing paper rolls can change the best settings.
- If even narrow black blocks are striped, clean the print head and verify the power supply before increasing density further.
