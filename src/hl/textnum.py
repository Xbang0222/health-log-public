"""用户原话的文字处理，全是纯函数。

数字（含中文数字）、单位、同义词归一（R4、R10）；估计用词（R13）；体重的数（R16）；
比较原话用的归一化（R2、R11）；餐次用词和“又、再、还”（第 6 节、R11）；计划数字的归属（R17）。
份量的各种写法、约数词说的是哪一处数量（第 2 步增补第 4、6、12 节）。

稳定公共入口；实现的唯一owner见各领域子模块。"""

from hl.language.goals import (
    GOAL_WORDS as GOAL_WORDS,
)
from hl.language.goals import (
    Goal as Goal,
)
from hl.language.goals import (
    goal_numbers as goal_numbers,
)
from hl.language.goals import (
    goals_in as goals_in,
)
from hl.language.meal_marks import (
    same_time as same_time,
)
from hl.language.meals import (
    MealPiece as MealPiece,
)
from hl.language.meals import (
    clock_meals as clock_meals,
)
from hl.language.meals import (
    instead as instead,
)
from hl.language.meals import (
    later_clauses as later_clauses,
)
from hl.language.meals import (
    many_meals as many_meals,
)
from hl.language.meals import (
    meal_from_time as meal_from_time,
)
from hl.language.meals import (
    meal_pieces as meal_pieces,
)
from hl.language.meals import (
    planned as planned,
)
from hl.language.meals import (
    says_again as says_again,
)
from hl.language.normalize import (
    clean as clean,
)
from hl.language.normalize import (
    cn_number as cn_number,
)
from hl.language.normalize import (
    compact as compact,
)
from hl.language.normalize import (
    fmt as fmt,
)
from hl.language.normalize import (
    fold as fold,
)
from hl.language.normalize import (
    kind as kind,
)
from hl.language.normalize import (
    normalize_items as normalize_items,
)
from hl.language.normalize import (
    normalize_net as normalize_net,
)
from hl.language.normalize import (
    normalize_state as normalize_state,
)
from hl.language.normalize import (
    normalize_unit as normalize_unit,
)
from hl.language.normalize import (
    number_value as number_value,
)
from hl.language.normalize import (
    simplified as simplified,
)
from hl.language.normalize import (
    squeeze as squeeze,
)
from hl.language.normalize import (
    visible as visible,
)
from hl.language.phrases import (
    DAY_WORD as DAY_WORD,
)
from hl.language.phrases import (
    DAYS as DAYS,
)
from hl.language.phrases import (
    MEAL_NAMES as MEAL_NAMES,
)
from hl.language.phrases import (
    MEAL_WORDS as MEAL_WORDS,
)
from hl.language.phrases import (
    SAID_DAYS as SAID_DAYS,
)
from hl.language.quantities import (
    amount_spans as amount_spans,
)
from hl.language.quantities import (
    has_amount as has_amount,
)
from hl.language.quantities import (
    quantities as quantities,
)
from hl.language.quantities import (
    said_amounts as said_amounts,
)
from hl.language.quantities import (
    with_generic_units as with_generic_units,
)
from hl.language.quantity_scope import (
    halves as halves,
)
from hl.language.quantity_scope import (
    hedge_near as hedge_near,
)
from hl.language.quantity_scope import (
    is_approx as is_approx,
)
from hl.language.quantity_scope import (
    is_hedged as is_hedged,
)
from hl.language.quantity_scope import (
    names_more as names_more,
)
from hl.language.quantity_tokens import (
    Quantity as Quantity,
)
from hl.language.quantity_tokens import (
    unit_name as unit_name,
)
from hl.language.units import (
    CLAUSE_END as CLAUSE_END,
)
from hl.language.units import (
    COUNTERS as COUNTERS,
)
from hl.language.units import (
    GRAMS as GRAMS,
)
from hl.language.units import (
    HEDGES as HEDGES,
)
from hl.language.units import (
    MEALS as MEALS,
)
from hl.language.units import (
    MILLILITRES as MILLILITRES,
)
from hl.language.units import (
    NOT_PORTIONS as NOT_PORTIONS,
)
from hl.language.units import (
    PORTION_WORDS as PORTION_WORDS,
)
from hl.language.units import (
    UNIT_FORMS as UNIT_FORMS,
)
from hl.language.weight_ambiguity import (
    unclear_numbers as unclear_numbers,
)
from hl.language.weight_clarity import (
    at_a_glance as at_a_glance,
)
from hl.language.weight_clarity import (
    extra_words as extra_words,
)
from hl.language.weight_clarity import (
    plain_weight as plain_weight,
)
from hl.language.weight_dates import (
    SaidDay as SaidDay,
)
from hl.language.weight_dates import (
    weight_days as weight_days,
)
from hl.language.weight_normalize import (
    with_points as with_points,
)
from hl.language.weight_normalize import (
    without_times as without_times,
)
from hl.language.weight_patterns import (
    KG_PER as KG_PER,
)
from hl.language.weight_patterns import (
    PLAUSIBLE_KG as PLAUSIBLE_KG,
)
from hl.language.weight_read import (
    heights_in as heights_in,
)
from hl.language.weight_read import (
    numbers_in as numbers_in,
)
from hl.language.weight_read import (
    odd_weight_units as odd_weight_units,
)
from hl.language.weight_read import (
    weights_in as weights_in,
)
from hl.language.weight_restatement import (
    restated as restated,
)
from hl.language.weight_types import (
    WeightMention as WeightMention,
)
from hl.language.weight_words import (
    WEIGHT_WORDS as WEIGHT_WORDS,
)
