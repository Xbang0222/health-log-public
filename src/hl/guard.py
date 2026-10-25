"""受保护路径的名单和判定：Agent 的一次工具调用是否在直接读写账本（R20，设计说明第 9 节）。"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from hl.configuration import values as configuration_values
from hl.storage import io as storage_io

# 受保护路径只在这里列一份：名字 → 拦截时指的路。文件工具的判定、命令文本的正则、
# hl init 建的目录和它生成的权限规则，都从这两张表取。
# 名字一律小写：文件工具的目标在比较前统一成小写。
PROTECTED_DIRS = {
    "log": "记录只能用 hl intent 修改，用 hl today、hl recent 查看",
    "foods": "用户库只能由 hl 写入：登记用 hl intent 的 food 操作，查看用 hl food list",
    storage_io.HIDDEN: "这是引擎内部文件，不能直接读写；用户原话收件箱只能由钩子写入",
}
PROTECTED_FILES = {
    storage_io.PLAN_FILE: "计划用 hl intent 的 plan 操作设定，用 hl plan show 查看",
    storage_io.DEFAULTS_FILE: ("默认品种用 hl intent 的 default 操作设定，variant:null 去掉"),
    configuration_values.CONFIG_NAME: "配置由 hl init、hl foods build 和 hl foods fetch 维护",
}
ADVICE = PROTECTED_DIRS | PROTECTED_FILES
ALLOWED_COMMANDS = ("hl", "git")
# 文件工具放路径的键：Claude Code 的 Read、Edit、Write（file_path）、NotebookEdit（notebook_path）、
# Grep（path），还有 MCP 工具常用的几种写法；值可以是一个路径，也可以是一串路径
PATH_KEYS = (
    *("file_path", "path", "notebook_path", "filePath", "dir_path", "directory"),
    *("file_paths", "paths", "source", "destination"),
)
PATTERN_KEYS = ("pattern", "glob")
COMMAND_KEYS = ("command", "cmd")  # 终端命令放在哪个键：多数工具是 command，也有写 cmd 的
# 会把别的话当成一轮新消息送回会话的工具（Claude Code 的名字）。
# 这些消息也经过 UserPromptSubmit 钩子，钩子分不出它们和用户说的话，进了收件箱就能当原话用（R2）：
# 后台子 Agent、工作流、后台盯着的命令结束时的报告，定时任务和 /loop 到点发出的提示，
# 别的会话发来的消息。记饮食用不着它们，hl init 的权限规则也把它们列入禁止。
PROMPT_TOOLS = ("Agent", "Workflow", "Monitor", "CronCreate", "ScheduleWakeup", "SendMessage")
OLD_TOOL_NAMES = ("Task",)  # Agent 的旧名：钩子照拦；权限规则写现在的名字 Agent
PROMPT_REASON = (
    "hl 拦截：在数据目录里不能用 {tool}。它的结果会被宿主程序当成一条新消息送回来，"
    "钩子分不出那是不是用户说的话，会被当成用户原话记进收件箱。"
    "要查什么用 hl 命令（hl today、hl plan show），要记的照用户说的原话用 hl intent。"
)
HOOK_REASON = (
    "hl 拦截：命令里不能出现 hl hook。它是钩子的入口，由 Agent 的宿主程序自己调用；"
    "用户原话只能由钩子写进收件箱。记饮食用 hl intent，原话照抄用户说的。"
)


def _either(names: dict[str, str]) -> str:
    return "|".join(re.escape(name) for name in names)


# 命令文本里的受保护路径：前面是开头、空白、引号或路径分隔符，后面是结尾或分隔符。
# 不看大小写：不区分大小写的文件系统上，LOG/ 和 log/ 是同一个目录
_MENTION = re.compile(
    r"""(?:^|(?<=[\s'"`=<>/(:,;|&]))"""
    rf"""(?:(?P<dir>{_either(PROTECTED_DIRS)})(?=$|[\s'"`/;|&)<>,])"""
    rf"""|(?P<file>{_either(PROTECTED_FILES)})(?=$|[\s'"`;|&)<>,]))""",
    re.IGNORECASE,
)
# 命令文本里的 hl hook：先去掉引号和反斜杠再找，hl 'hook'、折行的写法也认；不看大小写。
# hl 和 hook 之间夹着以 - 开头的参数（hl -- hook、hl --bogus hook），引擎照样当钩子跑，也认
_HOOK = re.compile(
    r"(?<![\w.-])(?:hl\.py|hl)(?:\s+(?:--data(?:=\S+|\s+\S+)|-\S*))*\s+hook(?![\w-])",
    re.IGNORECASE,
)
_QUOTING = re.compile(r"""['"\\]""")
# shell 的运算符，长的在前：连写的一串标点（;( 、&&( 、;> 、|&）照这张表一个个拆开
_OPERATORS = (
    *(";;&", "&>>", "<<<"),
    *(";;", ";&", "&&", "||", "|&", "&>", ">&", "<&", ">>", "<<", "<>", ">|"),
    *(";", "|", "&", "(", ")", "<", ">"),
)
_SEPARATORS = {";;&", ";;", ";&", "&&", "||", "|&", ";", "|", "&", "(", ")"}  # 这些断开一段命令
_REDIRECTS = set(_OPERATORS) - _SEPARATORS
_PUNCTUATION = set("();<>|&")
_WORD_BREAKS = " \t\n;|&()<>"  # shell 里一个词到这些字符为止
_CLOSERS = {"{": "}", "(": ")", "[": "]"}
# 这几种写法引擎拆不准（嵌套的命令、$'…' 里的转义），碰到受保护路径就直接拦
_OPAQUE = ("`", "$(", "$'")


def _blocked(name: str, target: str) -> str:
    return f"hl 拦截：不能直接读写受保护的路径 {target}。{ADVICE[name]}。"


def _folded(path: Path) -> Path:
    """解开符号链接，统一成小写：不区分大小写的文件系统上，LOG/ 和 log/ 是同一个目录。"""
    return Path(os.path.realpath(path).casefold())


def path_reason(base: Path, cwd: Path, target: str) -> str | None:
    """文件工具的目标落在受保护路径内时，返回拦截理由。"""
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        parts = _folded(path).relative_to(_folded(base)).parts
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] in PROTECTED_DIRS or (len(parts) == 1 and parts[0] in PROTECTED_FILES):
        return _blocked(parts[0], target)
    return None


def mention(text: str) -> str | None:
    """文本里出现的第一个受保护路径的名字；没有则为 None。"""
    found = _MENTION.search(text)
    return (found.group("dir") or found.group("file")).casefold() if found else None


def _uncommented(command: str) -> str:
    """去掉 # 注释，把引号外面的换行换成 ;，好交给 shlex 拆词。

    和 shell 一样：# 在词首才是注释，只到本行结尾；引号里的、词中间的（a#b）不是，
    ${…}、((…))、a[…] 里面的也不是。
    shlex 自带的注释处理不分这些，换行没了还会把后面的命令一起吞掉，所以不用它。
    """
    out: list[str] = []
    quote = ""  # 正在哪种引号里；不在引号里是空串
    nest: list[str] = []  # 还没合上的 ${、((、a[，记的是各自的收尾字符
    word_start = True
    at = 0
    while at < len(command):
        char = command[at]
        if char == "\\" and quote != "'" and at + 1 < len(command):
            if command[at + 1] != "\n" or quote:  # 引号外的反斜杠加换行是续行，两个都去掉
                out.append(command[at : at + 2])
                word_start = False
            at += 2
            continue
        if quote:
            quote = "" if char == quote else quote
            out.append(char)
        elif char == "#" and word_start and not nest:
            end = command.find("\n", at)
            at = len(command) if end < 0 else end
            continue
        elif char == "\n":
            out.append(" ; ")
            word_start = True
        else:
            quote = char if char in "'\"" else ""
            before = command[at - 1] if at else ""
            opens = {"{": before == "$", "(": before == "(", "[": before.isalnum() or before == "_"}
            if opens.get(char):
                nest.append(_CLOSERS[char])
            elif nest and char == nest[-1] and (char != ")" or before == ")"):
                nest.pop()
            out.append(char)
            word_start = char in _WORD_BREAKS
        at += 1
    return "".join(out)


def _operators(token: str) -> list[str]:
    """把一串连写的标点拆成一个个运算符：;( 是 ; 和 (，;> 是 ; 和 >。"""
    found = []
    at = 0
    while at < len(token):
        found.append(next(op for op in _OPERATORS if token.startswith(op, at)))
        at += len(found[-1])
    return found


def _segments(command: str) -> list[list[str]]:
    """把一条终端命令按 ; && || | & ( ) 和换行拆成若干段，每段是一串词（重定向符号也算一个词）。"""
    lexer = shlex.shlex(_uncommented(command), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    for token in lexer:
        if not set(token) <= _PUNCTUATION:
            segments[-1].append(token)
            continue
        for operator in _operators(token):
            if operator in _SEPARATORS:
                segments.append([])
            else:
                segments[-1].append(operator)
    return [segment for segment in segments if segment]


def command_reason(command: str) -> str | None:
    """终端命令该不该拦。

    出现 hl hook 一律拦；出现受保护路径、那一段又不是以 hl 或 git 开头，也拦。
    """
    if _HOOK.search(_QUOTING.sub("", command)):
        return HOOK_REASON
    # 引号、反斜杠拆开的名字（lo""g、l\og）shell 照样拼回去，去掉它们再找一遍
    name = mention(command) or mention(_QUOTING.sub("", command))
    if name is None:
        return None
    if any(mark in command for mark in _OPAQUE):
        return _blocked(name, name) + "涉及这些路径的命令里不能用 `…`、$(…)、$'…' 这些写法。"
    for segment in _segments(command):
        hit = mention(" ".join(segment))
        if hit is None:
            continue
        if segment[0] not in ALLOWED_COMMANDS or _redirects_into_protected(segment):
            return _blocked(hit, hit)
    return None


def _redirects_into_protected(segment: list[str]) -> bool:
    """这一段有没有把输入输出重定向到受保护路径（例如 hl today > log/x.yaml）。"""
    for token, target in zip(segment, segment[1:], strict=False):
        if token in _REDIRECTS and mention(target):
            return True
    return False


# Codex 的 apply_patch 把整个补丁放在 tool_input.command 里，每个文件一行头：
# *** Add File: <路径>、*** Update File: <路径>、*** Delete File: <路径>，
# 改名的在 Update File 下面再跟一行 *** Move to: <新路径>
_PATCH_HEADER = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE
)


def patch_reason(base: Path, cwd: Path, patch: str) -> str | None:
    """apply_patch 的补丁要改的文件里有受保护路径时，返回拦截理由。

    只看文件头里的路径，不看补丁的内容：改一份说明文档、内容里写着 log/ 的照常放行。
    一个文件头都找不到的（写法不对，或者不是补丁），退回去按终端命令的文本看。
    """
    targets = _PATCH_HEADER.findall(patch)
    if not targets:
        return command_reason(patch)
    for target in targets:
        if reason := path_reason(base, cwd, target):
            return reason
    return None


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _command_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        wrapped = len(value) == 3 and value[1] in ("-c", "-lc")
        return value[2] if wrapped else " ".join(value)
    return None


def tool_reason(
    base: Path, cwd: Path, tool_input: dict[str, Any], tool_name: str = ""
) -> str | None:
    """一次工具调用该不该拦。放行返回 None，拦截返回要写到标准错误的理由。

    tool_name 是钩子输入里的工具名：会把别的话当成新消息送回来的工具一律拦；
    Codex 的 apply_patch 按补丁的文件头看要改哪些文件。
    """
    if tool_name in PROMPT_TOOLS or tool_name in OLD_TOOL_NAMES:
        return PROMPT_REASON.format(tool=tool_name)
    command = next(
        (text for key in COMMAND_KEYS if (text := _command_text(tool_input.get(key))) is not None),
        None,
    )
    if command is not None:
        if tool_name == "apply_patch":
            return patch_reason(base, cwd, command)
        return command_reason(command)
    for key in PATH_KEYS:
        for target in _paths(tool_input.get(key)):
            if reason := path_reason(base, cwd, target):
                return reason
    for key in PATTERN_KEYS:
        pattern = tool_input.get(key)
        if isinstance(pattern, str) and (name := mention(pattern)):
            return _blocked(name, pattern)
    return None
