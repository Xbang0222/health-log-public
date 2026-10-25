"""Git 子进程执行、超时终止与错误摘要。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hl.storage.git_messages import HINTS, LISTED, LOCKED, NO_GIT_COMMAND

GIT_TIMEOUT = 60


GIT_GRACE = 5  # 超时后先请 git 自己收拾好（删掉它拿着的锁）再退出，等这么多秒还不退才强行结束


BRIEF_WIDTH = 200  # 提醒里每行最多带这么多字


def _git(
    data_dir: Path, *args: str, check: bool = True, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    """在数据目录里跑一条 git 命令。GIT_TIMEOUT 秒没做完就停掉它（_stop），抛 TimeoutExpired。"""
    command = ["git", "-C", str(data_dir), *args]
    stdin = subprocess.DEVNULL if input is None else subprocess.PIPE
    with subprocess.Popen(
        command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=GIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _stop(process)
            raise
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _stop(process: subprocess.Popen[str]) -> None:
    """git 超时了：先发 SIGTERM，git 收到会删掉自己拿着的锁（index.lock）再退出；等 GIT_GRACE 秒
    还不退，才强行结束（那样锁会留下）。不等它的输出读完：它起的钩子、签名程序可能还拿着不放。"""
    process.terminate()
    try:
        process.wait(timeout=GIT_GRACE)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _brief(exc: Exception) -> str:
    """git 出错的原因，一句话：报错的第一行（后面几行多是建议，拼在一起就成了碎片）。
    常见的几种换成说得清的话。"""
    if isinstance(exc, FileNotFoundError) and exc.filename == "git":
        return NO_GIT_COMMAND
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"git 在 {GIT_TIMEOUT} 秒内没有做完"
    detail = str(getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or exc)
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    if not lines:
        return type(exc).__name__
    first = lines[0]
    if "index.lock" in first:
        # 路径只说明失败发生在哪；EEXIST、权限和只读是不同的失败原因。
        reason = first.rpartition("index.lock")[2].strip("'\" :：。.")
        cause = reason.casefold()
        if cause in ("file exists", "文件已存在"):
            return LOCKED
        if cause in ("operation not permitted", "permission denied", "不允许的操作", "权限不够"):
            return f"git 没有权限创建索引锁（{reason}）"
        if cause in ("read-only file system", "只读文件系统"):
            return f"git 无法创建索引锁：文件系统只读（{reason}）"
    if first.endswith((":", "：")):  # 要紧的在下面几行（下列路径……被忽略：）：带上，不带提示行
        named = [line for line in lines[1:] if not line.lower().startswith(HINTS)]
        first += "、".join(named[:LISTED])
    return first[:BRIEF_WIDTH].rstrip("。.")
