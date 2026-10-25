"""餐次词与时间词的句内归属。"""

from __future__ import annotations

import re

from hl.language.phrases import (
    _AS,
    _AS_MEAL,
    _AT_CLOCK,
    _ATE,
    _ATE_IT_TAIL,
    _COMPARED,
    _DAY_OF,
    _DAY_TAIL,
    _DAY_WORDS,
    _DAYS_AGO,
    _GROUPS,
    _IS,
    _MEALS_OF,
    _NOT_THIS_MEAL,
    _SAME_TIME,
    _SKIPPED,
    _THAT_MEAL,
    _WHEN,
    DAYS,
)


def _eaten(lead: str) -> bool:
    """“<哪天>（的）<餐名>”说的是不是吃了那顿剩下的（第 6 节），不是那一餐。
    lead 是半句里它前面的话：前面说了吃喝、带、热、把（_ATE），或者紧挨着的是这一餐的餐次词
    加“是”（“中午是昨天的晚饭”“午饭就是昨天的晚饭”）的是。"""
    if _ATE.search(lead):
        return True
    link = _IS.search(lead)
    return bool(link) and any(
        found.end() == link.start() for group in _GROUPS for found in group.finditer(lead)
    )


def _marks(group: re.Pattern[str], clause: str) -> list[tuple[int, str, str, int, bool]]:
    """一组餐次词在一个半句里说到这一餐的每一处：（位置，餐次，词，几天前，明说了哪天没有）。

    “昨天晚上的米饭”说的是那顿饭里的东西，不算；“昨天晚上的夜宵”“昨晚宵夜”后面是餐名，
    说的还是这一餐。吃了那顿剩下的（“中午吃了昨晚的夜宵”，见 _eaten），那顿的餐名、时间词都不算。
    """
    marks = []
    for found in group.finditer(clause):
        word = found.group()
        before, after = clause[: found.start()], clause[found.end() :]
        if _NOT_THIS_MEAL[0].search(before) or _NOT_THIS_MEAL[1].match(after):
            continue
        days = _DAYS_AGO.search(before) or _DAY_OF.search(before)
        lead = before[: days.start("day")] if days else before
        if _COMPARED[0].search(lead) or (_COMPARED[1].search(lead) and _COMPARED[2].match(after)):
            continue
        dated = bool(days) or word in _DAY_WORDS
        gap = 1 if re.match("的(?!时候)", after) else 0
        named = _GROUPS[0].match(after, gap)  # 后面紧跟着（隔着“的”）餐名
        if dated and gap and not named:
            continue
        if group is _GROUPS[0]:
            that = _THAT_MEAL.search(before)
            if that and _eaten(before[: that.start()]):
                continue
        elif dated and named:
            if _NOT_THIS_MEAL[1].match(after, named.end()) or _eaten(lead):
                continue
        ago = _DAY_WORDS.get(word, DAYS[days["day"]] if days else 0)
        marks.append((found.start(), _MEALS_OF[word], word, ago, dated))
    return marks


# _marks 认出的一处：（位置，餐次，词，几天前，明说了哪天没有）
_MealMark = tuple[int, str, str, int, bool]


def same_time(name: str, word: str) -> bool:
    """时间词 word 说的是不是餐名 name 那一餐吃的时候：同一餐（“早饭”“早上”），
    或者那一餐就在这个时候吃（“夜宵”“晚上”“昨晚”，“下午茶”“下午”，“早饭”“上午”）。
    零食、加餐什么时候都能吃，不算。"""
    meal = _MEALS_OF.get(name)
    return word in _SAME_TIME.get(name, ()) or (meal != "加餐" and meal == _MEALS_OF.get(word))


def _own_meal(clause: str, mark: _MealMark, names: list[_MealMark]) -> bool:
    """有餐名的半句里，没跟着餐名的一个时间词说的是不是它自己那一餐（从它另起一截）。

    在餐名后面的：中间说了这一餐吃了什么、没吃（“早饭吃了两个鸡蛋晚上吃了一碗米饭”
    “早饭没吃中午吃了一碗米饭”），或者那个餐名是没吃的（“没吃早饭中午……”），是；
    中间只说了是、在、才、到这些（“早饭上午十点才吃”“宵夜是昨天晚上吃的”），说的是
    这一餐什么时候吃的，不是；是这一餐吃的时候、后面只说了几点（“夜宵吃了一碗米饭晚上十一点”），
    也是在说这一餐几点吃的，不是。在餐名前面的：中间说了吃、又不是吃了什么当作这一餐的
    （“中午吃了一碗米饭晚饭吃了两个鸡蛋”）是；中间说的是别的事（“昨晚没睡好早饭……”）、
    说的吃是吃了这一顿（“昨晚没睡好吃了宵夜”的“吃了”）不是（第十轮 D-3）。
    后面隔着“的”说的是那一餐的东西的（“午饭吃了晚上的米饭”）不是。"""
    pos, _, word, _, _ = mark
    end = pos + len(word)
    if re.match("的(?!时候)", clause[end:]) and not _GROUPS[0].match(clause, end + 1):
        return False
    ahead = [name for name in names if name[0] + len(name[2]) <= pos]
    if ahead:
        at, _, said, name_ago, name_dated = ahead[-1]
        between = _DAY_TAIL.sub("", clause[at + len(said) : pos])
        if _SKIPPED.search(clause[:at]):
            return True
        # “昨天的晚饭今天中午热了”“10月6号的晚饭今天中午热了”：餐名和时间词各说了一天、
        # 又不是这一餐吃的时候，说的是另一餐。餐名没说哪天的，还要紧挨着才算
        # （“早饭今天早上吃的”“零食是昨天晚上吃的”“昨天的宵夜今天凌晨吃的”还是这一餐）
        if (
            mark[4]
            and not same_time(said, word)
            and ((name_dated and mark[3] != name_ago) or (not name_dated and not between))
        ):
            return True
        if _WHEN.fullmatch(between):
            return False
        return not (same_time(said, word) and _AT_CLOCK.fullmatch(clause[end:]))
    between = clause[end : names[0][0]]
    eaten = _ATE_IT_TAIL.sub("", between)
    return bool(re.search("[吃喝]", eaten)) and not re.search(f"{_AS}$", between)


def _meal_marks(clause: str) -> list[tuple[int, str, str, int, bool, int]]:
    """一个半句里说到餐次的每一处：（位置，餐次，词，几天前，明说了哪天没有，从哪里切开）。
    有餐名时餐名优先：时间词说的是这一餐的，跟着餐名算，说的是另一餐的（见 _own_meal）才另算。
    餐名前面没说是哪天的，只有时间词说的就是这一餐时才带上它那天：时间词紧跟着餐名、
    中间隔着“的”（“昨晚宵夜”“昨天晚上的夜宵”），或者中间只说了吃、几点吃的、饿了吃的、
    吃了什么当作这一餐（“昨晚吃的宵夜”“昨晚吃了顿宵夜”“昨晚11点吃的宵夜”“昨晚饿了吃了宵夜”
    “昨天早上吃了两个鸡蛋当早饭”，见 _AS_MEAL），“今早早饭”明说了是今天。
    时间词和餐名中间说的是别的事（“昨晚没睡好早饭……”“昨天晚上加班到很晚早饭……”）、
    时间词在餐名后面（“宵夜是昨天晚上吃的”），拿不准，不带：没填 date 就记到今天，不逼模型改。
    带了日子的餐名从那个时间词切开。"""
    names, times = (_marks(group, clause) for group in _GROUPS)
    if not names:
        return [(*mark, mark[0]) for mark in times]
    marks, taken = [], set()
    for n, (pos, meal, word, ago, dated) in enumerate(names):
        last = names[n - 1][0] + len(names[n - 1][2]) if n else 0
        ahead = [mark for mark in times if last <= mark[0] < pos]
        cut = pos
        if ahead:  # 这个餐名前面最近的时间词，和上一个餐名之间没有别的餐名
            at, _, said, days_ago, said_day = ahead[-1]
            between = clause[at + len(said) : pos]
            if between in ("", "的") or _AS_MEAL.fullmatch(between):
                cut = at
                taken.add(at)
                if said_day and not dated:
                    ago, dated = days_ago, True
        marks.append((pos, meal, word, ago, dated, cut))
    for mark in times:
        if mark[0] not in taken and _own_meal(clause, mark, names):
            marks.append((*mark, mark[0]))
    return sorted(marks, key=lambda mark: mark[5])
