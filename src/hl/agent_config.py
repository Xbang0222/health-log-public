"""Agent 项目配置的静态核对；宿主真实执行仍由钩子探针验证。"""

from __future__ import annotations

import json
import shlex
import tomllib
from pathlib import Path
from typing import Any

from hl import codex_permissions, templates
from hl.configuration.values import Context

CLAUDE_SETTINGS = ".claude/settings.json"
CLAUDE_LOCAL = ".claude/settings.local.json"
CODEX_HOOKS = ".codex/hooks.json"
CODEX_CONFIG = ".codex/config.toml"
# PreToolUse 的 matcher 不写、写空串、写 "*" 都是所有工具（Claude Code、Codex 的文档都这么说）；
# Codex 的 matcher 是正则，".*" 也是
MATCH_ALL = (None, "", "*", ".*")
REGENERATE = (
    "这是可选宿主集成；正常记录无需修复这一项。只有用户选择启用 hooks 时，"
    "才备份并合并 {file} 与 {keep} 的自定义设置，按 AI 接入指南适配并验证宿主；不要直接删除配置"
)
CODEX_TRUST = (
    "Codex 还要信任这个项目、在 Codex 里输入 /hooks 审过并信任这两个钩子才会运行它们"
    "（hooks.json 改过要重新审），这两步引擎查不到：在 Codex 里说一句话，"
    "再运行 hl doctor，“钩子在工作”那一项里有 codex 的消息才算好了"
)


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": passed, "detail": detail}


def _rule(rule: Any) -> Any:
    """Bash(hl:*) 和 Bash(hl *) 是同一条规则：:* 是旧写法（Claude Code 文档，2.1.289 仍认）。"""
    if isinstance(rule, str) and rule.endswith(":*)"):
        return rule[:-3] + " *)"
    return rule


def _json(ctx: Context, relative: str) -> tuple[dict[str, Any] | None, str | None]:
    """读一个 JSON 配置文件：(内容, 读不了时的原因)。不存在的内容是空表、原因是 None。"""
    try:
        text = (ctx.data_dir / relative).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"{relative} 读不了（{exc.strerror or exc}）"
    try:
        data = json.loads(text)
    except ValueError:
        return None, f"{relative} 不是合法的 JSON"
    if not isinstance(data, dict):
        return None, f"{relative} 不是一个 JSON 对象"
    return data, None


def _commands(group: Any) -> list[str]:
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return []
    return [
        handler["command"]
        for handler in group["hooks"]
        if isinstance(handler, dict) and isinstance(handler.get("command"), str)
    ]


def _calls_hook(handler: Any, command: str) -> bool:
    """只确认可静态核对的同步直接调用；不把注释、echo 或 shell 包装当成已经接好。"""
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    if handler.get("async", False) is not False:
        return False
    actual = handler.get("command")
    if not isinstance(actual, str) or any(mark in actual for mark in ("$", "`", "\n")):
        return False
    try:
        words = shlex.split(actual, comments=True)
        expected = shlex.split(command)
    except ValueError:
        return False
    if not words:
        return False
    executable = Path(words[0])
    if words[0] != "hl" and not (executable.is_absolute() and executable.name == "hl"):
        return False
    # shlex 保留参数的语义，允许可执行文件和参数加引号，也允许绝对 hl 路径。
    return words[1:] == expected[1:]


def _hook_gaps(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """模板里的每个钩子，实际的配置里都要有：同一个事件、调用同一条命令；
    模板的 matcher 盖住所有工具的，实际的也要盖住所有工具。"""
    gaps = []
    hooks = actual.get("hooks") if isinstance(actual.get("hooks"), dict) else {}
    for event, groups in expected["hooks"].items():
        present = hooks.get(event) if isinstance(hooks.get(event), list) else []
        for group in groups:
            for command in _commands(group):
                found = [
                    g
                    for g in present
                    if isinstance(g, dict)
                    and isinstance(g.get("hooks"), list)
                    and any(_calls_hook(handler, command) for handler in g["hooks"])
                ]
                if not found:
                    gaps.append(
                        f"{event} 里没有可确认的同步 command 钩子调用 {command}"
                        "（type 必须为 command、async 不得开启、参数须有效；"
                        "包装脚本或复合命令无法静态确认，请检查宿主实际运行结果）"
                    )
                elif group.get("matcher") in MATCH_ALL and not any(
                    g.get("matcher") in MATCH_ALL for g in found
                ):
                    matchers = "、".join(str(g.get("matcher")) for g in found)
                    gaps.append(f'{event} 的 matcher 是 {matchers}，只盖住一部分工具，要改成 "*"')
    return gaps


def _listed(rules: list[str]) -> str:
    shown = "、".join(rules[:3])
    return shown + (f" 等 {len(rules)} 条" if len(rules) > 3 else "")


def _claude(ctx: Context) -> dict[str, Any]:
    """Claude Code：.claude/settings.json 里有模板里的钩子、权限规则和设置。"""
    name = "Claude Code 的钩子配置"
    actual, unreadable = _json(ctx, CLAUDE_SETTINGS)
    if unreadable:
        return _check(name, False, unreadable)
    if actual is None:
        return _check(name, False, f"未配置可选集成 {CLAUDE_SETTINGS}；本项目正常记录不需要它")
    expected = json.loads(templates.template(CLAUDE_SETTINGS))
    gaps = _hook_gaps(actual, expected)
    permissions = actual.get("permissions") if isinstance(actual.get("permissions"), dict) else {}
    for kind, rules in expected["permissions"].items():
        have = permissions.get(kind) if isinstance(permissions.get(kind), list) else []
        if any(not isinstance(rule, str) for rule in have):
            gaps.append(f"permissions.{kind} 配置不正确：每条权限规则必须是字符串")
        have = {_rule(rule) for rule in have if isinstance(rule, str)}
        missing = [rule for rule in rules if _rule(rule) not in have]
        if missing:
            gaps.append(f"permissions.{kind} 里缺 {_listed(missing)}")
    for key, value in expected.items():
        if key not in ("permissions", "hooks") and actual.get(key) != value:
            gaps.append(f"没有设 {key} 为 {json.dumps(value)}")
    for relative in (CLAUDE_SETTINGS, CLAUDE_LOCAL):
        settings, _ = _json(ctx, relative)
        if settings and settings.get("disableAllHooks") is True:
            gaps.append(f"{relative} 里 disableAllHooks 是 true，所有钩子都不会运行；把它去掉")
    if gaps:
        regenerate = REGENERATE.format(file=CLAUDE_SETTINGS, keep=CLAUDE_LOCAL)
        return _check(name, False, f"{CLAUDE_SETTINGS}：{'；'.join(gaps)}。{regenerate}")
    return _check(
        name,
        True,
        f"{CLAUDE_SETTINGS} 里两个钩子、禁止直接读写账本的权限规则都在。"
        "在数据目录里启动 Claude Code 才读得到它；没信任过这个目录时 claude -p 不用里面的 "
        "allow 规则（钩子和 deny 规则照常），hl 命令要另外允许",
    )


def _codex(ctx: Context) -> dict[str, Any]:
    """Codex：.codex/hooks.json 里有模板里的钩子，.codex/config.toml 没有关掉钩子。"""
    name = "Codex 的钩子配置"
    actual, unreadable = _json(ctx, CODEX_HOOKS)
    if unreadable:
        return _check(name, False, unreadable)
    if actual is None:
        return _check(name, False, f"未配置可选集成 {CODEX_HOOKS}；本项目正常记录不需要它")
    expected = json.loads(templates.template(CODEX_HOOKS))
    gaps = [f"{CODEX_HOOKS}：{gap}" for gap in _hook_gaps(actual, expected)]
    try:
        settings = tomllib.loads((ctx.data_dir / CODEX_CONFIG).read_text(encoding="utf-8"))
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError):
        gaps.append(f"{CODEX_CONFIG} 读不了或者不是合法的 TOML")
        settings = {}
    gaps += [f"{CODEX_CONFIG}：{gap}" for gap in codex_permissions.gaps(settings)]
    features = settings.get("features") if isinstance(settings.get("features"), dict) else {}
    for key in ("hooks", "codex_hooks"):  # codex_hooks 是 hooks 的旧名，Codex 0.147 仍认
        if features.get(key) is False:
            gaps.append(f"{CODEX_CONFIG} 里 [features] {key} = false，钩子被关掉了")
    if gaps:
        regenerate = (
            "这是可选宿主集成，正常记录无需修复这一项；只有用户选择启用 hooks 时，"
            "才保留并合并自定义设置，按 AI 接入指南适配并验证宿主；init 不覆盖已有文件"
        )
        return _check(name, False, f"{'；'.join(gaps)}。{regenerate}。{CODEX_TRUST}")
    return _check(
        name,
        True,
        f"{CODEX_HOOKS} 里两个钩子都在，项目权限允许本地 Git 提交且保留配置目录只读。"
        f"更高层设置或启动时的 --sandbox 覆盖，本检查查不到。{CODEX_TRUST}",
    )
