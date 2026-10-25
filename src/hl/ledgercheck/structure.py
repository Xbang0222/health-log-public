"""每日记录、计划和默认品种的结构与签名核验。"""

from __future__ import annotations

from typing import Any

from hl import schema
from hl.foods.table_types import SOURCES, Table, agrees, split
from hl.ledgercheck.messages import _IN_ENTRY, WHOLE, Found, Restorable
from hl.ledgercheck.repairs import _restore_only, _undo_entry
from hl.storage import keys as storage_keys


def _structure(name: str, data: Any) -> list[tuple[str, str]]:
    """结构问题：（出错的位置，说明）。同一处同一个问题只算一次（缺几个必填字段时会报几遍）。"""
    found = [(e["where"], f"{e['where']}：{e['problem']}") for e in schema.errors(name, data)]
    return list(dict.fromkeys(found))


def _row_problems(entry_id: str, row: dict[str, Any], table: Table) -> list[str]:
    agreed = agrees(row, table)
    if agreed is None:
        return [f"{entry_id} 的食物编码 {row['food']} 不存在"]
    if not agreed:
        source = SOURCES[split(row["food"])[0]]  # 只有重算的行会对不上：成分表、内置食物
        return [f"{entry_id} 里“{row['name']}”{row['g']} 克的营养数值与{source}算出来的不一致"]
    return []


def _structure_fix(where: str, day: str, doc: Any, at: str, git: Restorable) -> str:
    """结构问题出在某一条记录里、那一条有 id：也能撤掉它。别的只能用 git 恢复。"""
    hit = _IN_ENTRY.match(at)
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if hit and isinstance(entries, list) and int(hit[1]) < len(entries):
        entry = entries[int(hit[1])]
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
            return _undo_entry(where, day, entry["id"], git())
    return _restore_only(where, git())


def day_problems(
    key: bytes, table: Table | None, day: str, doc: Any, where: str, git: Restorable
) -> Found:
    """一份每日记录的全部问题，每个是（问题，改法）。

    table 为 None 时不做营养重算（只查结构和签名）。
    """
    broken = _structure("day", doc)
    if broken:
        return [
            (f"结构不对（{text}）", _structure_fix(where, day, doc, at, git)) for at, text in broken
        ]
    problems = []
    if doc["date"] != day:
        problems.append(
            (f"文件里的日期 {doc['date']} 与文件路径不一致", _restore_only(where, git()))
        )
    for name, label in (("day_type", "当天类型"), ("weight", "体重")):
        if name in doc and not storage_keys.signed(key, name, day, doc[name]):
            problems.append((f"{label}的签名不对", _restore_only(where, git())))
    ids = [entry["id"] for entry in doc["entries"]]
    for duplicated in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append((f"记录 id {duplicated} 重复", _restore_only(where, git())))
    for entry in doc["entries"]:
        found = (
            [] if storage_keys.signed(key, "entry", day, entry) else [f"{entry['id']} 的签名不对"]
        )
        if table is not None:
            for row in entry["items"]:
                found += _row_problems(entry["id"], row, table)
        if found:
            fix = _undo_entry(where, day, entry["id"], git())
            problems += [(text, fix) for text in found]
    return problems


def plan_problems(key: bytes, plans: Any) -> list[str]:
    found = [text for _, text in _structure("plan", plans)]
    if found:
        return [f"结构不对（{text}）" for text in found]
    problems = []
    for pos, plan in enumerate(plans):
        label = f"第 {pos + 1} 条计划"
        if not storage_keys.signed(key, "plan", "", plan):
            problems.append(f"{label}的签名不对")
        if plan["default"] not in plan["days"]:
            problems.append(f"{label}的默认日子类型“{plan['default']}”不在它的 days 里")
        if pos and plan["from"] < plans[pos - 1]["from"]:
            problems.append(f"{label}的生效日期 {plan['from']} 早于上一条，计划日期不能倒退")
    return problems


def defaults_problems(key: bytes, defaults: Any) -> list[tuple[Any, str]]:
    """默认品种文件的问题，每个是（键，问题）：结构、每一条的签名。键是 WHOLE 的是整个文件的问题。
    品种在不在概念表里另外看（stale_defaults）。"""
    if not isinstance(defaults, dict):
        return [(WHOLE, f"结构不对（{text}）") for _, text in _structure("defaults", defaults)]
    found: list[tuple[Any, str]] = []
    for name, entry in defaults.items():
        broken = _structure("defaults", {name: entry})
        found += [(name, f"结构不对（{text}）") for _, text in broken]
        if not broken and not storage_keys.signed(key, "default", name, entry):
            found.append((name, f"“{name}”的默认品种签名不对"))
    return found


def _repaired(key: bytes, plans: Any) -> list[dict[str, Any]]:
    """hl plan set 修坏文件时留下的计划：单独拿出来过得了校验的那几条，按生效日期排好
    （同一天起的几版保持原来的先后）。"""
    entries = plans if isinstance(plans, list) else []
    kept = [plan for plan in entries if not plan_problems(key, [plan])]
    return sorted(kept, key=lambda plan: plan["from"])


def _whole_day(doc: Any, day: str) -> bool:
    """重建清单读得进这份每日文件：是一张表，日期就是路径上的那天，记录是个列表（manifest._scan
    只数这样的）。"""
    return isinstance(doc, dict) and doc.get("date") == day and isinstance(doc.get("entries"), list)
