from __future__ import annotations

from PIL import Image

ESC = b"\x1b"
GS = b"\x1d"


def command(*parts: bytes) -> bytes:
    return b"".join(parts)


def text(line: str = "") -> bytes:
    return f"{line}\n".encode("cp437", errors="replace")


def centered(line: str, columns: int) -> bytes:
    return text(line[:columns].center(columns))


def select_print_density(density: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x31", bytes([density]))


def select_print_speed(speed: int) -> bytes:
    return command(GS, b"(K", b"\x02\x00", b"\x32", bytes([speed]))


def cut() -> bytes:
    return command(GS, b"V", b"\x41", b"\x03")


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
