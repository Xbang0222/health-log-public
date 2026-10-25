"""将各层食品搜索候选转换成一致的展示结果。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl.foods import table
from hl.foods.concept_types import Concept, Index, Unit
from hl.foods.search_dry import is_dry
from hl.foods.search_names import CONCEPT, KINDS, RECIPE, SAVED, _Candidate
from hl.foods.table_types import Boohee, Food, View


# ---------- 列出的一条 ----------
def _kcal(value: float) -> int | float:
    return table.round_half_up(value, 0)


def _number(value: float) -> int | float:
    """150.0 → 150：克数照写，整数不带小数点。"""
    return int(value) if float(value).is_integer() else value


def _units(concept: Concept) -> dict[str, dict[str, float]]:
    """概念的量词合多少：g（可食部克数）、gross_g（称出来的整重）、ml。"""
    return {
        unit: {
            key: _number(value)
            for key, value in (("g", spec.g), ("gross_g", spec.gross_g), ("ml", spec.ml))
            if value is not None
        }
        for unit, spec in concept.units.items()
    }


def _recipe(concept: Concept, foods: View) -> dict[str, Any]:
    """一道菜谱：每个量词合多少克（有一份成品的重量时）、多少千卡；每 100 克的热量。
    配方里有查不到、热量未知的原料时不写热量。"""
    shown: dict[str, Any] = {"ref": concept.name, "kind": KINDS[RECIPE], "name": concept.name}
    kcal: float | None = 0.0
    for part in concept.recipe:
        food = foods.get(part.food)
        if food is None or food.kcal is None or kcal is None:
            kcal = None
        else:
            kcal += food.kcal * part.g / 100
    if kcal is not None and concept.serving_g:
        shown["kcal_100g"] = _kcal(kcal * 100 / concept.serving_g)
    units: dict[str, dict[str, float]] = {}
    for unit, spec in concept.units.items():
        servings = spec.recipe or 0
        units[unit] = {}
        if concept.serving_g:
            units[unit]["g"] = _number(round(servings * concept.serving_g, 1))
        if kcal is not None:
            units[unit]["kcal"] = _kcal(servings * kcal)
    shown["units"] = units
    return shown


def _concept(concept: Concept, foods: View, variant: str | None) -> dict[str, Any]:
    """一个概念：每 100 克的热量（说到品种的按那个品种，不然按默认品种）、量词、品种。"""
    shown: dict[str, Any] = {"ref": concept.name, "kind": KINDS[CONCEPT], "name": concept.name}
    if variant:
        shown["variant"] = variant
    which = variant or concept.default or concept.unsure or next(iter(concept.variants), None)
    food = foods.get(concept.variants[which].food) if which in concept.variants else None
    if food is not None and food.kcal is not None:
        shown["kcal_100g"] = _kcal(food.kcal)
    if concept.units:
        shown["units"] = _units(concept)
    if len(concept.variants) > 1:
        shown["variants"] = list(concept.variants)
    return shown


def _shown(candidate: _Candidate, foods: View, variant: str | None = None) -> dict[str, Any]:
    """列出的一条（search 和 near 一样）。"""
    layer = candidate.layer
    if layer == SAVED:
        entry = candidate.source
        shown: dict[str, Any] = {"ref": table.join(table.CUSTOM, entry.name)}
        shown |= {"kind": KINDS[SAVED], "name": entry.name}
        if entry.kcal_100g is not None:
            shown["kcal_100g"] = _kcal(entry.kcal_100g)
        if entry.per is not None:
            shown["per"] = entry.per
            if entry.kcal_per is not None:
                shown["kcal"] = _kcal(entry.kcal_per)
        return shown
    if layer in (CONCEPT, RECIPE):
        concept, _ = candidate.source
        return _concept(concept, foods, variant) if layer == CONCEPT else _known(concept, foods)
    code, food = candidate.source
    return _table_entry(layer, code, food)


def _table_entry(layer: str, code: str, food: Food) -> dict[str, Any]:
    """成分表、薄荷库的一条：成分表带水分，薄荷库带自带的量词；都带 dry。"""
    shown: dict[str, Any] = {"ref": table.join(layer, code), "kind": KINDS[layer]}
    shown |= {"name": food.name, "kcal_100g": _kcal(food.kcal or 0)}
    if layer == table.CN6:
        shown["water"] = food.water
    elif isinstance(food, Boohee) and food.per == "ml":
        shown["per_ml"] = True  # 每 100 毫升的热量；克和毫升按 1:1 通用
    shown["dry"] = is_dry(food)
    if isinstance(food, Boohee) and food.units:
        shown["units"] = {unit: dict(spec) for unit, spec in food.units.items()}
    return shown


# ---------- 估算通道里列它自己、认出的原料 ----------
def _known(concept: Concept, foods: View) -> dict[str, Any]:
    return _recipe(concept, foods) if concept.recipe else _concept(concept, foods, None)


def itself(concept: Concept, foods: View, saved: Mapping[str, float]) -> dict[str, Any]:
    """认得出、只缺用户说的量词时，near 里列的这一条本身（增补第 2.5 节）：字段同搜索，units 是
    它已有的量词（概念的克数；菜谱的克数和热量），加上用户库里给它存过的量词补充（量词 → 克数）。"""
    shown = _known(concept, foods)
    units = shown.get("units", {})
    shown["units"] = units | {u: {"g": _number(g)} for u, g in saved.items() if u not in units}
    return shown


def entry_itself(
    ref: str, food: Food, units: Mapping[str, Unit], saved: Mapping[str, float]
) -> dict[str, Any]:
    """两层兜底命中（成分表、薄荷库的一条）、只缺用户说的量词时，near 里列的这一条本身
    （增补第 2.5 节）：字段同搜索，units 是记账时能按的量词（可食部的克数，或毫升数），加上
    用户库里给它存过的量词补充。"""
    kind, code = table.split(ref)
    shown = _table_entry(kind, code, food)
    listed: dict[str, dict[str, float]] = {}
    for unit, spec in units.items():
        if spec.g is not None:
            listed[unit] = {"g": _number(spec.g)}
        else:
            listed[unit] = {"ml": _number(spec.ml or 0)}
    listed |= {unit: {"g": _number(g)} for unit, g in saved.items() if unit not in listed}
    shown["units"] = listed
    return shown


def ingredients(index: Index, foods: View, words: Mapping[str, str]) -> list[dict[str, Any]]:
    """text 里认出的食物词对应的概念和菜谱（增补第 8.1 节的 ingredients），字段同搜索。
    words：原词 → 概念名；不是同一种东西的词（含用户库里存的名字）没有概念，跳过。"""
    found = []
    for name in dict.fromkeys(words.values()):
        concept = index.concepts.get(name)
        if concept is not None:
            found.append(_known(concept, foods))
    return found
