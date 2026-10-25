"""食品副本读取、哈希校验与薄荷延迟加载。"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from hl.configuration import values as configuration_values
from hl.foods.table_types import Boohee, Food, Table
from hl.storage import io as storage_io

FILE = "cn6.json"

WHERE = f"{storage_io.HIDDEN}/{FILE}"


class TableError(Exception):
    """成分表副本用不了。kind：missing（不存在）、unreadable（是个目录、没有权限）
    或 broken（哈希对不上或内容损坏）。"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


# ---------- 副本内容 ----------
def serialize(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------- 加载 ----------
def path(data_dir: Path) -> Path:
    return data_dir / storage_io.HIDDEN / FILE


def load(data_dir: Path, expected_sha: str) -> Table:
    """读成分表副本并核对哈希；用不了时抛 TableError。"""
    try:
        text = path(data_dir).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TableError("missing", "成分表副本 .hl/cn6.json 不存在") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise TableError("unreadable", f"成分表副本 .hl/cn6.json {storage_io.UNREADABLE}") from exc
    if sha256_of(text) != expected_sha:
        raise TableError("broken", "成分表副本的哈希与 hl.toml 里记录的不一致")
    try:
        return _foods(json.loads(text))
    except (ValueError, KeyError, TypeError) as exc:
        raise TableError("broken", f"成分表副本的内容读不出来：{exc!r}") from exc


def _foods(doc: Any) -> Table:
    """副本内容（hl foods build 写下的 JSON）里的成分表。"""
    return {
        code: Food(**{**item, "trace": tuple(item["trace"])}) for code, item in doc["foods"].items()
    }


# ---------- 薄荷库副本（增补第 13.1、13.2 节）----------
BOOHEE_FILE = "boohee.json"

BOOHEE_WHERE = f"{storage_io.HIDDEN}/{BOOHEE_FILE}"

# 没装、用不了时 add 照常工作，当作没有这一层（增补第 13.2 节）：提醒放进 warnings，是给模型的
BOOHEE_ABSENT = "没装（hl.toml 的 [foods] boohee_sha256 是空的）"

BOOHEE_SKIPPED = "这次当作没有薄荷库：名字对得上薄荷库的食物也走估算"

FIX_BOOHEE_FETCH = "要用薄荷库就运行 hl foods fetch（要联网下载）"


def boohee_path(data_dir: Path) -> Path:
    return data_dir / storage_io.HIDDEN / BOOHEE_FILE


def boohee_text(data_dir: Path, expected_sha: str) -> str:
    """薄荷库副本的全文，核对过哈希；没装（absent）、用不了时抛 TableError。"""
    if not expected_sha:
        raise TableError("absent", f"薄荷库副本{BOOHEE_ABSENT}")
    try:
        text = boohee_path(data_dir).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TableError("missing", f"薄荷库副本 {BOOHEE_WHERE} 不存在") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise TableError(
            "unreadable", f"薄荷库副本 {BOOHEE_WHERE} {storage_io.UNREADABLE}"
        ) from exc
    if sha256_of(text) != expected_sha:
        raise TableError("broken", "薄荷库副本的哈希与 hl.toml 里记录的不一致")
    return text


def load_boohee(data_dir: Path, expected_sha: str) -> dict[str, Boohee]:
    """读薄荷库副本：编号 → 条目。没装、用不了时抛 TableError。"""
    text = boohee_text(data_dir, expected_sha)
    try:
        doc = json.loads(text)
        return {
            code: Boohee(**{**item, "edible": 100, "trace": ()})
            for code, item in doc["foods"].items()
        }
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise TableError("broken", f"薄荷库副本的内容读不出来：{exc!r}") from exc


def boohee_problem(data_dir: Path, expected_sha: str) -> TableError | None:
    """薄荷库副本装了却用不了时的问题（只核对哈希，不解析）；没装、用得了都是 None。"""
    try:
        boohee_text(data_dir, expected_sha)
    except TableError as exc:
        return None if exc.kind == "absent" else exc
    return None


def boohee_note(exc: TableError, data_dir: Path) -> str:
    """薄荷库副本用不了时放进 warnings 的提醒：出了什么事、这次怎么办、怎么修。"""
    if exc.kind == "unreadable":
        return f"{exc}，{BOOHEE_SKIPPED}。{storage_io.FIX_OS}"
    if exc.kind == "absent":
        return f"{exc}，{BOOHEE_SKIPPED}。{FIX_BOOHEE_FETCH}"
    raw = configuration_values.foods_raw_dir(data_dir, "boohee_raw_dir")
    if raw and Path(raw).is_dir():
        how = f"用上次整理时的原始数据重新整理：运行 hl foods build {shlex.quote(raw)}"
    else:
        how = f"重新下载整理：{FIX_BOOHEE_FETCH}"
    return f"{exc}，{BOOHEE_SKIPPED}。{how}"


class BooheeLayer(Mapping[str, Food]):
    """薄荷库这一层：用到时才读，只读一次。没装、用不了都当作空的（增补第 13.2 节），
    用到过而用不了时 warnings() 给出提醒。"""

    def __init__(self, data_dir: Path, expected_sha: str) -> None:
        self._data_dir, self._sha = data_dir, expected_sha
        self._foods: dict[str, Boohee] | None = None
        self._problem: TableError | None = None

    def _load(self) -> dict[str, Boohee]:
        if self._foods is None:
            try:
                self._foods = load_boohee(self._data_dir, self._sha)
            except TableError as exc:
                self._foods, self._problem = {}, exc
        return self._foods

    def __getitem__(self, code: str) -> Food:
        return self._load()[code]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())

    def warnings(self) -> list[str]:
        """用到过这一层而它用不了时的提醒；没用到、用得了都是空的。"""
        if self._problem is None:
            return []
        return [boohee_note(self._problem, self._data_dir)]
