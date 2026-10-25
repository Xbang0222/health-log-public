"""概念和菜谱条目的字段校验，以及严格 YAML 键读取。"""

from __future__ import annotations

import math
from collections.abc import Hashable
from typing import Any

import yaml

from hl.foods.concept_types import Concept, Cook, Part, Unit, Variant

LOOKALIKE_KEYS = ("not_same", "neutral", "stop", "generic")

# 做法词的四档（增补第 10 节）。cooking.yaml 里别的节（油盐比例、拆菜辅料）由用到它们的模块读
TIERS = ("不加", "加盐", "加油和盐", "另一种食物")

CONCEPT_KEYS = (
    "aliases", "default", "unsure", "units", "density", "cook", "variants",
    "net_aliases", "cuts", "lookalikes",
)  # fmt: skip

DISH_KEYS = ("aliases", "units", "recipe", "salt_g", "serving_g", "basis", "lookalikes")

VARIANT_KEYS = ("food", "names", "aliases", "cooked_product")

UNIT_AMOUNTS = ("g", "gross_g", "ml", "recipe")

UNIT_KEYS = (*UNIT_AMOUNTS, "variant", "rough")

COOK_KEYS = ("yield", "kind", "source")

COOK_KINDS = ("煮熟", "泡发")

PART_KEYS = ("food", "g", "note")


class _Loader(yaml.SafeLoader):
    """和 safe_load 一样，只是同一张表里键重复时报错（safe_load 会悄悄留下后一个）。"""


def _unique_keys(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> Any:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
        if isinstance(key, Hashable):
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"键“{key}”重复", key_node.start_mark
                )
            seen.add(key)
    return loader.construct_mapping(node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_keys)


class _Reader:
    """读一个条目，顺手记下格式问题：每条问题以“文件 条目名：”开头。"""

    def __init__(self, where: str) -> None:
        self.where = where
        self.problems: list[str] = []

    def bad(self, what: str) -> None:
        self.problems.append(f"{self.where}：{what}")

    def keys(self, raw: dict[Any, Any], allowed: tuple[str, ...], at: str = "") -> None:
        for key in raw:
            if key not in allowed:
                where = f"{at} 里" if at else ""
                self.bad(f"{where}不认识的键“{key}”（能用的：{'、'.join(allowed)}）")

    def words(self, raw: dict[Any, Any], key: str, at: str = "") -> tuple[str, ...]:
        value = raw.get(key)
        if value is None:
            return ()
        if not isinstance(value, list) or not all(isinstance(w, str) and w.strip() for w in value):
            self.bad(f"{_key(at, key)} 要写成一列文字，例如 [牛肉, 牛腩]")
            return ()
        return tuple(dict.fromkeys(w.strip() for w in value))

    def text(self, raw: dict[Any, Any], key: str, at: str = "") -> str | None:
        value = raw.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.bad(f"{_key(at, key)} 要写一段文字")
            return None
        return value.strip()

    def number(
        self, raw: dict[Any, Any], key: str, at: str = "", zero: bool = False
    ) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not ok or not math.isfinite(value) or value < 0 or (value == 0 and not zero):
            self.bad(f"{_key(at, key)} 要写一个{'不小于' if zero else '大于'} 0 的数")
            return None
        return value

    def flag(self, raw: dict[Any, Any], key: str, at: str = "") -> bool:
        value = raw.get(key, False)
        if not isinstance(value, bool):
            self.bad(f"{_key(at, key)} 只能写 true 或 false")
            return False
        return value

    def table(self, raw: dict[Any, Any], key: str, example: str) -> dict[Any, Any]:
        value = raw.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.bad(f"{key} 要写成一张表，例如 {example}")
            return {}
        return value

    def code(self, raw: dict[Any, Any], at: str) -> str:
        value = raw.get("food")
        if value is None:
            self.bad(f"{at} 要写 food（成分表编码）")
        elif not isinstance(value, str) or not value.strip():
            self.bad(f'{at}.food 要加引号写成文字（"082119"）：不加引号的数会丢掉开头的 0')
        else:
            return value.strip()
        return ""


def _key(at: str, key: str) -> str:
    return f"{at}.{key}" if at else key


def _unit(reader: _Reader, name: Any, raw: Any, dish: bool) -> Unit | None:
    at = f"units.{name}"
    if not isinstance(name, str) or not name.strip():
        reader.bad(f"量词“{name}”要是文字")
        return None
    if not isinstance(raw, dict):
        reader.bad(f"{at} 要写成一张表，例如 {{{'recipe: 1' if dish else 'g: 50'}}}")
        return None
    reader.keys(raw, UNIT_KEYS, at)
    amounts = {key: reader.number(raw, key, at) for key in UNIT_AMOUNTS if key in raw}
    want = ("recipe",) if dish else ("g", "gross_g", "ml")
    wrong = [key for key in amounts if key not in want]
    if wrong:
        why = "菜谱的量词只写 recipe（合几份配方）" if dish else "recipe 只有菜谱的量词才写"
        reader.bad(f"{at} 不能写 {'、'.join(wrong)}：{why}")
    elif len(amounts) != 1:
        reader.bad(f"{at} 要写且只写一个：{'、'.join(want)}")
    variant = reader.text(raw, "variant", at)
    if dish and variant is not None:
        reader.bad(f"{at} 不能写 variant：菜谱没有品种")
    return Unit(**amounts, variant=variant, rough=reader.flag(raw, "rough", at))


def _variant(reader: _Reader, name: Any, raw: Any) -> Variant | None:
    at = f"variants.{name}"
    if not isinstance(name, str) or not name.strip():
        reader.bad(f"品种名“{name}”要是文字")
        return None
    if not isinstance(raw, dict):
        reader.bad(f'{at} 要写成一张表，例如 {{food: "111101x"}}')
        return None
    reader.keys(raw, VARIANT_KEYS, at)
    return Variant(
        name=name.strip(),
        food=reader.code(raw, at),
        names=reader.words(raw, "names", at),
        aliases=reader.words(raw, "aliases", at),
        cooked_product=reader.flag(raw, "cooked_product", at),
    )


def _cook(reader: _Reader, raw: Any) -> Cook | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        reader.bad('cook 要写成一张表，例如 {yield: 0.7, kind: 煮熟, source: "…"}')
        return None
    reader.keys(raw, COOK_KEYS, "cook")
    ratio = reader.number(raw, "yield", "cook")
    if "yield" not in raw:
        reader.bad("cook 要写 yield（做熟或泡发后的重量 ÷ 原来的重量）")
    kind = raw.get("kind", COOK_KINDS[0])
    if kind not in COOK_KINDS:
        reader.bad(f"cook kind 只能是 {'、'.join(COOK_KINDS)}，不能是“{kind}”")
    source = raw.get("source")
    if ratio is None or kind not in COOK_KINDS:
        return None
    return Cook(ratio, kind, source.strip() if isinstance(source, str) and source.strip() else None)


def _parts(reader: _Reader, raw: Any) -> tuple[Part, ...]:
    if not isinstance(raw, list) or not raw:
        reader.bad('recipe 要列出至少一种原料，例如 [{food: "111101x", g: 50}]')
        return ()
    parts = []
    for pos, row in enumerate(raw):
        at = f"recipe[{pos}]"
        if not isinstance(row, dict):
            reader.bad(f'{at} 要写成 {{food: "111101x", g: 50}}')
            continue
        reader.keys(row, PART_KEYS, at)
        grams = reader.number(row, "g", at)
        if "g" not in row:
            reader.bad(f"{at} 要写 g（一份配方里的可食部生重）")
        parts.append(Part(reader.code(row, at), grams or 0, reader.text(row, "note", at)))
    return tuple(parts)


def _concept(name: str, source: str, raw: Any) -> tuple[Concept | None, list[str]]:
    """一个条目：有 recipe 的是菜谱，其余是概念。返回（读出来的条目，格式问题）。"""
    reader = _Reader(f"{source} {name}")
    if not isinstance(raw, dict):
        reader.bad("要写成一张表（aliases、variants 这些键）")
        return None, reader.problems
    dish = "recipe" in raw
    reader.keys(raw, DISH_KEYS if dish else CONCEPT_KEYS)
    units = {
        unit: spec
        for unit, item in reader.table(raw, "units", "{个: {g: 50}}").items()
        if (spec := _unit(reader, unit, item, dish)) is not None
    }
    variants = {
        variant.name: variant
        for key, item in reader.table(raw, "variants", '{普通: {food: "111101x"}}').items()
        if (variant := _variant(reader, key, item)) is not None
    }
    if not dish and not variants:
        reader.bad('variants 要列出至少一个品种，例如 {普通: {food: "111101x"}}')
    concept = Concept(
        name=name,
        source=source,
        aliases=tuple(dict.fromkeys((name, *reader.words(raw, "aliases")))),
        variants=variants,
        default=reader.text(raw, "default"),
        units=units,
        density=reader.number(raw, "density"),
        cook=_cook(reader, raw.get("cook")),
        recipe=_parts(reader, raw["recipe"]) if dish else (),
        unsure=reader.text(raw, "unsure"),
        net_aliases=reader.words(raw, "net_aliases"),
        cuts=reader.words(raw, "cuts"),
        lookalikes=reader.words(raw, "lookalikes"),
        salt_g=reader.number(raw, "salt_g", zero=True),
        serving_g=reader.number(raw, "serving_g"),
        basis=reader.text(raw, "basis"),
    )
    return (None if reader.problems else concept), reader.problems
