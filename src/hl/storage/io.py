"""原子文件读写、账本锁和本次写入集合。"""

from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

HIDDEN = ".hl"


PLAN_FILE = "plan.yaml"


DEFAULTS_FILE = "defaults.yaml"


DAY_KEYS = ("date", "day_type", "weight", "entries")


# 这一次调用（这把锁里）写过的文件：自动提交只提交它们，进锁时清空
_written: set[Path] = set()

# flock is process-level on some systems and a second handle can deadlock on others.
# Serialize threads (also protecting _written) and reuse the same lock in nested calls.
_process_lock = threading.RLock()
_held = threading.local()


# ---------- 原子读写 ----------
UNREADABLE = "读不出来：它是个目录，或者没有读的权限"


FIX_OS = (
    "这个位置上是个目录，或者引擎没有读写它的权限，引擎和 git 都修不了：把问题原样告诉用户，"
    "请用户看一下——是个目录就挪走它（先看看里面有没有要留的东西），没有权限就改好权限；"
    "你就此停下，不要自己改文件"
)


# 进不去的文件夹：要改的是它，不是里面的文件（改文件本身的权限照样报“没有权限”）
FIX_FOLDER = (
    "引擎打不开这个文件夹，引擎和 git 都修不了：把问题原样告诉用户，请用户看一下它——"
    "它应该是个文件夹，当前用户要能读、能进入、能写（多半是权限被改了，改回来就好）；"
    "你就此停下，不要自己改文件"
)


def folder_blocked(reason: str) -> str:
    return f"打不开这个文件夹（{reason}）：里面的每日记录读不了"


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    """先写同目录的临时文件再替换，读的一方永远看不到写了一半的文件。"""
    write_bytes(path, text.encode("utf-8"), mode)


def write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Atomic byte-preserving replacement, including transaction rollback images."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _written.add(path)


def read_yaml(path: Path) -> Any:
    """文件不存在返回 None；内容不是合法 YAML 时抛 yaml.YAMLError，读不了时抛 OSError。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return yaml.safe_load(text)


def write_yaml(path: Path, data: Any) -> None:
    text = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000
    )
    write_text(path, text)


@contextmanager
def locked(data_dir: Path) -> Iterator[None]:
    """同目录读写串行；同线程重入不重新开锁，也不清空外层的写入集合。"""
    with _lock(data_dir, blocking=True):
        yield


@contextmanager
def try_locked(data_dir: Path) -> Iterator[bool]:
    """拿得到锁就拿着（给出 True），别的进程拿着就不等（给出 False）。hl check 用：它不能等锁
    （自动提交在锁里触发 pre-commit，pre-commit 另起进程跑的就是 hl check）。"""
    with _lock(data_dir, blocking=False) as got:
        yield got


@contextmanager
def _lock(data_dir: Path, *, blocking: bool) -> Iterator[bool]:
    if not _process_lock.acquire(blocking=blocking):
        yield False
        return
    root = data_dir.absolute()
    held = getattr(_held, "roots", set())
    try:
        if root in held:
            yield True
            return
        path = root / HIDDEN / "lock"
        # Never lock a different ledger through an internal link.
        if any(p.is_symlink() for p in (root, path.parent, path)):
            raise OSError("数据目录、.hl 或 lock 不能是符号链接")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a", encoding="utf-8")  # noqa: SIM115
        except OSError:
            if blocking:
                raise
            yield False
            return
        with handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except OSError:
                if blocking:
                    raise
                yield False
                return
            held.add(root)
            _held.roots = held
            if len(held) == 1:
                _written.clear()
            try:
                yield True
            finally:
                held.remove(root)
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        _process_lock.release()
