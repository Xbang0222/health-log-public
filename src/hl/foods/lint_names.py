"""检查概念词典的身份冲突、名字长度和名字尾巴。"""

from __future__ import annotations

from hl.foods import concepts, lexicon
from hl.foods.concept_types import Index, Tables
from hl.foods.lexicon_types import COOKING, FOOD, NEUTRAL, NOT_SAME, Entry

# 尾巴回归的固定句式（第 13.4 节）
TAIL_FORMS = ("{}大概两个", "{}大约200克", "{}只吃了一半", "{}中午吃了一个", "{}称了200克")

_PLACE = (NEUTRAL, COOKING)  # 只占位置、不要求对应项的词


def _clash(a: Entry, b: Entry) -> bool:
    """同一个词的两种身份能不能并存。"""
    if a.kind in _PLACE and b.kind in _PLACE:
        return False  # 依据词同时是做法词之类，都只占位置
    if a.kind in _PLACE or b.kind in _PLACE:
        other = b if a.kind in _PLACE else a
        return other.kind in (FOOD, NOT_SAME)  # 修饰词可以同时是依据词（面条的“熟重”）
    if NOT_SAME in (a.kind, b.kind):
        return a.kind != b.kind  # 两处都列成“不是同一种东西”的不算撞
    if a.concept != b.concept:
        return FOOD in (a.kind, b.kind)  # 几个概念共用的修饰词（脱脂）不算撞
    if a.variant and b.variant:
        return a.variant != b.variant  # 同一个概念的两个品种
    # 概念别名和本概念的品种叫法相同不算撞（鸡胸肉的“鸡胸”，第 5 节）；别名和净重叫法相同算撞
    return not (a.variant or b.variant)


def _identities(index: Index) -> list[str]:
    found = []
    for word, marks in lexicon.entries(index).items():
        involved = [
            mark
            for pos, mark in enumerate(marks)
            if any(_clash(mark, other) for at, other in enumerate(marks) if at != pos)
        ]
        if involved:
            where = next(mark.where for mark in reversed(involved) if mark.where)
            labels = "，又是".join(mark.label for mark in involved)
            found.append(f"{where}：“{word}”既是{labels}：一个词只能有一种身份（增补第 2.1 节）")
    return found


# —— 尾巴回归（第 2.3 节） ——


def _tails(index: Index) -> list[str]:
    """每个概念别名、净重叫法、菜谱别名套进固定句式，用引擎自己的取词和尾巴规则认一遍：
    要正好认出它自己，后面不能有尾巴。"""
    lex = lexicon.lexicon(index)
    found = []
    for word, name in index.words.items():
        concept = index.concepts[name]
        for form in TAIL_FORMS:
            said = form.format(word)
            got = lexicon.mentions(lex, said)
            first = got[0] if got else None
            if first and first.start == 0 and first.words[0].end == len(word) < first.end:
                tail = said[len(word) : first.end]
                why = f"里的“{tail}”是尾巴，会被认成另一种食物“{first.name}”"
            elif [(m.start, m.end, m.concept) for m in got] != [(0, len(word), name)]:
                seen = "、".join(f"“{m.name}”（{m.concept or '另一种食物'}）" for m in got)
                why = f"认不出“{word}”：取词取到的是 {seen or '空的'}"
            else:
                continue
            found.append(f"{concept.source} {concept.name}：“{said}”{why}（增补第 2.3 节）")
            break
    return found


def _table_words(tables: Tables) -> list[str]:
    """lookalikes.yaml 里不是同一种东西的词也至少两个字。"""
    why = "至少两个字，单字太容易出现在别的词里"
    return [
        f"{concepts.TABLES[0]}：not_same 里的“{word}”只有一个字：{why}"
        for word in tables.not_same
        if len(word) < 2
    ]
