"""账本路径阻塞、符号链接和非规范文件名诊断。"""

from __future__ import annotations

import os
from pathlib import Path

from hl.foods.table_types import Table
from hl.ledgercheck.messages import FIX_LINK, FIX_STRAY, HALT
from hl.result import problem
from hl.storage import days as storage_days
from hl.storage import io as storage_io


def _blocked(data_dir: Path, folder: Path, reason: str) -> dict[str, str]:
    return problem(
        folder.relative_to(data_dir).as_posix(),
        storage_io.folder_blocked(reason),
        storage_io.FIX_FOLDER,
    )


def misnamed(data_dir: Path, odd: Path) -> dict[str, str]:
    """名字和规范写法只差大小写的每日文件（08.YAML）。hl check 和读这一天的命令说的一样（R21）。

    不给 git：不分大小写的文件系统上，git 认为 08.yaml 没变，checkout 什么都不做，名字改不回来；
    分大小写的文件系统上，它会另外生成一个 08.yaml。请用户把名字改回来，给出确切的命令。
    """
    where = odd.relative_to(data_dir).as_posix()
    name = where.lower()
    fix = (
        f"这是每日文件，只是名字的大小写和规范的写法不一样：把问题告诉用户，请用户把它的名字改回 "
        f"{name}（在数据目录里运行 mv {where} {name}；用 git 恢复改不回名字），"
        f"改完再运行 hl check；你{HALT}"
    )
    return problem(where, f"文件名的大小写和规范的写法 {name} 不一样", fix)


def _both_fix(where: str, name: str) -> str:
    """分大小写的文件系统上，08.YAML 和 08.yaml 两个都在：留哪份只有用户知道。"""
    return (
        f"它和每日文件 {name} 的名字只差大小写，两个文件都在：把问题告诉用户，请用户看看要留哪份。"
        f"不要它，就把它移出 log/；要它不要 {name}，就先把 {name} 移出 log/，再把它改名成 {name}。"
        f"改完再运行 hl check；你{HALT}"
    )


def _link(data_dir: Path, path: Path) -> dict[str, str]:
    where = path.relative_to(data_dir).as_posix()
    target = os.readlink(path)
    if not os.path.exists(path):  # os.path 的这两个碰到进不去的地方回 False，不抛错，检查不中断
        what = f"是个符号链接，指向的 {target} 不存在（或者打不开）"
    else:
        what = (
            f"是个符号链接（指向 {target}），不是真的{'文件夹' if os.path.isdir(path) else '文件'}"
        )
    return problem(where, what, FIX_LINK)


def unopened(data_dir: Path, scan: storage_days.LogScan) -> list[dict[str, str]]:
    """hl check 用：log/ 下的符号链接和打不开的文件夹（R21）。走的时候进不去它们，
    里面有什么不知道，单独报出来，不当它们是空的。"""
    return [_link(data_dir, path) for path in scan.links] + [
        _blocked(data_dir, folder, reason) for folder, reason in scan.blocked
    ]


def _cannot_open(path: Path) -> bool:
    """打不开来读：位置上是个目录、没有读的权限。不见了不算：那是删掉了，重建时照常说会少。"""
    try:
        with path.open("rb"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def odd_files(
    data_dir: Path, key: bytes, table: Table | None, scan: storage_days.LogScan
) -> list[dict[str, str]]:
    """hl check 用：log/ 下名字不规范的文件（R21）。换了大小写的每日文件单独说规范的名字。
    只看名字，不看文件系统分不分大小写，两种文件系统上报的一样。（key、table 现在用不上了。）"""
    return [_odd(data_dir, path)[0] for path in scan.odd]


def _odd(data_dir: Path, path: Path) -> tuple[dict[str, str], bool]:
    """log/ 下名字不规范的一个文件：（问题，重建清单认不认得出它是哪一天）。"""
    where = path.relative_to(data_dir).as_posix()
    twin = storage_days.canonical_twin(data_dir, path)
    if twin is None:
        return problem(where, "不是规范的每日文件名（log/YYYY/MM/DD.yaml）", FIX_STRAY), False
    if storage_days.misnamed(twin) == path:
        return misnamed(data_dir, path), True
    name = twin.relative_to(data_dir).as_posix()
    what = f"文件名和每日文件 {name} 只差大小写"
    return problem(where, what, _both_fix(where, name)), False
