from __future__ import annotations

import pytest

from printer_app.table import (
    DOUBLE,
    ColspanCell,
    ColumnDef,
    TableBuilder,
)


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
    with pytest.raises(ValueError, match="cell spans"):
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


# --- external_borders=False ---


def test_no_external_total_width() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(20), ColumnDef(8)],
        external_borders=False,
    )
    assert t.total_width == 4 + 20 + 8 + 2


def test_no_external_top_border() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        external_borders=False,
    )
    assert t.top_border() == "────┬──────────"


def test_no_external_bottom_border() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        external_borders=False,
    )
    assert t.bottom_border() == "────┴──────────"


def test_no_external_separator() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        external_borders=False,
    )
    assert t.separator() == "────┼──────────"


def test_no_external_row() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left")],
        external_borders=False,
    )
    lines = t.row(["Hi", "World"])
    assert lines == [" Hi │World     "]


def test_no_external_single_col() -> None:
    t = TableBuilder(
        [ColumnDef(10)],
        external_borders=False,
    )
    assert t.total_width == 10
    assert t.top_border() == "──────────"
    assert t.separator() == "──────────"
    assert t.row(["Hi"]) == ["Hi        "]


# --- internal_borders=False ---


def test_no_internal_total_width() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(20), ColumnDef(8)],
        internal_borders=False,
    )
    assert t.total_width == 4 + 20 + 8 + 4


def test_no_internal_top_border() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        internal_borders=False,
    )
    assert t.top_border() == "┌───────────────┐"


def test_no_internal_bottom_border() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        internal_borders=False,
    )
    assert t.bottom_border() == "└───────────────┘"


def test_no_internal_separator() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        internal_borders=False,
    )
    assert t.separator() == "├───────────────┤"


def test_no_internal_row() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left")],
        internal_borders=False,
    )
    lines = t.row(["Hi", "World"])
    assert lines == ["│ Hi  World     │"]


def test_no_internal_single_col() -> None:
    t = TableBuilder(
        [ColumnDef(10)],
        internal_borders=False,
    )
    assert t.total_width == 12
    assert t.top_border() == "┌──────────┐"
    assert t.row(["Hi"]) == ["│Hi        │"]


# --- both off ---


def test_no_borders_total_width() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        external_borders=False,
        internal_borders=False,
    )
    assert t.total_width == 4 + 10 + 1


def test_no_borders_top_border_empty() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10)],
        external_borders=False,
        internal_borders=False,
    )
    assert t.top_border() == ""
    assert t.bottom_border() == ""
    assert t.separator() == ""


def test_no_borders_row() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left")],
        external_borders=False,
        internal_borders=False,
    )
    lines = t.row(["Hi", "World"])
    assert lines == [" Hi  World     "]


def test_no_borders_single_col() -> None:
    t = TableBuilder(
        [ColumnDef(10)],
        external_borders=False,
        internal_borders=False,
    )
    assert t.total_width == 10
    assert t.row(["Hi"]) == ["Hi        "]


# --- ColspanCell ---


def test_colspan_basic() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left"), ColumnDef(6, "right")]
    )
    lines = t.row([ColspanCell("Merged", span=2, align="center"), "42"])
    assert lines[0] == "│     Merged    │    42│"
    assert len(lines[0]) == t.total_width


def test_colspan_full_width() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left"), ColumnDef(6, "right")]
    )
    lines = t.row([ColspanCell("Full Width Title", span=3, align="center")])
    assert lines[0] == "│   Full Width Title   │"
    assert len(lines[0]) == t.total_width


def test_colspan_header_and_data() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left"), ColumnDef(6, "right")]
    )
    output = [
        t.top_border(),
        *t.row([ColspanCell("Report", span=3, align="center")]),
        t.separator(),
        *t.row(["#", "Name", "Time"], align_override="center"),
        t.separator(),
        *t.row(["1", "Hello", "08:00"]),
        t.bottom_border(),
    ]
    assert len(output) == 7
    assert output[0] == "┌────┬──────────┬──────┐"
    assert output[1] == "│        Report        │"
    assert output[5] == "│ 1  │Hello     │ 08:00│"


def test_colspan_with_no_internal() -> None:
    t = TableBuilder(
        [ColumnDef(4), ColumnDef(10), ColumnDef(6)],
        internal_borders=False,
    )
    lines = t.row([ColspanCell("Wide", span=2), "end"])
    assert lines[0] == "│Wide            end   │"
    assert len(lines[0]) == t.total_width


def test_colspan_word_wrap() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(6)])
    lines = t.row([ColspanCell("A long merged text", span=2)])
    assert len(lines) > 1
    assert all(len(line) == t.total_width for line in lines)


def test_colspan_span_exceeds_columns_raises() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(6)])
    with pytest.raises(ValueError, match="cell spans"):
        t.row([ColspanCell("x", span=3)])


def test_colspan_invalid_span_raises() -> None:
    t = TableBuilder([ColumnDef(4)])
    with pytest.raises(ValueError, match="colspan must be >= 1"):
        t.row([ColspanCell("x", span=0)])


def test_colspan_total_spans_exceed_raises() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(6)])
    with pytest.raises(ValueError, match="cell spans"):
        t.row(["a", "b", ColspanCell("c", span=1)])


def test_colspan_uses_first_column_align() -> None:
    t = TableBuilder([ColumnDef(6, "right"), ColumnDef(6, "left")])
    lines = t.row([ColspanCell("Hi", span=2)])
    assert lines[0] == "│           Hi│"


def test_colspan_align_override_takes_priority() -> None:
    t = TableBuilder([ColumnDef(6, "right"), ColumnDef(6, "left")])
    lines = t.row([ColspanCell("Hi", span=2)], align_override="center")
    assert lines[0] == "│      Hi     │"


# --- Borders with adjacent colspan ---


def test_top_border_flat_for_full_colspan() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    border = t.top_border(adjacent=[ColspanCell("Title", span=3)])
    assert border == "┌──────────────────────┐"


def test_bottom_border_flat_for_full_colspan() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    border = t.bottom_border(adjacent=[ColspanCell("Title", span=3)])
    assert border == "└──────────────────────┘"


def test_separator_flat_for_full_colspan_above() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    colspan = [ColspanCell("Title", span=3)]
    sep = t.separator(above=colspan)
    assert sep == "├────┬──────────┬──────┤"


def test_separator_flat_for_full_colspan_below() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    colspan = [ColspanCell("Title", span=3)]
    sep = t.separator(below=colspan)
    assert sep == "├────┴──────────┴──────┤"


def test_separator_flat_for_full_colspan_both() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    colspan = [ColspanCell("Title", span=3)]
    sep = t.separator(above=colspan, below=colspan)
    assert sep == "├──────────────────────┤"


def test_top_border_partial_colspan() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    border = t.top_border(adjacent=[ColspanCell("A", span=2), "B"])
    assert border == "┌───────────────┬──────┐"


def test_separator_partial_colspan_above() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    sep = t.separator(above=["A", ColspanCell("B", span=2)])
    assert sep == "├────┼──────────┬──────┤"


def test_separator_partial_colspan_below() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10), ColumnDef(6)])
    sep = t.separator(below=["A", ColspanCell("B", span=2)])
    assert sep == "├────┼──────────┴──────┤"


def test_border_adjacent_no_colspan_matches_default() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10)])
    assert t.top_border(adjacent=["A", "B"]) == t.top_border()
    assert t.separator(above=["A", "B"], below=["C", "D"]) == t.separator()
    assert t.bottom_border(adjacent=["A", "B"]) == t.bottom_border()


def test_border_adjacent_none_matches_default() -> None:
    t = TableBuilder([ColumnDef(4), ColumnDef(10)])
    assert t.top_border(adjacent=None) == t.top_border()
    assert t.separator(above=None, below=None) == t.separator()


def test_colspan_table_full_render() -> None:
    t = TableBuilder(
        [ColumnDef(4, "center"), ColumnDef(10, "left"), ColumnDef(6, "right")]
    )
    title = [ColspanCell("Report", span=3, align="center")]
    output = [
        t.top_border(adjacent=title),
        *t.row(title),
        t.separator(above=title),
        *t.row(["#", "Name", "Time"], align_override="center"),
        t.separator(),
        *t.row(["1", "Hello", "08:00"]),
        t.bottom_border(adjacent=title),
    ]
    assert output[0] == "┌──────────────────────┐"
    assert output[1] == "│        Report        │"
    assert output[2] == "├────┬──────────┬──────┤"
    assert output[-1] == "└──────────────────────┘"
