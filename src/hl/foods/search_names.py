"""食品搜索候选、名称规范化和搜索层级。"""

from __future__ import annotations

import re
import weakref
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from hl.foods import lexicon, table
from hl.foods.concept_types import Index
from hl.foods.search_dry import is_dry
from hl.foods.table_types import View
from hl.language import normalize as language_normalize

SAVED, CONCEPT, RECIPE = "saved", "concept", "recipe"  # 用户库、概念、菜谱；另两层用 table 的前缀

KINDS = {
    SAVED: "用户库",
    CONCEPT: "概念",
    RECIPE: "菜谱",
    table.CN6: "成分表",
    table.BOOHEE: "薄荷库",
}

# 搜索：同一档里名字一样长时按四层的先后（增补第 1 节）
LAYERS = (SAVED, CONCEPT, RECIPE, table.CN6, table.BOOHEE)

# near 同分时的先后（第 9 节）：用户库、菜谱、薄荷库、成分表
NEAR_RANK = {SAVED: 0, RECIPE: 1, table.BOOHEE: 2, table.CN6: 3}

# 搜索的几档（第 9 节）：完全相同、别名包含、成分表主名包含、薄荷库名称包含、方括号里的别名；
# 剩下的（这个词包含名字、只在成分表圆括号的说明里出现）排最后。用户库的条目不论哪档都排最前
EXACT, ALIAS, MAIN, BOOHEE_NAME, BRACKET, OTHER = range(1, 7)

_CONTAINS = {CONCEPT: ALIAS, RECIPE: ALIAS, "main": MAIN, table.BOOHEE: BOOHEE_NAME}

_CONTAINS |= {"bracket": BRACKET, "full": OTHER, SAVED: OTHER}

# 成分表名称：主名（括号、方括号、逗号之前）和方括号里的别名（“牛肉（小腿肉）［牛展、牛腱子］”）
_MAIN_END = re.compile(r"[(\[【,]")

_BRACKETS = re.compile(r"\[([^\[\]]*)\]|【([^【】]*)】")

_ALIAS_SEP = re.compile(r"[,、/]")


@dataclass(frozen=True)
class Saved:
    """用户库里的一条，交给 search 和 near：名字、每 100 克的热量，或按量词存的（per 是“1碗”）
    这一份的热量。热量不知道的是 None。"""

    name: str
    kcal_100g: float | None = None
    per: str | None = None
    kcal_per: float | None = None


def from_library(library: Any, foods: View) -> list[Saved]:
    """用户库（foods/custom.py 的 Library）里能用的食物 → Saved：按量词存的（per 是“1碗”）
    记这一份的热量，按克、毫升存的折成每 100 的热量。热量算不出来的是 None，照样列出名字。"""
    found = []
    for entry in library.foods():
        kcal = entry.kcal(foods)
        per = entry.per
        if "unit" in per:
            found.append(Saved(entry.name, per=entry.per_shown, kcal_per=kcal))
        else:
            size = per.get("g") or per.get("ml") or 100
            found.append(Saved(entry.name, None if kcal is None else kcal * 100 / size))
    return found


# ---------- 别名换成概念名 ----------
@dataclass(frozen=True)
class _Words:
    words: dict[str, str]  # 概念级的叫法 → 概念名
    longest: int
    firsts: frozenset[str]  # 叫法的第一个字：别的字开头的位置不用试


_WORDS: weakref.WeakKeyDictionary[Index, _Words] = weakref.WeakKeyDictionary()


def _words(index: Index) -> _Words:
    built = _WORDS.get(index)
    if built is None:
        words = index.words
        longest = max((len(word) for word in words), default=0)
        built = _Words(words, longest, frozenset(word[0] for word in words))
        _WORDS[index] = built
    return built


def canonical(index: Index, text: str) -> str:
    """把别名换成概念名（“西红柿炒蛋”→“番茄炒蛋”）：从左往右，每处取最长的那个叫法。"""
    found = _words(index)
    out, pos = [], 0
    while pos < len(text):
        if text[pos] in found.firsts:
            for size in range(min(found.longest, len(text) - pos), 1, -1):
                word = text[pos : pos + size]
                if word in found.words:
                    out.append(found.words[word])
                    pos += size
                    break
            else:
                out.append(text[pos])
                pos += 1
        else:
            out.append(text[pos])
            pos += 1
    return "".join(out)


def _chars(index: Index, want: str) -> set[str]:
    """和 want 沾边的字：want 自己的，加上 want 里每个概念全部叫法的字（“番茄”也带出“西红柿”）。"""
    chars = set(want)
    named = set(index.words.values())
    for concept in (index.concepts[name] for name in named if name in want):
        chars |= {char for word in (*concept.aliases, *concept.net_aliases) for char in word}
    return chars


# ---------- 候选 ----------
@dataclass(frozen=True)
class _Candidate:
    """一层里的一条：layer、显示的名字、拿来比的名字（（角色，名字）），和怎么列出它。"""

    layer: str
    name: str
    names: tuple[tuple[str, str], ...]
    source: Any  # Saved、(Concept, 品种叫法 → 品种)、(编码, Food)
    dry: bool = False


def _cn6_names(name: str) -> tuple[tuple[str, str], ...]:
    """成分表名称拿来比的几种：主名、方括号里的别名、整个名称。"""
    clean = language_normalize.clean(name).strip()
    hit = _MAIN_END.search(clean)
    main = (clean[: hit.start()] if hit else clean).strip()
    found = [("main", main)]
    for group in _BRACKETS.findall(clean):
        for alias in _ALIAS_SEP.split("".join(group)):
            if alias.strip():
                found.append(("bracket", alias.strip()))
    if clean != main:
        found.append(("full", clean))
    return tuple(found)


def _food_words(index: Index) -> dict[str, list[tuple[str, str]]]:
    """概念和菜谱的食物名（词典里身份是食物名的词：别名、净重叫法、独立品种词）：
    概念名 → [（词，品种）]，概念别名的品种是空的。"""
    found: dict[str, list[tuple[str, str]]] = {}
    for word, entries in lexicon.entries(index).items():
        for entry in entries:
            if entry.kind == lexicon.FOOD and entry.concept in index.concepts:
                found.setdefault(entry.concept, []).append((word, entry.variant))
    return found


def _candidates(
    index: Index, foods: View, saved: Iterable[Saved], concepts: bool
) -> Iterator[_Candidate]:
    """四层的每一条，按用户库、概念和菜谱、成分表、薄荷库。热量未知的成分表、薄荷库条目
    填进 parts 也用不上，不列。concepts 为假时不列概念（near）。"""
    for entry in saved:
        yield _Candidate(SAVED, entry.name, ((SAVED, entry.name),), entry)
    words = _food_words(index)
    for concept in index.concepts.values():
        layer = RECIPE if concept.recipe else CONCEPT
        if layer == CONCEPT and not concepts:
            continue
        own = words.get(concept.name, [(concept.name, "")])
        names = tuple((layer, word) for word, _ in own)
        variants = {word: variant for word, variant in own if variant}
        yield _Candidate(layer, concept.name, names, (concept, variants))
    for code, food in foods.cn6.items():
        if food.kcal is not None:
            names = _cn6_names(food.name)
            yield _Candidate(table.CN6, food.name, names, (code, food), is_dry(food))
    for code, food in foods.boohee.items():
        if food.kcal is not None:
            name = language_normalize.clean(food.name).strip()
            source = (code, food)
            yield _Candidate(table.BOOHEE, food.name, ((table.BOOHEE, name),), source, is_dry(food))
