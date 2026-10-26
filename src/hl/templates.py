"""项目模板的唯一读取、遍历和占位展开服务。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from hl import guard
from hl.storage import git_messages as storage_git_messages

SLOT = "{protected}"  # 模板里的占位：受保护路径的名单只在 guard 里有一份，生成时填进来
TOOLS_SLOT = "{prompt_tools}"  # 权限规则里的占位：禁止的那几个工具也只在 guard 里列一份
NOT_EXCLUDED_SLOT = "{not_excluded}"  # 钩子模板里的占位：那句话只在 store 里有一份
INDEX_PATHS_SLOT = "{protected_paths_json}"  # Git index 核对与 Agent 共用同一份保护路径


def walk(node: Traversable, prefix: str = "") -> Iterator[tuple[str, Traversable]]:
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}{child.name}"
        if child.is_dir():
            yield from walk(child, f"{relative}/")
        else:
            yield relative, child


def _protected(suffix: str) -> list[str]:
    """受保护路径的写法：目录后面带上 suffix（"/" 或 "/**"），文件原样。"""
    return [f"{name}{suffix}" for name in guard.PROTECTED_DIRS] + list(guard.PROTECTED_FILES)


def _expanded(node: Any) -> Any:
    """JSON 模板里带占位的权限规则：每个受保护路径各写一条，禁止的每个工具各写一条。"""
    if isinstance(node, dict):
        return {key: _expanded(value) for key, value in node.items()}
    if not isinstance(node, list):
        return node
    out: list[Any] = []
    for item in node:
        if item == TOOLS_SLOT:
            out += list(guard.PROMPT_TOOLS)
        elif isinstance(item, str) and SLOT in item:
            out += [item.replace(SLOT, path) for path in _protected("/**")]
        else:
            out.append(_expanded(item))
    return out


def template(relative: str) -> str:
    """模板 relative 填好占位之后的文本：hl init 照它写，hl doctor 拿它核对。"""
    source = resources.files("hl").joinpath("data", "templates", *relative.split("/"))
    return render(relative, source.read_text(encoding="utf-8"))


def render(relative: str, text: str) -> str:
    """把模板里的占位换成受保护路径：JSON 里一条规则展开成几条，别的文件里换成一串路径名。
    提交前的钩子里 .gitignore 放出 .hl/ 时说的那句话也在这里填：和 hl init、hl doctor 说的一样。"""
    text = text.replace(INDEX_PATHS_SLOT, json.dumps(_protected("/")))
    text = text.replace(
        NOT_EXCLUDED_SLOT,
        storage_git_messages.NOT_EXCLUDED.format(what=storage_git_messages.KEPT_OUT[".hl/"]),
    )
    if SLOT not in text and TOOLS_SLOT not in text:
        return text
    if relative.endswith(".json"):
        return json.dumps(_expanded(json.loads(text)), ensure_ascii=False, indent=2) + "\n"
    return text.replace(SLOT, "、".join(f"`{path}`" for path in _protected("/")))
