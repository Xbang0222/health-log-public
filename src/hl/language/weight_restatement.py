"""体重否定与重新陈述的判定。"""

from __future__ import annotations

import re

from hl.language.calendar_dates import _SAID_DAY
from hl.language.phrases import _DAY_WORDS, DAYS
from hl.language.units import CLAUSE_END
from hl.language.weight_normalize import _weight_text
from hl.language.weight_read import weights_in

# 否定体重的那句回答里，说不要这个数的（第十轮 W-4、C-1，规则 23）：数前面同一分句里的
# “不是、不算、别、不要、不按”（中间没有别的“是”和数：“不是81，是80”的 80 不算），
# 后面同一分句里的“不对、错了、离谱、不是”（“81公斤错了”“81太离谱了”；“没错了”不算），
# 后面的“是……的”（“81是昨天的”“81是我老婆的”“81那是昨天的”；“是对的、是真的”不算）
_NOT_THIS = re.compile(
    rf"(?:不是|不算|(?<![特分区告])别|不要|不按)[^是\d{re.escape(CLAUSE_END)}]*$"
)


_NOT_THIS_AFTER = re.compile(rf"[^\d{re.escape(CLAUSE_END)}]*?(?:不对|(?<![没不])错了|离谱|不是)")


_NOT_MINE = re.compile(
    rf"\s*(?:那个?|这个?|它)?\s*是(?!对|真|准|没错)[^\d{re.escape(CLAUSE_END)}]*的"
)

# 同一分句里说的是别的时候的（“上周是79”“昨天79”“以前是79”）：不是改口说的这次的体重
_OTHER_TIME = re.compile(
    r"上[个一]?(?:周|星期|礼拜|次|回|月)|之前|以前|原来|平时|去年|前几天|前阵子|那天|当时"
)


def _other_time(clause: str) -> bool:
    """这一分句说的是别的时候：有“上周、以前”这类词，或者有说的不是今天的日子词（见 _SAID_DAY）。"""
    if _OTHER_TIME.search(clause):
        return True
    for hit in _SAID_DAY.finditer(clause):
        word = hit.group("relative")
        if not word or DAYS.get(word, _DAY_WORDS.get(word, 0)):
            return True
    return False


def restated(reply: str) -> bool:
    """R16、R19（规则 23）：用户否定体重（比如问的是 81 公斤）的那句回答里又说了体重：
    说了别的数，是改口（“不对，是77.6”“81错了，是80”）；又说了这个数，是又说了一遍
    （“今天就是81公斤”）。两样都照 fix 拿这句回答不带确认再调用。
    只是不要这个数的不算：数前面是“不是、不算、别、不要、不按”，后面同一分句里跟着
    “不对、错了、离谱、不是”或者“是……的”（“别记81”“81公斤错了”“81是昨天的”）。
    同一分句里说的是别的时候的（“上周是79”）也不算：拿不准，照用户没有同意办。"""
    text = _weight_text(reply)
    for mention in weights_in(reply):
        if not mention.plausible:
            continue
        start, end = mention.span
        head = max(text.rfind(ch, 0, start) for ch in CLAUSE_END) + 1
        stop = min((p for ch in CLAUSE_END if (p := text.find(ch, end)) >= 0), default=len(text))
        if _NOT_THIS.search(text[head:start]) or _NOT_THIS_AFTER.match(text, end, stop):
            continue
        if _NOT_MINE.match(text, end) or _other_time(text[head:stop]):
            continue
        return True
    return False
