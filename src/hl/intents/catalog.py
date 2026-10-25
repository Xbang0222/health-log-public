"""Food cache availability and numerical nutrition checks."""

from hl.configuration.values import Context
from hl.foods import table
from hl.foods import table_types as ft
from hl.intents.contract import fail
from hl.language import units


def load_table(ctx: Context) -> ft.Table:
    if not ctx.foods_sha and not table.path(ctx.data_dir).exists():
        return {}
    return table.require(ctx.data_dir, ctx.foods_sha)


def values(given: dict, *, label: bool = False, amount: dict | None = None) -> dict:
    # Null is unknown. Partial macro data does not become zero for consistency checks.
    macros = [given.get(k) for k in ("protein", "fat", "carb")]
    lower_bound = sum(
        v * factor for v, factor in zip(macros, (4, 9, 4), strict=True) if v is not None
    )
    lower_bound += given.get("other_kcal", 0)
    tolerance = max(5, given["kcal"] * 0.2)
    too_high = lower_bound > given["kcal"] + tolerance
    too_low = (
        not label and all(v is not None for v in macros) and lower_bound < given["kcal"] - tolerance
    )
    if too_high or too_low:
        fail(
            "nutrition",
            "已知宏量营养与热量明显不一致（容差20%或5千卡）",
            "自行核对估算；酒精等额外能量用 other_kcal 并说明依据，不要凭空补营养数字",
        )
    amount = amount or {}
    unit = amount.get("unit")
    unit = next((name for name, forms in units.UNIT_FORMS.items() if unit in forms), unit)
    grams = amount.get("g")
    if grams is None and unit in units.GRAMS:
        grams = amount["n"] * units.GRAMS[unit]
    if grams is not None and given["kcal"] > grams * 10:
        fail("nutrition.kcal", "称重份量的热量超过每100克1000千卡", "核对整份量、单位和热量")
    return {
        k: None if given.get(k) is None else ft.round_half_up(given[k], ft.DIGITS[k])
        for k in ft.NUTRIENTS
    }
