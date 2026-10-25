"""体重表达及否定改口用词。"""

from __future__ import annotations

import re
import unicodedata

from hl.language.units import CLAUSE_END

# 说体重的词（R16）：整条消息里除了那一个数和它的单位，只剩这些词和标点、空白，才一眼清楚、
# 直接记；多出别的任何字（“瘦了”“目标”“老婆”“hhh”……）都先问。宁缺勿滥：少认一个词只是多问一次，
# 多认一个就可能把不是现在体重的数直接记下。只看繁体折成简体之后的字
WEIGHT_WORDS = (
    "体重", "称重", "今天", "今日", "今早", "今早上", "今晨", "早上", "早晨", "清晨", "晨起",
    "起床", "起来", "空腹", "称了", "称", "刚称", "刚刚", "上秤", "上磅",
    "现在", "目前",
    # “一下”只在称、记后面算（“称一下”）；跟在数或单位后面的是“以下”，见 _ROUGH_TAIL
    "称一下", "称了一下", "称了下", "称重一下", "记一下", "体重秤显示",
    # 记体重常说的（第九轮 W-8）；说别人的、目标、变化的词（“老婆”“目标”“减了”）照旧不算。
    # 测、量不算（“测了一下 36.5”多半是体温、血压、血糖，第十轮 W-7，规则 22）：只认称
    "帮我", "帮我记", "记录", "记录一下", "打卡", "刚才", "刚", "早起", "起床后", "晨重",
    "称一称", "本人",
    "是", "为", "我", "的", "了",
)  # fmt: skip


_WEIGHT_WORDS = re.compile("|".join(sorted(WEIGHT_WORDS, key=len, reverse=True)))

# 键帽数字有独立的组合符号，visible 会去掉变体选择符但保留键帽；不能截成 7、8 两个数。
_KEYCAP_NUMBER = re.compile(r"(?:[0-9]\ufe0f?\u20e3)+")


_ENDS_WITH_WEIGHT_WORD = re.compile(rf"(?:{_WEIGHT_WORDS.pattern})$")

# 句尾（这半句完、后面只剩标点空白）的语气词和拖长音的“~”也不算多出来的字（“体重 78.5 哦”
# “78.5啦~”，第九轮 W-8）。“吧”不算：“78.5吧”是拿不准；不在句尾的（“哦 78.5”）照旧算
_TRAILING_PARTICLES = re.compile(rf"[啊呀哦啦呢嘛~〜]+(?=[\s.…)\]]*(?:$|[{CLAUSE_END}]))")

# 标点里不算“只是标点”的：问号（“78.5？”是在问）、破折号和连字符（“-25kg”可能是掉了 25 公斤）、
# 中文输入法打出的大于小于号（“》80”，见 _HEDGE）
_NOT_JUST_MARKS = "?¿《》〈〉‹›«»"


def _just_marks(ch: str) -> bool:
    """空白和标点（问号、破折号、“》”这类大于小于号除外，见 _NOT_JUST_MARKS）：
    一眼清不清楚时不算多出来的字。"""
    category = unicodedata.category(ch)
    if category[0] == "Z" or ch.isspace():
        return True
    return category[0] == "P" and category != "Pd" and ch not in _NOT_JUST_MARKS


def _joined(text: str, pos: int) -> bool:
    """text[pos] 夹在两个数字中间（“0.3”“7:00”的点、冒号），或者是夹在两个字母中间的空格
    （“I weigh”）：说的是同一段话，不断开。"""
    if not 0 < pos < len(text) - 1:
        return False
    before, ch, after = text[pos - 1], text[pos], text[pos + 1]
    if ch.isspace():
        return ch == " " and _latin(before) and _latin(after)
    return before.isdigit() and after.isdigit()


def _latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()
