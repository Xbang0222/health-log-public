"""体重是否可直接记录的整句核对。"""

from __future__ import annotations

from collections.abc import Iterable

from hl.language.normalize import clean, simplified
from hl.language.weight_ambiguity import _rough_hits
from hl.language.weight_normalize import _weight_text, _without_asides
from hl.language.weight_read import _weight_marks, numbers_in
from hl.language.weight_types import WeightMention
from hl.language.weight_words import _TRAILING_PARTICLES, _WEIGHT_WORDS, _joined, _just_marks


def extra_words(
    message: str, mention: WeightMention, days: Iterable[tuple[int, int]] = ()
) -> str | None:
    """R16：整条消息里除了这个数和它的单位、说体重的词（见 WEIGHT_WORDS）、句尾的语气词
    （见 _TRAILING_PARTICLES）、标点和空白，多出来的第一段话，照原话的写法（“瘦了”“hhh”“7:00”）；
    没有多出来的返回 None。

    单位是用户单说的（“单位是斤”“按斤算”），那句话也算这个数的单位。整条消息里找不到这个数
    （模型抄的和消息对不上），整条消息都算多出来的。days 是调用方核对过、对得上要记的那天的
    日子词的位置（“昨天体重78.5”记到昨天，见 weight_days），也算说体重的词。
    """
    seen = clean(message)
    text = simplified(seen)
    found = [m for m, height in _weight_marks(message, message) if not height and m == mention]
    if not found:
        return seen.strip() or None
    # 这个数连同它的单位，单位是单说的再加上单说的那句（“单位是斤”）
    own = [range(*found[0].span), range(*(found[0].noted or (0, 0)))]
    own += [range(*span) for span in days]
    kept = [any(pos in part for part in own) for pos in range(len(text))]
    # 说体重的词一个字一个字往后找，重叠的也算（“帮我记一下”是“帮我记”和“记一下”）
    words = [_WEIGHT_WORDS.match(text, pos) for pos in range(len(text))]
    for hit in [*filter(None, words), *_TRAILING_PARTICLES.finditer(text)]:
        for pos in range(*hit.span()):
            kept[pos] = True
    for pos, ch in enumerate(text):
        kept[pos] = kept[pos] or _just_marks(ch)
    first = next((pos for pos, ok in enumerate(kept) if not ok), None)
    if first is None:
        return None
    # 给用户看的那一段：从多出来的第一个字往后，到空白、标点或这个数（和单说的单位）为止；
    # 数字中间的标点（“0.3”“7:00”）、两个字母中间的空白（“I weigh”）不断开
    stop = first + 1
    while stop < len(text) and not any(stop in part for part in own):
        if _just_marks(text[stop]) and not _joined(text, stop):
            break
        stop += 1
    return seen[first:stop].strip()


def plain_weight(message: str, mention: WeightMention) -> bool:
    """R16：这个数的写法一眼清楚：整条消息里只有这一个数（见 numbers_in），用阿拉伯数字写
    （可带一个小数点），后面紧跟体重单位或者没写单位、消息里也没单说单位（见 WeightMention.plain），
    换算成公斤像体重，消息里也没有约数的说法。message 是原话所在的整条消息。"""
    rest = _without_asides(_weight_text(message))
    return (
        mention.plain
        and mention.plausible
        and len(numbers_in(message)) == 1
        and next(_rough_hits(rest), None) is None
    )


def at_a_glance(message: str, mention: WeightMention) -> bool:
    """R16：这个体重一眼清楚，可以不问用户直接记：写法一眼清楚（见 plain_weight），
    整条消息里除了它和它的单位也只有说体重的词、标点和空白（见 extra_words）。"""
    return plain_weight(message, mention) and extra_words(message, mention) is None
