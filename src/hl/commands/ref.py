"""hl ref [--kg]：参考范围表（设计说明第 7.5 节）。

只读引擎自带的 reference.yaml、原样展示：不读数据目录，不写任何文件，不碰计划。
计划由用户自己定，这里的数只供查看（第 11 节第 3 条）。
"""

from __future__ import annotations

import argparse
import math
from decimal import Decimal
from importlib import resources
from typing import Any

import yaml

from hl import schema
from hl.foods.table_types import round_half_up
from hl.language.normalize import fmt
from hl.language.weight_patterns import PLAUSIBLE_KG
from hl.result import Abort, Result, error, ok, problem, rejected

REFERENCE_FILE = "reference.yaml"
UNITS = {
    "g/d": "克/天",
    "mg/d": "毫克/天",
    "%E": "%（占总热量）",
    "g/kg/d": "克/公斤体重/天",
    "g/kg_lbm/d": "克/公斤去脂体重/天",
    "%bw/wk": "%体重/周",
}
# 按体重给的范围，--kg 换算成什么：（单位，每公斤乘几，留几位小数）。按去脂体重给的不换算：
# 引擎不知道去脂体重
PER_KG = {"g/kg/d": ("克/天", Decimal(1), 0), "%bw/wk": ("公斤/周", Decimal("0.01"), 2)}
UPPER = {"≤": "不超过", "<": "少于"}
HEAD = "下面是带出处的参考范围，只供参考，不会写进你的计划；目标定多少由你自己决定"
FIX_KG = "--kg 填用户自己说的体重（公斤，20~300 之间）；用户没说体重就不要加 --kg"
BROKEN = "引擎自带的参考范围表 reference.yaml 有问题"


def problems(data: Any) -> list[dict[str, str]]:
    """reference.yaml 的问题：结构（JSON Schema），再加上 schema 管不到的几条。合规时为空。"""
    found = schema.errors("reference", data)
    if found:
        return found
    hint = "改 src/hl/data/reference.yaml"
    seen: set[str] = set()
    for pos, item in enumerate(data["items"]):
        where = f"items[{pos}]"
        if item["id"] in seen:
            found.append(problem(where, f"id {item['id']} 重复", hint))
        seen.add(item["id"])
        if item["source"] not in data["sources"]:
            found.append(problem(where, f"出处 {item['source']} 不在 sources 里", hint))
        if "low" in item and item["low"] > item["high"]:
            found.append(problem(where, "low 比 high 大", hint))
    return found


def load() -> dict[str, Any]:
    """读引擎自带的参考范围表。它随引擎发布，读不进来、校验不过是引擎的问题，返回 error。"""
    text = resources.files("hl").joinpath("data", REFERENCE_FILE).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise Abort(error(f"{BROKEN}：不是合法的 YAML（{exc}）")) from exc
    found = problems(data)
    if found:
        listed = "；".join(f"{item['where']}：{item['problem']}" for item in found[:5])
        raise Abort(error(f"{BROKEN}：{listed}"))
    return data


def _digits(*values: Any) -> int:
    """几个数里小数位最多的那个有几位：1.4 和 2.0 都按一位写，读出来是 1.4~2.0。"""
    return max(-min(Decimal(str(v)).as_tuple().exponent, 0) for v in values)


def _span(low: Any, high: Any, upper: str | None, unit: str) -> str:
    places = _digits(*(v for v in (low, high) if v is not None))
    low_text, high_text = (f"{v:.{places}f}" if v is not None else "" for v in (low, high))
    gap = "" if unit.startswith("%") else " "
    if upper:
        return f"{UPPER[upper]} {high_text}{gap}{unit}"
    shown = high_text if low == high else f"{low_text}~{high_text}"
    return f"{shown}{gap}{unit}"


def _for_kg(item: dict[str, Any], kg: float | None) -> dict[str, Any] | None:
    if kg is None or item["unit"] not in PER_KG:
        return None
    unit, per, places = PER_KG[item["unit"]]
    weight = Decimal(str(kg))

    def scaled(value: Any) -> float | int | None:
        if value is None:
            return None
        return round_half_up(Decimal(str(value)) * per * weight, places)

    return {"low": scaled(item.get("low")), "high": scaled(item["high"]), "unit": unit}


def _entry(item: dict[str, Any], sources: dict[str, Any], kg: float | None) -> dict[str, Any]:
    source = sources[item["source"]]
    return {
        "id": item["id"],
        "topic": item["topic"],
        "what": item["what"],
        "who": item["who"],
        "low": item.get("low"),
        "high": item["high"],
        "upper": item.get("upper"),
        "unit": UNITS[item["unit"]],
        "for_kg": _for_kg(item, kg),
        "source": {key: source[key] for key in ("name", "by", "url", "kind")},
        "checked": item["checked"],
        "where": item["where"],
        "note": item["note"],
    }


def _line(entry: dict[str, Any], kg: float | None) -> str:
    source = entry["source"]
    span = _span(entry["low"], entry["high"], entry["upper"], entry["unit"])
    text = f"- {entry['who']}，{entry['what']}：{span}"
    converted = entry["for_kg"]
    if converted is not None:
        text += f"，按 {fmt(kg)} 公斤算是 " + _span(
            converted["low"], converted["high"], entry["upper"], converted["unit"]
        )
    return (
        f"{text}。注：{entry['note'].rstrip('。')}。"
        f"出处：《{source['name']}》，{source['by']}；{source['kind']}，{entry['checked']}；"
        f"网址 {source['url']}"  # 网址放在行尾、前面空一格：Markdown 里认得出链接，不带上后面的字
    )


def run(args: argparse.Namespace) -> Result:
    kg = args.kg
    if kg is not None and not (math.isfinite(kg) and PLAUSIBLE_KG[0] <= kg <= PLAUSIBLE_KG[1]):
        raise Abort(rejected([problem("--kg", f"{fmt(kg)} 公斤不像体重", FIX_KG)]))
    data = load()
    entries = [_entry(item, data["sources"], kg) for item in data["items"]]
    lines = [f"{HEAD}。", *(_line(entry, kg) for entry in entries)]
    return ok("\n".join(lines), kg=kg, items=entries)
