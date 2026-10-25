"""食品副本的唯一整理与安装服务；调用方负责加锁和自动提交。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl.configuration import write as configuration_write
from hl.configuration.values import Context
from hl.foods import boohee, cn6, fetch, table
from hl.result import problem
from hl.storage import io as storage_io

FIX_RAW = (
    "给出原始数据所在的目录：成分表是若干 .json 文件，每个文件是一个记录数组；"
    "薄荷库是 all.csv 和 food_detail_backup.json"
)
FIX_PROBLEMS = "修正原始数据后重新构建"
CN6, BOOHEE = fetch.CN6, fetch.BOOHEE  # 哪一份：成分表、薄荷库
NAMES = {CN6: "成分表", BOOHEE: "薄荷库"}


@dataclass
class Installed:
    """装好的一份副本：哪一份、条数、哈希、质检条数、说给用户的话。"""

    kind: str
    count: int
    sha256: str
    quality: dict[str, int]
    tell: str

    def fields(self) -> dict[str, Any]:
        return {"count": self.count, "sha256": self.sha256, "quality": self.quality}


@dataclass
class Failed:
    """没装上：出了什么问题（交给 rejected 的几条）。"""

    kind: str
    problems: list[dict[str, str]] = field(default_factory=list)


def kind_of(raw_dir: Path) -> str:
    """原始数据目录放的是哪一份：有 all.csv 的是薄荷库，别的按成分表读。"""
    return BOOHEE if boohee.looks_like(raw_dir) else CN6


def install(ctx: Context, raw_dir: Path, kind: str) -> Installed | Failed:
    """整理 raw_dir 里的原始数据，写进副本，把哈希和原始数据目录（绝对路径）写进 hl.toml。
    调用方负责加锁和自动提交。"""
    foods = ctx.foods
    if kind == BOOHEE:
        source, commit = foods.get("boohee_source", ""), foods.get("boohee_commit", "")
        built = boohee.read(raw_dir, str(source), str(commit))
    else:
        built = cn6.read(raw_dir, foods.get("source", ""), foods.get("commit", ""))
    if built.problems:
        return Failed(kind, [problem(str(raw_dir), text, FIX_PROBLEMS) for text in built.problems])
    count = built.doc["meta"]["count"]
    if count == 0:
        return Failed(kind, [problem(str(raw_dir), f"目录里没有任何{NAMES[kind]}记录", FIX_RAW)])
    text = table.serialize(built.doc)
    sha = table.sha256_of(text)
    # 原始数据目录也记下（绝对路径）：副本坏了，改法照它给出照抄就能跑的命令（R15）
    raw = os.path.abspath(raw_dir)
    if kind == BOOHEE:
        storage_io.write_text(table.boohee_path(ctx.data_dir), text)
        configuration_write.set_foods_values(
            ctx.data_dir, {"boohee_sha256": sha, "boohee_raw_dir": raw}
        )
        tell = f"薄荷库副本已整理：{boohee.describe(built.quality, count)}"
    else:
        storage_io.write_text(table.path(ctx.data_dir), text)
        configuration_write.set_foods_build(ctx.data_dir, sha, raw)
        tell = f"成分表副本已构建，共 {count} 条。{cn6.describe(built.quality)}"
    return Installed(kind, count, sha, built.quality, tell)
