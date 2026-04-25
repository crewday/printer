from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml

from printer_app.models import PrinterProfile

PROFILE_PACKAGE = "printer_app.profiles"


@lru_cache
def load_profiles() -> tuple[PrinterProfile, ...]:
    profile_dir = files(PROFILE_PACKAGE)
    profiles = [
        _parse_profile(
            path.name.removesuffix(".yaml"), yaml.safe_load(path.read_text())
        )
        for path in profile_dir.iterdir()
        if path.name.endswith((".yaml", ".yml"))
    ]
    return tuple(sorted(profiles, key=lambda profile: profile.name.lower()))


def profile_ids() -> set[str]:
    return {profile.id for profile in load_profiles()}


def get_profile(profile_id: str) -> PrinterProfile | None:
    return next(
        (profile for profile in load_profiles() if profile.id == profile_id),
        None,
    )


def default_profile() -> PrinterProfile:
    return get_profile("epson_tm_t20ii") or load_profiles()[0]


def _parse_profile(profile_id: str, raw: Any) -> PrinterProfile:
    if not isinstance(raw, dict):
        raise ValueError(f"invalid printer profile: {profile_id}")

    code_pages = raw.get("code_pages") or ["cp437"]
    if not isinstance(code_pages, list):
        raise ValueError(f"profile {profile_id} code_pages must be a list")

    return PrinterProfile(
        id=profile_id,
        name=str(raw.get("name", profile_id)),
        description=str(raw.get("description", "")),
        paper_width=str(raw.get("paper_width", "")),
        cut_behavior=str(raw.get("cut_behavior", "")),
        code_pages=tuple(str(code_page) for code_page in code_pages),
        image_logo=bool(raw.get("image_logo", True)),
        supports_print_density=bool(raw.get("supports_print_density", True)),
        supports_print_speed=bool(raw.get("supports_print_speed", True)),
        paper_columns=int(raw.get("paper_columns", 48)),
        print_density=int(raw.get("print_density", 0)),
        print_speed=int(raw.get("print_speed", 0)),
        cut=bool(raw.get("cut", True)),
    )
