"""JSON Schema 加载与校验；校验失败时，fix 取自出错位置最近的 x-hint。"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from hl.result import problem

FALLBACK_HINT = "对照 AGENTS.md 里的写法修改这个字段"


def load(name: str) -> dict[str, Any]:
    source = resources.files("hl").joinpath("data", "schema", f"{name}.schema.json")
    return json.loads(source.read_text(encoding="utf-8"))


def _shown(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:60]


def shown_key(key: Any) -> str:
    """键在问题里的写法：文字原样；不是文字的按 JSON 写（YAML 的 true:、yes: 是 true，~: 是 null，
    .inf: 是 Infinity）。要按键找条目的命令（hl default --clear）用它来认 hl check 报出来的键。"""
    return key if isinstance(key, str) else _shown(key)


def _where(err: ValidationError) -> str:
    path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in err.path)
    return path.lstrip(".") or "(顶层)"


def _describe(err: ValidationError) -> str:
    rule, expected, value = err.validator, err.validator_value, err.instance
    if rule == "required":
        missing = [key for key in expected if key not in value]
        return f"缺少必填字段：{'、'.join(missing)}"
    if rule == "additionalProperties":
        extra = sorted({str(key) for key in value} - set(err.schema.get("properties", {})))
        return f"有不认识的字段：{'、'.join(extra)}"
    if rule == "type":
        return f"类型不对：应为 {expected}，实际是 {_shown(value)}"
    if rule in ("enum", "const"):
        return f"取值不在允许范围内：{_shown(value)}"
    if rule == "pattern":
        return f"格式不对：{_shown(value)}"
    if rule in ("minLength", "minItems", "minProperties"):
        return "不能为空"
    if rule in ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"):
        return f"数值超出范围：{_shown(value)}"
    return err.message


def _hint(root: dict[str, Any], err: ValidationError) -> str:
    node: Any = root
    hint = root.get("x-hint")
    for step in err.absolute_schema_path:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and "x-hint" in node:
            hint = node["x-hint"]
    return hint or FALLBACK_HINT


def _odd(data: Any, where: str = "") -> list[tuple[str, str]]:
    """YAML 写得出、JSON 里不会有的东西：不是文字的键、不是有限的数。返回（位置，问题）。

    schema 是照 JSON 写的，碰到这些会校验不下去，所以先单独查一遍。
    """
    if isinstance(data, dict):
        found = []
        for key, value in data.items():
            if isinstance(key, str):
                found += _odd(value, f"{where}.{key}" if where else key)
            else:
                found.append((where, f"键 {shown_key(key)} 不是文字（数字、yes、no 这类要加引号）"))
        return found
    if isinstance(data, list):
        return [hit for pos, value in enumerate(data) for hit in _odd(value, f"{where}[{pos}]")]
    if isinstance(data, float) and not math.isfinite(data):
        return [(where, f"数值不是有限的数：{data}")]
    return []


def errors(name: str, data: Any) -> list[dict[str, str]]:
    """按名字取 schema 校验 data，返回 {where, problem, fix} 列表；合规时为空。"""
    root = load(name)
    odd = _odd(data)
    if odd:
        hint = root.get("x-hint") or FALLBACK_HINT
        return [problem(where or "(顶层)", text, hint) for where, text in odd]
    validator = Draft202012Validator(root)
    found = sorted(validator.iter_errors(data), key=lambda err: [str(part) for part in err.path])
    return [problem(_where(err), _describe(err), _hint(root, err)) for err in found]
