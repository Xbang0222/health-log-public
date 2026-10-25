"""Replay is historical acknowledgement, never a stale current success summary."""

from __future__ import annotations

import copy

from hl.foods import custom
from hl.intents import meals
from hl.intents.catalog import load_table
from hl.ledgercheck.days import load_day
from hl.ledgercheck.defaults import read_defaults_file
from hl.ledgercheck.plans import load_plans
from hl.result import Result
from hl.storage import days


def replay(ctx, key, payload, receipt):
    original = copy.deepcopy(receipt["result"])
    fields = {
        "id": original.get("id", payload["request_id"]),
        "request_id": payload["request_id"],
        "replayed": True,
        "recorded": False,
        "original_result": original,
        "tell_user": "该请求已处理，本次没有重复写入。",
        "current_status": "processed",
    }
    if receipt.get("cancelled") or original.get("cancelled"):
        fields.update(
            cancelled=True, current_status="cancelled", tell_user="该请求已经取消，本次没有记录。"
        )
        return Result("duplicate", fields)
    if "target" in original:
        current = None
        foods = load_table(ctx)
        for path in days.day_files(ctx.data_dir):
            day = days.day_of(ctx.data_dir, path)
            doc = load_day(ctx.data_dir, key, foods, day)
            entry = next((e for e in doc["entries"] if e["id"] == original["target"]["id"]), None)
            if entry:
                current = meals.public(day, entry)
                break
        fields["current"] = current
        if current is None:
            fields.update(current_status="deleted", tell_user="原记录后来已删除，本次没有重记。")
        else:
            same = current["target"] == original["target"]
            fields.update(
                current_status="unchanged" if same else "amended",
                tell_user="该请求已处理，本次没有重复写入。当前记录："
                + meals.describe(current["input_items"])
                + "。",
            )
    elif payload["action"] in ("weight", "day"):
        kind = "weight" if payload["action"] == "weight" else "day_type"
        doc = load_day(ctx.data_dir, key, load_table(ctx), original["date"])
        current = doc.get(kind)
        fields.update(
            current=current,
            current_status="unchanged" if current == original.get(kind) else "superseded",
        )
    elif payload["action"] == "plan":
        plans = load_plans(ctx.data_dir, key)
        current = plans[-1] if plans else None
        fields.update(
            current=current,
            current_status="unchanged" if current == original.get("plan") else "superseded",
        )
    elif payload["action"] == "default":
        from hl.foods import concepts

        concept = concepts.lookup(concepts.load(), payload["name"])[0]
        current = read_defaults_file(ctx.data_dir, key)[0].get(concept.name)
        fields.update(
            current=current,
            current_status="unchanged" if current == original.get("default") else "superseded",
        )
    elif payload["action"] == "food":
        current = custom.load(ctx.data_dir, key).get(payload["name"])
        fields["current"] = dict(current.body) if current else None
    return Result("duplicate", fields)
