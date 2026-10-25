"""Recognize partially downgraded v2 ledgers, including pre-marker prototypes."""

import yaml

from hl.result import problem
from hl.storage import days, io


def _v2(doc, name):
    if name.startswith("log/") and isinstance(doc, dict):
        entries = doc.get("entries")
        records = [
            doc.get("weight"),
            doc.get("day_type"),
            *(entries if isinstance(entries, list) else []),
        ]
    elif name == "plan.yaml" and isinstance(doc, list):
        records = doc
    elif name in ("defaults.yaml", "foods/custom.yaml") and isinstance(doc, dict):
        records = doc.values()
    else:
        return False
    # Only metadata positions count: a legacy plan/food may legitimately be named "origin".
    return any(
        isinstance(v, dict) and {"origin", "input_items", "revision"} & v.keys() for v in records
    )


def legacy_errors(ctx):
    if ctx.settings["format"] != 1:
        return []
    errors = []
    fix = "这是部分恢复或降级的账本；恢复完整匹配的配置、历史与账本，不要覆盖重签"
    if (ctx.data_dir / ".hl/intents.json").exists():
        errors.append(problem(".hl/intents.json", "格式 1 目录存在格式 2 操作历史", fix))
    paths = days.day_files(ctx.data_dir) + [
        ctx.data_dir / name for name in ("plan.yaml", "defaults.yaml", "foods/custom.yaml")
    ]
    for path in paths:
        try:
            doc = io.read_yaml(path)
        except (OSError, ValueError, yaml.YAMLError):
            continue  # Normal file validation reports malformed/unreadable documents.
        name = path.relative_to(ctx.data_dir).as_posix()
        if _v2(doc, name):
            errors.append(
                problem(
                    path.relative_to(ctx.data_dir).as_posix(),
                    "格式 1 标记与记录中的格式 2 元数据不一致",
                    fix,
                )
            )
    return errors
