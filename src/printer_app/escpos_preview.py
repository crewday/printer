from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from printer_app.escpos import CODE_PAGES

DEFAULT_FONT_A_CELL_WIDTH_DOTS = 12
DEFAULT_FONT_A_CELL_HEIGHT_DOTS = 24
DEFAULT_FONT_B_CELL_WIDTH_DOTS = 9
DEFAULT_FONT_B_CELL_HEIGHT_DOTS = 20

_CODE_PAGE_FROM_INDEX = {v: k for k, v in CODE_PAGES.items()}
_BOX_CHARS_HORIZONTAL = frozenset(
    "─═┬┴┼╦╩╬├┤╠╣┌┐└┘╔╗╚╝╒╕╘╛╞╡╤╧╪╫╓╖╙╜"
)


@dataclass(frozen=True)
class EscposPreview:
    png: bytes
    width_dots: int
    height_dots: int


@dataclass(frozen=True)
class PreviewFont:
    regular: ImageFont.ImageFont
    bold: ImageFont.ImageFont
    cell_width_dots: int
    cell_height_dots: int
    midline_y: int


def render_payload_to_png(
    payload: bytes,
    *,
    columns: int,
    code_page: str = "cp437",
    width_dots: int | None = None,
) -> EscposPreview:
    image = render_payload_to_image(
        payload,
        columns=columns,
        code_page=code_page,
        width_dots=width_dots,
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return EscposPreview(
        png=buffer.getvalue(),
        width_dots=image.width,
        height_dots=image.height,
    )


def render_payload_to_image(
    payload: bytes,
    *,
    columns: int,
    code_page: str = "cp437",
    width_dots: int | None = None,
) -> Image.Image:
    width_dots = width_dots or columns * DEFAULT_FONT_A_CELL_WIDTH_DOTS
    fonts = _preview_fonts()
    alignment = 0
    bold = False
    underline = 0
    font_name = "a"
    width_multiplier = 1
    height_multiplier = 1
    y = 0
    strips: list[tuple[int, Image.Image, int]] = []
    text_buffer = bytearray()
    active_cp = code_page
    line_spacing: int | None = None

    def flush_text(*, force_line_feed: bool = False) -> None:
        nonlocal y, text_buffer
        if not text_buffer and not force_line_feed:
            return
        line = bytes(text_buffer).decode(active_cp, errors="replace")
        text_buffer.clear()
        preview_font = fonts[font_name]
        strip = _text_line_to_image(
            line,
            preview_font.bold if bold else preview_font.regular,
            columns,
            preview_font.cell_width_dots,
            preview_font.cell_height_dots,
            width_multiplier,
            height_multiplier,
            underline,
            preview_font.midline_y,
        )
        content_width = _text_content_width(
            line,
            columns,
            preview_font.cell_width_dots,
            width_multiplier,
        )
        x = _aligned_x(width_dots, content_width, alignment)
        advance = line_spacing if line_spacing is not None else strip.height
        strips.append((x, strip, advance))
        y += advance

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
                flush_text()
                alignment = 0
                bold = False
                underline = 0
                font_name = "a"
                width_multiplier = 1
                height_multiplier = 1
                active_cp = code_page
                line_spacing = None
                i += 2
                continue
            if command == 0x33 and i + 2 < len(payload):
                line_spacing = payload[i + 2]
                i += 3
                continue
            if command == 0x32:
                line_spacing = None
                i += 2
                continue
            if command == 0x61 and i + 2 < len(payload):
                flush_text()
                alignment = payload[i + 2]
                i += 3
                continue
            if command == 0x45 and i + 2 < len(payload):
                flush_text()
                bold = payload[i + 2] != 0
                i += 3
                continue
            if command == 0x2D and i + 2 < len(payload):
                flush_text()
                underline = payload[i + 2]
                i += 3
                continue
            if command == 0x4D and i + 2 < len(payload):
                flush_text()
                font_name = "b" if payload[i + 2] == 1 else "a"
                i += 3
                continue
            if command == 0x74 and i + 2 < len(payload):
                active_cp = _CODE_PAGE_FROM_INDEX.get(
                    payload[i + 2], code_page
                )
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
                strips.append((x, raster, raster.height))
                y += raster.height
                i = data_end
                continue
            if command == 0x42 and i + 2 < len(payload):
                i += 3
                continue
            if command == 0x21 and i + 2 < len(payload):
                flush_text()
                size = payload[i + 2]
                width_multiplier = ((size >> 4) & 0x07) + 1
                height_multiplier = (size & 0x07) + 1
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
    for x, strip, advance in strips:
        preview.paste(strip, (x, cursor_y))
        cursor_y += advance
    return preview


def _preview_fonts() -> dict[str, PreviewFont]:
    try:
        font_a = ImageFont.truetype("DejaVuSansMono.ttf", 18)
        bold_a = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 18)
        font_b = ImageFont.truetype("DejaVuSansMono.ttf", 14)
        bold_b = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 14)
    except OSError:
        font_a = ImageFont.load_default(size=18)
        bold_a = font_a
        font_b = ImageFont.load_default(size=14)
        bold_b = font_b
    return {
        "a": PreviewFont(
            regular=font_a,
            bold=bold_a,
            cell_width_dots=DEFAULT_FONT_A_CELL_WIDTH_DOTS,
            cell_height_dots=DEFAULT_FONT_A_CELL_HEIGHT_DOTS,
            midline_y=_measure_midline(font_a, DEFAULT_FONT_A_CELL_HEIGHT_DOTS),
        ),
        "b": PreviewFont(
            regular=font_b,
            bold=bold_b,
            cell_width_dots=DEFAULT_FONT_B_CELL_WIDTH_DOTS,
            cell_height_dots=DEFAULT_FONT_B_CELL_HEIGHT_DOTS,
            midline_y=_measure_midline(font_b, DEFAULT_FONT_B_CELL_HEIGHT_DOTS),
        ),
    }


def _measure_midline(font: ImageFont.ImageFont, cell_height: int) -> int:
    try:
        probe = Image.new("L", (24, cell_height), 255)
        draw = ImageDraw.Draw(probe)
        draw.text((0, 1), "─", font=font, fill=0)
        best_y = cell_height // 2
        best_count = 0
        for y in range(cell_height):
            count = sum(1 for x in range(24) if probe.getpixel((x, y)) < 128)
            if count > best_count:
                best_count = count
                best_y = y
        return best_y if best_count > 0 else cell_height // 2
    except Exception:
        return cell_height // 2


def _text_line_to_image(
    line: str,
    font: ImageFont.ImageFont,
    columns: int,
    cell_width_dots: int,
    cell_height_dots: int,
    width_multiplier: int,
    height_multiplier: int,
    underline: int = 0,
    midline_y: int = 0,
) -> Image.Image:
    max_chars = _preview_text_columns(columns, cell_width_dots, width_multiplier)
    base = Image.new(
        "L",
        (max_chars * cell_width_dots, cell_height_dots),
        255,
    )
    draw = ImageDraw.Draw(base)
    for col, char in enumerate(line[:max_chars]):
        x = col * cell_width_dots
        draw.text((x, 1), char, font=font, fill=0)
    if underline and line:
        visible = min(len(line), max_chars)
        if visible:
            line_y = cell_height_dots - underline - 1
            draw.line(
                (0, line_y, visible * cell_width_dots - 1, line_y),
                fill=0,
                width=underline,
            )
    if midline_y > 0:
        for col, char in enumerate(line[:max_chars]):
            if char in _BOX_CHARS_HORIZONTAL:
                x_start = col * cell_width_dots
                draw.line(
                    (
                        x_start,
                        midline_y,
                        x_start + cell_width_dots - 1,
                        midline_y,
                    ),
                    fill=0,
                )
    if width_multiplier == 1 and height_multiplier == 1:
        return base
    return base.resize(
        (base.width * width_multiplier, base.height * height_multiplier),
        Image.Resampling.NEAREST,
    )


def _preview_text_columns(
    columns: int,
    cell_width_dots: int,
    width_multiplier: int,
) -> int:
    width_dots = columns * DEFAULT_FONT_A_CELL_WIDTH_DOTS
    return max(1, width_dots // (cell_width_dots * width_multiplier))


def _text_content_width(
    line: str,
    columns: int,
    cell_width_dots: int,
    width_multiplier: int,
) -> int:
    if not line:
        return 0
    visible_chars = min(
        len(line),
        _preview_text_columns(columns, cell_width_dots, width_multiplier),
    )
    return visible_chars * cell_width_dots * width_multiplier


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
