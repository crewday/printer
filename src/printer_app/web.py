from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
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
    default_cups_printer_raw,
    default_network_printer_raw,
    default_receipt_template,
    default_usb_printer_raw,
    load_config,
    parse_receipt_template,
    write_raw_config,
)
from printer_app.cron import cron_matches
from printer_app.models import (
    AppConfig,
    CrewdayWorker,
    PrinterConfig,
    PrinterProfile,
    ReceiptTemplateConfig,
    TaskBatch,
    WorkerConfig,
)
from printer_app.profiles import get_profile, load_profiles
from printer_app.renderer import (
    render_black_test,
    render_calibration_sweep,
    render_font_test,
    render_receipt,
    render_receipt_preview,
)
from printer_app.secrets import secret_key_configured
from printer_app.task_source import build_task_source, fetch_crewday_workers
from printer_app.transport import (
    SUPPORTED_TYPES,
    printer_connection_label,
    send_to_printer,
)

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
security = HTTPBasic(auto_error=False)


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
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
) -> None:
    config = load_config(config_path_from_env())
    password_hash = configured_password_hash(config.ui.password_hash)
    if not password_hash:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="credentials required",
            headers={"WWW-Authenticate": "Basic"},
        )
    valid_user = credentials.username == config.ui.username
    valid_password = verify_password(credentials.password, password_hash)
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _resolve_printer(config: AppConfig, name: str) -> PrinterConfig:
    printer = config.printer_by_name(name)
    if printer is None:
        raise HTTPException(status_code=404, detail=f"printer not found: {name}")
    return printer


def _printer_url(name: str, *suffix: str) -> str:
    path = "/printer/" + quote(name, safe="")
    if suffix:
        path += "/" + "/".join(suffix)
    return path


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: Annotated[None, Depends(require_auth)]) -> HTMLResponse:
    config = load_config(config_path_from_env())
    crewday_workers, crewday_error = _load_worker_roster(config)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config": config,
            "profiles": load_profiles(),
            "printer_types": SUPPORTED_TYPES,
            "crewday_workers": crewday_workers,
            "crewday_worker_error": crewday_error,
            "results": list(reversed(RECENT_RESULTS[-8:])),
            "template_data": _template_to_payload(config.receipt_template),
            "default_template_data": _template_to_payload(default_receipt_template()),
            "secret_key_configured": secret_key_configured(),
        },
    )


@app.post("/settings")
def save_schedule(
    _: Annotated[None, Depends(require_auth)],
    print_schedule_cron: Annotated[str, Form()] = "",
    timezone: Annotated[str, Form()] = "Asia/Dubai",
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    raw["print_schedule"] = {
        **(raw.get("print_schedule") or {}),
        "cron": print_schedule_cron.strip(),
    }
    raw["timezone"] = timezone.strip() or "Asia/Dubai"
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Schedule settings were not saved: {exc}")
    else:
        _record("Saved schedule settings.")
    return RedirectResponse("/", status_code=303)


@app.post("/printers/add")
def add_printer(
    _: Annotated[None, Depends(require_auth)],
    name: Annotated[str, Form()],
    profile: Annotated[str, Form()],
    printer_type: Annotated[str, Form()] = "network_escpos",
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    raw = config_to_raw(config)
    printer_name = name.strip()
    if not printer_name:
        _record("Printer name cannot be empty.")
        return RedirectResponse("/", status_code=303)
    existing_names = {p.get("name") for p in raw.get("printers", [])}
    if printer_name in existing_names:
        _record(f"Printer name already exists: {printer_name!r}")
        return RedirectResponse("/", status_code=303)

    factories = {
        "network_escpos": default_network_printer_raw,
        "usb_escpos": default_usb_printer_raw,
        "cups_escpos": default_cups_printer_raw,
    }
    factory = factories.get(printer_type, default_network_printer_raw)
    raw["printers"].append(factory(printer_name))
    raw["printers"][-1]["profile"] = profile
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Printer was not added: {exc}")
    else:
        _record(f"Added printer {printer_name!r}.")
    return RedirectResponse(_printer_url(printer_name), status_code=303)


@app.post("/printers/{name}/delete")
def delete_printer(
    name: str,
    _: Annotated[None, Depends(require_auth)],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    if len(config.printers) <= 1:
        _record("Cannot delete the last printer.")
        return RedirectResponse("/", status_code=303)
    raw = config_to_raw(config)
    raw["printers"] = [p for p in raw["printers"] if p.get("name") != name]
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Printer was not deleted: {exc}")
    else:
        _record(f"Deleted printer {name!r}.")
    return RedirectResponse("/", status_code=303)


@app.get("/printer/{name}", response_class=HTMLResponse)
def printer_detail(
    request: Request,
    name: str,
    _: Annotated[None, Depends(require_auth)],
) -> HTMLResponse:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    preview = _preview_for_first_worker(config, config.receipt_template, printer)
    selected_profile = get_profile(printer.profile)
    return templates.TemplateResponse(
        request,
        "printer.html",
        {
            "config": config,
            "printer": printer,
            "profiles": load_profiles(),
            "selected_profile": selected_profile,
            "profile_data": [_profile_data(p) for p in load_profiles()],
            "all_code_pages": sorted(escpos.CODE_PAGES),
            "preview": preview,
            "preview_worker": _first_enabled_worker(config, allow_disabled=True),
            "results": list(reversed(RECENT_RESULTS[-8:])),
        },
    )


@app.post("/printer/{name}/settings")
def save_printer_settings(
    name: str,
    _: Annotated[None, Depends(require_auth)],
    host: Annotated[str, Form()] = "",
    port: Annotated[int, Form()] = 0,
    timeout_seconds: Annotated[float, Form()] = 5.0,
    paper_columns: Annotated[int, Form()] = 48,
    profile: Annotated[str, Form()] = "epson_tm_t20ii",
    code_page: Annotated[str, Form()] = "cp1252",
    print_density: Annotated[int, Form()] = 8,
    print_speed: Annotated[int, Form()] = 6,
    image_logo: Annotated[str | None, Form()] = None,
    supports_print_density: Annotated[str | None, Form()] = None,
    supports_print_speed: Annotated[str | None, Form()] = None,
    cut: Annotated[str | None, Form()] = None,
    usb_vendor_id: Annotated[str | None, Form()] = None,
    usb_product_id: Annotated[str | None, Form()] = None,
    cups_printer_name: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    _resolve_printer(config, name)
    raw = config_to_raw(config)
    for entry in raw["printers"]:
        if entry.get("name") == name:
            entry.update(
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
            if usb_vendor_id is not None:
                entry["usb_vendor_id"] = usb_vendor_id
            if usb_product_id is not None:
                entry["usb_product_id"] = usb_product_id
            if cups_printer_name is not None:
                entry["cups_printer_name"] = cups_printer_name
            break
    try:
        write_raw_config(config_path_from_env(), raw)
    except ValueError as exc:
        _record(f"Printer settings were not saved: {exc}")
    else:
        _record(f"Saved settings for printer {name!r}.")
    return RedirectResponse(_printer_url(name), status_code=303)


@app.post("/printer/{name}/dry-run")
def printer_dry_run(
    name: str,
    _: Annotated[None, Depends(require_auth)],
) -> Response:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    worker = _first_enabled_worker(config)
    now = datetime.now(ZoneInfo(config.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    payload = render_receipt(batch, printer, now, config.receipt_template)
    _record(f"Rendered {len(payload)} receipt bytes for {name!r} without printing.")
    return Response(payload, media_type="application/octet-stream")


@app.post("/printer/{name}/print-test")
def printer_print_test(
    name: str,
    _: Annotated[None, Depends(require_auth)],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    try:
        result = _print_worker_receipts(
            config, [_first_enabled_worker(config).name], printer
        )
    except Exception as exc:
        _record(f"Print test failed for {name!r}: {exc}")
    else:
        _record(
            f"Printed {result['bytes']} bytes to {printer_connection_label(printer)}."
        )
    return RedirectResponse(_printer_url(name), status_code=303)


@app.post("/printer/{name}/black-test")
def printer_black_test(
    name: str,
    _: Annotated[None, Depends(require_auth)],
    density: Annotated[int, Form()],
    speed: Annotated[int, Form()],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    printer = replace(printer, print_density=density, print_speed=speed)
    payload = render_black_test(printer)
    try:
        send_to_printer(payload, printer)
    except Exception as exc:
        _record(f"Black test failed for {name!r}: {exc}")
    else:
        _record(f"Printed black test on {name!r} with density={density} speed={speed}.")
    return RedirectResponse(_printer_url(name), status_code=303)


@app.post("/printer/{name}/font-test")
def printer_font_test(
    name: str,
    _: Annotated[None, Depends(require_auth)],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    payload = render_font_test(printer)
    try:
        send_to_printer(payload, printer)
    except Exception as exc:
        _record(f"Font test failed for {name!r}: {exc}")
    else:
        _record(
            f"Printed font test to {printer_connection_label(printer)} "
            f"({name!r}) with {printer.code_page}."
        )
    return RedirectResponse(_printer_url(name), status_code=303)


@app.post("/printer/{name}/calibration/wizard")
def printer_calibration_wizard(
    name: str,
    _: Annotated[None, Depends(require_auth)],
    phase: Annotated[str, Form()],
    density: Annotated[int, Form()],
    speed: Annotated[int, Form()],
) -> RedirectResponse:
    config = load_config(config_path_from_env())
    printer = _resolve_printer(config, name)
    try:
        settings = _calibration_settings(phase, density, speed)
    except ValueError as exc:
        _record(f"Calibration wizard failed for {name!r}: {exc}")
        return RedirectResponse(_printer_url(name), status_code=303)

    printer = replace(printer, cut=True)
    payload = render_calibration_sweep(
        printer,
        tuple(settings),
        title=_calibration_title(phase),
    )
    try:
        send_to_printer(payload, printer)
    except Exception as exc:
        _record(f"Calibration wizard failed for {name!r}: {exc}")
    else:
        combos = ", ".join(f"d={d}/s={s}" for d, s in settings)
        _record(f"Printed calibration strip on {name!r} ({combos}); cut at end.")
    return RedirectResponse(_printer_url(name), status_code=303)


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
    worker_schedule = [str(value) for value in form.getlist("worker_schedule")]
    worker_crewday_user_id = [
        str(value) for value in form.getlist("worker_crewday_user_id")
    ]
    worker_printer = [str(value) for value in form.getlist("worker_printer")]
    raw_workers: list[dict[str, object]] = []
    enabled = {
        int(value)
        for value in (str(item) for item in form.getlist("worker_enabled"))
        if value.strip().lstrip("-").isdigit()
    }
    row_count = min(
        len(worker_name),
        len(worker_schedule),
        len(worker_crewday_user_id),
        len(worker_printer),
    )
    for index in range(row_count):
        w_name = worker_name[index].strip()
        crewday_user_id = worker_crewday_user_id[index].strip()
        if not w_name or not crewday_user_id:
            continue
        raw_workers.append(
            {
                "name": w_name,
                "schedule": worker_schedule[index].strip(),
                "crewday_user_id": crewday_user_id,
                "enabled": index in enabled,
                "printer": worker_printer[index].strip(),
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
    printer = config.first_printer()
    preview = _preview_for_first_worker(config, template, printer)
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


def _preview_for_first_worker(
    config: AppConfig,
    template: ReceiptTemplateConfig,
    printer: PrinterConfig,
) -> dict[str, str | int]:
    worker = _first_enabled_worker(config, allow_disabled=True)
    now = datetime.now(ZoneInfo(config.timezone))
    try:
        batch = build_task_source(config).fetch_task_batch(worker, now=now)
    except Exception:
        batch = TaskBatch(
            worker_name=worker.name,
            source_label="Preview unavailable",
            generated_at=now,
            tasks=(),
        )
    preview = render_receipt_preview(
        batch,
        printer,
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
    last_run_key: tuple[tuple[str, str], ...] | None = None
    while True:
        try:
            config = load_config(config_path_from_env())
            now = datetime.now().replace(second=0, microsecond=0)
            due_workers = _scheduled_worker_names(config, now)
            run_key = tuple((name, now.isoformat()) for name in due_workers)
            if due_workers and run_key != last_run_key:
                result = _print_worker_receipts(config, due_workers)
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


def _scheduled_worker_names(config: AppConfig, now: datetime) -> list[str]:
    names: list[str] = []
    for worker in config.workers:
        if not worker.enabled:
            continue
        cron = worker.schedule or config.print_schedule.cron
        if cron and cron_matches(cron, now):
            names.append(worker.name)
    return names


def _print_worker_receipts(
    config: AppConfig,
    worker_names: list[str] | None = None,
    target_printer: PrinterConfig | None = None,
) -> dict[str, object]:
    workers = _select_workers(config, worker_names)
    task_source = build_task_source(config)
    total_bytes = 0
    printed_workers: list[str] = []

    workers_by_printer = _group_workers_by_printer(config, workers, target_printer)
    for printer, printer_workers in workers_by_printer:
        printer_config = replace(printer, cut=True)
        payload = bytearray()
        for worker in printer_workers:
            now = datetime.now(ZoneInfo(config.timezone))
            batch = task_source.fetch_task_batch(worker, now=now)
            payload += render_receipt(
                batch, printer_config, now, config.receipt_template
            )
        if payload:
            send_to_printer(bytes(payload), printer_config)
            total_bytes += len(payload)
            printed_workers.extend(w.name for w in printer_workers)

    if not printed_workers:
        raise ValueError("no workers are enabled in config")

    return {
        "status": "printed",
        "count": len(printed_workers),
        "workers": printed_workers,
        "bytes": total_bytes,
        "cut": True,
    }


def _group_workers_by_printer(
    config: AppConfig,
    workers: list[WorkerConfig],
    target_printer: PrinterConfig | None = None,
) -> list[tuple[PrinterConfig, list[WorkerConfig]]]:
    if target_printer is not None:
        return [(target_printer, workers)]
    printer_map: dict[str, list[WorkerConfig]] = {}
    for worker in workers:
        printer = config.printer_for_worker(worker)
        printer_map.setdefault(printer.name, []).append(worker)
    result: list[tuple[PrinterConfig, list[WorkerConfig]]] = []
    for printer in config.printers:
        if printer.name in printer_map:
            result.append((printer, printer_map[printer.name]))
    return result


def _select_workers(
    config: AppConfig,
    worker_names: list[str] | None,
) -> list[WorkerConfig]:
    if worker_names is None:
        return [worker for worker in config.workers if worker.enabled]

    workers_by_name = {worker.name: worker for worker in config.workers}
    missing = [name for name in worker_names if name not in workers_by_name]
    if missing:
        raise ValueError(f"worker not found in config: {', '.join(missing)}")
    selected = [workers_by_name[name] for name in worker_names]
    disabled = [worker.name for worker in selected if not worker.enabled]
    if disabled:
        raise ValueError(f"worker is disabled in config: {', '.join(disabled)}")
    return selected


def _first_enabled_worker(
    config: AppConfig, *, allow_disabled: bool = False
) -> WorkerConfig:
    for worker in config.workers:
        if worker.enabled:
            return worker
    if allow_disabled and config.workers:
        return config.workers[0]
    raise ValueError("no workers are enabled in config")


def _load_worker_roster(
    config: AppConfig,
) -> tuple[list[dict[str, object]], str | None]:
    try:
        crewday_workers = fetch_crewday_workers(config)
    except Exception as exc:
        crewday_workers = ()
        error = str(exc)
    else:
        error = None

    if not crewday_workers:
        crewday_workers = tuple(
            CrewdayWorker(
                user_id=worker.crewday_user_id or worker.name,
                name=worker.name,
            )
            for worker in config.workers
        )

    configured = {
        worker.crewday_user_id: worker
        for worker in config.workers
        if worker.crewday_user_id
    }
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for crewday_worker in crewday_workers:
        if not crewday_worker.user_id:
            continue
        configured_worker = configured.get(crewday_worker.user_id)
        seen.add(crewday_worker.user_id)
        rows.append(
            {
                "user_id": crewday_worker.user_id,
                "name": crewday_worker.name,
                "enabled": configured_worker.enabled if configured_worker else False,
                "schedule": configured_worker.schedule if configured_worker else "",
                "printer": configured_worker.printer if configured_worker else "",
            }
        )

    for worker in config.workers:
        if worker.crewday_user_id and worker.crewday_user_id in seen:
            continue
        rows.append(
            {
                "user_id": worker.crewday_user_id or "",
                "name": worker.name,
                "enabled": worker.enabled,
                "schedule": worker.schedule,
                "printer": worker.printer,
            }
        )
    return rows, error


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
