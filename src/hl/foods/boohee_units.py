"""薄荷量词标签解析、大小排除与重复量词核对。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from hl.language import units as language_units

# 量词栏：“1盘蛋炒饭(300.0克)”“1只(中)鸡蛋(60.0克，可食部分53.0克)”“1瓶果粒橙(450.0毫升)”
AMOUNT = re.compile(r"\((\d+(?:\.\d+)?)(克|毫升)(?:，可食部分(\d+(?:\.\d+)?)克)?\)$")

HEAD = re.compile(r"(\d+(?:\.\d+)?|半)([^\d()（）/]{1,4}?)(?:\(([中大小])\))?")

STANDARD = "标准"  # “标准(100克)”“标准(100毫升)”：说的是营养按什么算，不是量词

GENERIC = {form for forms in language_units.UNIT_FORMS.values() for form in forms}

SAME = 0.05  # 同一个量词出现几次、折成每 1 个的克数相差在 5% 以内算同一个

UNITS = "units"  # 收下的量词

UNITS_SIZED = "units_sized"  # 带“大”“小”的，不收

UNITS_GENERIC = "units_generic"  # 克、毫升这类通用单位，引擎自己会算，不收

UNITS_UNPARSED = "units_unparsed"  # 解析不了的，丢掉

UNITS_CONFLICT = "units_conflict"  # 同一个量词几处的克数对不上，整个丢掉


def _number(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def parse_units(labels: list[str], name: str, counts: Counter[str]) -> tuple[dict[str, Any], bool]:
    """量词栏 →（每 1 个量词合多少，营养是不是按每 100 毫升算），按增补第 13.1 节：

    带“(中)”的当作不带大小；带“(大)”“(小)”的、量词以“大”“小”开头的不收；数字不是 1 的折成
    每 1 个；带“可食部分”的记 {gross_g, g}；毫升的记 {ml}；通用单位、解析不了的丢掉。
    同一个量词出现几次：折成每 1 个相差不到 5% 的取数字最小的那处，相差大的整个量词丢掉。
    counts 里累计各项条数。
    """
    found: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    per_ml = False
    for label in labels:
        if label.startswith(STANDARD):
            per_ml = per_ml or "毫升" in label
            continue
        amount = AMOUNT.search(label)
        head = label[: amount.start()] if amount else ""
        spec = (
            HEAD.fullmatch(head[: len(head) - len(name)].strip()) if head.endswith(name) else None
        )
        if amount is None or spec is None:
            counts[UNITS_UNPARSED] += 1
            continue
        number, unit, size = spec[1], spec[2].strip(), spec[3]
        if size in ("大", "小") or unit[0] in "大小":
            counts[UNITS_SIZED] += 1
            continue
        if unit[0] == "中" and len(unit) > 1:
            unit = unit[1:]
        n = 0.5 if number == "半" else float(number)
        if unit in GENERIC or n <= 0:
            counts[UNITS_GENERIC if unit in GENERIC else UNITS_UNPARSED] += 1
            continue
        whole, kind, edible = float(amount[1]), amount[2], amount[3]
        if kind == "毫升":
            each: dict[str, Any] = {"ml": _number(whole / n)}
        elif edible is not None:
            each = {"gross_g": _number(whole / n), "g": _number(float(edible) / n)}
        else:
            each = {"g": _number(whole / n)}
        found.setdefault(unit, []).append((n, each))
    units: dict[str, Any] = {}
    for unit, seen in found.items():
        seen.sort(key=lambda pair: pair[0])
        first = seen[0][1]
        if all(_same(first, each) for _, each in seen[1:]):
            units[unit] = first
            counts[UNITS] += 1
        else:
            counts[UNITS_CONFLICT] += 1
    return units, per_ml


def _same(one: dict[str, Any], other: dict[str, Any]) -> bool:
    if ("ml" in one) != ("ml" in other):
        return False
    a, b = one.get("g", one.get("ml")), other.get("g", other.get("ml"))
    return abs(a - b) <= SAME * max(a, b)
