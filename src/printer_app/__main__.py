from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from textwrap import wrap
from zoneinfo import ZoneInfo

import yaml


ESC = b"\x1b"
GS = b"\x1d"


@dataclass(frozen=True)
class PrinterConfig:
    type: str
    profile: str
    host: str
    port: int
    timeout_seconds: float
    paper_columns: int
    print_density: int
    print_speed: int
    cut: bool


@dataclass(frozen=True)
class WorkerConfig:
    name: str
    schedule: str
    tasks: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    printer: PrinterConfig
    workers: tuple[WorkerConfig, ...]


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}

    printer_raw = raw.get("printer") or {}
    workers_raw = raw.get("workers") or []
    if not workers_raw:
        raise ValueError("config must include at least one worker")

    printer = PrinterConfig(
        type=str(printer_raw.get("type", "network_escpos")),
        profile=str(printer_raw.get("profile", "generic_escpos")),
        host=str(printer_raw["host"]),
        port=int(printer_raw.get("port", 9100)),
        timeout_seconds=float(printer_raw.get("timeout_seconds", 5)),
        paper_columns=int(printer_raw.get("paper_columns", 42)),
        print_density=int(printer_raw.get("print_density", 0)),
        print_speed=int(printer_raw.get("print_speed", 0)),
        cut=bool(printer_raw.get("cut", True)),
    )
    validate_printer_config(printer)

    workers = tuple(
        WorkerConfig(
            name=str(worker["name"]),
            schedule=str(worker.get("schedule", "0 8 * * *")),
            tasks=tuple(str(task) for task in worker.get("tasks", [])),
        )
        for worker in workers_raw
    )
    return AppConfig(printer=printer, workers=workers)


def validate_printer_config(printer: PrinterConfig) -> None:
    if not 0 <= printer.print_density <= 255:
        raise ValueError("printer.print_density must be between 0 and 255")
    if not 0 <= printer.print_speed <= 17:
        raise ValueError("printer.print_speed must be between 0 and 17")


def command(*parts: bytes) -> bytes:
    return b"".join(parts)


def text(line: str = "") -> bytes:
    return f"{line}\n".encode("cp437", errors="replace")


def centered(line: str, columns: int) -> bytes:
    return text(line[:columns].center(columns))


def separator(columns: int, char: str = "-") -> bytes:
    return text(char * columns)


def render_receipt(worker: WorkerConfig, printer: PrinterConfig, now: datetime) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += command(ESC, b"@")
    output += select_print_density(printer.print_density)
    output += select_print_speed(printer.print_speed)
    output += command(ESC, b"a", b"\x01")
    output += command(ESC, b"E", b"\x01")
    output += command(GS, b"!", b"\x11")
    output += centered("CREWDAY", columns // 2)
    output += command(GS, b"!", b"\x00")
    output += centered("TASK RECEIPT", columns)
    output += command(ESC, b"E", b"\x00")
    output += separator(columns, "=")

    output += command(ESC, b"a", b"\x00")
    output += text(f"Worker: {worker.name}")
    output += text(f"Printed: {now.strftime('%Y-%m-%d %H:%M %Z')}")
    output += text(f"Schedule: {worker.schedule}")
    output += separator(columns)

    if worker.tasks:
        for index, task in enumerate(worker.tasks, start=1):
            prefix = f"{index}. "
            wrapped = wrap(task, width=max(columns - len(prefix), 10)) or [""]
            output += text(prefix + wrapped[0])
            for continuation in wrapped[1:]:
                output += text(" " * len(prefix) + continuation)
            output += text()
    else:
        output += text("No tasks configured.")
        output += text()

    output += separator(columns)
    output += command(ESC, b"a", b"\x01")
    output += text("Make today visible.")
    output += text()
    output += text()

    if printer.cut:
        output += command(GS, b"V", b"\x41", b"\x03")

    return bytes(output)


def render_black_test(printer: PrinterConfig) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += command(ESC, b"@")
    output += select_print_density(printer.print_density)
    output += select_print_speed(printer.print_speed)
    output += command(ESC, b"a", b"\x01")
    output += command(ESC, b"E", b"\x01")
    output += text("BLACK TEST")
    output += command(ESC, b"E", b"\x00")
    output += text()

    output += command(ESC, b"a", b"\x00")
    output += text("Reverse text bars:")
    output += reverse_bar(columns, "DENSITY CONFIGURED")
    output += reverse_bar(columns, "SPEED LOW")
    output += text()

    output += text("Filled raster blocks:")
    output += text("Narrow:")
    output += filled_raster_block(width_bytes=12, height_dots=48)
    output += text()
    output += text("Medium:")
    output += filled_raster_block(width_bytes=24, height_dots=48)
    output += text()
    output += text("Full width:")
    output += filled_raster_block(width_bytes=48, height_dots=96)
    output += text()
    output += text("If these blocks are striped, reduce speed further")
    output += text("or raise density within the printer profile.")
    output += text()
    output += text()

    if printer.cut:
        output += command(GS, b"V", b"\x41", b"\x03")

    return bytes(output)


def reverse_bar(columns: int, label: str) -> bytes:
    padded = f" {label} "[:columns].center(columns)
    return command(GS, b"B", b"\x01") + text(padded) + command(GS, b"B", b"\x00")


def filled_raster_block(width_bytes: int, height_dots: int) -> bytes:
    x_l = width_bytes & 0xFF
    x_h = (width_bytes >> 8) & 0xFF
    y_l = height_dots & 0xFF
    y_h = (height_dots >> 8) & 0xFF
    return command(GS, b"v0", b"\x00", bytes([x_l, x_h, y_l, y_h])) + (
        b"\xff" * width_bytes * height_dots
    )


def select_print_density(density: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x31", bytes([density]))


def select_print_speed(speed: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x32", bytes([speed]))


def send_to_network_printer(payload: bytes, printer: PrinterConfig) -> None:
    if printer.type != "network_escpos":
        raise ValueError(f"unsupported printer type: {printer.type}")

    with socket.create_connection(
        (printer.host, printer.port),
        timeout=printer.timeout_seconds,
    ) as sock:
        sock.sendall(payload)


def print_test(config_path: Path, dry_run: bool, worker_name: str | None) -> int:
    config = load_config(config_path)
    worker = select_worker(config.workers, worker_name)
    now = datetime.now(ZoneInfo("Asia/Dubai"))
    payload = render_receipt(worker, config.printer, now)

    if dry_run:
        sys.stdout.buffer.write(payload)
        return 0

    send_to_network_printer(payload, config.printer)
    print(
        f"printed {len(payload)} bytes for {worker.name} "
        f"to {config.printer.host}:{config.printer.port}",
        flush=True,
    )
    return 0


def black_test(
    config_path: Path,
    dry_run: bool,
    density: int | None,
    speed: int | None,
) -> int:
    config = load_config(config_path)
    printer = config.printer
    if density is not None:
        printer = replace(printer, print_density=density)
    if speed is not None:
        printer = replace(printer, print_speed=speed)
    validate_printer_config(printer)
    payload = render_black_test(printer)

    if dry_run:
        sys.stdout.buffer.write(payload)
        return 0

    send_to_network_printer(payload, config.printer)
    print(
        f"printed {len(payload)} black-test bytes "
        f"to {printer.host}:{printer.port} "
        f"with density={printer.print_density} speed={printer.print_speed}",
        flush=True,
    )
    return 0


def select_worker(workers: tuple[WorkerConfig, ...], worker_name: str | None) -> WorkerConfig:
    if worker_name is None:
        return workers[0]

    for worker in workers:
        if worker.name == worker_name:
            return worker
    raise ValueError(f"worker not found in config: {worker_name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printer_app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    print_test_parser = subparsers.add_parser("print-test")
    print_test_parser.add_argument("--config", type=Path, default=Path("/config/printer.yaml"))
    print_test_parser.add_argument("--dry-run", action="store_true")
    print_test_parser.add_argument("--worker")

    black_test_parser = subparsers.add_parser("black-test")
    black_test_parser.add_argument("--config", type=Path, default=Path("/config/printer.yaml"))
    black_test_parser.add_argument("--dry-run", action="store_true")
    black_test_parser.add_argument("--density", type=int)
    black_test_parser.add_argument("--speed", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "print-test":
        return print_test(args.config, args.dry_run, args.worker)
    if args.command == "black-test":
        return black_test(args.config, args.dry_run, args.density, args.speed)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
