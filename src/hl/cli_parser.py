"""命令参数声明与 argparse 错误转译；执行和输出留在 cli。"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, NoReturn

from hl.commands import (
    food_search,
)

# argparse 的英文报错 → 中文
MESSAGES = (
    (r"the following arguments are required: (.+)", r"缺少必须的参数：\1"),
    (r"unrecognized arguments: (.+)", r"多了不认识的参数：\1"),
    (r"argument (.+): expected one argument", r"参数 \1 后面要跟一个值"),
    (r"argument (.+): invalid float value: (.+)", r"参数 \1 要填数字，现在是 \2"),
    (r"argument (.+): invalid int value: (.+)", r"参数 \1 要填整数，现在是 \2"),
    (r"argument (.+): invalid choice: (.+) \(choose from (.+)\)", r"\1 不能是 \2，只能是：\3"),
)

HOOKS = {"user-prompt": "把用户原话写进收件箱", "pre-tool": "拦截对受保护路径的直接读写"}

DATE, SAID = "YYYY-MM-DD", "原话"

DATE_HELP, SAID_HELP, JSON_HELP = "默认今天", "用户说的原话，照抄", "输入的 JSON 对象"

RETIRED = {
    ("add", None),
    ("undo", None),
    ("weight", None),
    ("default", None),
    ("food", "add"),
    ("plan", "set"),
    ("day", "set"),
    ("manifest", "rebuild"),
}
RETIRED_HINT = (
    "旧写入口已退役；日常写入使用 intent --json 的结构化契约，读取 HEALTH_LOG_V2.md"
    "（缺少时读取 AGENTS.md）。完整性损坏按 check 的当前诊断恢复，不重建或重签来绕过校验。"
)


def retired_route(argv: list[str]) -> bool:
    """识别旧入口，只用于给出兼容拒绝；不读取账本或解析旧写入协议。"""
    words = list(argv)
    while words:
        if words[0] == "--data":
            words = words[2:]
        elif words[0].startswith("--data="):
            words = words[1:]
        else:
            break
    return bool(words) and ((words[0], None) in RETIRED or (tuple(words[:2]) in RETIRED))


def _retired(commands: Any, name: str) -> None:
    commands.add_parser(name, help="已退役；请用 intent", description=RETIRED_HINT)


class _Usage(Exception):
    """命令行写错了。"""

    def __init__(self, message: str, usage: str) -> None:
        for pattern, chinese in MESSAGES:
            message = re.sub(pattern, chinese, message)
        super().__init__(message)
        self.usage = " ".join(usage.removeprefix("usage: ").split())


class _Exit(Exception):
    """argparse 想结束进程（例如 --help）；带上它要的退出码。"""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """不自己结束进程的解析器：出错和退出都变成异常，交给 main 处理。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.color = False  # 用法说明要放进 JSON，不能带终端颜色码

    def error(self, message: str) -> NoReturn:
        raise _Usage(message, self.format_usage().strip())

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _Exit(status)

    def parse_known_args(
        self, args: list[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> tuple[argparse.Namespace, list[str]]:
        # shell 的引号到 argv 时已消失。仅把原话参数的连字符值绑定成 --said=原话；
        # 当前子命令的真实选项仍交给 argparse，不能把缺值后的 --confirm 等吞掉。
        given = list(sys.argv[1:] if args is None else args)
        bound = []
        pos = 0
        while pos < len(given):
            word = given[pos]
            if (
                word in ("--said", "--answer")
                and word in self._option_string_actions
                and pos + 1 < len(given)
                and given[pos + 1].startswith("-")
                and given[pos + 1] != "--"
                and given[pos + 1].split("=", 1)[0] not in self._option_string_actions
            ):
                bound.append(f"{word}={given[pos + 1]}")
                pos += 2
            else:
                bound.append(word)
                pos += 1
        return super().parse_known_args(bound, namespace)


def _group(commands: Any, name: str, text: str) -> Any:
    """带二级子命令的命令（例如 hl plan set）。"""
    return commands.add_parser(name, help=text).add_subparsers(dest="action", required=True)


def _parser() -> _Parser:
    about = "health-log：记账式饮食记录引擎。每条命令输出一个 JSON 对象。"
    parser = _Parser(prog="hl", description=about)
    parser.add_argument("--data", metavar="目录", help="持久账本目录（优先于 HL_DATA）")
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")

    one = commands.add_parser("init", help="生成数据目录，可重复执行")
    one.add_argument(
        "dir",
        nargs="?",
        metavar="目录",
        help="源码脚本默认本项目；裸安装 hl 默认 HL_DATA 或 ~/health-data",
    )
    one.add_argument("--hooks", action="store_true", help="额外安装可选宿主 hooks")

    one = commands.add_parser("intent", help="提交结构化意图（唯一日常写入口）")
    group = one.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", dest="payload", metavar="JSON")
    group.add_argument("--file", metavar="文件", help="JSON 文件，- 从标准输入读")
    for name in ("recent", "history"):
        one = commands.add_parser(
            name, help="查询目标与版本" if name == "recent" else "查询更改历史"
        )
        one.add_argument("--limit", type=int, default=20)
        if name == "history":
            one.add_argument("--request-id")
    one = commands.add_parser("find", help="按关键词、日期、餐次查记录或更改历史")
    one.add_argument("words", nargs="+", metavar="关键词")
    one.add_argument("--from", dest="start")
    one.add_argument("--to", dest="end")
    one.add_argument("--meal", choices=("早餐", "午餐", "晚餐", "加餐"))
    one.add_argument("--limit", type=int, default=50)
    one.add_argument("--history", action="store_true")
    one = commands.add_parser("migrate", help="旧账本预检，--apply 完整备份后升级")
    one.add_argument("--apply", action="store_true")

    foods = _group(commands, "foods", "成分表和薄荷库的副本")
    build_help = "把原始数据（成分表的 .json 或薄荷库的 all.csv 所在目录）整理成本地副本"
    one = foods.add_parser("build", help=build_help)
    one.add_argument("raw_dir", metavar="原始数据目录")
    foods.add_parser("fetch", help="下载固定版本的成分表和薄荷库，核对校验值后整理成本地副本")

    library = _group(commands, "food", "用户库（自己登记的食物、存下的估算），在库里找条目")
    _retired(library, "add")
    library.add_parser("list", help="列出用户库里的条目")
    search_help = "在用户库、常用食物和菜谱、成分表、薄荷库里找条目（只读）"
    one = library.add_parser("search", help=search_help)
    one.add_argument("words", nargs="+", metavar="词", help="要找的食物名，几个词时要都对得上")
    limit_help = f"最多列几条，默认 {food_search.LIMIT}"
    one.add_argument("--limit", type=int, default=food_search.LIMIT, metavar="N", help=limit_help)

    hooks = _group(commands, "hook", "钩子入口")
    for name, text in HOOKS.items():
        one = hooks.add_parser(name, help=text)
        one.add_argument("--agent", default="unknown", help="Agent 名称")

    _retired(commands, "add")

    one = commands.add_parser("today", help="今日已吃、目标、还差多少、可以吃什么")
    one.add_argument("--date", metavar=DATE, help=DATE_HELP)

    one = commands.add_parser("report", help="一段时间的汇总：逐天的账、平均值、体重按周的变化")
    one.add_argument("--days", type=int, metavar="N", help="最近 N 天（含今天），默认 7")
    one.add_argument("--from", dest="start", metavar=DATE, help="从哪天起；和 --days 二选一")
    one.add_argument("--to", dest="end", metavar=DATE, help="到哪天为止，默认今天")

    for name in ("undo", "weight", "default"):
        _retired(commands, name)
    plans = _group(commands, "plan", "查看计划；旧 set 已退役")
    _retired(plans, "set")
    one = plans.add_parser("show", help="查看计划")
    one.add_argument("--date", metavar=DATE, help=DATE_HELP)
    days = _group(commands, "day", "已退役；请用 intent")
    _retired(days, "set")
    manifests = _group(commands, "manifest", "已退役；按 check 诊断恢复")
    _retired(manifests, "rebuild")

    one = commands.add_parser("ref", help="参考范围表：只供查看，不写进计划")
    kg_help = "用户自己说的体重（公斤）；按体重给的范围顺带换算成克"
    one.add_argument("--kg", type=float, metavar="数字", help=kg_help)

    commands.add_parser("check", help="全库校验")
    commands.add_parser("doctor", help="安装自检")
    return parser
