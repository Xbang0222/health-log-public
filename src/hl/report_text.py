"""报告中空白日、营养平均值与体重变化的文字表达。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from hl import budget
from hl.foods import table
from hl.language.normalize import fmt

WEEK = 7  # 体重按这么多天一段平均，从最后一天往前分

RUN = 3  # 没有记录的日子连着这么多天以上，说成“某天至某天”


# ---------- 文字 ----------
def _runs(days: list[str]) -> str:
    """没有记录的日子：连着 RUN 天以上的说成“某天至某天”。"""
    groups: list[list[str]] = []
    for day in days:
        if groups and date.fromisoformat(day) - date.fromisoformat(groups[-1][-1]) == timedelta(1):
            groups[-1].append(day)
        else:
            groups.append([day])
    return "、".join(
        f"{group[0]} 至 {group[-1]}（{len(group)} 天）" if len(group) >= RUN else "、".join(group)
        for group in groups
    )


def _gap(key: str, value: Any) -> str:
    """差值（目标减已吃）说成“少 X”“多 X”；钠是上限。"""
    unit = budget.UNITS.get(key, "千卡")
    label = budget.LABELS.get(key, "热量")
    goal = "上限" if key == "sodium" else "目标"
    if value == 0:
        return f"{label}和{goal}一样"
    if key == "sodium" and value < 0:
        return f"钠超出上限 {fmt(-value)} {unit}"
    return f"{label}比{goal}{'少' if value > 0 else '多'} {fmt(abs(value))} {unit}"


def _average_text(avg: dict[str, Any]) -> str:
    totals, unknown = avg["totals"], avg["unknown"]
    kcal = f"{totals['kcal']} 千卡"
    shares = (
        (budget.EXACT, avg["exact_kcal"]),
        (budget.KINDS[table.AMOUNT], avg["approx_kcal"]),
        (budget.KINDS[table.CONTENT], avg["est_kcal"]),
    )
    if avg["approx_kcal"] or avg["est_kcal"]:
        kcal += "（" + "，".join(f"{label} {n} 千卡" for label, n in shares if n) + "）"
    eaten = "、".join(
        f"{budget.LABELS[key]} {budget.known(totals[key], unknown[key], budget.UNITS[key])}"
        for key in budget.LABELS
    )
    text = f"有饮食记录的 {avg['days']} 天平均每天吃 {kcal}，{eaten}"
    if avg["left"] is None:
        return f"{text}；这几天都没有计划，没有目标可比"
    gaps = "、".join(_gap(key, value) for key, value in avg["left"].items())
    groups: dict[int, list[str]] = {}
    for key, count in avg["left_days"].items():
        groups.setdefault(count, []).append(budget.LABELS.get(key, "热量"))
    if len(groups) == 1:
        basis = f"按有目标的 {next(iter(groups))} 天算"
    else:
        basis = "按有这项目标的天数平均：" + "，".join(
            f"{'、'.join(labels)} {count} 天" for count, labels in groups.items()
        )
    return f"{text}；和当天目标比，平均每天{gaps}（{basis}）"


def _weight_text(weights: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[str]:
    if not weights:
        return ["这段时间没有记体重。"]
    lines = ["体重：" + "、".join(f"{w['date']} {fmt(w['kg'])} 公斤" for w in weights) + "。"]
    parts = []
    for pos, block in enumerate(blocks):
        span = f"{block['from']} 至 {block['to']}"
        if block["avg_kg"] is None:
            parts.append(f"{span} 没有记体重")
            continue
        text = f"{span} 平均 {fmt(block['avg_kg'])} 公斤（记了 {block['count']} 次）"
        change = block["change_kg"]
        if change == 0:
            text += "，和前一段一样"
        elif change is not None:
            text += f"，比前一段{'轻' if change < 0 else '重'}了 {fmt(abs(change))} 公斤"
        elif pos:
            text += "，前一段没有记体重，比不了"
        parts.append(text)
    tail = "；这段时间不到两段，没有前一段可比" if len(blocks) == 1 else ""
    lines.append(f"体重按 {WEEK} 天一段平均（从最后一天往前分）：" + "；".join(parts) + tail + "。")
    return lines
