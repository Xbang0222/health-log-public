"""History filters are scoped to the entities actually changed in each event."""

from __future__ import annotations

import json


def changed_entities(event):
    changes = event.get("changes", {})
    if not isinstance(changes, dict):
        return
    for path, delta in changes.items():
        if path.startswith("log/") and path.endswith(".yaml"):
            day = path[4:-5].replace("/", "-")
            before, after = delta.get("before") or {}, delta.get("after") or {}
            old = {e["id"]: e for e in before.get("entries", [])}
            new = {e["id"]: e for e in after.get("entries", [])}
            for identity in old.keys() | new.keys():
                if old.get(identity) != new.get(identity):
                    for entry in (old.get(identity), new.get(identity)):
                        if entry:
                            yield day, entry.get("meal"), entry
            for field in ("weight", "day_type"):
                if before.get(field) != after.get(field):
                    yield day, None, {field: [before.get(field), after.get(field)]}
        else:
            yield event["at"][:10], None, delta


def matches(event, words, start, end, meal, normalized):
    for day, changed_meal, entity in changed_entities(event):
        if not start <= day <= end or meal and meal != changed_meal:
            continue
        text = normalized(json.dumps(entity, ensure_ascii=False))
        if all(word in text for word in words):
            return True
    # Non-mutating audit events can be searched, but cannot satisfy a meal filter.
    if not event.get("changes") and not meal and start <= event["at"][:10] <= end:
        text = normalized(json.dumps(event, ensure_ascii=False))
        return all(word in text for word in words)
    return False
