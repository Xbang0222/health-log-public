"""全库不可读文件巡检和清单重建前置检查。"""

from __future__ import annotations

from pathlib import Path

from hl.foods.table_types import Table
from hl.ledgercheck.days import read_day_file
from hl.ledgercheck.defaults import broken_defaults
from hl.ledgercheck.messages import DEFAULTS_FILE, PLAN_FILE
from hl.ledgercheck.paths import _blocked, _cannot_open, _odd, unopened
from hl.ledgercheck.plans import read_plan_file
from hl.ledgercheck.reading import _read
from hl.ledgercheck.structure import _whole_day
from hl.manifests import io as manifests_io
from hl.manifests import model as manifests_model
from hl.result import problem
from hl.storage import days as storage_days
from hl.storage import io as storage_io


def unreadable_ledger(data_dir: Path, key: bytes) -> list[dict[str, str]]:
    """hl manifest rebuild 用：账本里读不了、或者认不出是哪一天的（R15、R21）。重建只数读得出来、
    名字认得出的东西，别的当成空的，确认后就从清单里划掉了；权限、名字改回来，那些记录又成了
    “清单里没有的”。所以有这些就不重建，也不先问用户：log/ 下的符号链接、打不开的文件夹，
    名字不规范的文件（08.yml、“08 (1).yaml”，和 08.yaml 只差大小写、两个都在的 08.YAML；
    只差大小写、规范名字的不在的认得出是哪一天，不算），每日文件（连同清单里记着的日子，
    照规范的路径）、计划、默认品种的位置上是个目录或没有权限；没有可以对照的清单（丢了、读不出来、
    验签不过、还没建过）时，还有整份读不进来的（_unscanned）：清单在的，重建前会把少了的逐条
    说给用户，由用户决定，hl check 对它们给的改法里也有这一条。说法和 hl check 报的一样。"""
    scan = storage_days.scan_log(data_dir)
    errors = unopened(data_dir, scan)
    errors += [
        error for error, counted in (_odd(data_dir, path) for path in scan.odd) if not counted
    ]
    listed, _ = manifests_io.read(data_dir, key)
    days = {
        *scan.days,
        *(storage_days.day_path(data_dir, day) for day in (listed or {}).get("days", {})),
    }
    for path in sorted(days):
        folder = storage_days.blocked(data_dir, path)
        if folder is not None:  # 文件本身打不开，要改的却是它所在的文件夹：指到那个文件夹
            errors.append(_blocked(data_dir, folder, "没有权限"))
        elif _cannot_open(path):
            where = path.relative_to(data_dir).as_posix()
            errors.append(problem(where, storage_io.UNREADABLE, storage_io.FIX_OS))
    for name in (PLAN_FILE, DEFAULTS_FILE):
        if _cannot_open(data_dir / name):
            errors.append(problem(name, storage_io.UNREADABLE, storage_io.FIX_OS))
    if not errors and listed is None:  # 先报读不了的：文件夹进不去时连列也列不全
        errors = _unscanned(data_dir, key)
    return list({(error["where"], error["problem"]): error for error in errors}.values())


def _unscanned(data_dir: Path, key: bytes) -> list[dict[str, str]]:
    """整份读不进来的账本文件（第十轮 I-3）：每日文件不是合法的 YAML、不是一张表（空的也算）、
    日期和路径对不上、记录不是列表，计划不是合法的 YAML、不是列表，默认品种不是合法的 YAML、
    不是一张表。重建会把它们当成空的：那一天、那几版计划、那些默认品种就从清单里漏了，照 fix 用
    git 取回之后又成了“清单里没有的”。和读不了的一样先请用户处理，报的是 hl check 对这个文件
    报的那几条（取回、或者停下）。读不了的（是个目录、没有权限）上面已经报了，这里不再读。"""
    errors = []
    chosen: dict[str, Path] = {}  # 和 manifest._scan 挑的一样：两个都在时用规范名字的
    for path, day in storage_days.day_like_files(data_dir):
        if day not in chosen or path == storage_days.day_path(data_dir, day):
            chosen[day] = path
    for day, path in sorted(chosen.items()):
        doc, unreadable = _read(path)
        if unreadable == [storage_io.UNREADABLE] or (not unreadable and _whole_day(doc, day)):
            continue
        errors += read_day_file(data_dir, key, None, path)[1]
    plans, unreadable = _read(data_dir / PLAN_FILE)
    if unreadable != [storage_io.UNREADABLE] and (
        unreadable or not isinstance(plans, (list, type(None)))
    ):
        errors += read_plan_file(data_dir, key)[1]
    return errors + [
        error
        for error in broken_defaults(data_dir, key)
        if error["problem"] != storage_io.UNREADABLE
    ]


def wait_to_rebuild(
    data_dir: Path, key: bytes, errors: list[dict[str, str]]
) -> list[dict[str, str]]:
    """hl check 用：清单要重建（丢了、读不出来、验签不过），同时又有 hl manifest rebuild 会因此
    拒绝的（读不了的文件或文件夹、名字认不出是哪一天的、整份读不进来的，unreadable_ledger）：
    两条 fix 打架，清单这一条改成先停下，等那几条处理好。只在清单要重建时才去查。"""
    if not any(error["fix"] == manifests_model.FIX_LOST for error in errors):
        return errors
    if not unreadable_ledger(data_dir, key):
        return errors
    later = manifests_model.FIX_LOST_LATER
    return [
        {**error, "fix": later} if error["fix"] == manifests_model.FIX_LOST else error
        for error in errors
    ]


def listed_days(
    data_dir: Path, key: bytes, table: Table | None, scan: storage_days.LogScan
) -> list[dict[str, str]]:
    """hl check 用：清单里记着、走 log/ 时没读到的日子，按规范的路径读一遍（R21）：
    文件不见了，或在符号链接、打不开的文件夹后面。换了大小写的不再读，那一条已经说了怎么改回来。"""
    listed, _ = manifests_io.read(data_dir, key)
    walked = set(scan.days) | {storage_days.canonical_twin(data_dir, path) for path in scan.odd}
    errors = []
    for day in (listed or {}).get("days", {}):
        path = storage_days.day_path(data_dir, day)
        if path not in walked:
            errors += read_day_file(data_dir, key, table, path)[1]
    return errors
