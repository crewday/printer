from __future__ import annotations

from importlib.resources import files


def test_static_template_editor_is_packaged() -> None:
    assert files("printer_app").joinpath("static/template-editor.js").is_file()
