"""hl doctor：安装自检。钩子默认失败放行，所以要确认它们确实在工作。"""

from __future__ import annotations

import argparse
import shutil
from datetime import timedelta
from typing import Any

from hl.agent_config import _check, _claude, _codex
from hl.configuration.values import Context
from hl.foods import table
from hl.origins import inbox as origins_inbox
from hl.result import Abort, Result, ok
from hl.storage import git_hooks as storage_git_hooks
from hl.storage import git_ignore as storage_git_ignore
from hl.storage import git_messages as storage_git_messages
from hl.storage import git_outer as storage_git_outer
from hl.storage import git_state as storage_git_state
from hl.storage import git_tracking as storage_git_tracking
from hl.storage import keys as storage_keys

RECENT = timedelta(minutes=10)


def _executable() -> dict[str, Any]:
    found = shutil.which("hl")
    detail = found or "PATH 上找不到 hl；用 uv tool install 安装后，钩子和权限规则才能生效"
    return _check("hl 在 PATH 上", found is not None, detail)


def _table(ctx: Context) -> dict[str, Any]:
    try:
        count = len(table.load(ctx.data_dir, ctx.foods_sha))
    except table.TableError as exc:
        return _check("成分表副本", False, f"{exc}；{table.fix(exc, ctx.data_dir)}")
    return _check("成分表副本", True, f"在位，共 {count} 条，哈希与 hl.toml 一致")


def _boohee(ctx: Context) -> dict[str, Any]:
    """薄荷库副本（增补第 13.2 节）：没装、用不了都不挡记账，只是名字对得上薄荷库的食物也走估算。"""
    name = "薄荷库副本"
    try:
        count = len(table.load_boohee(ctx.data_dir, ctx.boohee_sha))
    except table.TableError as exc:
        if exc.kind == "absent":
            detail = f"没装：名字对得上薄荷库的食物也走估算，不影响记账；{table.FIX_BOOHEE_FETCH}"
            return _check(name, False, detail)
        return _check(name, False, table.boohee_note(exc, ctx.data_dir))
    return _check(name, True, f"在位，共 {count} 条，哈希与 hl.toml 一致")


def _secret(ctx: Context) -> tuple[dict[str, Any], str | None]:
    """签名密钥这一项，和要模型照着办的 next。detail 会接进 tell_user 转告用户，只说出了什么问题；
    怎么办是给模型的话（请用户从备份恢复、就此停下……），和各条命令说的一样，放在 next 里（R14）。"""
    try:
        storage_keys.secret(ctx.data_dir)
    except Abort as stop:
        body = stop.result.to_json()
        return _check("签名密钥", False, body["error"]), body["next"]
    return _check("签名密钥", True, "在位，对得上数据目录里签过名的东西"), None


def _inbox(ctx: Context) -> dict[str, Any]:
    name = "钩子在工作（收件箱里有最近的消息）"
    messages = origins_inbox.recent(ctx.data_dir)
    if messages is None:
        return _check(name, False, "收件箱不存在：UserPromptSubmit 钩子从来没有写入过")
    stamps = [m.ts for m in messages if m.ts is not None]
    if not stamps:
        return _check(name, False, "收件箱里没有带时间的消息")
    age = ctx.now - max(stamps)
    minutes = int(age.total_seconds() // 60)
    detail = f"最近一条用户消息在 {minutes} 分钟前"
    agents = sorted(
        {
            m.agent
            for m in messages
            if m.agent and m.ts is not None and timedelta(0) <= ctx.now - m.ts <= RECENT
        }
    )
    if agents:
        window = int(RECENT.total_seconds() // 60)
        detail += f"；最近 {window} 分钟内的消息来自 {'、'.join(agents)}"
    if age > RECENT:
        detail += "；在 Agent 里发一句话再运行 hl doctor，仍然如此就说明钩子没有生效"
    return _check(name, age <= RECENT, detail)


def _git(ctx: Context) -> dict[str, Any]:
    name = "git 自动提交"
    if ctx.no_git:
        return _check(name, True, "已按 HL_NO_GIT=1 跳过")
    if not ctx.autocommit:
        return _check(name, True, "hl.toml 里关闭了 autocommit")
    if not storage_git_state.is_repo(ctx.data_dir):
        return _check(name, False, "数据目录不是 git 仓库；运行 hl init 初始化")
    # 自动提交的提醒叫模型来看这一项：提交不上的几种常见原因，这里要看得出来
    if shutil.which("git") is None:
        return _check(
            name, False, f"{storage_git_messages.NO_GIT_COMMAND}，自动提交做不了；装好 git 就恢复"
        )
    lock = storage_git_state.lock_left(ctx.data_dir)  # .git 是个文件时，锁不在数据目录的 .git/ 下
    if lock:
        detail = f"没有 git 命令在跑的话，是上次中断留下的：删掉 {lock} 就恢复"
        return _check(name, False, f"{storage_git_messages.LOCKED}，这时提交不上；{detail}")
    broken = storage_git_state.repo_problem(ctx.data_dir)
    if broken:  # 开了 extensions.worktreeConfig 把 worktree 弄坏了的，说出原因和撤回的命令
        trap = storage_git_hooks.worktree_trap(ctx.data_dir)
        return _check(name, False, f"git 读不了这个仓库：{broken}" + (f"。{trap}" if trap else ""))
    problems = []
    doing = storage_git_state.unfinished_problem(ctx.data_dir)
    if doing:
        problems.append(doing)
    if storage_git_hooks.hooks_path(ctx.data_dir) != ".githooks":
        detail = "core.hooksPath 没有指向 .githooks，提交前不会跑 hl check"
        problems.append(f"{detail}；{storage_git_hooks.hooks_fix(ctx.data_dir)}")
    problems += storage_git_tracking.commit_blockers(ctx.data_dir, ctx.today)
    left = storage_git_tracking.untracked_ledger(ctx.data_dir)
    if left:
        problems.append(left)
    signing = [storage_git_messages.SIGNING] if storage_git_state.signing(ctx.data_dir) else []
    if problems:
        return _check(name, False, "；".join(problems + signing))
    return _check(name, True, "；".join(["仓库在位，提交前会跑 hl check", *signing]))


def _hidden(ctx: Context) -> dict[str, Any]:
    """签名密钥、用户原话（.hl/ 下）不进 git：git 照规则忽略它们，也没有已经进了 git 的（R14）。
    和 autocommit 开没开无关：用户自己 git add -A 也会把它们带进去。数据目录所在的外层仓库会把
    数据目录下的文件提交进去时，外层也要忽略它们（规则 20）。"""
    name = ".hl/ 不进 git"
    if ctx.no_git:
        return _check(name, True, "已按 HL_NO_GIT=1 跳过")
    outer = storage_git_outer.outer_problem(ctx.data_dir)
    if not storage_git_state.is_repo(ctx.data_dir):
        if outer:
            return _check(name, False, outer)
        return _check(name, True, "数据目录不是 git 仓库，用不着查")
    problem = "；".join(
        found for found in (storage_git_ignore.hidden_problem(ctx.data_dir), outer) if found
    )
    if problem:
        return _check(name, False, problem)
    return _check(name, True, "git 忽略 .hl/，里面的文件也没有进过暂存区")


def run(ctx: Context, args: argparse.Namespace) -> Result:
    secret, then = _secret(ctx)
    checks = [secret, _table(ctx), _boohee(ctx)]
    if secret["ok"]:
        from hl.ledgercheck.service import run as check_ledger

        checked = check_ledger(ctx, argparse.Namespace(read_only=True))
        checks.append(_check("账本完整性", checked.status == "ok", checked.to_json()))
    checks[1]["optional"] = not bool(ctx.foods_sha)
    checks[2]["optional"] = True
    for check in (_executable(), _claude(ctx), _codex(ctx), _inbox(ctx), _git(ctx), _hidden(ctx)):
        check["optional"] = True
        checks.append(check)
    failed = [c for c in checks if not c["ok"] and not c.get("optional")]
    tell = (
        "核心运行环境可用；hooks、Git 和全局 PATH 均为可选。" if not failed else "核心自检有问题。"
    )
    return ok(
        tell,
        ready=not failed,
        data_dir=str(ctx.data_dir),
        format=ctx.settings["format"],
        checks=checks,
        **({"next": then} if then else {}),
    )
