"""用户消息、原话引用模型及追加式收件箱读写。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hl.storage import io as storage_io

RECENT = 50


INBOX = "inbox.jsonl"


@dataclass(frozen=True)
class Message:
    ts: datetime | None
    text: str
    pos: int = 0  # 在收件箱里是第几行（从 0 数）；收件箱只追加，行号能分出先后
    # 在哪个对话（会话）里说的：钩子输入的 session_id。旧版本钩子写的、钩子输入里没有的是空
    session: str = ""
    agent: str = ""  # 钩子记下的 Agent 名称（claude、codex）；hl doctor 用它说钩子在哪边工作


def together(one: str, other: str) -> bool:
    """两句话是不是可能出自同一个对话：会话一样，或者有一句没记会话（旧版本写的，照旧算）。
    同时开着几个对话时，引擎在一个对话里问的事，只有这个对话里的话才是回答（K-1）。"""
    return not one or not other or one == other


@dataclass(frozen=True)
class Quote:
    """一段原话的出处：出自哪条消息、消息里对应的原文，以及同一个半句里没抄到的前后文。

    text 是用户自己写的那一段（全角已折成半角）：标点、空格以它为准，不以模型抄的为准，
    引擎认数字、份量、估计用词都看它。before、after 到逗号、句号、换行为止（R13）。
    start 是 text 在折成半角的消息里的位置；prior 是再往前的那一个半句（没有为空）；
    ahead 是这条消息里 text 之前的全部文字（R3 找“前面最近提到的食物”用）。
    """

    message: Message
    before: str = ""
    after: str = ""
    text: str = ""
    start: int = 0
    prior: str = ""
    ahead: str = ""

    @property
    def clauses(self) -> str:
        """抄下来的这一段所在的那几个完整半句。"""
        return self.before + self.text + self.after


def inbox_path(data_dir: Path) -> Path:
    return data_dir / storage_io.HIDDEN / INBOX


def append(data_dir: Path, record: dict[str, Any]) -> None:
    """钩子入口用：往收件箱追加一行。调用方负责加锁。

    最后一行没写完（没有换行：写到一半断电、磁盘满）时先补一个换行，再写这一行：
    不然这句话接在那半行后面，两句并成一行，都读不出来，用户刚说的话就记不上。
    """
    path = inbox_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "a+b") as handle:
        size = handle.seek(0, 2)
        if size:
            handle.seek(size - 1)
            if handle.read(1) != b"\n":
                line = b"\n" + line
        handle.write(line)  # 追加模式：不管读到哪里，都写在文件末尾


def _parse(line: str, pos: int = 0) -> Message | None:
    try:
        record = json.loads(line)
        text = record["text"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(text, str):
        return None
    try:
        ts = datetime.fromisoformat(record["ts"])
    except (KeyError, TypeError, ValueError):
        ts = None
    session = record.get("session") if isinstance(record, dict) else None
    session = session if isinstance(session, str) else ""
    agent = record.get("agent")
    agent = agent if isinstance(agent, str) else ""
    return Message(ts if ts is None or ts.tzinfo else ts.astimezone(), text, pos, session, agent)


def _decoded(line: bytes) -> str | None:
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _lines(data_dir: Path) -> list[str | None] | None:
    """收件箱一行一条。只按换行符切：消息里的 U+2028、U+2029、U+0085 不是行尾。

    一行一行地解码：被外力写坏、不是合法 UTF-8 的那一行是 None，照样占一行（先后按行数认，
    R19），只是不算用户说过的话（它本来也抄不出来）；不连累别的行，写入不因此出内部错误。
    """
    try:
        lines = inbox_path(data_dir).read_bytes().split(b"\n")
    except FileNotFoundError:
        return None
    return [_decoded(line) for line in (lines[:-1] if lines[-1] == b"" else lines)]


def _messages(lines: list[str | None], offset: int = 0) -> list[Message]:
    found = (_parse(line, offset + n) for n, line in enumerate(lines) if line and line.strip())
    return [message for message in found if message is not None]


def recent(data_dir: Path) -> list[Message] | None:
    """收件箱里最近 50 条用户消息；收件箱不存在返回 None。"""
    lines = _lines(data_dir)
    return None if lines is None else _messages(lines)[-RECENT:]


def damaged(data_dir: Path) -> list[int]:
    """hl check 用：收件箱最近 50 条消息那一段里读不出来的行（不是合法的 UTF-8，或者不是引擎
    写的那种 JSON），行号从 1 数。它们被跳过了，用户在那几行说的话抄不到。更早的不管：
    反正已经抄不到了。"""
    lines = _lines(data_dir) or []
    messages = _messages(lines)
    start = messages[-RECENT].pos if len(messages) >= RECENT else 0
    return [
        n + 1
        for n, line in enumerate(lines[start:], start)
        if line is None or (line.strip() and _parse(line) is None)
    ]


def size(data_dir: Path) -> int:
    """收件箱现在有多少行。收件箱只追加，所以它能标出"此刻之前"和"此刻之后"。"""
    return len(_lines(data_dir) or [])


def since(data_dir: Path, position: int, session: str = "") -> list[Message]:
    """收件箱里第 position 行之后追加的用户消息，按先后排列。

    给了 session 的，只要这个对话里的（和没记会话的，见 together）：别的对话里的话不是在答
    这个对话里问的事（K-1）。"""
    found = _messages((_lines(data_dir) or [])[position:], position)
    return [message for message in found if together(message.session, session)]


def session_at(data_dir: Path, position: int) -> str:
    """收件箱第 position 行那条消息是在哪个对话里说的；没记、读不出来的是空。"""
    found = since(data_dir, position)[:1] if position >= 0 else []
    return found[0].session if found and found[0].pos == position else ""
