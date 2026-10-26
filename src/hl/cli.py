"""参数解析和分发；整个引擎里唯一结束进程的地方。

main(argv) 向标准输出打印恰好一个 JSON 对象并返回退出码；
hl hook 两个子命令是例外，按 Agent 的钩子协议工作。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from hl.cli_parser import DATE as DATE
from hl.cli_parser import DATE_HELP as DATE_HELP
from hl.cli_parser import HOOKS as HOOKS
from hl.cli_parser import JSON_HELP as JSON_HELP
from hl.cli_parser import MESSAGES as MESSAGES
from hl.cli_parser import RETIRED, RETIRED_HINT, retired_route
from hl.cli_parser import SAID as SAID
from hl.cli_parser import SAID_HELP as SAID_HELP
from hl.cli_parser import _Exit as _Exit
from hl.cli_parser import _group as _group
from hl.cli_parser import _Parser as _Parser
from hl.cli_parser import _parser as _parser
from hl.cli_parser import _Usage as _Usage
from hl.commands import (
    check,
    doctor,
    food,
    food_search,
    foods_build,
    foods_fetch,
    hook,
    init,
    plan,
    ref,
    report,
    today,
)
from hl.configuration import read as configuration_read
from hl.configuration.values import Context
from hl.intents import migration
from hl.intents import query as intent_query
from hl.intents import service as intent_service
from hl.intents import state as intent_state
from hl.manifests import model as manifests_model
from hl.result import Abort, Result, error, problem, rejected
from hl.storage import git_state as storage_git_state
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys
from hl.storage import transactions

Handler = Callable[[Context, argparse.Namespace], Result]


def retired(ctx=None, args=None):
    return rejected(
        [
            problem(
                "command",
                "旧原话裁决写入口已退役",
                RETIRED_HINT,
            )
        ]
    )


HANDLERS: dict[tuple[str, str | None], Handler] = {
    ("intent", None): intent_service.run,
    ("recent", None): intent_query.recent,
    ("history", None): intent_query.history,
    ("find", None): intent_query.find,
    ("migrate", None): migration.run,
    ("foods", "build"): foods_build.run,
    ("foods", "fetch"): foods_fetch.run,
    ("food", "list"): food.list_foods,
    ("food", "search"): food_search.run,
    ("today", None): today.run,
    ("report", None): report.run,
    ("plan", "show"): plan.show_plan,
    ("check", None): check.run,
    ("doctor", None): doctor.run,
    **dict.fromkeys(RETIRED, retired),
}

# 会写数据目录的命令：git 操作做到一半时一律拒绝（规则 19）。hl init 另外查
WRITES = {
    ("intent", None),
    ("migrate", None),
    ("foods", "build"),
    ("foods", "fetch"),
}


def _utf8(stream: Any) -> None:
    """标准输入输出的编码不是 UTF-8 时改成 UTF-8。

    进出的都是带中文的 JSON；PYTHONIOENCODING=ascii 之类的环境里不能因此打不出结果（R1）。
    """
    encoding = (getattr(stream, "encoding", None) or "").replace("-", "").replace("_", "")
    if encoding.lower() != "utf8" and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def _hook_name(argv: list[str]) -> str | None:
    """这次调用的是哪个钩子入口；不是钩子返回 None。参数写错了也要认得出来。

    看第一个不以 - 开头的词：它是 hook、后面又有入口名，就是钩子（hl --bogus hook pre-tool 也算）。
    """
    pos = 0
    while pos < len(argv):
        arg = argv[pos]
        if arg == "--data":
            pos += 2
            continue
        if arg.startswith("-"):
            pos += 1
            continue
        if arg != "hook":
            return None
        return next((word for word in argv[pos + 1 :] if word in HOOKS), None)
    return None


def _run_hook(name: str, argv: list[str]) -> int:
    """钩子入口不走输出契约：命令行写错、当前目录不存在，也按钩子协议收尾（第 9 节）。"""
    environ = dict(os.environ)
    try:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            _utf8(stream)
        # hook 前面的 “--”：各版本 argparse 处理不一样（3.12.3 把它当成命令名），先去掉
        first = argv.index("hook")
        args = _parser().parse_args([arg for arg in argv[:first] if arg != "--"] + argv[first:])
        cwd = Path.cwd()
        if args.data:
            environ["HL_DATA"] = args.data
        if name == "user-prompt":
            return hook.user_prompt(args.agent, environ, cwd, sys.stdin)
        return hook.pre_tool(environ, cwd, sys.stdin, sys.stderr)
    except _Exit as stop:
        return stop.code
    except Exception as exc:
        return hook.failed(name, exc, environ, sys.stdin, sys.stderr)


def _inside(data_dir: Path, exc: OSError) -> str | None:
    """读写失败的那个文件相对数据目录的路径；不在数据目录里返回 None。"""
    for name in (exc.filename2, exc.filename):  # os.replace 失败时 filename2 才是要写的那个文件
        if isinstance(name, (str, os.PathLike)):
            try:
                return Path(name).resolve().relative_to(data_dir.resolve()).as_posix()
            except ValueError:
                continue
    return None


def _execute(args: argparse.Namespace) -> Result:
    environ = dict(os.environ)
    if args.data:
        environ["HL_DATA"] = args.data
    if args.command == "init":
        return init.run(args.dir, environ, Path.cwd(), hooks=args.hooks)
    if args.command == "intent" and args.file:
        args.payload = (
            sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        )
    if args.command == "ref":  # 只读引擎自带的参考范围表，用不着数据目录
        return ref.run(args)
    command = (args.command, getattr(args, "action", None))
    handler = HANDLERS[command]
    if command in RETIRED:
        return retired()
    ctx = configuration_read.load(environ, Path.cwd())
    if command in WRITES and not ctx.no_git:
        refused = storage_git_state.refuse_unfinished(
            ctx.data_dir
        )  # 自动提交关着也查：放弃时照样抹掉
        if refused is not None:
            return refused
    try:
        with storage_io.locked(ctx.data_dir):
            key = storage_keys.secret(ctx.data_dir)
            transactions.recover(ctx.data_dir, key)
            ctx = configuration_read.load(environ, Path.cwd())
            if ctx.settings["format"] == 2 and args.command not in ("doctor", "migrate"):
                intent_state.load(ctx, key)
            return handler(ctx, args)
    except OSError as exc:  # 数据目录里哪个文件读写不了（是个目录、没有权限）：说出是哪个
        where = _inside(ctx.data_dir, exc)
        if where is None:
            raise
        what = f"读写不了（{exc.strerror or type(exc).__name__}）：它是个目录，或者没有读写的权限"
        return rejected([problem(where, what, storage_io.FIX_OS)], manifests_model.NEXT_DATA)


def _emit(result: Result) -> int:
    """打印结果，返回退出码。

    结果里带着写不成 UTF-8 的字符（参数里落单的代理项、非法字节）时，退回全转义的 JSON：
    无论如何都要打印出一个 JSON（R1）。
    """
    body = result.to_json()
    text = json.dumps(body, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(body, ensure_ascii=True)
    print(text)
    return result.exit_code


def main(argv: list[str]) -> int:
    """执行一条命令：打印恰好一个 JSON 对象，返回退出码。"""
    name = _hook_name(argv)
    if name is not None:
        return _run_hook(name, argv)
    _utf8(sys.stdin)
    _utf8(sys.stdout)
    try:
        args = _parser().parse_args(argv)
    except _Exit as stop:
        return stop.code
    except _Usage as wrong:
        if retired_route(argv):
            return _emit(retired())
        fix = f"按这个用法重写命令：{wrong.usage}"
        return _emit(rejected([problem("命令行", f"命令行参数不对：{wrong}", fix)]))
    try:
        result = _execute(args)
    except Abort as stop:
        result = stop.result
    except Exception as exc:  # 引擎自身出错也要给出结构化的结果
        result = error(f"引擎内部错误：{type(exc).__name__}: {exc}")
    return _emit(result)


def run() -> NoReturn:
    """控制台脚本 hl 的入口。"""
    sys.exit(main(sys.argv[1:]))
