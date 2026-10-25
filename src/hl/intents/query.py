"""Read targets and versions through the same verified projection used for writes."""

from __future__ import annotations

from hl.foods import custom
from hl.intents import meals, state
from hl.intents.catalog import load_table
from hl.ledgercheck.days import load_day
from hl.ledgercheck.defaults import read_defaults_file
from hl.ledgercheck.plans import load_plans
from hl.result import ok
from hl.storage import days, keys


def recent(ctx, args):
    _limit(args.limit)
    key = keys.secret(ctx.data_dir)
    foods = load_table(ctx)
    entries, weights, types = [], [], []
    for path in reversed(days.day_files(ctx.data_dir)):
        day = days.day_of(ctx.data_dir, path)
        doc = load_day(ctx.data_dir, key, foods, day)
        entries.extend(meals.public(day, e) for e in reversed(doc["entries"]))
        if "weight" in doc:
            weights.append({"date": day, **doc["weight"], "version": doc["weight"]["sig"]})
        if "day_type" in doc:
            types.append({"date": day, **doc["day_type"], "version": doc["day_type"]["sig"]})
    plans = load_plans(ctx.data_dir, key)
    defaults, errors = read_defaults_file(ctx.data_dir, key)
    if errors:
        from hl.result import Abort, rejected

        raise Abort(rejected(errors))
    library = custom.load(ctx.data_dir, key)
    if library.broken or any(entry.problem for entry in library.entries.values()):
        from hl.intents.contract import fail

        fail(custom.FILE, "用户食品库损坏，不能把它显示为空库", "运行 check，并从完整备份恢复")
    value = state.load(ctx, key) if ctx.settings["format"] == 2 else state.new()
    pending = value["pending"]
    drafts = {
        name: {"date": d["date"], "said": d["payload"]["said"], "action": d["payload"]["action"]}
        for name, d in value["drafts"].items()
    }
    return ok(
        "已读取最近记录。",
        entries=entries[: args.limit],
        weights=weights[: args.limit],
        day_types=types[: args.limit],
        plan=plans[-1] if plans else None,
        defaults=defaults,
        foods={n: {"version": e.body.get("sig"), "per": e.per} for n, e in library.entries.items()},
        pending=pending,
        drafts=drafts,
    )


def history(ctx, args):
    _limit(args.limit)
    if ctx.settings["format"] == 1:
        _legacy_history(ctx)
        return ok("格式1没有结构化更改历史；原记录仍可查询，迁移后开始保留操作历史。", events=[])
    key = keys.secret(ctx.data_dir)
    value = state.load(ctx, key)
    events = value["audit"]
    if args.request_id:
        events = [e for e in events if e["request_id"] == args.request_id]
    return ok("已读取操作历史。", events=events[-args.limit :])


def find(ctx, args):
    import json
    import unicodedata

    from hl.configuration.values import pick_date
    from hl.intents.contract import fail

    def normalized(text):
        return unicodedata.normalize("NFKC", text).casefold()

    words = [normalized(word.strip()) for word in args.words if word.strip()]
    if not words or not 1 <= args.limit <= 1000:
        fail("find", "关键词不能为空；limit 必须在 1–1000 之间")
    start = pick_date(args.start, "0001-01-01", "from")
    end = pick_date(args.end, "9999-12-31", "to")
    if start > end:
        fail("from", "起始日期晚于结束日期")
    key = keys.secret(ctx.data_dir)
    found = []
    if args.history:
        if ctx.settings["format"] == 1:
            _legacy_history(ctx)
            return ok("格式1没有结构化更改历史；可查询原记录。", matches=[], total=0, history=True)
        value = state.load(ctx, key)
        for event in reversed(value["audit"]):
            from hl.intents.history_search import matches

            if matches(event, words, start, end, args.meal, normalized):
                found.append(event)
    else:
        foods = load_table(ctx)
        for path in reversed(days.day_files(ctx.data_dir)):
            day = days.day_of(ctx.data_dir, path)
            if not start <= day <= end:
                continue
            doc = load_day(ctx.data_dir, key, foods, day)
            for entry in reversed(doc["entries"]):
                if args.meal and entry["meal"] != args.meal:
                    continue
                text = normalized(json.dumps(entry, ensure_ascii=False))
                if all(word in text for word in words):
                    found.append(meals.public(day, entry))
    return ok(
        f"找到 {len(found)} 条{'历史变更' if args.history else '记录'}。",
        matches=found[: args.limit],
        total=len(found),
        history=args.history,
    )


def _limit(n):
    from hl.intents.contract import fail

    if not 1 <= n <= 1000:
        fail("limit", "查询条数须在 1–1000 之间")


def _legacy_history(ctx):
    """Absence of a legacy audit is truthful only after checking version evidence."""
    from hl.ledgercheck.protocol import legacy_errors
    from hl.manifests.io import read
    from hl.result import Abort, rejected

    errors = legacy_errors(ctx) + read(ctx.data_dir, keys.secret(ctx.data_dir))[1]
    if errors:
        raise Abort(rejected(errors))
