"""把用户回答判定为肯定、否定或尚不明确。"""

from __future__ import annotations

import re

from hl.confirmation.terms import (
    _AFFIRM,
    _AFFIRM_DROP,
    _APART,
    _ASKING,
    _CHANGE,
    _CLAUSE_TAIL,
    _DIGIT,
    _ERRORS,
    _KEEP,
    _NO_CHANGE,
    _NO_IN_CLAUSE,
    _NOISE,
    _NOT_AFTER,
    _NOT_BEFORE,
    _NOT_NO,
    _NOT_SEPARATE,
    _RETRACT,
    _SEPARATELY,
    _TRAIL,
    AGAIN,
    DROP_DEFAULT,
    DROP_RECORD,
    MORE,
    NO,
    UNCLEAR,
    YES,
)
from hl.language import normalize as language_normalize
from hl.language import units as language_units


# ---------- 用户的回答算不算确认 ----------
def _mode(deleting: bool | str) -> str:
    """问的是不是“要删除吗”、删的是什么；早先记下的 True 是删记录。"""
    return DROP_RECORD if deleting is True else deleting or ""


def judge(reply: str, deleting: bool | str = False) -> str:
    """用户这句话是在确认（YES）、否定或更正（NO），还是判不出（UNCLEAR）。

    引擎不猜：依次看
    1. 在问（吗、？❓、什么、对不对、对吧、谁让……）：判不出；
    2. 有否定或更正（不对、错了、改成、算了、不用……）：否定；
    3. 有省略号（嗯……）：在犹豫，判不出；
    4. 去掉空白、常见的标点和语气词之后，整句完全由肯定词拼成（“对”“对的，没问题”“好的好的”）：
       确认。带数字的（阿拉伯数字或中文数字）不算，复述引擎问的数也一样；
       带着别的符号、表情的也不算；
    5. 其余（肯定之后又说了别的、犹豫、带条件、不相干的话）都判不出。
    deleting：引擎问的是“要删除吗”（DROP_RECORD 删记录、DROP_DEFAULT 去掉默认品种）。
    这时“删吧、去掉、不要了”是同意，“不删、留着”是否定，“就这样、照记”分不清是删还是留，不算同意。
    “记错了、记重了”对记录是同意删；对默认品种是“你弄错了”，算否定。
    “撤销、撤掉”对记录是同意删；对默认品种多半是要取消这次操作，判不出。
    问的是 hl add 的去重（第十轮 C-5、D-5）：AGAIN 问“是另外又吃了一份吗？”，照上面判，
    只是回答里说了是另外吃的（“不是，鸡蛋是另外吃的”），前面的否定拿不准在否定什么，判不出；
    MORE 见 _add_or_change。
    """
    text = language_normalize.simplified(
        language_normalize.fold(reply)
    )  # 繁体字的“對”“沒錯”“不對”和简体一样认
    if _ASKING.search(text):
        return UNCLEAR
    mode, heard = _mode(deleting), _NOT_NO.sub(" ", text)
    if mode == MORE:
        return _add_or_change(text, heard)
    if mode in _AFFIRM_DROP:
        refused = _KEEP.search(heard) or (mode == DROP_DEFAULT and _ERRORS.search(heard))
    else:
        refused = _RETRACT.search(heard)
        if refused and mode == AGAIN and _APART.search(_NOT_SEPARATE.sub(" ", heard)):
            return UNCLEAR
    if refused:
        return NO
    if _TRAIL.search(text):
        return UNCLEAR
    plain = _NOISE.sub("", text)
    affirm = _AFFIRM_DROP.get(mode, _AFFIRM)
    return YES if affirm.fullmatch(plain) and not _DIGIT.search(plain) else UNCLEAR


def explained_denial(text: str) -> bool:
    """K16：否定之外还给了解释，需要澄清；不把解释当确认或推断用户的新选择。"""
    text = language_normalize.clean(text)
    if judge(text) != NO:
        return False
    # 明确取消的意愿到此为止；不能因为后面带理由就重新催问。
    if re.search(
        r"取消|算了|作废|不用|不要|不必|不需要|不改|别改|别问|不想|不可以|不行"
        r"|再想|想想|考虑|稍后|等会|先停|以后再|别(?:再)?[按改问定设记算动做办]"
        r"|太多|太少|离谱|不合适|不同意|不接受|不按|不算|先不",
        text,
    ):
        return False
    rest = _NOISE.sub("", _RETRACT.sub("", text))
    return len(rest) >= 4 and not re.fullmatch(r"[这是那个不没对错]+", rest)


def _add_or_change(text: str, heard: str) -> str:
    """R11（第十轮 D-5、C-5）：引擎问“是另外吃的、要补记上，还是要改这一餐？”（MORE），用户这句话
    选的是补记（YES）、改这一餐（NO），还是判不出。text 是折过繁简的回答，heard 去掉了“没错、
    不用改”这类不是否定的话（judge）。二选一：“对、是、不是、不对”都答不上，判不出。
    说了是另外吃的、要补记（“补记”“牛奶是另外喝的”，前面的“不是”不算），没说要改、没带数字：补记；
    说了要改（“改这一餐”“记错了”“只吃了……”“算了”）、或者说不是另外吃的（“不是另外喝的”“不用补记”），
    没说补记：改这一餐；两样都说了、有省略号、带数字（说了新的数）的判不出。"""
    heard = _NO_CHANGE.sub(" ", heard)
    rest = _NOT_SEPARATE.sub(" ", heard)
    adding = _SEPARATELY.search(rest)
    changing = _NOT_SEPARATE.search(heard) or _CHANGE.search(rest)
    if changing:
        return UNCLEAR if adding else NO
    plain = _NOISE.sub("", text)
    if not adding or _TRAIL.search(text) or _DIGIT.search(plain):
        return UNCLEAR
    return YES


def name_spots(reply: str, names: list[str]) -> list[tuple[str, int, int]]:
    """回答里说到 names 里哪几个名称、各在哪：（名称，起，止），位置按 textnum.fold 过的回答，
    按先后排。名称和核对名称时一样按 textnum.compact 比（空白、标点、引号不算）；一个名称是另一个的
    一部分时（“训练日”“大训练日”），先认长的。"""
    folded = language_normalize.fold(reply)
    squeezed, places = language_normalize.squeeze(folded)
    taken = [False] * len(squeezed)
    found = []
    for name in sorted(names, key=lambda name: len(language_normalize.compact(name)), reverse=True):
        word = language_normalize.compact(name)
        start = squeezed.find(word) if word else -1
        while start >= 0:
            end = start + len(word)
            if not any(taken[start:end]):
                taken[start:end] = [True] * len(word)
                found.append((name, places[start], places[end - 1] + 1))
            start = squeezed.find(word, end)
    return sorted(found, key=lambda spot: spot[1])


def negated(reply: str, spans: list[tuple[int, int]]) -> list[bool]:
    """回答里 spans 这几处（textnum.fold 过的回答里的位置）说到的名称、数，各是不是在说不要它
    （用户定的第 23 条）：前面在同一个半句里紧挨着否定词（“不是训练日”“别按训练日算”“不算训练日”
    “不是 1800 千卡”），或者后面到下一处之前跟着“不对、错了、离谱、太多了、改成、算了”这类话
    （“训练日不对”“1800 千卡太多了，改成 1600”“训练日，不对，是休息日”的训练日），
    只是带着“不、没、别”的要在同一个半句里（“训练日不算”）。“没错、不过、不用改”里的“不、没”
    不算。紧挨着下一处前面的否定词算那一处的（“是训练日，不是休息日”的“不是”说的是休息日）。"""
    text = language_normalize.simplified(language_normalize.fold(reply))
    text = _NOT_NO.sub(lambda found: " " * len(found.group()), text)
    order = sorted(range(len(spans)), key=lambda pos: spans[pos])
    heads = []  # 每一处紧挨着的否定词从哪里开始；没有为 None
    for rank, pos in enumerate(order):
        start = spans[pos][0]
        head = max(text.rfind(ch, 0, start) for ch in language_units.CLAUSE_END) + 1
        if rank:
            head = max(head, spans[order[rank - 1]][1])
        before = text[head:start]
        while before and language_normalize.kind(before[-1]) in "PZS":
            before = before[:-1]
        hit = _NOT_BEFORE.search(before)
        heads.append(head + hit.start() if hit else None)
    flags = [False] * len(spans)
    for rank, pos in enumerate(order):
        follow = order[rank + 1] if rank + 1 < len(order) else None
        stop = len(text) if follow is None else spans[follow][0]
        if follow is not None and heads[rank + 1] is not None:
            stop = heads[rank + 1]
        after = text[spans[pos][1] : stop]
        clause = _CLAUSE_TAIL.split(after)[0]
        flags[pos] = heads[rank] is not None or bool(
            _NOT_AFTER.search(after) or _NO_IN_CLAUSE.search(clause)
        )
    return flags
