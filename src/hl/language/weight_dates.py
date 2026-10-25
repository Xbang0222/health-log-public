"""体重原话中的具体日期及其归属。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from hl.language.calendar_dates import _SAID_DAY, _said_date
from hl.language.normalize import clean, simplified
from hl.language.units import CLAUSE_END
from hl.language.weight_normalize import _blank, _without_asides
from hl.language.weight_read import _weight_marks
from hl.language.weight_types import WeightMention
from hl.language.weight_words import WEIGHT_WORDS, _just_marks

# 日子词和那个数中间只隔着这些（还有标点、空白、涂掉的钟点），这个数才是那天的（见 weight_days）：
# 说体重的词、一天里的时候，和“也、还、都、就”（“前天也是78.5”“昨天就78.5了”）
_TIMES_OF_DAY = (
    "早上", "早晨", "清晨", "一早", "上午", "中午", "晌午", "下午", "傍晚", "晚上",
    "夜里", "半夜", "深夜", "凌晨", "睡前",
)  # fmt: skip


_DAY_FILLER = re.compile(
    "|".join(sorted({*WEIGHT_WORDS, *_TIMES_OF_DAY, "也", "还", "都", "就"}, key=len, reverse=True))
)

# 说在数后面的日子词，和数中间、到这半句完都只能有说体重的词、一天里的时候（第十轮 W-2，规则 21）：
# “也、还、都、就”不算（“78.5，昨天也是”说的是昨天也是这个数），也不能隔着半句
_DAY_FILLER_AFTER = re.compile(
    "|".join(sorted({*WEIGHT_WORDS, *_TIMES_OF_DAY}, key=len, reverse=True))
)


@dataclass(frozen=True)
class SaidDay:
    """原话里说体重的那个数是哪天的：那个日子词（照原话）、它说的日子、在 clean(消息) 里的位置。"""

    word: str
    day: str  # YYYY-MM-DD
    span: tuple[int, int]
    # “今天、昨天、昨晚”这类从说话那天往前数的词：对得上要记的那天时算说体重的词（见 extra_words）
    relative: bool


def _filler(text: str, after: bool = False) -> bool:
    """只有说体重的词、一天里的时候、“也、还、都、就”、标点和空白（见 _DAY_FILLER）。
    after：日子词说在数后面的，“也、还、都、就”和半句完的标点不算（见 _DAY_FILLER_AFTER）。"""
    if after:
        kept = _DAY_FILLER_AFTER.sub(_blank, text)
        return all(_just_marks(ch) and ch not in CLAUSE_END for ch in kept)
    return all(_just_marks(ch) for ch in _DAY_FILLER.sub(_blank, text))


def weight_days(message: str, mention: WeightMention, base: date) -> list[SaidDay]:
    """R16：原话所在的整条消息里，这个数说的是哪天的体重（“昨天体重78.5”“78.5 是昨天的”）；
    base 是用户说这句话的那天。没说返回空列表。

    日子词（见 _SAID_DAY）和这个数中间只隔着说体重的词、一天里的时候、标点和空白（钟点涂成空白），
    才是这个数的：先看前面最近的那个（连着说的几个都算：“今天周四 78.5”），前面没有挨着的再看后面，
    说在后面的要在同一个半句里，和数中间、到这半句完都只能有说体重的词、一天里的时候、标点和空白
    （“78.5 是昨天的”；“78.5，昨天也是”不算，第十轮 W-2）。中间隔着别的话的
    （“比昨天轻了0.3，现在70.5”“昨天忘了记，体重78.5”），引擎不猜它是不是这个数的。
    这个数说了几遍的，每一处都挨着日子词才算；有一处没挨着，返回空列表。
    """
    seen = clean(message)
    text = simplified(seen)
    rest = _without_asides(text)
    hits = []
    for hit in _SAID_DAY.finditer(text):
        day = _said_date(hit, base)
        if day is not None:  # 认不出是哪天的日子词就是一段别的话，隔开前后
            word = seen[hit.start() : hit.end()]
            hits.append(SaidDay(word, day.isoformat(), hit.span(), bool(hit.group("relative"))))
    found = [m for m, height in _weight_marks(message, message) if not height and m == mention]
    said: list[SaidDay] = []
    for one in found:
        start, end = one.span
        before, cursor = [], start
        for hit in reversed([hit for hit in hits if hit.span[1] <= start]):
            if not _filler(rest[hit.span[1] : cursor]):
                break
            before.append(hit)
            cursor = hit.span[0]
        after, cursor = [], end
        for hit in [hit for hit in hits if hit.span[0] >= end]:
            if before or not _filler(rest[cursor : hit.span[0]], after=True):
                break
            after.append(hit)
            cursor = hit.span[1]
        stop = min((p for ch in CLAUSE_END if (p := rest.find(ch, cursor)) >= 0), default=len(rest))
        if after and not _filler(rest[cursor:stop], after=True):
            after = []
        if not before and not after:
            return []
        said += before + after
    return said
