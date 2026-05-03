from __future__ import annotations

import pytest

from printer_app.table import DOUBLE, SINGLE, ColumnDef, TableBuilder


def _three_col() -> TableBuilder:
    return TableBuilder(
        [
            ColumnDef(4, "center"),
            ColumnDef(20, "left"),
            ColumnDef(8, "right"),
        ]
    )


def test_total_width() -> None:
    t = _three_col()
    assert t.total_width == 4 + 20 + 8 + 4


def test_top_border() -> None:
    border = _three_col().top_border()
    assert border == "┌────┬────────────────────┬────────┐"


def test_bottom_border() -> None:
    border = _three_col().bottom_border()
    assert border == "└────┴────────────────────┴────────┘"


def test_separator() -> None:
    sep = _three_col().separator()
    assert sep == "├────┼────────────────────┼────────┤"


def test_double_top_border() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        style=DOUBLE,
    )
    assert t.top_border() == "╔════╦══════════╗"


def test_single_data_row() -> None:
    lines = _three_col().row(["1", "Hello", "08:00"])
    assert lines == ["│ 1  │Hello               │   08:00│"]


def test_header_row_centered() -> None:
    lines = _three_col().row(["#", "Name", "Time"], align_override="center")
    assert lines == ["│ #  │        Name        │  Time  │"]


def test_fewer_cells_padded() -> None:
    lines = _three_col().row(["1", "Hello"])
    assert lines == ["│ 1  │Hello               │        │"]


def test_no_cells() -> None:
    lines = _three_col().row([])
    assert lines == ["│    │                    │        │"]


def test_too_many_cells_raises() -> None:
    with pytest.raises(ValueError, match="expected at most 3"):
        _three_col().row(["a", "b", "c", "d"])


def test_empty_columns_raises() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        TableBuilder([])


def test_word_wrap() -> None:
    t = TableBuilder([ColumnDef(6, "left")])
    lines = t.row(["Hello World"])
    assert lines == ["│Hello │", "│World │"]


def test_word_wrap_multi_column() -> None:
    t = TableBuilder([ColumnDef(6, "left"), ColumnDef(6, "left")])
    lines = t.row(["Hello World", "Foo"])
    assert lines == ["│Hello │Foo   │", "│World │      │"]


def test_right_align() -> None:
    t = TableBuilder([ColumnDef(8, "right")])
    lines = t.row(["42"])
    assert lines == ["│      42│"]


def test_center_align() -> None:
    t = TableBuilder([ColumnDef(8, "center")])
    lines = t.row(["ab"])
    assert lines == ["│   ab   │"]


def test_long_text_truncated() -> None:
    t = TableBuilder([ColumnDef(4)])
    lines = t.row(["ABCDEFGHIJ"])
    assert all(len(line) == 6 for line in lines)
    assert "ABCD" in lines[0]


def test_single_column_table() -> None:
    t = TableBuilder([ColumnDef(10)])
    assert t.total_width == 12
    assert t.top_border() == "┌──────────┐"
    assert t.bottom_border() == "└──────────┘"
    assert t.separator() == "├──────────┤"
    assert t.row(["Hi"]) == ["│Hi        │"]


def test_numeric_cell() -> None:
    t = TableBuilder([ColumnDef(6, "right")])
    lines = t.row([123])
    assert lines == ["│   123│"]


def test_empty_string_cell() -> None:
    t = TableBuilder([ColumnDef(4)])
    lines = t.row([""])
    assert lines == ["│    │"]
