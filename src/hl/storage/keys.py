"""签名密钥读取、已有签名资料识别与 HMAC 签名核验。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

from hl.result import Abort, Result, error
from hl.storage.days import day_like_files, scan_log
from hl.storage.io import DEFAULTS_FILE, HIDDEN, PLAN_FILE, UNREADABLE, read_yaml

# ---------- 签名（R14） ----------
SECRET = f"{HIDDEN}/secret"


NEXT_SECRET = (
    f"签名密钥只在这台机器的 {SECRET} 里，不进 git，git 里也没有它。请用户从备份恢复 {SECRET}，"
    "放回去再调用一次；恢复不了，把这个问题原样告诉用户，就此停下，不要自己生成密钥：换一把新的，"
    "已有的记录、计划、默认品种就都对不上签名了"
)


NEXT_NEW_SECRET = "还没有签过名的数据，换一把新密钥不碍事：运行 hl init 补齐数据目录，再调用一次"


NEXT_SECRET_OS = (
    f"{SECRET} 的位置上是个目录，或者引擎没有读它的权限，引擎修不了："
    "把问题原样告诉用户，请用户看一下——是个目录就挪走它（先看看里面有没有要留的东西），"
    "再把密钥从备份放回去；没有权限就改好权限。你就此停下，不要自己生成密钥"
)


KEY_FORM = re.compile(rb"[0-9a-f]{64}")  # hl init 生成的样子：secrets.token_hex(32)


KEY_LENGTH = 64


NOT_HEX = re.compile(rb"[^0-9a-f]")


BOM = b"\xef\xbb\xbf"


# 套在两头的一对引号（开头的，结尾的）：中文输入法下抄的是弯引号
QUOTES = tuple((a.encode(), b.encode()) for a, b in ('""', "''", "“”", "‘’"))


WRONG_FORM = "的格式不对：不是引擎生成的那种 64 位十六进制，{what}"


NOT_FITTING = (
    "对不上这个数据目录：清单和文件里签过名的东西，用它一条都验不过（多半是换了一把、抄错了备份）"
)


def signed_data(data_dir: Path) -> bool:
    """数据目录里有没有签过名的数据：每日文件、计划、默认品种、清单，或者 hl.toml 里清单建过的记号。
    有的话密钥只能从备份恢复，不能换一把新的（R14、R22）。"""
    named = (PLAN_FILE, DEFAULTS_FILE, f"{HIDDEN}/manifest.json", f"{HIDDEN}/intents.json")
    if any((data_dir / name).exists() for name in named):
        return True
    scan = scan_log(data_dir)
    if scan.days or scan.odd or scan.links or scan.blocked:
        return True
    try:
        text = (data_dir / "hl.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return re.search(r"^\s*\[manifest\]", text, re.MULTILINE) is not None


def _copied_key(raw: bytes) -> bytes:
    """从备份抄回来时常见的样子还原成 hl init 写的那样：去掉两头空白、开头的 BOM、
    套在两头的一对引号（英文的、中文弯引号都算），十六进制不分大小写（R14）。还原错了也不要紧：
    签名验不过，照样报对不上。"""
    key = raw.strip()
    if key.startswith(BOM):
        key = key[len(BOM) :].strip()
    for start, end in QUOTES:
        if len(key) >= len(start) + len(end) and key.startswith(start) and key.endswith(end):
            key = key[len(start) : -len(end)].strip()
            break
    return key.lower()


def _wrong_form(key: bytes) -> str:
    """格式不对时说出是哪一种：混进了别的字，还是位数不对（截短了、多了）。位数按字数算，不按
    字节数：混进一个全角字，UTF-8 里占 3 个字节，用户数的是 1 位。"""
    found = []
    if NOT_HEX.search(key):
        found.append("混进了不是十六进制（0-9、a-f）的字")
    count = len(key.decode("utf-8", errors="replace"))  # 不是 UTF-8 的字节，一个算一位
    if count < KEY_LENGTH:
        found.append(f"只有 {count} 位（可能抄漏了，或者文件被截断了）")
    elif count > KEY_LENGTH:
        found.append(f"有 {count} 位（多出来一截，可能多抄了别的东西）")
    return WRONG_FORM.format(what="；".join(found))


def read_secret(data_dir: Path) -> tuple[bytes | None, str, bool]:
    """读密钥、核对格式，不看它对不对得上数据：（密钥，用不了时说哪里不对，是不是读不了）。
    读不了是位置上是个目录、没有权限：hl init 也修不了，只能请用户看一下（R14）。"""
    try:
        raw = (data_dir / SECRET).read_bytes()
    except FileNotFoundError:
        return None, f"签名密钥 {SECRET} 不存在", False
    except OSError:
        return None, f"签名密钥 {SECRET} {UNREADABLE}", True
    # 十六进制是 ASCII；UTF-16 的每两个字节里有一个 NUL。只诊断编码，不换密钥，
    # 也不自动改写用户恢复的文件。误加两个 BOM 字节但主体仍为 UTF-8 的照常报字符问题。
    if b"\0" in raw:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                decoded = raw.decode(encoding)
            except UnicodeError:
                continue
            if decoded and decoded.isascii() and "\0" not in decoded:
                what = "文件存成了 UTF-16；请保留原密钥内容，用 UTF-8 编码保存"
                return None, f"签名密钥 {SECRET} {what}", False
    key = _copied_key(raw)
    if not key:
        return None, f"签名密钥 {SECRET} 是空的", False
    if not KEY_FORM.fullmatch(key):
        return None, f"签名密钥 {SECRET} {_wrong_form(key)}", False
    return key, "", False


def secret_error(data_dir: Path, what: str, unreadable: bool) -> Result:
    """密钥用不了时各条命令（和 hl init）返回的 error：读不了的请用户看一下；有签过名的数据时
    只能从备份恢复；还没有的，hl init 换一把新的就好（R14）。"""
    if unreadable:
        return error(what, NEXT_SECRET_OS)
    return error(what, NEXT_SECRET if signed_data(data_dir) else NEXT_NEW_SECRET)


def secret(data_dir: Path) -> bytes:
    """签名密钥。不存在、读不了、是空的、格式不对，或者对不上数据目录里签过名的东西，都返回 error：
    不当成“所有数据都被改过”，免得照 fix 重建出空清单、再一条条撤掉记录（R14）。"""
    key, what, unreadable = read_secret(data_dir)
    if key is not None:
        if _fits(data_dir, key):
            return key
        what = f"签名密钥 {SECRET} {NOT_FITTING}"
    raise Abort(secret_error(data_dir, what, unreadable))


def _quiet_yaml(path: Path) -> Any:
    try:
        return read_yaml(path)
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return None


def _signed_things(data_dir: Path) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """文件里带签名的每一样：（种类，所属，内容）。读不出来、形状不对的跳过。"""
    intent = _quiet_yaml(data_dir / HIDDEN / "intents.json")
    if isinstance(intent, dict) and "sig" in intent:
        yield "intents", "", intent
    plans = _quiet_yaml(data_dir / PLAN_FILE)
    for plan in plans if isinstance(plans, list) else []:
        if isinstance(plan, dict) and "sig" in plan:
            yield "plan", "", plan
    defaults = _quiet_yaml(data_dir / DEFAULTS_FILE)
    for name, entry in defaults.items() if isinstance(defaults, dict) else []:
        if isinstance(entry, dict) and "sig" in entry:
            yield "default", name, entry
    for path, day in day_like_files(data_dir):
        doc = _quiet_yaml(path)
        if not isinstance(doc, dict):
            continue
        entries = doc.get("entries")
        parts = [("entry", e) for e in entries] if isinstance(entries, list) else []
        parts += [(name, doc.get(name)) for name in ("weight", "day_type")]
        for kind, part in parts:
            if isinstance(part, dict) and "sig" in part:
                yield kind, day, part


def _fits(data_dir: Path, key: bytes) -> bool:
    """这把密钥对得上数据目录里签过名的东西（R14）。清单验签通过就算；清单验不过（不见了、
    读不出来、被改过），再看文件里签过名的东西：有一条验得过就算（那是别的东西被改过，由读时校验
    去报），一条都验不过才是密钥不对。还没有签过名的东西，无从核对，也算。"""
    try:
        body = json.loads((data_dir / HIDDEN / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        body = None
    if isinstance(body, dict) and signed(key, "manifest", "", body):
        return True
    seen = False
    for kind, scope, thing in _signed_things(data_dir):
        if signed(key, kind, scope, thing):
            return True
        seen = True
    return not seen


def sign(key: bytes, kind: str, scope: str, body: Mapping[str, Any]) -> str:
    """对"种类 + 所属日期 + 内容"做 HMAC-SHA256；防手滑和偷懒，不防蓄意伪造。"""
    payload = {"kind": kind, "scope": scope, "body": {k: v for k, v in body.items() if k != "sig"}}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


def signed(key: bytes, kind: str, scope: str, body: Mapping[str, Any]) -> bool:
    sig = body.get("sig")
    if not isinstance(sig, str):
        return False
    try:
        return hmac.compare_digest(sig, sign(key, kind, scope, body))
    except (TypeError, ValueError):  # 内容里有 JSON 写不出来的东西，不会是引擎签的
        return False
