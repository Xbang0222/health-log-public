"""Version 2 input contract. No raw-language semantic adjudication."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator

from hl import schema
from hl.configuration.values import is_date
from hl.result import Abort, problem, rejected

TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0, "maximum": 1000000}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
MEAL = {"enum": ["早餐", "午餐", "晚餐", "加餐"]}


def obj(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def array(item: dict, minimum: int = 1) -> dict:
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": 100}


AMOUNT = obj({"n": POSITIVE, "unit": TEXT}, ("n", "unit"))
NUTRITION = obj(
    {
        name: {"type": ["number", "null"], "minimum": 0, "maximum": 1000000}
        for name in ("kcal", "protein", "fat", "carb", "fiber", "sodium")
    },
    ("kcal",),
)
NUTRITION["properties"]["kcal"]["type"] = "number"
NUTRITION["properties"]["other_kcal"] = {"type": "number", "minimum": 0, "maximum": 1000000}
ESTIMATE = obj(
    {
        "nutrition": NUTRITION,
        "parts": array(obj({"food": TEXT, "g": POSITIVE}, ("food", "g"))),
        "basis": TEXT,
        "remember": {"type": "boolean"},
        "url": TEXT,
    },
    ("basis",),
)
ESTIMATE["oneOf"] = [{"required": ["nutrition"]}, {"required": ["parts"]}]
ITEM = obj(
    {
        "name": TEXT,
        "amount": AMOUNT,
        "variant": TEXT,
        "state": {"enum": ["生", "熟"]},
        "net": {"enum": ["带皮", "去皮"]},
        "approximate": {"type": "boolean"},
        "estimate": ESTIMATE,
        "food": TEXT,
    },
    ("name",),
)
TARGET = obj({"date": DATE, "id": TEXT, "version": TEXT}, ("date", "id", "version"))
SOURCE = obj({"at": TEXT, "message_ids": array({"type": "integer", "minimum": 0}), "session": TEXT})
BASE = {
    "request_id": {**TEXT, "maxLength": 200},
    "action": TEXT,
    "said": TEXT,
    "answers": array(TEXT, 0),
    "source": SOURCE,
}
PLAN = schema.load("plan_set")["properties"]
CUSTOM = schema.load("custom")["additionalProperties"]["properties"]
ACTIONS = {
    "add": ({"date": DATE, "meal": MEAL, "items": array(ITEM)}, ("items",)),
    "amend": (
        {
            "target": TARGET,
            "date": DATE,
            "meal": MEAL,
            "changes": array(obj({"item_id": TEXT, "item": ITEM}, ("item_id", "item"))),
            "remove_items": array(TEXT),
            "add_items": array(ITEM),
        },
        ("target",),
    ),
    "delete": ({"targets": array(TARGET)}, ("targets",)),
    "weight": (
        {
            "date": DATE,
            "kg": {**POSITIVE, "maximum": 1000},
            "expected_version": {"type": ["string", "null"]},
        },
        ("kg",),
    ),
    "plan": (
        {
            "from": DATE,
            "default": TEXT,
            "days": PLAN["days"],
            "expected_version": {"type": ["string", "null"]},
        },
        ("days",),
    ),
    "day": (
        {"date": DATE, "name": TEXT, "expected_version": {"type": ["string", "null"]}},
        ("name",),
    ),
    "default": (
        {
            "name": TEXT,
            "variant": {"type": ["string", "null"]},
            "expected_version": {"type": ["string", "null"]},
        },
        ("name", "variant"),
    ),
    "food": (
        {
            "name": TEXT,
            "per": CUSTOM["per"],
            "nutrition": NUTRITION,
            "basis": TEXT,
            "label": {"type": "boolean"},
            "expected_version": {"type": ["string", "null"]},
        },
        ("name", "per", "nutrition", "basis"),
    ),
    "confirm": ({"token": TEXT}, ("token",)),
    "cancel": ({"token": TEXT, "cancel_request_id": TEXT}, ()),
    "noop": ({"reason": TEXT}, ("reason",)),
}


def fail(
    where: str, message: str, fix: str = "按 intent 契约修正调用；已知信息自行修正，不要重问用户"
):
    raise Abort(rejected([problem(where, message, fix)]))


def parse(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except ValueError:
        fail("JSON", "不是合法 JSON")
    if not isinstance(data, dict) or data.get("action") not in ACTIONS:
        fail("action", f"支持的操作：{', '.join(ACTIONS)}")
    props, required = ACTIONS[data["action"]]
    contract = obj({**BASE, **props}, ("request_id", "action", "said", *required))
    errors = list(Draft202012Validator(contract).iter_errors(data))
    odd = schema._odd(data)
    if errors or odd:
        found = [
            problem(
                ".".join(map(str, e.path)) or "JSON",
                e.message,
                "按 intent 契约修正工具参数；不要把机器字段问题转问用户",
            )
            for e in errors
        ]
        found += [problem(at, text, "数值须有限，键须是字符串") for at, text in odd]
        raise Abort(rejected(found))
    for field in ("date", "from"):
        if field in data and not is_date(data[field]):
            fail(field, "日期不存在")
    targets = data.get("targets", [data["target"]] if "target" in data else [])
    for target in targets:
        if not is_date(target["date"]):
            fail("target.date", "日期不存在")
    if "at" in data.get("source", {}):
        try:
            at = datetime.fromisoformat(data["source"]["at"])
            if at.tzinfo is None:
                raise ValueError
        except ValueError:
            fail("source.at", "来源时间须为带时区 ISO 8601 时间")
    return data
