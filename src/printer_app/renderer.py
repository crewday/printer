from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
from textwrap import wrap

import cairosvg
from PIL import Image, ImageOps

from printer_app import escpos
from printer_app.models import PrinterConfig, ReceiptTask, TaskBatch

BRAND = "crew.day"
RECEIPT_TITLE = "TASK LIST"
RULE_THICKNESS_DOTS = 2
TASK_INDENT = "  "
CHECKBOX_MARK = "[ ] "
CHECKBOX_CONTINUATION = "    "
LOGO_MAX_WIDTH_DOTS = 384
LOGO_DOTS_PER_COLUMN = 8
RULE_DOTS_PER_COLUMN = 12


@dataclass(frozen=True)
class TaskTextBlock:
    title_lines: tuple[str, ...]
    meta_lines: tuple[str, ...]
    checklist_lines: tuple[str, ...]


def render_receipt(batch: TaskBatch, printer: PrinterConfig, now: datetime) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_print_density(printer.print_density)
    output += escpos.select_print_speed(printer.print_speed)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += _logo_bytes(columns)
    output += escpos.text()
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    output += escpos.centered(RECEIPT_TITLE, columns)
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += _rule(columns)

    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += _render_lines(_metadata_lines(batch, now, columns))
    output += _rule(columns)

    if batch.tasks:
        for index, task in enumerate(batch.tasks, start=1):
            output += _render_task(index, task, columns)
    else:
        output += escpos.text("No tasks for this print window.")
        output += escpos.text()

    output += _rule(columns)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.text(BRAND)
    output += escpos.text()
    output += escpos.text()

    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def render_black_test(printer: PrinterConfig) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_print_density(printer.print_density)
    output += escpos.select_print_speed(printer.print_speed)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    output += escpos.text("BLACK TEST")
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += escpos.text()

    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.text(
        f"Density: {printer.print_density}  Speed: {printer.print_speed}"
    )
    output += escpos.text("Reverse text bars:")
    output += escpos.reverse_bar(columns, "DENSITY CONFIGURED")
    output += escpos.reverse_bar(columns, "SPEED CHECK")
    output += escpos.text()

    output += escpos.text("Filled raster blocks:")
    output += escpos.text("Narrow:")
    output += escpos.filled_raster_block(width_bytes=12, height_dots=48)
    output += escpos.text()
    output += escpos.text("Medium:")
    output += escpos.filled_raster_block(width_bytes=24, height_dots=48)
    output += escpos.text()
    output += escpos.text("Full width:")
    output += escpos.filled_raster_block(width_bytes=48, height_dots=96)
    output += escpos.text()
    output += escpos.text("Solid blocks are worst-case thermal load.")
    output += escpos.text("Judge final settings on normal receipts too.")
    output += escpos.text()
    output += escpos.text()

    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def receipt_text_preview(batch: TaskBatch, now: datetime, columns: int) -> str:
    lines = [
        BRAND.center(columns),
        RECEIPT_TITLE.center(columns),
        _preview_rule(columns),
        *_metadata_lines(batch, now, columns),
        _preview_rule(columns),
    ]
    for index, task in enumerate(batch.tasks, start=1):
        lines.extend(_task_preview_lines(index, task, columns))
    if not batch.tasks:
        lines.append("No tasks for this print window.")
    lines.extend([_preview_rule(columns), BRAND.center(columns)])
    return "\n".join(lines)


def _render_task(index: int, task: ReceiptTask, columns: int) -> bytes:
    block = _task_text_block(index, task, columns)
    output = bytearray()
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    for line in block.title_lines:
        output += escpos.text(line)
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += _render_lines(block.meta_lines)
    output += _render_lines(block.checklist_lines)
    output += escpos.text()
    return bytes(output)


def _rule(columns: int) -> bytes:
    return (
        escpos.command(escpos.ESC, b"a", b"\x00")
        + escpos.horizontal_rule(
            columns,
            dots_per_column=RULE_DOTS_PER_COLUMN,
            thickness_dots=RULE_THICKNESS_DOTS,
        )
        + escpos.text()
    )


def _task_preview_lines(index: int, task: ReceiptTask, columns: int) -> list[str]:
    block = _task_text_block(index, task, columns)
    return [*block.title_lines, *block.meta_lines, *block.checklist_lines, ""]


def _task_text_block(index: int, task: ReceiptTask, columns: int) -> TaskTextBlock:
    title_lines = tuple(_wrapped(f"{index}. {task.title}", columns))
    meta = _task_meta(task)
    meta_lines = _indented_lines(meta, columns) if meta else ()
    checklist_lines = tuple(
        line for item in task.checklist for line in _checklist_item_lines(item, columns)
    )
    return TaskTextBlock(
        title_lines=title_lines,
        meta_lines=meta_lines,
        checklist_lines=checklist_lines,
    )


def _metadata_lines(batch: TaskBatch, now: datetime, columns: int) -> tuple[str, ...]:
    return (
        *_label_lines("Worker", batch.worker_name, columns),
        *_label_lines("Printed", now.strftime("%Y-%m-%d %H:%M %Z"), columns),
        *_label_lines("Source", batch.source_label, columns),
    )


def _task_meta(task: ReceiptTask) -> str:
    parts = []
    if task.time_window:
        parts.append(task.time_window)
    elif task.scheduled_start:
        parts.append(task.scheduled_start.strftime("%H:%M"))
    if task.duration_minutes:
        parts.append(f"{task.duration_minutes} min")
    if task.property_name:
        parts.append(task.property_name)
    if task.area:
        parts.append(task.area)
    if task.priority in {"high", "urgent"}:
        parts.append(f"{task.priority} priority")
    if task.photo_required:
        parts.append("photo required")
    return " | ".join(parts)


def _label_lines(label: str, value: str, columns: int) -> tuple[str, ...]:
    prefix = f"{label}: "
    lines = wrap(value, width=max(columns - len(prefix), 10)) or [""]
    return (
        prefix + lines[0],
        *(" " * len(prefix) + line for line in lines[1:]),
    )


def _indented_lines(value: str, columns: int) -> tuple[str, ...]:
    width = columns - len(TASK_INDENT)
    return tuple(f"{TASK_INDENT}{line}"[:columns] for line in _wrapped(value, width))


def _checklist_item_lines(value: str, columns: int) -> tuple[str, ...]:
    first_indent = TASK_INDENT + CHECKBOX_MARK
    next_indent = TASK_INDENT + CHECKBOX_CONTINUATION
    width = columns - len(first_indent)
    lines = _wrapped(value, width)
    return (
        f"{first_indent}{lines[0]}"[:columns],
        *(f"{next_indent}{line}"[:columns] for line in lines[1:]),
    )


def _render_lines(lines: tuple[str, ...]) -> bytes:
    return b"".join(escpos.text(line) for line in lines)


def _wrapped(value: str, columns: int) -> list[str]:
    return wrap(value, width=columns, break_long_words=False) or [""]


def _preview_rule(columns: int) -> str:
    return "=" * columns


@lru_cache(maxsize=8)
def _logo_bytes(columns: int) -> bytes:
    width = min(columns * LOGO_DOTS_PER_COLUMN, LOGO_MAX_WIDTH_DOTS)
    png = cairosvg.svg2png(
        url=str(files("printer_app").joinpath("assets/crewday-logo.svg")),
        output_width=width,
    )
    rgba = Image.open(BytesIO(png)).convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox:
        rgba = rgba.crop(bbox)

    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    image = background.convert("L")
    image = ImageOps.expand(image, border=8, fill=255)
    image = image.point(lambda pixel: 0 if pixel < 180 else 255, mode="1")
    return escpos.raster_image(image)
