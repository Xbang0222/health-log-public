"""记过的原话出自哪里（.hl/recorded.json，R11）在清单里的那一份：文件丢了、对不上时照它补回（K-3）。

recorded.json 没有签名，也不进 git：它丢了、被清空、读不出来、换回了旧的一份，引擎就认不出
同一条消息里的话已经记过，同一处原话会再记一份，hl check 也看不出来。所以每记一条，出处先连同
那一天的记录一起记进清单（签了名，见 manifest.save_day），再写 recorded.json。

改清单的写命令进来时（manifest._editing）、hl add 和 hl undo 用到出处之前、hl check，都拿清单里
的这一份对一下：文件里没有的，照原样补回去。补的是引擎自己记下的、原样的东西，不用问用户。
文件里有、清单里没有的不删：多一条出处只会让引擎多问一次，不会记错。

清单里还没有这一份的（这次改动之前建的清单）：改清单时按那时文件里有的认下。在那之前就丢了的、
清单和 recorded.json 一起丢了的，补不回来（收件箱也一起丢了的不要紧：那些话再也抄不到了）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl import pending

FIELD = "recorded"  # 清单里放这一份的键


def _same(note: dict[str, Any]) -> str:
    return json.dumps(note, ensure_ascii=False, sort_keys=True)


def _file(data_dir: Path) -> list[dict[str, Any]] | None:
    """recorded.json 里现在有的；读不了（位置上是个目录、没有权限）返回 None，由 hl check 去报。"""
    try:
        return pending.notes(data_dir)
    except OSError:
        return None


def missing(data_dir: Path, body: dict[str, Any]) -> list[dict[str, Any]]:
    """清单 body 里记着、recorded.json 里没有的出处（那条消息已经抄不到了的不算）。"""
    have = _file(data_dir)
    if have is None:
        return []
    held = {_same(note) for note in have}
    kept = pending.live_notes(data_dir, body.get(FIELD, []))
    return [note for note in kept if _same(note) not in held]


def restore(data_dir: Path, body: dict[str, Any]) -> int:
    """把清单 body 里记着、recorded.json 里没有的出处补回文件，返回补了几条。调用方负责加锁。

    补回后的先后照清单里的；文件里另有、清单里没有的接在后面。"""
    lost = missing(data_dir, body)
    if not lost:
        return 0
    kept = pending.live_notes(data_dir, body.get(FIELD, []))
    listed = {_same(note) for note in kept}
    extra = [note for note in _file(data_dir) or [] if _same(note) not in listed]
    try:
        pending.write_notes(data_dir, [*kept, *extra])
    except OSError:
        return 0
    return len(lost)


def adopt(data_dir: Path, body: dict[str, Any]) -> None:
    """清单还没记这一份时，按 recorded.json 里现在有的记上；读不了先不记，下次写清单时再说。"""
    if FIELD not in body:
        have = _file(data_dir)
        if have is not None:
            body[FIELD] = pending.live_notes(data_dir, have)


def add(data_dir: Path, body: dict[str, Any], note: dict[str, Any]) -> None:
    """清单里记上这一条出处（写 recorded.json 之前）；那条消息已经抄不到了的旧出处顺手清掉。"""
    adopt(data_dir, body)
    body[FIELD] = [*pending.live_notes(data_dir, body.get(FIELD, [])), note]


def merged(data_dir: Path, old: dict[str, Any] | None) -> list[dict[str, Any]]:
    """重建清单时记的这一份：原来的清单里记着的，加上 recorded.json 里另有的。"""
    kept = pending.live_notes(data_dir, old.get(FIELD, [])) if old is not None else []
    listed = {_same(note) for note in kept}
    have = pending.live_notes(data_dir, _file(data_dir) or [])
    return [*kept, *(note for note in have if _same(note) not in listed)]
