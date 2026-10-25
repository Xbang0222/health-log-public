"""按文字找食物（增补第 2 节）：词典、取词、尾巴、菜名，只在这一处。

另有没说名字的“又吃了一个”（R3）、只是在说没吃的那几句（R11）。items 怎么对上这些食物
（R3 的覆盖检查）在 match.py；概念表和菜谱的数据模型和加载在 concepts.py，数据校验在 lint.py。"""

from __future__ import annotations

from hl.foods.lexicon_build import _BUILT as _BUILT
from hl.foods.lexicon_build import _ORDER as _ORDER
from hl.foods.lexicon_build import _identity as _identity
from hl.foods.lexicon_build import _options as _options
from hl.foods.lexicon_build import _token as _token
from hl.foods.lexicon_build import entries as entries
from hl.foods.lexicon_build import lexicon as lexicon
from hl.foods.lexicon_build import readings as readings
from hl.foods.lexicon_build import tokens as tokens
from hl.foods.lexicon_mentions import _dish as _dish
from hl.foods.lexicon_mentions import _one_side as _one_side
from hl.foods.lexicon_mentions import _place as _place
from hl.foods.lexicon_mentions import _tail as _tail
from hl.foods.lexicon_mentions import mentions as mentions
from hl.foods.lexicon_types import COOKING as COOKING
from hl.foods.lexicon_types import FOOD as FOOD
from hl.foods.lexicon_types import MAX_READINGS as MAX_READINGS
from hl.foods.lexicon_types import MODIFIER as MODIFIER
from hl.foods.lexicon_types import NEUTRAL as NEUTRAL
from hl.foods.lexicon_types import NOT_SAME as NOT_SAME
from hl.foods.lexicon_types import NUMBER_CHARS as NUMBER_CHARS
from hl.foods.lexicon_types import SAVED_FILE as SAVED_FILE
from hl.foods.lexicon_types import SHARED_NEUTRAL as SHARED_NEUTRAL
from hl.foods.lexicon_types import Entry as Entry
from hl.foods.lexicon_types import Grid as Grid
from hl.foods.lexicon_types import Lexicon as Lexicon
from hl.foods.lexicon_types import Mention as Mention
from hl.foods.lexicon_types import Span as Span
from hl.foods.lexicon_types import Token as Token
from hl.foods.lexicon_types import Word as Word
from hl.foods.lexicon_usage import _AGAIN as _AGAIN
from hl.foods.lexicon_usage import _FOODS as _FOODS
from hl.foods.lexicon_usage import _HELPING as _HELPING
from hl.foods.lexicon_usage import _NOT_A_HELPING as _NOT_A_HELPING
from hl.foods.lexicon_usage import _NOT_EATEN as _NOT_EATEN
from hl.foods.lexicon_usage import _has_amount as _has_amount
from hl.foods.lexicon_usage import _is_helping as _is_helping
from hl.foods.lexicon_usage import _overlaps as _overlaps
from hl.foods.lexicon_usage import food_spots as food_spots
from hl.foods.lexicon_usage import helpings as helpings
from hl.foods.lexicon_usage import not_eaten as not_eaten
from hl.foods.lexicon_usage import placed as placed
from hl.foods.lexicon_usage import scan as scan
from hl.foods.lexicon_usage import spots as spots
from hl.foods.lexicon_usage import unrecorded as unrecorded
