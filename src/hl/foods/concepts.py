"""概念表与菜谱：数据模型和加载（设计说明 7.4，增补第 13.1 节），按名字查概念和品种。

同一个数据来源里还有认词用的两张表：lookalikes.yaml（不是同一种东西、中性词、停用字、泛称）和
cooking.yaml（做法词分档），只在这里读进来。按文字取词在 lexicon.py，覆盖检查（R3）在 match.py，
数据校验在 lint.py。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from hl.foods.concept_parse import CONCEPT_KEYS as CONCEPT_KEYS
from hl.foods.concept_parse import COOK_KEYS as COOK_KEYS
from hl.foods.concept_parse import COOK_KINDS as COOK_KINDS
from hl.foods.concept_parse import DISH_KEYS as DISH_KEYS
from hl.foods.concept_parse import LOOKALIKE_KEYS as LOOKALIKE_KEYS
from hl.foods.concept_parse import PART_KEYS as PART_KEYS
from hl.foods.concept_parse import TIERS as TIERS
from hl.foods.concept_parse import UNIT_AMOUNTS as UNIT_AMOUNTS
from hl.foods.concept_parse import UNIT_KEYS as UNIT_KEYS
from hl.foods.concept_parse import VARIANT_KEYS as VARIANT_KEYS
from hl.foods.concept_parse import _concept as _concept
from hl.foods.concept_parse import _cook as _cook
from hl.foods.concept_parse import _key as _key
from hl.foods.concept_parse import _Loader as _Loader
from hl.foods.concept_parse import _parts as _parts
from hl.foods.concept_parse import _Reader as _Reader
from hl.foods.concept_parse import _unique_keys as _unique_keys
from hl.foods.concept_parse import _unit as _unit
from hl.foods.concept_parse import _variant as _variant
from hl.foods.concept_types import Concept as Concept
from hl.foods.concept_types import Cook as Cook
from hl.foods.concept_types import DataError as DataError
from hl.foods.concept_types import Index as Index
from hl.foods.concept_types import Part as Part
from hl.foods.concept_types import Source as Source
from hl.foods.concept_types import Tables as Tables
from hl.foods.concept_types import Unit as Unit
from hl.foods.concept_types import Variant as Variant

FILES = ("concepts.yaml", "dishes.yaml")

# 认词用的表（增补第 13.1 节）：数据目录里可以不放，不放就用引擎自带的那份
TABLES = ("lookalikes.yaml", "cooking.yaml")

BUILTIN = resources.files("hl").joinpath("data")  # 引擎自带的那份

ENV = "HL_CONCEPTS"  # 测试用：指向放着 concepts.yaml 和 dishes.yaml 的目录


def _texts(source: Source) -> tuple[dict[str, str], list[str]]:
    """数据来源 → {文件名: 内容}。目录里要有 concepts.yaml 和 dishes.yaml；lookalikes.yaml、
    cooking.yaml 没放的，用引擎自带的那份。"""
    if source is None:
        raw = os.environ.get(ENV)
        source = Path(raw) if raw else BUILTIN
    if isinstance(source, Mapping):
        texts, problems = dict(source), []
    elif not source.is_dir():
        return {}, [f"{source}：不是一个目录（要放 {'、'.join(FILES)}）"]
    else:
        texts, problems = {}, []
        for name in (*FILES, *TABLES):
            path = source.joinpath(name)
            if path.is_file():
                texts[name] = path.read_text(encoding="utf-8")
            elif name in FILES:
                problems.append(f"{name}：{source} 里没有这个文件")
    for name in TABLES:
        if name not in texts:
            texts[name] = BUILTIN.joinpath(name).read_text(encoding="utf-8")
    return texts, problems


def describe(source: Source = None) -> str:
    """这份数据在哪，说给人听：引擎自带的，还是 HL_CONCEPTS 指的目录。"""
    if source is None and os.environ.get(ENV):
        return f"环境变量 {ENV} 指的 {os.environ[ENV]} 里的概念表和菜谱"
    return "引擎自带的概念表和菜谱" if source is None or source == BUILTIN else "概念表和菜谱"


def parse(source: Source = None) -> tuple[Index, list[str]]:
    """读概念表和菜谱，不抛错：返回（读得出来的条目，格式问题）。每条问题以“文件 条目名：”开头。

    source 是放着 concepts.yaml 和 dishes.yaml 的目录，或者 {文件名: 内容}；不给时用环境变量
    HL_CONCEPTS 指的目录（测试用），没设就用引擎自带的。数据之间对不对得上由 lint 查。
    """
    texts, problems = _texts(source)
    found: dict[str, Concept] = {}
    docs: dict[str, dict[Any, Any]] = {}
    for file, text in texts.items():
        try:
            doc = yaml.load(text, Loader=_Loader)  # _Loader 是 SafeLoader，只多查重复的键
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = f"第 {mark.line + 1} 行" if mark else ""
            problems.append(f"{file}：{line}不是合法的 YAML（{getattr(exc, 'problem', exc)}）")
            continue
        if doc is None:
            continue
        if not isinstance(doc, dict):
            what = "几节（not_same: …）" if file in TABLES else "（食物名: 内容）"
            problems.append(f"{file}：最外层要是一张表{what}")
            continue
        if file in TABLES:
            docs[file] = doc
            continue
        for name, raw in doc.items():
            if not isinstance(name, str) or not name.strip():
                problems.append(f"{file}：条目名“{name}”要是文字")
            elif name in found:
                problems.append(f"{file} {name}：和 {found[name].source} 里的条目重名")
            else:
                concept, wrong = _concept(name, file, raw)
                problems += wrong
                if concept is not None:
                    found[name] = concept
    tables, wrong = _tables(docs)
    return _index(found, tables), problems + wrong


def _tables(docs: dict[str, dict[Any, Any]]) -> tuple[Tables, list[str]]:
    """lookalikes.yaml 和 cooking.yaml 的内容 → Tables，顺手记下格式问题。"""
    looks = _Reader(TABLES[0])
    raw = docs.get(TABLES[0], {})
    looks.keys(raw, LOOKALIKE_KEYS)
    stop = raw.get("stop", "")
    if not isinstance(stop, str):
        looks.bad("stop 要写成一串字，例如 的了吃喝")
        stop = ""
    cooking = _Reader(TABLES[1])
    tables = Tables(
        not_same=looks.words(raw, "not_same"),
        neutral=_groups(looks, raw, "neutral", "{生熟依据词: [熟重, 生重]}"),
        stop="".join(dict.fromkeys(stop.replace(" ", ""))),
        generic=looks.words(raw, "generic"),
        methods=_groups(cooking, docs.get(TABLES[1], {}), "methods", "{加盐: [炖, 卤]}"),
    )
    wrong = [tier for tier in tables.methods if tier not in TIERS]
    if wrong:
        cooking.bad(f"methods 只分这几档：{'、'.join(TIERS)}，没有“{'、'.join(wrong)}”")
    return tables, [*looks.problems, *cooking.problems]


def _groups(
    reader: _Reader, raw: dict[Any, Any], key: str, example: str
) -> dict[str, tuple[str, ...]]:
    """按类写的一张表：类名 → 这一类的词。"""
    groups = {}
    for name, words in reader.table(raw, key, example).items():
        if not isinstance(name, str) or not name.strip():
            reader.bad(f"{key} 的类名“{name}”要是文字")
            continue
        groups[name.strip()] = reader.words({name: words}, name, key)
    return groups


def _index(found: dict[str, Concept], tables: Tables) -> Index:
    words = {word: c.name for c in found.values() for word in (*c.aliases, *c.net_aliases)}
    owners: dict[str, set[tuple[str, str]]] = {}
    for concept in found.values():
        for variant in concept.variants.values():
            for word in variant.words:
                owners.setdefault(word, set()).add((concept.name, variant.name))
    variant_words = {
        word: next(iter(hits))
        for word, hits in owners.items()
        if len(hits) == 1 and word not in words
    }
    return Index(found, words, variant_words, tables)


def load(source: Source = None) -> Index:
    """读概念表和菜谱（数据来源见 parse）。每次调用都重新读。格式不对抛 DataError。"""
    index, problems = parse(source)
    if problems:
        raise DataError(problems, describe(source))
    return index


def lookup(index: Index, text: str) -> tuple[Concept, str | None] | None:
    """一个食物名对应哪个概念；如果这个名字本身就是某个品种的叫法，连品种一起返回。"""
    if text in index.words:
        return index.concepts[index.words[text]], None
    if text in index.variant_words:
        concept_name, variant_name = index.variant_words[text]
        return index.concepts[concept_name], variant_name
    return None


def find_variant(concept: Concept, word: str) -> str | None:
    for variant in concept.variants.values():
        if word in variant.words:
            return variant.name
    return None


def units_for(concept: Concept | None) -> list[str]:
    """一种食物能按哪些单位记：概念表里的量词；不是菜的还能按克，有密度的还能按毫升。

    概念表里没有的食物（None）只能按克。
    """
    if concept is None:
        return ["g"]
    if concept.recipe:
        return list(concept.units)
    return [*concept.units, "g", *(["ml"] if concept.density else [])]


def references(index: Index) -> list[tuple[str, str, str]]:
    """概念表和菜谱引用的全部成分表编码：（数据文件，出处说明，编码）。"""
    found = []
    for concept in index.concepts.values():
        for variant in concept.variants.values():
            found.append((concept.source, f"{concept.name}／{variant.name}", variant.food))
        for part in concept.recipe:
            found.append((concept.source, f"{concept.name}的菜谱", part.food))
    return found
