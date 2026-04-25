from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from printer_app import escpos
from printer_app.cron import validate_cron_or_empty
from printer_app.models import (
    AppConfig,
    CrewdayConfig,
    PrinterConfig,
    PrintScheduleConfig,
    UIConfig,
    WorkerConfig,
)
from printer_app.profiles import default_profile, get_profile, profile_ids

DEFAULT_CONFIG_PATH = Path("/config/printer.yaml")


def config_path_from_env() -> Path:
    return Path(os.environ.get("PRINTER_CONFIG", str(DEFAULT_CONFIG_PATH)))


def default_config() -> dict[str, Any]:
    ui_username = os.environ.get("PRINTER_UI_USERNAME", "admin")
    printer_host = os.environ.get("PRINTER_HOST", "192.168.20.15")
    crewday_token = os.environ.get("CREWDAY_API_TOKEN")
    profile = default_profile()
    return {
        "ui": {
            "username": ui_username,
            "password_hash": None,
        },
        "crewday": {
            "source": "mock",
            "base_url": "http://crewday:8000",
            "api_token": crewday_token,
            "workspace_id": None,
        },
        "print_schedule": {
            "cron": "",
        },
        "printer": {
            "type": "network_escpos",
            "profile": profile.id,
            "host": printer_host,
            "port": 9100,
            "timeout_seconds": 5,
            "paper_columns": profile.paper_columns,
            "code_page": profile.code_pages[0],
            "image_logo": profile.image_logo,
            "supports_print_density": profile.supports_print_density,
            "supports_print_speed": profile.supports_print_speed,
            "print_density": profile.print_density,
            "print_speed": profile.print_speed,
            "cut": profile.cut,
        },
        "workers": [
            {
                "name": "Vincent",
                "schedule": "",
                "crewday_user_id": None,
                "timezone": "Asia/Dubai",
                "tasks": [
                    "Review overnight crewday updates",
                    "Print the next task batch",
                    "Confirm thermal printer output is readable",
                ],
            }
        ],
    }


def ensure_config(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_raw_config(path, default_config())
    return True


def load_config(path: Path) -> AppConfig:
    ensure_config(path)
    with path.open("r", encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> AppConfig:
    ui_raw = raw.get("ui") or {}
    crewday_raw = raw.get("crewday") or {}
    print_schedule_raw = raw.get("print_schedule") or {}
    printer_raw = raw.get("printer") or {}
    workers_raw = raw.get("workers") or []

    if not workers_raw:
        raise ValueError("config must include at least one worker")

    ui = UIConfig(
        username=str(
            os.environ.get("PRINTER_UI_USERNAME") or ui_raw.get("username", "admin")
        ),
        password_hash=ui_raw.get("password_hash"),
    )
    crewday = CrewdayConfig(
        source=str(crewday_raw.get("source", "mock")),
        base_url=str(crewday_raw.get("base_url", "http://crewday:8000")).rstrip("/"),
        api_token=os.environ.get("CREWDAY_API_TOKEN") or crewday_raw.get("api_token"),
        workspace_id=crewday_raw.get("workspace_id"),
    )
    print_schedule = PrintScheduleConfig(
        cron=str(print_schedule_raw.get("cron", "")).strip(),
    )
    validate_cron_or_empty(print_schedule.cron)
    profile_id = str(printer_raw.get("profile", default_profile().id))
    profile = get_profile(profile_id) or default_profile()
    printer = PrinterConfig(
        type=str(printer_raw.get("type", "network_escpos")),
        profile=profile_id,
        host=str(printer_raw.get("host", "192.168.20.15")),
        port=int(printer_raw.get("port", 9100)),
        timeout_seconds=float(printer_raw.get("timeout_seconds", 5)),
        paper_columns=int(printer_raw.get("paper_columns", profile.paper_columns)),
        code_page=str(printer_raw.get("code_page", profile.code_pages[0])),
        image_logo=bool(printer_raw.get("image_logo", profile.image_logo)),
        supports_print_density=bool(
            printer_raw.get(
                "supports_print_density",
                profile.supports_print_density,
            )
        ),
        supports_print_speed=bool(
            printer_raw.get("supports_print_speed", profile.supports_print_speed)
        ),
        print_density=int(printer_raw.get("print_density", profile.print_density)),
        print_speed=int(printer_raw.get("print_speed", profile.print_speed)),
        cut=bool(printer_raw.get("cut", profile.cut)),
    )
    validate_printer_config(printer)

    workers = tuple(
        WorkerConfig(
            name=str(worker["name"]),
            schedule=str(worker.get("schedule", "")),
            crewday_user_id=worker.get("crewday_user_id"),
            timezone=str(worker.get("timezone", "Asia/Dubai")),
            tasks=tuple(str(task) for task in worker.get("tasks", [])),
        )
        for worker in workers_raw
    )
    return AppConfig(
        ui=ui,
        crewday=crewday,
        print_schedule=print_schedule,
        printer=printer,
        workers=workers,
    )

def validate_printer_config(printer: PrinterConfig) -> None:
    if printer.type != "network_escpos":
        raise ValueError(f"unsupported printer.type: {printer.type}")
    if printer.profile not in profile_ids():
        raise ValueError(f"unsupported printer.profile: {printer.profile}")
    if printer.code_page not in escpos.CODE_PAGES:
        raise ValueError(f"unsupported printer.code_page: {printer.code_page}")
    if not printer.host:
        raise ValueError("printer.host is required")
    if not 1 <= printer.port <= 65535:
        raise ValueError("printer.port must be between 1 and 65535")
    if printer.timeout_seconds <= 0:
        raise ValueError("printer.timeout_seconds must be positive")
    if not 24 <= printer.paper_columns <= 64:
        raise ValueError("printer.paper_columns must be between 24 and 64")
    if not 0 <= printer.print_density <= 255:
        raise ValueError("printer.print_density must be between 0 and 255")
    if not 0 <= printer.print_speed <= 17:
        raise ValueError("printer.print_speed must be between 0 and 17")


def write_config(path: Path, config: AppConfig) -> None:
    write_raw_config(path, config_to_raw(config))


def write_raw_config(path: Path, raw: dict[str, Any]) -> None:
    parse_config(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as tmp:
        yaml.safe_dump(raw, tmp, sort_keys=False)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def config_to_raw(config: AppConfig) -> dict[str, Any]:
    return {
        "ui": asdict(config.ui),
        "crewday": asdict(config.crewday),
        "print_schedule": asdict(config.print_schedule),
        "printer": asdict(config.printer),
        "workers": [asdict(worker) for worker in config.workers],
    }
