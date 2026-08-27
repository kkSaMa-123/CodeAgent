"""命令执行前的三档风险分类。"""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from enum import StrEnum


class CommandRisk(StrEnum):
    ALLOW = "allow"
    APPROVAL_REQUIRED = "approval_required"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class CommandDecision:
    risk: CommandRisk
    reason: str


DENY_PATTERNS = (
    (
        re.compile(r"(^|[;&|]\s*)(sudo\s+)?(shutdown|reboot|halt|poweroff)\b", re.I),
        "禁止系统电源操作",
    ),
    (re.compile(r"\b(mkfs|fdisk|diskutil\s+erase|format)\b", re.I), "禁止磁盘破坏操作"),
    (re.compile(r"\bdd\b[^;&|]*\bof=/dev/", re.I), "禁止写入设备"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:", re.I), "禁止 fork bomb"),
    (re.compile(r"\brm\s+-[^\n;&|]*r[^\n;&|]*f[^\n;&|]*(/|~)(\s|$)", re.I), "禁止递归删除系统路径"),
    (
        re.compile(r"(^|\s)(/etc|/System|/Library|/usr|/bin|/sbin|/var)(/|\s|$)"),
        "禁止操作工作区外系统路径",
    ),
)

APPROVAL_PATTERNS = (
    (re.compile(r"(^|[;&|]\s*)(rm|rmdir|mv)\b", re.I), "命令可能删除或移动文件"),
    (re.compile(r"\b(pip|pip3|uv|poetry)\s+install\b", re.I), "命令将安装 Python 依赖"),
    (
        re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|add|remove|update)\b", re.I),
        "命令将修改前端依赖",
    ),
    (
        re.compile(
            r"\bgit\s+(add|commit|push|pull|checkout|switch|merge|rebase|reset|clean|restore|tag)\b",
            re.I,
        ),
        "命令将修改 Git 状态",
    ),
    (re.compile(r"(^|[^<])>{1,2}\s*[^&]", re.I), "命令包含文件重定向"),
)

ALLOW_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff",),
    ("mypy",),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("pnpm", "test"),
    ("pnpm", "build"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "show"),
    ("git", "branch"),
    ("ls",),
    ("pwd",),
    ("find",),
    ("rg",),
)


def classify_command(command: str) -> CommandDecision:
    if not command.strip():
        return CommandDecision(CommandRisk.DENY, "命令不能为空")
    if "\x00" in command or "\n" in command or "\r" in command:
        return CommandDecision(CommandRisk.DENY, "命令不能包含 NUL 或换行符")
    for pattern, reason in DENY_PATTERNS:
        if pattern.search(command):
            return CommandDecision(CommandRisk.DENY, reason)
    for pattern, reason in APPROVAL_PATTERNS:
        if pattern.search(command):
            return CommandDecision(CommandRisk.APPROVAL_REQUIRED, reason)
    try:
        tokens = tuple(shlex.split(command))
    except ValueError:
        return CommandDecision(CommandRisk.DENY, "命令引号不完整")
    lowered = tuple(token.lower() for token in tokens)
    if tokens and tokens[0] == sys.executable:
        lowered = ("python", *lowered[1:])
    for prefix in ALLOW_PREFIXES:
        if lowered[: len(prefix)] == prefix:
            return CommandDecision(CommandRisk.ALLOW, "低风险验证或只读命令")
    return CommandDecision(CommandRisk.APPROVAL_REQUIRED, "命令未命中自动允许规则")
