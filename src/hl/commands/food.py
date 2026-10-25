"""Read-only personal food catalogue. Registration belongs to intents.settings."""

from __future__ import annotations

import argparse
from typing import Any

from hl import budget
from hl.configuration.values import Context
from hl.foods import custom, table
from hl.foods.table_types import View
from hl.intents.catalog import load_table
from hl.language import normalize as language_normalize
from hl.result import Result, ok, problem, rejected
from hl.storage import keys as storage_keys


def _described(name: str, body: dict[str, Any], view: View) -> str:
    """问话、tell_user 里怎么说这一条：营养值型的说出每一项，配方型的说出热量和原料。"""
    entry = custom.Entry(name, body)
    nutrition = entry.nutrition
    if nutrition is None:
        return entry.shown(view)
    each = "" if "unit" in entry.per else "每 "
    head = f"{each}{entry.per_shown} {language_normalize.fmt(nutrition['kcal'])} 千卡"
    rest = [
        f"{label} {language_normalize.fmt(nutrition[key])} {budget.UNITS[key]}"
        for key, label in budget.LABELS.items()
        if nutrition.get(key) is not None
    ]
    return "、".join([head, *rest])


# ---------- hl food list ----------
def list_foods(ctx: Context, args: argparse.Namespace) -> Result:
    """用户库里的条目：登记的、存下的估算、量词补充（第 8.6 节）。只读。"""
    key = storage_keys.secret(ctx.data_dir)
    library = custom.load(ctx.data_dir, key)
    if library.broken is not None:
        return rejected([problem(custom.FILE, library.broken, custom.FIX_RESTORE)])
    foods = load_table(ctx)
    boohee = table.BooheeLayer(ctx.data_dir, ctx.boohee_sha)
    view = table.View(foods, boohee=boohee)
    listed = [_listed(entry, view) for entry in library.entries.values()]
    if not listed:
        told = "用户库还是空的：估算记下的食物、用 intent food 登记的食物会存在这里。"
        return ok(told, foods=[])
    said = "；".join(_spoken(entry, view) for entry in library.entries.values())
    told = f"用户库里有 {len(listed)} 条：{said}。"
    return ok(told, foods=listed).warn(boohee.warnings(), tell=False)


def _kind(entry: custom.Entry) -> str:
    if not entry.food:
        return "量词补充"
    return custom.LABEL if entry.label else "估算"


def _listed(entry: custom.Entry, view: View) -> dict[str, Any]:
    shown: dict[str, Any] = {"name": entry.name, "kind": _kind(entry)}
    if entry.problem:
        return shown | {"problem": entry.problem}
    if entry.food:
        shown["ref"] = table.join(table.CUSTOM, entry.name)
        shown["per"] = entry.per_shown
        kcal = entry.kcal(view)
        shown["kcal"] = None if kcal is None else table.round_half_up(kcal, 0)
        shown["src"] = entry.src
        for key in ("basis", "url", "date"):
            if entry.body.get(key):
                shown[key] = entry.body[key]
    if entry.units:
        shown["units"] = entry.units
    return shown


def _spoken(entry: custom.Entry, view: View) -> str:
    if entry.problem:
        return f"{entry.name}（被直接改过，用不了）"
    units = "、".join(f"一{unit} {language_normalize.fmt(g)} 克" for unit, g in entry.units.items())
    if not entry.food:
        return f"{entry.name}的量词：{units}"
    told = f"{entry.name}（{_kind(entry)}）：{_described(entry.name, dict(entry.body), view)}"
    return f"{told}，量词：{units}" if units else told
