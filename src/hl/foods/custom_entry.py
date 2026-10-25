"""用户食品条目的份量换算、营养明细与展示语义。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hl.foods import table
from hl.foods.table_types import CONTENT, View, make_row
from hl.language import normalize as language_normalize
from hl.language import units as language_units

LABEL = "包装标签"

# 菜的“份、盘、碗”通用（增补第 6 节）：存的估算有其中一个，用户说另一个时按同样的量算，份量是大概的
DISH_UNITS = ("份", "盘", "碗")


# ---------- 一条 ----------
@dataclass(frozen=True)
class Entry:
    """用户库里的一条。problem 不为空是这一条结构不对或签名不对，不能用。"""

    name: str
    body: Mapping[str, Any]
    problem: str | None = None

    @property
    def food(self) -> bool:
        """是一种食物（包装标签或存下来的估算），不只是量词补充。"""
        return "per" in self.body

    @property
    def per(self) -> dict[str, Any]:
        return dict(self.body.get("per") or {})

    @property
    def parts(self) -> list[dict[str, Any]]:
        return list(self.body.get("parts") or [])

    @property
    def nutrition(self) -> dict[str, Any] | None:
        return self.body.get("nutrition")

    @property
    def units(self) -> dict[str, float]:
        """量词补充：量词 → 一个合多少克。"""
        return {unit: spec["g"] for unit, spec in (self.body.get("units") or {}).items()}

    def unit_date(self, unit: str) -> str:
        """量词补充是哪天存的。"""
        return str((self.body.get("units") or {}).get(unit, {}).get("date", ""))

    @property
    def src(self) -> str:
        return str(self.body.get("src", ""))

    @property
    def label(self) -> bool:
        return self.src == LABEL

    @property
    def per_shown(self) -> str:
        """per 的说法：“1碗”“100 克”“100 毫升”。"""
        per = self.per
        if "unit" in per:
            return f"{language_normalize.fmt(per['n'])}{per['unit']}"
        if "ml" in per:
            return f"{language_normalize.fmt(per['ml'])} 毫升"
        return f"{language_normalize.fmt(per.get('g', 100))} 克"

    def grams(self, n: float, unit: str) -> tuple[Decimal, bool] | None:
        """n 个 unit 合多少克，和是不是大概的（按量词补充、一份的重量折的）；折不了是 None。"""
        if unit in language_units.GRAMS:
            return Decimal(str(n)) * Decimal(str(language_units.GRAMS[unit])), False
        if unit in self.units:
            return Decimal(str(n)) * Decimal(str(self.units[unit])), True
        per = self.per
        if "unit" in per and unit == per["unit"] and self.body.get("serving_g"):
            each = Decimal(str(self.body["serving_g"])) / Decimal(str(per["n"]))
            return Decimal(str(n)) * each, True
        return None

    def same_unit(self, unit: str) -> str | None:
        """用户说的 unit 能不能当成 per 的量词：正好是它，或者都是菜的“份、盘、碗”（包装标签不算，
        它不是菜）。能的返回 per 的量词。"""
        per_unit = self.per.get("unit")
        if per_unit is None:
            return None
        if unit == per_unit:
            return per_unit
        dish = not self.label and unit in DISH_UNITS and per_unit in DISH_UNITS
        return per_unit if dish else None

    def factor(self, n: float, unit: str) -> tuple[Decimal, Decimal | None, bool] | None:
        """n 个 unit 是 per 的几倍、合多少克（不知道是 None）、是不是大概的；折不了是 None。

        先看 per 的量词本身，再按克数折（通用重量单位、量词补充），最后看菜的“份、盘、碗”通用。
        """
        per = self.per
        if "unit" in per and unit == per["unit"]:
            weight = self.grams(n, unit)
            return Decimal(str(n)) / Decimal(str(per["n"])), weight[0] if weight else None, False
        found = self._factor_by_weight(n, unit)
        if found is not None:
            return found
        same = self.same_unit(unit)
        if same is not None:
            weight = self.grams(n, same)
            return Decimal(str(n)) / Decimal(str(per["n"])), weight[0] if weight else None, True
        return None

    def _factor_by_weight(self, n: float, unit: str) -> tuple[Decimal, Decimal | None, bool] | None:
        per = self.per
        if "ml" in per and unit in language_units.MILLILITRES:
            ml = Decimal(str(n)) * Decimal(str(language_units.MILLILITRES[unit]))
            return ml / Decimal(str(per["ml"])), None, False
        weight = self.grams(n, unit)
        if weight is None:
            return None
        grams, approx = weight
        if "g" in per:
            return grams / Decimal(str(per["g"])), grams, approx
        if "unit" in per and self.body.get("serving_g"):  # serving_g 是 per 这个量的克数
            return grams / Decimal(str(self.body["serving_g"])), grams, approx
        return None

    def by_grams(self) -> bool:
        """能不能按克数折：每 100 克存的，或者知道一份多重的。"""
        return "g" in self.per or bool(self.body.get("serving_g"))

    def accepted(self) -> list[str]:
        """问份量时举的单位：per 的量词、量词补充里的、能按克折的加克。"""
        per = self.per
        units = [per["unit"]] if "unit" in per else []
        units += [unit for unit in self.units if unit not in units]
        if self.by_grams():
            units.append("g")
        if "ml" in per:
            units.append("ml")
        return units

    def kcal(self, foods: View) -> float | None:
        """per 这个量的热量；配方里有查不到、热量未知的原料是 None。"""
        if self.nutrition is not None:
            return float(self.nutrition["kcal"])
        total = 0.0
        for part in self.parts:
            food = foods.get(part["food"])
            if food is None or food.kcal is None:
                return None
            total += food.kcal * part["g"] / 100
        return total

    def rows(
        self, foods: View, times: Decimal, grams: Decimal | None, est: list[str], amount: str
    ) -> list[dict[str, Any]] | str:
        """按这一条记 per 的 times 倍：配方型拆成原料行（part_of 是名字），营养值型记一行
        my:<名字>（知道克数时带 g）。原料不在库里了、热量未知的，返回问题。"""
        marks = [*est, *([] if self.label else [CONTENT])]
        src = self.src
        if self.nutrition is not None:
            row: dict[str, Any] = {"food": table.join(table.CUSTOM, self.name), "name": self.name}
            row["amount"] = amount
            if grams is not None and grams > 0:
                row["g"] = table.round_half_up(grams, 1)
            for key in table.NUTRIENTS:
                value = self.nutrition.get(key)
                row[key] = (
                    None
                    if value is None
                    else table.round_half_up(Decimal(str(value)) * times, table.DIGITS[key])
                )
            row["src"] = src
            row["est"] = [mark for mark in table.MARKS if mark in marks]
            return [row]
        rows = []
        for part in self.parts:
            food = foods.get(part["food"])
            if food is None:
                return f"用户库里“{self.name}”的原料 {part['food']} 现在库里没有了"
            if food.kcal is None:
                return f"用户库里“{self.name}”的原料“{food.name}”的热量是未知"
            weight = Decimal(str(part["g"])) * times
            rows.append(make_row(part["food"], food, weight, src, marks, amount, self.name))
        return [row for row in rows if row["g"] > 0]

    def shown(self, foods: View) -> str:
        """tell_user 里怎么说这一条：“1碗约 429 千卡（面条 300 克、螺蛳 30 克）”
        “每 100 克约 51 千卡（……）”。"""
        kcal = table.round_half_up(self.kcal(foods) or 0, 0)
        head = f"{'' if 'unit' in self.per else '每 '}{self.per_shown}约 {kcal} 千卡"
        if not self.parts:
            return head
        names = []
        for part in self.parts:
            food = foods.get(part["food"])
            grams = language_normalize.fmt(round(part["g"], 1))
            names.append(f"{food.name if food else part['food']} {grams} 克")
        return f"{head}（{'、'.join(names)}）"
