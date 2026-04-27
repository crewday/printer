from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UIConfig:
    username: str
    password_hash: str | None


@dataclass(frozen=True)
class PrinterConfig:
    name: str
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
    usb_vendor_id: int | None = None
    usb_product_id: int | None = None
    cups_printer_name: str | None = None


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
    workspace_slug: str | None
    workspace_id: str | None


@dataclass(frozen=True)
class PrintScheduleConfig:
    cron: str


@dataclass(frozen=True)
class ReceiptTemplateSection:
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


@dataclass(frozen=True)
class ReceiptTemplateConfig:
    sections: tuple[ReceiptTemplateSection, ...]


@dataclass(frozen=True)
class WorkerConfig:
    name: str
    schedule: str
    crewday_user_id: str | None
    enabled: bool = True
    printer: str = ""


@dataclass(frozen=True)
class AppConfig:
    ui: UIConfig
    printers: tuple[PrinterConfig, ...]
    crewday: CrewdayConfig
    print_schedule: PrintScheduleConfig
    receipt_template: ReceiptTemplateConfig
    timezone: str
    workers: tuple[WorkerConfig, ...]

    def printer_by_name(self, name: str) -> PrinterConfig | None:
        for printer in self.printers:
            if printer.name == name:
                return printer
        return None

    def first_printer(self) -> PrinterConfig:
        return self.printers[0]

    def printer_for_worker(self, worker: WorkerConfig) -> PrinterConfig:
        if worker.printer:
            found = self.printer_by_name(worker.printer)
            if found is not None:
                return found
        return self.first_printer()


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


@dataclass(frozen=True)
class CrewdayWorker:
    user_id: str
    name: str
