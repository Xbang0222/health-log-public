"""识别干品并生成按干重计算的提醒。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hl.foods.table_types import Boohee, Food, View
from hl.language import normalize as language_normalize

DRY_WATER = 20  # 每 100 克水分低于它的成分表条目是干品或粉（和两层兜底同一个界限）

DRY_NOTE_G = 100  # 干品、冲调前的粉用到超过这么多克时提醒


# ---------- 干品 ----------
def is_dry(food: Food) -> bool:
    """干品或粉（第 9 节）：成分表里每 100 克水分低于 20 克的；薄荷库整理时标了 dry 的
    （饮料类每 100 克超过 150 千卡、名称含粉、速溶、三合一、固体、干重的）。水分不知道的不算。"""
    if isinstance(food, Boohee):
        return food.dry
    return food.water is not None and food.water < DRY_WATER


def dry_note(food: Food, grams: float) -> str | None:
    """干品、冲调前的粉用到超过 100 克时，接在 tell_user 里的提醒；不用提醒是 None。

    多半是把冲好、做熟、泡发之后的重量按干的条目记了，热量会多出好几倍：说出按什么算的，
    请用户不对就说。grams 是这一条记下的克数。
    """
    if not is_dry(food) or grams <= DRY_NOTE_G:
        return None
    amount = language_normalize.fmt(round(grams, 1))
    if isinstance(food, Boohee):
        return (
            f"“{food.name}”是冲调前的粉，{amount} 克是按干粉算的；喝的是冲好的，请说用了多少克粉。"
        )
    return (
        f"“{food.name}”水分不到 {DRY_WATER}%，{amount} 克是按它本身算的；说的若是做熟、泡发、"
        "冲好之后的重量，这样算会多出好几倍，不对可以直接说。"
    )


def dry_notes(rows: Iterable[Mapping[str, Any]], foods: View) -> list[str]:
    """一次记下的明细行里，同一个干品、冲调前的粉合起来超过 100 克的，各一句提醒（dry_note）。

    估算通道按 parts 记下之后接在 tell_user 里（第 8.1、9 节）；est 行、查不到的编码不算。
    """
    grams: dict[str, float] = {}
    for row in rows:
        if isinstance(row.get("food"), str) and isinstance(row.get("g"), (int, float)):
            grams[row["food"]] = grams.get(row["food"], 0) + row["g"]
    notes = []
    for ref, total in grams.items():
        food = foods.get(ref)
        note = dry_note(food, total) if food is not None else None
        if note is not None:
            notes.append(note)
    return notes
