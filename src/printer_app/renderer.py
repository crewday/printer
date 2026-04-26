from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
from textwrap import wrap

import cairosvg
from jinja2 import Environment, StrictUndefined
from PIL import Image, ImageDraw, ImageOps

from printer_app import escpos
from printer_app.escpos_preview import render_payload_to_png
from printer_app.models import (
    PrinterConfig,
    ReceiptTask,
    ReceiptTemplateConfig,
    ReceiptTemplateSection,
    TaskBatch,
)

BRAND = "crew.day"
RULE_THICKNESS_DOTS = 2
TASK_INDENT = "  "
CHECKBOX_MARK = "[ ] "
CHECKBOX_CONTINUATION = "    "
LOGO_MAX_WIDTH_DOTS = 384
LOGO_DOTS_PER_COLUMN = 8
RULE_DOTS_PER_COLUMN = 12
FONT_A_CELL_WIDTH_DOTS = RULE_DOTS_PER_COLUMN
FONT_A_CELL_HEIGHT_DOTS = 24
FONT_B_CELL_WIDTH_DOTS = 9
FONT_B_CELL_HEIGHT_DOTS = 20
TEXT_CELL_WIDTH_DOTS = FONT_A_CELL_WIDTH_DOTS
TEXT_CELL_HEIGHT_DOTS = FONT_A_CELL_HEIGHT_DOTS
ALIGNMENTS = {"left": b"\x00", "center": b"\x01", "right": b"\x02"}
TEMPLATE_ENV = Environment(autoescape=False, undefined=StrictUndefined)


@dataclass(frozen=True)
class TaskTextBlock:
    title_lines: tuple[str, ...]
    meta_lines: tuple[str, ...]
    checklist_lines: tuple[str, ...]


@dataclass(frozen=True)
class ReceiptPreview:
    png: bytes
    width_dots: int
    height_dots: int


DEFAULT_RECEIPT_TEMPLATE = ReceiptTemplateConfig(
    sections=(
        ReceiptTemplateSection(type="logo", align="center"),
        ReceiptTemplateSection(
            type="text",
            value="{{ worker_name }}, {{ display_date }}",
            align="center",
            font="b",
            width=2,
            height=2,
            bold=True,
        ),
        ReceiptTemplateSection(
            type="text",
            value="Printed on {{ display_datetime }}",
            align="center",
            font="b",
        ),
        ReceiptTemplateSection(type="separator", align="center"),
        ReceiptTemplateSection(type="tasks"),
        ReceiptTemplateSection(type="separator", align="center", trailing_blank=False),
        ReceiptTemplateSection(type="logo", align="center", scale=0.5),
    )
)

CalibrationSetting = tuple[int, int]


def render_receipt(
    batch: TaskBatch,
    printer: PrinterConfig,
    now: datetime,
    template: ReceiptTemplateConfig | None = None,
) -> bytes:
    template = template or DEFAULT_RECEIPT_TEMPLATE
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_code_page(printer.code_page)
    if printer.supports_print_density:
        output += escpos.select_print_density(printer.print_density)
    if printer.supports_print_speed:
        output += escpos.select_print_speed(printer.print_speed)
    for section in template.sections:
        output += _render_template_section(section, batch, printer, now)

    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def render_receipt_preview(
    batch: TaskBatch,
    printer: PrinterConfig,
    now: datetime,
    template: ReceiptTemplateConfig | None = None,
) -> ReceiptPreview:
    payload = render_receipt(batch, printer, now, template)
    width_dots = printer.paper_columns * RULE_DOTS_PER_COLUMN
    preview = render_payload_to_png(
        payload,
        columns=printer.paper_columns,
        code_page=printer.code_page,
        width_dots=width_dots,
    )
    return ReceiptPreview(
        png=preview.png,
        width_dots=preview.width_dots,
        height_dots=preview.height_dots,
    )


def render_black_test(printer: PrinterConfig) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_code_page(printer.code_page)
    if printer.supports_print_density:
        output += escpos.select_print_density(printer.print_density)
    if printer.supports_print_speed:
        output += escpos.select_print_speed(printer.print_speed)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    output += escpos.text("BLACK TEST", printer.code_page)
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += escpos.text("", printer.code_page)

    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.text(
        f"Density: {printer.print_density}  Speed: {printer.print_speed}",
        printer.code_page,
    )
    output += escpos.text("Reverse text bars:", printer.code_page)
    output += escpos.reverse_bar(columns, "DENSITY CONFIGURED", printer.code_page)
    output += escpos.reverse_bar(columns, "SPEED CHECK", printer.code_page)
    output += escpos.text("", printer.code_page)

    output += escpos.text("Filled raster blocks:", printer.code_page)
    output += escpos.text("Narrow:", printer.code_page)
    output += escpos.filled_raster_block(width_bytes=12, height_dots=48)
    output += escpos.text("", printer.code_page)
    output += escpos.text("Medium:", printer.code_page)
    output += escpos.filled_raster_block(width_bytes=24, height_dots=48)
    output += escpos.text("", printer.code_page)
    output += escpos.text("Full width:", printer.code_page)
    output += escpos.filled_raster_block(width_bytes=48, height_dots=96)
    output += escpos.text("", printer.code_page)
    output += escpos.text(
        "Solid blocks are worst-case thermal load.",
        printer.code_page,
    )
    output += escpos.text(
        "Judge final settings on normal receipts too.",
        printer.code_page,
    )
    output += escpos.text("", printer.code_page)
    output += escpos.text("", printer.code_page)

    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def render_calibration_sweep(
    printer: PrinterConfig,
    settings: tuple[CalibrationSetting, ...],
    title: str,
) -> bytes:
    output = bytearray()
    columns = printer.paper_columns

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_code_page(printer.code_page)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.bold(True)
    output += escpos.text(title.upper(), printer.code_page)
    output += escpos.bold(False)
    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.text("Pick the first dark readable sample.", printer.code_page)
    output += escpos.text("", printer.code_page)

    for index, (density, speed) in enumerate(settings, start=1):
        if printer.supports_print_density:
            output += escpos.select_print_density(density)
        if printer.supports_print_speed:
            output += escpos.select_print_speed(speed)
        output += escpos.bold(True)
        output += escpos.text(
            f"{index}. density={density} speed={speed}",
            printer.code_page,
        )
        output += escpos.bold(False)
        output += escpos.text(
            "Readable task text 0123456789".ljust(columns)[:columns],
            printer.code_page,
        )
        output += escpos.reverse_bar(columns, "DARK BAR", printer.code_page)
        output += escpos.filled_raster_block(width_bytes=10, height_dots=16)
        output += escpos.text("", printer.code_page)

    output += escpos.select_font("a")
    output += escpos.select_text_size()
    output += escpos.bold(False)
    output += escpos.underline(0)
    output += escpos.text("", printer.code_page)
    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def render_font_test(printer: PrinterConfig) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_code_page(printer.code_page)
    if printer.supports_print_density:
        output += escpos.select_print_density(printer.print_density)
    if printer.supports_print_speed:
        output += escpos.select_print_speed(printer.print_speed)

    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.bold(True)
    output += escpos.select_text_size(width=2, height=2)
    output += escpos.text("FONT TEST", printer.code_page)
    output += escpos.select_text_size()
    output += escpos.bold(False)
    output += escpos.text("", printer.code_page)

    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.text(
        f"Profile: {printer.profile}  Code page: {printer.code_page}",
        printer.code_page,
    )
    output += escpos.text(
        f"Columns: {columns}  Density: {printer.print_density}  Speed: "
        f"{printer.print_speed}",
        printer.code_page,
    )
    output += _rule(columns, printer.code_page)

    output += escpos.select_font("a")
    output += escpos.text(
        "Font A normal: The quick brown fox 0123456789",
        printer.code_page,
    )
    output += escpos.select_font("b")
    output += escpos.text(
        "Font B normal: The quick brown fox 0123456789",
        printer.code_page,
    )
    output += escpos.select_font("a")
    output += escpos.text("", printer.code_page)

    output += escpos.bold(True)
    output += escpos.text("Bold: heavier task headings", printer.code_page)
    output += escpos.bold(False)
    output += escpos.underline(1)
    output += escpos.text("Underline 1-dot: labels and warnings", printer.code_page)
    output += escpos.underline(2)
    output += escpos.text("Underline 2-dot: stronger emphasis", printer.code_page)
    output += escpos.underline(0)
    output += escpos.text("", printer.code_page)

    for width, height, label in (
        (2, 1, "Double width"),
        (1, 2, "Double height"),
        (2, 2, "Double width + height"),
    ):
        output += escpos.select_text_size(width=width, height=height)
        output += escpos.text(label, printer.code_page)
        output += escpos.select_text_size()
        output += escpos.text(f"normal reset after {label.lower()}", printer.code_page)

    output += escpos.text("", printer.code_page)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.text("Centered text", printer.code_page)
    output += escpos.command(escpos.ESC, b"a", b"\x02")
    output += escpos.text("Right aligned text", printer.code_page)
    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.reverse_bar(columns, "REVERSE PRINT SAMPLE", printer.code_page)
    output += escpos.text("", printer.code_page)
    output += escpos.text("Symbols: # * + - / = @ [] {} <>", printer.code_page)
    output += escpos.text(
        "Accents: été à l'hôtel, déjà vu, façade, garçon, où, Noël, 12€",
        printer.code_page,
    )
    output += escpos.text("", printer.code_page)

    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.bold(True)
    output += escpos.text("Bitmap raster image", printer.code_page)
    output += escpos.bold(False)
    output += _bitmap_test_bytes()
    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += escpos.text(
        "Bitmap should show border, diagonals, and checker blocks.",
        printer.code_page,
    )
    output += escpos.text("", printer.code_page)

    output += escpos.select_font("a")
    output += escpos.select_text_size()
    output += escpos.bold(False)
    output += escpos.underline(0)
    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def _bitmap_test_bytes() -> bytes:
    image = Image.new("1", (256, 96), 255)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=0, width=2)
    draw.line((8, 8, image.width - 9, image.height - 9), fill=0, width=2)
    draw.line((image.width - 9, 8, 8, image.height - 9), fill=0, width=2)

    for row in range(4):
        for col in range(8):
            if (row + col) % 2 == 0:
                x0 = 16 + col * 14
                y0 = 18 + row * 14
                draw.rectangle((x0, y0, x0 + 11, y0 + 11), fill=0)

    draw.rectangle((152, 20, 232, 38), fill=0)
    draw.rectangle((152, 56, 232, 74), fill=0)
    draw.rectangle((152, 20, 170, 74), fill=0)
    draw.rectangle((214, 20, 232, 74), fill=0)
    draw.rectangle((176, 42, 208, 52), fill=0)

    return escpos.raster_image(image)


def receipt_text_preview(
    batch: TaskBatch,
    now: datetime,
    columns: int,
    template: ReceiptTemplateConfig | None = None,
) -> str:
    template = template or DEFAULT_RECEIPT_TEMPLATE
    lines: list[str] = []
    for section in template.sections:
        lines.extend(_preview_template_section(section, batch, now, columns))
    return "\n".join(lines)


def _render_template_section(
    section: ReceiptTemplateSection,
    batch: TaskBatch,
    printer: PrinterConfig,
    now: datetime,
) -> bytes:
    columns = printer.paper_columns
    code_page = printer.code_page
    match section.type:
        case "blank":
            return escpos.text("", code_page)
        case "logo":
            if not printer.image_logo:
                return b""
            return escpos.command(escpos.ESC, b"a", b"\x01") + _logo_bytes(
                columns, scale=section.scale
            )
        case "separator":
            return _rule(columns, code_page, trailing_blank=section.trailing_blank)
        case "tasks":
            output = bytearray()
            output += escpos.command(escpos.ESC, b"a", b"\x00")
            output += escpos.select_font("a")
            if batch.tasks:
                for index, task in enumerate(batch.tasks, start=1):
                    output += _render_task(index, task, columns, code_page)
            else:
                output += escpos.text("No tasks for this print window.", code_page)
                output += escpos.text("", code_page)
            return bytes(output)
        case "text":
            return _render_template_text(section, batch, now, columns, code_page)
        case _:
            raise ValueError(f"unsupported receipt template section: {section.type}")


def _render_template_text(
    section: ReceiptTemplateSection,
    batch: TaskBatch,
    now: datetime,
    columns: int,
    code_page: str,
) -> bytes:
    value = _render_template_value(section.value or "", batch, now)
    max_chars = _font_columns(columns, section.font, section.width)
    lines = tuple(
        line for raw in value.splitlines() for line in _wrapped(raw, max_chars)
    )
    output = bytearray()
    output += escpos.command(escpos.ESC, b"a", ALIGNMENTS[section.align])
    output += escpos.select_font(section.font)
    output += escpos.select_text_size(width=section.width, height=section.height)
    output += escpos.bold(section.bold)
    if section.underline:
        output += escpos.underline(section.underline)
    output += _render_lines(lines, code_page)
    if section.underline:
        output += escpos.underline(0)
    output += escpos.bold(False)
    output += escpos.select_text_size()
    return bytes(output)


def _preview_template_section(
    section: ReceiptTemplateSection,
    batch: TaskBatch,
    now: datetime,
    columns: int,
) -> list[str]:
    match section.type:
        case "blank":
            return [""]
        case "logo":
            return [_aligned_preview_line(BRAND, columns, "center")]
        case "separator":
            lines = [_preview_rule(columns)]
            if section.trailing_blank:
                lines.append("")
            return lines
        case "tasks":
            lines: list[str] = []
            for index, task in enumerate(batch.tasks, start=1):
                lines.extend(_task_preview_lines(index, task, columns))
            if not batch.tasks:
                lines.append("No tasks for this print window.")
            return lines
        case "text":
            value = _render_template_value(section.value or "", batch, now)
            max_chars = _font_columns(columns, section.font, section.width)
            return [
                _aligned_preview_line(line, columns, section.align)
                for raw in value.splitlines()
                for line in _wrapped(raw, max_chars)
            ]
        case _:
            raise ValueError(f"unsupported receipt template section: {section.type}")


def _render_template_value(value: str, batch: TaskBatch, now: datetime) -> str:
    template = TEMPLATE_ENV.from_string(value)
    return template.render(
        brand=BRAND,
        worker_name=batch.worker_name,
        source_label=batch.source_label,
        task_count=len(batch.tasks),
        display_date=_display_date(now),
        display_datetime=_display_datetime(now),
        printed_at=now,
        generated_at=batch.generated_at,
    )


def _render_task(index: int, task: ReceiptTask, columns: int, code_page: str) -> bytes:
    block = _task_text_block(index, task, columns)
    output = bytearray()
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    for line in block.title_lines:
        output += escpos.text(line, code_page)
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += _render_lines(block.meta_lines, code_page)
    output += _render_lines(block.checklist_lines, code_page)
    output += escpos.text("", code_page)
    return bytes(output)


def _rule(columns: int, code_page: str, *, trailing_blank: bool = True) -> bytes:
    output = escpos.command(escpos.ESC, b"a", b"\x00") + escpos.horizontal_rule(
        columns,
        dots_per_column=RULE_DOTS_PER_COLUMN,
        thickness_dots=RULE_THICKNESS_DOTS,
    )
    if trailing_blank:
        output += escpos.text("", code_page)
    return output


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


def _receipt_heading(batch: TaskBatch, now: datetime) -> str:
    return f"{batch.worker_name}, {_display_date(now)}"


def _printed_on_line(now: datetime) -> str:
    return f"Printed on {_display_datetime(now)}"


def _display_date(value: datetime) -> str:
    return f"{value.strftime('%B')} {_ordinal(value.day)}, {value:%Y}"


def _display_datetime(value: datetime) -> str:
    return f"{_display_date(value)} {value:%H:%M:%S} {_timezone_offset(value)}"


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _timezone_offset(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None:
        return ""
    total_minutes = math.floor(offset.total_seconds() / 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if minutes:
        return f"{sign}{hours:02d}:{minutes:02d}"
    return f"{sign}{hours:02d}"


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


def _render_lines(lines: tuple[str, ...], code_page: str) -> bytes:
    return b"".join(escpos.text(line, code_page) for line in lines)


def _render_centered_text(
    value: str,
    columns: int,
    code_page: str,
    *,
    font: str = "a",
    width: int = 1,
    height: int = 1,
    bold: bool = False,
) -> bytes:
    max_chars = _font_columns(columns, font, width)
    lines = _wrapped(value, max_chars)
    output = bytearray()
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.select_font(font)
    output += escpos.select_text_size(width=width, height=height)
    output += escpos.bold(bold)
    output += _render_lines(tuple(lines), code_page)
    output += escpos.bold(False)
    output += escpos.select_text_size()
    return bytes(output)


def _font_columns(columns: int, font: str, width_multiplier: int = 1) -> int:
    cell_width = (
        FONT_B_CELL_WIDTH_DOTS if font.lower() == "b" else FONT_A_CELL_WIDTH_DOTS
    )
    width_dots = columns * FONT_A_CELL_WIDTH_DOTS
    return max(1, width_dots // (cell_width * width_multiplier))


def _wrapped(value: str, columns: int) -> list[str]:
    return wrap(value, width=columns, break_long_words=False) or [""]


def _preview_rule(columns: int) -> str:
    return "=" * columns


def _aligned_preview_line(value: str, columns: int, align: str) -> str:
    if align == "center":
        return value.center(columns)
    if align == "right":
        return value.rjust(columns)
    return value


@lru_cache(maxsize=16)
def _logo_bytes(columns: int, scale: float = 1.0) -> bytes:
    max_width = min(columns * LOGO_DOTS_PER_COLUMN, LOGO_MAX_WIDTH_DOTS)
    width = max(1, round(max_width * scale))
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
