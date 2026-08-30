"""工具目录、对话能力配置与运行快照。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOOL_CATALOG: tuple[dict[str, str | bool], ...] = (
    {
        "name": "list_files",
        "label": "查看项目文件",
        "description": "浏览工作区目录结构",
        "group": "readonly",
        "risk": "只读",
        "default_enabled": True,
    },
    {
        "name": "read_file",
        "label": "读取文件",
        "description": "读取工作区 UTF-8 文本文件",
        "group": "readonly",
        "risk": "只读",
        "default_enabled": True,
    },
    {
        "name": "search_text",
        "label": "搜索代码",
        "description": "在工作区内搜索文本",
        "group": "readonly",
        "risk": "只读",
        "default_enabled": True,
    },
    {
        "name": "git_diff",
        "label": "查看代码变更",
        "description": "查看工作区 Git Diff",
        "group": "readonly",
        "risk": "只读",
        "default_enabled": True,
    },
    {
        "name": "write_file",
        "label": "写入文件",
        "description": "创建或覆盖文本文件",
        "group": "editing",
        "risk": "修改工作区",
        "default_enabled": True,
    },
    {
        "name": "replace_in_file",
        "label": "修改文件",
        "description": "精确替换文件中的文本",
        "group": "editing",
        "risk": "修改工作区",
        "default_enabled": True,
    },
    {
        "name": "run_command",
        "label": "运行命令",
        "description": "在工作区执行受控命令",
        "group": "command",
        "risk": "部分命令需确认",
        "default_enabled": True,
    },
)
ALL_TOOL_NAMES = frozenset(str(item["name"]) for item in TOOL_CATALOG)


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    enabled_tools: tuple[str, ...]
    skills: tuple[dict[str, Any], ...] = ()
    legacy: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled_tools": list(self.enabled_tools),
            "skills": [
                {key: value for key, value in skill.items() if key != "instructions"}
                for skill in self.skills
            ],
            "legacy": self.legacy,
        }


def validate_tool_names(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(names))
    unknown = sorted(set(unique) - ALL_TOOL_NAMES)
    if unknown:
        raise ValueError(f"未知工具: {', '.join(unknown)}")
    return tuple(name for name in (str(item["name"]) for item in TOOL_CATALOG) if name in unique)


def compose_system_prompt(
    base: str, snapshot: CapabilitySnapshot, *, max_chars: int = 40_000
) -> str:
    tools = "、".join(snapshot.enabled_tools) or "无（仅聊天模式）"
    sections = [base, f"本轮允许使用的工具：{tools}。不得尝试调用未启用工具。"]
    for skill in sorted(snapshot.skills, key=lambda item: str(item["name"])):
        sections.append(
            f'<skill name="{skill["name"]}" version="{skill["version"]}">\n'
            f"{skill['instructions']}\n</skill>"
        )
    result = "\n\n".join(sections)
    if len(result) > max_chars:
        raise ValueError("已启用 Skill 的指令总长度超过限制")
    return result
