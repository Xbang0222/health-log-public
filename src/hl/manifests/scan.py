"""从现有签名账本生成清单快照和可读摘要。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hl.manifests.model import (
    PARTS,
    _defaults,
    _entries,
    _note,
    _part_shown,
    _plan_shown,
    _signed_part,
    _signed_plans,
    _snapshot,
)
from hl.storage import days as storage_days
from hl.storage import io as storage_io


def _quiet(path: Path) -> Any:
    """读不出来的文件当作没有内容：清单只数签名有效的东西，坏文件留给读时校验去报。"""
    try:
        return storage_io.read_yaml(path)
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return None


def _adopted(data_dir: Path, key: bytes) -> dict[str, dict[str, Any]] | None:
    """清单还没记默认品种时，按现在的 defaults.yaml 补上的那一节；文件不在或是空的，补一节空的。

    文件里有一条过不了校验（或者读不出来），返回 None，先不补：只记好的那几条，用户照 fix 用 git
    恢复坏的那一条之后，它签名有效、清单里却没有，又被当成“退回了旧版本”，怎么修都修不好。
    等文件好了，之后哪一次写入再补。
    """
    try:
        defaults = storage_io.read_yaml(defaults_path(data_dir))
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return None
    if defaults is None:
        return {}
    signed = _defaults(key, defaults)
    return signed if isinstance(defaults, dict) and len(signed) == len(defaults) else None


def _scan(data_dir: Path, key: bytes) -> tuple[dict[str, Any], dict[tuple[str, ...], str]]:
    """按现有文件里签名有效的东西生成一份清单（还没签名），连同每一样在文件里是什么样子
    （键是（日期，记录 id）、（日期，weight／day_type）或（plan，签名），重建时说给用户听）。"""
    days: dict[str, Any] = {}
    looks: dict[tuple[str, ...], str] = {}
    # 和 hl check 一样不分大小写地找（08.YAML 也算那一天）；分大小写的文件系统上两个都在时用规范的
    chosen: dict[str, Path] = {}
    for path, day in storage_days.day_like_files(data_dir):
        if day not in chosen or path == storage_days.day_path(data_dir, day):
            chosen[day] = path
    for day, path in sorted(chosen.items()):
        doc = _quiet(path)
        if not isinstance(doc, dict) or doc.get("date") != day:
            continue
        _note(days, day, _snapshot(key, day, doc))
        for entry in _entries(doc):
            looks[(day, str(entry.get("id")))] = f"{entry.get('meal')}：{entry.get('said')}"
        for name, _ in PARTS:
            part = _signed_part(key, day, doc, name)
            if part:
                looks[(day, name)] = _part_shown(name, part)
    plans = _signed_plans(key, _quiet(data_dir / storage_io.PLAN_FILE))
    for plan in plans:
        looks[("plan", plan["sig"])] = _plan_shown(plan)
    return {"days": days, "plans": [plan["sig"] for plan in plans]}, looks


def build(data_dir: Path, key: bytes) -> dict[str, Any]:
    """按现有文件里签名有效的东西生成一份清单（还没签名）。默认品种不在这里：
    重建时另外记（preview），第一次写入时等文件好了再补（_editing）。"""
    return _scan(data_dir, key)[0]


def defaults_path(data_dir: Path) -> Path:
    return data_dir / storage_io.DEFAULTS_FILE
