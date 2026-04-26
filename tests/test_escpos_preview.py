from __future__ import annotations

from printer_app import escpos
from printer_app.escpos_preview import render_payload_to_image, render_payload_to_png


def test_render_payload_to_png_returns_receipt_dimensions() -> None:
    payload = (
        escpos.command(escpos.ESC, b"@")
        + escpos.command(escpos.ESC, b"a", b"\x01")
        + escpos.bold(True)
        + escpos.text("Preview", "cp858")
        + escpos.bold(False)
        + escpos.cut()
    )

    preview = render_payload_to_png(
        payload,
        columns=48,
        code_page="cp858",
        width_dots=576,
    )

    assert preview.png.startswith(b"\x89PNG")
    assert preview.width_dots == 576
    assert preview.height_dots > 0


def test_render_payload_to_image_renders_raster_graphics() -> None:
    payload = (
        escpos.command(escpos.ESC, b"@")
        + escpos.filled_raster_block(width_bytes=2, height_dots=3)
    )

    image = render_payload_to_image(payload, columns=48, width_dots=576)

    assert image.size == (576, 3)
    assert image.getpixel((0, 0)) == 0
    assert image.getpixel((15, 2)) == 0
    assert image.getpixel((16, 0)) == 255
