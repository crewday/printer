from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from printer_app import escpos
from printer_app.auth import configured_password_hash, hash_password, verify_password
from printer_app.config import (
    config_path_from_env,
    config_to_raw,
    default_receipt_template,
    load_config,
    parse_receipt_template,
    write_raw_config,
)
from printer_app.cron import cron_matches
from printer_app.models import AppConfig, PrinterProfile, ReceiptTemplateConfig
from printer_app.profiles import get_profile, load_profiles
from printer_app.renderer import (
    render_black_test,
    render_calibration_sweep,
    render_font_test,
    render_receipt,
    render_receipt_preview,
)
from printer_app.secrets import secret_key_configured
from printer_app.task_source import build_task_source
from printer_app.transport import send_to_network_printer

RECENT_RESULTS: list[str] = []
SCHEDULER_TASK: asyncio.Task[None] | None = None


async def _start_scheduler() -> None:
    global SCHEDULER_TASK
    if SCHEDULER_TASK is None or SCHEDULER_TASK.done():
        SCHEDULER_TASK = asyncio.create_task(_schedule_loop())


async def _stop_scheduler() -> None:
    global SCHEDULER_TASK
    if SCHEDULER_TASK is None:
        return
    SCHEDULER_TASK.cancel()
    with suppress(asyncio.CancelledError):
        await SCHEDULER_TASK
    SCHEDULER_TASK = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await _start_scheduler()
    try:
        yield
    finally:
        await _stop_scheduler()


app = FastAPI(title="Crewday Printer", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).with_name("static")),
    name="static",
)
templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
security = HTTPBasic()


class PrintReceiptsRequest(BaseModel):
    workers: list[str] | None = None


class TemplateSectionPayload(BaseModel):
    type: str
    value: str | None = None
    align: str = "left"
    font: str = "a"
    width: int = 1
    height: int = 1
    bold: bool = False
    underline: int = 0
    scale: float = 1.0
    trailing_blank: bool = True


class TemplatePayload(BaseModel):
    sections: list[TemplateSectionPayload]


def require_auth(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> None:
    config = load_config(config_path_from_env())
    password_hash = configured_password_hash(config.ui.password_hash)
    if not password_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UI password is not configured. Set PRINTER_UI_PASSWORD.",
        )
    valid_user = credentials.username == config.ui.username
    valid_password = verify_password(credentials.password, password_hash)
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: Annotated[None, Depends(require_auth)]) -> HTMLResponse:
    config = load_config(config_path_from_env())
    preview = _preview_for_first_worker(config, config.receipt_template)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config": config,
            "profiles": load_profiles(),
            "selected_profile": get_profile(config.printer.profile),
            "profile_data": [_profile_data(profile) for profile in load_profiles()],
            "all_code_pages": sorted(escpos.CODE_PAGES),
            "preview": preview,
            "results": list(reversed(RECENT_RESULTS[-8:])),
            "template_data": _template_to_payload(config.receipt_template),
            "default_template_data": _template_to_payload(default_receipt_template()),
            "secret_key_configured": secret_key_configured(),
        },
    )


@app.post("/settings")
def save_settings(
    _: Annotated[None, Depends(require_auth)],
    host: Annotated[str, Form()],
    port: Annotated[int, Form()],
    timeout_seconds: Annotated[float, Form()],
    paper_columns: Annotated[int, Form()],
    profile: Annotated[str, Form()],
    code_page: Annotated[str, Form()],
    print_density: Annotated[int, Form()],
    print_speed: Annotated[int, Form()],
    print_schedule_cron: Annotated[str, Form()] = "",
    image_logo: Annotated[str | None, Form()] = None,
    supports_print_density: Annotated[str | None, Form()] = None,
    supports_print_speed: Annotated[str | None, Form()] = None,
    cut: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["printer"].update(
        {
            "host": host,
            "port": port,
            "timeout_seconds": timeout_seconds,
            "paper_columns": paper_columns,
            "profile": profile,
            "code_page": code_page,
            "image_logo": image_logo == "on",
            "supports_print_density": supports_print_density == "on",
            "supports_print_speed": supports_print_speed == "on",
            "print_density": print_density,
            "print_speed": print_speed,
            "cut": cut == "on",
        }
    )
    raw["print_schedule"] = {
        **(raw.get("print_schedule") or {}),
        "cron": print_schedule_cron.strip(),
    }
    write_raw_config(config_path_from_env(), raw)
    _record("Saved printer settings.")
    return RedirectResponse("/", status_code=303)


@app.post("/crewday")
def save_crewday(
    _: Annotated[None, Depends(require_auth)],
    source: Annotated[str, Form()],
    base_url: Annotated[str, Form()],
    workspace_slug: Annotated[str, Form()] = "",
    api_token: Annotated[str, Form()] = "",
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["crewday"] = {
        **(raw.get("crewday") or {}),
        "source": source,
        "base_url": base_url.strip().rstrip("/") or "http://crewday:8000",
        "workspace_slug": workspace_slug.strip() or None,
        "workspace_id": None,
    }
    if api_token.strip():
        raw["crewday"]["api_token"] = api_token.strip()
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Crewday settings were not saved: {exc}")
    else:
        _record("Saved Crewday connection settings.")
    return RedirectResponse("/", status_code=303)


@app.post("/access")
def save_access(
    _: Annotated[None, Depends(require_auth)],
    ui_username: Annotated[str, Form()],
    ui_password: Annotated[str, Form()] = "",
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["ui"] = {
        **(raw.get("ui") or {}),
        "username": ui_username.strip() or "admin",
    }
    if ui_password:
        raw["ui"]["password_hash"] = hash_password(ui_password)
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Access settings were not saved: {exc}")
    else:
        _record("Saved UI access settings.")
    return RedirectResponse("/", status_code=303)


@app.post("/workers")
async def save_workers(
    request: Request,
    _: Annotated[None, Depends(require_auth)],
) -> RedirectResponse:
    form = await request.form()
    worker_name = [str(value) for value in form.getlist("worker_name")]
    worker_timezone = [str(value) for value in form.getlist("worker_timezone")]
    worker_schedule = [str(value) for value in form.getlist("worker_schedule")]
    worker_crewday_user_id = [
        str(value) for value in form.getlist("worker_crewday_user_id")
    ]
    worker_tasks = [str(value) for value in form.getlist("worker_tasks")]
    raw_workers: list[dict[str, object]] = []
    enabled = {
        int(value)
        for value in (str(item) for item in form.getlist("worker_enabled"))
        if value.strip().lstrip("-").isdigit()
    }
    row_count = min(
        len(worker_name),
        len(worker_timezone),
        len(worker_schedule),
        len(worker_crewday_user_id),
        len(worker_tasks),
    )
    for index in range(row_count):
        name = worker_name[index].strip()
        if index not in enabled or not name:
            continue
        raw_workers.append(
            {
                "name": name,
                "schedule": worker_schedule[index].strip(),
                "crewday_user_id": worker_crewday_user_id[index].strip() or None,
                "timezone": worker_timezone[index].strip() or "Asia/Dubai",
                "tasks": [
                    line.strip()
                    for line in worker_tasks[index].splitlines()
                    if line.strip()
                ],
            }
        )

    if not raw_workers:
        _record("Worker settings were not saved: at least one worker is required.")
        return RedirectResponse("/", status_code=303)

    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["workers"] = raw_workers
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Worker settings were not saved: {exc}")
    else:
        _record(f"Saved {len(raw_workers)} worker configuration row(s).")
    return RedirectResponse("/", status_code=303)


@app.post("/dry-run")
def dry_run(_: Annotated[None, Depends(require_auth)]) -> Response:
    config = load_config(config_path_from_env())
    worker = config.workers[0]
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    payload = render_receipt(batch, config.printer, now, config.receipt_template)
    _record(f"Rendered {len(payload)} receipt bytes without printing.")
    return Response(payload, media_type="application/octet-stream")


@app.post("/print-test")
def print_test(_: Annotated[None, Depends(require_auth)]) -> RedirectResponse:
    config = load_config(config_path_from_env())
    try:
        result = _print_worker_receipts(config, [config.workers[0].name])
    except Exception as exc:
        _record(f"Print failed: {exc}")
    else:
        _record(
            f"Printed {result['bytes']} bytes "
            f"to {config.printer.host}:{config.printer.port}."
        )
    return RedirectResponse("/", status_code=303)


@app.post("/api/receipts/print")
def print_receipts_api(
    _: Annotated[None, Depends(require_auth)],
    request: Annotated[PrintReceiptsRequest | None, Body()] = None,
    workers: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    config = load_config(config_path_from_env())
    worker_names = _requested_worker_names(request, workers)
    try:
        result = _print_worker_receipts(config, worker_names)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _record(f"API print failed: {exc}")
        raise HTTPException(status_code=502, detail=f"print failed: {exc}") from exc

    names = ", ".join(result["workers"])
    _record(
        f"API printed {result['count']} receipt"
        f"{'' if result['count'] == 1 else 's'} for {names}."
    )
    return result


@app.post("/api/template/preview")
def template_preview(
    _: Annotated[None, Depends(require_auth)],
    payload: TemplatePayload,
) -> dict[str, object]:
    config = load_config(config_path_from_env())
    template = _payload_to_template(payload)
    preview = _preview_for_first_worker(config, template)
    return preview


@app.post("/api/template/save")
def template_save(
    _: Annotated[None, Depends(require_auth)],
    payload: TemplatePayload,
) -> dict[str, object]:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["receipt_template"] = {
        "sections": [_payload_section_to_raw(section) for section in payload.sections]
    }
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record(f"Saved receipt template ({len(payload.sections)} sections).")
    return {"status": "saved", "sections": len(payload.sections)}


@app.get("/api/template/default")
def template_default(
    _: Annotated[None, Depends(require_auth)],
) -> dict[str, object]:
    return _template_to_payload(default_receipt_template())


@app.post("/black-test")
def black_test(
    _: Annotated[None, Depends(require_auth)],
    density: Annotated[int, Form()],
    speed: Annotated[int, Form()],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    printer = replace(config.printer, print_density=density, print_speed=speed)
    payload = render_black_test(printer)
    try:
        send_to_network_printer(payload, printer)
    except Exception as exc:
        _record(f"Black test failed: {exc}")
    else:
        _record(f"Printed black test with density={density} speed={speed}.")
    return RedirectResponse("/", status_code=303)


@app.post("/font-test")
def font_test(_: Annotated[None, Depends(require_auth)]) -> RedirectResponse:
    config = load_config(config_path_from_env())
    payload = render_font_test(config.printer)
    try:
        send_to_network_printer(payload, config.printer)
    except Exception as exc:
        _record(f"Font test failed: {exc}")
    else:
        _record(
            f"Printed font test to {config.printer.host}:{config.printer.port} "
            f"with {config.printer.code_page}."
        )
    return RedirectResponse("/", status_code=303)


@app.post("/calibration/wizard")
def calibration_wizard(
    _: Annotated[None, Depends(require_auth)],
    phase: Annotated[str, Form()],
    density: Annotated[int, Form()],
    speed: Annotated[int, Form()],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    try:
        settings = _calibration_settings(phase, density, speed)
    except ValueError as exc:
        _record(f"Calibration wizard failed: {exc}")
        return RedirectResponse("/", status_code=303)

    printer = replace(config.printer, cut=True)
    payload = render_calibration_sweep(
        printer,
        tuple(settings),
        title=_calibration_title(phase),
    )
    try:
        send_to_network_printer(payload, printer)
    except Exception as exc:
        _record(f"Calibration wizard failed: {exc}")
    else:
        combos = ", ".join(f"d={d}/s={s}" for d, s in settings)
        _record(f"Printed compact calibration strip ({combos}); cut at end.")
    return RedirectResponse("/", status_code=303)


def _preview_for_first_worker(
    config: AppConfig,
    template: ReceiptTemplateConfig,
) -> dict[str, str | int]:
    worker = config.workers[0]
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    preview = render_receipt_preview(
        batch,
        config.printer,
        now,
        template,
    )
    encoded = b64encode(preview.png).decode("ascii")
    return {
        "src": f"data:image/png;base64,{encoded}",
        "width_dots": preview.width_dots,
        "height_dots": preview.height_dots,
    }


def _payload_to_template(payload: TemplatePayload) -> ReceiptTemplateConfig:
    raw = {"sections": [_payload_section_to_raw(s) for s in payload.sections]}
    try:
        return parse_receipt_template(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _payload_section_to_raw(section: TemplateSectionPayload) -> dict[str, object]:
    raw: dict[str, object] = {
        "type": section.type,
        "align": section.align,
        "font": section.font,
        "width": section.width,
        "height": section.height,
        "bold": section.bold,
        "underline": section.underline,
        "scale": section.scale,
        "trailing_blank": section.trailing_blank,
    }
    if section.value is not None:
        raw["value"] = section.value
    return raw


def _template_to_payload(template: ReceiptTemplateConfig) -> dict[str, object]:
    return {
        "sections": [
            {
                "type": section.type,
                "value": section.value,
                "align": section.align,
                "font": section.font,
                "width": section.width,
                "height": section.height,
                "bold": section.bold,
                "underline": section.underline,
                "scale": section.scale,
                "trailing_blank": section.trailing_blank,
            }
            for section in template.sections
        ]
    }


def _record(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    RECENT_RESULTS.append(f"{stamp} {message}")
    del RECENT_RESULTS[:-20]


async def _schedule_loop() -> None:
    last_run_key: tuple[str, str] | None = None
    while True:
        try:
            config = load_config(config_path_from_env())
            cron = config.print_schedule.cron
            now = datetime.now().replace(second=0, microsecond=0)
            run_key = (cron, now.isoformat())
            if cron and run_key != last_run_key and cron_matches(cron, now):
                result = _print_worker_receipts(config)
                last_run_key = run_key
                _record(
                    f"Scheduled print sent {result['count']} receipt"
                    f"{'' if result['count'] == 1 else 's'}."
                )
        except Exception as exc:
            _record(f"Scheduled print failed: {exc}")
        await asyncio.sleep(_seconds_until_next_minute())


def _seconds_until_next_minute() -> float:
    now = datetime.now()
    return max(60 - now.second - (now.microsecond / 1_000_000), 1)


def _requested_worker_names(
    request: PrintReceiptsRequest | None,
    query_workers: list[str] | None,
) -> list[str] | None:
    raw_workers = (
        query_workers
        if query_workers is not None
        else (request.workers if request else None)
    )
    if not raw_workers:
        return None

    names: list[str] = []
    for value in raw_workers:
        names.extend(part.strip() for part in value.split(",") if part.strip())
    return names or None


def _print_worker_receipts(
    config: AppConfig,
    worker_names: list[str] | None = None,
) -> dict[str, object]:
    workers = _select_workers(config, worker_names)
    task_source = build_task_source(config)
    printer = replace(config.printer, cut=True)
    payload = bytearray()
    for worker in workers:
        now = datetime.now(ZoneInfo(worker.timezone))
        batch = task_source.fetch_task_batch(worker, now=now)
        payload += render_receipt(batch, printer, now, config.receipt_template)

    send_to_network_printer(bytes(payload), printer)
    return {
        "status": "printed",
        "count": len(workers),
        "workers": [worker.name for worker in workers],
        "bytes": len(payload),
        "cut": True,
    }


def _select_workers(
    config: AppConfig,
    worker_names: list[str] | None,
):
    if worker_names is None:
        return list(config.workers)

    workers_by_name = {worker.name: worker for worker in config.workers}
    missing = [name for name in worker_names if name not in workers_by_name]
    if missing:
        raise ValueError(f"worker not found in config: {', '.join(missing)}")
    return [workers_by_name[name] for name in worker_names]


def _profile_data(profile: PrinterProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "name": profile.name,
        "paper_width": profile.paper_width,
        "cut_behavior": profile.cut_behavior,
        "code_pages": profile.code_pages,
        "image_logo": profile.image_logo,
        "supports_print_density": profile.supports_print_density,
        "supports_print_speed": profile.supports_print_speed,
        "paper_columns": profile.paper_columns,
        "print_density": profile.print_density,
        "print_speed": profile.print_speed,
        "cut": profile.cut,
    }


def _calibration_settings(
    phase: str,
    density: int,
    speed: int,
) -> list[tuple[int, int]]:
    if phase == "quick":
        return [(4, 12), (6, 9), (8, 6), (10, 4)]
    if phase == "refine_density":
        return [(value, speed) for value in _window(density, 2, 0, 255)]
    if phase == "refine_speed":
        return [(density, value) for value in _window(speed, 2, 0, 17)]
    raise ValueError(f"unknown calibration phase: {phase}")


def _window(center: int, step: int, minimum: int, maximum: int) -> list[int]:
    values = [
        center - step * 2,
        center - step,
        center,
        center + step,
        center + step * 2,
    ]
    return sorted({min(max(value, minimum), maximum) for value in values})


def _calibration_title(phase: str) -> str:
    titles = {
        "quick": "Calibration quick sweep",
        "refine_density": "Calibration density refine",
        "refine_speed": "Calibration speed refine",
    }
    return titles.get(phase, "Calibration sweep")
