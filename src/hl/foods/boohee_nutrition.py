"""薄荷营养字段解析与热量一致性校验。"""

from __future__ import annotations

from typing import Any

from hl.foods.boohee_units import AMOUNT as AMOUNT
from hl.foods.boohee_units import GENERIC as GENERIC
from hl.foods.boohee_units import HEAD as HEAD
from hl.foods.boohee_units import SAME as SAME
from hl.foods.boohee_units import STANDARD as STANDARD
from hl.foods.boohee_units import UNITS as UNITS
from hl.foods.boohee_units import UNITS_CONFLICT as UNITS_CONFLICT
from hl.foods.boohee_units import UNITS_GENERIC as UNITS_GENERIC
from hl.foods.boohee_units import UNITS_SIZED as UNITS_SIZED
from hl.foods.boohee_units import UNITS_UNPARSED as UNITS_UNPARSED
from hl.foods.boohee_units import _number as _number
from hl.foods.boohee_units import _same as _same
from hl.foods.boohee_units import parse_units as parse_units

# all.csv 的列 → 副本字段：每 100 克（或每 100 毫升）的含量，钠是毫克
COLUMNS = {
    "热量": "kcal",
    "蛋白质": "protein",
    "脂肪": "fat",
    "碳水化合物": "carb",
    "纤维素": "fiber",
    "钠": "sodium",
}

NUTRIENTS = tuple(COLUMNS.values())

# 原数据里表示没有数据的写法（“一”是抓取时把破折号写成了汉字一）
UNKNOWN_MARKS = ("", "一", "—", "-")


def parse_value(raw: str) -> float | None:
    """原始取值 → 数值；没有数据的写法是 None。不是数的抛 ValueError。"""
    text = raw.strip()
    if text in UNKNOWN_MARKS:
        return None
    value = float(text)
    return int(value) if value.is_integer() else value


def consistent(food: dict[str, Any], drink: bool) -> bool:
    """增补第 13.3 节的热量自洽：高 = 4×蛋白质＋4×碳水＋9×脂肪，低 = 高 − 4×纤维。

    热量低于 0.7×低 − 10、或高于 1.3×高 ＋ 10 的对不上。饮料和名称含“酒”的只查偏低一边
    （酒精的热量不在三大营养素里）。蛋白质、脂肪、碳水有一样没有数据的，按 0 算，也只查偏低
    一边：少算了的那一样只会让“高”偏低。纤维没有数据的按 0 算。
    """
    kcal = food["kcal"]
    macros = [food[key] for key in ("protein", "carb", "fat")]
    protein, carb, fat = (value or 0 for value in macros)
    high = 4 * protein + 4 * carb + 9 * fat
    low = high - 4 * (food["fiber"] or 0)
    if kcal < 0.7 * low - 10:
        return False
    return drink or None in macros or kcal <= 1.3 * high + 10
