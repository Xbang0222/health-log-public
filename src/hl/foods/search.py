"""在四层库里找条目（增补第 9 节）：hl food search 的搜索，和估算通道给模型列的 near。

四层：用户库（交进来的是 Saved）、概念和菜谱（Index）、成分表和薄荷库（合并视图 View）。
- search：名字或别名包含这个词、或这个词包含名字（至少两个字）；概念的别名互相通用。按第 9 节
  的几档排，几个词要都对得上。
- near：估算通道（第 8.1 节）列给模型的相近条目，最多五条，单独排：名字整个包含 text 的在前，
  其余按共有的字数排；干品和粉排在后面。概念不进 near（它们在 unknown 的 ingredients 里）。
两边列出的每一条字段一样（_shown），ref 可以直接填进 estimate.parts[].food。

dry（干品、冲调前的粉）也在这里定，“用到且超过 100 克时提醒”的话由 dry_note 给出：兜底按薄荷库
记的（fallback）用它，估算通道按 parts 记下的行交给 dry_notes。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from hl.foods.concept_types import Index
from hl.foods.search_dry import DRY_NOTE_G as DRY_NOTE_G
from hl.foods.search_dry import DRY_WATER as DRY_WATER
from hl.foods.search_dry import dry_note as dry_note
from hl.foods.search_dry import dry_notes as dry_notes
from hl.foods.search_dry import is_dry as is_dry
from hl.foods.search_names import _ALIAS_SEP as _ALIAS_SEP
from hl.foods.search_names import _BRACKETS as _BRACKETS
from hl.foods.search_names import _CONTAINS as _CONTAINS
from hl.foods.search_names import _MAIN_END as _MAIN_END
from hl.foods.search_names import _WORDS as _WORDS
from hl.foods.search_names import ALIAS as ALIAS
from hl.foods.search_names import BOOHEE_NAME as BOOHEE_NAME
from hl.foods.search_names import BRACKET as BRACKET
from hl.foods.search_names import CONCEPT as CONCEPT
from hl.foods.search_names import EXACT as EXACT
from hl.foods.search_names import KINDS as KINDS
from hl.foods.search_names import LAYERS as LAYERS
from hl.foods.search_names import MAIN as MAIN
from hl.foods.search_names import NEAR_RANK as NEAR_RANK
from hl.foods.search_names import OTHER as OTHER
from hl.foods.search_names import RECIPE as RECIPE
from hl.foods.search_names import SAVED as SAVED
from hl.foods.search_names import Saved as Saved
from hl.foods.search_names import _Candidate as _Candidate
from hl.foods.search_names import _candidates as _candidates
from hl.foods.search_names import _chars as _chars
from hl.foods.search_names import _cn6_names as _cn6_names
from hl.foods.search_names import _food_words as _food_words
from hl.foods.search_names import _Words as _Words
from hl.foods.search_names import _words as _words
from hl.foods.search_names import canonical as canonical
from hl.foods.search_names import from_library as from_library
from hl.foods.search_view import _concept as _concept
from hl.foods.search_view import _kcal as _kcal
from hl.foods.search_view import _known as _known
from hl.foods.search_view import _number as _number
from hl.foods.search_view import _recipe as _recipe
from hl.foods.search_view import _shown as _shown
from hl.foods.search_view import _table_entry as _table_entry
from hl.foods.search_view import _units as _units
from hl.foods.search_view import entry_itself as entry_itself
from hl.foods.search_view import ingredients as ingredients
from hl.foods.search_view import itself as itself
from hl.foods.table_types import View
from hl.language import normalize as language_normalize

LIMIT = 5  # near 最多几条（第 9 节）

SEARCH_LIMIT = 10  # hl food search 不给 --limit 时最多列几条


# ---------- 搜索 ----------
def _tier(want: str, candidate: _Candidate, plain: list[str]) -> tuple[int, str] | None:
    """一个词对上这一条的哪一档（第 9 节），和对上的是哪个品种的叫法；对不上是 None。
    plain 是 candidate.names 里每个名字换成概念名之后的样子。"""
    best: tuple[int, str] | None = None
    variants = candidate.source[1] if candidate.layer in (CONCEPT, RECIPE) else {}
    for (role, name), name_plain in zip(candidate.names, plain, strict=True):
        if name_plain == want:
            tier = EXACT
        elif want in name_plain:
            tier = _CONTAINS[role]
        elif len(name) >= 2 and name_plain in want and role != "full":
            tier = OTHER
        else:
            continue
        found = (tier, variants.get(name, ""))
        if best is None or found < best:
            best = found
    return best


def search(
    index: Index,
    foods: View,
    words: list[str],
    saved: Iterable[Saved] = (),
    limit: int = SEARCH_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """hl food search：四层里和这几个词都对得上的条目，按第 9 节排好，最多 limit 条；
    另返回一共对上了几条。

    对得上：名字或别名包含这个词，或这个词包含名字（名字至少两个字）；两边都先把别名换成
    概念名，所以概念的别名互相通用。排序：用户库的最前；然后按档（完全相同、别名包含、
    成分表主名包含、薄荷库名称包含、方括号里的别名、其余），几个词取最差的那一档；
    同一档里名字短的在前，一样长的按四层的先后。
    """
    wants = [canonical(index, language_normalize.clean(word).strip()) for word in words]
    wants = [want for want in wants if want]
    if not wants:
        return [], 0
    ranked: list[tuple[tuple[Any, ...], _Candidate, str]] = []
    for candidate in _candidates(index, foods, saved, concepts=True):
        plain = [canonical(index, name) for _, name in candidate.names]
        hits = []
        for want in wants:
            hit = _tier(want, candidate, plain)
            if hit is None:
                break
            hits.append(hit)
        else:
            tier = 0 if candidate.layer == SAVED else max(tier for tier, _ in hits)
            variant = next((variant for _, variant in hits if variant), "")
            key = (tier, len(candidate.name), LAYERS.index(candidate.layer), candidate.name)
            ranked.append((key, candidate, variant))
    ranked.sort(key=lambda found: found[0])
    shown = [_shown(candidate, foods, variant or None) for _, candidate, variant in ranked[:limit]]
    return shown, len(ranked)


# ---------- near ----------
def _score(want: str, name: str) -> float:
    """共有的字数 ÷ 两边合起来的字数。"""
    shared = sum((Counter(want) & Counter(name)).values())
    return shared / (len(want) + len(name))


def near(
    index: Index, foods: View, text: str, saved: Iterable[Saved] = (), limit: int = LIMIT
) -> list[dict[str, Any]]:
    """库里和 text 相近的条目（第 9 节 near 的排法），最多 limit 条；字段和 search 的一样。

    先把两边的别名换成概念名；名字整个包含 text 的排最前，其余按“共有的字数 ÷ 两边合起来的
    字数”从高到低；同一档里干品和粉排在非干品后面；同分时按用户库、菜谱、薄荷库、成分表，
    再按名字短的在前。一个字都不共有的不列。用户库、菜谱、薄荷库、成分表四层，概念不列。
    """
    want = canonical(index, language_normalize.clean(text).strip())
    if not want:
        return []
    chars = _chars(index, want)
    best: dict[int, tuple[tuple[Any, ...], _Candidate]] = {}
    for pos, candidate in enumerate(_candidates(index, foods, saved, concepts=False)):
        for _, name in candidate.names:  # 成分表的主名、方括号里的别名、整个名称取最好的
            if not chars & set(name):
                continue
            plain = canonical(index, language_normalize.clean(name).strip())
            score = _score(want, plain)
            if score <= 0:
                continue
            rank = NEAR_RANK[candidate.layer]
            key = (want not in plain, candidate.dry, -score, rank, len(candidate.name), pos)
            if pos not in best or key < best[pos][0]:
                best[pos] = (key, candidate)
    ranked = sorted(best.values(), key=lambda found: found[0])
    return [_shown(candidate, foods) for _, candidate in ranked[:limit]]
