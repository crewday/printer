from __future__ import annotations

from PIL import Image

ESC = b"\x1b"
GS = b"\x1d"
CODE_PAGES = {
    "cp437": 0,
    "cp850": 2,
    "cp860": 3,
    "cp863": 4,
    "cp865": 5,
    "cp866": 17,
    "cp852": 18,
    "cp858": 19,
    "cp1252": 16,
}


def command(*parts: bytes) -> bytes:
    return b"".join(parts)


def text(line: str = "", code_page: str = "cp437") -> bytes:
    return f"{line}\n".encode(code_page, errors="replace")


def centered(line: str, columns: int, code_page: str = "cp437") -> bytes:
    return text(line[:columns].center(columns), code_page)


def select_font(font: str) -> bytes:
    fonts = {"a": 0, "b": 1}
    return command(ESC, b"M", bytes([fonts[font.lower()]]))


def select_text_size(width: int = 1, height: int = 1) -> bytes:
    if not 1 <= width <= 8:
        raise ValueError("text width multiplier must be between 1 and 8")
    if not 1 <= height <= 8:
        raise ValueError("text height multiplier must be between 1 and 8")
    size = ((width - 1) << 4) | (height - 1)
    return command(GS, b"!", bytes([size]))


def bold(enabled: bool) -> bytes:
    return command(ESC, b"E", b"\x01" if enabled else b"\x00")


def underline(mode: int = 1) -> bytes:
    if mode not in {0, 1, 2}:
        raise ValueError("underline mode must be 0, 1, or 2")
    return command(ESC, b"-", bytes([mode]))


def select_print_density(density: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x31", bytes([density]))


def select_print_speed(speed: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x32", bytes([speed]))


def set_line_spacing(n: int) -> bytes:
    if not 0 <= n <= 255:
        raise ValueError("line spacing must be between 0 and 255")
    return command(ESC, b"3", bytes([n]))


def reset_line_spacing() -> bytes:
    return command(ESC, b"2")


def select_code_page(code_page: str) -> bytes:
    return command(ESC, b"t", bytes([CODE_PAGES[code_page]]))


def cut() -> bytes:
    return command(GS, b"V", b"\x41", b"\x03")


def reverse_bar(columns: int, label: str, code_page: str = "cp437") -> bytes:
    padded = f" {label} "[:columns].center(columns)
    return (
        command(GS, b"B", b"\x01")
        + text(padded, code_page)
        + command(GS, b"B", b"\x00")
    )


def filled_raster_block(width_bytes: int, height_dots: int) -> bytes:
    x_l = width_bytes & 0xFF
    x_h = (width_bytes >> 8) & 0xFF
    y_l = height_dots & 0xFF
    y_h = (height_dots >> 8) & 0xFF
    return command(GS, b"v0", b"\x00", bytes([x_l, x_h, y_l, y_h])) + (
        b"\xff" * width_bytes * height_dots
    )


def horizontal_rule(
    columns: int,
    *,
    dots_per_column: int,
    thickness_dots: int,
) -> bytes:
    width_dots = columns * dots_per_column
    width_bytes = (width_dots + 7) // 8
    return filled_raster_block(width_bytes=width_bytes, height_dots=thickness_dots)


def raster_image(image: Image.Image) -> bytes:
    mono = image.convert("1")
    width, height = mono.size
    width_bytes = (width + 7) // 8
    data = bytearray()
    pixels = mono.load()
    for y in range(height):
        for x_byte in range(width_bytes):
            value = 0
            for bit in range(8):
                x = x_byte * 8 + bit
                if x < width and pixels[x, y] == 0:
                    value |= 0x80 >> bit
            data.append(value)

    x_l = width_bytes & 0xFF
    x_h = (width_bytes >> 8) & 0xFF
    y_l = height & 0xFF
    y_h = (height >> 8) & 0xFF
    return command(GS, b"v0", b"\x00", bytes([x_l, x_h, y_l, y_h]), bytes(data))
