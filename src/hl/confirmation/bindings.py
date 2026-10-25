"""固定批次目标的绑定、完成与生命周期。"""

from __future__ import annotations

from pathlib import Path

from hl.configuration import values as configuration_values
from hl.confirmation.queue import _load, _put
from hl.confirmation.records import _find, digest
from hl.language import normalize as language_normalize


def bind_targets(
    data_dir: Path,
    kind: str,
    said: str,
    spoken: int,
    targets: list[dict[str, str]] | None = None,
) -> list[dict[str, str]] | None:
    """K23：一句原话固定指向的对象。确认消耗、其他提问和队列条数都不能扩大这批对象。

    只按原话位置过期，同样文字的新消息是另一批。调用方负责加锁；已有绑定只读不覆写。
    finish_targets标记完成后返回[]，从未绑定返回None。
    """
    key = digest("bound-targets", [kind, language_normalize.compact(said), spoken])
    items = _load(data_dir)
    old = _find(items, key)
    if old is not None:
        value = old.get("targets")
        if (
            not isinstance(value, list)
            or not value
            or not all(
                isinstance(target, dict)
                and configuration_values.is_date(str(target.get("date")))
                and all(isinstance(target.get(field), str) for field in ("id", "entry"))
                for target in value
            )
        ):
            return None
        return [] if old.get("finished") is True else value
    if targets is not None:
        note = {
            "digest": key,
            "kind": "bound-targets",
            "inbox": spoken,
            "summary": "",
            "targets": targets,
        }
        _put(data_dir, items, note)
        return targets
    return None


def finish_targets(data_dir: Path, kind: str, said: str, spoken: int) -> None:
    """K23：批次实际删除成功后标记完成，防止复用ID让旧原话删除新记录。调用方持锁。

    留着原targets供排查，读取返回空列表（已完成），不等于None（尚未绑定）。仍按出处位置过期。
    """
    key = digest("bound-targets", [kind, language_normalize.compact(said), spoken])
    items = _load(data_dir)
    item = _find(items, key)
    if item is not None:
        _put(data_dir, items, {**item, "finished": True})
