from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from textwrap import wrap


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

    @property
    def total_width(self) -> int:
        content = sum(c.width for c in self._columns)
        n = len(self._columns)
        if self._external:
            return content + n + 1
        return content + n - 1

    def top_border(self) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.tl if self._external else ""
        mid = self._style.tj if self._internal else self._style.h
        right = self._style.tr if self._external else ""
        return self._border(left, mid, right)

    def bottom_border(self) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.bl if self._external else ""
        mid = self._style.bj if self._internal else self._style.h
        right = self._style.br if self._external else ""
        return self._border(left, mid, right)

    def separator(self) -> str:
        if not self._external and not self._internal:
            return ""
        left = self._style.lj if self._external else ""
        mid = self._style.x if self._internal else self._style.h
        right = self._style.rj if self._external else ""
        return self._border(left, mid, right)

    def row(
        self,
        cells: Sequence[str | ColspanCell],
        *,
        align_override: str | None = None,
    ) -> list[str]:
        spans = _parse_cells(cells, len(self._columns))
        render_cols = _build_render_cols(
            spans, self._columns, align_override
        )
        wrapped = [
            wrap(str(rc.text), width=rc.width, break_long_words=True) or [""]
            for rc in render_cols
        ]
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

    def _border(self, left: str, mid: str, right: str) -> str:
        if not self._internal:
            width = sum(c.width for c in self._columns) + len(self._columns) - 1
            return left + self._style.h * width + right
        segments: list[str] = [left]
        for i, col in enumerate(self._columns):
            segments.append(self._style.h * col.width)
            segments.append(mid if i < len(self._columns) - 1 else right)
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
        result.append(_RenderCol(cell.text, width, align))
        col_idx += cell.span
    return result


def _align_text(text: str, width: int, align: str) -> str:
    if align == "center":
        return text.center(width)[:width]
    if align == "right":
        return text.rjust(width)[:width]
    return text.ljust(width)[:width]
