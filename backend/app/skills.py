"""本地 SKILL.md 的安全加载。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.capabilities import validate_tool_names


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)
    required_tools: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)

    @field_validator("version", mode="before")
    @classmethod
    def normalize_version(cls, value: Any) -> str:
        return str(value)


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    path: str
    name: str
    description: str
    version: str
    required_tools: tuple[str, ...]
    recommended_tools: tuple[str, ...]
    instructions: str
    digest: str


def load_skill(directory: str | Path, *, max_chars: int = 30_000) -> LoadedSkill:
    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Skill 路径必须是目录")
    raw_source = root / "SKILL.md"
    if raw_source.is_symlink():
        raise ValueError("SKILL.md 不能是符号链接")
    source = raw_source.resolve(strict=True)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("SKILL.md 不能通过符号链接指向目录外") from exc
    if not source.is_file():
        raise ValueError("Skill 目录必须包含普通文件 SKILL.md")
    text = source.read_text(encoding="utf-8")
    if len(text) > max_chars:
        raise ValueError("SKILL.md 内容超过限制")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("SKILL.md 缺少 YAML front matter")
    raw, instructions = text[4:].split("\n---\n", 1)
    metadata = SkillMetadata.model_validate(yaml.safe_load(raw) or {})
    required = validate_tool_names(metadata.required_tools)
    recommended = validate_tool_names(metadata.recommended_tools)
    instructions = instructions.strip()
    if not instructions:
        raise ValueError("Skill 指令正文不能为空")
    return LoadedSkill(
        path=str(root),
        name=metadata.name.strip(),
        description=metadata.description.strip(),
        version=metadata.version.strip(),
        required_tools=required,
        recommended_tools=recommended,
        instructions=instructions,
        digest=hashlib.sha256(text.encode()).hexdigest(),
    )
