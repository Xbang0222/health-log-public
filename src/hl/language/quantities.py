"""完整份量的提取、组合、负值与复合约数边界。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from hl.language.quantity_tokens import (
    _IN_WORDS,
    _NOT_A_COUNT,
    _NOT_FOOD_AFTER,
    _PEOPLE_BEFORE,
    _QTY_CHARS,
    _QTY_LIANG,
    _QTY_LIANG_ALONE,
    _QTY_LINK,
    _QTY_START,
    _QTY_TERM,
    _ROUGH_FILLERS,
    Quantity,
    _bare_word,
    _Count,
    _counts_at,
    _qty_value,
    _unit_of,
    _unit_word,
)
from hl.language.units import _UNIT_SYNONYMS, COUNTERS, GRAMS, MILLILITRES


def _counted(text: str, start: int, count: _Count, unit_word: re.Pattern[str]) -> Quantity | None:
    """数后面接上单位，成为一处份量；接不上、说的不是份量就是 None。"""
    if text.startswith("几", count.end):  # 其他未识别的含“几”写法不能截成一个确定数
        return None
    found = unit_word.match(text, count.end)
    if found is None:
        return None
    word = found["unit"] or found["filled"]
    if text.startswith(_IN_WORDS, found.end() - len(word)):
        return None
    unit = _unit_of(word)
    if count.needs_counter and unit == "两":
        return None
    n, readings, end, parts = count.n, count.readings, found.end(), ()
    rough = count.rough or _rough_filler(found["filler"])
    if unit == "斤" and count.whole:
        liang = _QTY_LIANG.match(text, end) or _QTY_LIANG_ALONE.match(text, end)
        if liang:
            m = _qty_value(liang["m"])
            n = count.n + m / 10 + (0.05 if liang.re is _QTY_LIANG and liang["half"] else 0)
            readings, end, parts = (n,), liang.end(), ((count.n, "斤"), (m, "两"))
    half = count.whole and not parts and text.startswith("半", end)
    if half and not unit_word.match(text, end + 1):  # “一碗半”是 1.5 碗；“一个半个”不算
        n, readings, end, parts = n + 0.5, (n + 0.5,), end + 1, ((n, unit),)
    if text.startswith("多", end):  # “一斤多”“一碗多”
        rough, end = True, end + 1
    if _NOT_FOOD_AFTER.match(text, end):
        return None
    return Quantity(n, unit, start, end, rough, readings, parts)


def _rough_filler(filler: str | None) -> bool:
    return bool(filler) and filler in _ROUGH_FILLERS


def _pair_at(text: str, pos: int, unit_word: re.Pattern[str]) -> Quantity | None:
    """俩 = 2 个，仨 = 3 个；后面带着量词的（“俩碗”）按那个量词。"""
    n = 2 if text[pos] == "俩" else 3
    found = unit_word.match(text, pos + 1)
    word = found and (found["unit"] or found["filled"])
    if found and word and not text.startswith(_IN_WORDS, found.end() - len(word)):
        unit, end = _unit_of(word), found.end()
    else:
        unit, end = "个", pos + 1
    if _NOT_FOOD_AFTER.match(text, end):
        return None
    return Quantity(n, unit, pos, end, readings=(n,))


def _quantity_at(text: str, pos: int, unit_word: re.Pattern[str]) -> Quantity | None:
    before = text[pos - 1 : pos]
    if text[:pos].rstrip().endswith(("-", "−", "负")):
        return None  # 负数不能丢掉符号后记成正份量。
    if before and (before.isdigit() or before in f".点{_QTY_CHARS}两{_NOT_A_COUNT}"):
        return None  # 数的中间，或者序数、每个、不确定的数
    if text[pos] in "俩仨":
        return None if before and before in _PEOPLE_BEFORE else _pair_at(text, pos, unit_word)
    if text[pos] == "半" and before and before in "大小多":
        return None  # 大半碗、小半碗：说不准是多少
    for count in _counts_at(text, pos):
        if found := _counted(text, pos, count, unit_word):
            return found
    return None


def _unclear_open_spans(text: str, unit_word: re.Pattern[str]) -> list[tuple[int, int]]:
    """含“十几”的复合范围/备选不是单一有界约数，不可只读取其中一端。"""
    spans = []
    for first in _QTY_TERM.finditer(text):
        end, count = first.end(), 1
        opened = "几" in first.group()
        while True:
            unit = unit_word.match(text, end)
            stop = unit.end() if unit else end
            link = _QTY_LINK.match(text, stop)
            following = _QTY_TERM.match(text, link.end()) if link else None
            if following is None:
                end = stop
                break
            count += 1
            opened = opened or "几" in following.group()
            end = following.end()
        if opened and count > 1:
            spans.append((first.start(), end))
    return spans


def quantities(text: str, units: Iterable[str] = ()) -> list[Quantity]:
    """一段话里的每一处份量，按在原话里的先后排（增补第 4、6 节）。

    text 是 clean 过的原话，位置照它算。units 是这样食物自己的量词，通用单位和通用量词表之外的
    也认。十几到九十几取范围中间值；无界数（几片、几十克、大半碗）、序数（第二碗）、说人和时间的（一个人、
    一个半小时）不是份量；“一些、一点”没有量词，也不是。
    """
    known = {*_UNIT_SYNONYMS.values(), *COUNTERS}
    extra = tuple(sorted({unit for unit in units if unit not in known}))
    unit_word = _unit_word(extra)
    unclear = _unclear_open_spans(text, unit_word)
    found: list[Quantity] = []
    pos = 0
    while start := _QTY_START.search(text, pos):
        quantity = _quantity_at(text, start.start(), unit_word)
        if quantity:
            found.append(quantity)
        pos = quantity.end if quantity else start.start() + 1
    found += _bare_counters(text, extra, found)
    return sorted(
        (q for q in found if not any(q.start < end and start < q.end for start, end in unclear)),
        key=lambda quantity: quantity.start,
    )


def _bare_counters(text: str, extra: tuple[str, ...], taken: list[Quantity]) -> list[Quantity]:
    """前面没有数字的量词，记 1（“吃了个苹果”）；前面是数字、“几、第、每”的不算。"""
    found = []
    for bare in _bare_word(extra).finditer(text):
        before = text[bare.start() - 1 : bare.start()]
        if any(q.start <= bare.start() < q.end for q in taken) or (
            before and (before.isdigit() or before in f"{_QTY_CHARS}两半俩仨{_NOT_A_COUNT}")
        ):
            continue
        if text.startswith(_IN_WORDS, bare.start("unit")):
            continue
        if _NOT_FOOD_AFTER.match(text, bare.end()):
            continue
        rough = _rough_filler(bare["filler"])
        found.append(Quantity(1, bare["unit"], bare.start(), bare.end(), rough, (1,), bare=True))
    return found


def said_amounts(text: str, n: float, unit: str) -> list[Quantity]:
    """文本里能读成 (n, unit) 的每一处份量（约数的哪一头都算）。"""
    return [
        quantity
        for quantity in quantities(text, [unit])
        if quantity.unit == unit and any(abs(value - n) < 1e-9 for value in quantity.readings)
    ]


def amount_spans(text: str, n: float, unit: str) -> list[tuple[int, int]]:
    """找出文本里"数字 + 单位"正好是 (n, unit) 的位置。"""
    return [(quantity.start, quantity.end) for quantity in said_amounts(text, n, unit)]


def with_generic_units(units: Iterable[str]) -> list[str]:
    """能按克记的，斤、两、公斤也能记；能按毫升记的，升也能记（增补第 6 节）。"""
    result = list(units)
    if "g" in result:
        result += [unit for unit in GRAMS if unit not in result]
    if "ml" in result:
        result += [unit for unit in MILLILITRES if unit not in result]
    return result


def has_amount(text: str, units: Iterable[str]) -> bool:
    """文本里有没有明说了数字（或“半”）的份量，单位是 units 里的任何一个。"""
    wanted = with_generic_units(units)
    return any(not q.bare and q.unit in wanted for q in quantities(text, wanted))
