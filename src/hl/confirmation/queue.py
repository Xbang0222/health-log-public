"""确认队列的唯一读写与保留策略。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl.confirmation.records import _sound
from hl.confirmation.reply_scope import _settle
from hl.confirmation.terms import FILE, KEEP
from hl.origins import inbox as origins_inbox
from hl.storage import io as storage_io


def _path(data_dir: Path, name: str = FILE) -> Path:
    return data_dir / storage_io.HIDDEN / name


def _load(data_dir: Path, name: str = FILE) -> list[dict[str, Any]]:
    try:
        items = json.loads(_path(data_dir, name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    if name == FILE:  # recorded.json 的每一条由 _span 把关
        return [item for item in items if _sound(item)]
    return [item for item in items if isinstance(item, dict)]


def _save(data_dir: Path, items: list[dict[str, Any]]) -> None:
    text = json.dumps(_trim(data_dir, items), ensure_ascii=False, indent=1)
    storage_io.write_text(_path(data_dir), text)


def _trim(data_dir: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只留还用得着的。

    一条事项只在它的位置（提问时收件箱的行数，作废记号是否定的下一行）还没落到
    收件箱最近 50 条之外时有用：比那更早的话再也抄不到了。作废记号只看这个，不管后来又问了多少
    别的事，不然用户的“不”会被挤掉，原来那句话又能拿来问一遍。用户否定过、后来又问了还没办成的
    （refused，问着的、被撤掉的都算）也一样：挤掉了，再交否定之前的原话就不问直接办了。
    固定批次（K23）和明确改餐的替换句（K12）也只看出处位置，不能被其他事项挤掉后扩大或重复记。
    别的再按条数限着，最多 KEEP 条，先去掉最早的。记成过一餐的（done）只按条数：
    R11 去重还要看那句原话是什么时候记成的。
    要去掉的确认先看它的回答：用户已经否定了的换成作废记号，照上面的规矩留不留。
    """
    messages = origins_inbox.recent(data_dir) or []
    oldest = messages[0].pos if messages else 0  # 收件箱里还抄得到的最早那条消息

    def stale(item: dict[str, Any]) -> bool:
        if "void" in item:  # 否定之前说的话（void 之前的行）都抄不到了
            return item["void"] <= oldest
        if "done" in item:
            return False
        return int(item.get("inbox", 0)) < oldest

    def placed(item: dict[str, Any]) -> bool:  # 只看位置、不按条数清的
        return (
            "void" in item
            or bool(item.get("refused"))
            or item.get("kind") == "bound-targets"
            or (item.get("kind") == "resay" and bool(item.get("replacement")))
        )

    kept = []
    for item in items:
        if stale(item):
            item = _settle(data_dir, item)
            if item is None or stale(item):
                continue
        kept.append(item)
    extra = sum(not placed(item) for item in kept) - KEEP
    trimmed = []
    for item in kept:
        if not placed(item) and extra > 0:
            extra -= 1
            item = _settle(data_dir, item)
            if item is None or stale(item):
                continue
        trimmed.append(item)
    return trimmed


def _put(data_dir: Path, items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    """把 item 放到最后（同一件事原来那条换掉）。"""
    _save(data_dir, [*(it for it in items if it.get("digest") != item["digest"]), item])
