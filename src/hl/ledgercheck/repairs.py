"""Integrity failures require restoration, never normal writes that bless bad data."""

from __future__ import annotations

from typing import Any

from hl.ledgercheck.messages import DEFAULTS_FILE, NO_GIT, PLAN_FILE, TAMPERED
from hl.manifests import model as manifests_model


def restore(where: str) -> str:
    """用 git 取回最近一次提交里的那一份（R15）。只在 _restorable 看过、走得通时给。"""
    return f"用 git 恢复它（git checkout HEAD -- {where}），做完再运行 hl check"


def _restore_only(where: str, git: bool) -> str:
    """只有 git 恢复这一条路：体重、当天类型、日期、重复的 id、整份文件读不出来。走不通就停下。"""
    if git:
        return f"{TAMPERED}{restore(where)}"
    return f"{TAMPERED}{NO_GIT}。{manifests_model.RESTORE_BACKUP}"


def _undo_entry(where: str, day: str, entry_id: Any, git: bool) -> str:
    """A broken entry cannot be deleted through a write service whose preflight rejects it."""
    return _restore_only(where, git)


def _fix_plan(git: bool) -> str:
    """Do not discard invalid historical plans when saving a new plan."""
    return _restore_only(PLAN_FILE, git)


def _fix_plan_short(git: bool) -> str:
    """Missing or reordered plan versions must match the accepted manifest again."""
    return "计划历史与清单不一致。" + _restore_only(PLAN_FILE, git)


def _fix_defaults(git: bool) -> str:
    """Deleting a broken defaults file also breaks its signed manifest and state head."""
    return _restore_only(DEFAULTS_FILE, git)
