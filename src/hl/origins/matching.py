"""原话分句边界、出处定位和同会话回答核对。"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from pathlib import Path

from hl.language import normalize as language_normalize
from hl.language import phrases as language_phrases
from hl.language import units as language_units
from hl.origins.inbox import INBOX, Message, Quote, recent, together
from hl.origins.messages import (
    FIX_ANSWER,
    FIX_INSTALL,
    FIX_OTHER_SESSION,
    FIX_SAME_MESSAGE,
    FIX_VERBATIM,
    FIX_WIDEN,
    HARD,
    SOFT,
    Quotes,
)
from hl.result import Abort, problem, rejected


def _runs_on(ch: str) -> bool:
    """数字或拉丁字母：它后面的空格只是排版（"200 克""whey protein"），不是停顿。"""
    return ch.isdigit() or "LATIN" in unicodedata.name(ch, "")


def _ends_sentence(ch: str) -> bool:
    """夹在两个数字之间时也断句的字符：逗号、顿号、句号、分号、问号、叹号、括号、引号、换行。

    小数点、连字符、斜杠、冒号、撇号和各种符号不算：1.5、1-2、1/2、8:30 是一个整体。
    """
    category = unicodedata.category(ch)
    if category in ("Zl", "Zp") or ch in "\n\r\v\f\x85":
        return True
    return category[0] == "P" and category != "Pd" and ch not in "./:'·"


def _hugs(ch: str) -> bool:
    """贴在抄下来的那一段两头、比较时被去掉的符号（%、括号……）：算进原文里，句读不算。"""
    return language_normalize.kind(ch) in "PS" and ch not in language_units.CLAUSE_END


def _break(folded: str, places: list[int], index: int) -> int:
    """留下的第 index 个字符前面是不是分句的边界；是的话，是 SOFT 还是 HARD。

    消息的头尾、标点、换行是边界；空格左边是汉字时也是（语音输入拿空格当停顿）；
    餐次用词（早上、午饭……）前面也是，哪怕没有标点。
    两个数字之间：小数点、连字符、斜杠、冒号、空格不是边界（1-2、1/2 不能从中间切开），
    逗号、顿号、括号、换行这些句读照样是。
    """
    if index in (0, len(places)):
        return HARD
    kind = language_normalize.kind
    low, high = index - 1, index
    while kind(folded[places[low]]) in "PZCS":  # 两个数字之间留下来的符号：退到两边的数字
        low -= 1
    while kind(folded[places[high]]) in "PZCS":
        high += 1
    left, right = places[low], places[high]
    gap = folded[left + 1 : right]
    if (low, high) != (index - 1, index) or (folded[left].isdigit() and folded[right].isdigit()):
        return HARD if any(_ends_sentence(ch) for ch in gap) else 0
    if any(kind(ch) in "PSC" or unicodedata.category(ch) in ("Zl", "Zp") for ch in gap):
        return HARD
    if gap and not _runs_on(folded[left]):
        return SOFT
    return SOFT if folded.startswith(language_phrases.MEAL_WORDS, right) else 0


def _prepared(message: Message) -> tuple[str, str, str, list[int]]:
    """（原文，折成小写的原文，去掉空白标点后的样子，它每个字在原文里的位置）。"""
    cleaned = language_normalize.clean(message.text)
    folded = cleaned.casefold()
    if len(folded) != len(cleaned):  # 个别字符折成小写会变长，位置对不上：拿折过的当原文
        cleaned = folded
    return (cleaned, folded, *language_normalize.squeeze(folded))


def locate(text: str, message: Message) -> Quote | None:
    """text 是不是从这条消息里原样抄下来的一个或连续几个完整分句；是就返回（第一处的）出处。"""
    return next(_quotes(text, message), None)


def locations(text: str, message: Message) -> list[Quote]:
    """text 在这条消息里的每一处出处，按先后排列（同样的话一条消息里可能说了不止一次，R11）。"""
    return list(_quotes(text, message))


def _quotes(text: str, message: Message) -> Iterator[Quote]:
    needle = language_normalize.compact(text)
    if not needle:
        return
    cleaned, folded, hay, places = _prepared(message)
    start = hay.find(needle)
    while start != -1:
        end = start + len(needle)
        if _break(folded, places, start) and _break(folded, places, end):
            first, last = places[start], places[end - 1] + 1
            while last < len(cleaned) and _hugs(cleaned[last]):  # “22%”的 % 跟着数字走
                last += 1
            while first and _hugs(cleaned[first - 1]):
                first -= 1
            head = max(cleaned.rfind(ch, 0, first) for ch in language_units.CLAUSE_END) + 1
            tails = [
                pos for ch in language_units.CLAUSE_END if (pos := cleaned.find(ch, last)) != -1
            ]
            tail = min(tails, default=len(cleaned))
            ahead = cleaned[: max(head - 1, 0)]
            prior = ahead[max(ahead.rfind(ch) for ch in language_units.CLAUSE_END) + 1 :]
            before, after = cleaned[head:first], cleaned[last:tail]
            text = cleaned[first:last]
            yield Quote(message, before, after, text, first, prior, cleaned[:first])
        start = hay.find(needle, start + 1)


def _widen(text: str, messages: list[Message]) -> str | None:
    """text 在用户最近说的话里，只是没抄完整：返回把它包在里面的完整分句（最近的那条消息里的）。"""
    needle = language_normalize.compact(text)
    for message in reversed(messages):
        cleaned, folded, hay, places = _prepared(message)
        start = hay.find(needle) if needle else -1
        if start == -1:
            continue
        end = start + len(needle)
        while not _break(folded, places, start):
            start -= 1
        while not _break(folded, places, end):
            end += 1
        return cleaned[places[start] : places[end - 1] + 1]
    return None


def _not_said(where: str, text: str, messages: list[Message]) -> dict[str, str]:
    whole = _widen(text, messages)
    fix = (FIX_WIDEN.format(whole=whole) if whole else "") + FIX_VERBATIM
    return problem(where, f"“{text}”不是用户最近说过的原话", fix)


def sources(text: str, messages: list[Message]) -> list[Quote]:
    """text 在这些消息里的出处，按消息先后排列（一句话用户可能说过不止一次）。"""
    found = (locate(text, message) for message in messages)
    return [quote for quote in found if quote is not None]


def said_in(text: str, messages: list[Message]) -> bool:
    return bool(sources(text, messages))


def placed(data_dir: Path, quotes: Quotes, answers: Quotes = ()) -> list[Quote]:
    """quotes 每一条最近一次的出处，回答所在的那几条消息不算：用户回答时又说了一遍同样的话
    （问“是另外又吃了一份吗”，他回“不是，两碗米饭”），原话还是引擎问的那一句，不是回答里的
    （规则 24）。只核对 quotes，不核对 answers：hl add 先按出处查重，再核对回答（require）；
    回答说在原话之前、用户后来又说了一遍原话的，原话照样认后来那一处，回答由 require 拒掉。
    任何一条原话对不上、收件箱不存在，都以 rejected 结束这条命令。"""
    messages = recent(data_dir)
    if messages is None:
        where = f".hl/{INBOX}"
        raise Abort(rejected([problem(where, "用户原话收件箱不存在，无法核对原话", FIX_INSTALL)]))
    replies = {hits[-1].message.pos for _, text in answers if (hits := sources(text, messages))}
    said = [sources(text, messages) for _, text in quotes]
    said = [[quote for quote in hits if quote.message.pos not in replies] or hits for hits in said]
    errors = [
        _not_said(where, text, messages)
        for (where, text), hits in zip(quotes, said, strict=True)
        if not hits
    ]
    if errors:
        raise Abort(rejected(errors))
    return [hits[-1] for hits in said]


def require(data_dir: Path, quotes: Quotes, answers: Quotes = (), asked: int = 0) -> list[Quote]:
    """quotes、answers 都是（出处，原话）列表；任何一条对不上就以 rejected 结束这条命令。

    answers 是用户的回答，还得是提问之后说的：asked 是引擎提问时收件箱的行数（没问过是 0）；
    没问过，或者原话是提问之后才说的，就要出自原话所在那条消息之后。同时开着几个对话时，
    回答还得是和原话同一个对话里说的（together，K-1）。
    返回每一条最近一次的出处，先 quotes 后 answers。带着回答时，原话认回答之前最近的那一处：
    用户说“删掉”，引擎问“要删除吗”，用户又回了一句“删掉”，原话是前一句，回答是后一句。
    回答之前没说过的，才认最近的那一处。
    """
    messages = recent(data_dir)
    if messages is None:
        where = f".hl/{INBOX}"
        raise Abort(rejected([problem(where, "用户原话收件箱不存在，无法核对原话", FIX_INSTALL)]))
    replies = [sources(text, messages) for _, text in answers]
    first = min((hits[-1].message.pos for hits in replies if hits), default=None)  # 最早的回答
    said = [sources(text, messages) for _, text in quotes]
    if first is not None:
        said = [[quote for quote in hits if quote.message.pos < first] or hits for hits in said]
    spoken = max((hits[-1].message.pos for hits in said if hits), default=-1)  # 原话最近说在第几行
    # 原话是在哪个对话里说的：回答只认这个对话里的（K-1）
    home = next((h[-1].message.session for h in said if h and h[-1].message.pos == spoken), "")
    after = max(asked, spoken + 1)
    errors = []
    for (where, text), hits in zip(quotes, said, strict=True):
        if not hits:
            errors.append(_not_said(where, text, messages))
    for pos, ((where, text), hits) in enumerate(zip(answers, replies, strict=True)):
        later = [quote for quote in hits if quote.message.pos >= after]
        replies[pos] = [quote for quote in later if together(quote.message.session, home)]
        if not hits:
            errors.append(_not_said(where, text, messages))
        elif not replies[pos] and later:
            what = f"“{text}”是用户在另一个对话里说的，不能当作这次的回答"
            errors.append(problem(where, what, FIX_OTHER_SESSION))
        elif not replies[pos] and hits[-1].message.pos == spoken:
            what = f"“{text}”和原话在同一条消息里，不是用户后来的回答"
            errors.append(problem(where, what, FIX_SAME_MESSAGE))
        elif not replies[pos]:
            when = "引擎提问" if asked > spoken else "说那句原话"
            what = f"“{text}”是用户在{when}之前说的话，不能当作这次的回答"
            errors.append(problem(where, what, FIX_ANSWER))
    if errors:
        raise Abort(rejected(errors))
    return [hits[-1] for hits in (*said, *replies)]
