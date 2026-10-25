"""餐次分句、未来意图与重说范围。"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime

from hl.language.meal_marks import _meal_marks, _MealMark
from hl.language.normalize import number_value
from hl.language.phrases import (
    _AGAIN,
    _ALONE,
    _ATE_AT,
    _DAY_WORDS,
    _EATEN,
    _FUTURE,
    _GROUPS,
    _HALF_END,
    _INSTEAD,
    _INSTEAD_OF,
    _INTEND,
    _JOINED,
    _MISSED,
    _SKIP_AFTER,
    _SKIP_HOW,
    _SKIPPED,
    MEAL_WORDS,
    SAID_DAYS,
)
from hl.language.units import CLAUSE_END

# ---------- 餐次 ----------
_CLAUSE = re.compile(rf"[^{CLAUSE_END}]+")


@dataclass(frozen=True)
class MealPiece:
    """一段话里说同一餐的一截：起止位置、餐次、依据的词和那个词的位置。

    自己没带餐次词的一截顺延前面的：at 在 start 之前；前面也没有时 meal 为空。
    前面说的是没吃那一餐的（“早饭没吃，吃了一碗米饭”“没吃早饭吃了一碗米饭”），不顺延它：
    meal 为空，missed 是说没吃的那一截（第十轮 D-4）。
    """

    start: int
    end: int
    meal: str | None = None
    word: str = ""
    at: int = -1
    ago: int = 0  # 说的是几天前的这一餐（“昨天晚上”“昨晚”是 1，“前天中午”是 2）
    dated: bool = False  # 原话明说了是哪天（“今天早上”“今早”“昨天晚上”），没说的按今天
    missed: MealPiece | None = None  # 跟在说没吃那一餐的后面、自己没说餐次的：没吃的那一截

    @property
    def spoken(self) -> str:
        """用户怎么说的这一餐，连同是哪天（“昨天晚上”“昨晚”“早上”）。"""
        if self.word in _DAY_WORDS or not self.ago:
            return self.word
        day = SAID_DAYS[self.ago] if 0 <= self.ago < len(SAID_DAYS) else f"{self.ago}天前"
        return day + self.word


def planned(text: str) -> bool:
    """这一段说的是不是还没吃、打算以后吃的（“明天早上打算吃一个苹果”“晚上准备吃两个鸡蛋”）。
    说了“吃了、吃过、吃完、点了、才吃的”的不算（“想吃就吃了一个”）；“本来想吃”说的是没吃成，
    “不想吃”“很想吃”说的是想不想，也不算。"""
    return bool(_FUTURE.search(text) or _INTEND.search(text)) and not _EATEN.search(text)


def _later(clause: str, after: str) -> tuple[bool, int]:
    """一个半句说的是不是打算以后吃、还没吃的（R3 不逼模型列它里面的食物），
    和它里面从哪里起的餐次词不算一餐（在这之前的还是在说这一餐）。after 是下一个半句。

    “明天早上打算吃”“晚上准备吃两个鸡蛋”整句的餐次词都不算。拿不准的照原话认餐次，
    宁可多认一处，也不把吃了的东西记到别的餐、当成没吃：“早上明天要体检”里“明天”后面
    没说吃喝，“早上”还是这一餐；想吃、打算吃的后面接着说了吃了，那半句的餐次词是这一餐
    （“早上不想吃饭，就喝了一杯牛奶”“晚上想吃火锅没去成，吃了一碗米饭”），想吃的那样
    说了没吃成的才算没吃，没说的（“中午很想吃米饭，就吃了一碗”）是吃了。
    """
    if not planned(clause):
        return False, len(clause)
    future = _FUTURE.search(clause)
    if future:
        return True, 0 if re.search("[吃喝]", clause[future.end() :]) else future.start()
    if not _EATEN.search(after):
        return True, 0
    return bool(re.search(_MISSED, clause) or _INSTEAD.match(after)), len(clause)


def later_clauses(text: str) -> list[tuple[int, int]]:
    """说的是打算以后吃、还没吃的那几个半句的起止（R3 不逼模型列它们里的食物）。"""
    clauses = list(_CLAUSE.finditer(text))
    return [
        (clause.start(), clause.end())
        for n, clause in enumerate(clauses)
        if _later(clause.group(), clauses[n + 1].group() if n + 1 < len(clauses) else "")[0]
    ]


def _clauses(text: str) -> list[tuple[int, int]]:
    """认餐次用的半句的起止：到标点、换行为止，汉字后面的空格也断开（语音输入的停顿，R2）。"""
    edges = [0, *(n for found in _HALF_END.finditer(text) for n in found.span()), len(text)]
    return [(start, end) for start, end in zip(edges[::2], edges[1::2], strict=True) if start < end]


def _halves(text: str) -> list[list[tuple[int, int]]]:
    """认餐次用的半句（见 _clauses），每个是几段的起止：只说了哪天、哪个时候的半句
    （“昨晚”“昨天”“昨天晚上”，见 _ALONE）和后面隔着空格、逗号的那半句连起来认，
    中间的空格、逗号不算（“昨晚 宵夜吃了一碗米饭”同“昨晚宵夜……”，第十轮 D-3）。"""
    halves: list[list[tuple[int, int]]] = []
    for start, end in _clauses(text):
        if halves:
            head, tail = halves[-1][-1]
            if _ALONE.fullmatch(text[head:tail]) and _JOINED.fullmatch(text[tail:start]):
                halves[-1].append((start, end))
                continue
        halves.append([(start, end)])
    return halves


def _place(spans: list[tuple[int, int]], at: int) -> int:
    """连起来认的半句（spans 几段连在一起）里的第 at 个字在原文里的位置。"""
    for start, end in spans:
        if at < end - start:
            return start + at
        at -= end - start
    return spans[-1][1] + at


def meal_pieces(text: str) -> list[MealPiece]:
    """把一段话按“说的是哪一餐”切成几截。

    一个半句（到标点为止，汉字后面的空格也算停顿；只说了哪天、哪个时候的和后面那半句连着，
    见 _halves）里只有一处餐次词时整句都算它的
    （“吃了两个鸡蛋当早饭”）；不止一处时从第二处起另起一截（“早上吃了鸡蛋中午吃了米饭”）。
    没带餐次词的半句顺延前一截的。“昨天晚上剩的”“早上买的”说的不是这一餐，不算；
    “昨天晚上吃了一碗米饭”是昨天的晚餐（ago 是 1）。说的是打算以后吃的半句（“明天早上打算吃”）
    不是一餐，里面的餐次词不算（哪些还算见 _later）。说的是没吃那一餐的（“早饭没吃”“没吃早饭”，
    见 _skip_end），后面没带餐次词的不顺延它，记下 missed（第十轮 D-4）。
    """
    pieces: list[MealPiece] = []
    last = MealPiece(0, 0)  # 后面没带餐次词的半句顺延它
    halves = _halves(text)
    said = ["".join(text[start:end] for start, end in spans) for spans in halves]
    for n, spans in enumerate(halves):
        _, cut = _later(said[n], said[n + 1] if n + 1 < len(said) else "")
        clause = said[n][:cut]
        marks = _meal_marks(clause)
        cuts = [_place(spans, mark[5]) for mark in marks[1:]]
        edges = [spans[0][0], *cuts, spans[-1][1]]
        for k, (start, end) in enumerate(zip(edges, edges[1:], strict=False)):
            if not marks:
                pieces.append(dataclasses.replace(last, start=start, end=end))
                continue
            pos, meal, word, ago, dated, _ = marks[k]
            last = MealPiece(start, end, meal, word, _place(spans, pos), ago, dated)
            skip = _skip_end(clause, marks[k][:5])
            if skip is None:
                pieces.append(last)
                continue
            # 说没吃这一餐的话到这里为止：后面的、后面没带餐次词的半句都不顺延它（第十轮 D-4）
            stop = min(_place(spans, skip), end)
            pieces.append(dataclasses.replace(last, end=stop))
            last = MealPiece(stop, end, missed=pieces[-1])
            if stop < end:
                pieces.append(last)
    return pieces


def _skip_end(clause: str, mark: _MealMark) -> int | None:
    """半句里的这一处餐次词说的是不是没吃这一餐（“没吃早饭”“早饭没吃”“早上什么都没吃”，
    见 _SKIPPED、_SKIP_AFTER）：是的话，说没吃的话在半句里到哪为止；不是返回 None。"""
    pos, _, word, _, _ = mark
    end = pos + len(word)
    before = _SKIPPED.search(clause[:pos])
    if before:  # “早饭没吃中午……”“早饭什么都没吃中午……”的“没吃”说的是前面的早饭，
        # “早上没吃早饭”的说的是后面的早饭（时间词不会是“没吃”的东西）
        lead = re.sub(f"{_SKIP_HOW}$", "", clause[: before.start()])
        if _GROUPS[0].fullmatch(word) or not lead.endswith(tuple(MEAL_WORDS)):
            return end
    found = _SKIP_AFTER.match(clause, end)
    return found.end() if found else None


def instead(text: str) -> bool:
    """说没吃那一餐之后的这一截，是不是接着说“就、只、随便……”吃了什么（“就喝了一杯牛奶”）：
    可能是拿它当了那一餐，拿不准是哪一餐（第十轮 D-4）。"""
    return bool(_INSTEAD_OF.match(text))


def clock_meals(text: str) -> set[str]:
    """这一截里说的几点吃的（“十二点吃了一碗米饭”“8:30吃的”）按时间算是哪几餐（同 meal_from_time）：
    没说上午下午的，两种都算（“八点”是早餐或晚餐，“十二点”是午餐或加餐）。没说几点是空的。"""
    meals: set[str] = set()
    for found in _ATE_AT.finditer(text):
        number = re.match(r"\d{1,2}|[零〇一二两三四五六七八九十]+", found.group(1))
        if number is None:
            continue
        hour = int(number_value(number.group()))
        if hour > 24:
            continue
        if 0 < hour < 12:
            hours = {hour, hour + 12}
        elif hour == 12:
            hours = {12, 0}
        else:
            hours = {hour % 24}
        meals |= {meal_from_time(datetime(2000, 1, 1, h)) for h in hours}
    return meals


# 说的是几餐都吃了（“三餐都喝了牛奶”“每顿一个鸡蛋”“早中晚各一个”“早晚喝了牛奶”
# “早、中各一个”“中晚饭都是米饭”）。“早午餐”是一餐，“两餐之间”说的是什么时候，
# “三餐很规律”说的是吃饭规不规律，“早早吃了”是吃得早。后面接着“没、不、要、之外、
# 吃得、吃不”的（“好几顿没吃”“早晚都要减肥”“三餐之外”“三餐都吃得很少”“每顿都吃不饱”），
# “好几顿”“这几顿”，说的都不是那几餐吃了东西：拿不准的不提
_MANY_MEALS = re.compile(
    r"(?:(?:(?<![好这前近])几|[两三]|每一?)[餐顿](?!之间|中间)|餐餐|顿顿|早中晚"
    r"|(?:早、?中、?晚|早、?[中晚]|中、?晚)(?:饭|餐)?(?:[各都]|(?=[吃喝])))"
    rf"(?![^{CLAUSE_END}]{{0,3}}(?:规律|正常|准时|按时|定时|固定))"
    r"(?!(?:都|也|各)?(?:没|不|要|之外|以外|[吃喝][得不]))"
)


def many_meals(text: str) -> list[str]:
    """一段话里说几餐都吃了的词，按先后，不重复（第 6 节）。"""
    return list(dict.fromkeys(found.group() for found in _MANY_MEALS.finditer(text)))


def says_again(old: str, new: str) -> bool:
    """新的这句是不是“又、再、还”加上旧的那句（“又吃了一个苹果”）：说的是又一次，不是重复。

    old、new 都是归一化之后的（compact）。
    """
    return new.endswith(old) and _AGAIN.fullmatch(new[: len(new) - len(old)]) is not None


def meal_from_time(moment: datetime) -> str:
    hour = moment.hour
    if 5 <= hour < 10:
        return "早餐"
    if 11 <= hour < 14:
        return "午餐"
    if 17 <= hour < 21:
        return "晚餐"
    return "加餐"
