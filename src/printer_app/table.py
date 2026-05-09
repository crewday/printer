from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from textwrap import wrap

VALID_ALIGNS = frozenset({"left", "center", "right"})


@dataclass(frozen=True)
class BoxChars:
    h: str
    v: str
    tl: str
    tr: str
    bl: str
    br: str
    lj: str
    rj: str
    tj: str
    bj: str
    x: str


SINGLE = BoxChars(
    h="─",
    v="│",
    tl="┌",
    tr="┐",
    bl="└",
    br="┘",
    lj="├",
    rj="┤",
    tj="┬",
    bj="┴",
    x="┼",
)

DOUBLE = BoxChars(
    h="═",
    v="║",
    tl="╔",
    tr="╗",
    bl="╚",
    br="╝",
    lj="╠",
    rj="╣",
    tj="╦",
    bj="╩",
    x="╬",
)


@dataclass(frozen=True)
class ColumnDef:
    width: int
    align: str = "left"


@dataclass(frozen=True)
class ColspanCell:
    text: str
    span: int = 1
    align: str | None = None


@dataclass(frozen=True)
class _RenderCol:
    text: str
    width: int
    align: str


class TableBuilder:
    def __init__(
        self,
        columns: Sequence[ColumnDef],
        *,
        style: BoxChars | None = None,
        external_borders: bool = True,
        internal_borders: bool = True,
    ):
        self._columns = tuple(columns)
        self._style = style or SINGLE
        self._external = external_borders
        self._internal = internal_borders
        if not self._columns:
            raise ValueError("table must have at least one column")
        for column in self._columns:
            if column.width < 1:
                raise ValueError("table column widths must be >= 1")
            _validate_align(column.align)

    @property
    def total_width(self) -> int:
        return self._content_width + (2 if self._external else 0)

    @property
    def _content_width(self) -> int:
        return sum(c.width for c in self._columns) + len(self._columns) - 1

    def top_border(
        self, adjacent: Sequence[str | ColspanCell] | None = None
    ) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.tl if self._external else ""
        mid = self._style.tj if self._internal else self._style.h
        right = self._style.tr if self._external else ""
        return self._border(left, mid, right, adjacent)

    def bottom_border(
        self, adjacent: Sequence[str | ColspanCell] | None = None
    ) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.bl if self._external else ""
        mid = self._style.bj if self._internal else self._style.h
        right = self._style.br if self._external else ""
        return self._border(left, mid, right, adjacent)

    def separator(
        self,
        above: Sequence[str | ColspanCell] | None = None,
        below: Sequence[str | ColspanCell] | None = None,
    ) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.lj if self._external else ""
        right = self._style.rj if self._external else ""
        if above is not None or below is not None:
            return self._separator_border(left, right, above, below)
        mid = self._style.x if self._internal else self._style.h
        return self._border(left, mid, right)

    def row(
        self,
        cells: Sequence[str | ColspanCell],
        *,
        align_override: str | None = None,
    ) -> list[str]:
        if align_override is not None:
            _validate_align(align_override)
        spans = _parse_cells(cells, len(self._columns))
        render_cols = _build_render_cols(
            spans, self._columns, align_override
        )
        wrapped = [_wrap_cell(rc.text, rc.width) for rc in render_cols]
        max_lines = max(len(w) for w in wrapped)
        edge = self._style.v if self._external else ""
        join = self._style.v if self._internal else " "
        result: list[str] = []
        for line_idx in range(max_lines):
            parts: list[str] = []
            for col_idx, rc in enumerate(render_cols):
                text = (
                    wrapped[col_idx][line_idx]
                    if line_idx < len(wrapped[col_idx])
                    else ""
                )
                parts.append(_align_text(text, rc.width, rc.align))
            result.append(edge + join.join(parts) + edge)
        return result

    def _border(
        self,
        left: str,
        mid: str,
        right: str,
        adjacent: Sequence[str | ColspanCell] | None = None,
    ) -> str:
        if not self._internal:
            return left + self._style.h * self._content_width + right
        boundaries = _boundary_positions(adjacent, len(self._columns))
        return self._build_border(
            left,
            right,
            lambda i: mid if i in boundaries else self._style.h,
        )

    def _separator_border(
        self,
        left: str,
        right: str,
        above: Sequence[str | ColspanCell] | None,
        below: Sequence[str | ColspanCell] | None,
    ) -> str:
        if not self._internal:
            return left + self._style.h * self._content_width + right
        above_bounds = _boundary_positions(above, len(self._columns))
        below_bounds = _boundary_positions(below, len(self._columns))
        return self._build_border(
            left,
            right,
            lambda i: _separator_join(
                i, above_bounds, below_bounds, self._style
            ),
        )

    def _build_border(
        self,
        left: str,
        right: str,
        join_for_boundary: Callable[[int], str],
    ) -> str:
        segments: list[str] = [left]
        n = len(self._columns)
        for i, col in enumerate(self._columns):
            segments.append(self._style.h * col.width)
            if i < n - 1:
                segments.append(join_for_boundary(i))
            else:
                segments.append(right)
        return "".join(segments)


def _parse_cells(
    cells: Sequence[str | ColspanCell], num_columns: int
) -> list[ColspanCell]:
    result: list[ColspanCell] = []
    for cell in cells:
        if isinstance(cell, ColspanCell):
            if cell.span < 1:
                raise ValueError("colspan must be >= 1")
            result.append(cell)
        else:
            result.append(ColspanCell(str(cell), span=1))
    total_span = sum(c.span for c in result)
    if total_span > num_columns:
        raise ValueError(
            f"cell spans ({total_span}) exceed column count ({num_columns})"
        )
    while total_span < num_columns:
        result.append(ColspanCell("", span=1))
        total_span += 1
    return result


def _build_render_cols(
    spans: list[ColspanCell],
    columns: tuple[ColumnDef, ...],
    align_override: str | None,
) -> list[_RenderCol]:
    result: list[_RenderCol] = []
    col_idx = 0
    for cell in spans:
        spanned = columns[col_idx : col_idx + cell.span]
        width = sum(c.width for c in spanned)
        if cell.span > 1:
            width += cell.span - 1
        align = align_override or cell.align or spanned[0].align
        _validate_align(align)
        result.append(_RenderCol(cell.text, width, align))
        col_idx += cell.span
    return result


def _boundary_positions(
    cells: Sequence[str | ColspanCell] | None, num_columns: int
) -> set[int]:
    if cells is None:
        return set(range(num_columns - 1))
    spans = _parse_cells(cells, num_columns)
    boundaries: set[int] = set()
    col_idx = 0
    for cell in spans:
        col_idx += cell.span
        if col_idx < num_columns:
            boundaries.add(col_idx - 1)
    return boundaries


def _separator_join(
    boundary: int,
    above_bounds: set[int],
    below_bounds: set[int],
    style: BoxChars,
) -> str:
    has_above = boundary in above_bounds
    has_below = boundary in below_bounds
    if has_above and has_below:
        return style.x
    if has_below:
        return style.tj
    if has_above:
        return style.bj
    return style.h


def _wrap_cell(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.extend(
            wrap(raw_line, width=width, break_long_words=True) or [""]
        )
    return lines or [""]


def _validate_align(align: str) -> None:
    if align not in VALID_ALIGNS:
        raise ValueError(f"unsupported table alignment: {align}")


def _align_text(text: str, width: int, align: str) -> str:
    if align == "center":
        return text.center(width)[:width]
    if align == "right":
        return text.rjust(width)[:width]
    return text.ljust(width)[:width]
