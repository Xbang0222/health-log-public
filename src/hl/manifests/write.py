"""账本修改后的清单同步、出处同步与重建服务。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from hl import sources
from hl.configuration import read as configuration_read
from hl.manifests import io as manifest_io
from hl.manifests.model import NEXT_DATA, _note, _snapshot, versions
from hl.manifests.scan import _adopted, build, defaults_path
from hl.result import Abort, rejected
from hl.storage import days as storage_days
from hl.storage import io as storage_io


@contextmanager
def _editing(data_dir: Path, key: bytes) -> Iterator[dict[str, Any]]:
    """改清单：进来时读，出去时签名写回。

    清单自己有问题时不让写，这时还没动任何文件。还没有清单的数据目录，先按现有记录建一份；
    还没记默认品种的，不论这次写的是什么，写完都按那时的 defaults.yaml 补上——
    文件里有一条过不了校验就先不补（见 _adopted）。
    """
    body, errors = manifest_io.read(data_dir, key)
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
    if body is None:
        body = build(data_dir, key)
    sources.restore(data_dir, body)  # recorded.json 丢了、少了几条：照清单里记着的补回（K-3）
    mark = configuration_read.manifest_mark(data_dir)
    yield body
    if "defaults" not in body:
        adopted = _adopted(data_dir, key)
        if adopted is not None:
            body["defaults"] = adopted
    sources.adopt(data_dir, body)
    manifest_io._write(data_dir, key, body, mark)


def restore_sources(data_dir: Path, key: bytes) -> int:
    """recorded.json 里少了清单里记着的出处，照原样补回，返回补了几条。清单有问题时不补
    （由各条命令照清单的问题去报）。调用方负责加锁（见 sources）。"""
    body, _ = manifest_io.read(data_dir, key)
    return 0 if body is None else sources.restore(data_dir, body)


def save_day(
    data_dir: Path, key: bytes, doc: Mapping[str, Any], note: dict[str, Any] | None = None
) -> None:
    """写某一天的文件，再把它记进清单；note 是这次记的原话出自哪里，先记进清单，
    调用方随后再写 recorded.json（见 sources）。"""
    with _editing(data_dir, key) as body:
        storage_days.save_day(data_dir, doc)
        _note(body["days"], doc["date"], _snapshot(key, doc["date"], doc))
        if note is not None:
            sources.add(data_dir, body, note)


def save_plans(data_dir: Path, key: bytes, plans: list[dict[str, Any]]) -> None:
    """写计划文件，再按先后把各版的签名记进清单。"""
    with _editing(data_dir, key) as body:
        storage_io.write_yaml(data_dir / storage_io.PLAN_FILE, plans)
        body["plans"] = versions(key, plans)


def save_defaults(data_dir: Path, key: bytes, defaults: dict[str, Any], name: str) -> None:
    """写默认品种文件，再把 name 这一条记进清单（清掉了的从清单里划掉）。

    别的食物的条目清单里照旧记着原来的：文件里那几条要是被退回过，这次写入不把它抹平。
    """
    with _editing(data_dir, key) as body:
        storage_io.write_yaml(defaults_path(data_dir), defaults)
        if "defaults" not in body:
            return  # 清单还没记默认品种：写完由 _editing 按整个文件补上
        if name in defaults:
            entry = defaults[name]
            body["defaults"][name] = {"variant": entry["variant"], "sig": entry["sig"]}
        else:
            body["defaults"].pop(name, None)


def drop_entry(data_dir: Path, key: bytes, day: str, entry_id: str) -> None:
    """撤销用：先从清单里划掉这一条；调用方随后再改文件。"""
    with _editing(data_dir, key) as body:
        listed = body["days"].get(day)
        if listed and entry_id in listed["entries"]:
            del listed["entries"][entry_id]
            _note(body["days"], day, listed)


def rebuild(data_dir: Path, key: bytes, body: dict[str, Any], said: str, now: datetime) -> None:
    """写下 preview 生成的新清单，连同重建的时间和原话。记过的原话出自哪里不从文件里重建：
    原来的清单里记着的、recorded.json 里有的都留下，再把文件补齐（K-3）。"""
    body["rebuilt"] = {"at": now.isoformat(timespec="seconds"), "said": said}
    body[sources.FIELD] = sources.merged(data_dir, manifest_io.read(data_dir, key)[0])
    manifest_io._write(data_dir, key, body, configuration_read.manifest_mark(data_dir))
    sources.restore(data_dir, body)


def bind_protocol(data_dir: Path, key: bytes, version: int = 2) -> None:
    """Persist the adopted write protocol independently of unsigned hl.toml."""
    with _editing(data_dir, key) as body:
        previous = body.get("protocol", 1)
        if previous > version:
            raise Abort(
                rejected(
                    [
                        {
                            "where": ".hl/manifest.json",
                            "problem": "不能降低已采用的协议版本",
                            "fix": "使用兼容的引擎并恢复完整备份",
                        }
                    ]
                )
            )
        body["protocol"] = version
