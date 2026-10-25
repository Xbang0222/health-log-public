"""只作食物名边界的口语短语；不把不定量转换成数量。"""

from __future__ import annotations

import re

from hl.language.quantities import quantities
from hl.language.units import PORTION_WORDS

_COUNTERS = "|".join(
    re.escape(word) for word in sorted((*PORTION_WORDS, "口"), key=len, reverse=True)
)
_VAGUE = re.compile(
    rf"一点点|一小点|一点(?![零〇一二两三四五六七八九十百千万\d])|一些|少许|少量"
    rf"|几(?:小|大)?(?:{_COUNTERS})"
)
_POINT = re.compile(
    r"(?:[吃喝加放来]了?|还有|有|就)(?P<amount>点)(?!心|[零〇一二三四五六七八九十\d])"
)
_ACTION = re.compile(r"抹了|包着")


def name_boundaries(text: str) -> set[int]:
    """模糊份量和动作只分开食物名，数量仍由 quantities 唯一解析。"""
    measured_ends = {q.end for q in quantities(text) if not q.bare}
    # “一份一点点奶茶”已经说了明确份量，后面的“一点点”留给食物名。
    spans = [match.span() for match in _VAGUE.finditer(text) if match.start() not in measured_ends]
    spans += [match.span() for match in _ACTION.finditer(text)]
    spans += [match.span("amount") for match in _POINT.finditer(text)]
    return {at for start, end in spans for at in range(start, end)}


def unconsumed_soup(text: str, end: int, concept: str | None) -> bool:
    """只识别已知汤面之后明确的汤未喝；不适用于普通汤或整碗未吃。"""
    return (
        concept == "牛肉面"
        and re.match(r"汤(?:没喝|没有喝)(?!完|几|多少|光|尽)", text[end:]) is not None
    )
