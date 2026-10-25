"""每日日志路径、目录巡检、记录编号和原话重合判断。"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from hl.language import normalize as language_normalize
from hl.storage.io import DAY_KEYS, write_yaml


# ---------- 每日文件 ----------
def day_path(data_dir: Path, day: str) -> Path:
    year, month, dom = day.split("-")
    return data_dir / "log" / year / month / f"{dom}.yaml"


DAY_NAME = re.compile(r"(\d{4})/(\d{2})/(\d{2})\.yaml")  # 相对 log/ 的规范写法，扩展名小写


def _day_name(relative: str) -> bool:
    """相对 log/ 的路径是不是规范的每日文件名：YYYY/MM/DD.yaml，而且是个真的日期。"""
    hit = DAY_NAME.fullmatch(relative)
    if hit is None:
        return False
    try:
        date.fromisoformat("-".join(hit.groups()))
    except ValueError:
        return False
    return True


# 系统自己在文件夹里放的文件（Finder、Windows 资源管理器）：不是用户放的，移走了下次打开又生成
SYSTEM_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


def _system_file(name: str) -> bool:
    """.DS_Store、._08.yaml（macOS 在别的文件系统上给每个文件配的“._”副本）、Thumbs.db 这类。"""
    return name.casefold() in SYSTEM_FILES or name.startswith("._")


@dataclass
class LogScan:
    """走一遍 log/ 看到的东西，各自按路径排序。

    days 是名字规范的每日文件，是符号链接的也在（读的时候跟进去，内容照样查）；odd 是名字
    不规范的文件，符号链接不在里面；links 是符号链接（git 只记下链接本身，遍历也不跟进）；
    blocked 是打不开的文件夹和原因。"""

    days: list[Path] = field(default_factory=list)
    odd: list[Path] = field(default_factory=list)
    links: list[Path] = field(default_factory=list)
    blocked: list[tuple[Path, str]] = field(default_factory=list)


def scan_log(data_dir: Path) -> LogScan:
    """log/ 下的每一项都看（R21）。不按扩展名、不按大小写筛：macOS 上 08.YAML 打开的就是
    08.yaml，只找小写的 .yaml 会把它漏掉。写到一半的临时文件（.名字.随机.tmp）和系统自己放的
    文件（.DS_Store 这类）不算。打不开的文件夹记下来接着走，不中断，也不悄悄跳过。"""
    log = data_dir / "log"
    found = LogScan()
    if log.is_symlink():
        found.links.append(log)
        return found

    def unopened(exc: OSError) -> None:
        if not isinstance(exc, FileNotFoundError):  # 走的时候刚被删掉的不算
            reason = "没有权限" if isinstance(exc, PermissionError) else exc.strerror or str(exc)
            found.blocked.append((Path(exc.filename), reason))

    for folder, folders, files in os.walk(log, onerror=unopened):
        for name, is_dir in [*((n, True) for n in folders), *((n, False) for n in files)]:
            if not is_dir and (
                name.startswith(".") and name.endswith(".tmp") or _system_file(name)
            ):
                continue
            path = Path(folder) / name
            link = os.path.islink(path)
            if link:  # 是文件夹的，os.walk 不跟进去，里面的每日文件就漏了
                found.links.append(path)
            if _day_name(path.relative_to(log).as_posix()):
                found.days.append(path)  # 位置上是个目录的也在里面：读的时候报它读不了
            # 符号链接只报它是链接，不另说名字不规范，免得两种改法打架
            elif not is_dir and not link:
                found.odd.append(path)
    for paths in (found.days, found.odd, found.links):
        paths.sort()
    found.blocked.sort()
    return found


def day_files(data_dir: Path) -> list[Path]:
    """log/ 下名字规范的每日文件，按路径排序。位置上是个目录的也在里面：读的时候报它读不了。"""
    return scan_log(data_dir).days


def blocked(data_dir: Path, path: Path) -> Path | None:
    """从数据目录往下到 path 所在的文件夹，第一个进不去的（没有权限）；都进得去返回 None。
    这时打开 path 报的是“没有权限”，可要改权限的是这个文件夹，不是 path 本身。"""
    folder = data_dir
    for part in path.relative_to(data_dir).parent.parts:
        folder = folder / part
        if not folder.is_dir():  # 上一层进得去，这里 stat 不会因为权限出错
            return None
        if not os.access(folder, os.X_OK):
            return folder
    return None


def day_like_files(data_dir: Path) -> list[tuple[Path, str]]:
    """log/ 下名字不分大小写算是每日文件的（08.yaml，也有 08.YAML），连同它是哪一天，按路径排序。
    重建清单、核对密钥都按它找：只找规范名字的，会漏掉换了大小写的那一天，和 hl check 对不上。"""
    log = data_dir / "log"
    scan = scan_log(data_dir)
    found = [
        (path, day_of(data_dir, path))
        for path in [*scan.days, *scan.odd]
        if not path.is_dir() and _day_name(path.relative_to(log).as_posix().lower())
    ]
    return sorted(found)


def canonical_twin(data_dir: Path, path: Path) -> Path | None:
    """名字和规范写法只差大小写的每日文件（08.YAML）：返回规范名字的那个路径（08.yaml）。
    只看名字，不看文件系统分不分大小写：两种文件系统上说的是同一件事（R21）。"""
    relative = path.relative_to(data_dir / "log").as_posix()
    if _day_name(relative) or not _day_name(relative.lower()):
        return None
    return data_dir / "log" / relative.lower()


def _names(folder: Path) -> list[str]:
    """文件夹里各项的名字，照磁盘上存的写法（不分大小写的文件系统上也是）；读不了是空的。"""
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def misnamed(path: Path) -> Path | None:
    """规范名字的每日文件（08.yaml）不在，同一个文件夹里有个名字只差大小写的文件（08.YAML）：
    返回它。不分大小写的文件系统上打开 08.yaml 读到的就是它，分大小写的读不到；两边都按
    “名字不对”说，请用户改回来，不往里写（R21）。"""
    names = _names(path.parent)
    if path.name in names:
        return None
    for name in names:
        if name.lower() == path.name.lower() and not (path.parent / name).is_dir():
            return path.parent / name
    return None


def day_of(data_dir: Path, path: Path) -> str:
    """每日文件的路径对应的日期：log/2026/10/08.yaml 是 2026-10-08。"""
    return "-".join(path.relative_to(data_dir / "log").with_suffix("").parts)


def new_day(day: str) -> dict[str, Any]:
    return {"date": day, "entries": []}


def save_day(data_dir: Path, doc: Mapping[str, Any]) -> None:
    ordered = {key: doc[key] for key in DAY_KEYS if key in doc}
    write_yaml(day_path(data_dir, doc["date"]), ordered)


def entry_key(day: str, meal: str, said: str) -> str:
    """记录的存档键：sha1(日期 | 餐次 | 归一化的原话)。只写进记录，R11 查重不看它。"""
    return hashlib.sha1(f"{day}|{meal}|{language_normalize.compact(said)}".encode()).hexdigest()[
        :10
    ]


_NUMERAL = frozenset("0123456789零〇一二两三四五六七八九十百千万")


_NUMBER_GLUE = _NUMERAL | {".", "点"}


def _inside(part: str, whole: str) -> bool:
    """part 整个出现在 whole 里，而且没有把一个数切开：“50克”不在“150克”里，“2个”不在“12个”里。"""
    start = whole.find(part)
    while start >= 0:
        end = start + len(part)
        head = start > 0 and part[0] in _NUMERAL and whole[start - 1] in _NUMBER_GLUE
        tail = end < len(whole) and part[-1] in _NUMERAL and whole[end] in _NUMBER_GLUE
        if not head and not tail:
            return True
        start = whole.find(part, start + 1)
    return False


def overlapping(doc: Mapping[str, Any], said: str) -> list[dict[str, Any]]:
    """R11：这一天里原话和这句话重合的记录。

    归一化之后相同算重合；一句包含另一句也算（模型重试时少抄或多抄了半句），
    但包含的地方不能把一个数切开。
    """
    new = language_normalize.compact(said)
    olds = [(entry, language_normalize.compact(entry["said"])) for entry in doc["entries"]]
    return [entry for entry, old in olds if old and (_inside(old, new) or _inside(new, old))]


def next_entry_id(doc: Mapping[str, Any]) -> str:
    numbers = [int(entry["id"][1:]) for entry in doc["entries"]]
    return f"e{max(numbers, default=0) + 1}"
