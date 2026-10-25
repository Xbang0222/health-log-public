"""每日账本的可信读取与历史体重投影。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl.foods.table_types import Table
from hl.ledgercheck.messages import NEXT_DATA, Checked
from hl.ledgercheck.paths import _blocked, misnamed
from hl.ledgercheck.reading import _or_os, _read, _require_manifest, _settled
from hl.ledgercheck.recovery import _restorable
from hl.ledgercheck.repairs import _restore_only
from hl.ledgercheck.structure import _structure, _structure_fix, day_problems
from hl.manifests import compare as manifests_compare
from hl.manifests import io as manifests_io
from hl.manifests import model as manifests_model
from hl.result import Abort, problem, rejected
from hl.storage import days as storage_days


def _day_file(data_dir: Path, key: bytes, table: Table | None, path: Path) -> Checked:
    """先读清单，再读每日文件。文件不存在时内容是 None，只看清单里记没记着这一天。"""
    day = storage_days.day_of(data_dir, path)
    where = path.relative_to(data_dir).as_posix()
    listed, _ = manifests_io.read(data_dir, key)
    git = _restorable(data_dir, key, where, table)
    if not path.exists():
        gaps = manifests_compare.day_gaps(listed, day, None, False)
        return None, [], [(text, manifests_model.fix_gone(where, git())) for text in gaps]
    doc, unreadable = _read(path)
    problems = [(text, _or_os(text, lambda: _restore_only(where, git()))) for text in unreadable]
    if not unreadable:
        problems = day_problems(key, table, day, doc, where, git)
    gaps = [
        (text, manifests_model.fix_gone(where, git()))
        for text in manifests_compare.day_gaps(listed, day, doc)
    ]
    return doc, problems, gaps + manifests_compare.day_extras(listed, key, day, doc)


def read_day_file(
    data_dir: Path, key: bytes, table: Table | None, path: Path
) -> tuple[Any, list[dict[str, str]]]:
    """读 log/ 下的一个文件，检查并对照清单，返回（内容，{where, problem, fix} 列表）。

    文件不存在时内容是 None；清单里记着这一天有东西，就是一个问题。
    """
    folder = storage_days.blocked(data_dir, path)
    if folder is not None:  # 打开文件报“没有权限”，要改的却是它所在的文件夹：指到那个文件夹
        return None, [_blocked(data_dir, folder, "没有权限")]
    odd = storage_days.misnamed(path)
    if odd is not None:  # 名字只差大小写：两种文件系统上都先请用户改回来，不读它、不往里写
        return None, [misnamed(data_dir, odd)]
    where = path.relative_to(data_dir).as_posix()
    doc, problems, gaps = _settled(lambda: _day_file(data_dir, key, table, path))
    return doc, [problem(where, text, fix) for text, fix in problems + gaps]


def day_for_undo(
    data_dir: Path, key: bytes, path: Path
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """hl undo 用：读这一天的文件，看撤销做不做得了（R18）。返回（内容，问题）。

    撤销是修复手段，不验签、不查每条记录的结构：被改坏的、手写的记录也要能删掉。整个文件坏了
    （读不出来、空的、没有记录列表），或者清单里记着的东西不见了、换成了别的，就删不了：
    问题和改法和 hl check 给的一样（R15）。文件里多出来、清单里没记着的不算：撤掉它正是那一条
    的改法。文件不在、清单里也没记着这一天，是空的一天。调用方攥着锁，不用 _settled 重读。
    名字只差大小写（08.YAML）的，和 read_day_file 一样先请用户改回来，不往里写（R21）。
    """
    folder = storage_days.blocked(data_dir, path)
    if folder is not None:
        return None, [_blocked(data_dir, folder, "没有权限")]
    odd = storage_days.misnamed(path)
    if odd is not None:
        return None, [misnamed(data_dir, odd)]
    day = storage_days.day_of(data_dir, path)
    where = path.relative_to(data_dir).as_posix()
    listed, _ = manifests_io.read(data_dir, key)
    git = _restorable(data_dir, key, where)
    if not path.exists():
        gaps = manifests_compare.day_gaps(listed, day, None, False)
        return storage_days.new_day(day), [
            problem(where, t, manifests_model.fix_gone(where, git())) for t in gaps
        ]
    doc, unreadable = _read(path)
    if unreadable:
        fix = _or_os(unreadable[0], lambda: _restore_only(where, git()))
        return None, [problem(where, text, fix) for text in unreadable]
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
        broken = _structure("day", doc)
        fixes = [_structure_fix(where, day, doc, at, git) for at, _ in broken]
        return None, [
            problem(where, f"结构不对（{text}）", fix)
            for (_, text), fix in zip(broken, fixes, strict=True)
        ]
    gaps = manifests_compare.day_gaps(listed, day, doc)
    return doc, [problem(where, text, manifests_model.fix_gone(where, git())) for text in gaps]


def load_day(data_dir: Path, key: bytes, table: Table | None, day: str) -> dict[str, Any]:
    """读某一天的记录；不存在时给一份空的。

    任何一项校验不过、或对不上清单就拒绝，提示运行 hl check。
    """
    _require_manifest(data_dir, key)
    doc, errors = read_day_file(data_dir, key, table, storage_days.day_path(data_dir, day))
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
    return storage_days.new_day(day) if doc is None else doc


def load_weight_history(data_dir: Path, key: bytes, day: str) -> float | None:
    """R16 回看用：只读可信的历史体重，不依赖当天饮食、日类型是否完整。

    文件仍须可读、日期正确；体重复用每日结构/验签规则，清单仍双向对照。丢失、
    回退或多出来的体重不能跳过。当前日的写入仍须 load_day 完整校验；这里不写任何历史文件。
    """
    listed, errors = manifests_io.read(data_dir, key)
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
    path = storage_days.day_path(data_dir, day)
    folder = storage_days.blocked(data_dir, path)
    if folder is not None:
        raise Abort(rejected([_blocked(data_dir, folder, "没有权限")], NEXT_DATA))
    odd = storage_days.misnamed(path)
    if odd is not None:
        raise Abort(rejected([misnamed(data_dir, odd)], NEXT_DATA))
    where = path.relative_to(data_dir).as_posix()
    git = _restorable(data_dir, key, where)  # 提议恢复整份文件时，仍核对全部内容
    wanted = (listed or {}).get("days", {}).get(day, {}).get("weight")
    days = {day: {"entries": {}, "weight": wanted, "day_type": None}} if wanted else {}
    scoped = {"days": days} if listed is not None else None
    exists = path.exists()
    doc, unreadable = _read(path)
    if isinstance(doc, dict):
        doc = {
            "date": doc.get("date"),
            "entries": [],
            **({"weight": doc["weight"]} if "weight" in doc else {}),
        }
    found = [(text, _or_os(text, lambda: _restore_only(where, git()))) for text in unreadable]
    if exists and not unreadable:
        found += day_problems(key, None, day, doc, where, git)
    found += [
        (text, manifests_model.fix_gone(where, git()))
        for text in manifests_compare.day_gaps(scoped, day, doc, exists)
    ]
    found += manifests_compare.day_extras(scoped, key, day, doc)
    if found:
        raise Abort(rejected([problem(where, text, fix) for text, fix in found], NEXT_DATA))
    return doc["weight"]["kg"] if isinstance(doc, dict) and "weight" in doc else None
