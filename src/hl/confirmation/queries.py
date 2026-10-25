"""按事项、内容和位置查询回答与拒绝状态。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl.confirmation.confirmation import _void
from hl.confirmation.queue import _load
from hl.confirmation.records import _alike, _find, _open, _said_no, _spots, digest
from hl.confirmation.reply_scope import _reply, _verdict
from hl.confirmation.terms import NO, REDO, _fix_refused, _fix_void
from hl.origins import inbox as origins_inbox


def verdict(data_dir: Path, kind: str, subject: Any) -> str | None:
    """这件事还在等确认、用户提问之后说了话：那句话判下来是什么（YES、NO、UNCLEAR），只看不销。
    没问过、问过的作废了撤掉了、用户还没说话，返回 None。"""
    item = _find(_load(data_dir), digest(kind, subject))
    reply = _reply(data_dir, item) if item is not None and _open(item) else None
    return _verdict(item, reply) if item is not None and reply is not None else None


def denied(data_dir: Path, kind: str, units: list[dict[str, int]]) -> origins_inbox.Message | None:
    """R11：用户否定过的那一问里，有没有和 units 碰到同一截原话的。有就返回用户那句否定。

    问的是哪几截挂在那一问上（ask 的 units），回答只算这一问还开着时用户说的话：
    用户回答之前引擎又问了别的，这一问撤掉了，它的那几截跟着不算（用户答的是后问的那件事）；
    用户否定了的换成作废记号，那几截留在作废记号上，只看位置、不按条数清（_trim），
    后来再问多少别的事都挤不掉。还开着、用户提问之后说的第一句话是否定的，也算。调用方负责加锁。
    """
    want = _spots({"units": units})
    for item in _load(data_dir):
        if item.get("kind") != kind or not _spots(item) & want:
            continue
        if "void" in item:  # 作废记号记的是否定的下一行
            said = origins_inbox.since(data_dir, item["void"] - 1)[:1]
            return said[0] if said else origins_inbox.Message(None, "", item["void"] - 1)
        reply = _reply(data_dir, item) if _open(item) else None
        if reply is not None and _verdict(item, reply) == NO:
            return reply
    return None


def was_refused(data_dir: Path, kind: str, subject: Any, alike: Any = None) -> bool:
    """用户否定过这件事：作废记号还在，或者否定之后又问过、还没办成。调用方负责加锁。

    给“有时才要问”的命令用（计划这次没有对不上的、不用问）：用户说过不，后来又要办，
    就算这次没有别的要问，也要再问一遍，不能悄悄办了它（R19）。
    alike：内容相同的事项（见 _alike）被否定过也算。
    """
    items = _load(data_dir)
    key = digest(kind, subject)
    for item in [*(it for it in items if it.get("digest") == key), *_alike(items, kind, alike)]:
        if "void" in item or item.get("refused"):
            return True
        reply = _reply(data_dir, item) if _open(item) else None
        if reply is not None and _verdict(item, reply) == NO:
            return True
    return False


def refused_in(data_dir: Path, kind: str, subject: Any, alike: Any = None) -> int | None:
    """用户否定这件事的那句话在收件箱的第几行；没否定过（或者否定之后又问过）返回 None。
    调用方负责加锁。

    给原话可能就出自那句否定的命令用（体重：问“81 公斤吗”，用户答“不对，今天就是81公斤”；
    计划、当天类型：用户答“不是，就按训练日 2000 千卡定”）：照 fix 拿那句话来调用，
    不是拿原来那句话再问一遍，也不算确认，要重新问用户（见 unsure）。
    还在等回答、回答是否定的，和 refusal 一样先换成作废记号。
    alike：内容相同的事项（见 _alike）也算，几次否定算最后那一次。
    """
    items = _load(data_dir)
    key = digest(kind, subject)
    found = [*(it for it in items if it.get("digest") == key), *_alike(items, kind, alike)]
    lines = []
    for item in {it["digest"]: it for it in found}.values():
        if _open(item):
            reply = _reply(data_dir, item)
            if reply is not None and _verdict(item, reply) == NO:
                item = _void(data_dir, _load(data_dir), item, reply)
        if "void" in item:
            lines.append(int(item["void"]) - 1)
    return max(lines, default=None)


def denial(
    data_dir: Path,
    kind: str,
    subject: Any,
    errors: list[dict[str, str]],
    *,
    redo: str = REDO,
    alike: Any = None,
) -> origins_inbox.Message | None:
    """errors 只有“用户否定了”这一条（带确认来确认作废了，或者拿原来那句话再来被拒，redo 是调用方
    给 check、refusal 的那个）：返回用户说“不”的那句话，调用方看里面是不是又把这件事说了一遍
    （第九轮 A-6）。别的错误、找不到那句话的，返回 None。调用方负责加锁。"""
    if len(errors) != 1 or errors[0]["fix"] not in (_fix_void(redo), _fix_refused(redo)):
        return None
    line = refused_in(data_dir, kind, subject, alike)
    if line is None:
        return None
    return next(
        (message for message in origins_inbox.since(data_dir, line) if message.pos == line), None
    )


def refused_at(data_dir: Path, kind: str, subject: Any) -> int | None:
    """用户对这件事说“不”的那句话在收件箱第几行；没说过（没问过、还没回答、同意了、撤掉了）
    返回 None。调用方负责加锁。

    否定之后又问了一遍、还没办成的（还在等回答、回答判不出、答了“对”还没去办、被别的问题撤掉了），
    也还记着那句“不”（R19）：办成之前不能当他没说过。又说了一次“不”的，算后说的那一次。
    """
    item = _find(_load(data_dir), digest(kind, subject))
    if item is None:
        return None
    reply = _reply(data_dir, item) if _open(item) else None
    if reply is not None and _verdict(item, reply) == NO:
        return reply.pos
    return _said_no(item)


def reasked(data_dir: Path, kind: str, subject: Any) -> bool:
    """用户否定过这件事、引擎又问了，还没办成（还在等回答、回答判不出、被别的问题撤掉了）。
    调用方负责加锁。

    给有时才要问的命令用（体重这次一眼清楚、也没跳变）：不带确认来也照样再问，带确认、
    用户答了“对”才办（R19）。又被否定了的不算：那是作废记号，照 refusal 的规矩办。
    """
    item = _find(_load(data_dir), digest(kind, subject))
    if item is None or not item.get("refused") or "void" in item:
        return False
    reply = _reply(data_dir, item) if _open(item) else None
    return reply is None or _verdict(item, reply) != NO
