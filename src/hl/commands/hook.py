"""hl hook user-prompt / pre-tool：两种 Agent 共用的钩子入口（R20，设计说明第 9 节）。

钩子按 Agent 的钩子协议工作，不输出 JSON：
user-prompt 不写标准输出、退出码永远是 0；pre-tool 放行为 0，拦截或自身出错为 2，理由写在标准错误。
退出码 2 加标准错误在 Claude Code（2.1.289）和 Codex（0.147）里都是拦下这次工具调用、
把理由交给模型；别的非零退出码两边都只算钩子自己失败，照样放行，所以出错也用 2。
"""

from __future__ import annotations

import contextlib
import json
import re
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from hl import guard
from hl.configuration import read as configuration_read
from hl.configuration import values as configuration_values
from hl.origins import inbox as origins_inbox
from hl.storage import io as storage_io

ALLOW, BLOCK = 0, 2
ERROR_LOG = "hook-errors.log"
# Claude Code 把后台任务（子 Agent、后台命令、工作流）结束时的报告也当成一轮新消息交给
# UserPromptSubmit 钩子，整段包在 <task-notification> 里。里面的话是模型和程序写的，不是用户说的，
# 不进收件箱（R2）。没有收尾标签的，从开头标签一直算到末尾。
_NOTIFICATION = re.compile(r"<task-notification>.*?(?:</task-notification>|\Z)", re.DOTALL)


def _user_words(prompt: str) -> str:
    """去掉宿主程序自己生成的后台任务报告，剩下的才是用户说的话；全是报告的剩下空串。"""
    if "<task-notification>" not in prompt:
        return prompt
    return _NOTIFICATION.sub("", prompt).strip()


def _payload(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("钩子输入不是 JSON 对象")
    return payload


def _input_cwd(payload: Mapping[str, Any], cwd: Path) -> Path:
    given = payload.get("cwd")
    return Path(given) if isinstance(given, str) and given else cwd


def _log_error(
    data_dir: Path | None, name: str, exc: Exception, environ: Mapping[str, str]
) -> None:
    """钩子自身的错误记到 .hl/hook-errors.log；连这一步也失败就只能放弃。"""
    if data_dir is None:
        return
    with contextlib.suppress(Exception):
        path = data_dir / storage_io.HIDDEN / ERROR_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        trace = "".join(traceback.format_exception(exc))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{configuration_values.now(environ).isoformat()} {name}\n{trace}\n")


def user_prompt(agent: str, environ: Mapping[str, str], cwd: Path, stdin: TextIO) -> int:
    """把用户原话追加到收件箱。无论发生什么都不写标准输出，退出码永远是 0。"""
    data_dir = None
    try:
        data_dir = configuration_read.find_data_dir(environ, cwd)
        payload = _payload(stdin.read())
        data_dir = configuration_read.find_data_dir(environ, _input_cwd(payload, cwd), cwd)
        if data_dir is None:
            return ALLOW
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("钩子输入里没有 prompt 字段")
        said = _user_words(prompt)
        if not said:  # 整条都是后台任务的报告：用户什么也没说
            return ALLOW
        record = {
            "ts": configuration_values.now(environ).isoformat(),
            "text": said,
            "agent": agent,
            "session": str(payload.get("session_id", "")),
        }
        with storage_io.locked(data_dir):
            origins_inbox.append(data_dir, record)
    except Exception as exc:  # 钩子绝不能打断用户的对话
        _log_error(data_dir, "user-prompt", exc, environ)
    return ALLOW


def pre_tool(environ: Mapping[str, str], cwd: Path, stdin: TextIO, stderr: TextIO) -> int:
    """拦截对受保护路径的直接读写。自身出任何异常也拦截：宁可误拦，不可放行。"""
    data_dir = None
    try:
        data_dir = configuration_read.find_data_dir(environ, cwd)
        payload = _payload(stdin.read())
        work_dir = _input_cwd(payload, cwd)
        data_dir = configuration_read.find_data_dir(environ, work_dir, cwd)
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            raise ValueError("钩子输入里没有 tool_input 字段")
        tool_name = payload.get("tool_name")
        tool_name = tool_name if isinstance(tool_name, str) else ""
        reason = guard.tool_reason(data_dir or work_dir, work_dir, tool_input, tool_name)
    except Exception as exc:  # 见上：自身出错按拦截处理
        _log_error(data_dir, "pre-tool", exc, environ)
        stderr.write(f"hl hook pre-tool 自身出错，按规则先拦截这次操作：{exc!r}\n")
        return BLOCK
    if reason is None:
        return ALLOW
    stderr.write(reason + "\n")
    return BLOCK


def _anywhere(environ: Mapping[str, str], stdin: TextIO) -> Path | None:
    """出了错也尽力找到数据目录，好把错误记进去：HL_DATA、输入的 cwd、当前目录，能用哪个用哪个。"""
    starts: list[Path] = []
    with contextlib.suppress(Exception):
        given = _payload(stdin.read()).get("cwd")
        if isinstance(given, str) and given:
            starts.append(Path(given))
    with contextlib.suppress(Exception):
        starts.append(Path.cwd())
    with contextlib.suppress(Exception):
        return configuration_read.find_data_dir(environ, *starts)
    return None


def failed(
    name: str, exc: Exception, environ: Mapping[str, str], stdin: TextIO, stderr: TextIO
) -> int:
    """钩子还没开始干活就出了错（命令行写错、当前目录不存在）：照样按钩子协议收尾。

    user-prompt 不输出、退出码 0；pre-tool 把原因写到标准错误、退出码 2。
    """
    _log_error(_anywhere(environ, stdin), name, exc, environ)
    if name == "user-prompt":
        return ALLOW
    with contextlib.suppress(Exception):
        stderr.write(f"hl hook pre-tool 自身出错，按规则先拦截这次操作：{exc}\n")
    return BLOCK
