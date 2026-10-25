"""hl today [--date]：今日已吃、目标、还差多少、可以吃什么。读到的文件全部先校验（R15）。"""

from __future__ import annotations

import argparse

from hl import budget
from hl.configuration import values as configuration_values
from hl.configuration.values import Context
from hl.foods import concepts as foods_concepts
from hl.foods import table_io as foods_table_io
from hl.intents.catalog import load_table
from hl.intents.meals import public
from hl.ledgercheck import days as ledgercheck_days
from hl.ledgercheck import defaults as ledgercheck_defaults
from hl.ledgercheck import plans as ledgercheck_plans
from hl.result import Result, ok
from hl.storage import keys as storage_keys


def run(ctx: Context, args: argparse.Namespace) -> Result:
    day = configuration_values.pick_date(args.date, ctx.today, "--date")
    foods = load_table(ctx)
    key = storage_keys.secret(ctx.data_dir)
    doc = ledgercheck_days.load_day(ctx.data_dir, key, foods, day)
    plans = ledgercheck_plans.load_plans(ctx.data_dir, key)
    view = budget.view(plans, day, doc)
    index = foods_concepts.load()
    tips = budget.suggest(
        ledgercheck_defaults.load_suggest(ctx.data_dir, index), index, foods, view
    )
    entries = [public(day, entry) for entry in doc["entries"]]
    weight = doc["weight"]["kg"] if "weight" in doc else None
    tell_user = budget.describe(day, view) + "。"
    if weight is not None:
        tell_user += f"体重 {weight} 公斤。"
    if tips:
        tell_user += "接下来可以吃：" + "；".join(tips) + "。"
    # 薄荷库副本装了却用不了：照常算，提醒放进 warnings（增补 13.2）；没装不提醒，hl doctor 会说
    broken = foods_table_io.boohee_problem(ctx.data_dir, ctx.boohee_sha)
    warnings = [foods_table_io.boohee_note(broken, ctx.data_dir)] if broken else []
    return ok(
        tell_user,
        date=day,
        day_type=view.day_type,
        entries=entries,
        totals=view.totals,
        unknown=view.unknown,
        target=view.target,
        left=view.left,
        est_kcal=view.est_kcal,
        approx_kcal=view.approx_kcal,
        weight=weight,
        weight_version=doc.get("weight", {}).get("sig"),
        suggest=tips,
    ).warn(warnings, tell=False)
