"""将词片组合为食物提及，确定名字尾巴和做法归属。"""

from __future__ import annotations

from dataclasses import replace

from hl.foods import concepts
from hl.foods.lexicon_build import tokens
from hl.foods.lexicon_types import COOKING, FOOD, NOT_SAME, Grid, Lexicon, Mention, Token
from hl.language.food_boundaries import unconsumed_soup


def _tail(grid: Grid, token: Token) -> int:
    """食物词后面算尾巴的那一截到哪里为止（第 2.3 节）；没有尾巴就是这个词的末尾。

    尾巴是紧跟着的 1 到 2 个可用字，再往后是边界。是这个概念的切法字（牛肉片）、后面紧跟“的”
    （牛奶热的一杯）的不算。
    """
    if unconsumed_soup(grid.text, token.end, token.concept):
        return token.end
    end = grid.run(token.end)
    tail = grid.text[token.end : end]
    cuts = grid.lex.cuts.get(token.concept or "", ())
    if not 1 <= len(tail) <= 2 or tail in cuts or grid.text[end : end + 1] == "的":
        return token.end
    return end


def mentions(lex: Lexicon, text: str, found: list[Token] | None = None) -> list[Mention]:
    """原话里的每样食物，按先后排：先认尾巴，再认一道菜的名字，最后是只连着一边的做法词。

    found 是取好的词（readings 的某一种），不给就用默认的那种。
    """
    found = tokens(lex, text) if found is None else found
    grid = Grid(lex, text, found)
    foods: list[Mention] = []
    for token in found:
        if token.kind == FOOD and (end := _tail(grid, token)) > token.end:
            foods.append(Mention(token.start, end, text[token.start : end], words=(token,)))
        elif token.kind == FOOD:
            foods.append(Mention(*_place(token), token.concept, token.variant, words=(token,)))
        elif token.kind == NOT_SAME:
            foods.append(Mention(*_place(token), words=(token,)))
    cooks = [token for token in found if token.kind == COOKING]
    left = []
    for cook in cooks:
        dish = _dish(grid, foods, cook)
        if dish is None:
            left.append(cook)
        else:
            foods = [m for m in foods if not dish.start <= m.start < dish.end] + [dish]
    for cook in left:
        foods = _one_side(text, foods, cook)
    return sorted(foods, key=lambda m: m.start)


def _place(token: Token) -> tuple[int, int, str]:
    return token.start, token.end, token.word


def _dish(grid: Grid, foods: list[Mention], cook: Token) -> Mention | None:
    """做法词两边都连着食物时，从左边那串食物词的第一个到右边的食物词或尾巴，算一道菜的名字
    （第 2.4 节）。两边的食物各自紧挨着一处数量时不并（“一碗米饭煎鸡蛋两个”是两样）。"""
    ends = {m.end: m for m in foods}
    left = ends.get(cook.start)
    if left is None:
        return None
    right = next((m for m in foods if m.start == cook.end), None)
    if right is not None:
        end = right.end
    else:  # 右边是没进词典的字（辣椒炒肉的“肉”）：和尾巴一样 1 到 2 个字，后面是边界
        end = grid.run(cook.end)
        # 后面紧跟“的、了”的是在说做成什么样（炒熟了、炖烂的），不是菜名
        if not 1 <= end - cook.end <= 2 or grid.text[end : end + 1] in ("的", "了"):
            return None
    if grid.amount_at(left.start, after=False) and grid.amount_at(end, after=True):
        return None
    first = left
    while (before := ends.get(first.start)) is not None:
        first = before
    inside = [m for m in foods if first.start <= m.start and m.end <= end]
    words = sorted(
        {*(w for m in inside for w in (*m.cooking, *m.words)), cook}, key=lambda t: t.start
    )
    return Mention(first.start, end, grid.text[first.start : end], words=tuple(words))


def _one_side(text: str, foods: list[Mention], cook: Token) -> list[Mention]:
    """只连着一边的做法词（第 10 节）：连在食物前面、是“另一种食物”那一档的，整个算另一种
    食物（炸鸡腿）；别的算这样食物的做法（炒鸡蛋、鸡蛋煮的），食物照常认。"""
    right = next((m for m in foods if m.start == cook.end), None)
    left = next((m for m in foods if m.end == cook.start), None)
    if right is not None and cook.label == concepts.TIERS[-1]:
        merged = Mention(
            cook.start, right.end, text[cook.start : right.end], words=(cook, *right.words)
        )
        return [m for m in foods if m is not right] + [merged]
    target = right or left
    if target is None or target.concept is None:
        return foods
    attached = replace(target, cooking=(*target.cooking, cook))
    return [attached if m is target else m for m in foods]
