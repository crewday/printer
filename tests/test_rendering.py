from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from printer_app.models import PrinterConfig, ReceiptTask, TaskBatch
from printer_app.renderer import receipt_text_preview, render_receipt


def _printer() -> PrinterConfig:
    return PrinterConfig(
        type="network_escpos",
        profile="epson_tm_t20ii",
        host="127.0.0.1",
        port=9100,
        timeout_seconds=5,
        paper_columns=48,
        print_density=8,
        print_speed=6,
        cut=True,
    )


def test_receipt_preview_contains_required_fields() -> None:
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("Asia/Dubai"))
    batch = TaskBatch(
        worker_name="Vincent",
        source_label="Mock tasks",
        generated_at=now,
        tasks=(
            ReceiptTask(id="1", title="Prepare Villa Sud", property_name="Villa Sud"),
        ),
    )

    preview = receipt_text_preview(batch, now, 48)

    assert "Worker: Vincent" in preview
    assert "Printed: 2026-04-25 08:30 +04" in preview
    assert "Prepare Villa Sud" in preview


def test_receipt_renders_escpos_bytes_with_logo_and_cut() -> None:
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("Asia/Dubai"))
    batch = TaskBatch(
        worker_name="Vincent",
        source_label="Mock tasks",
        generated_at=now,
        tasks=(ReceiptTask(id="1", title="Prepare Villa Sud"),),
    )

    payload = render_receipt(batch, _printer(), now)

    assert payload.startswith(b"\x1b@")
    assert b"TASK LIST" in payload
    assert b"Prepare Villa Sud" in payload
    assert payload.endswith(b"\x1dVA\x03")


def test_logo_raster_is_not_solid_black() -> None:
    from printer_app.renderer import _logo_bytes

    payload = _logo_bytes(48)
    raster = payload[8:]
    black_bits = sum(byte.bit_count() for byte in raster)
    total_bits = len(raster) * 8

    assert 0 < black_bits < total_bits * 0.45
