"""《中国食物成分表》原始数据的整理和质检（设计说明 7.3，第 2 步增补第 13.3 节）。

只在 hl foods build、hl foods fetch 时跑：读原始数据目录里的记录文件，整理成成分表副本
（.hl/cn6.json）的内容。副本的读取、核对哈希在 foods/table.py。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 原始字段 → 副本字段
FIELDS = {
    "edible": "edible",
    "energyKCal": "kcal",
    "protein": "protein",
    "fat": "fat",
    "CHO": "carb",
    "dietaryFiber": "fiber",
    "Na": "sodium",
    "water": "water",  # 只给两层兜底用（增补第 2.5 节：水分不到 20% 的干货不走兜底），不算营养
}
# 原始记录里可以没有的字段：没有就是未知
OPTIONAL = ("water",)
UNKNOWN_MARKS = ("", "—", "un")
MACROS = ("protein", "fat", "carb")
# 质检（增补第 13.3 节）：热量有数值、三大营养素全未知的条目，热量按未知处理
KCAL_UNKNOWN = "kcal_unknown"


@dataclass
class Built:
    """整理的结果：副本内容、问题（有就不能装）、质检的条数。"""

    doc: dict[str, Any]
    problems: list[str]
    quality: dict[str, int] = field(default_factory=dict)


def parse_value(raw: str) -> tuple[float | None, bool]:
    """原始取值 →（数值，是否微量）。Tr 记 0；带 * 的参考值取数值；—、空串、un 是未知。"""
    text = raw.strip()
    if text == "Tr":
        return 0.0, True
    if text in UNKNOWN_MARKS:
        return None, False
    number = text.removesuffix("*")
    return (int(number) if number.isdigit() else float(number)), False


def _convert(record: dict[str, Any]) -> dict[str, Any]:
    food: dict[str, Any] = {"name": record["foodName"]}
    trace = []
    for raw_key, key in FIELDS.items():
        raw = record.get(raw_key, "") if raw_key in OPTIONAL else record[raw_key]
        value, is_trace = parse_value(raw)
        food[key] = value
        if is_trace:
            trace.append(key)
    food["trace"] = trace
    return food


def _kcal_checked(food: dict[str, Any]) -> bool:
    """热量有数值、蛋白质脂肪碳水全未知：原书印错的（044501 薤的热量印成 1），热量改成未知。
    改了返回 True。"""
    if food["kcal"] is None or any(food[key] is not None for key in MACROS):
        return False
    food["kcal"] = None
    food["trace"] = [key for key in food["trace"] if key != "kcal"]
    return True


def read(raw_dir: Path, source: str, commit: str) -> Built:
    """读原始数据目录里的每个记录文件，整理成副本内容，同时做质检。"""
    foods: dict[str, Any] = {}
    problems: list[str] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{path.name} 不是合法的 JSON：{exc}")
            continue
        if not isinstance(records, list):
            continue  # 目录里的说明性文件（例如 enrich_log.json）不是记录
        for position, record in enumerate(records):
            try:
                code = record["foodCode"]
                converted = _convert(record)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                problems.append(f"{path.name} 第 {position + 1} 条读不出来：{exc!r}")
                continue
            if code in foods:
                problems.append(f"{path.name} 里的编码 {code} 重复出现")
            foods[code] = converted
    dropped = sum(_kcal_checked(food) for food in foods.values())
    doc = {
        "meta": {"source": source, "commit": commit, "count": len(foods)},
        "foods": dict(sorted(foods.items())),
    }
    return Built(doc, problems, {KCAL_UNKNOWN: dropped})


def build(raw_dir: Path, source: str, commit: str) -> tuple[dict[str, Any], list[str]]:
    """（副本内容，问题列表）：read 去掉质检条数。"""
    built = read(raw_dir, source, commit)
    return built.doc, built.problems


def describe(quality: dict[str, int]) -> str:
    """质检结果说给用户的话；没有要说的是空串。"""
    dropped = quality.get(KCAL_UNKNOWN, 0)
    if not dropped:
        return ""
    return f"热量按未知处理 {dropped} 条（原书热量有数、蛋白质脂肪碳水全未知，多半是印错的）。"
