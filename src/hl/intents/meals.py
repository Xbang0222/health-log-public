"""Meal creation, item-scoped replacement, moves and exact-target deletion."""

from __future__ import annotations

import copy
import uuid

from hl import schema
from hl.configuration.values import Context
from hl.intents.catalog import load_table
from hl.intents.contract import fail
from hl.intents.nutrition import Calculator
from hl.ledgercheck.days import load_day
from hl.manifests import write as manifests
from hl.storage import days, keys


def target(day: str, entry: dict) -> dict:
    return {"date": day, "id": entry["id"], "version": entry["sig"]}


def grouped(entry: dict) -> tuple[list[dict], list[dict]]:
    rows = copy.deepcopy(entry["items"])
    inputs = copy.deepcopy(entry.get("input_items", []))
    if inputs:
        return inputs, rows
    # Legacy rows remain signed in their original form. Temporary group IDs for query/amend only.
    groups = {}
    for pos, row in enumerate(rows):
        name = row.get("part_of") or row["name"]
        group = (row.get("part_of"), row.get("amount")) if row.get("part_of") else pos
        if group not in groups:
            identity = f"legacy-{len(groups) + 1}"
            groups[group] = identity
            inputs.append({"item_id": identity, "name": name, "legacy": True})
        row["item_id"] = groups[group]
    return inputs, rows


def public(day: str, entry: dict) -> dict:
    inputs, _ = grouped(entry)
    return {**entry, "date": day, "target": target(day, entry), "input_items": inputs}


def locate(ctx: Context, key: bytes, wanted: dict) -> tuple[dict, dict]:
    doc = load_day(ctx.data_dir, key, load_table(ctx), wanted["date"])
    entry = next((e for e in doc["entries"] if e["id"] == wanted["id"]), None)
    if entry is None or entry["sig"] != wanted["version"]:
        fail(
            "target",
            "目标已改变或不存在，本次没有修改",
            "重新 recent 查询；不要用旧 ID/版本覆盖新记录",
        )
    return doc, entry


def item_ids(items: list[dict]) -> list[dict]:
    return [{**item, "item_id": "i" + uuid.uuid4().hex} for item in items]


def save(ctx: Context, key: bytes, doc: dict) -> None:
    errors = schema.errors("day", doc)
    if errors:
        fail("entry", f"生成的记录不合结构：{errors}")
    manifests.save_day(ctx.data_dir, key, doc)


def describe(inputs: list[dict]) -> str:
    def shown(item):
        amount = item.get("amount")
        return item["name"] + (f" {amount['n']:g}{amount['unit']}" if amount else "")

    return "、".join(shown(item) for item in inputs)


def add(ctx: Context, key: bytes, payload: dict, day: str, origin: dict) -> tuple[dict, dict]:
    meal = payload.get("meal", "加餐")
    inputs = item_ids(payload["items"])
    calculated = Calculator(ctx, key).resolve(inputs)
    doc = load_day(ctx.data_dir, key, load_table(ctx), day)
    entry = {
        "id": "e" + str(uuid.uuid4().int),
        "key": days.entry_key(day, meal, payload["said"]),
        "meal": meal,
        "said": payload["said"],
        "items": calculated.rows,
        "input_items": inputs,
        "origin": origin,
        "revision": 1,
    }
    entry["sig"] = keys.sign(key, "entry", day, entry)
    doc["entries"].append(entry)
    save(ctx, key, doc)
    notes = calculated.notes
    if "meal" not in payload:
        notes.append("未指定餐次，记为加餐")
    result = {
        "id": entry["id"],
        "date": day,
        "meal": meal,
        "target": target(day, entry),
        "items": entry["items"],
        "input_items": inputs,
        "recorded": True,
        "tell_user": f"已记{day}{meal}：{describe(inputs)}。",
        "notes": notes,
    }
    return result, calculated.saves


def amend(ctx: Context, key: bytes, payload: dict, origin: dict) -> tuple[dict, dict]:
    old_doc, old = locate(ctx, key, payload["target"])
    inputs, rows = grouped(old)
    indexed = {i["item_id"]: i for i in inputs}
    changes = payload.get("changes", [])
    removed = payload.get("remove_items", [])
    touched = [c["item_id"] for c in changes] + removed
    if len(touched) != len(set(touched)) or any(identity not in indexed for identity in touched):
        fail(
            "changes", "项目不存在或同一项目被重复修改", "recent 取当前 item_id，只提交要更改的项目"
        )
    if (
        not touched
        and not payload.get("add_items")
        and not any(k in payload for k in ("date", "meal"))
    ):
        fail("amend", "没有要修改的字段")
    replacements = [{**c["item"], "item_id": c["item_id"]} for c in changes]
    extras = item_ids(payload.get("add_items", []))
    calculated = Calculator(ctx, key).resolve([*replacements, *extras])
    replaced = {i["item_id"]: i for i in replacements}
    updated_inputs = [replaced.get(i["item_id"], i) for i in inputs if i["item_id"] not in removed]
    updated_inputs.extend(extras)
    if not updated_inputs:
        fail("remove_items", "不能把一餐改成空记录", "用户要取消整条记录时使用 delete")
    kept_rows = [r for r in rows if r["item_id"] not in touched]
    all_rows = kept_rows + calculated.rows
    rank = {item["item_id"]: i for i, item in enumerate(updated_inputs)}
    all_rows.sort(key=lambda row: rank[row["item_id"]])
    day = payload.get("date", old_doc["date"])
    new = {
        **old,
        # Legacy eN identities were unique only within their day. Promote on the
        # first authorized edit; migration itself must retain every original byte.
        "id": old["id"] if "input_items" in old else "e" + str(uuid.uuid4().int),
        "meal": payload.get("meal", old["meal"]),
        "items": all_rows,
        "input_items": updated_inputs,
        "said": payload["said"],
        "origin": origin,
        "revision": old.get("revision", 0) + 1,
    }
    new["key"] = days.entry_key(day, new["meal"], payload["said"])
    new["sig"] = keys.sign(key, "entry", day, new)
    if day == old_doc["date"]:
        old_doc["entries"] = [new if e["id"] == old["id"] else e for e in old_doc["entries"]]
        save(ctx, key, old_doc)
    else:
        destination = load_day(ctx.data_dir, key, load_table(ctx), day)
        if any(e["id"] == new["id"] for e in destination["entries"]):
            fail("target", "目标日期存在相同身份的记录")
        old_doc["entries"] = [e for e in old_doc["entries"] if e["id"] != old["id"]]
        destination["entries"].append(new)
        save(ctx, key, old_doc)
        save(ctx, key, destination)
    detail = describe(replacements + extras) or f"日期/餐次改为{day}{new['meal']}"
    if removed:
        detail += f"，移除{describe([indexed[i] for i in removed])}"
    return {
        "id": new["id"],
        "previous_target": payload["target"],
        "target": target(day, new),
        "date": day,
        "meal": new["meal"],
        "items": new["items"],
        "input_items": updated_inputs,
        "recorded": True,
        "tell_user": f"已改：{detail}；其余保留。",
        "notes": calculated.notes,
    }, calculated.saves


def delete(ctx: Context, key: bytes, payload: dict) -> dict:
    targets = payload["targets"]
    identities = [(t["date"], t["id"]) for t in targets]
    if len(set(identities)) != len(identities):
        fail("targets", "删除目标重复")
    # Validate the entire frozen batch before any modification.
    located = [locate(ctx, key, t) for t in targets]
    documents = {doc["date"]: doc for doc, _ in located}
    for doc in documents.values():
        doc["entries"] = [e for e in doc["entries"] if (doc["date"], e["id"]) not in identities]
        save(ctx, key, doc)
    return {"tell_user": f"已删除 {len(targets)} 条记录。", "deleted": targets, "recorded": True}
