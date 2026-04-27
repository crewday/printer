from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from printer_app import escpos
from printer_app.cron import validate_cron_or_empty
from printer_app.models import (
    AppConfig,
    CrewdayConfig,
    PrinterConfig,
    PrintScheduleConfig,
    ReceiptTemplateConfig,
    ReceiptTemplateSection,
    UIConfig,
    WorkerConfig,
)
from printer_app.profiles import default_profile, get_profile, profile_ids
from printer_app.secrets import decrypt_secret, encrypt_secret, is_encrypted_secret

DEFAULT_CONFIG_PATH = Path("/config/printer.yaml")

DEFAULT_RECEIPT_TEMPLATE = {
    "sections": [
        {"type": "logo", "align": "center"},
        {
            "type": "text",
            "value": "{{ worker_name }}, {{ display_date }}",
            "align": "center",
            "font": "b",
            "width": 2,
            "height": 2,
            "bold": True,
        },
        {
            "type": "text",
            "value": "Printed on {{ display_datetime }}",
            "align": "center",
            "font": "b",
        },
        {"type": "separator", "align": "center"},
        {"type": "tasks"},
        {"type": "separator", "align": "center", "trailing_blank": False},
        {"type": "logo", "align": "center", "scale": 0.5},
    ],
}


def config_path_from_env() -> Path:
    return Path(os.environ.get("PRINTER_CONFIG", str(DEFAULT_CONFIG_PATH)))


def _default_printer_raw(name: str, host: str | None = None) -> dict[str, Any]:
    profile = default_profile()
    return {
        "name": name,
        "type": "network_escpos",
        "profile": profile.id,
        "host": host or os.environ.get("PRINTER_HOST", "192.168.20.15"),
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
    }


def default_config() -> dict[str, Any]:
    ui_username = os.environ.get("PRINTER_UI_USERNAME", "admin")
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
            "workspace_slug": None,
            "workspace_id": None,
        },
        "print_schedule": {
            "cron": "",
        },
        "timezone": os.environ.get("PRINTER_TIMEZONE", "Asia/Dubai"),
        "receipt_template": DEFAULT_RECEIPT_TEMPLATE,
        "printers": [_default_printer_raw("Default")],
        "workers": [
            {
                "name": "Vincent",
                "schedule": "",
                "crewday_user_id": None,
                "enabled": True,
                "printer": "Default",
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
    receipt_template_raw = raw.get("receipt_template") or DEFAULT_RECEIPT_TEMPLATE
    printers_raw = raw.get("printers") or []
    workers_raw = raw.get("workers") or []
    timezone = str(
        raw.get("timezone") or os.environ.get("PRINTER_TIMEZONE") or "Asia/Dubai"
    )

    if not workers_raw:
        raise ValueError("config must include at least one worker")

    ui = UIConfig(
        username=str(
            os.environ.get("PRINTER_UI_USERNAME")
            or decrypt_secret(ui_raw.get("username", "admin"))
        ),
        password_hash=decrypt_secret(ui_raw.get("password_hash")),
    )
    crewday = CrewdayConfig(
        source=str(crewday_raw.get("source", "mock")),
        base_url=str(crewday_raw.get("base_url", "http://crewday:8000")).rstrip("/"),
        api_token=os.environ.get("CREWDAY_API_TOKEN")
        or decrypt_secret(crewday_raw.get("api_token")),
        workspace_slug=crewday_raw.get("workspace_slug")
        or crewday_raw.get("workspace_id"),
        workspace_id=crewday_raw.get("workspace_id"),
    )
    print_schedule = PrintScheduleConfig(
        cron=str(print_schedule_raw.get("cron", "")).strip(),
    )
    validate_cron_or_empty(print_schedule.cron)
    validate_timezone(timezone)
    printers = _parse_printers(printers_raw)
    receipt_template = parse_receipt_template(receipt_template_raw)

    workers = tuple(
        WorkerConfig(
            name=str(worker["name"]),
            schedule=str(worker.get("schedule", "")),
            crewday_user_id=worker.get("crewday_user_id"),
            enabled=bool(worker.get("enabled", True)),
            printer=str(worker.get("printer", "")),
        )
        for worker in workers_raw
    )
    return AppConfig(
        ui=ui,
        crewday=crewday,
        print_schedule=print_schedule,
        receipt_template=receipt_template,
        timezone=timezone,
        printers=printers,
        workers=workers,
    )


def _parse_printers(printers_raw: list[Any]) -> tuple[PrinterConfig, ...]:
    if not printers_raw:
        raise ValueError("config must include at least one printer")
    printers: list[PrinterConfig] = []
    names: set[str] = set()
    for printer_raw in printers_raw:
        if not isinstance(printer_raw, dict):
            raise ValueError("each printer entry must be a mapping")
        name = str(printer_raw.get("name", "")).strip()
        if not name:
            raise ValueError("each printer must have a non-empty name")
        if name in names:
            raise ValueError(f"duplicate printer name: {name!r}")
        names.add(name)
        profile_id = str(printer_raw.get("profile", default_profile().id))
        profile = get_profile(profile_id) or default_profile()
        printer = PrinterConfig(
            name=name,
            type=str(printer_raw.get("type", "network_escpos")),
            profile=profile_id,
            host=str(printer_raw.get("host", "192.168.20.15")),
            port=int(printer_raw.get("port", 9100)),
            timeout_seconds=float(printer_raw.get("timeout_seconds", 5)),
            paper_columns=int(
                printer_raw.get("paper_columns", profile.paper_columns)
            ),
            code_page=str(printer_raw.get("code_page", profile.code_pages[0])),
            image_logo=bool(printer_raw.get("image_logo", profile.image_logo)),
            supports_print_density=bool(
                printer_raw.get(
                    "supports_print_density",
                    profile.supports_print_density,
                )
            ),
            supports_print_speed=bool(
                printer_raw.get(
                    "supports_print_speed", profile.supports_print_speed
                )
            ),
            print_density=int(
                printer_raw.get("print_density", profile.print_density)
            ),
            print_speed=int(printer_raw.get("print_speed", profile.print_speed)),
            cut=bool(printer_raw.get("cut", profile.cut)),
        )
        validate_printer_config(printer)
        printers.append(printer)
    return tuple(printers)


def default_receipt_template() -> ReceiptTemplateConfig:
    return parse_receipt_template(DEFAULT_RECEIPT_TEMPLATE)


def parse_receipt_template(raw: dict[str, Any]) -> ReceiptTemplateConfig:
    sections_raw = raw.get("sections") or []
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValueError("receipt_template.sections must include at least one section")
    if not all(isinstance(section, dict) for section in sections_raw):
        raise ValueError("receipt_template.sections must contain mappings")

    template = ReceiptTemplateConfig(
        sections=tuple(
            ReceiptTemplateSection(
                type=str(section.get("type", "")).strip(),
                value=(
                    str(section["value"]) if section.get("value") is not None else None
                ),
                align=str(section.get("align", "left")).strip().lower(),
                font=str(section.get("font", "a")).strip().lower(),
                width=int(section.get("width", 1)),
                height=int(section.get("height", 1)),
                bold=bool(section.get("bold", False)),
                underline=int(section.get("underline", 0)),
                scale=float(section.get("scale", 1.0)),
                trailing_blank=bool(section.get("trailing_blank", True)),
            )
            for section in sections_raw
        )
    )
    validate_receipt_template(template)
    return template


def validate_receipt_template(template: ReceiptTemplateConfig) -> None:
    allowed_types = {"blank", "logo", "separator", "tasks", "text"}
    allowed_alignments = {"left", "center", "right"}
    allowed_fonts = {"a", "b"}
    for section in template.sections:
        if section.type not in allowed_types:
            raise ValueError(
                f"unsupported receipt_template section type: {section.type}"
            )
        if section.type == "text" and section.value is None:
            raise ValueError("receipt_template text sections require value")
        if section.align not in allowed_alignments:
            raise ValueError(f"unsupported receipt_template alignment: {section.align}")
        if section.font not in allowed_fonts:
            raise ValueError(f"unsupported receipt_template font: {section.font}")
        if not 1 <= section.width <= 8:
            raise ValueError("receipt_template section width must be between 1 and 8")
        if not 1 <= section.height <= 8:
            raise ValueError("receipt_template section height must be between 1 and 8")
        if section.underline not in {0, 1, 2}:
            raise ValueError("receipt_template section underline must be 0, 1, or 2")
        if section.scale <= 0:
            raise ValueError("receipt_template section scale must be positive")


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


def validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unsupported timezone: {timezone}") from exc


def write_config(path: Path, config: AppConfig) -> None:
    write_raw_config(path, config_to_raw(config))


def write_raw_config(path: Path, raw: dict[str, Any]) -> None:
    parse_config(raw)
    raw = encrypt_raw_config(raw)
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
        "timezone": config.timezone,
        "receipt_template": {
            "sections": [
                asdict(section) for section in config.receipt_template.sections
            ]
        },
        "printers": [asdict(printer) for printer in config.printers],
        "workers": [asdict(worker) for worker in config.workers],
    }


def encrypt_raw_config(raw: dict[str, Any]) -> dict[str, Any]:
    stored = dict(raw)
    ui = dict(stored.get("ui") or {})
    crewday = dict(stored.get("crewday") or {})
    if ui.get("username") is not None:
        ui["username"] = _encrypt_config_value(ui["username"])
    if ui.get("password_hash") is not None:
        ui["password_hash"] = _encrypt_config_value(ui["password_hash"])
    if crewday.get("api_token") is not None:
        crewday["api_token"] = _encrypt_config_value(crewday["api_token"])
    stored["ui"] = ui
    stored["crewday"] = crewday
    return stored


def _encrypt_config_value(value: object) -> object:
    if value is None or is_encrypted_secret(value):
        return value
    return encrypt_secret(str(value))
