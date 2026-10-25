"""Structured weight, plan, day type, defaults and personal food operations."""

from __future__ import annotations

import uuid

from hl import schema
from hl.configuration.values import Context
from hl.foods import concepts, custom
from hl.intents.catalog import load_table, values
from hl.intents.contract import fail
from hl.intents.meals import save
from hl.ledgercheck.days import load_day
from hl.ledgercheck.defaults import read_defaults_file
from hl.ledgercheck.plans import load_plans
from hl.manifests import write as manifests
from hl.result import Abort, needs_input, question
from hl.storage import keys


def cas(payload: dict, old: dict | None) -> None:
    current = old.get("sig") if old else None
    if payload.get("expected_version") != current:
        fail(
            "expected_version",
            "已有内容的版本与调用不一致，本次没有修改",
            "先 recent 或 plan show 查询版本，再提交更正",
        )


def apply(ctx: Context, key: bytes, payload: dict, day: str) -> dict:
    action = payload["action"]
    if action in ("weight", "day"):
        doc = load_day(ctx.data_dir, key, load_table(ctx), day)
        kind = "weight" if action == "weight" else "day_type"
        cas(payload, doc.get(kind))
        if action == "weight":
            body = {"kg": payload["kg"], "said": payload["said"]}
            tell = f"已记{day}体重 {payload['kg']:g} 公斤。"
        else:
            plans = load_plans(ctx.data_dir, key)
            active = [p for p in plans if p["from"] <= day]
            if not active or payload["name"] not in active[-1]["days"]:
                fail(
                    "name",
                    "该日期的计划中没有这个日子类型",
                    "plan show 查询可用类型，或先按用户要求设计划",
                )
            body = {"name": payload["name"], "said": payload["said"]}
            tell = f"{day}已按{payload['name']}记录。"
        body["revision"] = uuid.uuid4().hex
        body["sig"] = keys.sign(key, kind, day, body)
        doc[kind] = body
        save(ctx, key, doc)
        return {"tell_user": tell, "date": day, kind: body, "recorded": True}
    if action == "plan":
        plans = load_plans(ctx.data_dir, key)
        cas(payload, plans[-1] if plans else None)
        start = payload.get("from", day)
        if plans and start < plans[-1]["from"]:
            fail("from", "新计划生效日期不能早于最后一版计划", "保留历史；选择新的生效日期")
        if len(payload["days"]) > 1 and "default" not in payload:
            raise Abort(
                needs_input(
                    [
                        question(
                            "计划",
                            "confirm",
                            "平常默认用哪种日子类型？",
                            list(payload["days"]),
                            "多种类型不能替用户选择默认项",
                        )
                    ],
                    "只补用户选择的 default；保持原计划名称、目标和同一 request_id。",
                )
            )
        default = payload.get("default", next(iter(payload["days"])))
        if default not in payload["days"]:
            fail("default", "默认类型不在 days 中")
        body = {
            "from": start,
            "default": default,
            "days": payload["days"],
            "said": [payload["said"]],
        }
        body["revision"] = uuid.uuid4().hex
        body["sig"] = keys.sign(key, "plan", "", body)
        plans.append(body)
        errors = schema.errors("plan", plans)
        if errors:
            fail("plan", str(errors))
        manifests.save_plans(ctx.data_dir, key, plans)
        return {
            "tell_user": f"计划已更新，从{start}生效，默认{default}。",
            "plan": body,
            "recorded": True,
        }
    if action == "default":
        index = concepts.load()
        hit = concepts.lookup(index, payload["name"])
        if not hit:
            fail("name", "没有这个常见食物概念", "food search 查询名称")
        concept, _ = hit
        defaults, errors = read_defaults_file(ctx.data_dir, key)
        if errors:
            fail("defaults", str(errors))
        cas(payload, defaults.get(concept.name))
        variant = payload["variant"]
        if variant is None:
            defaults.pop(concept.name, None)
        else:
            canonical = concepts.find_variant(concept, variant)
            if not canonical:
                fail("variant", "品种不存在", f"有效品种：{'、'.join(concept.variants)}")
            body = {"variant": canonical, "said": payload["said"]}
            body["revision"] = uuid.uuid4().hex
            body["sig"] = keys.sign(key, "default", concept.name, body)
            defaults[concept.name] = body
        manifests.save_defaults(ctx.data_dir, key, defaults, concept.name)
        change = "清除" if variant is None else "设为" + variant
        return {
            "tell_user": f"{concept.name}默认品种已{change}。",
            "default": defaults.get(concept.name),
            "recorded": True,
        }
    library = custom.load(ctx.data_dir, key)
    if library.broken or any(e.problem for e in library.entries.values()):
        fail(custom.FILE, "用户库损坏，不能覆盖重签")
    name = payload["name"]
    old = library.get(name)
    cas(payload, dict(old.body) if old else None)
    label = payload.get("label", False)
    body = {
        "per": payload["per"],
        "nutrition": values(payload["nutrition"], label=label, amount=payload["per"]),
        "basis": payload["basis"],
        "src": "包装标签" if label else "模型估算",
        "est": [] if label else ["content"],
        "date": day,
        "said": payload["said"],
        "sig": "",
        "revision": uuid.uuid4().hex,
    }
    errors = schema.errors("custom", {name: body})
    if errors:
        fail("food", str(errors))
    custom.save(ctx.data_dir, key, name, body)
    return {"tell_user": f"已保存{name}{'包装标签' if label else '营养估算'}。", "recorded": True}
