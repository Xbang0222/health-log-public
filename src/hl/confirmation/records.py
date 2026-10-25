"""确认队列项的形状、摘要、匹配与状态读取。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from hl.confirmation.terms import AGAIN, DROP_DEFAULT, DROP_RECORD, MORE


def _count(value: Any) -> bool:
    """收件箱的行数：非负整数（true、false 不算）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _sound(item: Any) -> bool:
    """pending.json 里的这一条是不是好的。写坏了的（手改过的、来路不明的）当作没问过：
    带确认来是“没有内容相同的待确认事项”，重新问一遍就好，不让命令出内部错误。"""
    if not isinstance(item, dict) or not isinstance(item.get("digest"), str):
        return False
    if not isinstance(item.get("alike", ""), str) or not isinstance(item.get("session", ""), str):
        return False
    if "void" in item:
        return _count(item["void"])
    if "retired" in item:
        return _count(item["retired"]) and _count(item.get("inbox", 0))
    if not _count(item.get("inbox")) or ("done" in item and not _count(item["done"])):
        return False
    mode = item.get("deleting", False)
    if not (isinstance(mode, bool) or mode in ("", DROP_RECORD, DROP_DEFAULT, AGAIN, MORE)):
        return False
    flags = ("confirm", "hint", "refused", "follow", "finished")
    if any(not isinstance(item.get(flag, False), bool) for flag in flags):
        return False
    if any(name in item and not _count(item[name]) for name in ("no_at", "last", "cut")):
        return False
    gaps = item.get("gaps", [])
    if not isinstance(gaps, list) or not all(_gap(gap) for gap in gaps):
        return False
    try:
        datetime.fromisoformat(item.get("asked_at", "2000-01-01"))
    except (TypeError, ValueError):
        return False
    return True


def _gap(gap: Any) -> bool:
    """追问的回答不认的一段收件箱：[起, 止)，两个行数（见 ask、cut_off）。"""
    return isinstance(gap, list) and len(gap) == 2 and all(map(_count, gap)) and gap[0] <= gap[1]


def digest(kind: str, subject: Any) -> str:
    """事项摘要：同一种事、同样的内容，摘要相同。"""
    text = json.dumps([kind, subject], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()


# ---------- 记下问过什么 ----------
def _find(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("digest") == key), None)


def _marker(item: dict[str, Any], **mark: int) -> dict[str, Any]:
    """待确认事项换成一个记号：void 作废了，retired 撤掉了。否定过的照样记着（was_refused），
    内容相同的别的事项也照样认得出（alike）。

    问的是哪几截原话（units，见 denied）只留在作废记号上：撤掉的那一问用户没回答过，不挡什么。
    否定过又问了的，撤掉了也还记着用户说“不”的那一行（no_at，见 refused_at）。
    问的是哪一条（about，见 asked_about）也留着：带确认来不指明是哪一条时，好说出问过的是哪一条。
    """
    kept = ("digest", "kind", "summary", "refused", "no_at", "alike", "about")
    kept += ("units",) if "void" in mark else ()
    return {**{key: item[key] for key in kept if key in item}, **mark}


def _alike(items: list[dict[str, Any]], kind: str, alike: Any) -> list[dict[str, Any]]:
    """内容和这件事相同的事项。alike 是这件事去掉不相干的部分之后剩下的内容：计划只看定的是什么
    （每种日子的各项数，名称按归一后的写法），生效日期、已有的几版计划、默认的日子不一样，
    也是用户否定过的那份（R19）。"""
    if alike is None:
        return []
    same = digest(kind, alike)
    return [item for item in items if item.get("alike") == same]


def _said_no(item: dict[str, Any]) -> int | None:
    """用户对这件事说“不”的那句话在收件箱第几行：作废记号记着它的下一行；否定过、又问了还没办成的
    记在 no_at 上。别的（没否定过的、早先没记下这一行的）返回 None。"""
    if "void" in item:
        return int(item["void"]) - 1
    return item["no_at"] if item.get("refused") and _count(item.get("no_at")) else None


def _open(item: dict[str, Any]) -> bool:
    """还在等用户回答的确认（经 check 问的；hl add 的追问不算）。"""
    return item.get("confirm") is True and "void" not in item and "retired" not in item


def _asking(item: dict[str, Any]) -> bool:
    """还在等用户回答的一问：确认（_open），或者 hl add 的追问（还没记成一餐的）。"""
    if "void" in item or "retired" in item:
        return False
    return item.get("confirm") is True or (item.get("follow") is True and "done" not in item)


def _spots(item: dict[str, Any]) -> set[tuple[int, int]]:
    """这一问问的是哪几截原话：（消息在收件箱第几行，那一截从第几个字开始）。写坏了的不算。"""
    units = item.get("units")
    if not isinstance(units, list):
        return set()
    return {
        (unit["message"], unit["unit"])
        for unit in units
        if isinstance(unit, dict) and _count(unit.get("message")) and _count(unit.get("unit"))
    }
