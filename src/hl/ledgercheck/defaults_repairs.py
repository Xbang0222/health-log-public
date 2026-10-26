"""Separate obsolete valid preferences from damaged or missing signed defaults."""

from __future__ import annotations

from typing import Any

from hl import schema
from hl.foods import concepts
from hl.ledgercheck.messages import DEFAULTS_FILE
from hl.ledgercheck.repairs import _fix_defaults
from hl.manifests import model as manifests_model


def clear_command(name: Any) -> str:
    """Only a still-known concept can be cleared through the structured contract."""
    if not isinstance(name, str) or name not in concepts.load().concepts:
        return "这项旧设置已不参与计算，可以保留；当前入口不能清理已移除的概念，请交维护者处理"
    return (
        f"先用 recent 读取“{schema.shown_key(name)}”的当前版本，再用 intent action=default、"
        "variant=null、expected_version=当前版本清除（保留用户原话，使用新 request_id）"
    )


def _clear_with(name: Any) -> str:
    return clear_command(name)


def _settable(name: Any) -> bool:
    return isinstance(name, str) and name in concepts.load().concepts


def _redo(name: Any) -> str:
    """Compatibility helper for callers describing a valid obsolete preference."""
    return clear_command(name)


def _default_fix(name: Any, git: bool) -> str:
    """Malformed values cannot be repaired by writing a new normal preference."""
    return _fix_defaults(git)


def _settle_fix(name: Any, kind: str, git: bool) -> str:
    why = {
        "gone": f"清单里记着这一条，{DEFAULTS_FILE} 里却没有了。",
        "changed": "这一条签名有效，但不是清单记着的那一版。",
        "extra": "这一条签名有效，但没有被当前清单接纳。",
    }[kind]
    if git and kind != "extra":
        return why + manifests_model.fix_gone(DEFAULTS_FILE, True, "")
    return why + manifests_model.RESTORE_BACKUP
