"""约数修饰词与份量的句内归属。"""

from __future__ import annotations

import re

from hl.language.normalize import compact
from hl.language.phrases import _HALF_END, _HALF_START, DAY_WORD, MEAL_WORDS
from hl.language.quantities import quantities
from hl.language.quantity_tokens import Quantity
from hl.language.units import (
    _AFTER_HEDGES,
    _FILLERS,
    _NUMBER,
    CLAUSE_END,
    HEDGES,
    PORTION_WORDS,
    UNIT_FORMS,
)

# 约数词和它说的那处数量之间只能隔着这些（增补第 12 节）
_HEDGE_GAP = r"(?:\s|有|是|吃了|喝了)*"


_HEDGE_BEFORE = re.compile(
    rf"(?P<word>{'|'.join(word for word in HEDGES if word not in _AFTER_HEDGES)}){_HEDGE_GAP}$"
)


_HEDGE_AFTER = re.compile(rf"\s*(?P<word>{'|'.join(_AFTER_HEDGES)})")


_HEDGE_WORDS = re.compile("|".join(HEDGES))


def _hedge_by(text: str, quantity: Quantity) -> re.Match[str] | None:
    """紧挨着这处数量的约数词，连同它在 text 里的位置（见 hedge_near）。"""
    return _HEDGE_BEFORE.search(text, 0, quantity.start) or _HEDGE_AFTER.match(text, quantity.end)


def hedge_near(text: str, quantity: Quantity) -> str | None:
    """紧挨着这处数量的约数词，没有就是 None（增补第 12 节）。

    说在数前面的（大概、大约、差不多、估计、目测）和数之间只能隔着空白、有、是、吃了、喝了；
    “左右”要紧跟在数后面。“一个人吃了大概两碗”的“大概”只算“两碗”的。
    """
    found = _hedge_by(text, quantity)
    return found["word"] if found else None


def is_approx(text: str, quantity: Quantity) -> bool:
    """R13、增补第 12 节：这处数量是不是说成了约数。一个约数词只落在一处数量上。

    紧挨着哪处数量（hedge_near），就是哪处的。不挨着任何数量的（“200克米饭（大概）”
    “米饭200克、左右吧”“大概五花肉150克”）落在同一个半句里（到标点为止，见 CLAUSE_END）后面
    最近的那处，后面没有就前面最近的；“左右”说在数后面，先找前面的。别的半句里的不算。
    quantity 的位置按 text 算。
    """
    if hedge_near(text, quantity) is not None:
        return True
    start = max(text.rfind(mark, 0, quantity.start) for mark in CLAUSE_END) + 1
    ends = [text.find(mark, quantity.end) for mark in CLAUSE_END]
    end = min((pos for pos in ends if pos >= 0), default=len(text))
    others = [
        q
        for q in quantities(text, [quantity.unit])
        if not q.bare and start <= q.start and q.end <= end
        if q.end <= quantity.start or q.start >= quantity.end
    ]
    near = sorted([quantity, *others], key=lambda q: q.start)
    taken = {found.span("word") for q in near if (found := _hedge_by(text, q))}
    for word in _HEDGE_WORDS.finditer(text, start, end):
        if word.span() in taken:
            continue
        after = [q for q in near if q.start >= word.end()][:1]
        before = [q for q in near if q.end <= word.start()][-1:]
        targets = before + after if word[0] in _AFTER_HEDGES else after + before
        if targets and targets[0] is quantity:
            return True
    return False


# 说吃了多少用的份量（names_more）：份量的量词，加上“口、点、些”和克、毫升
_EATEN_UNITS = (*PORTION_WORDS, "口", "点", "些", *UNIT_FORMS["g"], *UNIT_FORMS["ml"])


_EATEN_AMOUNT = re.compile(
    rf"(?:{_NUMBER}|半)[{_FILLERS}]?(?:{'|'.join(sorted(_EATEN_UNITS, key=len, reverse=True))})半?",
    re.IGNORECASE,
)


_EATING = re.compile(r"[吃喝啃]")

# 说吃了什么时，食物名之外常说的字（哪天、哪一餐、份量另外去掉）
_PLAIN_WORDS = re.compile(
    r"不是|不对|其实|一共|总共|加起来|大概|大约|差不多|左右|应该|还有|就是|只有|然后|后来|好的"
    r"|[我就也都还又再只才是有和跟与各对好嗯哦噢喔呃那这的了啊呀吧呢嘛哈啦吃喝啃过完]"
)


_MEAL_WORD = re.compile("|".join(sorted(MEAL_WORDS, key=len, reverse=True)))


def names_more(text: str) -> bool:
    """R11 核对用户重说的那句（第十轮 D-1、D-2）：这段话说了份量或者吃、喝，去掉哪天、哪一餐、
    份量和“吃了、是、就、一共”这些之后还剩下字（“一碗螺蛳粉”“吃了螺蛳粉”）：多半说了概念表里
    没有的食物。“两碗”“昨天晚上一碗”“就两个”只说了份量；“等一下”“好的”没说吃的，都不算。"""
    said = compact(text)
    if not (_EATEN_AMOUNT.search(said) or _EATING.search(said)):
        return False
    rest = _EATEN_AMOUNT.sub("", said)
    rest = _MEAL_WORD.sub("", re.sub(DAY_WORD, "", rest))
    return bool(_PLAIN_WORDS.sub("", rest))


def halves(text: str) -> list[tuple[int, int]]:
    """把一段话切成半句，返回每个半句的起止位置。

    标点、换行断开；汉字后面的空格断开（语音输入拿空格当停顿）；
    餐次用词和“后来、然后、接着、之后、随后、过后、又、再、还”前面也断开，哪怕没有标点。
    """
    cuts = {0, len(text)}
    for found in _HALF_END.finditer(text):
        cuts.update(found.span())
    cuts.update(found.start() for found in _HALF_START.finditer(text))
    edges = sorted(cuts)
    pieces = zip(edges, edges[1:], strict=False)
    return [(start, end) for start, end in pieces if compact(text[start:end])]


def _portions(text: str) -> list[int]:
    """文本里明说了数字（或“半”）的份量各从哪里开始：数字后面带着单位或量词，见 quantities。"""
    return [quantity.start for quantity in quantities(text) if not quantity.bare]


def _hedge_target(text: str, piece: tuple[int, int], portions: list[int]) -> int | None:
    """一段里只有估计用词、没有份量（“鸡胸肉 大概 150克”的“大概”）：它说的是哪个份量。

    返回那个份量在 text 里的起点：后面最近的一个，后面没有就前面最近的一个；
    “左右”说在数的后面，先找前面的。portions 是 text 里每个份量的起点（见 _portions）。
    """
    start, end = piece
    after = [pos for pos in portions if pos >= end]
    before = [pos for pos in portions if pos < start]
    near = [after[0] if after else None, before[-1] if before else None]
    if all(word in _AFTER_HEDGES for word in HEDGES if word in text[start:end]):
        near.reverse()
    return next((pos for pos in near if pos is not None), None)


def is_hedged(text: str, span: tuple[int, int]) -> bool:
    """R13：这个份量是不是说成了估计。text 是份量所在的那半句（到逗号、句号、换行为止）。

    半句再按 halves 分段（汉字后面的空格，餐次用词和“然后、又、再”这类词的前面，见 halves）。
    估计用词管它那一段里的份量；那一段里没有份量，就管它说的那一个（见 _hedge_target）。
    份量是带着单位或量词的数：“一共、一下子”“五花肉”里的数字不算。
    """
    portions = _portions(text)
    for start, end in halves(text):
        if not any(word in text[start:end] for word in HEDGES):
            continue
        if not any(start <= pos < end for pos in portions):
            target = _hedge_target(text, (start, end), portions)
            if target is not None and span[0] <= target < span[1]:
                return True
        elif start <= span[0] < end:
            return True
    return False
