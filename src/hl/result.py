"""结果类型：六种 status，各自对应固定的退出码和固定字段（设计说明第 3 节，R1；增补第 8.1 节）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXIT_CODES = {
    "ok": 0,
    "duplicate": 0,
    "error": 1,
    "rejected": 2,
    "needs_input": 3,
    "needs_estimate": 4,
}

NEXT_ASK = (
    "把 tell_user 原样问用户；拿到回答后，把回答原话追加到 answers，"
    "回答里说了份量的补上 amount，其余不变，再调用一次同一条命令"
)
NEXT_FIX = "按 errors 里每一条的 fix 改好输入，再调用一次；不要直接改数据文件"
# 用户在确认时说了不：这件事到此为止。fix 以它开头的错误，next 也不叫模型再调用（R19）
STOP = "用户没有同意：这件事不办，告诉用户没有执行，不要再调用"
NEXT_STOP = (
    "用户没有同意，这件事不办：告诉用户没有执行，不要再调用这条命令。"
    "用户说了新的、或者后来又说要办，照 fix 里说的办"
)
# 引擎问过之后用户还没说话就带了确认：fix 以它开头的错误，next 也不叫模型马上再调用（R19）
WAIT = "把上次返回的 tell_user 原样问用户，等用户回答之后再带确认调用"
NEXT_WAIT = (
    "引擎的提问用户还没有回答：先把上次返回的 tell_user 原样问用户，"
    "等用户回答了，再把回答的原话带上确认调用一次；用户回答之前不要再调用"
)
# 要用户再说一句才办得了（引擎认不准他的说法、那句话里少了要核对的字）：fix 以它开头的错误，
# next 也不叫模型马上再调用、自己改写原话，先请用户说（第 3 节）
SAY_AGAIN = "要用户再说一句才办得了，用户说之前不要再调用"
NEXT_SAY_AGAIN = (
    "要用户再说一句才办得了：照 fix 请用户再说一句，等用户说了，用他新说的原话再调用一次；"
    "用户说之前不要再调用，也不要自己改写原话"
)
NEXT_REPORT = "这是引擎或安装的问题：把 error 原样告诉用户，不要自己改文件"
# 库里没有的食物要模型估（增补第 8.1 节）：没有 tell_user，不用问用户，模型自己估好再调用
HOW_ESTIMATE = (
    "每一样照 unknown 里它的 template 改好：estimate 优先用 parts，把它拆成库里的原料和可食部"
    "克数（food 照抄 near、ingredients 里的 ref，或者写常见的原料名）。g 的生熟、干湿口径跟 "
    "food 所引用的条目一致：生猪肉填生重，蒸米饭填熟重，干面条填干重；不要把熟食条目的 g "
    "换成生料重量。拆不了就改用 nutrition "
    "给用户说的这个量整份的热量、蛋白质、脂肪、碳水（克）和钠（毫克）。basis 写按什么估的；"
    "上网查到的写上 url。template 的 parts 已经预填成这一样本身的（库里有，只是没有用户说的"
    "这个量词），food 不要改，只把 g 改成用户说的这个量大约多少克；预填了这样食物和“油”两样的"
    "（炸的、糖醋的，算另一种食物），两样都估上克数，裹的粉、糖醋汁这类另加。"
    "把 items 里这一项换成改好的 template，其余不变，再调用一次"
)
NEXT_ESTIMATE = (
    f"库里没有这几样（或没有用户说的量词），要你来估，不用问用户。{HOW_ESTIMATE}。"
    "估不出来、要用户说清楚是什么的，先问用户，用他回答的原话追加到 answers"
)
# 要问用户、同时有库里没有的几样要估（增补第 8.1 节）：问完再估，带回答的那次调用里可以一并交上
NEXT_ASK_ESTIMATE = (
    f"{NEXT_ASK}。unknown 里列的几样库里没有，要你来估（这个不用问用户）：可以在带回答的那次调用里"
    f"一并交上，也可以先不填、等引擎返回 needs_estimate 再估。{HOW_ESTIMATE}"
)


class Note(str):
    """一条提醒：整句是给模型的（放进 warnings），tell 是其中说给用户听的那部分（接在 tell_user
    后面）。叫模型运行哪条命令的话不进 tell_user：模型原样转告，用户就看到写给模型的话了。"""

    tell: str

    def __new__(cls, tell: str, then: str) -> Note:
        note = super().__new__(cls, f"{tell.rstrip('。')}。{then}")
        note.tell = tell
        return note


@dataclass
class Result:
    """一条命令的结果；cli 把它打成一个 JSON 对象并换算成退出码。"""

    status: str
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.status]

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, **self.fields}

    def warn(self, warnings: list[str], tell: bool = True) -> Result:
        """附上不影响结果的提醒（例如自动提交失败）。

        tell 为真时提醒也接在 tell_user 后面：模型照常原样转告，用户就知道了，
        不靠模型留意 warnings。是 Note 的只接它说给用户的那部分。
        """
        if warnings:
            self.fields["warnings"] = [*self.fields.get("warnings", []), *warnings]
            if tell and "tell_user" in self.fields:
                told = (getattr(text, "tell", text) for text in warnings)
                said = "".join(f"提醒：{text.rstrip('。')}。" for text in told)
                self.fields["tell_user"] += said
        return self


class Abort(Exception):
    """带着结果提前结束一条命令（不一定是出错）。

    任何模块都可以抛，只有 cli 把它变成输出和退出码。
    """

    def __init__(self, result: Result) -> None:
        super().__init__(result.status)
        self.result = result


def ok(tell_user: str, **fields: Any) -> Result:
    return Result("ok", {"tell_user": tell_user, **fields})


def duplicate(tell_user: str, entry_id: str, **fields: Any) -> Result:
    return Result("duplicate", {"tell_user": tell_user, "id": entry_id, **fields})


def needs_input(questions: list[dict[str, Any]], next_step: str = NEXT_ASK) -> Result:
    tell_user = " ".join(dict.fromkeys(q["ask"] for q in questions))  # 一样的问题只问一遍
    return Result(
        "needs_input", {"questions": questions, "tell_user": tell_user, "next": next_step}
    )


def needs_estimate(unknown: list[dict[str, Any]], next_step: str = NEXT_ESTIMATE) -> Result:
    """库里没有的食物要模型估（增补第 8.1 节）。不问用户，所以没有 tell_user。"""
    return Result("needs_estimate", {"unknown": unknown, "next": next_step})


def rejected(errors: list[dict[str, str]], next_step: str = NEXT_FIX) -> Result:
    if next_step == NEXT_FIX and any(item["fix"].startswith(STOP) for item in errors):
        next_step = NEXT_STOP  # 用户说了不：不能再叫模型“改好输入，再调用一次”
    elif next_step == NEXT_FIX and any(item["fix"].startswith(WAIT) for item in errors):
        next_step = NEXT_WAIT  # 用户还没回答：先问用户，不是马上再调用
    elif next_step == NEXT_FIX and any(item["fix"].startswith(SAY_AGAIN) for item in errors):
        next_step = NEXT_SAY_AGAIN  # 要用户再说一句：先请他说，不是自己改写了马上再调用
    return Result("rejected", {"errors": errors, "next": next_step})


def error(message: str, next_step: str = NEXT_REPORT) -> Result:
    return Result("error", {"error": message, "next": next_step})


def question(item: str, field_name: str, ask: str, options: list[str], why: str) -> dict[str, Any]:
    """一个追问。field_name 只能是 variant、amount、state、net、confirm。"""
    return {"item": item, "field": field_name, "ask": ask, "options": options, "why": why}


def problem(where: str, what: str, fix: str) -> dict[str, str]:
    """一条输入错误。fix 必须告诉模型具体怎么改。"""
    return {"where": where, "problem": what, "fix": fix}
