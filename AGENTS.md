# Agent Instructions

This repository builds a Docker-hosted service that prints worker task lists from the sibling `../crewday` project to thermal receipt printers.

## Hard Rules

- Do not run project runtime or toolchain commands directly on the host.
- Use Docker for anything that installs or runs project dependencies, including Python, uv/pip, CUPS, printer drivers, test runners, linters, app servers, schedulers, calibration commands, and printer commands.
- Calibration, printer tests, config generation, and UI/server commands must run inside Docker.
- `docker-compose.yml` is a local development entrypoint only and is not used for real deployments.
- The Docker Compose UI login is intentionally fixed at `admin` / `admin` for local development.
- Normal repository and shell operations may run on the host when they do not install or execute project dependencies. Examples: `find`, `rg`, `sed`, `git status`, `git diff`, `git commit`, and `git push`.
- Host-side editing is allowed.
- Target Python is Python 3.14.
- Keep printer settings configurable. Do not hard-code a single printer model or address into application logic.
- Treat real printer output as an integration side effect. Make dry-run rendering available for development.

## Product Direction

- The service periodically prints configured workers' task lists on a cron-like schedule.
- The default tested printer is an Epson TM-T20II reachable at `192.168.20.15`, but the code must support other ESC/POS-compatible printers and future printer backends.
- Printed output should be attractive, compact, and readable on thermal paper.
- Every printed task list must include the worker name, print date/time, and task content.
- Configuration should live outside the image and be bind-mounted during development and deployment.
- Configuration must be YAML.
- The service should be able to create an initial YAML config when the configured file does not exist.
- Development containers should support auto reload when code or config changes.
- A small password-protected web UI should be exposed by the container for setup, printer calibration, and config changes.
- UI credentials must be configurable through environment variables and/or YAML config.

## Engineering Direction

- Keep IO boundaries explicit:
  - crewday data source
  - schedule runner
  - authenticated setup/calibration UI
  - receipt renderer
  - printer transport/backend
- Prefer small, testable modules over a single script.
- Keep an offline path for rendering bytes/text without touching a real printer.
- Add integration commands that make network printer tests intentional and visible.
- Avoid adding host-specific assumptions; Docker Compose should be the standard local entrypoint.
