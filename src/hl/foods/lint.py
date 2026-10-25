"""概念表和菜谱的数据校验（增补第 13.4 节）：hl check 和开发时的测试共用这一份。

concepts.parse 只管读不读得进来（格式）；这里查读进来的条目之间、条目和成分表之间对不对得上。
errors 是必须改的问题，warnings 只是提醒。每条以“文件 条目名：”开头。"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Iterator

from hl.foods import concepts
from hl.foods.concept_types import Concept, Index, Source, Tables
from hl.foods.lint_names import _PLACE as _PLACE
from hl.foods.lint_names import TAIL_FORMS as TAIL_FORMS
from hl.foods.lint_names import _clash as _clash
from hl.foods.lint_names import _identities as _identities
from hl.foods.lint_names import _table_words as _table_words
from hl.foods.lint_names import _tails as _tails
from hl.foods.table_types import Table
from hl.language import normalize as language_normalize

# 第 5 节的门槛：各品种每 100 克的热量比值超过 RATIO、并且相差超过 KCAL_GAP 千卡，或者蛋白质、
# 脂肪、碳水任一项比值超过 RATIO、并且相差超过 GRAMS_GAP 克，就不许有默认品种，必须问
RATIO = 1.2

KCAL_GAP = 10

GRAMS_GAP = 10

NUTRIENTS = (
    ("热量", "kcal", KCAL_GAP, "千卡"),
    ("蛋白质", "protein", GRAMS_GAP, "克"),
    ("脂肪", "fat", GRAMS_GAP, "克"),
    ("碳水", "carb", GRAMS_GAP, "克"),
)

# 一份成品的重量 ÷ 配方原料克数之和：带汤的面、吸了水的饺子皮会重一些，炸过、烤过的会轻一些；
# 不到一半、超过四倍的多半是写错了
SERVING_RANGE = (0.5, 4.0)

UNIT_SLACK = 0.02  # 菜谱里的克数和整个、半个差多少还算对得上（按克数的比例）

# 量出来的量词（勺、碗、杯这类，按名字里的字认）：配方里写几克油、几克米饭不用凑成整勺整碗，
# 菜谱只核对个、根、只这类论个数的
MEASURED = "勺匙杯碗盒瓶罐听袋包盘碟份两斤升"

GENERIC_UNITS = ("g", "克", "公克", "kg", "公斤", "千克", "ml", "毫升", "l", "升", "斤")  # 第 6 节

COUNT_UNITS = ("个", "根", "颗", "串", "把")

# 按整个吃的：水果 06、蛋 11、薯类 021、根菜 041、茄果瓜菜 043、薯芋 047（成分表编码的开头）
WHOLE_FOODS = ("06", "11", "021", "041", "043", "047")


def errors(source: Source = None, foods: Table | None = None, *, missing: bool = True) -> list[str]:
    """一份概念表和菜谱（数据来源见 concepts.parse）的全部问题：读不进来的，加上 check 查出来的。"""
    index, problems = concepts.parse(source)
    return [*problems, *check(index, foods, missing=missing)]


def check(index: Index, foods: Table | None = None, *, missing: bool = True) -> list[str]:
    """读进来的条目之间、条目和成分表之间对不对得上。

    foods 不给时不查和成分表有关的几条；missing 为 False 时不报成分表里没有的编码
    （hl check 把它算成成分表副本的问题另外报，见 R21）。
    """
    owners = _owners(index)
    found = []
    for concept in index.concepts.values():
        what = [*_lengths(concept), *_units(concept)]
        if concept.recipe:
            what += _dish(concept, owners, foods, missing)
        else:
            what += _pointers(concept)
            what += _must_ask(concept, foods)
            what += _cook(concept, index.tables)
            if foods is not None:
                rows = ((f"{concept.name}／{v.name}", v.food) for v in concept.variants.values())
                what += _codes(rows, foods, missing)
        found += [f"{concept.source} {concept.name}：{text}" for text in what]
    return [*found, *_table_words(index.tables), *_identities(index), *_tails(index)]


def warnings(source: Source = None) -> list[str]:
    """只提醒、不算错的：水果、蛋、整个吃的蔬菜没有按个数说的量词（第 13.4 节）。"""
    index, _ = concepts.parse(source)
    found = []
    for concept in index.concepts.values():
        variant = concept.variants.get(concept.default or "") or next(
            iter(concept.variants.values()), None
        )
        if variant is None or not variant.food.startswith(WHOLE_FOODS):
            continue
        if not any(unit in concept.units for unit in COUNT_UNITS):
            found.append(
                f"{concept.source} {concept.name}：整个吃的东西没有按个数说的量词"
                f"（{'、'.join(COUNT_UNITS)} 之一），用户说“一个”时只能追问克数"
            )
    return found


# —— 每个条目自己 ——


def _lengths(concept: Concept) -> Iterator[str]:
    """别名、品种名和各种叫法至少两个字（第 13.1 节）；cuts 是切法字，不算。"""
    words = [*concept.aliases, *concept.net_aliases, *concept.lookalikes]
    words += [word for variant in concept.variants.values() for word in variant.words]
    for word in dict.fromkeys(words):
        if len(word) < 2:
            yield f"“{word}”只有一个字：别名、品种名和各种叫法至少两个字，单字太容易出现在别的词里"


def _units(concept: Concept) -> Iterator[str]:
    for name, unit in concept.units.items():
        if name.lower() in GENERIC_UNITS:
            yield f"量词“{name}”是通用单位（增补第 6 节），引擎自己会换算，不要写成自己的量词"
        elif name == "两" and not unit.rough:
            yield (
                "量词“两”要标 rough: true：说的是食堂口径的二两，不是称出来的 50 克（增补第 6 节）"
            )
        if unit.ml is not None and concept.density is None:
            yield f"units.{name} 按毫升写，要有 density（每毫升多少克）才换得成克"


def _pointers(concept: Concept) -> Iterator[str]:
    """default、unsure、量词里的 variant 指向存在的品种。"""
    named = [("default", concept.default), ("unsure", concept.unsure)]
    named += [(f"units.{name}.variant", unit.variant) for name, unit in concept.units.items()]
    have = "、".join(concept.variants)
    for key, variant in named:
        if variant is not None and variant not in concept.variants:
            yield f"{key} “{variant}”不是{concept.name}的品种（有：{have}）"


def _codes(rows: Iterable[tuple[str, str]], foods: Table, missing: bool) -> Iterator[str]:
    """每个编码都在成分表里，热量已知。"""
    for label, code in rows:
        food = foods.get(code)
        if food is None:
            if missing:
                yield f"{label}的编码“{code}”不在成分表里"
        elif food.kcal is None:
            yield f"{label}的编码“{code}”（{food.name}）热量未知：换一个有热量的条目"


def _spread(concept: Concept, foods: Table) -> tuple[bool, str] | None:
    """各品种每 100 克差多少：（超没超第 5 节的门槛，算出来的数）。编码缺了、热量未知的另外报。"""
    rows = [foods.get(variant.food) for variant in concept.variants.values()]
    if not rows or any(row is None or row.kcal is None for row in rows):
        return None
    over, said = False, []
    for label, field, gap, unit in NUTRIENTS:
        values = [value for row in rows if (value := getattr(row, field)) is not None]
        if len(values) < 2:
            continue
        low, high = min(values), max(values)
        ratio = high / low if low > 0 else (math.inf if high > 0 else 1.0)
        hit = ratio > RATIO and high - low > gap
        over = over or hit
        if field == "kcal" or hit:
            shown = "无穷大" if math.isinf(ratio) else f"{ratio:.2f}"
            said.append(
                f"{label} {language_normalize.fmt(low)}–{language_normalize.fmt(high)} {unit}"
                f"（比值 {shown}，相差 {language_normalize.fmt(round(high - low, 1))}）"
            )
    return over, "、".join(said)


def _must_ask(concept: Concept, foods: Table | None) -> Iterator[str]:
    """没有默认品种 ⇔ 超过第 5 节的门槛；没有默认品种的要写 unsure。"""
    if concept.default is None and concept.unsure is None:
        yield (
            "没有 default（不问就用的品种），就要写 unsure：用户说不清是哪种时用的品种，"
            "指向最常见的那种（增补第 5 节）"
        )
    spread = _spread(concept, foods) if foods is not None else None
    if spread is None:
        return
    over, said = spread
    gate = f"增补第 5 节的门槛（比值超过 {RATIO}，且相差超过 {KCAL_GAP} 千卡或 {GRAMS_GAP} 克）"
    if over and concept.default is not None:
        yield f"各品种每 100 克{said}，超过{gate}，不能写 default：去掉它，让引擎问用户是哪种"
    elif not over and concept.default is None:
        why = f"各品种每 100 克{said}，没超过{gate}" if said else "只有一个品种"
        yield f"{why}，要写 default（不问就用的品种）"


def _says_state(word: str, kind: str, tables: Tables) -> bool:
    """品种叫法说的是不是生熟（泡发）状态：熟的、生牛肉、干木耳。"""
    marks = (*tables.neutral.get("生熟依据词", ()), *tables.neutral.get("泡发依据词", ()))
    if any(mark in word for mark in marks):
        return True
    if "熟" in word or word.startswith("生"):
        return True
    return kind == "泡发" and (word.startswith("干") or "泡" in word)


def _cook(concept: Concept, tables: Tables) -> Iterator[str]:
    cook = concept.cook
    if cook is None:
        return
    if cook.source is None:
        yield "cook 要写 source：yield 是从哪里来的"
    if cook.kind == "泡发" and cook.ratio <= 1:
        yield (
            "cook 是泡发，yield 要大于 1（泡发后比干的时候重），"
            f"现在是 {language_normalize.fmt(cook.ratio)}"
        )
    for variant in concept.variants.values():
        word = next((w for w in variant.words if _says_state(w, cook.kind, tables)), None)
        if word is not None and not variant.cooked_product:
            yield (
                f"品种“{variant.name}”的叫法“{word}”说的是生熟或泡发状态，和 cook 说的是同一件事"
                "（增补第 7 节）：去掉这个品种，或者标 cooked_product: true（做好的成品）"
            )


# —— 菜谱 ——


def _owners(index: Index) -> dict[str, Concept]:
    """编码 → 用到它的第一个概念（不算菜谱）。"""
    owners: dict[str, Concept] = {}
    for concept in index.concepts.values():
        if not concept.recipe:
            for variant in concept.variants.values():
                owners.setdefault(variant.food, concept)
    return owners


def _sizes(concept: Concept, code: str, foods: Table | None) -> dict[str, float]:
    """这个编码按概念论个数的量词，一个合多少克可食部。按整重写的要用成分表的可食部。"""
    variant = next((v.name for v in concept.variants.values() if v.food == code), None)
    sizes = {}
    for name, unit in concept.units.items():
        if unit.variant not in (None, variant) or any(char in MEASURED for char in name):
            continue
        food = foods.get(code) if foods is not None else None
        if unit.g is not None:
            sizes[name] = unit.g
        elif unit.gross_g is not None and food is not None:
            sizes[name] = unit.gross_g * (100 if food.edible is None else food.edible) / 100
        elif unit.ml is not None and concept.density is not None:
            sizes[name] = unit.ml * concept.density
    return sizes


def _whole(grams: float, sizes: Collection[float]) -> bool:
    """克数是不是整个或半个的倍数（至少半个）。"""
    for size in sizes:
        halves = round(grams / (size / 2))
        if halves >= 1 and abs(grams - halves * size / 2) <= UNIT_SLACK * grams:
            return True
    return False


def _dish(
    dish: Concept, owners: dict[str, Concept], foods: Table | None, missing: bool
) -> Iterator[str]:
    if dish.salt_g is None:
        yield "菜谱要写 salt_g：一份配方折合多少克盐，可以是 0（增补第 11 节）"
    if not dish.units:
        yield "菜谱要写至少一个量词，例如 units: {份: {recipe: 1}}"
    total = sum(part.g for part in dish.recipe)
    if dish.serving_g is not None and total > 0:
        low, high = SERVING_RANGE
        ratio = dish.serving_g / total
        if not low <= ratio <= high:
            yield (
                f"serving_g {language_normalize.fmt(dish.serving_g)} 克是配方原料合计"
                f" {language_normalize.fmt(total)} 克的 {ratio:.2f} 倍，"
                f"不在 {low} 到 {high} 倍之间，多半写错了"
            )
    if foods is not None:
        rows = ((f"{dish.name}的菜谱 recipe[{pos}]", p.food) for pos, p in enumerate(dish.recipe))
        yield from _codes(rows, foods, missing)
    for pos, part in enumerate(dish.recipe):
        owner = owners.get(part.food)
        sizes = _sizes(owner, part.food, foods) if owner is not None else {}
        if not sizes or _whole(part.g, sizes.values()):
            continue
        said = " ".join(text for text in (dish.basis, part.note) if text)
        if owner is None or any(alias in said for alias in owner.aliases):
            continue
        shown = "、".join(
            f"一{name} {language_normalize.fmt(round(g, 1))} 克" for name, g in sizes.items()
        )
        yield (
            f"recipe[{pos}] 的 {language_normalize.fmt(part.g)} 克{owner.name}"
            f"对不上它的量词（{shown}）："
            "按整个或半个写，或者在 basis、note 里说明为什么是这个数"
        )


# —— 一个词只有一种身份（第 2.1 节） ——
