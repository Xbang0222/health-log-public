"""Signed intent receipts, audit history, pending operations and projection anchors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hl.configuration.values import Context
from hl.intents.contract import fail
from hl.origins import inbox
from hl.storage import days, io, keys

FILE = ".hl/intents.json"


def new() -> dict:
    return {"format": 2, "receipts": {}, "pending": {}, "drafts": {}, "audit": [], "heads": {}}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def heads(data_dir: Path) -> dict[str, str]:
    paths = days.day_files(data_dir)
    paths += [
        data_dir / name
        for name in ("plan.yaml", "defaults.yaml", "foods/custom.yaml")
        if (data_dir / name).exists()
    ]
    return {
        p.relative_to(data_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def load(ctx: Context, key: bytes) -> dict:
    path = ctx.data_dir / FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail(FILE, "操作收据/历史缺失或不可读", "从完整备份恢复，不要重建或重签")
    valid = (
        isinstance(value, dict)
        and value.get("format") == 2
        and all(isinstance(value.get(k), dict) for k in ("receipts", "pending", "drafts", "heads"))
        and isinstance(value.get("audit"), list)
        and keys.signed(key, "intents", "", value)
    )
    if not valid:
        fail(FILE, "操作收据/历史结构或签名不正确", "从完整备份恢复，不要重建或重签")
    if value["heads"] != heads(ctx.data_dir):
        fail(FILE, "账本与操作历史不一致（文件被改动、删除或退回）", "从完整备份恢复后检查")
    return value


def write(ctx: Context, key: bytes, value: dict) -> None:
    from hl.manifests.write import bind_protocol

    bind_protocol(ctx.data_dir, key)
    value["heads"] = heads(ctx.data_dir)
    value["sig"] = keys.sign(key, "intents", "", value)
    io.write_text(
        ctx.data_dir / FILE, json.dumps(value, ensure_ascii=False, indent=2) + "\n", 0o600
    )


def origin(ctx: Context, payload: dict) -> dict:
    source = payload.get("source", {})
    result = {
        "kind": "agent-reported",
        "said": payload["said"],
        "answers": payload.get("answers", []),
        "said_source": "agent-reported",
        "answers_source": "agent-reported",
        "at": source.get("at", ctx.now.isoformat()),
    }
    if "message_ids" not in source:
        return result
    wanted = source["message_ids"]
    messages = {m.pos: m for m in inbox.since(ctx.data_dir, 0)}
    chosen = [messages.get(pos) for pos in wanted]
    if (
        len(set(wanted)) != len(wanted)
        or any(m is None for m in chosen)
        or "\n".join(m.text for m in chosen if m) != payload["said"]
        or any(m.session != source.get("session", "") for m in chosen if m)
    ):
        fail(
            "source.message_ids",
            "收件箱引用与原文/会话不匹配",
            "核对引用；不能声称宿主采集了未核对的原话",
        )
    return {
        **result,
        "kind": "agent-reported" if payload.get("answers") else "host-captured",
        "said_source": "host-captured",
        "message_ids": wanted,
        "session": source.get("session", ""),
        "at": chosen[0].ts.isoformat() if chosen[0].ts else result["at"],
    }
