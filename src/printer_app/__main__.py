from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from printer_app.config import config_path_from_env, ensure_config, load_config
from printer_app.models import WorkerConfig
from printer_app.renderer import receipt_text_preview, render_black_test, render_receipt
from printer_app.task_source import build_task_source
from printer_app.transport import send_to_network_printer


def print_test(config_path: Path, dry_run: bool, worker_name: str | None) -> int:
    config = load_config(config_path)
    worker = select_worker(config.workers, worker_name)
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    payload = render_receipt(batch, config.printer, now)

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


def preview(config_path: Path, worker_name: str | None) -> int:
    config = load_config(config_path)
    worker = select_worker(config.workers, worker_name)
    now = datetime.now(ZoneInfo(worker.timezone))
    batch = build_task_source(config).fetch_task_batch(worker, now=now)
    print(receipt_text_preview(batch, now, config.printer.paper_columns))
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
    payload = render_black_test(printer)

    if dry_run:
        sys.stdout.buffer.write(payload)
        return 0

    send_to_network_printer(payload, printer)
    print(
        f"printed {len(payload)} black-test bytes "
        f"to {printer.host}:{printer.port} "
        f"with density={printer.print_density} speed={printer.print_speed}",
        flush=True,
    )
    return 0


def serve(config_path: Path, host: str, port: int) -> int:
    import uvicorn

    ensure_config(config_path)
    uvicorn.run(
        "printer_app.web:app",
        host=host,
        port=port,
        factory=False,
        reload=False,
    )
    return 0


def select_worker(
    workers: tuple[WorkerConfig, ...],
    worker_name: str | None,
) -> WorkerConfig:
    if worker_name is None:
        return workers[0]

    for worker in workers:
        if worker.name == worker_name:
            return worker
    raise ValueError(f"worker not found in config: {worker_name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printer_app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config")
    init_parser.add_argument("--config", type=Path, default=config_path_from_env())

    preview_parser = subparsers.add_parser("preview")
    preview_parser.add_argument("--config", type=Path, default=config_path_from_env())
    preview_parser.add_argument("--worker")

    print_test_parser = subparsers.add_parser("print-test")
    print_test_parser.add_argument(
        "--config",
        type=Path,
        default=config_path_from_env(),
    )
    print_test_parser.add_argument("--dry-run", action="store_true")
    print_test_parser.add_argument("--worker")

    black_test_parser = subparsers.add_parser("black-test")
    black_test_parser.add_argument(
        "--config",
        type=Path,
        default=config_path_from_env(),
    )
    black_test_parser.add_argument("--dry-run", action="store_true")
    black_test_parser.add_argument("--density", type=int)
    black_test_parser.add_argument("--speed", type=int)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--config", type=Path, default=config_path_from_env())
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8080)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-config":
        created = ensure_config(args.config)
        print(f"{'created' if created else 'exists'}: {args.config}")
        return 0
    if args.command == "preview":
        return preview(args.config, args.worker)
    if args.command == "print-test":
        return print_test(args.config, args.dry_run, args.worker)
    if args.command == "black-test":
        return black_test(args.config, args.dry_run, args.density, args.speed)
    if args.command == "serve":
        return serve(args.config, args.host, args.port)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
