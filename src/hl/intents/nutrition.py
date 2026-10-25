"""Deterministic nutrition from structured foods; never parse the user's utterance."""

from __future__ import annotations

from dataclasses import dataclass, field

from hl.configuration.values import Context
from hl.foods import concepts, custom, table_io
from hl.foods import table_types as ft
from hl.intents.catalog import load_table, values
from hl.intents.contract import fail
from hl.intents.selection import select
from hl.language import units
from hl.ledgercheck.defaults import load_defaults
from hl.result import Abort, needs_estimate, needs_input, question


@dataclass
class Resolved:
    rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    saves: dict[str, dict] = field(default_factory=dict)


def ask(name: str, field_name: str, text: str, options: list[str] | None = None) -> dict:
    return question(name, field_name, text, options or [], "这项事实会影响记录")


class Calculator:
    def __init__(self, ctx: Context, key: bytes):
        self.ctx = ctx
        self.index = concepts.load()
        self.library = custom.load(ctx.data_dir, key)
        if self.library.broken or any(e.problem for e in self.library.entries.values()):
            fail(custom.FILE, "用户食品库有损坏，不能重新签名覆盖", "运行 check 并从备份恢复")
        self.defaults = load_defaults(ctx.data_dir, key, self.index)
        self.foods = ft.View(
            load_table(ctx), boohee=table_io.BooheeLayer(ctx.data_dir, ctx.boohee_sha)
        )
        self.questions: list[dict] = []
        self.unknown: list[dict] = []
        self.out = Resolved()

    def resolve(self, items: list[dict]) -> Resolved:
        for pos, item in enumerate(items):
            rows = self.one(item, pos)
            for row in rows:
                row["item_id"] = item["item_id"]
            self.out.rows.extend(rows)
        if self.questions:
            result = needs_input(
                self.questions,
                "只问尚缺事实；把回答追加到 answers，补齐同一 request_id。"
                "已明确的日期、餐次、食品和数量不要重复问。",
            )
            if self.unknown:
                result.fields["unknown"] = self.unknown
            raise Abort(result)
        if self.unknown:
            raise Abort(
                needs_estimate(
                    self.unknown,
                    "仅为用户已经说明的实际份量估算换算/营养，填写 estimate"
                    "（nutrition 或 parts 与 basis），同一 request_id 重试。"
                    "如果 amount 是你自行补的，先移除 amount 重试并问实际吃了多少；"
                    "不能猜一份/一碗或换量词绕过缺份量。缺缓存可 foods fetch；估算不是实测。",
                )
            )
        return self.out

    def unknown_item(self, item: dict, pos: int, reason: str) -> list:
        template = {k: v for k, v in item.items() if k != "item_id"}
        self.unknown.append(
            {
                "item": pos,
                "text": item["name"],
                "reason": reason,
                "near": [],
                "ingredients": [],
                "template": {
                    **template,
                    "estimate": {"nutrition": {"kcal": None}, "basis": "按实际份量估算依据"},
                },
            }
        )
        return []

    def one(self, item: dict, pos: int) -> list[dict]:
        name = item["name"]
        if "amount" not in item:
            self.questions.append(ask(name, "amount", f"{name}吃了多少？"))
        concept, named_variant, code = select(self.index, item)
        amount = item.get("amount", {})
        n, unit = amount.get("n"), amount.get("unit")
        unit = next(
            (canonical for canonical, forms in units.UNIT_FORMS.items() if unit in forms), unit
        )
        shown = f"{n:g}{unit}" if n is not None else ""
        marks = [ft.AMOUNT] if item.get("approximate") else []
        if item.get("estimate"):
            return self.estimate(item, shown, marks) if n is not None else []
        # An explicit data-source code must never be shadowed by a same-name label.
        saved = (
            self.library.get(ft.split(code)[1])
            if code and ft.split(code)[0] == ft.CUSTOM
            else (self.library.get(name) if not code else None)
        )
        if code and ft.split(code)[0] == ft.CUSTOM and (not saved or not saved.food):
            fail("food", "指定的用户库食品不存在或没有营养", "food search 查询实际用户库编码")
        if saved and saved.food:
            if n is None:
                return []
            factor = saved.factor(n, unit)
            if factor is None:
                return self.unknown_item(
                    item, pos, "已有估算/标签不支持这个单位；补换算或这份的估算"
                )
            times, grams, approximate = factor
            rows = saved.rows(
                self.foods, times, grams, marks + ([ft.AMOUNT] if approximate else []), shown
            )
            if isinstance(rows, str):
                fail(name, rows)
            if not saved.label:
                self.out.notes.append(f"{name}沿用已存估算")
            return rows
        if concept and concept.recipe:
            if n is None:
                return []
            measure = concept.units.get(unit)
            scale = n * measure.recipe if measure and measure.recipe else None
            if scale is None and unit in units.GRAMS and concept.serving_g:
                scale = n * units.GRAMS[unit] / concept.serving_g
            if scale is None:
                return self.unknown_item(item, pos, "菜谱没有这个量词的换算")
            parts = [{"food": ft.ref(p.food), "g": p.g * scale} for p in concept.recipe]
            if concept.salt_g:
                parts.append({"food": ft.SALT, "g": concept.salt_g * scale})
            rows = self.parts(parts, shown, name, [ft.AMOUNT, ft.CONTENT], "菜谱估算")
            if rows is None:
                return self.unknown_item(item, pos, "菜谱原料缓存不可用")
            self.out.notes.append(f"{name}按标准菜谱估算")
            return rows
        variant = None
        measure = concept.units.get(unit) if concept else None
        if concept:
            choice = item.get("variant") or named_variant
            if choice:
                choice = concepts.find_variant(concept, choice)
                if choice is None:
                    fail(
                        name, "品种不存在", f"有效品种：{'、'.join(concept.variants)}；先自行归一化"
                    )
            if measure and measure.variant:
                if choice and choice != measure.variant:
                    fail(name, "这个量词与品种的换算不相容", "使用用户给出的称重或为该份量提供估算")
                choice = measure.variant
            if not choice:
                stored = self.defaults.get(concept.name)
                choice = stored or concept.default
                if choice:
                    self.out.notes.append(f"{name}按{choice}")
            if not choice and len(concept.variants) == 1:
                choice = next(iter(concept.variants))
            if not choice:
                self.questions.append(
                    ask(
                        name,
                        "variant",
                        f"{name}是哪种：{'、'.join(concept.variants)}？",
                        list(concept.variants),
                    )
                )
                return []
            variant = concept.variants[choice]
            if code and ft.ref(code) != ft.ref(variant.food):
                fail(name, "food 编码与所选品种不一致")
            code = ft.ref(variant.food)
        if n is None:
            return []
        if not code:
            matches = [
                (ft.join(kind, key), food)
                for kind, layer in self.foods.layers()
                for key, food in layer.items()
                if food.name == name
            ]
            if len(matches) == 1:
                code = matches[0][0]
        food = self.foods.get(code) if code else None
        if not food or food.kcal is None:
            return self.unknown_item(item, pos, "无匹配的可计算食品/缓存；需有依据的估算")
        grams = None
        if measure:
            marks.append(ft.AMOUNT)
            if measure.g:
                grams = n * measure.g
            elif measure.ml and concept.density:
                grams = n * measure.ml * concept.density
            elif measure.gross_g and food.edible is not None:
                grams = n * measure.gross_g * food.edible / 100
        elif unit in units.GRAMS:
            grams = n * units.GRAMS[unit]
            if concept and concept.cook and not (variant and variant.cooked_product):
                if "state" not in item:
                    self.questions.append(
                        ask(name, "state", f"{name}称的是生重还是熟重？", ["生", "熟"])
                    )
                    return []
                if item["state"] == "熟":
                    grams /= concept.cook.ratio
                    marks.append(ft.AMOUNT)
                    self.out.notes.append(f"{name}按熟重折算")
            if item.get("net") == "带皮":
                if food.edible is None:
                    return self.unknown_item(item, pos, "无可食部比例")
                grams *= food.edible / 100
            elif food.edible is not None and food.edible < 100 and "net" not in item:
                self.out.notes.append(f"{name}称重按可食部")
        elif unit in units.MILLILITRES and concept and concept.density:
            grams = n * units.MILLILITRES[unit] * concept.density
        if grams is None:
            return self.unknown_item(item, pos, "没有这个单位的可靠换算")
        if grams < 0.05 or grams > 1000000:
            fail(name, "换算后重量超出可记录范围（0.05–1000000g）")
        kind = ft.split(code)[0]
        src = "薄荷库" if kind == ft.BOOHEE else "成分表"
        if kind == ft.BOOHEE:
            marks.append(ft.CONTENT)
        return [ft.make_row(code, food, grams, src, marks, shown)]

    def parts(self, parts: list[dict], shown: str, name: str, marks: list[str], src: str):
        rows = []
        for part in parts:
            code = part["food"]
            found = concepts.lookup(self.index, code)
            if found:
                concept, choice = found
                choice = choice or concept.default
                if not choice and len(concept.variants) == 1:
                    choice = next(iter(concept.variants))
                if choice:
                    code = ft.ref(concept.variants[choice].food)
            food = self.foods.get(code)
            if not food or food.kcal is None:
                return None
            if part["g"] < 0.05:
                fail(name, "原料重量太小，取整后将为零")
            rows.append(ft.make_row(code, food, part["g"], src, marks, shown, name))
        return rows

    def estimate(self, item: dict, shown: str, marks: list[str]) -> list[dict]:
        estimate, name = item["estimate"], item["name"]
        if "nutrition" in estimate:
            rows = [
                {
                    "food": "est",
                    "name": name,
                    "amount": shown,
                    **values(estimate["nutrition"], amount=item["amount"]),
                    "src": "模型估算",
                    "est": [*marks, ft.CONTENT],
                }
            ]
        else:
            rows = self.parts(estimate["parts"], shown, name, [*marks, ft.CONTENT], "模型估算")
            if rows is None:
                fail(
                    name,
                    "估算原料编码不存在或没有热量",
                    "food search 查询可用原料，或提供整份 nutrition",
                )
        self.out.notes.append(f"{name}为营养估算")
        if estimate.get("remember", True) and not concepts.lookup(self.index, name):
            nutrition = {
                k: None if any(r[k] is None for r in rows) else sum(r[k] for r in rows)
                for k in ft.NUTRIENTS
            }
            self.out.saves[name] = {
                "per": item["amount"],
                "nutrition": nutrition,
                "src": "模型估算",
                "est": [ft.CONTENT],
                "basis": estimate["basis"],
                "date": self.ctx.today,
            }
        return rows
