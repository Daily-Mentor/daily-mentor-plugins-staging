"""Shared helpers for compute modules."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from ..models import Cell, Row, Tooltip


def fmt_money(v: float | None, *, decimals: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"


def fmt_pct(v: float | None, *, decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{decimals}f}%"


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def month_label(d: date) -> str:
    return d.strftime("%b %Y")


def text_cell(coord: str, value: str, *, bold: bool = False, indent: int = 0) -> Cell:
    return Cell(coord=coord, value=value, fmt="text", bold=bold, indent=indent, confidence="derived")


def section_cell(coord: str, value: str) -> Cell:
    return Cell(coord=coord, value=value, fmt="text", bold=True, section_header=True, confidence="derived")


def money_cell(coord: str, value: float | None, *, tooltip: Tooltip | None = None,
               confidence: str = "provisional", decimals: int = 0,
               is_total: bool = False) -> Cell:
    return Cell(
        coord=coord,
        value=value,
        fmt="currency" if decimals == 0 else "currency_dec",
        tooltip=tooltip,
        confidence=confidence,
        is_total=is_total,
        is_missing=value is None,
    )


def pct_cell(coord: str, value: float | None, *, tooltip: Tooltip | None = None,
             confidence: str = "provisional") -> Cell:
    return Cell(
        coord=coord,
        value=value,
        fmt="pct",
        tooltip=tooltip,
        confidence=confidence,
        is_missing=value is None,
    )


def int_cell(coord: str, value: int | float | None, *, tooltip: Tooltip | None = None,
             confidence: str = "provisional") -> Cell:
    return Cell(
        coord=coord,
        value=value,
        fmt="int",
        tooltip=tooltip,
        confidence=confidence,
        is_missing=value is None,
    )


def make_row(cells: Iterable[Cell], *, is_total: bool = False, is_section: bool = False,
             expandable_key: str | None = None) -> Row:
    return Row(cells=list(cells), is_total=is_total, is_section=is_section, expandable_key=expandable_key)
