from __future__ import annotations

from datetime import datetime

from printer_app.cron import cron_matches, validate_cron_or_empty


def test_cron_matches_lists_ranges_and_steps() -> None:
    now = datetime(2026, 4, 27, 8, 30)

    assert cron_matches("*/30 8-18 * * 1-5", now) is True
    assert cron_matches("0 8 * * 1-5", now) is False
    assert cron_matches("30 7,8 * * 1", now) is True


def test_cron_supports_sunday_as_zero_or_seven() -> None:
    sunday = datetime(2026, 4, 26, 8, 0)

    assert cron_matches("0 8 * * 0", sunday) is True
    assert cron_matches("0 8 * * 7", sunday) is True


def test_cron_validation_rejects_bad_values() -> None:
    try:
        validate_cron_or_empty("60 8 * * *")
    except ValueError as exc:
        assert "between 0 and 59" in str(exc)
    else:
        raise AssertionError("invalid minute should fail cron validation")
