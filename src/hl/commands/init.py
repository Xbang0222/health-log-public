"""hl init [目录]：生成数据目录。可重复执行，已有的文件一律不动（R22）。"""

from __future__ import annotations

import argparse
import os
import secrets
from collections.abc import Mapping
from datetime import date
from importlib import resources
from pathlib import Path

from hl import guard, templates
from hl.configuration import read as configuration_read
from hl.configuration import values as configuration_values
from hl.foods import table
from hl.result import Abort, Result, error, ok
from hl.storage import git_commit as storage_git_commit
from hl.storage import git_hooks as storage_git_hooks
from hl.storage import git_ignore as storage_git_ignore
from hl.storage import git_outer as storage_git_outer
from hl.storage import git_state as storage_git_state
from hl.storage import git_tracking as storage_git_tracking
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys
from hl.storage import transactions
from hl.templates import template as template

EXECUTABLE = (".githooks/pre-commit",)
BACKUP = (
    f"签名密钥在 {storage_keys.SECRET}，它不进 git：请另外备份一份（换电脑、重装时要用；"
    "丢了它，已有的记录就都验不过签名）。"
)


def _today(environ: Mapping[str, str]) -> str:
    """今天（HL_TODAY 优先）；HL_TODAY 写坏了也不碍 hl init 的事，用本机的日期。"""
    try:
        return configuration_values.today(environ)
    except Abort:
        return date.today().isoformat()


def run(
    target: str | None, environ: Mapping[str, str], cwd: Path, *, hooks: bool = False
) -> Result:
    chosen = target or environ.get("HL_DATA") or str(Path.home() / "health-data")
    data_dir = Path(os.path.abspath(Path(chosen).expanduser()))
    if environ.get("HL_NO_GIT") != "1":  # git 操作做到一半：什么都不写（规则 19）
        refused = storage_git_state.refuse_unfinished(data_dir)
        if refused is not None:
            return refused
    for folder in guard.PROTECTED_DIRS:  # 受保护的目录就是引擎自己管的那几个
        (data_dir / folder).mkdir(parents=True, exist_ok=True)
    created = []
    with storage_io.locked(data_dir):
        secret_path = data_dir / storage_keys.SECRET
        key, what, unreadable = storage_keys.read_secret(data_dir)
        if (data_dir / transactions.FILE).exists():
            if key is None:
                return error(
                    "初始化或写入被中断，事务密钥缺失；保留目录并恢复原密钥，不要重新初始化"
                )
            transactions.recover(data_dir, key)
        signed = storage_keys.signed_data(data_dir)
        if unreadable:  # 是个目录、没有权限：换不了，也不该换，请用户看一下
            return storage_keys.secret_error(data_dir, what, unreadable)
        if signed and key is None and not secret_path.exists():
            # 新密钥对不上已有的签名，整个历史就作废了：只能从备份恢复（R14、R22）。什么都不写
            what = (
                f"数据目录里已经有签过名的数据，签名密钥 {storage_keys.SECRET} "
                "却不见了，不能生成新的"
            )
            return error(what, storage_keys.NEXT_SECRET)
        if signed:  # 空的、格式不对、对不上已有的签名：和各条命令说的一样，什么都不写
            try:
                storage_keys.secret(data_dir)
            except Abort as stop:
                return stop.result
        if not (data_dir / configuration_values.CONFIG_NAME).exists() and storage_keys.signed_data(
            data_dir
        ):
            return configuration_read.missing_toml(data_dir)  # 不重新生成：取回原来那一份（R22）
        if (data_dir / configuration_values.CONFIG_NAME).exists():
            from hl.ledgercheck import service as check

            existing = configuration_read.read_settings(data_dir)
            if existing["format"] == 2:
                # An existing v2 configuration is never a fresh ledger: validate before
                # recreating templates or history, including recovery of interrupted writes.
                if key is None:
                    return error("已有格式 2 账本缺少密钥，不能用 init 重建；请恢复完整备份")
                transactions.recover(data_dir, key)
                existing = configuration_read.read_settings(data_dir)
                context = configuration_values.Context(
                    data_dir,
                    _today(environ),
                    configuration_values.now(environ),
                    environ.get("HL_NO_GIT") == "1",
                    existing,
                )
                checked = check.run(context, argparse.Namespace(read_only=True))
                if checked.status != "ok":
                    return checked
        if key is None:  # 不在，或者还没有签过名的数据时空了、格式不对：换一把新的不碍事
            storage_io.write_text(secret_path, secrets.token_hex(32) + "\n", 0o600)
            created.append(storage_keys.SECRET)
        key = storage_keys.secret(data_dir)
        with transactions.transaction(
            data_dir,
            key,
            [
                "hl.toml",
                ".hl/intents.json",
                ".hl/manifest.json",
                ".hl/recorded.json",
                "AGENTS.md",
                "CLAUDE.md",
            ],
        ):
            root = resources.files("hl").joinpath("data", "templates")
            for relative, source in templates.walk(root):
                if not hooks and relative.startswith((".claude/", ".codex/", ".githooks/")):
                    continue
                destination = data_dir / relative
                if destination.exists():
                    continue
                mode = 0o755 if relative in EXECUTABLE else 0o644
                text = templates.render(relative, source.read_text(encoding="utf-8"))
                storage_io.write_text(destination, text, mode)
                created.append(relative)
            settings = configuration_read.read_settings(data_dir)
            if settings["format"] == 2:
                from hl.configuration.values import Context
                from hl.intents import state

                if not (data_dir / state.FILE).exists():
                    if signed:
                        return error("操作历史缺失，不能用 init 重建；请恢复完整备份")
                    state.write(
                        Context(
                            data_dir,
                            _today(environ),
                            configuration_values.now(environ),
                            environ.get("HL_NO_GIT") == "1",
                            settings,
                        ),
                        storage_keys.secret(data_dir),
                        state.new(),
                    )
        warnings = []
        changed = False
        if hooks and environ.get("HL_NO_GIT") != "1":
            # 自动提交只提交引擎这次写的文件：生成的模板也由这里提交，不留给之后哪一次写入
            warnings, changed = storage_git_hooks.git_init(data_dir)
            if storage_git_state.is_repo(
                data_dir
            ):  # .hl/ 不进 git：用户自己的 .gitignore 没写，也要忽略它
                kept, wrote = storage_git_ignore.keep_out(data_dir)
                warnings += kept
                changed = changed or wrote
                # .gitignore 忽略了账本文件、log/ 下有符号链接：以后的写入提交不上，当场说
                warnings += storage_git_tracking.commit_blockers(data_dir, _today(environ))
            # 外层仓库会把数据目录下的文件提交进去时，.hl/ 也要它自己忽略（规则 20）
            kept, wrote = storage_git_outer.keep_out_outer(data_dir)
            warnings += kept
            changed = changed or wrote
            # 仓库没建成，autocommit 自己会跳过；git_init 的提醒也可能只是说钩子的事，照常提交
            enabled = settings.get("git", {}).get("autocommit", True) is True
            warnings += storage_git_commit.autocommit(data_dir, enabled, "hl init")
    done = f"新建了 {len(created)} 个文件" if created else "文件都已存在，没有改动"
    if changed and not created:  # 文件没动，git 的设置补上了（建了仓库、设了钩子、写了 exclude）
        done = "文件都已存在，补上了 git 的设置"
    steps = "下一步：运行 hl doctor 自检"
    if not table.path(data_dir).exists():
        steps = (
            "下一步：运行 hl foods fetch 下载并整理成分表和薄荷库（要联网；"
            "手上有原始数据时用 hl foods build <原始数据目录>），再运行 hl doctor 自检"
        )
    tell_user = f"数据目录已就绪：{data_dir}（{done}）。{steps}。"
    if storage_keys.SECRET in created:
        tell_user += BACKUP
    return ok(tell_user, data_dir=str(data_dir), created=created).warn(warnings)
