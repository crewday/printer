# Crewday Printer TODO

This is the working build list derived from `AGENTS.md`, `docs/SPEC.md`,
`docs/PRINTER_CALIBRATION.md`, and the sibling Crewday project.

## Confirmed Decisions

- Web UI: FastAPI + Jinja, served by the printer container.
- Receipt logo: import `../crewday/app/web/public/crewday-logo.svg` and
  rasterize it for ESC/POS printing.
- Physical printer tests: ask before sending real tickets to `192.168.20.15`.
- Crewday data: implement a mockable interface now; keep the HTTP integration
  shaped around Crewday's current `GET /api/v1/tasks` endpoint.
- Tooling: use `uv` inside Docker for dependency install, command execution,
  tests, linting, formatting, and virtual environment management.

## Specification Additions

- Runtime config has three explicit IO sections:
  - `crewday`: source type, base URL, token, workspace/user mapping, and mock
    task data.
  - `printer`: backend/profile/network settings.
  - `ui`: username and optional password hash; environment variables override
    secrets.
- The receipt renderer accepts a neutral `TaskBatch` object. It does not know
  whether tasks came from mock YAML or Crewday HTTP.
- The Crewday HTTP source will eventually call:
  - `GET /api/v1/tasks?assignee_user_id=...&scheduled_for_utc_gte=...&scheduled_for_utc_lt=...`
  - optional state filters for `pending`/`in_progress`/`scheduled`.
- The mock source remains first-class so dry-run rendering and UI preview never
  require Crewday or a printer.
- UI config writes must be atomic and validated before replace.
- Real printing is exposed only through intentional commands/buttons.

## Build Tasks

### Foundation

- [x] Preserve Docker-only runtime/tooling rule.
- [x] Import Crewday logo into this project.
- [x] Split the current single CLI module into small modules:
  - [x] config load/default/write/validation
  - [x] task source interface and implementations
  - [x] receipt renderer
  - [x] ESC/POS helpers
  - [x] printer transport
  - [x] CLI entrypoint
  - [x] web UI entrypoint
- [x] Add tests for config and rendering using Docker.

### Config

- [x] Create initial YAML when missing.
- [x] Read config path from `PRINTER_CONFIG`, defaulting to `/config/printer.yaml`.
- [x] Prefer env secrets:
  - `PRINTER_UI_USERNAME`
  - `PRINTER_UI_PASSWORD`
  - `CREWDAY_API_TOKEN`
- [x] Validate printer density/speed/port/timeout/paper columns.
- [x] Keep printer model/address configurable.
- [x] Save YAML atomically from UI.

### Data Source

- [x] Define `TaskSource.fetch_task_batch(worker, now)`.
- [x] Implement `MockTaskSource` from YAML worker task entries.
- [x] Implement `CrewdayHttpTaskSource` as a not-yet-default integration path.
- [x] Normalize Crewday and mock tasks into common task items:
  - title
  - property/name
  - area
  - start time/window
  - duration
  - priority
  - evidence requirement
  - checklist

### Receipt Design

- [x] Rasterize Crewday SVG logo to monochrome ESC/POS image bytes.
- [x] Use Crewday's design language on thermal paper:
  - warm ledger-like hierarchy translated to black/white
  - strong worker/date header
  - compact task cards
  - clear metadata rows for property, area, time, duration, priority
  - checklist items rendered beneath each task
- [x] Include worker name, print date/time, and task content on every ticket.
- [x] Keep output compact for 48-column paper.
- [x] Avoid dense black logo blocks that could stripe.
- [x] Preserve dry-run byte rendering.

### Printer Backend

- [x] Keep raw TCP ESC/POS backend configurable.
- [x] Fail clearly when network printer is unreachable.
- [x] Keep cut behavior configurable.
- [x] Keep calibration commands visible and intentional.

### Web UI

- [x] Add authenticated UI.
- [x] Fail closed when no password/env secret is configured.
- [x] View/edit printer settings.
- [x] Run dry-run preview.
- [x] Trigger calibration tests.
- [x] Trigger normal test receipt only after explicit action.
- [x] Show recent command results/errors.
- [ ] Persist selected calibration values to YAML.

### Scheduler

- [ ] Add cron-like schedule runner after the manual/UI path is solid.
- [ ] Support dev auto-reload for code/config changes.
- [ ] Add structured logs and health checks.

### Verification

- [ ] Run tests inside Docker.
- [ ] Run dry-run render inside Docker.
- [ ] Ask before any real print.
