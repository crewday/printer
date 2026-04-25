from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from printer_app.models import (
    AppConfig,
    CrewdayConfig,
    PrinterConfig,
    UIConfig,
    WorkerConfig,
)

DEFAULT_CONFIG_PATH = Path("/config/printer.yaml")


def config_path_from_env() -> Path:
    return Path(os.environ.get("PRINTER_CONFIG", str(DEFAULT_CONFIG_PATH)))


def default_config() -> dict[str, Any]:
    ui_username = os.environ.get("PRINTER_UI_USERNAME", "admin")
    printer_host = os.environ.get("PRINTER_HOST", "192.168.20.15")
    crewday_token = os.environ.get("CREWDAY_API_TOKEN")
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
        "printer": {
            "type": "network_escpos",
            "profile": "epson_tm_t20ii",
            "host": printer_host,
            "port": 9100,
            "timeout_seconds": 5,
            "paper_columns": 48,
            "print_density": 8,
            "print_speed": 6,
            "cut": True,
        },
        "workers": [
            {
                "name": "Vincent",
                "schedule": "0 8 * * *",
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
    printer = PrinterConfig(
        type=str(printer_raw.get("type", "network_escpos")),
        profile=str(printer_raw.get("profile", "generic_escpos")),
        host=str(printer_raw.get("host", "192.168.20.15")),
        port=int(printer_raw.get("port", 9100)),
        timeout_seconds=float(printer_raw.get("timeout_seconds", 5)),
        paper_columns=int(printer_raw.get("paper_columns", 48)),
        print_density=int(printer_raw.get("print_density", 0)),
        print_speed=int(printer_raw.get("print_speed", 0)),
        cut=bool(printer_raw.get("cut", True)),
    )
    validate_printer_config(printer)

    workers = tuple(
        WorkerConfig(
            name=str(worker["name"]),
            schedule=str(worker.get("schedule", "0 8 * * *")),
            crewday_user_id=worker.get("crewday_user_id"),
            timezone=str(worker.get("timezone", "Asia/Dubai")),
            tasks=tuple(str(task) for task in worker.get("tasks", [])),
        )
        for worker in workers_raw
    )
    return AppConfig(ui=ui, crewday=crewday, printer=printer, workers=workers)


def validate_printer_config(printer: PrinterConfig) -> None:
    if printer.type != "network_escpos":
        raise ValueError(f"unsupported printer.type: {printer.type}")
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
        "printer": asdict(config.printer),
        "workers": [asdict(worker) for worker in config.workers],
    }
