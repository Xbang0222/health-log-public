"""合计、目标、还差多少、接下来可以吃什么（设计说明 3.1 与第 8 节）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from typing import Any

import yaml

from hl.foods.concept_types import Index
from hl.foods.table_types import (
    AMOUNT,
    CONTENT,
    DIGITS,
    MARKS,
    NUTRIENTS,
    Table,
    marks,
    round_half_up,
)

LABELS = {"protein": "蛋白质", "fat": "脂肪", "carb": "碳水", "fiber": "纤维", "sodium": "钠"}
UNITS = {"protein": "克", "fat": "克", "carb": "克", "fiber": "克", "sodium": "毫克"}
SUGGEST_FILE = "suggest.yaml"
CANDIDATES = ("proteins", "staples")  # suggest.yaml 里放候选食物的两个键
# 建议里用到、第 8 节没有定数的几个界限。第 8 节定的三个数（40、250、50）在 suggest.yaml 里
SPENT_MARGIN = 50  # 剩余热量比预留给蔬菜的多不出这么多千卡：算额度基本用完，只建议蔬菜
PROTEIN_ENOUGH = 15  # 蛋白质缺口不到这么多克：不再建议蛋白质来源
PROTEIN_SHARE = 0.6  # 一份蛋白质来源最多占剩余热量的这个比例，免得把额度全花在一样东西上
MIN_PORTION = 50  # 算出来不到这么多克的份量不值得建议
STAPLE_ROOM = 100  # 扣掉蛋白质来源和蔬菜之后，剩余热量不超过这么多千卡：不建议主食
CARB_ENOUGH = 20  # 碳水缺口不超过这么多克：不建议主食
FIBER_NOTE = "纤维按成分表的“不溶性膳食纤维”口径"
# 增补第 12 节：估算的两种说法；准确的那类没有标记
EXACT = "准确"
KINDS = {AMOUNT: "份量是大概的", CONTENT: "成分是估的"}


@dataclass(frozen=True)
class DayView:
    """某一天的账：明细条数、按哪种日子算、目标、已吃、无数据条数、还差多少、估算热量。

    est_kcal 是成分是估的明细的热量（两样都标了的也算这里），approx_kcal 是只有份量是大概的。
    """

    rows: int
    day_type: str | None
    target: dict[str, Any] | None
    totals: dict[str, Any]
    unknown: dict[str, int]
    left: dict[str, Any] | None
    est_kcal: int
    approx_kcal: int


def _sum(values: list[Any], key: str) -> float | int:
    return round_half_up(sum((Decimal(str(v)) for v in values), Decimal(0)), DIGITS[key])


def rows_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for entry in doc["entries"] for row in entry["items"]]


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """六项合计：各条明细取整后的值相加，只合计已知的值。"""
    return {key: _sum([r[key] for r in rows if r[key] is not None], key) for key in NUTRIENTS}


def unknown(rows: list[dict[str, Any]]) -> dict[str, int]:
    """每项营养素有多少条明细是未知。"""
    return {key: sum(1 for r in rows if r[key] is None) for key in NUTRIENTS if key != "kcal"}


def kind(row: Mapping[str, Any]) -> str | None:
    """汇总时这条明细归哪一类（增补第 12 节）：CONTENT、AMOUNT，准确的是 None。"""
    found = marks(row)
    if CONTENT in found:
        return CONTENT
    return AMOUNT if AMOUNT in found else None


def plan_on(plans: list[dict[str, Any]], day: str) -> dict[str, Any] | None:
    """某天生效的计划：生效日期不晚于该天的最后一条。"""
    active = [plan for plan in plans if plan["from"] <= day]
    return active[-1] if active else None


def view(plans: list[dict[str, Any]], day: str, doc: dict[str, Any]) -> DayView:
    rows = rows_of(doc)
    eaten = totals(rows)
    plan = plan_on(plans, day)
    day_type, target, left = None, None, None
    if plan is not None:
        chosen = doc.get("day_type", {}).get("name")
        day_type = chosen if chosen in plan["days"] else plan["default"]
        target = plan["days"][day_type]
        left = {
            key: round_half_up(Decimal(str(goal)) - Decimal(str(eaten[key])), DIGITS[key])
            for key, goal in target.items()
        }
    approx, est = (int(_sum([r["kcal"] for r in rows if kind(r) == k], "kcal")) for k in MARKS)
    return DayView(len(rows), day_type, target, eaten, unknown(rows), left, est, approx)


# ---------- 文字 ----------
def known(value: Any, missing: int, unit: str) -> str:
    """R12：有未知项时写成"至少 X（有 N 项无数据）"，不把未知当 0。"""
    return f"至少 {value} {unit}（有 {missing} 项无数据）" if missing else f"{value} {unit}"


def describe(day: str, v: DayView, alone: bool = True) -> str:
    """把一天的账说成一句可以原样转告用户的话。

    alone 为假时是一段时间的汇总里的一天（hl report）：纤维口径由汇总在最后说一次，
    没有计划时只说“这天没有计划”，不每天提示设定计划。
    """
    kcal = v.totals["kcal"]
    parts = [f"{day} 已吃 {kcal} 千卡"]
    if v.est_kcal or v.approx_kcal:
        exact = kcal - v.est_kcal - v.approx_kcal
        shares = ((EXACT, exact), (KINDS[AMOUNT], v.approx_kcal), (KINDS[CONTENT], v.est_kcal))
        parts[0] += "（" + "，".join(f"{label} {n} 千卡" for label, n in shares if n) + "）"
    if v.target is None or v.left is None:
        if not v.rows:
            return f"{day} 还没有记录。还没有设定计划"
        eaten = "、".join(
            f"{LABELS[key]} {known(v.totals[key], v.unknown[key], UNITS[key])}" for key in LABELS
        )
        if not alone:
            return f"{parts[0]}，{eaten}；这天没有计划"
        return f"{parts[0]}，{eaten}（{FIBER_NOTE}）。还没有设定计划"
    over = v.left["kcal"] < 0
    rest = f"已超出 {-v.left['kcal']} 千卡" if over else f"还剩 {v.left['kcal']} 千卡"
    parts[0] += f"；按“{v.day_type}”目标 {v.target['kcal']} 千卡，{rest}"
    for key in ("protein", "fat", "carb", "fiber"):
        if key in v.target:
            status = f"还差 {v.left[key]} 克" if v.left[key] > 0 else "已达标"
            eaten = known(v.totals[key], v.unknown[key], "克")
            parts.append(f"{LABELS[key]} {eaten}，目标 {v.target[key]} 克，{status}")
    if "sodium" in v.target:
        status = f"已超出 {-v.left['sodium']} 毫克" if v.left["sodium"] < 0 else "未超"
        eaten = known(v.totals["sodium"], v.unknown["sodium"], "毫克")
        parts.append(f"钠 {eaten}，上限 {v.target['sodium']} 毫克，{status}")
    text = "；".join(parts)
    return f"{text}（{FIBER_NOTE}）" if alone and "fiber" in v.target else text


def est_note(rows: Iterable[Mapping[str, Any]]) -> str:
    """一项食物写出的几行带了哪几种估算，说成括号里的一句；都准确是空串。"""
    found = {mark for row in rows for mark in marks(row)}
    labels = [KINDS[mark] for mark in MARKS if mark in found]
    return f"（{'，'.join(labels)}）" if labels else ""


# ---------- 建议 ----------
def builtin_suggest() -> dict[str, Any]:
    """引擎自带的候选食物和上限；数据目录里的 suggest.yaml 按键盖在它上面（见 audit）。"""
    text = resources.files("hl").joinpath("data", SUGGEST_FILE).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _as_eaten(candidate: dict[str, Any], index: Index, table: Table) -> tuple[float, float, float]:
    """候选食物按吃的时候的重量算，每 100 克的（千卡，蛋白质，碳水）；查不到时全为 0。"""
    concept = index.concepts.get(candidate["concept"])
    variant = concept.variants.get(candidate["variant"]) if concept else None
    food = table.get(variant.food) if variant else None
    if concept is None or food is None or not food.kcal:
        return 0.0, 0.0, 0.0
    factor = 1 / concept.cook_yield if candidate.get("state") == "熟" and concept.cook_yield else 1
    return food.kcal * factor, (food.protein or 0) * factor, (food.carb or 0) * factor


def _tens(grams: float) -> int:
    return int(grams // 10 * 10)


def _protein_tip(
    conf: dict[str, Any], index: Index, table: Table, kcal_left: float, protein_left: float | None
) -> tuple[str | None, float]:
    """蛋白质来源：按顺序取前两种放得进剩余额度的，给用户二选一。

    返回（建议，两种里热量高的那种占掉多少千卡）；缺口太小或没有放得进的，建议是 None。
    """
    if protein_left is not None and protein_left < PROTEIN_ENOUGH:
        return None, 0.0
    cap = conf["protein_cap"]
    want = cap if protein_left is None else min(protein_left, cap)
    options, used = [], 0.0
    for candidate in conf["proteins"]:
        kcal, protein, _ = _as_eaten(candidate, index, table)
        if not protein:
            continue
        grams = _tens(min(want / protein * 100, kcal_left * PROTEIN_SHARE / kcal * 100))
        if grams >= MIN_PORTION:
            options.append(
                f"{candidate['label']} {grams} 克（约 {kcal * grams / 100:.0f} 千卡，"
                f"蛋白质 {protein * grams / 100:.0f} 克）"
            )
            used = max(used, kcal * grams / 100)
        if len(options) == 2:
            break
    if not options:
        return None, 0.0
    return "蛋白质来源（二选一）：" + " 或 ".join(options), used


def _staple_tip(
    conf: dict[str, Any], index: Index, table: Table, rest: float, carb_left: float | None
) -> str | None:
    """主食：只用候选里的第一种。rest 是扣掉蛋白质来源和蔬菜预留之后还剩的热量。"""
    if rest <= STAPLE_ROOM or (carb_left is not None and carb_left <= CARB_ENOUGH):
        return None
    candidate = conf["staples"][0]
    kcal, _, carb = _as_eaten(candidate, index, table)
    if not kcal:
        return None
    limits = [rest / kcal * 100, conf["staple_cap"]]
    if carb_left is not None and carb:
        limits.append(carb_left / carb * 100)
    grams = _tens(min(limits))
    if grams < MIN_PORTION:
        return None
    return f"主食：{candidate['label']} {grams} 克（约 {kcal * grams / 100:.0f} 千卡）"


def suggest(conf: dict[str, Any], index: Index, table: Table, v: DayView) -> list[str]:
    """按剩余额度算接下来可以吃什么：蛋白质来源二选一、主食、预留给蔬菜的热量。"""
    if v.left is None:
        return []
    reserve = conf["vegetable_reserve"]
    kcal_left = v.left["kcal"]
    if kcal_left <= reserve + SPENT_MARGIN:
        return ["今天的热量额度基本用完了，还饿的话吃点蔬菜或喝水"]
    protein, used = _protein_tip(conf, index, table, kcal_left, v.left.get("protein"))
    staple = _staple_tip(conf, index, table, kcal_left - used - reserve, v.left.get("carb"))
    tips = [tip for tip in (protein, staple) if tip]
    return [*tips, f"蔬菜：已预留 {reserve} 千卡，放心吃"]
