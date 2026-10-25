"""Codex 本项目权限 profile 的静态核对；不推断宿主最终生效配置。"""

from __future__ import annotations

from typing import Any

ROOT_RULES = {".git": "write", ".codex": "read", ".agents": "read"}


def gaps(settings: dict[str, Any]) -> list[str]:
    """只认已实测的项目范围规则；其他配置明确标记为无法静态确认。"""
    problems = []
    if "sandbox_mode" in settings or "sandbox_workspace_write" in settings:
        problems.append("本项目仍有旧 sandbox 设置，可能覆盖命名权限；按 README 迁移后重启 Codex")
    selected = settings.get("default_permissions")
    profiles = settings.get("permissions")
    profile = (
        profiles.get(selected) if isinstance(profiles, dict) and isinstance(selected, str) else None
    )
    if not isinstance(profile, dict):
        return [
            *problems,
            "缺少 default_permissions 选中的账本命名权限 profile；默认沙箱不能写 .git",
        ]
    if profile.get("extends") != ":workspace":
        problems.append("账本权限 profile 没有继承 :workspace，无法确认原有沙箱边界")
    filesystem = profile.get("filesystem")
    roots = filesystem.get(":workspace_roots") if isinstance(filesystem, dict) else None
    if not isinstance(roots, dict):
        roots = {}
    for path, permission in ROOT_RULES.items():
        if roots.get(path) != permission:
            problems.append(f"账本权限 :workspace_roots 中 {path} 应为 {permission}")
    if (isinstance(filesystem, dict) and set(filesystem) != {":workspace_roots"}) or set(
        roots
    ) - ROOT_RULES.keys():
        problems.append("账本权限含额外路径规则，无法静态确认是否覆盖所需保护；请核对宿主实际权限")
    if profile.get("workspace_roots"):
        problems.append("账本权限另加了工作目录，无法静态确认授权仅限当前账本")
    network = profile.get("network")
    if not isinstance(network, dict) or network.get("enabled") is not False:
        problems.append("账本权限的 network.enabled 应为 false")
    return problems
