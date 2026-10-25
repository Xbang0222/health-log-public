"""The sole daily write service: validate, CAS, commit, receipt, audit."""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from hl.foods import custom
from hl.intents import contract, meals, settings, state
from hl.result import Abort, Result, needs_input, ok, question
from hl.storage import days, git_commit, io, keys
from hl.storage.transactions import transaction

FIXED_PATHS = [
    "hl.toml",
    "plan.yaml",
    "defaults.yaml",
    "foods/custom.yaml",
    ".hl/manifest.json",
    ".hl/recorded.json",
    state.FILE,
]


def paths_for(ctx, payload, day):
    paths = {p.relative_to(ctx.data_dir).as_posix() for p in days.day_files(ctx.data_dir)}
    candidates = {day, payload.get("date", day)}
    candidates.update(t["date"] for t in payload.get("targets", []))
    if "target" in payload:
        candidates.add(payload["target"]["date"])
    paths.update(days.day_path(Path("."), d).as_posix() for d in candidates)
    return sorted(paths | set(FIXED_PATHS))


def snapshot(data_dir, paths):
    # Full values, not just hashes: deleted and replaced content remains reviewable without Git.
    return {
        name: io.read_yaml(data_dir / name)
        for name in paths
        if name.startswith("log/") or name in ("plan.yaml", "defaults.yaml", "foods/custom.yaml")
    }


def preflight(ctx):
    from hl.ledgercheck.service import run as check

    checked = check(ctx, argparse.Namespace(read_only=True))
    if checked.status != "ok":
        raise Abort(checked)


def run(ctx, args) -> Result:
    payload = contract.parse(args.payload)
    if ctx.settings["format"] != 2:
        contract.fail(
            "format",
            "旧账本可查询；启用新写入前需要迁移预检与备份",
            "运行 migrate，再运行 migrate --apply",
        )
    key = keys.secret(ctx.data_dir)
    with io.locked(ctx.data_dir):
        value = state.load(ctx, key)
        request_id = payload["request_id"]
        fingerprint = state.digest(payload)
        preflight(ctx)
        receipt = value["receipts"].get(request_id)
        if receipt:
            if not receipt.get("cancelled") and receipt["fingerprint"] != fingerprint:
                contract.fail(
                    "request_id",
                    "此请求已经结束，不能用同一编号提交不同操作",
                    "查询已完成结果；新的用户请求使用新 request_id",
                )
            from hl.intents.receipts import replay

            return replay(ctx, key, payload, receipt)
        origin = state.origin(ctx, payload)
        source_time = datetime.fromisoformat(origin["at"])
        if source_time > ctx.now + timedelta(minutes=5):
            contract.fail(
                "source.at", "来源时间在未来", "使用原消息的真实时间，不得用未来时间绕过日期校验"
            )
        default_day = source_time.date().isoformat()
        if "source" not in payload:
            default_day = ctx.today
        day = payload.get("date", value["drafts"].get(request_id, {}).get("date", default_day))
        action = payload["action"]
        if action in ("add", "weight", "amend") and day > max(ctx.today, default_day):
            contract.fail(
                "date", "尚未发生的日期不能记为已吃/已称", "未来打算用 noop，不要写饮食或体重"
            )
        paths = paths_for(ctx, payload, day)
        if action in ("confirm", "cancel") and payload.get("token") in value["pending"]:
            frozen = value["pending"][payload["token"]]["payload"]
            paths = sorted(set(paths + paths_for(ctx, frozen, day)))
        with transaction(ctx.data_dir, key, paths):
            before = snapshot(ctx.data_dir, paths)
            try:
                result = dispatch(ctx, key, value, payload, day, origin)
            except Abort as stop:
                if stop.result.status not in ("needs_input", "needs_estimate"):
                    raise
                stop.result.fields.update(
                    recorded=False, draft=True, request_id=request_id, date=day
                )
                if stop.result.status == "needs_input":
                    prefix = "原记录保持不变。" if action == "amend" else "这部分尚未记入。"
                    stop.result.fields["tell_user"] = prefix + stop.result.fields["tell_user"]
                value["drafts"].setdefault(request_id, {"date": day, "payload": payload})
                state.write(ctx, key, value)
                return stop.result
            if result.status == "needs_input":
                result.fields.update(recorded=False, request_id=request_id)
                state.write(ctx, key, value)
                return result
            result.fields.setdefault("recorded", False)
            result.fields["origin"] = origin
            result.fields["request_id"] = request_id
            notes = list(dict.fromkeys(result.fields.pop("notes", [])))
            estimated = any(row.get("est") for row in result.fields.get("items", []))
            if estimated and not any("估算" in n for n in notes):
                notes.append("份量按常见大小估算")
            if notes:
                result.fields["notes"] = notes
                result.fields["tell_user"] += "（" + "；".join(notes) + "）"
            value["receipts"][request_id] = {"fingerprint": fingerprint, "result": result.fields}
            value["drafts"].pop(request_id, None)
            after = snapshot(ctx.data_dir, paths)
            changes = {
                name: {"before": before[name], "after": after[name]}
                for name in before
                if before[name] != after[name]
            }
            value["audit"].append(
                {
                    "request_id": request_id,
                    "action": action,
                    "origin": origin,
                    "at": ctx.now.isoformat(),
                    "changes": changes,
                }
            )
            state.write(ctx, key, value)
            preflight(ctx)
        # Commit journal is gone before optional Git invokes its independent pre-commit check.
        warnings = git_commit.autocommit(
            ctx.data_dir, ctx.autocommit, f"hl intent {action} {request_id}"
        )
        return result.warn(warnings, tell=False)


def dispatch(ctx, key, value, payload, day, origin) -> Result:
    action = payload["action"]
    request_id = payload["request_id"]
    pending_request = next(
        (p for p in value["pending"].values() if p["payload"]["request_id"] == request_id), None
    )
    if pending_request:
        if state.digest(pending_request["payload"]) != state.digest(payload):
            contract.fail(
                "request_id", "待确认操作的目标已经冻结", "使用 confirm/cancel 与返回的 token"
            )
        return Result("needs_input", pending_request["question"])
    if action in ("add", "amend"):
        fields, saves = (
            meals.add(ctx, key, payload, day, origin)
            if action == "add"
            else meals.amend(ctx, key, payload, origin)
        )
        library = custom.load(ctx.data_dir, key)
        for name, body in saves.items():
            if library.get(name) is None:
                custom.save(ctx.data_dir, key, name, body)
        return Result("ok", fields)
    if action == "delete":
        for t in payload["targets"]:
            meals.locate(ctx, key, t)
        if len(payload["targets"]) == 1:
            return Result("ok", meals.delete(ctx, key, payload))
        if len({(t["date"], t["id"]) for t in payload["targets"]}) != len(payload["targets"]):
            contract.fail("targets", "批量删除目标重复")
        token = uuid.uuid4().hex
        shown = "、".join(f"{t['date']}/{t['id']}" for t in payload["targets"])
        result = needs_input(
            [
                question(
                    "记录",
                    "confirm",
                    f"确认删除这 {len(payload['targets'])} 条记录吗？",
                    ["确认", "取消"],
                    "批量删除需要一次确认",
                )
            ],
            "本轮停止工具调用，向用户展示这次 preview 的日期餐次食物并询问一次。"
            "必须等这次预览之后的新用户回复，再用 confirm + token 或 cancel。"
            "不能把发起删除的原请求（即使说了确定）重复当成确认，也不能在同轮自行 confirm。"
            "取消后的新批删同样先展示新预览；旧确认不复用。",
        )
        result.fields.update(
            token=token,
            targets=payload["targets"],
            preview=[
                meals.public(t["date"], meals.locate(ctx, key, t)[1]) for t in payload["targets"]
            ],
            diagnostic_targets=shown,
        )
        value["pending"][token] = {"payload": payload, "question": result.fields}
        return result
    if action in ("confirm", "cancel"):
        from hl.intents.confirmations import finish

        return finish(ctx, key, value, payload)
    if action == "noop":
        return ok(f"未记录：{payload['reason']}。", recorded=False)
    return Result("ok", settings.apply(ctx, key, payload, day))
