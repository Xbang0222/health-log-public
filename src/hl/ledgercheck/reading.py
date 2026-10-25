"""账本读取错误转换与清单核验的共同边界。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from hl.ledgercheck.messages import NEXT_DATA, Checked
from hl.manifests import io as manifests_io
from hl.result import Abort, rejected
from hl.storage import io as storage_io


def _read(path: Path) -> tuple[Any, list[str]]:
    try:
        return storage_io.read_yaml(path), []
    except (yaml.YAMLError, UnicodeDecodeError):
        return None, ["不是合法的 YAML"]
    except OSError:
        return None, [storage_io.UNREADABLE]


def _or_os(text: str, fix: Callable[[], str]) -> str:
    """读不了的（是个目录、没有权限），git 也取不回来，别的路也走不通：只能请用户看一下。"""
    return storage_io.FIX_OS if text == storage_io.UNREADABLE else fix()


def _settled(read: Callable[[], Checked]) -> Checked:
    """不拿锁的读可能正好夹在一次写入的“改文件”和“改清单”之间：有缺口就重读一遍，两次都缺才算。"""
    found = read()
    return read() if found[2] else found


def _require_manifest(data_dir: Path, key: bytes) -> None:
    """清单自己丢了、读不出来或验签不过时，读和写都不做（R15）。"""
    _, errors = manifests_io.read(data_dir, key)
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
