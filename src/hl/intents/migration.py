"""Preflight and backed-up format-1 to format-2 migration; no legacy re-signing."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import tomllib
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from hl import templates
from hl.configuration import read
from hl.configuration.values import Context
from hl.intents import state
from hl.ledgercheck import service as check
from hl.result import Abort, Result, error, ok
from hl.storage import io, keys, transactions

GUIDES = ("AGENTS.md", "CLAUDE.md", "HEALTH_LOG_V2.md")
GUIDE_POINTER = (
    "# 此账本已迁移为 format 2\n\n"
    "先读取本目录 [HEALTH_LOG_V2.md](HEALTH_LOG_V2.md)，按其中的结构化意图契约调用引擎。\n"
    "下方原指南中的旧写入协议、逐字匹配、先删后重记和强制 hooks 约束已被取代；"
    "个人业务偏好仍保留。与新契约冲突时以 HEALTH_LOG_V2.md 为准。\n\n"
    "---\n\n"
)


def _upgrade_guides(root: Path) -> None:
    """Retain every original guide byte after an explicit authority pointer."""
    io.write_text(root / "HEALTH_LOG_V2.md", templates.template("AGENTS.md"))
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        original = path.read_bytes() if path.exists() else b""
        io.write_bytes(path, GUIDE_POINTER.encode("utf-8") + original)


def _inventory(root: Path) -> dict[str, str]:
    """Reject links/special files instead of copying data from outside the ledger."""
    if root.is_symlink():
        raise Abort(error("迁移目录不能是符号链接", "使用真实持久目录，并保留原账本"))
    result = {}
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(folder) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise Abort(
                    error(f"迁移预检发现链接或特殊文件：{path}", "先检查并移出该文件再预检")
                )
            if stat.S_ISREG(mode):
                result[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return result


def _backup(root: Path, inventory: dict[str, str]) -> Path:
    destination = root.with_name(f"{root.name}.backup-{uuid4().hex}")
    shutil.copytree(root, destination, symlinks=True)
    destination.chmod(0o700)
    if _inventory(destination) != inventory:
        raise Abort(
            error(
                f"备份核对失败，原账本未迁移；保留备份供检查：{destination}",
                "停止外部写入后重新预检，不要删除原账本",
            )
        )
    # Make the verified backup durable before changing either version marker.
    for folder, _, files in os.walk(destination, topdown=False):
        for name in files:
            with (Path(folder) / name).open("rb") as handle:
                os.fsync(handle.fileno())
        transactions.sync_directory(Path(folder))
    transactions.sync_directory(destination.parent)
    return destination


def run(ctx: Context, args: argparse.Namespace) -> Result:
    with io.locked(ctx.data_dir):
        key = keys.secret(ctx.data_dir)
        transactions.recover(ctx.data_dir, key)
        ctx = replace(ctx, settings=read.read_settings(ctx.data_dir))
        inventory = _inventory(ctx.data_dir)
        checked = check.run(ctx, argparse.Namespace(read_only=True))
        if checked.status != "ok":
            return checked
        if ctx.settings["format"] == 2:
            state.load(ctx, key)
            return ok("账本已是格式 2，无需迁移。", migrated=False, format=2)
        if not getattr(args, "apply", False):
            return ok(
                "预检通过。迁移将先完整备份账本，再启用新写入和新指南；旧记录与签名原样保留。",
                migrated=False,
                from_format=1,
                to_format=2,
                guide_updates=list(GUIDES),
                next="运行 migrate --apply；备份保存在数据目录同一父目录",
            )
        if (ctx.data_dir / state.FILE).exists():
            return error("格式 1 账本已存在新操作历史，不能覆盖", "请诊断版本标记或从完整备份恢复")
        backup = _backup(ctx.data_dir, inventory)
        original = (ctx.data_dir / "hl.toml").read_text(encoding="utf-8")
        updated, count = re.subn(r"(?m)^format\s*=\s*1\b", "format = 2", original, count=1)
        if count != 1 or tomllib.loads(updated).get("format") != 2:
            return error("无法安全更新格式标记，原账本未迁移", f"保留备份 {backup}，检查 hl.toml")
        migrated = replace(ctx, settings=tomllib.loads(updated))
        value = state.new()
        value["audit"].append(
            {
                "request_id": "migration-" + uuid4().hex,
                "action": "migrate",
                "at": ctx.now.isoformat(),
                "from_format": 1,
                "to_format": 2,
                "backup": str(backup),
                "changes": [],
            }
        )
        with transactions.transaction(
            ctx.data_dir,
            key,
            ["hl.toml", state.FILE, ".hl/manifest.json", ".hl/recorded.json", *GUIDES],
        ):
            io.write_text(ctx.data_dir / "hl.toml", updated)
            _upgrade_guides(ctx.data_dir)
            state.write(migrated, key, value)
            state.load(migrated, key)
            verified = check.run(migrated, argparse.Namespace(read_only=True))
            if verified.status != "ok":
                raise Abort(verified)
        return ok(
            "已迁移为格式 2，旧记录与签名未变；完整备份已保存。",
            migrated=True,
            format=2,
            backup=str(backup),
            guide_updates=list(GUIDES),
        )
