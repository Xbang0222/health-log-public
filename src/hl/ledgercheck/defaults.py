"""默认品种与建议文件的可信读取和有效性诊断。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl import budget, schema
from hl.foods.concept_types import Index
from hl.ledgercheck.defaults_repairs import _clear_with, _default_fix, _settle_fix
from hl.ledgercheck.messages import (
    DEFAULTS_FILE,
    FIX_CANDIDATE,
    FIX_SUGGEST,
    NEXT_DATA,
    NEXT_SUGGEST,
    WHOLE,
)
from hl.ledgercheck.reading import _or_os, _read
from hl.ledgercheck.recovery import _restorable
from hl.ledgercheck.repairs import _fix_defaults
from hl.ledgercheck.structure import defaults_problems
from hl.manifests import compare as manifests_compare
from hl.manifests import io as manifests_io
from hl.result import Abort, problem, rejected


def _known(index: Index, name: str, entry: dict[str, Any]) -> bool:
    concept = index.concepts.get(name)
    return concept is not None and entry["variant"] in concept.variants


def stale_defaults(index: Index, defaults: Any) -> list[str]:
    """引擎写的、但概念表里已经没有那种食物或那个品种的默认品种（引擎升级去掉了）：只提醒。
    每条是 hl check 的一条 warnings，带着去掉它的命令。"""
    if schema.errors("defaults", defaults):
        return []  # 结构不对，由读时校验去报
    return [
        f"{DEFAULTS_FILE}：默认品种“{name}：{entry['variant']}”在概念表里不存在。"
        f"概念表里已经没有这一项，这条默认品种用不上了。用户同意的话，{_clear_with(name)}"
        for name, entry in defaults.items()
        if not _known(index, name, entry)
    ]


def suggest_problems(index: Index, override: Any) -> list[tuple[str, str]]:
    """数据目录里 suggest.yaml 的全部问题，每个是（问题，改法）：结构、候选在概念表里存在。"""
    found = schema.errors("suggest", override)
    if found:
        return [(f"{err['where']}：{err['problem']}", err["fix"]) for err in found]
    problems = []
    for name in budget.CANDIDATES:
        for pos, candidate in enumerate(override.get(name, [])):
            concept = index.concepts.get(candidate["concept"])
            if concept is None or candidate["variant"] not in concept.variants:
                shown = f"{candidate['concept']}／{candidate['variant']}"
                problems.append((f"{name}[{pos}]：概念表里没有“{shown}”", FIX_CANDIDATE))
    return problems


def _defaults_file(data_dir: Path, key: bytes) -> tuple[Any, list[tuple[Any, str]]]:
    """默认品种文件的内容和它本身的问题，每个是（键，问题）；键是 WHOLE 的是整个文件的问题。"""
    defaults, unreadable = _read(data_dir / DEFAULTS_FILE)
    if unreadable or defaults is None:
        return defaults, [(WHOLE, text) for text in unreadable]
    return defaults, defaults_problems(key, defaults)


def read_defaults_file(data_dir: Path, key: bytes) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """读默认品种文件并检查，也和清单对照；文件不存在时没有默认品种。
    每个问题的改法都带着那一条的键（照 hl check 显示的写法），命令照抄就能用。"""
    defaults, found = _defaults_file(data_dir, key)
    git = _restorable(data_dir, key, DEFAULTS_FILE)
    errors = [
        problem(DEFAULTS_FILE, text, _or_os(text, lambda n=name: _default_fix(n, git())))
        for name, text in found
    ]
    if any(name is WHOLE for name, _ in found):
        return {}, errors  # 整个文件坏了：先不和清单对照，不然条条都“不见了”，改法还对不上
    listed, _ = manifests_io.read(data_dir, key)  # 清单自己的问题由调用方去报
    for name, text, kind in manifests_compare.defaults_gaps(listed, key, defaults):
        fix = _settle_fix(name, kind, git() if kind != "extra" else False)
        errors.append(problem(DEFAULTS_FILE, text, fix))
    return defaults if isinstance(defaults, dict) else {}, errors


def broken_defaults(data_dir: Path, key: bytes) -> list[dict[str, str]]:
    """整个 defaults.yaml 的问题（读不出来、不是一张表）。hl default 用：这时只改一条写回去，
    别的默认品种就一起没了，写不成的先说出来，不先问用户（R5）。"""
    _, found = _defaults_file(data_dir, key)
    whole = [text for name, text in found if name is WHOLE]
    if not whole:
        return []
    git = _restorable(data_dir, key, DEFAULTS_FILE)
    return [
        problem(DEFAULTS_FILE, text, _or_os(text, lambda: _fix_defaults(git()))) for text in whole
    ]


def read_suggest_file(data_dir: Path, index: Index) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """“可以吃什么”的候选和上限：数据目录的 suggest.yaml 按键盖在引擎自带的上面（第 8 节）。

    返回（合并后的配置，{where, problem, fix} 列表）；有问题时配置就是引擎自带的。
    这个文件由用户自己写，没有签名；写错了是数据问题，不是引擎出错。
    """
    conf = budget.builtin_suggest()
    override, unreadable = _read(data_dir / budget.SUGGEST_FILE)
    if override is None and not unreadable:
        return conf, []
    found = [(text, "先把它改成一个合法的 YAML 文件") for text in unreadable]
    found = found or suggest_problems(index, override)
    if found:
        return conf, [
            problem(budget.SUGGEST_FILE, text, f"{fix}。{FIX_SUGGEST}") for text, fix in found
        ]
    return {**conf, **override}, []


def load_suggest(data_dir: Path, index: Index) -> dict[str, Any]:
    """hl today 用：suggest.yaml 有问题就拒绝，说明哪一处不对、怎么改。"""
    conf, errors = read_suggest_file(data_dir, index)
    if errors:
        raise Abort(rejected(errors, NEXT_SUGGEST))
    return conf


def load_defaults(data_dir: Path, key: bytes, index: Index) -> dict[str, str]:
    """用户设定的默认品种（概念名 → 品种名）。校验不过就拒绝：不按来路不明的默认品种记。

    概念表里已经没有的（stale_defaults）用不上，跳过，不拦着记别的。
    """
    defaults, errors = read_defaults_file(data_dir, key)
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
    return {
        name: entry["variant"] for name, entry in defaults.items() if _known(index, name, entry)
    }
