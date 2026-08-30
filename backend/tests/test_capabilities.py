import asyncio
from pathlib import Path

import pytest

from app.agent.tools import ToolExecutionContext
from app.capabilities import CapabilitySnapshot, compose_system_prompt
from app.persistence import SQLiteRepository
from app.providers.types import ToolCall
from app.skills import load_skill
from app.tools.defaults import build_file_tool_registry


def test_filtered_registry_hides_and_rejects_disabled_tools(tmp_path: Path) -> None:
    registry = build_file_tool_registry(enabled_tools=["read_file"])
    names = [item["function"]["name"] for item in registry.definitions]
    assert names == ["read_file"]
    result = asyncio.run(
        registry.execute(
            ToolCall("forged", "write_file", '{}', {}),
            ToolExecutionContext("run", tmp_path, lambda: False),
        )
    )
    assert result.status == "error"
    assert result.error_type == "unknown_tool"


def test_skill_rejects_symlinked_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "---\nname: linked\ndescription: 不应读取\n---\n\n指令。",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").symlink_to(source)
    with pytest.raises(ValueError, match="符号链接"):
        load_skill(skill_dir)


def test_skill_load_and_run_snapshot_are_frozen(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: 测试 Skill\nversion: 1.0\n"
        "required_tools:\n  - read_file\n---\n\n先读取文件。\n",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "db.sqlite3")
    try:
        project = repository.register_project(workspace)
        conversation = repository.create_conversation(project.id)
        skill = repository.register_skill(load_skill(skill_dir))
        repository.set_conversation_capabilities(conversation.id, ["read_file"], [skill["id"]])
        run = repository.create_run(conversation.id, "分析项目")
        snapshot = repository.get_run_capabilities(run["id"], include_instructions=True)
        assert snapshot.enabled_tools == ("read_file",)
        assert snapshot.skills[0]["name"] == "test-skill"
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: 已更新\nrequired_tools:\n  - read_file\n"
            "---\n\n新的指令。",
            encoding="utf-8",
        )
        repository.register_skill(load_skill(skill_dir))
        assert repository.get_run_capabilities(run["id"]).enabled_tools == ("read_file",)
        assert snapshot.skills[0]["instructions"] == "先读取文件。"
    finally:
        repository.close()


def test_skill_requires_enabled_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: needs-command\ndescription: 需要命令\n"
        "required_tools:\n  - run_command\n---\n\n运行测试。",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "db.sqlite3")
    try:
        conversation = repository.create_conversation(repository.register_project(workspace).id)
        skill = repository.register_skill(load_skill(skill_dir))
        with pytest.raises(ValueError, match="缺少必需工具"):
            repository.set_conversation_capabilities(conversation.id, ["read_file"], [skill["id"]])
    finally:
        repository.close()


def test_prompt_contains_selected_skill() -> None:
    prompt = compose_system_prompt(
        "基础规则",
        CapabilitySnapshot(
            ("read_file",),
            (
                {
                    "name": "review",
                    "version": "1",
                    "instructions": "检查代码",
                    "digest": "x",
                    "required_tools": [],
                },
            ),
        ),
    )
    assert "read_file" in prompt
    assert '<skill name="review"' in prompt
    assert "检查代码" in prompt
