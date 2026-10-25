"""从概念构建词典，并选择覆盖原话的分词结果。"""

from __future__ import annotations

import weakref

from hl.foods import concepts
from hl.foods.concept_types import Index
from hl.foods.lexicon_types import (
    COOKING,
    FOOD,
    MAX_READINGS,
    MODIFIER,
    NEUTRAL,
    NOT_SAME,
    SAVED_FILE,
    SHARED_NEUTRAL,
    Entry,
    Lexicon,
    Token,
    Word,
)


def entries(index: Index) -> dict[str, list[Entry]]:
    """词典里的每个词和它的全部身份。一个词有几种身份时由数据校验报错（lint.py）。

    品种叫法写在 names 里的，和包含本概念别名的（全脂牛奶、土鸡蛋），单说也是食物名，带出品种；
    其余的品种叫法是修饰词。概念的 lookalikes 和 lookalikes.yaml 的 not_same 并在一起。
    """
    found: dict[str, list[Entry]] = {}

    def add(word: str, entry: Entry) -> None:
        if entry not in found.setdefault(word, []):
            found[word].append(entry)

    tables = index.tables
    for label, words in {**tables.neutral, **SHARED_NEUTRAL}.items():
        for word in words:
            add(word, Entry(NEUTRAL, label, concepts.TABLES[0] if label in tables.neutral else ""))
    for tier, words in tables.methods.items():
        for word in words:
            add(word, Entry(COOKING, f"做法词（{tier}）", concepts.TABLES[1], tier=tier))
    for word in tables.not_same:
        add(word, Entry(NOT_SAME, f"{concepts.TABLES[0]} 列的不是同一种东西", concepts.TABLES[0]))
    for word in tables.saved:  # 用户库的名字整个算另一种食物（“牛肉酸辣粉”不再认成牛肉）
        add(word, Entry(NOT_SAME, "用户库里存的食物", SAVED_FILE))
    for c in index.concepts.values():
        where = f"{c.source} {c.name}"
        alias = f"菜谱{c.name}的别名" if c.recipe else f"{c.name}的别名"
        for word in c.aliases:
            add(word, Entry(FOOD, alias, where, c.name))
        for word in c.net_aliases:
            add(word, Entry(FOOD, f"{c.name}的净重叫法", where, c.name))
        for word in c.lookalikes:
            add(word, Entry(NOT_SAME, f"{c.name}列的不是同一种东西", where, c.name))
        for v in c.variants.values():
            for word in v.words:
                own = word in v.names or any(a != word and a in word for a in c.aliases)
                label = f"{c.name}／{v.name}的{'独立品种词' if own else '叫法'}"
                add(word, Entry(FOOD if own else MODIFIER, label, where, c.name, v.name))
    return found


_ORDER = (FOOD, NOT_SAME, COOKING, NEUTRAL, MODIFIER)

_BUILT: weakref.WeakKeyDictionary[Index, Lexicon] = weakref.WeakKeyDictionary()


def _identity(found: list[Entry]) -> Word:
    """一个词有几种身份时（数据校验报错，用户库的名字除外）取词只认一种：食物名优先，
    概念别名优先于品种叫法（鸡胸肉的“鸡胸”）。"""
    best = min(found, key=lambda entry: (_ORDER.index(entry.kind), entry.variant != ""))
    if best.kind == FOOD:
        return Word(FOOD, best.concept, best.variant or None, best.label)
    if best.kind == COOKING:
        return Word(COOKING, label=best.tier)
    return Word(best.kind if best.kind == NOT_SAME else NEUTRAL, label=best.label)


def lexicon(index: Index) -> Lexicon:
    """这份概念表的词典。同一个 Index 只建一次。"""
    built = _BUILT.get(index)
    if built is None:
        words = {word: _identity(found) for word, found in entries(index).items()}
        cuts = {concept.name: concept.cuts for concept in index.concepts.values()}
        units = (u for concept in index.concepts.values() for u in concept.units)
        longest = max(map(len, words), default=1)
        built = Lexicon(words, index.tables.stop, cuts, tuple(dict.fromkeys(units)), longest)
        _BUILT[index] = built
    return built


def _options(lex: Lexicon, text: str) -> list[list[int]]:
    """每个位置起头的词各到哪里结束，长的在前。"""
    n = len(text)
    return [
        [
            at + size
            for size in range(min(lex.longest, n - at), 0, -1)
            if text[at : at + size] in lex.words
        ]
        for at in range(n)
    ]


def readings(lex: Lexicon, text: str, limit: int = MAX_READINGS) -> list[list[Token]]:
    """取词：在所有互不重叠的取法里，取盖住字数最多的，字数相同取词数少的（增补第 2.2 节）。

    仍然并列的几种都返回（最多 limit 种），按从左数第一个词起得早、更长的排在前面
    （“牛肉干核桃”先给 牛肉干＋核桃，再给 牛肉＋干核桃）：第一种是引擎默认的取法。
    """
    options = _options(lex, text)
    n = len(text)
    best = [(0, 0)] * (n + 1)  # 从这个位置到末尾最好的（盖住的字数，−词数）
    for at in range(n - 1, -1, -1):
        score = best[at + 1]
        for end in options[at]:
            covered, count = best[end]
            score = max(score, (covered + end - at, count - 1))
        best[at] = score
    found: list[tuple[tuple[int, int], ...]] = []
    stack: list[tuple[int, tuple[tuple[int, int], ...]]] = [(0, ())]
    while stack and len(found) < limit:  # 按字典序走遍并列最好的取法：先取词、长的先，再跳过
        at, taken = stack.pop()
        if at == n:
            found.append(taken)
            continue
        ahead = []
        for end in options[at]:
            covered, count = best[end]
            if (covered + end - at, count - 1) == best[at]:
                ahead.append((end, (*taken, (at, end))))
        if best[at + 1] == best[at]:
            ahead.append((at + 1, taken))
        stack.extend(reversed(ahead))
    return [[_token(lex, text, start, end) for start, end in taken] for taken in found]


def _token(lex: Lexicon, text: str, start: int, end: int) -> Token:
    word = lex.words[text[start:end]]
    return Token(start, end, text[start:end], word.kind, word.concept, word.variant, word.label)


def tokens(lex: Lexicon, text: str) -> list[Token]:
    """引擎默认的那种取法（见 readings）。"""
    return readings(lex, text, 1)[0]
