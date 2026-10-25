"""确认流程、拒绝记号与实际提交前的门禁。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hl.confirmation.judgment import _mode
from hl.confirmation.questions import _retire, ask
from hl.confirmation.queue import _load, _put, _save
from hl.confirmation.records import _alike, _find, _marker, digest
from hl.confirmation.reply_scope import _reply, _verdict
from hl.confirmation.terms import (
    FIX_RETIRED,
    HOW_TO_ANSWER,
    HOW_TO_DROP,
    NO,
    REDO,
    UNCLEAR,
    _fix_refused,
    _fix_void,
)
from hl.origins import inbox as origins_inbox
from hl.origins import matching as origins_matching
from hl.result import WAIT, problem


def _void(
    data_dir: Path, items: list[dict[str, Any]], item: dict[str, Any], reply: origins_inbox.Message
) -> dict[str, Any]:
    """用户否定了：把待确认事项换成一个作废记号，记下否定说在收件箱的哪一行之前。"""
    gone = _marker(item, void=reply.pos + 1)
    _put(data_dir, items, gone)
    return gone


def refusal(
    data_dir: Path,
    kind: str,
    subject: Any,
    spoken: int,
    where: str,
    *,
    redo: str = REDO,
    alike: Any = None,
) -> list[dict[str, str]]:
    """不带确认来问同一件事：用户是不是已经否定过了。是就返回错误。调用方负责加锁。

    spoken 是原话最近一次说在收件箱的第几行，where 是原话那个字段的写法。
    redo 是用户后来又要办时怎么重新问，写进 fix。
    引擎问过之后用户否定了，模型不能拿原来那句话再问一遍、等别的话里冒出一个“好”；
    用户把那句话又说了一遍（说在否定之后），才重新问。
    alike：内容相同的事项（见 _alike）被否定过也算，原话要说在最后一次否定之后。
    """
    items = _load(data_dir)
    key = digest(kind, subject)
    found = [*(it for it in items if it.get("digest") == key), *_alike(items, kind, alike)]
    voids = []
    for item in {it["digest"]: it for it in found}.values():
        # 没问过的、只提醒过模型的（hint）照常问；撤掉的：撤的时候用户没有回答，照常重新问
        if "retired" in item or item.get("hint"):
            continue
        if "void" not in item:
            reply = _reply(data_dir, item)
            if reply is None or _verdict(item, reply) != NO:
                continue
            item = _void(data_dir, _load(data_dir), item, reply)
        voids.append(item["void"])
    if not voids or spoken >= max(voids):
        return []
    return [problem(where, "引擎问过这件事，用户已经否定了", _fix_refused(redo))]


def confirm(
    data_dir: Path,
    kind: str,
    subject: Any,
    answer: str | None,
    now: datetime,
    fields: tuple[str, str] = ("confirm", "answer"),
    *,
    redo: str = REDO,
    alike: Any = None,
    how: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    """核对一次带确认的调用，返回（错误，再问一遍时要先说的话）。调用方负责加锁。

    两样都空就是通过，这条待确认事项销掉；内容相同的事项（alike）也一起销掉：
    用户否定过、后来又确认了，这份内容就不再算被否定过。
    提问之后用户说的第一句话才是回答。它是否定或更正：这件事作废，返回错误。
    它判不出是不是确认：不作废，从现在起重新等回答，调用方把同一个问题连同这句话再问一遍。
    fields 是调用方那条命令里“确认”和“回答”两个字段的写法，错误的 where 用它。
    redo 是用户后来又要办时怎么重新问，写进否定时的 fix。
    how 是再问一遍时怎么回答（照这一问的选项说）；不给就按问的是不是“要删除吗”选（HOW_TO_DROP）。
    """
    confirm_field, answer_field = fields
    key = digest(kind, subject)
    items = _load(data_dir)
    item = _find(items, key)
    if item is not None and "void" in item:
        return [problem(confirm_field, "用户已经否定过，这次确认作废了", _fix_void(redo))], ""
    if item is not None and "retired" in item:
        what = "引擎问过这件事、用户还没回答，就又问了别的事：用户接下来说的话只算后问那件事的回答"
        return [problem(confirm_field, what, FIX_RETIRED)], ""
    if item is None or item.get("hint"):  # 只提醒过模型的（hint）也不算问过用户
        fix = "先不带确认调用一次，把引擎的提问原样问用户；内容和上次问的不一样时要重新问"
        return [problem(confirm_field, "没有内容相同的待确认事项", fix)], ""
    if not answer:
        fix = f"把用户回答的原话放进 {answer_field} 一并带上"
        return [problem(answer_field, "带确认调用时没有附上用户的回答", fix)], ""
    reply = _reply(data_dir, item)
    if reply is None:  # fix 以 WAIT 开头，next 跟着说先问用户、等他回答（result.rejected）
        return [problem(confirm_field, "引擎提问之后，用户还没有说过话", WAIT)], ""
    # 看用户的整句话，不看模型摘出来的那几个字："不对"里摘一个"对"不算确认
    verdict = _verdict(item, reply)
    if verdict == NO:
        _void(data_dir, items, item, reply)
        what = f"引擎提问之后用户说的是“{reply.text}”，不是确认"
        return [problem(answer_field, what, _fix_void(redo))], ""
    if verdict == UNCLEAR:
        again = {**item, "asked_at": now.isoformat(), "inbox": origins_inbox.size(data_dir)}
        session = item.get("session", "")
        _put(data_dir, _retire(data_dir, items, key, session), again)  # 再问一遍也是只问这一件
        how = how or HOW_TO_DROP.get(_mode(item.get("deleting", False)), HOW_TO_ANSWER)
        return [], f"你刚才说的是“{reply.text}”，我没法确定这是不是确认。{how}。"
    if not origins_matching.said_in(answer, [reply]):
        fix = f"回答要一字不改地抄用户在提问之后说的第一句话：“{reply.text}”"
        what = f"“{answer}”不是用户在引擎提问之后说的第一句话"
        return [problem(answer_field, what, fix)], ""
    same = {key, *(it["digest"] for it in _alike(items, kind, alike))}
    _save(data_dir, [it for it in items if it.get("digest") not in same])
    return [], ""


def check(
    data_dir: Path,
    kind: str,
    subject: Any,
    question: str,
    now: datetime,
    *,
    confirmed: bool,
    answer: str | None,
    spoken: int,
    fields: tuple[str, str] = ("--confirm", "--answer"),
    said: str = "--said",
    deleting: bool | str = False,
    redo: str = REDO,
    alike: Any = None,
    how: str | None = None,
    units: list[dict[str, int]] | None = None,
    about: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """一件要用户确认才能办的事。返回（错误，要问用户的话）：两样都空，就是用户确认过了。

    confirmed 是这次调用带没带确认。没带：记下这次提问，返回提问（用户已经否定过的不再问）；
    带了：按 confirm 核对，回答判不出时返回要再问一遍的话。
    spoken 是原话最近一次说在收件箱的第几行，said 是原话那个字段的写法。
    redo 是用户否定之后又要办时怎么重新问（写进 fix），默认用他否定之后说的那句话。
    alike 是这件事去掉不相干的部分之后的内容（见 _alike）；how 是判不出、再问一遍时怎么回答
    （见 confirm）；units 是问的是哪几截原话（见 ask）；about 是问的是哪一条（见 asked_about）。
    调用方负责加锁。
    """
    if confirmed:
        errors, again = confirm(
            data_dir, kind, subject, answer, now, fields, redo=redo, alike=alike, how=how
        )
        return errors, again + question if again else ""
    refused = refusal(data_dir, kind, subject, spoken, said, redo=redo, alike=alike)
    if refused:
        return refused, ""
    ask(
        *(data_dir, kind, subject, question, now),
        deleting=deleting,
        confirm=True,
        alike=alike,
        units=units,
        about=about,
        spoken=spoken,
    )
    return [], question
