"""hl foods fetch 的下载（第 2 步增补第 13.2 节）：按 hl.toml 里固定的提交，下载成分表和薄荷库的
原始数据，核对校验值，放进数据目录的 .hl/raw/<哪一份>/。整理还是 hl foods build 的那一段代码。

原始数据从网上来，不可信：文件名只认一层的普通名字，大小有上限，整份核对过校验值才用；
没核对上的不留。校验值是各文件“sha256  文件名”按文件名排好、一行一个，整个的 sha256。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from hl import store
from hl.foods import boohee, table

CN6, BOOHEE = table.CN6, "boohee"  # 哪一份；也是 .hl/raw/ 下的目录名
ENV = "HL_FOODS_URL"  # 测试用：改从这个地址下载（它下面的 /api 当 GitHub 的接口，/raw 当原始文件）
API, RAW = "https://api.github.com", "https://raw.githubusercontent.com"
RAW_DIR = "raw"
TIMEOUT = 60  # 秒，每次请求
MB = 1024 * 1024
MAX_FILE = 64 * MB  # 一个文件的上限（薄荷的 food_detail_backup.json 约 15 MB）
MAX_LISTING = 4 * MB
MAX_FILES = 500
BASE = re.compile(r"https?://[^\s/?#]+(?:/[^\s?#]*)?")
SOURCE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
COMMIT = re.compile(r"[0-9a-f]{7,40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[^/\\\x00-\x1f]+")  # 一层的文件名：不带路径分隔符和控制字符
# 每一份在 hl.toml [foods] 里的几个键：仓库、提交、仓库里的目录（薄荷库的文件在仓库根上）、校验值
KEYS = {
    CN6: ("source", "commit", "dataset", "raw_sha256"),
    BOOHEE: ("boohee_source", "boohee_commit", "", "boohee_raw_sha256"),
}
FILES = {CN6: (), BOOHEE: boohee.FILES}  # 固定的文件名；空的是列出目录里所有的 .json


class FetchError(Exception):
    """这一份没下载成：说出为什么（说给用户听的一句话）。"""


@dataclass(frozen=True)
class Base:
    """从哪里下载：GitHub 的接口（列目录）和原始文件。"""

    api: str
    raw: str


@dataclass(frozen=True)
class Pin:
    """一份原始数据固定的版本：哪个仓库、哪个提交、仓库里的哪个目录、哪些文件、校验值。"""

    kind: str
    source: str
    commit: str
    folder: str
    files: tuple[str, ...]
    digest: str
    values: dict[str, str]  # 用到的 hl.toml [foods] 的键和值

    def unrecorded(self, foods: Mapping[str, Any]) -> dict[str, str]:
        """hl.toml 里还没写着（没有这一行、是空的）的那几项：装好之后补写进去，记下装的是哪一版。"""
        return {key: value for key, value in self.values.items() if foods.get(key) != value}


@dataclass(frozen=True)
class Got:
    """核对过校验值的原始数据在哪：刚下载的临时目录，或之前下载过、核对无误的 .hl/raw/<哪一份>。"""

    kind: str
    folder: Path
    downloaded: bool


def base(environ: Mapping[str, str]) -> Base:
    url = environ.get(ENV, "").rstrip("/")
    if not url:
        return Base(API, RAW)
    if not BASE.fullmatch(url):
        raise FetchError(f"环境变量 {ENV} 不是 http:// 或 https:// 开头的地址：{url!r}")
    return Base(f"{url}/api", f"{url}/raw")


def _template() -> dict[str, Any]:
    text = resources.files("hl").joinpath("data", "templates", "hl.toml").read_text("utf-8")
    return tomllib.loads(text)["foods"]


def pins(foods: Mapping[str, Any]) -> dict[str, Pin | FetchError]:
    """两份各自固定的版本。hl.toml 里没有这一行、或者是空的，用引擎模板里的（以前的 hl.toml）；
    写法不对的那一份不下载。"""
    template = _template()
    found: dict[str, Pin | FetchError] = {}
    for kind, keys in KEYS.items():
        values = {key: str(foods.get(key) or template[key]) for key in keys if key}
        source, commit, digest = (values[keys[0]], values[keys[1]], values[keys[3]])
        folder = values.get(keys[2], "")
        wrong = [
            key
            for key, value, pattern in (
                (keys[0], source, SOURCE),
                (keys[1], commit, COMMIT),
                (keys[3], digest, DIGEST),
            )
            if not pattern.fullmatch(value) or ".." in value
        ]
        parts = folder.split("/") if folder else []
        if any(part in ("", ".", "..") or not NAME.fullmatch(part) for part in parts):
            wrong.append(keys[2])
        if wrong:
            found[kind] = FetchError(f"hl.toml 的 [foods] 里 {'、'.join(wrong)} 的写法不对")
        else:
            found[kind] = Pin(kind, source, commit, folder, FILES[kind], digest, values)
    return found


def raw_path(data_dir: Path, kind: str) -> Path:
    return data_dir / store.HIDDEN / RAW_DIR / kind


def digest(folder: Path, names: list[str] | tuple[str, ...]) -> str:
    lines = "".join(
        f"{hashlib.sha256((folder / name).read_bytes()).hexdigest()}  {name}\n"
        for name in sorted(names)
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _matches(folder: Path, pin: Pin) -> bool:
    """之前下载过的这一份还在、和校验值对得上。"""
    try:
        names = pin.files or [path.name for path in folder.glob("*.json") if path.is_file()]
        return bool(names) and digest(folder, names) == pin.digest
    except OSError:
        return False


def _get(url: str, what: str, limit: int) -> bytes:
    """下载一个地址；连不上、服务器报错、太大都是 FetchError。urllib 到用时才导入：
    别的命令启动时不用为它花时间。"""
    import http.client
    import urllib.error
    import urllib.request

    host = urlsplit(url).netloc
    request = urllib.request.Request(url, headers={"User-Agent": "hl"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        busy = "（多半是访问太频繁被限制了，过一会儿再试）" if exc.code in (403, 429) else ""
        raise FetchError(f"下载 {what} 时 {host} 回了 HTTP {exc.code}{busy}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"连不上 {host}（{exc.reason}）") from exc
    except TimeoutError as exc:
        raise FetchError(f"下载 {what} 时等 {host} 超过了 {TIMEOUT} 秒") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise FetchError(f"下载 {what} 时和 {host} 的连接断了（{exc}）") from exc
    if len(body) > limit:
        raise FetchError(f"{what} 超过 {limit // MB} MB，不像是要下载的数据")
    return body


def _listing(pin: Pin, where: Base) -> list[str]:
    """成分表目录里的 .json 文件名（GitHub 的接口列出来的）。"""
    folder = quote(pin.folder, safe="/")
    url = f"{where.api}/repos/{pin.source}/contents/{folder}?ref={pin.commit}"
    body = _get(url, f"{pin.folder} 的文件列表", MAX_LISTING)
    try:
        entries = json.loads(body)
    except ValueError as exc:
        raise FetchError(f"{pin.folder} 的文件列表读不出来（不是 JSON）") from exc
    if not isinstance(entries, list):
        raise FetchError(f"{pin.folder} 的文件列表读不出来（不是一个列表）")
    names = sorted(
        {
            entry["name"]
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("type") == "file"
            and isinstance(entry.get("name"), str)
            and entry["name"].endswith(".json")
        }
    )
    odd = [name for name in names if not NAME.fullmatch(name) or name.startswith(".")]
    if odd:
        raise FetchError(f"{pin.folder} 的文件列表里有不像文件名的一项：{odd[0]!r}")
    if not names:
        raise FetchError(f"{pin.folder} 里没有 .json 文件")
    if len(names) > MAX_FILES:
        raise FetchError(f"{pin.folder} 里有 {len(names)} 个 .json 文件，不像是要下载的数据")
    return names


def obtain(data_dir: Path, pin: Pin, where: Base) -> Got:
    """拿到这一份核对过的原始数据：之前下载过、对得上的不再下载；否则下载到 .hl/raw/ 下的临时
    目录，校验值对上才交出去。没成是 FetchError，临时目录不留。"""
    target = raw_path(data_dir, pin.kind)
    if _matches(target, pin):
        return Got(pin.kind, target, downloaded=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{pin.kind}-", dir=target.parent))
    try:
        names = pin.files or _listing(pin, where)
        folder = f"{quote(pin.folder, safe='/')}/" if pin.folder else ""
        for name in names:
            url = f"{where.raw}/{pin.source}/{pin.commit}/{folder}{quote(name)}"
            (temp / name).write_bytes(_get(url, name, MAX_FILE))
        if digest(temp, names) != pin.digest:
            key = KEYS[pin.kind][3]
            raise FetchError(f"下载的文件和 hl.toml 里记的校验值（[foods] {key}）对不上，没有用")
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return Got(pin.kind, temp, downloaded=True)


def place(data_dir: Path, got: Got) -> Path:
    """把刚下载的换到 .hl/raw/<哪一份>/（原来的整个换掉）；返回它。调用方持有数据目录的锁。"""
    target = raw_path(data_dir, got.kind)
    if not got.downloaded:
        return target
    if target.exists() or target.is_symlink():
        old = Path(tempfile.mkdtemp(prefix=f".{got.kind}-old-", dir=target.parent))
        os.replace(target, old / got.kind)
        os.replace(got.folder, target)
        shutil.rmtree(old, ignore_errors=True)
    else:
        os.replace(got.folder, target)
    return target


def discard(got: Got) -> None:
    """没用上的临时目录删掉（已经换到位的不在了，不用管）。"""
    if got.downloaded:
        shutil.rmtree(got.folder, ignore_errors=True)
