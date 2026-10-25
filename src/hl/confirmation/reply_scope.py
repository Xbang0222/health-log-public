"""限定回答的消息位置、会话与生效范围。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl.confirmation.judgment import judge
from hl.confirmation.records import _marker, _open
from hl.confirmation.terms import NO
from hl.origins import inbox as origins_inbox


def _heard(data_dir: Path, item: dict[str, Any]) -> origins_inbox.Message | None:
    """这一问最近一次问了之后用户说的第一句话；还没说过返回 None。追问分几次问完时起点不动
    （回答都从第一次算起），最近一次问在哪记在 last 上；别的就是提问的位置。"""
    start = item.get("last", item["inbox"])
    return next(iter(origins_inbox.since(data_dir, start, item.get("session", ""))), None)


def _settle(data_dir: Path, item: dict[str, Any]) -> dict[str, Any] | None:
    """要去掉的这一条：还在等回答的确认、用户已经否定了的，换成作废记号，那句“不”不能丢；
    别的返回 None。"""
    if not _open(item):
        return None
    reply = _reply(data_dir, item)
    return _marker(item, void=reply.pos + 1) if reply and _verdict(item, reply) == NO else None


def _reply(data_dir: Path, item: dict[str, Any]) -> origins_inbox.Message | None:
    """引擎提问之后用户说的第一句话；还没说过返回 None。

    同时开着几个对话时，只认问这件事的那个对话里的话（ask 记下的 session，K-1）。
    只按收件箱里的先后认（提问时收件箱有几行，之后的第一条），不看时间：
    时钟可以拨（HL_NOW），拨快了就会跳过用户紧接着说的“不删”，拿后面的“好”当回答。
    """
    return next(iter(origins_inbox.since(data_dir, item["inbox"], item.get("session", ""))), None)


def _verdict(item: dict[str, Any], reply: origins_inbox.Message) -> str:
    return judge(reply.text, deleting=item.get("deleting", False))
