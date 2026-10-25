"""表达计划目标。"""

from __future__ import annotations

from typing import Any

from hl import budget
from hl.language import normalize as language_normalize


def _spoken(days: dict[str, dict[str, Any]], default: str) -> str:
    parts = []
    for name, goals in days.items():
        goals_said = [f"{language_normalize.fmt(goals['kcal'])} 千卡"]
        for key, value in goals.items():
            if key != "kcal":
                label = budget.LABELS[key] + ("上限" if key == "sodium" else "")
                goals_said.append(f"{label} {language_normalize.fmt(value)} {budget.UNITS[key]}")
        parts.append(f"{name}{'（默认）' if name == default else ''}：{'、'.join(goals_said)}")
    return "；".join(parts)
