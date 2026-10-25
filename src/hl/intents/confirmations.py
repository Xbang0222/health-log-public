"""Frozen batch confirmation and terminal, target-scoped cancellation."""

from __future__ import annotations

import copy

from hl.intents import contract, meals, state
from hl.result import Result, needs_input, ok, question


def finish(ctx, key, value, payload):
    token = payload.get("token")
    request = payload.get("cancel_request_id")
    if token and request:
        contract.fail("cancel", "token 与 cancel_request_id 二选一")
    action = payload["action"]
    if action == "confirm":
        waiting = value["pending"].get(token)
        if waiting is None:
            contract.fail(
                "token", "确认已取消、结束或不存在", "不要重开确认；新的用户请求须重新查询"
            )
        result = Result("ok", meals.delete(ctx, key, waiting["payload"]))
        frozen = waiting["payload"]
        value["receipts"][frozen["request_id"]] = {
            "fingerprint": state.digest(frozen),
            "result": copy.deepcopy(result.fields),
        }
        del value["pending"][token]
        return result
    if not token and not request:
        candidates = [(name, p["payload"]["request_id"]) for name, p in value["pending"].items()]
        candidates += [(None, name) for name in value["drafts"] if name != payload["request_id"]]
        if len(candidates) > 1:
            return needs_input(
                [
                    question(
                        "待办",
                        "confirm",
                        "要取消哪件未完成的记录？",
                        [],
                        "有多个不同待办，不能误取消别的会话",
                    )
                ],
                "先查询 recent，使用准确 token 或 cancel_request_id，只问有歧义的范围",
            )
        if candidates:
            token, request = candidates[0]
    result = ok("已取消，没有修改记录。", recorded=False, cancelled=True)
    waiting = value["pending"].get(token)
    if token and not waiting:
        contract.fail(
            "token",
            "未找到这项待确认操作，本次没有取消任何待办",
            "recent 查询准确 token；不要猜编号",
        )
    if request and not waiting:
        pair = next(
            ((t, p) for t, p in value["pending"].items() if p["payload"]["request_id"] == request),
            None,
        )
        if pair:
            token, waiting = pair
    if waiting:
        request = waiting["payload"]["request_id"]
        frozen = waiting["payload"]
        del value["pending"][token]
    elif request in value["drafts"]:
        frozen = value["drafts"].pop(request)["payload"]
    elif request in value["receipts"]:
        return ok("这件事已经结束，现有记录没有改动。", recorded=False)
    elif request:
        contract.fail(
            "cancel_request_id",
            "未找到这项待办，本次没有取消任何待办",
            "recent 查询准确 request_id；不要猜编号",
        )
    else:
        return result
    value["receipts"][request] = {
        "fingerprint": state.digest(frozen),
        "cancelled": True,
        "result": copy.deepcopy(result.fields),
    }
    value["drafts"].pop(request, None)
    return result
