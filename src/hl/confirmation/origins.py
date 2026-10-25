"""按原话位置查询已问、已否定和已退役的问题。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl.confirmation.queue import _load
from hl.confirmation.records import _find, _open, _said_no, digest
from hl.confirmation.reply_scope import _reply, _verdict
from hl.confirmation.terms import ABOUT, NO


def asked_about(
    data_dir: Path, kind: str, said: str, spoken: int
) -> tuple[dict[str, str], bool] | None:
    """kind 这种事凭原话 said（textnum.compact 过的，说在收件箱第 spoken 行）最近一次问的是哪一条
    （about，见 ask），这一问还在等回答（真）还是被别的问题撤掉了（假）。调用方负责加锁。

    给不指明是哪一条的命令用（hl undo 不给 --id 删当天最后一条，R18）：问过之后最后一条换了，
    要说出问过的是哪一条，不能改问、改删别的（第九轮 A-2）。没这样问过、问完已经办了、
    用户否定了的，返回 None；用户在提问之后又说了一遍这句话（spoken 在提问之后），是新的一次，
    也返回 None。
    """
    for item in reversed(_load(data_dir)):
        about = item.get("about")
        if item.get("kind") != kind or not isinstance(about, dict) or about.get("said") != said:
            continue
        if not (_open(item) or "retired" in item) or spoken >= int(item.get("inbox", 0)):
            continue
        if all(isinstance(about.get(name), str) for name in ABOUT):
            return about, _open(item)
    return None


def asked_from(data_dir: Path, kind: str, said: str) -> list[tuple[int, int, int | None]]:
    """规则 24：kind 这种事凭原话 said（textnum.compact 过的）问过、还没办成的那几问，问的那段原话
    出自哪里（about 里的 message、start，见 ask）：（那条消息在收件箱第几行，从第几个字起，
    之后说的话到第几行为止还算在答这一问）。调用方负责加锁。

    还在等回答的、被别的问题撤掉的都算：用户之后又说了同样的话（回答里又带着它，或者撤掉之后答
    后问的那件事时说的），原话还是问的那一句，不是他后来那句里的（add._asked_spot）。用户已经说了
    “不”的，那句否定之后说的是他新说的那句（R11 重说），第三项是那句否定在第几行；别的是 None。
    作废了的（否定已经办了）不算：之后说的都是新说的。
    """
    found = []
    for item in _load(data_dir):
        about = item.get("about")
        if item.get("kind") != kind or not isinstance(about, dict) or about.get("said") != said:
            continue
        message, start = about.get("message"), about.get("start")
        if not (_open(item) or "retired" in item) or not isinstance(message, str):
            continue
        if not (message.isdecimal() and isinstance(start, str) and start.isdecimal()):
            continue
        reply = _reply(data_dir, item) if _open(item) else None
        until = reply.pos if reply is not None and _verdict(item, reply) == NO else None
        found.append((int(message), int(start), until))
    return found


def answering(data_dir: Path, kind: str, said: str, pos: int) -> int | None:
    """收件箱第 pos 行那句话是不是在答 kind 这种事凭原话 said（textnum.compact 过的）问的那一问：
    那一问还在等回答，这句是提问之后用户说的第一句。是就返回提问时收件箱的行数，不是返回 None。
    调用方负责加锁。

    用户回答时又把原话说了一遍（问“要删除 e1 吗”，他答“香蕉那条删掉”）：原话还是提问之前
    那一处，不是新的一次（用户定的第 24 条，复核 C-4）。
    """
    for item in reversed(_load(data_dir)):
        about = item.get("about")
        if item.get("kind") != kind or not isinstance(about, dict) or about.get("said") != said:
            continue
        if _open(item) and (reply := _reply(data_dir, item)) is not None and reply.pos == pos:
            return int(item["inbox"])
    return None


def denied_about(data_dir: Path, kind: str, said: str, spoken: int) -> dict[str, str] | None:
    """kind 这种事凭原话 said（textnum.compact 过的，说在收件箱第 spoken 行）问过、用户否定了的
    是哪一条（about，见 ask）；原话说在那句“不”之后的，是新的一次，不算。没有返回 None。
    调用方负责加锁。

    给不指明是哪一条的命令用（hl undo 不给 --id）：否定之后又记了一餐，当天最后一条换了，拿否定
    之前的原话再来，还是用户否定了的那件事，不能改问新记的那条（用户定的第 25 条，复核 C-4）。
    """
    for item in reversed(_load(data_dir)):
        about = item.get("about")
        if item.get("kind") != kind or not isinstance(about, dict) or about.get("said") != said:
            continue
        if not all(isinstance(about.get(name), str) for name in ABOUT):
            continue
        reply = _reply(data_dir, item) if _open(item) else None
        said_no = reply.pos if reply and _verdict(item, reply) == NO else _said_no(item)
        if said_no is not None and spoken <= said_no:
            return about
    return None


def retired(data_dir: Path, kind: str, subject: Any) -> bool:
    """引擎就这件事问过、用户还没回答就又问了别的事，这一问撤掉了，后来也没再问过（见 _retire）。
    给 hl add 用：追问撤掉了，用户后来的话不能拿来答它（第九轮 C-1）。"""
    item = _find(_load(data_dir), digest(kind, subject))
    return item is not None and "retired" in item and "done" not in item


def cut_off(data_dir: Path, kind: str, subject: Any, spoken: list[int]) -> bool:
    """拿来答这一问的话里，有没有说在别的问题顶掉它之后、再问它之前的（见 _retire）。
    spoken 是那几句回答各在收件箱的第几行；没带回答的，这一问还被顶着没再问过就算有：
    分不清是照哪句补的（用户定的第 24 条，复核 C-3）。记成过一餐的不管。"""
    item = _find(_load(data_dir), digest(kind, subject))
    if item is None or "done" in item:
        return False
    gaps = [*item.get("gaps", []), *([[item["cut"], None]] if "cut" in item else [])]
    if not spoken:
        return "cut" in item
    return any(start <= pos and (end is None or pos < end) for pos in spoken for start, end in gaps)


def asked(data_dir: Path, kind: str, subject: Any, day: str | None = None) -> int:
    """引擎就这件事提问时收件箱的行数；没问过返回 0。

    这句原话已经记成过一餐、这次要记到另一天：返回记成时收件箱的行数，那之前的回答用过了。
    """
    item = _find(_load(data_dir), digest(kind, subject))
    if item is None:
        return 0
    if "done" in item and item.get("date") != day:
        return int(item["done"])
    return int(item.get("inbox", 0))
