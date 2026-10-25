"""hl foods fetch：按 hl.toml 里固定的提交下载成分表和薄荷库的原始数据，核对校验值，整理成副本
（第 2 步增补第 13.2 节）。整理调 hl foods build 的同一段代码（foods/install.py）。

哪一份没成，另一份照常装上，结果的 missing 里说缺了哪一份、为什么，没成的那一份原来的副本不动；
两份都没成返回 error。下载在锁外做（要一会儿，不挡别的命令），换到位和整理在锁里。
"""

from __future__ import annotations

import argparse
import dataclasses
import os
from typing import Any

from hl.configuration import write as configuration_write
from hl.configuration.values import Context
from hl.foods import fetch, install
from hl.result import Result, error, ok
from hl.storage import git_commit as storage_git_commit
from hl.storage import io as storage_io

ORDER = (fetch.CN6, fetch.BOOHEE)
NAMES = {fetch.CN6: "成分表", fetch.BOOHEE: "薄荷库"}
NEXT_MISSING = (
    "把 tell_user 原样转告用户；missing 里缺的那一份，等能联网了再运行一次 hl foods fetch，"
    "已经装好的不会重新下载"
)
NEXT_NONE = (
    "这是下载的问题，副本和 hl.toml 都没改：把 error 原样告诉用户；等能联网了再运行一次 "
    "hl foods fetch。用户手上有原始数据时，也可以运行 hl foods build <原始数据目录>"
)
Done = dict[str, tuple[install.Installed, bool]]  # 装好的：整理结果，这次是不是新下载的


def _pinned(ctx: Context, pin: fetch.Pin) -> Context:
    """整理时用的版本（副本 meta 里的来源和提交）照这次下载的写。"""
    return dataclasses.replace(ctx, settings={**ctx.settings, "foods": {**ctx.foods, **pin.values}})


def _without(ctx: Context, kind: str) -> str:
    """缺的这一份，说给用户的后果。"""
    had = ctx.foods_sha if kind == fetch.CN6 else ctx.boohee_sha
    if had:
        return "原来装的那份没动。"
    if kind == fetch.CN6:
        return "没有成分表还记不了账，要等下载成了才能记。"
    return "没有薄荷库照样能记账，名字对得上薄荷库的食物先走估算。"


def _download(ctx: Context, missing: dict[str, str]) -> dict[str, tuple[fetch.Pin, fetch.Got]]:
    """两份各自下载（锁外）；没成的原因记进 missing。"""
    try:
        where = fetch.base(os.environ)
    except fetch.FetchError as exc:
        missing.update(dict.fromkeys(ORDER, str(exc)))
        return {}
    got = {}
    for kind, pin in fetch.pins(ctx.foods).items():
        try:
            if isinstance(pin, fetch.FetchError):
                raise pin
            got[kind] = (pin, fetch.obtain(ctx.data_dir, pin, where))
        except fetch.FetchError as exc:
            missing[kind] = str(exc)
    return got


def _install(
    ctx: Context, got: dict[str, tuple[fetch.Pin, fetch.Got]], missing: dict[str, str]
) -> Done:
    """在锁里把下载的换到位、整理成副本；以前的 hl.toml 没写版本的补上，记下装的是哪一版。"""
    installed: Done = {}
    for kind, (pin, one) in got.items():
        done = install.install(_pinned(ctx, pin), fetch.place(ctx.data_dir, one), kind)
        if isinstance(done, install.Failed):
            missing[kind] = "；".join(item["problem"] for item in done.problems)
            continue
        unrecorded = pin.unrecorded(ctx.foods)
        if unrecorded:
            configuration_write.set_foods_values(ctx.data_dir, unrecorded)
        installed[kind] = (done, one.downloaded)
    return installed


def run(ctx: Context, args: argparse.Namespace) -> Result:
    missing: dict[str, str] = {}
    got = _download(ctx, missing)
    installed: Done = {}
    warnings: list[str] = []
    try:
        if got:
            with storage_io.locked(ctx.data_dir):
                installed = _install(ctx, got, missing)
                counts = "、".join(f"{NAMES[k]} {d.count} 条" for k, (d, _) in installed.items())
                if installed:
                    message = f"hl foods fetch：{counts}"
                    warnings = storage_git_commit.autocommit(ctx.data_dir, ctx.autocommit, message)
    finally:
        for _, one in got.values():
            fetch.discard(one)
    if not installed:
        reasons = "；".join(f"{NAMES[kind]}：{missing[kind]}" for kind in ORDER)
        return error(f"成分表和薄荷库都没装上。{reasons}", NEXT_NONE)
    fields: dict[str, Any] = {}
    said: list[str] = []
    for kind in ORDER:
        if kind in installed:
            done, downloaded = installed[kind]
            fields[kind] = {**done.fields(), "downloaded": downloaded}
            again = "" if downloaded else "原始数据之前下载过、核对无误，这次没有重新下载。"
            said.append(done.tell + again)
        else:
            fields[kind] = None
            said.append(f"{NAMES[kind]}这次没装上：{missing[kind]}。{_without(ctx, kind)}")
    lost = [{"dataset": NAMES[kind], "reason": missing[kind]} for kind in ORDER if kind in missing]
    extra = {"next": NEXT_MISSING} if lost else {}
    return ok("".join(said), **fields, missing=lost, **extra).warn(warnings)
