"""查找原话里的食物位置、额外份量以及未吃范围。"""

from __future__ import annotations

import re

from hl.foods import concepts
from hl.foods.concept_types import Index
from hl.foods.lexicon_build import lexicon, tokens
from hl.foods.lexicon_types import FOOD, NOT_SAME, Span
from hl.language import meals as language_meals
from hl.language import normalize as language_normalize
from hl.language import phrases as language_phrases
from hl.language import quantities as language_quantities
from hl.language import quantity_scope as language_quantity_scope

# 没说食物名、只说了数量的半句，带着这些词才是“又吃了多少”（“大概 250 毫升”只是在补充前面的份量）
_AGAIN = "又|再|还|另|多|加|添|续|吃|喝|来|干|啃|后来|然后|接着|之后|随后|过后"

_HELPING = re.compile("|".join((_AGAIN, *language_phrases.MEAL_WORDS)))

# 有这些的不是：合计、没吃的、只是想吃、时间和人数
_NOT_A_HELPING = re.compile(
    r"一共|总共|合计|共计|总计|加起来|加一起|剩|扔|没[吃喝动]|倒[了掉]|想|打算|准备|本来|差点"
    r"|个(?:小时|钟头|月|星期|礼拜|人)"
)

# 只是在说没吃什么（F 是食物名）：“没吃牛肉面”“牛肉面和饺子都没吃”。“没吃完、没吃几口”是吃了的
_FOODS = r"F(?:(?:和|跟|与|还有|也)?F)*"

_NOT_EATEN = re.compile(
    rf"(?:但是?|可是|不过|而且|就|也|都|还)*(?:没有?|不|别)[吃喝要点](?:过|了)?{_FOODS}[了的啊呢呀]*"
    rf"|{_FOODS}(?:就|也|都|还|倒是)*(?:没有?|不)[吃喝要点](?:过|了)?[了的啊呢呀]*"
)


def scan(index: Index, text: str) -> list[Span]:
    """文本里提到的食物词（第 2.2 节的取词）：概念别名、菜谱别名、独立品种词，和不是同一种东西的词。

    concept 是概念名；不是同一种东西的词没有概念，concept 就是这个词自己。
    """
    return [
        Span(token.start, token.end, token.word, token.concept or token.word)
        for token in tokens(lexicon(index), text)
        if token.kind in (FOOD, NOT_SAME)
    ]


def placed(text: str, names: list[str]) -> list[Span]:
    """items 里的名字在文本里各出现在哪：长名先占位，“土鸡蛋”里的“鸡蛋”不再算一次。"""
    taken = [False] * len(text)
    spans = []
    for name in sorted({name for name in names if name}, key=lambda n: (-len(n), n)):
        start = text.find(name)
        while start != -1:
            end = start + len(name)
            if not any(taken[start:end]):
                taken[start:end] = [True] * len(name)
                spans.append(Span(start, end, name, ""))
            start = text.find(name, start + 1)
    return sorted(spans, key=lambda span: span.start)


def helpings(index: Index, text: str, listed: list[Span], offset: int) -> list[Span]:
    """R3：没说名字、只说了数量的半句（“后来又吃了一个”），各算在它前面最近提到的食物上。

    text 是用户那条消息从头到原话末尾的文字，offset 之后才是原话；只数落在原话里的半句。
    listed 是 items 里的名字出现的地方（见 placed）。
    返回每个这样的半句：位置，和它算在哪个食物名上。
    “最近提到的”只在用得上这个单位的食物里找（“一碗米饭，又吃了两个”说的不是米饭）。
    食物名那半句自己没带数量时，后面第一个只有数量的半句是它自己的数量，不是又一次。
    """
    others = [span for span in scan(index, text) if not _overlaps(span, listed)]
    foods = sorted([*listed, *others], key=lambda span: span.end)
    extra = []
    seen: list[Span] = []
    owed: set[Span] = set()  # 说了名字、还没说数量的
    for start, end in language_quantity_scope.halves(text):
        half = text[start:end]
        named = [span for span in foods if span.start < end and start < span.end]
        if named:
            seen += named
            owed |= {span for span in named if not _has_amount(index, half, span)}
            continue
        food = next((span for span in reversed(seen) if _has_amount(index, half, span)), None)
        if food in owed:
            owed.discard(food)
        elif food in listed and start >= offset and _is_helping(half):
            extra.append(Span(start, end, food.word, ""))
    return extra


def _is_helping(half: str) -> bool:
    """这半句说的是不是“又吃了多少”：带着“又、后来、中午、吃、喝”这类词，又不是在说合计、没吃的。"""
    return bool(_HELPING.search(half)) and not _NOT_A_HELPING.search(half)


def _has_amount(index: Index, half: str, food: Span) -> bool:
    """这半句里有没有这种食物用得上的份量（数字加它的单位）。"""
    hit = concepts.lookup(index, food.word)
    return language_quantities.has_amount(half, concepts.units_for(hit[0] if hit else None))


def _overlaps(span: Span, others: list[Span]) -> bool:
    return any(span.start < other.end and other.start < span.end for other in others)


def spots(index: Index, said: str, names: list[str], ahead: str = "") -> list[int]:
    """原话里说到 items 里这些食物的每一处，位置从原话开头数（第 6 节认餐次用）。

    名字出现的地方算，没说名字、只说了数量的半句（R3）也算。
    """
    listed = placed(ahead + said, names)
    found = [*listed, *helpings(index, ahead + said, listed, len(ahead))]
    return sorted(span.start - len(ahead) for span in found if span.start >= len(ahead))


def food_spots(index: Index, text: str) -> list[int]:
    """R11 核对用户重说的那句（第十轮 D-1）：文本里说到吃的东西的每一处，不看 items。

    概念表里的食物名算；没说名字、只说了数量的半句，R3 算作又吃了一次的也算（“昨天晚上一碗米饭，
    今天晚上两碗”的后半句，算在前面说过的米饭上）。名字说在后面的不算（“昨天晚上一碗，
    今天晚上两碗米饭”的前半句）：引擎不猜那一碗是什么。
    """
    named = scan(index, text)
    return sorted(span.start for span in [*named, *helpings(index, text, named, 0)])


def not_eaten(index: Index, text: str) -> bool:
    """这一段是不是只在说没吃什么（“没吃牛肉面”“牛肉面没吃”）：只有食物名和“没吃、没喝”，
    没有份量，也没有别的话；或者说的是还没吃、打算以后吃的（“明天早上打算吃一个苹果”）。
    R11 给出没记过的那一段时不算它。拿不准的都不算。"""
    if language_meals.planned(text):
        return True
    said = language_normalize.compact(text)
    spans = scan(index, said)
    if not spans:
        return False
    shape, at = "", 0
    for span in spans:  # 食物名换成 F；compact 之后都是小写，不会和原文里的字混在一起
        shape += said[at : span.start] + "F"
        at = span.end
    return _NOT_EATEN.fullmatch(shape + said[at:]) is not None


def unrecorded(index: Index, message: str, heard: list[str]) -> list[str]:
    """R3：用户这条消息里提到的食物中，哪些词在 heard（已经记下的原话和回答）里没出现过。"""
    words = dict.fromkeys(span.word for span in scan(index, message))
    return [word for word in words if not any(word in text for text in heard)]
