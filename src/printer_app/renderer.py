from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
from textwrap import wrap

import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageOps

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
TEXT_CELL_WIDTH_DOTS = RULE_DOTS_PER_COLUMN
TEXT_CELL_HEIGHT_DOTS = 24


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


def render_receipt(batch: TaskBatch, printer: PrinterConfig, now: datetime) -> bytes:
    columns = printer.paper_columns
    output = bytearray()

    output += escpos.command(escpos.ESC, b"@")
    output += escpos.select_code_page(printer.code_page)
    if printer.supports_print_density:
        output += escpos.select_print_density(printer.print_density)
    if printer.supports_print_speed:
        output += escpos.select_print_speed(printer.print_speed)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    if printer.image_logo:
        output += _logo_bytes(columns)
    output += escpos.text("", printer.code_page)
    output += escpos.command(escpos.ESC, b"E", b"\x01")
    output += escpos.centered(RECEIPT_TITLE, columns, printer.code_page)
    output += escpos.command(escpos.ESC, b"E", b"\x00")
    output += _rule(columns, printer.code_page)

    output += escpos.command(escpos.ESC, b"a", b"\x00")
    output += _render_lines(_metadata_lines(batch, now, columns), printer.code_page)
    output += _rule(columns, printer.code_page)

    if batch.tasks:
        for index, task in enumerate(batch.tasks, start=1):
            output += _render_task(index, task, columns, printer.code_page)
    else:
        output += escpos.text("No tasks for this print window.", printer.code_page)
        output += escpos.text("", printer.code_page)

    output += _rule(columns, printer.code_page)
    output += escpos.command(escpos.ESC, b"a", b"\x01")
    output += escpos.text(BRAND, printer.code_page)
    output += escpos.text("", printer.code_page)
    output += escpos.text("", printer.code_page)

    if printer.cut:
        output += escpos.cut()
    return bytes(output)


def render_receipt_preview(
    batch: TaskBatch, printer: PrinterConfig, now: datetime
) -> ReceiptPreview:
    payload = render_receipt(batch, printer, now)
    width_dots = printer.paper_columns * RULE_DOTS_PER_COLUMN
    image = _escpos_payload_to_image(
        payload,
        width_dots,
        printer.paper_columns,
        printer.code_page,
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return ReceiptPreview(
        png=buffer.getvalue(),
        width_dots=image.width,
        height_dots=image.height,
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


def _rule(columns: int, code_page: str) -> bytes:
    return (
        escpos.command(escpos.ESC, b"a", b"\x00")
        + escpos.horizontal_rule(
            columns,
            dots_per_column=RULE_DOTS_PER_COLUMN,
            thickness_dots=RULE_THICKNESS_DOTS,
        )
        + escpos.text("", code_page)
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


def _render_lines(lines: tuple[str, ...], code_page: str) -> bytes:
    return b"".join(escpos.text(line, code_page) for line in lines)


def _wrapped(value: str, columns: int) -> list[str]:
    return wrap(value, width=columns, break_long_words=False) or [""]


def _preview_rule(columns: int) -> str:
    return "=" * columns


def _escpos_payload_to_image(
    payload: bytes,
    width_dots: int,
    columns: int,
    code_page: str,
) -> Image.Image:
    font, bold_font, text_height = _preview_fonts()
    alignment = 0
    bold = False
    y = 0
    strips: list[tuple[int, Image.Image]] = []
    text_buffer = bytearray()

    def flush_text(*, force_line_feed: bool = False) -> None:
        nonlocal y, text_buffer
        if not text_buffer and not force_line_feed:
            return
        line = bytes(text_buffer).decode(code_page, errors="replace")
        text_buffer.clear()
        strip = _text_line_to_image(
            line,
            bold_font if bold else font,
            columns,
            text_height,
        )
        x = _aligned_x(width_dots, _text_content_width(line, columns), alignment)
        strips.append((x, strip))
        y += strip.height

    i = 0
    while i < len(payload):
        byte = payload[i]
        if byte == 0x0A:
            flush_text(force_line_feed=True)
            i += 1
            continue

        if byte == 0x1B and i + 1 < len(payload):
            command = payload[i + 1]
            if command == 0x40:
                alignment = 0
                bold = False
                i += 2
                continue
            if command == 0x61 and i + 2 < len(payload):
                alignment = payload[i + 2]
                i += 3
                continue
            if command == 0x45 and i + 2 < len(payload):
                bold = payload[i + 2] != 0
                i += 3
                continue
            if command == 0x74 and i + 2 < len(payload):
                i += 3
                continue

        if byte == 0x1D and i + 1 < len(payload):
            command = payload[i + 1]
            if command == 0x28:
                if i + 5 < len(payload) and payload[i + 2] == 0x4B:
                    data_length = payload[i + 3] + (payload[i + 4] << 8)
                    i += 5 + data_length
                    continue
                if i + 4 < len(payload):
                    data_length = payload[i + 2] + (payload[i + 3] << 8)
                    i += 4 + data_length
                    continue
            if command == 0x76 and i + 7 < len(payload) and payload[i + 2] == ord("0"):
                flush_text()
                width_bytes = payload[i + 4] + (payload[i + 5] << 8)
                height = payload[i + 6] + (payload[i + 7] << 8)
                data_start = i + 8
                data_end = data_start + width_bytes * height
                raster = _raster_bytes_to_image(
                    payload[data_start:data_end], width_bytes, height
                )
                x = _aligned_x(width_dots, raster.width, alignment)
                strips.append((x, raster))
                y += raster.height
                i = data_end
                continue
            if command == 0x42 and i + 2 < len(payload):
                i += 3
                continue
            if command == 0x56:
                i += 4 if i + 3 < len(payload) else 2
                continue

        text_buffer.append(byte)
        i += 1

    flush_text()
    height = max(y, 1)
    preview = Image.new("L", (width_dots, height), 255)
    cursor_y = 0
    for x, strip in strips:
        preview.paste(strip, (x, cursor_y))
        cursor_y += strip.height
    return preview


def _preview_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, int]:
    try:
        return (
            ImageFont.truetype("DejaVuSansMono.ttf", 18),
            ImageFont.truetype("DejaVuSansMono-Bold.ttf", 18),
            TEXT_CELL_HEIGHT_DOTS,
        )
    except OSError:
        font = ImageFont.load_default(size=18)
        return font, font, TEXT_CELL_HEIGHT_DOTS


def _text_line_to_image(
    line: str,
    font: ImageFont.ImageFont,
    columns: int,
    text_height: int,
) -> Image.Image:
    strip = Image.new("L", (columns * TEXT_CELL_WIDTH_DOTS, text_height), 255)
    draw = ImageDraw.Draw(strip)
    for col, char in enumerate(line[:columns]):
        x = col * TEXT_CELL_WIDTH_DOTS
        draw.text((x, 1), char, font=font, fill=0)
    return strip


def _text_content_width(line: str, columns: int) -> int:
    if not line:
        return 0
    return min(len(line), columns) * TEXT_CELL_WIDTH_DOTS


def _raster_bytes_to_image(data: bytes, width_bytes: int, height: int) -> Image.Image:
    image = Image.new("1", (width_bytes * 8, height), 255)
    pixels = image.load()
    for y in range(height):
        row = y * width_bytes
        for x_byte in range(width_bytes):
            value = data[row + x_byte] if row + x_byte < len(data) else 0
            for bit in range(8):
                if value & (0x80 >> bit):
                    pixels[x_byte * 8 + bit, y] = 0
    return image


def _aligned_x(width_dots: int, content_width: int, alignment: int) -> int:
    if alignment == 1:
        return max((width_dots - content_width) // 2, 0)
    if alignment == 2:
        return max(width_dots - content_width, 0)
    return 0


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
