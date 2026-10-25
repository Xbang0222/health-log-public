"""登记、替代与退役引擎提出的问题。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hl.confirmation.queue import _load, _put, _save
from hl.confirmation.records import _alike, _asking, _find, _marker, _open, _said_no, digest
from hl.confirmation.reply_scope import _heard, _settle
from hl.origins import inbox as origins_inbox


def _retire(
    data_dir: Path, items: list[dict[str, Any]], key: str, session: str = ""
) -> list[dict[str, Any]]:
    """引擎就 key 这件事问用户（请他确认，或者 hl add 追问）：别的确认、别的追问里用户还没回答的
    都撤掉，接下来说的话只算这一问的回答（第九轮 C-1：追问不撤，用户答删除的“是的”同时也答了
    藜麦是哪一种）。

    撤掉的换成撤掉的记号（记下撤掉时收件箱的行数，连同提问时的），带确认来、拿回答来交时说清楚
    为什么不算。用户已经回答了的不撤：那句话说在这一问之前，是在答那一问。确认里否定了的换成作废
    记号，肯定的、判不出的原样留着，带确认来照常核对（判不出的再问一遍）；追问的回答照常用，
    但只认说在这一问之前的：追问之后用户说的话不一定是在答它（先说了别的事），这一问之后说的
    只算这一问的回答，记下从哪一行起不认（cut，见 cut_off；用户定的第 24 条，复核 C-3）。
    确认只认提问之后的第一句话，用不着记。

    session 是这一问在哪个对话里问的：只撤同一个对话里的（provenance.together）。别的对话里
    用户说的话不是在答这一问，那边问的事照样等那边的回答（K-1）。
    """
    size = origins_inbox.size(data_dir)
    kept = []
    for it in items:
        here = origins_inbox.together(it.get("session", ""), session)
        if _asking(it) and it["digest"] != key and here:
            if _heard(data_dir, it) is None:
                it = _marker(it, retired=size, inbox=it["inbox"])
            elif _open(it):
                it = _settle(data_dir, it) or it
            elif "cut" not in it:
                it = {**it, "cut": size}
        kept.append(it)
    return kept


def ask(
    data_dir: Path,
    kind: str,
    subject: Any,
    summary: str,
    now: datetime,
    renew: bool = True,
    deleting: bool | str = False,
    confirm: bool = False,
    alike: Any = None,
    units: list[dict[str, int]] | None = None,
    about: dict[str, str] | None = None,
    spoken: int | None = None,
) -> None:
    """记下"引擎刚刚就这件事问过用户"。调用方负责加锁。

    summary 是提问的原文，只给人排查时看（翻 .hl/pending.json），引擎自己不读它；
    设计说明里的“事项摘要”是 digest。deleting：问的是不是“要删除吗”、删的是什么（见 judge）。
    renew 为假时，已经问过就不动起点：追问可能分几次问完，回答只要出自第一次提问之后；
    只记下最近一次问在哪（last），撤别的时看它（_heard）。撤掉了的照样重新算起：
    撤掉之后用户说的话是在答别的事。
    confirm：这是请用户确认（经 check 问的）；不是的就是 hl add 的追问（follow）。
    不管是不是确认，引擎都在问用户：别的确认、别的追问里用户还没回答的都撤掉（_retire），
    接下来说的话只算这一问的回答（用户答品种的“是的”“不是全脂”不是在答删记录、去重；
    答删记录的“是的”也不是在答品种）。
    alike：这件事去掉不相干的部分之后的内容（见 _alike），内容相同的事项被否定过也算否定过。
    units：这一问问的是哪几截原话（见 denied），挂在这一问上，和它一起撤掉、一起作废。
    about：问的是哪一条（见 asked_about），给不指明是哪一条的命令说出问过的是哪一条。
    spoken：原话说在收件箱第几行。记下它是在哪个对话里说的（session）：引擎在那个对话里问，
    回答只认那个对话里的话（_reply、_heard），撤别的问题也只撤那个对话里的（_retire，K-1）。
    """
    key = digest(kind, subject)
    session = origins_inbox.session_at(data_dir, spoken) if spoken is not None else ""
    items = _retire(data_dir, _load(data_dir), key, session)
    old = _find(items, key)
    if not renew and old is not None and "done" not in old and "retired" not in old:
        old["last"] = origins_inbox.size(data_dir)  # 追问的起点不动；撤掉别的照样要记下
        if "cut" in old:  # 被别的问题顶掉过：顶掉之后、这次再问之前说的话照样不认（cut_off）
            old["gaps"] = [*old.get("gaps", []), [old.pop("cut"), old["last"]]]
        _save(data_dir, items)
        return
    asked = {"digest": key, "kind": kind, "summary": summary, "asked_at": now.isoformat()}
    asked["inbox"] = origins_inbox.size(data_dir)  # 提问时收件箱有多少行：之后追加的才算回答
    asked["deleting"] = deleting
    if session:
        asked["session"] = session
    if alike is not None:
        asked["alike"] = digest(kind, alike)
    if about is not None:
        asked["about"] = about
    if not confirm:
        asked["follow"] = True
    else:
        asked["confirm"] = True
        before = [*([old] if old is not None else []), *_alike(items, kind, alike)]
        if any("void" in it or it.get("refused") for it in before):
            asked["refused"] = True  # 用户否定过、又要办：办成之前都记着（was_refused）
            said_no = [line for line in map(_said_no, before) if line is not None]
            if said_no:  # 用户说“不”的那句话在收件箱第几行（refused_at）
                asked["no_at"] = max(said_no)
        if units:
            asked["units"] = units
    if not renew and old is not None and "done" in old:  # 这句原话记成过一餐：那之前的回答用过了
        asked["inbox"] = max(int(old.get("inbox", 0)), int(old["done"]))
    _put(data_dir, items, asked)


def hint(data_dir: Path, kind: str, subject: Any, summary: str, now: datetime) -> bool:
    """这件事先只提醒模型（多半是它漏填了：补上再调用，不用问用户）。第一次提醒返回真。
    调用方负责加锁。

    提醒不是请用户确认：只记一笔，不撤别的确认；带确认来也不算数（confirm 只认经 check 问过的）。
    同一件事原样又来了（模型看过提醒，说不是漏填），或者问过、否定过、撤掉过（pending.json 里
    有它），返回假：调用方照常经 check 请用户确认。
    """
    key = digest(kind, subject)
    items = _load(data_dir)
    if _find(items, key) is not None:
        return False
    note = {"digest": key, "kind": kind, "summary": summary, "asked_at": now.isoformat()}
    _put(data_dir, items, {**note, "inbox": origins_inbox.size(data_dir), "hint": True})
    return True
