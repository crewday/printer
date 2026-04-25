from __future__ import annotations

from datetime import datetime


def validate_cron_or_empty(value: str) -> None:
    if not value:
        return
    _parse_cron(value)


def cron_matches(value: str, now: datetime) -> bool:
    minute, hour, day, month, weekday = _parse_cron(value)
    cron_weekday = (now.weekday() + 1) % 7
    return (
        _field_matches(minute, now.minute, 0, 59)
        and _field_matches(hour, now.hour, 0, 23)
        and _field_matches(day, now.day, 1, 31)
        and _field_matches(month, now.month, 1, 12)
        and _field_matches(weekday, cron_weekday, 0, 7, sunday_alias=True)
    )


def _parse_cron(value: str) -> tuple[str, str, str, str, str]:
    fields = value.split()
    if len(fields) != 5:
        raise ValueError("print_schedule.cron must be empty or a five-field cron")
    minute, hour, day, month, weekday = fields
    _validate_field(minute, 0, 59)
    _validate_field(hour, 0, 23)
    _validate_field(day, 1, 31)
    _validate_field(month, 1, 12)
    _validate_field(weekday, 0, 7, sunday_alias=True)
    return minute, hour, day, month, weekday


def _validate_field(
    expression: str,
    minimum: int,
    maximum: int,
    *,
    sunday_alias: bool = False,
) -> None:
    for token in expression.split(","):
        if not token:
            raise ValueError(f"invalid cron field: {expression}")
        _token_values(token, minimum, maximum, sunday_alias=sunday_alias)


def _field_matches(
    expression: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    sunday_alias: bool = False,
) -> bool:
    return value in {
        item
        for token in expression.split(",")
        for item in _token_values(token, minimum, maximum, sunday_alias=sunday_alias)
    }


def _token_values(
    token: str,
    minimum: int,
    maximum: int,
    *,
    sunday_alias: bool = False,
) -> range:
    base, step = _split_step(token)
    if base == "*":
        start = minimum
        end = maximum
    elif "-" in base:
        start_raw, end_raw = base.split("-", 1)
        start = _parse_value(start_raw, minimum, maximum, sunday_alias=sunday_alias)
        end = _parse_value(end_raw, minimum, maximum, sunday_alias=sunday_alias)
    else:
        start = _parse_value(base, minimum, maximum, sunday_alias=sunday_alias)
        end = start

    if step < 1:
        raise ValueError(f"invalid cron step: {token}")
    if start > end:
        raise ValueError(f"invalid cron range: {token}")
    return range(start, end + 1, step)


def _split_step(token: str) -> tuple[str, int]:
    if "/" not in token:
        return token, 1
    base, step_raw = token.split("/", 1)
    if not base or not step_raw:
        raise ValueError(f"invalid cron step: {token}")
    return base, int(step_raw)


def _parse_value(
    value: str,
    minimum: int,
    maximum: int,
    *,
    sunday_alias: bool,
) -> int:
    parsed = int(value)
    if sunday_alias and parsed == 7:
        return 0
    if not minimum <= parsed <= maximum:
        raise ValueError(f"cron value {parsed} must be between {minimum} and {maximum}")
    return parsed
