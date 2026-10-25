"""重说与保留事项的持久状态及查询。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from hl.configuration import values as configuration_values
from hl.confirmation.queue import _load, _put
from hl.confirmation.records import _count, _find, digest
from hl.confirmation.terms import Source
from hl.language import units as language_units


class Resaid(NamedTuple):
    """记下的一次重说（R11）。"""

    said_at: int  # 用户说“不是”的那句话在收件箱第几行
    targets: list[dict[str, str]]  # 要一条一条撤掉的那几条，各是 undo_subject
    labels: list[str]  # 那几条在回话里怎么说（“2026-10-08 的记录 e1（晚餐：……）”），一一对应
    meals: list[tuple[str, str]]  # 请他重说的是哪一天的哪一餐；空的（旧版本记的）是哪一餐都算
    message: int | None  # 被否定的那段原话出自收件箱第几行；旧版本记的没有
    # 请他重说时收件箱有几行：他接着说的第一句（这一行）是他新说的那句。
    # 拿他的否定回答当新说的那句、没请他重说的，旧版本记的，都没有
    asked: int | None = None
    word: str = ""  # 请他重说时那几餐怎么说（“昨天晚上”“早上和中午”）
    # 单独再说那一餐时（add._left_alone）：那一餐原来出自的那条消息（最早被否定的那条）。
    # 别的一餐记着的东西，那条消息里记的、它那几次重说记的也算（add._resaid_other）
    origin: int | None = None
    replacement: tuple[str, str] | None = None  # K12：用户明确改成的新餐；撤销目标仍是旧餐
    replacement_at: int | None = None  # 提供该完整替换句的消息位置


def resay(
    data_dir: Path,
    said_at: int,
    targets: list[dict[str, str]],
    now: datetime,
    labels: list[str],
    meals: list[tuple[str, str]],
    message: int,
    asked: tuple[int | None, str] = (None, ""),
    origin: int | None = None,
    replacement: tuple[str, str] | None = None,
) -> None:
    """R11：用户说了不是另外又吃的（那句话在收件箱第 said_at 行），fix 请他把这一餐重说一遍、
    一条一条撤掉 targets（各是 undo_subject，labels 是它们在回话里怎么说）、再用他新说的那句记。
    记下来，hl add 好认出：撤的时候用户说了不删，他新说的那句不记（resaid）。
    meals 是请他重说的那几餐（各是日期和餐次）：不记的只是这几餐的重说，别的餐照常记。
    message 是被否定的那段原话出自收件箱第几行：他重说时顺带说到的别的餐，那条消息里记过的
    还在，就不记（add._resaid_other）。要撤的一条都没有，也记下来。
    asked 是（请他重说时收件箱有几行，那几餐怎么说）：他接着说的第一句没说餐次，
    只请他重说了一餐的就是那一餐（add._answer_pieces）；拿他的回答当新说的那句的，第一项是 None。
    origin：他是单独再说那一餐（add._left_alone），那一餐原来出自的那条消息在收件箱第几行。
    replacement：K12完整否定回复指定的新餐；目标记录和meals仍指旧餐，另存回复位置防止先记后删。

    同一句“不是”又记一次（模型重交了被否定的那一段，已经撤掉的那几条不在这次的 targets 里），
    并上先前记下的：撤到一半说不删时，要照实说哪几条已经删了。调用方负责加锁。
    """
    key = digest("resay", said_at)
    items = _load(data_dir)
    old = next((note for note in resaid(data_dir) if note.said_at == said_at), None)
    pairs = list(zip(old.targets, old.labels, strict=True)) if old else []
    pairs += [
        (target, label)
        for target, label in zip(targets, labels, strict=True)
        if all(target != other for other, _ in pairs)
    ]
    note = {"digest": key, "kind": "resay", "summary": "", "asked_at": now.isoformat()}
    note.update(inbox=said_at, targets=[t for t, _ in pairs], labels=[label for _, label in pairs])
    said = [list(meal) for meal in old.meals] if old else []
    note["meals"] = said + [list(meal) for meal in meals if list(meal) not in said]
    note["message"] = message
    origin = old.origin if old and old.origin is not None else origin
    if origin is not None:
        note["origin"] = origin
    replacement = old.replacement if old and old.replacement else replacement
    if replacement is not None:
        note["replacement"] = list(replacement)
        note["replacement_at"] = old.replacement_at if old and old.replacement else said_at
    at = old.asked if old and old.asked is not None else asked[0]  # 头一次请他重说时的
    if at is not None:
        note.update(asked=at, word=old.word if old and old.asked is not None else asked[1])
    _put(data_dir, items, note)


def resaid(data_dir: Path) -> list[Resaid]:
    """记下的那几次重说。写坏了的不算；没记说法的（旧版本记的）按日期和 id 说。"""
    found = []
    for item in _load(data_dir):
        targets = item.get("targets")
        if item.get("kind") != "resay" or not isinstance(targets, list):
            continue
        labels = item.get("labels")
        if not isinstance(labels, list) or len(labels) != len(targets):
            labels = [None] * len(targets)
        sound = [
            (target, label if isinstance(label, str) else f"{target['date']} 的记录 {target['id']}")
            for target, label in zip(targets, labels, strict=True)
            if isinstance(target, dict)
            and configuration_values.is_date(str(target.get("date")))
            and all(isinstance(target.get(name), str) for name in ("id", "entry"))
        ]
        targets, labels = [t for t, _ in sound], [label for _, label in sound]
        meals = [
            (str(meal[0]), str(meal[1]))
            for meal in item.get("meals") or []
            if isinstance(meal, list) and len(meal) == 2
        ]
        message = item.get("message")
        message = message if _count(message) else None
        asked = item.get("asked") if _count(item.get("asked")) else None
        word = item.get("word") if isinstance(item.get("word"), str) else ""
        origin = item.get("origin") if _count(item.get("origin")) else None
        moved = item.get("replacement")
        replacement = (
            (str(moved[0]), str(moved[1]))
            if (
                isinstance(moved, list)
                and len(moved) == 2
                and configuration_values.is_date(str(moved[0]))
                and moved[1] in language_units.MEALS
            )
            else None
        )
        found.append(
            Resaid(
                int(item["inbox"]),
                targets,
                labels,
                meals,
                message,
                asked,
                word,
                origin,
                replacement,
                item["replacement_at"] if _count(item.get("replacement_at")) else None,
            )
        )
    return found


def move_resay(data_dir: Path, said_at: int, meal: tuple[str, str], spoken: int) -> None:
    """K12：核对完整重说后，只更新替换餐，不改待撤旧记录。调用方负责加锁。"""
    items = _load(data_dir)
    item = _find(items, digest("resay", said_at))
    if item is not None:
        _put(data_dir, items, {**item, "replacement": list(meal), "replacement_at": spoken})


class Kept(NamedTuple):
    """R11：引擎告诉过用户这一餐这次没有改、要改就单独再说（重说时顺带说了别的一餐）。"""

    said_at: int  # 告诉用户时说到了收件箱第几行：比它晚的消息才算他单独再说
    targets: list[dict[str, str]]  # 那一餐当时还留着的那几条，各是 undo_subject
    sources: list[Source]  # 那几条的出处，一一对应
    meal: tuple[str, str]  # 哪一天的哪一餐
    # 那几条是请用户重说哪条消息时留着的（被否定的那条消息）；旧版本记的没有
    message: int | None = None


def keep(
    data_dir: Path,
    said_at: int,
    targets: list[dict[str, str]],
    sources: list[Source],
    meal: tuple[str, str],
    now: datetime,
    message: int | None = None,
) -> None:
    """R11（第九轮 D-1）：引擎告诉用户 meal 这一餐（日期和餐次）这次没有改、要改就单独再说，
    那一餐还留着 targets 那几条（各是 undo_subject，sources 是它们的出处）。记下来：
    他之后（收件箱第 said_at 行之后）的话要记到同一天同一餐、那几条还在时，hl add 不直接记，
    先问是不是另外又吃的（add._left_alone）；不是，照重说的流程撤掉旧的再记。
    message 是请他重说哪条消息时说的这句（被否定的那条消息在收件箱第几行）：他单独再说时，
    那条消息和它那几次重说记下的别的餐也算这一天别的餐记着的（第十轮 A-2）。

    同一餐又记一次，并上先前记下的，从先前那一行算起。调用方负责加锁。
    """
    key = digest("kept", list(meal))
    old = next((note for note in kept(data_dir) if note.meal == meal), None)
    pairs = list(zip(old.targets, old.sources, strict=True)) if old else []
    pairs += [
        (target, source)
        for target, source in zip(targets, sources, strict=True)
        if all(target != other for other, _ in pairs)
    ]
    note = {"digest": key, "kind": "kept", "summary": "", "asked_at": now.isoformat()}
    note.update(inbox=min(said_at, old.said_at) if old else said_at, meal=list(meal))
    note.update(targets=[t for t, _ in pairs], sources=[list(s) for _, s in pairs])
    message = old.message if old and old.message is not None else message
    if message is not None:
        note["message"] = message
    _put(data_dir, _load(data_dir), note)


def kept(data_dir: Path) -> list[Kept]:
    """记下的那几餐（keep）。写坏了的不算。"""
    found = []
    for item in _load(data_dir):
        targets, sources, meal = item.get("targets"), item.get("sources"), item.get("meal")
        if item.get("kind") != "kept" or not isinstance(targets, list):
            continue
        if not isinstance(sources, list) or len(sources) != len(targets):
            continue
        if (
            not isinstance(meal, list)
            or len(meal) != 2
            or not configuration_values.is_date(str(meal[0]))
        ):
            continue
        sound = [
            (target, (source[0], source[1], source[2]))
            for target, source in zip(targets, sources, strict=True)
            if isinstance(target, dict)
            and configuration_values.is_date(str(target.get("date")))
            and all(isinstance(target.get(name), str) for name in ("id", "entry"))
            and isinstance(source, list)
            and len(source) == 3
            and all(_count(n) for n in source)
        ]
        found.append(
            Kept(
                int(item["inbox"]),
                [t for t, _ in sound],
                [s for _, s in sound],
                (str(meal[0]), str(meal[1])),
                item["message"] if _count(item.get("message")) else None,
            )
        )
    return found
