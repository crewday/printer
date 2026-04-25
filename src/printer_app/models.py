from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UIConfig:
    username: str
    password_hash: str | None


@dataclass(frozen=True)
class PrinterConfig:
    type: str
    profile: str
    host: str
    port: int
    timeout_seconds: float
    paper_columns: int
    code_page: str
    image_logo: bool
    supports_print_density: bool
    supports_print_speed: bool
    print_density: int
    print_speed: int
    cut: bool


@dataclass(frozen=True)
class PrinterProfile:
    id: str
    name: str
    description: str
    paper_width: str
    cut_behavior: str
    code_pages: tuple[str, ...]
    image_logo: bool
    supports_print_density: bool
    supports_print_speed: bool
    paper_columns: int
    print_density: int
    print_speed: int
    cut: bool


@dataclass(frozen=True)
class CrewdayConfig:
    source: str
    base_url: str
    api_token: str | None
    workspace_id: str | None


@dataclass(frozen=True)
class PrintScheduleConfig:
    cron: str


@dataclass(frozen=True)
class WorkerConfig:
    name: str
    schedule: str
    crewday_user_id: str | None
    timezone: str
    tasks: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    ui: UIConfig
    printer: PrinterConfig
    crewday: CrewdayConfig
    print_schedule: PrintScheduleConfig
    workers: tuple[WorkerConfig, ...]


@dataclass(frozen=True)
class ReceiptTask:
    id: str
    title: str
    property_name: str | None = None
    area: str | None = None
    scheduled_start: datetime | None = None
    time_window: str | None = None
    duration_minutes: int | None = None
    priority: str = "normal"
    status: str = "pending"
    photo_required: bool = False
    checklist: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskBatch:
    worker_name: str
    source_label: str
    generated_at: datetime
    tasks: tuple[ReceiptTask, ...]
