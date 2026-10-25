"""hl foods build <原始数据目录>：构建成分表本地副本，或整理薄荷库副本（目录里有 all.csv 的），
并把哈希和原始数据目录写入 hl.toml。hl foods fetch 下载之后也调这里的 install（增补第 13.2 节）。"""

from __future__ import annotations

import argparse
from pathlib import Path

from hl.configuration.values import Context
from hl.foods.install import FIX_RAW, NAMES
from hl.foods.install import Failed as Failed
from hl.foods.install import Installed as Installed
from hl.foods.install import install as install
from hl.foods.install import kind_of as kind_of
from hl.result import Result, ok, problem, rejected
from hl.storage import git_commit as storage_git_commit
from hl.storage import io as storage_io


def run(ctx: Context, args: argparse.Namespace) -> Result:
    raw_dir = Path(args.raw_dir).expanduser()
    if not raw_dir.is_dir():
        return rejected([problem("原始数据目录", f"{raw_dir} 不是一个目录", FIX_RAW)])
    kind = kind_of(raw_dir)
    with storage_io.locked(ctx.data_dir):
        done = install(ctx, raw_dir, kind)
        if isinstance(done, Failed):
            return rejected(done.problems)
        message = f"hl foods build：{NAMES[kind]} {done.count} 条"
        warnings = storage_git_commit.autocommit(ctx.data_dir, ctx.autocommit, message)
    return ok(done.tell, **done.fields()).warn(warnings)
