"""Durable multi-file rollback under the ledger lock.

The caller validates existing data before entering and validates its result before
leaving. Readers must take the same lock and call recover before loading data.
A signed before-image is durable before the first write; removing it is commit.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from hl.result import Abort, error
from hl.storage import io, keys

FILE = ".hl/transaction.json"
COMMON_PATHS = (
    "hl.toml",
    "plan.yaml",
    "defaults.yaml",
    "foods/custom.yaml",
    ".hl/manifest.json",
    ".hl/intents.json",
    ".hl/recorded.json",
    "AGENTS.md",
    "CLAUDE.md",
    "HEALTH_LOG_V2.md",
    ".gitignore",
    ".claude/settings.json",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".githooks/pre-commit",
)
_active = threading.local()


def _fail(message: str) -> Abort:
    return Abort(
        error(
            f"事务恢复未完成：{message}。未继续读写账本。",
            "保留整个数据目录及 .hl/transaction.json，从完整备份恢复或诊断；不要删除日志或重签数据",
        )
    )


def _allowed(relative: str) -> bool:
    if relative in COMMON_PATHS:
        return True
    hit = re.fullmatch(r"log/(\d{4})/(\d{2})/(\d{2})\.yaml", relative)
    if hit is None:
        return False
    try:
        date.fromisoformat("-".join(hit.groups()))
    except ValueError:
        return False
    return True


def _safe(root: Path, relative: str, *, journal: bool = False) -> Path:
    if not isinstance(relative, str) or not (_allowed(relative) or journal and relative == FILE):
        raise _fail(f"事务路径不在允许的账本文件中：{relative!r}")
    target = root / relative
    for part in (root, *reversed(target.relative_to(root).parents)):
        folder = part if part == root else root / part
        if folder.is_symlink() or folder.exists() and not folder.is_dir():
            raise _fail(f"路径包含链接或不是文件夹：{folder}")
    if target.is_symlink():
        raise _fail(f"文件不能是符号链接：{relative}")
    if target.exists() and not stat.S_ISREG(target.stat().st_mode):
        raise _fail(f"不是普通文件：{relative}")
    return target


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_files(root: Path, paths: Iterable[str]) -> None:
    folders = {root, root / ".hl"}
    for relative in paths:
        path = _safe(root, relative)
        if path.exists():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        folder = path.parent
        while folder != root:
            if folder.exists():
                folders.add(folder)
            folder = folder.parent
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        sync_directory(folder)


def _before(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    images = {}
    for relative in paths:
        path = _safe(root, relative)
        images[relative] = (
            None
            if not path.exists()
            else {
                "bytes": base64.b64encode(path.read_bytes()).decode("ascii"),
                "mode": stat.S_IMODE(path.stat().st_mode) & 0o777,
            }
        )
    if not images:
        raise _fail("事务未声明要写的文件")
    return images


def _read(root: Path, key: bytes) -> dict[str, Any] | None:
    path = _safe(root, FILE, journal=True)
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict) or not keys.signed(key, "transaction", "", body):
            raise ValueError("事务日志的签名无效")
        if set(body) != {"format", "id", "before", "sig"} or body["format"] != 1:
            raise ValueError("事务日志格式不受支持")
        before = body["before"]
        if not isinstance(before, dict) or not before:
            raise ValueError("事务日志缺少原始文件")
        for relative, image in before.items():
            _safe(root, relative)
            if image is not None:
                if not isinstance(image, dict) or set(image) != {"bytes", "mode"}:
                    raise ValueError("原始文件格式不正确")
                mode = image["mode"]
                if type(mode) is not int or not 0 <= mode <= 0o777:
                    raise ValueError("原始文件权限不正确")
                base64.b64decode(image["bytes"], validate=True)
        return before
    except (ValueError, TypeError, binascii.Error, UnicodeError) as exc:
        raise _fail(str(exc)) from exc


def _remove_journal(root: Path) -> None:
    path = _safe(root, FILE, journal=True)
    path.unlink(missing_ok=True)
    sync_directory(path.parent)
    io._written.discard(path)


def _restore(root: Path, before: dict[str, Any]) -> None:
    for relative, image in before.items():
        path = _safe(root, relative)
        if image is None:
            path.unlink(missing_ok=True)
        else:
            io.write_bytes(path, base64.b64decode(image["bytes"], validate=True), image["mode"])
    _sync_files(root, before)
    _remove_journal(root)


def recover(data_dir: Path, key: bytes) -> bool:
    """Restore an interrupted transaction, or fail closed; never adopt its output."""
    root = data_dir.absolute()
    with io.locked(root):
        if root in getattr(_active, "roots", set()):
            raise _fail("不能在尚未结束的事务内恢复")
        before = _read(root, key)
        if before is None:
            return False
        written = io._written.copy()
        try:
            _restore(root, before)
        except OSError as exc:
            raise _fail(f"无法恢复原始文件：{exc}") from exc
        finally:
            io._written.clear()
            io._written.update(written)
        return True


@contextmanager
def transaction(data_dir: Path, key: bytes, paths: Iterable[str]) -> Iterator[None]:
    """All declared files commit together; any exception restores original bytes.

    Nested transactions for the same ledger are rejected. Recovery is idempotent if
    the process dies during rollback. A failed rollback retains the signed journal.
    """
    root = data_dir.absolute()
    with io.locked(root):
        recover(root, key)
        before = _before(root, paths)
        journal = _safe(root, FILE, journal=True)
        body = {"format": 1, "id": uuid4().hex, "before": before}
        body["sig"] = keys.sign(key, "transaction", "", body)
        written = io._written.copy()
        io.write_text(journal, json.dumps(body, ensure_ascii=False) + "\n", 0o600)
        sync_directory(journal.parent)
        sync_directory(root)
        roots = getattr(_active, "roots", set())
        roots.add(root)
        _active.roots = roots
        try:
            yield
            _sync_files(root, before)
            _remove_journal(root)
        except BaseException:
            try:
                if not journal.exists():
                    io.write_text(journal, json.dumps(body, ensure_ascii=False) + "\n", 0o600)
                    sync_directory(journal.parent)
                _restore(root, before)
            except OSError as exc:
                raise _fail(f"无法回滚，已保留事务日志：{exc}") from exc
            finally:
                io._written.clear()
                io._written.update(written)
            raise
        finally:
            roots.remove(root)
