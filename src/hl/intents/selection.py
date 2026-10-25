"""Resolve structured identity to the single canonical conversion policy."""

from hl.foods import concepts
from hl.foods import table_types as ft
from hl.intents.contract import fail


def select(index, item):
    hit = concepts.lookup(index, item["name"])
    concept, variant = hit if hit else (None, None)
    code = ft.ref(item["food"]) if item.get("food") else None
    if code and ft.split(code)[0] == ft.CUSTOM:
        if "state" in item:
            fail(
                "state", "用户库编码没有生熟换算规则", "核对标签对应称重口径，不要静默忽略生熟状态"
            )
        return None, None, code
    if code:
        candidates = [
            (c, v.name)
            for c in index.concepts.values()
            for v in c.variants.values()
            if ft.ref(v.food) == code
        ]
        if concept:
            matches = [v for c, v in candidates if c.name == concept.name]
            if not matches:
                fail("food", "编码不属于这个食品概念", "food search 查询相符的名称和编码")
            if len(matches) == 1:
                if variant and variant != matches[0]:
                    fail("food", "编码与名称指明的品种不符")
                variant = matches[0]
        elif len(candidates) == 1:
            concept, variant = candidates[0]
        elif candidates:
            fail(
                "name",
                "编码对应多个换算口径，需规范食品名称",
                "使用 food search 中的概念名称自行修正；不要重复询问已知事实",
            )
        elif "state" in item:
            fail(
                "state",
                "这个编码没有生熟换算规则，不能忽略称重状态",
                "选择与称重口径相同的食品编码并去掉 state，或使用有换算规则的规范名称",
            )
    if concept and item.get("variant"):
        explicit = concepts.find_variant(concept, item["variant"])
        if variant and explicit != variant:
            fail("variant", "显式品种与食品名称或编码不一致")
    return concept, variant, code
