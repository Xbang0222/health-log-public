"""Read-only plan view; mutations belong to intents.settings."""

from __future__ import annotations

import argparse

from hl import budget
from hl.configuration import values as configuration_values
from hl.configuration.values import Context
from hl.ledgercheck import days as ledgercheck_days
from hl.ledgercheck import plans as ledgercheck_plans
from hl.planning.presentation import _spoken
from hl.result import Result, ok
from hl.storage import keys as storage_keys


def show_plan(ctx: Context, args: argparse.Namespace) -> Result:
    day = configuration_values.pick_date(args.date, ctx.today, "--date")
    key = storage_keys.secret(ctx.data_dir)
    plans = ledgercheck_plans.load_plans(ctx.data_dir, key)
    plan = budget.plan_on(plans, day)
    if plan is None:
        tell_user = f"{day} 还没有生效的计划，可以用 intent 的 plan 操作设定。"
        empty = {"from": None, "default": None, "days": None, "day_type": None, "target": None}
        return ok(tell_user, **empty)
    view = budget.view(plans, day, ledgercheck_days.load_day(ctx.data_dir, key, None, day))
    tell_user = (
        f"{day} 生效的计划从 {plan['from']} 开始。{_spoken(plan['days'], plan['default'])}。"
        f"这一天按“{view.day_type}”算。"
    )
    fields = {"from": plan["from"], "default": plan["default"], "days": plan["days"]}
    return ok(tell_user, **fields, version=plan["sig"], day_type=view.day_type, target=view.target)
