"""hl report [--days N | --from YYYY-MM-DD --to YYYY-MM-DD]：一段时间的汇总（设计说明第 8.1 节）。

逐天列出六项合计、当天目标、差值、准确／份量是大概的／成分是估的各占多少热量、记了几餐；
再给有饮食记录那几天的平均值，和体重按 7 天一段平均的变化；没有饮食记录的日子单独列出。

只读。读到的每个文件（这段时间的每日文件、计划、清单、成分表副本）都先校验（R15），
有一个不过就整份不给数：少算了哪一天，平均值和体重变化就都不对了。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hl import budget
from hl.configuration import values as configuration_values
from hl.configuration.values import Context
from hl.foods.table_types import DIGITS, NUTRIENTS, round_half_up
from hl.intents.catalog import load_table
from hl.ledgercheck import days as ledgercheck_days
from hl.ledgercheck import messages as ledgercheck_messages
from hl.ledgercheck import plans as ledgercheck_plans
from hl.manifests import io as manifests_io
from hl.report_text import RUN as RUN
from hl.report_text import WEEK as WEEK
from hl.report_text import _average_text as _average_text
from hl.report_text import _gap as _gap
from hl.report_text import _runs as _runs
from hl.report_text import _weight_text as _weight_text
from hl.result import Abort, Result, ok, problem, rejected
from hl.storage import days as storage_days
from hl.storage import keys as storage_keys

DEFAULT_DAYS = 7

MAX_DAYS = 366

MEALS = ("早餐", "午餐", "晚餐", "加餐")

FIX_RANGE = (
    "最近几天用 --days N；某天到某天用 --from YYYY-MM-DD --to YYYY-MM-DD（不给 --to 就到今天）"
)


def _reject(where: str, what: str, fix: str) -> Abort:
    return Abort(rejected([problem(where, what, fix)]))


def _span(args: argparse.Namespace, today: str) -> list[str]:
    """这次汇总的日子，从早到晚。"""
    if args.days is not None and (args.start is not None or args.end is not None):
        raise _reject("--days", "--days 和 --from、--to 不能一起用", f"二选一：{FIX_RANGE}")
    if args.start is None and args.end is not None:
        raise _reject("--to", "给了 --to，没给 --from", f"加上 --from。{FIX_RANGE}")
    last = date.fromisoformat(today)
    if args.start is None:
        count = DEFAULT_DAYS if args.days is None else args.days
        if not 1 <= count <= MAX_DAYS:
            fix = f"--days 填 1 到 {MAX_DAYS} 之间的整数"
            raise _reject("--days", f"--days {count} 不在 1~{MAX_DAYS} 之间", fix)
        first = last - timedelta(days=count - 1)
    else:
        first = date.fromisoformat(configuration_values.pick_date(args.start, today, "--from"))
        last = date.fromisoformat(configuration_values.pick_date(args.end, today, "--to"))
        future = "填今天或以前的日子"
        if first.isoformat() > today:
            raise _reject("--from", f"{first} 还没到（今天是 {today}）", f"--from {future}")
        if last.isoformat() > today:
            fix = f"--to {future}；不给就到今天"
            raise _reject("--to", f"{last} 还没到（今天是 {today}）", fix)
        if first > last:
            raise _reject("--from", f"--from {first} 比 --to {last} 晚", "--from 要早于或等于 --to")
        if (last - first).days + 1 > MAX_DAYS:
            fix = f"一次最多汇总 {MAX_DAYS} 天，分几段查"
            raise _reject("--from", f"{first} 到 {last} 超过 {MAX_DAYS} 天", fix)
    return [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def _read(ctx: Context, days: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """读这段时间的每日文件和计划。问题全部收齐、去掉重复的，一起拒绝（R15）。"""
    foods = load_table(ctx)
    key = storage_keys.secret(ctx.data_dir)
    _, broken = manifests_io.read(ctx.data_dir, key)
    if broken:
        raise Abort(rejected(broken, ledgercheck_messages.NEXT_DATA))
    found: list[dict[str, str]] = []
    docs = {}
    for day in days:
        path = storage_days.day_path(ctx.data_dir, day)
        doc, problems = ledgercheck_days.read_day_file(ctx.data_dir, key, foods, path)
        found += problems
        docs[day] = storage_days.new_day(day) if doc is None else doc
    plans, problems = ledgercheck_plans.read_plan_file(ctx.data_dir, key)
    found += problems
    if found:
        unique = list({tuple(item.items()): item for item in found}.values())
        raise Abort(rejected(unique, ledgercheck_messages.NEXT_DATA))
    return docs, plans


def _day(day: str, doc: dict[str, Any], view: budget.DayView) -> dict[str, Any]:
    entries = doc["entries"]
    return {
        "date": day,
        "day_type": view.day_type,
        "meals": [meal for meal in MEALS if any(entry["meal"] == meal for entry in entries)],
        "entry_count": len(entries),
        "totals": view.totals,
        "unknown": view.unknown,
        "target": view.target,
        "left": view.left,
        "exact_kcal": view.totals["kcal"] - view.est_kcal - view.approx_kcal,
        "approx_kcal": view.approx_kcal,
        "est_kcal": view.est_kcal,
    }


def _shares(kinds: list[list[int]], total: int) -> list[int]:
    """三类热量的平均，加起来正好是 total（平均热量取整之后）。

    各类先向下取整，差的那几千卡给余数最大的几类（最大余数法）；余数一样大时按准确、份量是大概的、
    成分是估的这个顺序给。不能各自四舍五入之后拿总数去减：三份舍入误差叠到一类上，会出现
    “准确 -1 千卡”，或者一口准确的都没吃却多出 1 千卡。某一类每天都是 0 的，平均也一定是 0。
    """
    count = len(kinds[0])
    shares, rests = zip(*(divmod(sum(values), count) for values in kinds), strict=True)
    shares = list(shares)
    order = sorted(range(len(kinds)), key=lambda i: -rests[i])  # sorted 是稳定的：并列时按原顺序
    for i in order[: total - sum(shares)]:
        shares[i] += 1
    return shares


def _mean(values: list[Any], key: str) -> float | int:
    total = sum((Decimal(str(value)) for value in values), Decimal(0))
    return round_half_up(total / len(values), DIGITS[key])


def _average(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """有饮食记录那几天的平均值。差值只平均有这一项目标的那几天，各算了几天写在 left_days。

    准确、份量是大概的、成分是估的三类热量各自按逐天的值平均，再分配舍入，三样加起来就是平均热量
    （见 _shares）。
    """
    if not days:
        return None
    totals = {key: _mean([day["totals"][key] for day in days], key) for key in NUTRIENTS}
    kinds = ("exact_kcal", "approx_kcal", "est_kcal")
    exact, approx, est = _shares([[day[kind] for day in days] for kind in kinds], totals["kcal"])
    left, counted = {}, {}
    for key in NUTRIENTS:
        values = [day["left"][key] for day in days if day["left"] and key in day["left"]]
        if values:
            left[key], counted[key] = _mean(values, key), len(values)
    return {
        "days": len(days),
        "totals": totals,
        "unknown": {key: sum(day["unknown"][key] for day in days) for key in days[0]["unknown"]},
        "exact_kcal": exact,
        "approx_kcal": approx,
        "est_kcal": est,
        "left": left or None,
        "left_days": counted,
    }


def _weeks(days: list[str], weights: dict[str, Any]) -> list[dict[str, Any]]:
    """体重按 7 天一段平均：从最后一天往前分，最前面一段可能不满 7 天。

    每段和前一段比（都取两位小数之后相减）；这一段或前一段没记体重就是 null，不跳过去和更早的比。
    """
    parts = [days[max(0, end - WEEK) : end] for end in range(len(days), 0, -WEEK)][::-1]
    blocks: list[dict[str, Any]] = []
    previous = None
    for part in parts:
        kgs = [Decimal(str(weights[day])) for day in part if day in weights]
        avg = round_half_up(sum(kgs, Decimal(0)) / len(kgs), 2) if kgs else None
        change = None
        if avg is not None and previous is not None:
            change = round_half_up(Decimal(str(avg)) - Decimal(str(previous)), 2)
        blocks.append(
            {
                "from": part[0],
                "to": part[-1],
                "days": len(part),
                "count": len(kgs),
                "avg_kg": avg,
                "change_kg": change,
            }
        )
        previous = avg
    return blocks


def run(ctx: Context, args: argparse.Namespace) -> Result:
    days = _span(args, ctx.today)
    docs, plans = _read(ctx, days)
    listed, empty, lines = [], [], []
    for day in days:
        doc = docs[day]
        if not doc["entries"]:
            empty.append(day)
            continue
        view = budget.view(plans, day, doc)
        item = _day(day, doc, view)
        listed.append(item)
        meals = item["meals"]
        line = f"{budget.describe(day, view, alone=False)}；记了{'、'.join(meals)} {len(meals)} 餐"
        if item["entry_count"] != len(meals):
            line += f"（{item['entry_count']} 条记录）"
        lines.append(f"- {line}。")
    weights = [
        {"date": day, "kg": docs[day]["weight"]["kg"]} for day in days if "weight" in docs[day]
    ]
    blocks = _weeks(days, {w["date"]: w["kg"] for w in weights})
    average = _average(listed)
    head = f"{days[0]} 至 {days[-1]} 共 {len(days)} 天，有饮食记录的 {len(listed)} 天"
    if empty:
        head += f"；没有饮食记录的 {len(empty)} 天：{_runs(empty)}"
    told = [f"{head}。"]
    if average is not None:
        told.append(f"{_average_text(average)}。")
    told += _weight_text(weights, blocks)
    if lines:
        told += ["逐天：", *lines, f"{budget.FIBER_NOTE}。"]
    return ok(
        "\n".join(told),
        **{"from": days[0], "to": days[-1]},
        days=listed,
        empty_days=empty,
        average=average,
        weights=weights,
        weight_weeks=blocks,
    )
