from __future__ import annotations

from dataclasses import dataclass
from textwrap import wrap
from typing import Sequence


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


class TableBuilder:
    def __init__(
        self, columns: Sequence[ColumnDef], *, style: BoxChars | None = None
    ):
        self._columns = tuple(columns)
        self._style = style or SINGLE
        if not self._columns:
            raise ValueError("table must have at least one column")

    @property
    def total_width(self) -> int:
        return sum(c.width for c in self._columns) + len(self._columns) + 1

    def top_border(self) -> str:
        return self._border(self._style.tl, self._style.tj, self._style.tr)

    def bottom_border(self) -> str:
        return self._border(self._style.bl, self._style.bj, self._style.br)

    def separator(self) -> str:
        return self._border(self._style.lj, self._style.x, self._style.rj)

    def row(
        self,
        cells: Sequence[str],
        *,
        align_override: str | None = None,
    ) -> list[str]:
        if len(cells) > len(self._columns):
            raise ValueError(
                f"expected at most {len(self._columns)} cells, got {len(cells)}"
            )
        padded = list(cells) + [""] * (len(self._columns) - len(cells))
        wrapped = [
            wrap(str(cell), width=col.width, break_long_words=True) or [""]
            for cell, col in zip(padded, self._columns)
        ]
        max_lines = max(len(w) for w in wrapped)
        result: list[str] = []
        for line_idx in range(max_lines):
            parts: list[str] = []
            for col_idx, col in enumerate(self._columns):
                text = (
                    wrapped[col_idx][line_idx]
                    if line_idx < len(wrapped[col_idx])
                    else ""
                )
                align = align_override or col.align
                parts.append(_align_text(text, col.width, align))
            result.append(
                self._style.v + self._style.v.join(parts) + self._style.v
            )
        return result

    def _border(self, left: str, mid: str, right: str) -> str:
        segments: list[str] = [left]
        for i, col in enumerate(self._columns):
            segments.append(self._style.h * col.width)
            segments.append(mid if i < len(self._columns) - 1 else right)
        return "".join(segments)


def _align_text(text: str, width: int, align: str) -> str:
    if align == "center":
        return text.center(width)[:width]
    if align == "right":
        return text.rjust(width)[:width]
    return text.ljust(width)[:width]
