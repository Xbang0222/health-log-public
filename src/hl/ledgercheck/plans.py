"""计划文件的可信读取与可恢复性诊断。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hl.ledgercheck.messages import NEXT_DATA, PLAN_FILE, Checked, Restorable
from hl.ledgercheck.reading import _or_os, _read, _require_manifest, _settled
from hl.ledgercheck.recovery import _restorable
from hl.ledgercheck.repairs import _fix_plan, _fix_plan_short
from hl.ledgercheck.structure import _repaired, plan_problems
from hl.manifests import compare as manifests_compare
from hl.manifests import io as manifests_io
from hl.manifests import model as manifests_model
from hl.result import Abort, problem, rejected
from hl.storage import io as storage_io


def _fix_plans_gone(git: bool) -> str:
    return manifests_model.fix_gone(PLAN_FILE, git, manifests_model.WHY_PLANS)


def _plan_fixes(plans: Any, problems: list[str], short: list[str], git: Restorable) -> Checked:
    """计划文件的问题配上改法。内容本身有问题时不另报缺口：修好之后对不对得上清单，
    改的是用哪个改法。"""
    if problems:
        fix = (lambda: _fix_plan_short(git())) if short else (lambda: _fix_plan(git()))
        return plans, [(text, _or_os(text, fix)) for text in problems], []
    return plans, [], [(text, _fix_plans_gone(git())) for text in short]


def _plan_file(data_dir: Path, key: bytes) -> Checked:
    """先读清单，再读计划文件。有问题时，拿 plan set 修好之后的样子去对清单。"""
    listed, _ = manifests_io.read(data_dir, key)
    plans, problems = _read(data_dir / PLAN_FILE)
    if not problems and plans is not None:
        problems = plan_problems(key, plans)
    short = manifests_compare.plan_gaps(listed, key, _repaired(key, plans) if problems else plans)
    return _plan_fixes(plans, problems, short, _restorable(data_dir, key, PLAN_FILE))


def read_plan_file(data_dir: Path, key: bytes) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """读计划文件，检查并对照清单；文件不存在时是空计划。"""
    plans, problems, gaps = _settled(lambda: _plan_file(data_dir, key))
    return plans or [], [problem(PLAN_FILE, text, fix) for text, fix in problems + gaps]


def load_plans(data_dir: Path, key: bytes) -> list[dict[str, Any]]:
    _require_manifest(data_dir, key)
    plans, errors = read_plan_file(data_dir, key)
    if errors:
        raise Abort(rejected(errors, NEXT_DATA))
    return plans


def sound_plans(data_dir: Path, key: bytes) -> tuple[list[dict[str, Any]], str]:
    """hl plan set 用（R17）：plan.yaml 里过得了校验的计划，以及去掉了什么的说明（没去掉为空串）。

    整份都没问题时就是全部计划。有问题时，单独拿出来过得了校验的那几条原样留下，其余去掉；
    整份读不出来按没有旧计划处理。这是修好坏文件的办法，新的一条照样由 plan set 核对。
    比清单里记的少了几版（被删了）不在此列，文件坏没坏都一样：那不是坏了，照旧拒绝（R15）。
    """
    _require_manifest(data_dir, key)
    plans, problems, _ = _plan_file(data_dir, key)
    if any(fix == storage_io.FIX_OS for _, fix in problems):  # 是个目录、没有权限：写也写不进去
        raise Abort(rejected([problem(PLAN_FILE, text, fix) for text, fix in problems], NEXT_DATA))
    # 坏了也照样对：修好之后和清单里记着的对不上（少了几版、多了、先后变了），就不借“修坏文件”抹平
    listed, _ = manifests_io.read(data_dir, key)
    kept = _repaired(key, plans) if problems else plans or []
    gaps = manifests_compare.plan_gaps(listed, key, kept)
    if gaps:
        git = _restorable(data_dir, key, PLAN_FILE)()
        fix = _fix_plan_short(git) if problems else _fix_plans_gone(git)
        raise Abort(rejected([problem(PLAN_FILE, text, fix) for text in gaps], NEXT_DATA))
    if not problems:
        return kept, ""
    entries = plans if isinstance(plans, list) else []
    if not entries:
        return [], "原来的 plan.yaml 读不出来，已按没有旧计划重写。"
    if len(kept) == len(entries):  # 单独都没问题、只是顺序倒了：已按生效日期排回去
        return kept, "原来的 plan.yaml 里计划的先后被动过，已按生效日期排回去。"
    return kept, f"原来的 plan.yaml 里有 {len(entries) - len(kept)} 条计划过不了校验，已经去掉。"
