"""写入事件及原话出处的保存、有效期和身份查询。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from hl.configuration import values as configuration_values
from hl.confirmation.queue import _load, _path, _put
from hl.confirmation.records import _count, _find, digest
from hl.confirmation.terms import RECORDED, Source
from hl.language import normalize as language_normalize
from hl.origins import inbox as origins_inbox
from hl.storage import io as storage_io


def done(
    data_dir: Path,
    kind: str,
    subject: Any,
    day: str,
    now: datetime,
    source: Source | None = None,
    entry_id: str = "",
    meal: str = "",
) -> None:
    """这句原话记成了 day 这一天的一餐（entry_id 那一条，记在 meal，出处是 source）。
    调用方负责加锁。

    提问的记录不销掉：同一天重试还按原来的提问位置算（好落到去重上）；
    撤掉之后换一天再拿这句原话来记，之前的回答不能再用，得重新问。
    出处另外记在 recorded.json 里，留给 R11：同一处原话再拿来记，换一餐、换一天都认得出来。
    它一条记录一条、只追加，不跟着提问的记录改写（同一句原话又问了一遍、又记了一条，
    更早那条记录的出处照样在）；那条消息落到收件箱最近 50 条之外，再也抄不到了，才清掉
    （写坏了的也清掉，见 _span）。
    """
    key = digest(kind, subject)
    items = _load(data_dir)
    item = _find(items, key) or {"digest": key, "kind": kind, "summary": "", "inbox": 0}
    item = {**item, "asked_at": item.get("asked_at", now.isoformat())}
    item.pop("retired", None)  # 追问撤掉了、后来没再问就记成了：记成了就不再挡回答（见 retired）
    item.update(done=origins_inbox.size(data_dir), date=day)
    _put(data_dir, items, item)
    if source is None:
        return
    note = source_note(kind, subject, day, source, entry_id, meal, origins_inbox.size(data_dir))
    write_notes(data_dir, [*live_notes(data_dir, notes(data_dir)), note])


def source_note(
    kind: str,
    subject: Any,
    day: str,
    source: Source,
    entry_id: str,
    meal: str = "",
    written: int | None = None,
) -> dict[str, Any]:
    """recorded.json 里的一条：这句原话（摘要）记成了 day 这一天 meal 的 entry_id，出处是 source。
    记着餐次，撤掉之后重记时好按原来那一餐（K-4）；早先记的没有。"""
    note = {"date": day, "id": entry_id, "said": digest(kind, subject), "source": list(source)}
    if written is not None:
        note["written"] = written  # K23：实际写入事件位置，不是那句原话曾经说过的位置
    return {**note, "meal": meal} if meal else note


def notes_from(data_dir: Path, pos: int) -> list[dict[str, Any]]:
    """收件箱第 pos 行那条消息里的原话记成过的各条（recorded.json 里的原样），最近记的在前。"""
    return [note for note in reversed(notes(data_dir)) if note["source"][0] == pos]


def notes(data_dir: Path) -> list[dict[str, Any]]:
    """recorded.json 里的各条，按记的先后；出处写坏了的不算（见 _span）。
    读不了（位置上是个目录）抛 OSError。"""
    return [note for note in _load(data_dir, RECORDED) if _span(note) is not None]


def live_notes(data_dir: Path, found: Any) -> list[dict[str, Any]]:
    """保留可用的出处；K23实际写入比原话晚时，写入前的删除原话仍可用就也保留事件。"""
    messages = origins_inbox.recent(data_dir) or []
    oldest = messages[0].pos if messages else 0
    if not isinstance(found, list):
        return []
    return [
        note
        for note in found
        if isinstance(note, dict)
        and (span := _span(note)) is not None
        and (span[0] >= oldest or (_count(note.get("written")) and note["written"] > oldest))
    ]


def write_notes(data_dir: Path, found: list[dict[str, Any]]) -> None:
    storage_io.write_text(
        _path(data_dir, RECORDED), json.dumps(found, ensure_ascii=False, indent=1)
    )


def _span(item: dict[str, Any]) -> Source | None:
    """recorded.json 里这一条的出处；出处或日期写坏了（日期不是 YYYY-MM-DD）的返回 None，不算它。"""
    old = item.get("source")
    if not isinstance(old, list) or len(old) != 3 or not all(isinstance(n, int) for n in old):
        return None
    if not configuration_values.is_date(str(item.get("date"))):
        return None
    return old[0], old[1], old[2]


def recorded_from(data_dir: Path, pos: int) -> list[tuple[str, str, str, Source]]:
    """收件箱第 pos 行那条消息里的原话记成过哪几条：（日期，id，原话的摘要，出处），最近记的在前。

    记录后来撤掉了的也在里面，调用方要去那一天的文件里核对它还在不在。
    """
    return recorded_between(data_dir, pos, pos + 1)


def recorded_between(data_dir: Path, first: int, last: int) -> list[tuple[str, str, str, Source]]:
    """收件箱第 first 行到第 last 行之前那几条消息里的原话记成过哪几条，同 recorded_from。"""
    found = []
    messages = origins_inbox.recent(data_dir) or []
    oldest = messages[0].pos if messages else 0
    for item in reversed(_load(data_dir, RECORDED)):
        old = _span(item)
        # 因较晚写入而保留的K23事件，不让已过期的原话重新参与R11去重。
        if old is not None and max(first, oldest) <= old[0] < last:
            found.append((str(item.get("date")), str(item.get("id")), str(item.get("said")), old))
    return found


def recorded_at(data_dir: Path, said: str) -> int | None:
    """这句原话记成一餐时收件箱的行数；没记成过（或者早就不记得了）返回 None。"""
    item = _find(_load(data_dir), digest("add", language_normalize.compact(said)))
    return int(item["done"]) if item and "done" in item else None


def entry_at(data_dir: Path, day: str, entry: Any) -> int | None:
    """day 这一天这条记录记成时收件箱的行数（见 done）；查不到的（手写的、早就不记得了的）返回
    None。调用方负责加锁。

    新出处保留实际写入位置written；旧出处没有时，同一句原话这一天记过几次的算最近那一次。
    只在旧recorded.json里查得到的，算它的原话那条消息的下一行（记成不会比它早）。
    给 hl undo 不给 --id 时用：原话说在当天最后一条记上之前的，
    说的不会是这一条（用户定的第 25 条，复核 C-4）。
    """
    if not isinstance(entry, dict):
        return None
    recorded = [
        note
        for note in reversed(_load(data_dir, RECORDED))
        if _span(note) is not None and (note.get("date"), note.get("id")) == (day, entry.get("id"))
    ]
    # 新记录按实际写入事件定位；不能因200条队列淘汰，退回同一句旧原话曾经说过的位置。
    if recorded and _count(recorded[0].get("written")):
        return int(recorded[0]["written"])
    said = entry.get("said")
    if isinstance(said, str):
        item = _find(_load(data_dir), digest("add", language_normalize.compact(said)))
        if item is not None and "done" in item and item.get("date") == day:
            return int(item["done"])
    return _span(recorded[0])[0] + 1 if recorded else None


# ---------- 用户不同意删旧记录（R11、R18） ----------
def undo_subject(day: str, entry: Any) -> dict[str, str]:
    """hl undo 请用户确认删 day 这一天的这条记录时，问的是什么：连同整条记录现在的样子（连同签名；
    手写的记录没有签名，只看签名认不出它被换成了别的）。问过之后它变了，确认不算数。
    hl add 也用它认出用户不同意删的是哪一条。"""
    text = yaml.safe_dump(entry, sort_keys=True, allow_unicode=True)
    entry_id = str(entry.get("id", "")) if isinstance(entry, dict) else ""
    return {"date": day, "id": entry_id, "entry": hashlib.sha1(text.encode()).hexdigest()}
