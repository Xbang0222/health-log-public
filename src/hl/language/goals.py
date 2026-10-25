"""计划目标数字与日类型的归属。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hl.language.normalize import _readings, fold, visible
from hl.language.units import _NUMBER
from hl.language.weight_normalize import without_times

# ---------- 计划里的数字（R17） ----------
GOAL_WORDS = {
    "热量": "kcal", "能量": "kcal",
    "蛋白质": "protein", "蛋白": "protein",
    "脂肪": "fat",
    "碳水化合物": "carb", "碳水": "carb",
    "膳食纤维": "fiber", "纤维": "fiber",
    "钠": "sodium",
}  # fmt: skip


_KCAL_UNITS = ("千卡", "大卡", "kcal", "卡路里", "卡")  # 紧跟在数字后面：前面那个数是热量


_GOAL_UNITS = (*_KCAL_UNITS, "克", "g", "毫克", "mg")


_GOAL_STOPS = ",。;!?\n、()"


_FOR_ALL = ("都", "各", "同样", "一样", "每种", "两种")  # 这半句说的是所有日子，不单指前面那种


@dataclass(frozen=True)
class Goal:
    """用户说的一个数：哪一项的（没带项目词为 None）、几种读法、说的是哪几种日子（没指明为空）。"""

    field: str | None
    values: frozenset[float]
    days: frozenset[str]


@dataclass
class _Mark:
    """计划原话里的一处：日子名称（day）、项目词（word）、数字（num）或热量单位（unit）。"""

    kind: str
    value: Any
    start: int
    end: int
    field: str | None = None  # 数字归到了哪一项
    days: frozenset[str] = frozenset()  # 数字说的是哪几种日子


def goals_in(text: str, names: list[str]) -> list[Goal]:
    """R17：这段话里的每个数是哪一项的、说的是哪种日子。只认分得清的，分不清就不绑。

    项目：数字后面紧跟千卡、大卡的是热量；项目词和数字挨着（“蛋白 150”“150 克蛋白”）就是那一项。
    日子：数字跟着同一个分句里它前面的日子名称走（名称都在数字后面时跟后面的）；
    分句里没有名称，就接着上一个分句说的那种日子。只有一种日子时，所有的数都是它的。
    看不见的字符先去掉（“2\u200b200 千卡”是 2200，第十轮 W-10）。
    """
    text = fold(visible(text))
    days = {fold(name): name for name in names}
    goals: list[Goal] = []
    carried: frozenset[str] = frozenset()
    for start, end, marks in _goal_segments(text, days):
        _bind_fields(text, marks)
        marks = [mark for mark in marks if mark.kind in ("day", "num")]
        for_all = any(word in text[start:end] for word in _FOR_ALL)
        carried = _bind_days(marks, frozenset() if for_all else carried) or carried
        for mark in marks:
            if mark.kind == "num":
                said_for = frozenset(names) if len(names) == 1 else mark.days
                goals.append(Goal(mark.field, frozenset(mark.value), said_for))
    return goals


def goal_numbers(
    text: str, names: list[str]
) -> list[tuple[frozenset[float], str | None, int, int]]:
    """R19：这段话里说到的每个数：（几种读法，哪一项的（没带项目词为 None），起，止），位置按 fold
    过的原话，项目和 goals_in 一样认；日期、钟点里的数不算（见 without_times）。用户否定计划时，
    逐个看是不是他新说的、是不是在说不要它（用户定的第 23 条）。"""
    text = without_times(fold(text))
    days = {fold(name): name for name in names}
    found = []
    for _, _, marks in _goal_segments(text, days):
        _bind_fields(text, marks)
        found += [(frozenset(m.value), m.field, m.start, m.end) for m in marks if m.kind == "num"]
    return found


def _goal_segments(text: str, days: dict[str, str]) -> list[tuple[int, int, list[_Mark]]]:
    """按标点切成分句，找出每个分句里的日子名称、项目词、数字、热量单位。"""
    kinds = {
        "day": sorted(map(re.escape, days), key=len, reverse=True),
        "unit": list(_KCAL_UNITS),
        "word": sorted(GOAL_WORDS, key=len, reverse=True),
        "num": [_NUMBER],
        "stop": [f"[{re.escape(_GOAL_STOPS)}]"],
    }
    pattern = "|".join(f"(?P<{kind}>{'|'.join(words)})" for kind, words in kinds.items() if words)
    segments: list[tuple[int, int, list[_Mark]]] = []
    start, marks = 0, []
    for match in re.finditer(pattern, text):
        kind, word = match.lastgroup, match.group()
        if kind == "stop":
            segments.append((start, match.start(), marks))
            start, marks = match.end(), []
            continue
        value: Any = {"day": days.get(word), "word": GOAL_WORDS.get(word)}.get(kind)
        if kind == "num":
            value = _readings(text, word, match.end())
            small = word[0] not in "0123456789" and all(v < 10 and v.is_integer() for v in value)
            if not value or (small and not text[match.end() :].lstrip().startswith(_GOAL_UNITS)):
                kind = "aside"  # “一共”“每周三天”里的个位中文数字：留着，但不和项目词配对
        marks.append(_Mark(kind, value, match.start(), match.end()))
    return [*segments, (start, len(text), marks)]


def _bind_fields(text: str, marks: list[_Mark]) -> None:
    """数字归到哪一项：先认紧跟着的热量单位，再认挨着的项目词。"""
    for unit, number in zip(marks[1:], marks, strict=False):
        if (unit.kind, number.kind) == ("unit", "num") and not text[
            number.end : unit.start
        ].strip():
            number.field = "kcal"
    marks = [mark for mark in marks if mark.kind in ("day", "word", "num")]

    def pairs(step: int) -> list[tuple[_Mark, str]]:
        found = []
        for pos, mark in enumerate(marks):
            sides = marks[max(pos - 1, 0) : pos] + marks[pos + 1 : pos + 2]
            if mark.kind != "word" or any(side.kind == "word" for side in sides):
                continue  # 几个项目词连在一起（“蛋白脂肪碳水分别是……”）：分不清，不绑
            number = marks[pos + step] if 0 <= pos + step < len(marks) else None
            if number is not None and number.kind == "num" and number.field is None:
                found.append((number, mark.value))
        return found

    after, before = pairs(1), pairs(-1)  # “蛋白 150”和“150 克蛋白”两种说法，取配得多的
    for number, field in before if len(before) > len(after) else after:
        number.field = field


def _bind_days(marks: list[_Mark], carried: frozenset[str]) -> frozenset[str]:
    """数字说的是哪种日子；返回这个分句最后说到的日子（分句里没有名称时为空）。"""
    groups: list[set[str]] = []  # 连着点到的几种日子算一组
    latest = []  # 每一处之前最近的一组是第几组
    for pos, mark in enumerate(marks):
        if mark.kind == "day" and pos and marks[pos - 1].kind == "day":
            groups[-1].add(mark.value)
        elif mark.kind == "day":
            groups.append({mark.value})
        latest.append(len(groups) - 1)
    for mark, group in zip(marks, latest, strict=True):
        if mark.kind != "num":
            continue
        if not groups:
            mark.days = carried
        elif marks[0].kind == "day":
            mark.days = frozenset(groups[group])
        elif marks[-1].kind == "day":
            mark.days = frozenset(groups[group + 1])
        else:  # 名称夹在数字中间，分不清前后：这个分句里点到的日子都算
            mark.days = frozenset().union(*groups)
    return frozenset(groups[-1]) if groups else frozenset()
