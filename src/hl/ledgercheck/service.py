"""hl check：全库校验（R21）。有问题返回 rejected，where 是相对数据目录的文件路径。

引擎自带的概念表和菜谱也在这里校验（增补第 13.4 节）：它们坏了是引擎的问题，返回 error。
"""

from __future__ import annotations

import argparse
import json

from hl import pending, sources
from hl.configuration.values import Context
from hl.foods import concept_types as foods_concept_types
from hl.foods import concepts as foods_concepts
from hl.foods import custom as foods_custom
from hl.foods import lint as foods_lint
from hl.foods import table as foods_table
from hl.foods import table_io as foods_table_io
from hl.foods import table_types as foods_table_types
from hl.ledgercheck import days as ledgercheck_days
from hl.ledgercheck import defaults as ledgercheck_defaults
from hl.ledgercheck import messages as ledgercheck_messages
from hl.ledgercheck import paths as ledgercheck_paths
from hl.ledgercheck import plans as ledgercheck_plans
from hl.ledgercheck import protocol as ledgercheck_protocol
from hl.ledgercheck import scan as ledgercheck_scan
from hl.manifests import io as manifests_io
from hl.origins import inbox as origins_inbox
from hl.preparation import settings as preparation_settings
from hl.result import Abort, Result, error, ok, problem, rejected
from hl.storage import days as storage_days
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys

# 用当初那个目录重建还是缺：要换一份完整的原始数据，只有装 hl 的人知道在哪
FIX_ENGINE = (
    "成分表副本里缺这个编码，多半是构建时用的原始数据不完整：把这一条原样告诉用户，"
    "请装 hl 的人用完整的原始数据运行 hl foods build 重新构建；重建之后还缺，就是引擎自带数据的"
    "问题。你就此停下，不要自己找目录，也不要自己改文件"
)


def _table_errors(ctx: Context) -> tuple[foods_table_types.Table | None, list[dict[str, str]]]:
    if not ctx.foods_sha and not foods_table_io.path(ctx.data_dir).exists():
        return {}, []
    try:
        return foods_table_io.load(ctx.data_dir, ctx.foods_sha), []
    except foods_table_io.TableError as exc:
        return None, [problem(foods_table_io.WHERE, str(exc), foods_table.fix(exc, ctx.data_dir))]


def _reference_errors(
    index: foods_concept_types.Index, foods: foods_table_types.Table
) -> list[dict[str, str]]:
    """概念表和菜谱在引擎包里，不在数据目录：where 指到数据目录里对不上的那一头，成分表副本。"""
    return [
        problem(
            foods_table_io.WHERE,
            f"引擎自带的 {source} 里，{label}引用的编码 {code} 不在成分表副本里",
            FIX_ENGINE,
        )
        for source, label, code in foods_concepts.references(index)
        if code not in foods
    ]


def _internal_errors(ctx: Context) -> list[dict[str, str]]:
    """引擎自己的文件（待确认事项、记过的原话、收件箱）读不了：各条命令都会被它卡住，一起列出。"""
    errors = []
    for name in (pending.FILE, pending.RECORDED, origins_inbox.INBOX):
        try:
            with (ctx.data_dir / storage_io.HIDDEN / name).open("rb"):
                pass
        except FileNotFoundError:
            continue
        except OSError:
            errors.append(
                problem(f"{storage_io.HIDDEN}/{name}", storage_io.UNREADABLE, storage_io.FIX_OS)
            )
    return errors


def _inbox_warnings(ctx: Context) -> list[str]:
    """收件箱里读不出来的行引擎跳过了，不算问题（R2）；但用户在那几行说的话抄不到，说给用户听。"""
    try:
        lines = origins_inbox.damaged(ctx.data_dir)
    except OSError:
        return []  # 整个收件箱读不了：_internal_errors 已经报了
    if not lines:
        return []
    shown = "、".join(str(n) for n in lines)
    return [
        f"用户原话收件箱 {storage_io.HIDDEN}/{origins_inbox.INBOX} 第 {shown} 行读不出来"
        "（不是合法的 UTF-8，或者不是引擎写的格式），引擎跳过了这几行：用户在那里说的话不能当原话用"
    ]


RECORDED = f"{storage_io.HIDDEN}/{pending.RECORDED}"
FIX_BUSY = (
    "别的 hl 命令正在写数据目录：等它结束再运行 hl check，引擎会照清单里记着的补回。"
    "这是引擎自己的文件，不要手工改"
)


def _sources(ctx: Context, listed: dict | None) -> tuple[list[dict[str, str]], list[str]]:
    """recorded.json 丢了、被清空、换回了旧的（少了清单里记着的出处）：拿得到锁就照清单补回，
    说给用户听；别的命令正拿着锁，先报出来（K-3）。返回（问题，提醒）。"""
    if listed is None or not sources.missing(ctx.data_dir, listed):
        return [], []
    with storage_io.try_locked(ctx.data_dir) as got:
        count = sources.restore(ctx.data_dir, listed) if got else 0
    if count:
        told = (
            f"记过的原话出自哪里（{RECORDED}）少了 {count} 条（文件丢了、被清空或换回了旧的），"
            "已照清单里记着的补回：同一条消息里的话再拿来记，引擎照样认得出记过"
        )
        return [], [told]
    lost = len(sources.missing(ctx.data_dir, listed))
    if not lost:
        return [], []
    return [problem(RECORDED, f"记过的原话出自哪里少了 {lost} 条，清单里还记着", FIX_BUSY)], []


def run(ctx: Context, args: argparse.Namespace) -> Result:
    # 这里不能拿 store.locked：自动提交在锁里触发 pre-commit，pre-commit 另起进程跑的就是这条命令
    key = storage_keys.secret(ctx.data_dir)
    foods, errors = _table_errors(ctx)
    # 成分表副本里缺的编码多半是用户构建时的原始数据不全，下面照 R21 报给用户，这里不报
    broken = foods_lint.errors(foods=foods, missing=False)
    if broken:
        return error(f"{foods_concepts.describe()}有 {len(broken)} 处问题：" + "；".join(broken))
    index = foods_concepts.load()
    if foods:
        errors += _reference_errors(index, foods)
    listed, found = manifests_io.read(ctx.data_dir, key)
    errors += found
    errors += ledgercheck_protocol.legacy_errors(ctx)
    if (
        getattr(args, "read_only", False)
        and listed is not None
        and sources.missing(ctx.data_dir, listed)
    ):
        found, restored = (
            [problem(RECORDED, "出处索引缺失，预检不自动修复", "先运行 check 检查并恢复出处索引")],
            [],
        )
    else:
        found, restored = _sources(ctx, listed)
    errors += found
    defaults, found = ledgercheck_defaults.read_defaults_file(ctx.data_dir, key)
    errors += found
    stale = ledgercheck_defaults.stale_defaults(index, defaults)
    errors += ledgercheck_defaults.read_suggest_file(ctx.data_dir, index)[1]
    errors += preparation_settings.read_file(ctx.data_dir)[1]  # 做法估算的油盐比例（增补第 10 节）
    errors += ledgercheck_plans.read_plan_file(ctx.data_dir, key)[1]
    errors += foods_custom.problems(ctx.data_dir, key)
    # log/ 下的每一项都看；打不开的、符号链接后面的，清单里记着的日子照规范的路径再读一遍
    scan = storage_days.scan_log(ctx.data_dir)
    errors += ledgercheck_paths.unopened(ctx.data_dir, scan)
    for path in scan.days:
        errors += ledgercheck_days.read_day_file(ctx.data_dir, key, foods, path)[1]
    errors += ledgercheck_paths.odd_files(ctx.data_dir, key, foods, scan)
    errors += ledgercheck_scan.listed_days(ctx.data_dir, key, foods, scan)
    errors += _internal_errors(ctx)
    if ctx.settings["format"] == 2:
        from hl.intents import state

        try:
            state.load(ctx, key)
        except Abort as stop:
            errors.extend(stop.result.fields.get("errors", []))
    # 清单要重建、又有重建会拒绝的（读不了、整份读不进来……）：先停下，不两条打架
    errors = ledgercheck_scan.wait_to_rebuild(ctx.data_dir, key, errors)
    if errors:
        # 同一个问题只报一次（同一处缺几个必填字段，校验会报几遍）
        unique = list({json.dumps(err, sort_keys=True): err for err in errors}.values())
        return rejected(unique, ledgercheck_messages.NEXT_DATA)
    tell_user = f"检查通过：{len(scan.days)} 份每日记录、计划、默认品种、用户库和清单没有问题。"
    tell_user += "成分表副本校验通过。" if foods else "尚未安装成分表缓存；缓存食品计算暂不可用。"
    # 用不上的默认品种只是提醒，带着给模型的命令：留在 warnings 里，不接进 tell_user
    result = ok(tell_user, checked=len(scan.days)).warn(stale, tell=False)
    return result.warn(_inbox_warnings(ctx)).warn(restored)
