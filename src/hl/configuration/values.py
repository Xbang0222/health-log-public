"""配置结构校验、上下文、日期和纯 TOML 字段处理。"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from hl.result import Abort, error, problem, rejected

FORMAT = 2


CONFIG_NAME = "hl.toml"


HINT_INIT = "先运行 hl init [目录] 生成数据目录，或把环境变量 HL_DATA 指向已有的数据目录"


SHA_LINE = re.compile(r'^sha256\s*=\s*"([^"]*)"', re.MULTILINE)


AUTOCOMMIT = re.compile(r"^\s*autocommit\s*=\s*(true|false)\b", re.MULTILINE)


MARKED = re.compile(r"^\s*\[manifest\]", re.MULTILINE)


MANIFEST_MARK = (
    "\n[manifest]\n"
    "built = true         # 引擎加的记号：清单（.hl/manifest.json）已经建过，它再不见就是丢了\n"
)


@dataclass(frozen=True)
class Context:
    """一次调用的环境：数据目录、今天、现在、hl.toml 的内容。"""

    data_dir: Path
    today: str
    now: datetime
    no_git: bool
    settings: dict[str, Any]

    @property
    def autocommit(self) -> bool:
        return not self.no_git and bool(self.settings.get("git", {}).get("autocommit", True))

    @property
    def foods(self) -> dict[str, Any]:
        return self.settings.get("foods", {})

    @property
    def foods_sha(self) -> str:
        """hl foods build 记下的成分表副本哈希；还没构建时是空串。"""
        return str(self.foods.get("sha256", ""))

    @property
    def boohee_sha(self) -> str:
        """薄荷库副本的哈希（增补第 13.1 节）；为空表示没装，以前的 hl.toml 没有这一行也是没装。"""
        return str(self.foods.get("boohee_sha256", ""))


def _settings_wrong(settings: Mapping[str, Any]) -> str | None:
    """引擎要用的那几项写法不对时，说哪里不对（R15）。别的键不管。"""
    foods = settings.get("foods")
    if not isinstance(foods, dict):
        return "没有 [foods] 这一节"
    if "sha256" not in foods:
        return "[foods] 里没有 sha256 这一行"
    if not isinstance(foods["sha256"], str):
        return "[foods] 的 sha256 不是一串文字"
    git = settings.get("git", {})
    if not isinstance(git, dict) or not isinstance(git.get("autocommit", True), bool):
        return "[git] 的 autocommit 只能是 true 或 false"
    if "manifest" in settings:
        mark = settings["manifest"]
        if not isinstance(mark, dict) or mark.get("built") is not True:
            return "[manifest] 一节只能是引擎加的那一行 built = true"
    return None


def _parsed(text: str) -> dict[str, Any] | None:
    """一份 hl.toml 的内容用得上时返回它：读得出来，格式版本对，引擎要用的几项写法也对。"""
    try:
        settings = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    if settings.get("format") not in (1, FORMAT) or _settings_wrong(settings):
        return None
    return settings


def _shown(value: bool) -> str:
    return "true" if value else "false"


def _raw_dir_in(text: str) -> str:
    """一份（可能写坏了的）hl.toml 里 raw_dir 那一行的值；没有、读不出是空串。"""
    hit = RAW_DIR_LINE.search(text)
    if hit is None:
        return ""
    try:
        value = tomllib.loads("raw_dir = " + hit[0][len(hit[1]) :])["raw_dir"]
    except tomllib.TOMLDecodeError:
        return ""
    return value if isinstance(value, str) else ""


def now(environ: Mapping[str, str]) -> datetime:
    raw = environ.get("HL_NOW")
    if not raw:
        return datetime.now().astimezone()
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise Abort(error(f"环境变量 HL_NOW 不是合法的 ISO 8601 时间：{raw}")) from exc
    return value if value.tzinfo else value.astimezone()


def today(environ: Mapping[str, str]) -> str:
    raw = environ.get("HL_TODAY")
    if not raw:
        return now(environ).date().isoformat()
    if not is_date(raw):
        raise Abort(error(f"环境变量 HL_TODAY 不是合法日期（YYYY-MM-DD）：{raw}"))
    return raw


def is_date(text: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def pick_date(given: str | None, fallback: str, where: str) -> str:
    """命令里给了日期就校验后用它，没给就用今天。"""
    if given is None:
        return fallback
    if not is_date(given):
        fix = "日期写成 YYYY-MM-DD；用户没说日期就不要填"
        raise Abort(rejected([problem(where, f"“{given}”不是合法日期", fix)]))
    return given


RAW_DIR_LINE = re.compile(r"""^(raw_dir\s*=\s*)(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*')""", re.MULTILINE)


RAW_DIR_NOTE = "# hl foods build 写入：构建用的原始数据目录，成分表副本坏了照它重新构建"


def _toml_string(text: str) -> str:
    """TOML 的基本字符串：引号、反斜杠和控制字符转义，别的原样。"""
    escaped = "".join(
        f"\\{ch}"
        if ch in '"\\'
        else f"\\u{ord(ch):04x}"
        if ord(ch) < 0x20 or ord(ch) == 0x7F
        else ch
        for ch in text
    )
    return f'"{escaped}"'


def _with_raw_dir(text: str, raw_dir: str) -> str:
    """把原始数据目录写进 [foods] raw_dir：有这一行就换掉值，没有（以前的 hl.toml）就加在
    sha256 那一行后面。写出来读不回同一个目录（路径里有写不进 TOML 的字符），就不记。"""
    value = _toml_string(raw_dir)
    updated, count = RAW_DIR_LINE.subn(lambda hit: hit[1] + value, text, count=1)
    if count == 0:
        sha = re.search(r"^sha256\s*=.*$", text, flags=re.MULTILINE)
        if sha is None:
            return text
        line = f"\nraw_dir = {value}    {RAW_DIR_NOTE}"
        updated = text[: sha.end()] + line + text[sha.end() :]
    try:
        foods = tomllib.loads(updated).get("foods", {})
    except tomllib.TOMLDecodeError:
        return text
    return updated if isinstance(foods, dict) and foods.get("raw_dir") == raw_dir else text


FOODS_KEY = re.compile(r"^[A-Za-z0-9_]+\s*=[^\n]*$", re.MULTILINE)


def _foods_end(text: str) -> int | None:
    """hl.toml 里 [foods] 这一节最后一项的行尾；没有这一节是 None。"""
    head = re.search(r"^\[foods\][^\n]*$", text, re.MULTILINE)
    if head is None:
        return None
    after = re.search(r"^\[", text[head.end() :], re.MULTILINE)
    stop = head.end() + after.start() if after else len(text)
    keys = list(FOODS_KEY.finditer(text, head.end(), stop))
    return keys[-1].end() if keys else head.end()


def foods_raw_dir(data_dir: Path, key: str = "raw_dir") -> str:
    """hl foods build 记下的原始数据目录（成分表的是 raw_dir，薄荷库的是 boohee_raw_dir）；
    没记、读不出来都是空串。只用来给改法，不挡任何命令。"""
    try:
        foods = tomllib.loads((data_dir / CONFIG_NAME).read_text(encoding="utf-8")).get("foods")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ""
    raw = foods.get(key) if isinstance(foods, dict) else None
    return raw if isinstance(raw, str) else ""
