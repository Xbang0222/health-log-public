"""判断 HEAD 数据能否保留当前清单已知的全部记录。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl.manifests.model import PARTS, Items, _blank, _defaults, _entries, _signed_part, versions
from hl.storage import keys as storage_keys


def _hashable(value: Any) -> Any:
    """被改坏的文件里，id、键可能是列表之类：拿它的写法当键，免得放不进集合。"""
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _keeps(
    head: Mapping[Any, Any], valid: Items, present: set[Any], want: Mapping[Any, Any] | None
) -> bool:
    """用 HEAD 那份（head：键 → 签名，它自己过得了校验）换掉工作区那一份，丢不丢东西、带不带回东西。

    valid 是工作区那一份里签名有效的（键，签名），present 是工作区那一份里有的键（坏了的也算）。
    want 是清单里记着的（键 → 签名；早先的清单只记了键，签名是 None）。清单用不上
    （不见了、读不出来、验签不过、还没建过、没有这一节）时是 None：只拿工作区核对，不算核对过。
    """
    if want is not None:
        for name, sig in want.items():
            if name not in head or (sig is not None and head[name] != sig):
                return False  # 清单里记着的，HEAD 那份里没有，或者不是同一条
    for name, sig in valid:
        if head.get(name) == sig:
            continue
        if want is not None and want.get(name) is not None and want[name] != sig:
            continue  # 清单里记着的是另一条：工作区里这一条本来就不对（退回过旧版本）
        return False  # 签名有效、HEAD 那份里没有或不一样：取回就丢了它（没提交的写入）
    kept = set(valid)
    for name, sig in head.items():
        if want is None and name in present:
            continue
        if want is not None and (name in want or (name, sig) in kept):
            continue  # 清单里没有、工作区里本来就多出来的：取回前后一样，照那一条的 fix 收场
        return False  # 清单里去掉了（或工作区里根本没有）的，取回会把它带回来（没提交的撤销）
    return True


def _day_items(key: bytes, day: str, doc: Any) -> tuple[Items, set[Any]]:
    """一天的文件里签名有效的（键，签名），和有的键（坏了的也算）。
    键是（"entry"，记录 id）、"weight"、"day_type"。"""
    if not isinstance(doc, dict):
        return [], set()
    entries = _entries(doc)
    valid: Items = [
        (("entry", entry.get("id")), entry["sig"])
        for entry in entries
        if storage_keys.signed(key, "entry", day, entry)
    ]
    present = {("entry", _hashable(entry.get("id"))) for entry in entries}
    for name, _ in PARTS:
        if name in doc:
            present.add(name)
        part = _signed_part(key, day, doc, name)
        if part:
            valid.append((name, part["sig"]))
    return valid, present


def head_keeps_day(
    listed: Mapping[str, Any] | None, key: bytes, day: str, head: Any, now: Any
) -> bool:
    """这一天的文件换成 HEAD 那份（head，已经过了校验）不丢、不带回东西；now 是工作区那一份。"""
    want = None
    if listed is not None:
        day_listed = listed.get("days", {}).get(day) or _blank()
        want = {("entry", name): sig for name, sig in day_listed["entries"].items()}
        for name, _ in PARTS:
            if day_listed[name]:
                want[name] = day_listed[name] if isinstance(day_listed[name], str) else None
    valid, present = _day_items(key, day, now)
    return _keeps(dict(_day_items(key, day, head)[0]), valid, present, want)


def head_keeps_defaults(listed: Mapping[str, Any] | None, key: bytes, head: Any, now: Any) -> bool:
    """defaults.yaml 换成 HEAD 那份不丢、不带回默认品种。早先的清单没有这一节，只拿工作区核对。"""
    section = None if listed is None else listed.get("defaults")
    want = None if section is None else {name: was.get("sig") for name, was in section.items()}
    valid = [(name, entry["sig"]) for name, entry in _defaults(key, now).items()]
    present = {_hashable(name) for name in now} if isinstance(now, dict) else set()
    have = {name: entry["sig"] for name, entry in _defaults(key, head).items()}
    return _keeps(have, valid, present, want)


def head_keeps_plans(listed: Mapping[str, Any] | None, key: bytes, head: Any, now: Any) -> bool:
    """plan.yaml 换成 HEAD 那份不丢版数、生效的不变：清单记着先后时 HEAD 那份得和它一样，
    工作区里签名有效的每一版它也都有；清单用不上（或只记了版数）时，工作区里签名有效的各版
    得按原来的先后都在 HEAD 那份里（排在后面的生效，先后也要对）。"""
    have, found = versions(key, head), versions(key, now)
    want = None if listed is None else listed.get("plans")
    if isinstance(want, list):
        return have == want and set(found) <= set(have)
    if isinstance(want, int) and len(set(have)) < want:
        return False
    rest = iter(have)
    return all(sig in rest for sig in found)
