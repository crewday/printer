from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from printer_app.models import (
    PrinterConfig,
    ReceiptTask,
    ReceiptTemplateConfig,
    ReceiptTemplateSection,
    TaskBatch,
)
from printer_app.renderer import (
    receipt_text_preview,
    render_font_test,
    render_receipt,
    render_receipt_preview,
)


def _printer() -> PrinterConfig:
    return PrinterConfig(
        name="Default",
        type="network_escpos",
        profile="epson_tm_t20ii",
        host="127.0.0.1",
        port=9100,
        timeout_seconds=5,
        paper_columns=48,
        code_page="cp858",
        image_logo=True,
        supports_print_density=True,
        supports_print_speed=True,
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

    assert "Vincent, April 25th, 2026" in preview
    assert "Printed on April 25th, 2026 08:30:00 +04" in preview
    assert "Prepare Villa Sud" in preview
    assert "TASK LIST" not in preview
    assert "Source:" not in preview


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
    assert b"TASK LIST" not in payload
    assert b"Source:" not in payload
    assert b"Vincent, April 25th, 2026" in payload
    assert b"Printed on April 25th, 2026 08:30:00 +04" in payload
    assert b"\x1bM\x01" in payload
    assert b"\x1d!\x11" in payload
    assert b"\x1d!\x00" in payload
    assert b"Prepare Villa Sud" in payload
    assert payload.count(b"\x1dv0") >= 3
    assert payload.endswith(b"\x1dVA\x03")


def test_receipt_skips_disabled_profile_capability_commands() -> None:
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("Asia/Dubai"))
    batch = TaskBatch(
        worker_name="Vincent",
        source_label="Mock tasks",
        generated_at=now,
        tasks=(ReceiptTask(id="1", title="Prepare Villa Sud"),),
    )
    printer = replace(
        _printer(),
        image_logo=False,
        supports_print_density=False,
        supports_print_speed=False,
    )

    payload = render_receipt(batch, printer, now)

    assert b"\x1d(K\x02\x001" not in payload
    assert b"\x1d(K\x02\x002" not in payload
    assert b"\x1dv0" in payload


def test_receipt_preview_uses_configured_print_width() -> None:
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("Asia/Dubai"))
    batch = TaskBatch(
        worker_name="Vincent",
        source_label="Mock tasks",
        generated_at=now,
        tasks=(ReceiptTask(id="1", title="Prepare Villa Sud"),),
    )

    preview = render_receipt_preview(batch, _printer(), now)

    assert preview.png.startswith(b"\x89PNG")
    assert preview.width_dots == 48 * 12
    assert preview.height_dots > 0


def test_receipt_template_can_override_receipt_sections() -> None:
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("Asia/Dubai"))
    batch = TaskBatch(
        worker_name="Vincent",
        source_label="Mock tasks",
        generated_at=now,
        tasks=(ReceiptTask(id="1", title="Prepare Villa Sud"),),
    )
    template = ReceiptTemplateConfig(
        sections=(
            ReceiptTemplateSection(
                type="text",
                value="{{ brand }} for {{ worker_name }} ({{ task_count }})",
                align="center",
                bold=True,
            ),
            ReceiptTemplateSection(type="separator", trailing_blank=False),
            ReceiptTemplateSection(type="tasks"),
        )
    )

    payload = render_receipt(batch, _printer(), now, template)
    preview = receipt_text_preview(batch, now, 48, template)

    assert b"crew.day for Vincent (1)" in payload
    assert b"Printed on April 25th, 2026" not in payload
    assert b"Prepare Villa Sud" in payload
    assert "crew.day for Vincent (1)" in preview
    assert "Printed on April 25th, 2026" not in preview


def test_font_test_renders_escpos_feature_commands() -> None:
    payload = render_font_test(_printer())

    assert payload.startswith(b"\x1b@")
    assert b"FONT TEST" in payload
    assert b"\x1bM\x00" in payload
    assert b"\x1bM\x01" in payload
    assert b"\x1d!\x10" in payload
    assert b"\x1d!\x01" in payload
    assert b"\x1d!\x11" in payload
    assert b"\x1b-\x01" in payload
    assert b"\x1b-\x02" in payload
    assert b"\x1dB\x01" in payload
    assert "été à l'hôtel".encode("cp858") in payload
    assert "12€".encode("cp858") in payload
    assert b"Bitmap raster image" in payload
    assert payload.count(b"\x1dv0") >= 2
    assert payload.endswith(b"\x1dVA\x03")


def test_logo_raster_is_not_solid_black() -> None:
    from printer_app.renderer import _logo_bytes

    payload = _logo_bytes(48)
    raster = payload[8:]
    black_bits = sum(byte.bit_count() for byte in raster)
    total_bits = len(raster) * 8

    assert 0 < black_bits < total_bits * 0.45
