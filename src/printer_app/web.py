from __future__ import annotations

from base64 import b64encode
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from printer_app import escpos
from printer_app.auth import configured_password_hash, verify_password
from printer_app.config import (
    config_path_from_env,
    config_to_raw,
    load_config,
    write_raw_config,
)
from printer_app.models import AppConfig, PrinterProfile
from printer_app.profiles import get_profile, load_profiles
from printer_app.renderer import (
    render_black_test,
    render_receipt,
    render_receipt_preview,
)
from printer_app.task_source import build_task_source
from printer_app.transport import send_to_network_printer

app = FastAPI(title="Crewday Printer")
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).with_name("static")),
    name="static",
)
templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
security = HTTPBasic()
RECENT_RESULTS: list[str] = []


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
    preview = _preview_for_first_worker(config)
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
    write_raw_config(config_path_from_env(), raw)
    _record("Saved printer settings.")
    return RedirectResponse("/", status_code=303)


@app.post("/dry-run")
def dry_run(_: Annotated[None, Depends(require_auth)]) -> Response:
    config = load_config(config_path_from_env())
    worker = config.workers[0]
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    payload = render_receipt(batch, config.printer, now)
    _record(f"Rendered {len(payload)} receipt bytes without printing.")
    return Response(payload, media_type="application/octet-stream")


@app.post("/print-test")
def print_test(_: Annotated[None, Depends(require_auth)]) -> RedirectResponse:
    config = load_config(config_path_from_env())
    worker = config.workers[0]
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    payload = render_receipt(batch, config.printer, now)
    try:
        send_to_network_printer(payload, config.printer)
    except Exception as exc:
        _record(f"Print failed: {exc}")
    else:
        _record(
            f"Printed {len(payload)} bytes "
            f"to {config.printer.host}:{config.printer.port}."
        )
    return RedirectResponse("/", status_code=303)


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


def _preview_for_first_worker(config: AppConfig) -> dict[str, str | int]:
    worker = config.workers[0]
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    preview = render_receipt_preview(batch, config.printer, now)
    encoded = b64encode(preview.png).decode("ascii")
    return {
        "src": f"data:image/png;base64,{encoded}",
        "width_dots": preview.width_dots,
        "height_dots": preview.height_dots,
    }


def _record(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    RECENT_RESULTS.append(f"{stamp} {message}")
    del RECENT_RESULTS[:-20]


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
